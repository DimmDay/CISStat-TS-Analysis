"""Operator remediation must not expose keys or replace pinned Compose inputs."""
import contextlib
import io
import json
import subprocess
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.pgv_png_ops import worker_ops as ops


class FakeDocker:
    def __init__(self, states=("missing", "registered"), health=None):
        self.states = iter(states); self.calls = []; self.restarted = False
        self.initial = health or {"credential_state": "missing", "kinds": [], "worker_ok": False, "renderer_ok": True}
    def inspect(self):
        return {"project": "cisstat-stack", "files": ["/base/docker-compose.yml", "/release/stack.json"], "image": "sha256:" + "1" * 64}
    def health(self):
        return {"credential_state": "present", "kinds": ["render"], "worker_ok": True, "renderer_ok": True} if self.restarted else self.initial
    def ensure(self, layout):
        self.calls.append(("ensure", layout))
        return {"state": next(self.states), "kinds": ["render"]}
    def restart(self, layout):
        self.calls.append(("restart", layout)); self.restarted = True


@unittest.skipUnless(os.name == "posix", "repair operates on Linux VM file permissions")
class WorkerRepairTests(unittest.TestCase):
    def test_repair_appends_secret_privately_preserves_other_settings_and_pins(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".env"; old = b"OTHER_SECRET=keep-private\nCISSTAT_WORKER_KEY=\n"; path.write_bytes(old)
            docker = FakeDocker(); output = io.StringIO(); key = "cwk_" + "A" * 43
            with patch.object(ops.secrets, "token_urlsafe", return_value="A" * 43), contextlib.redirect_stdout(output):
                result = ops.repair(docker, path, wait_seconds=1)
            self.assertTrue(result["ready"])
            self.assertEqual(path.read_bytes(), old + ("\nCISSTAT_WORKER_KEY=" + key + "\n").encode())
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            self.assertNotIn(key, output.getvalue()); self.assertNotIn("keep-private", output.getvalue())
            self.assertEqual(docker.calls[-1], ("restart", docker.inspect()))
            self.assertEqual([x[0] for x in docker.calls], ["ensure", "ensure", "restart"])
    def test_existing_env_credential_is_reused_without_rotation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".env"; old=b"CISSTAT_WORKER_KEY=already-private\n"; path.write_bytes(old)
            docker=FakeDocker(states=("present",))
            ops.repair(docker, path, wait_seconds=1)
            self.assertEqual(path.read_bytes(), old)
    def test_revoked_invalid_or_expired_credentials_are_not_reactivated(self):
        for state in ["revoked", "expired", "invalid", "error"]:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as d:
                path=Path(d)/".env"; path.write_text("PRIVATE=keep\n")
                docker=FakeDocker(states=(state,))
                with self.assertRaises(ops.OpsError): ops.repair(docker, path, wait_seconds=1)
                self.assertEqual(path.read_text(), "PRIVATE=keep\n");self.assertFalse(docker.restarted)
    def test_ready_is_idempotent_and_symlink_env_is_rejected(self):
        ready={"credential_state":"present","kinds":["render"],"worker_ok":True,"renderer_ok":True}
        self.assertTrue(ops.repair(FakeDocker(health=ready), Path("unused"))["ready"])
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"private"; target.write_text("PRIVATE=keep\n")
            link=Path(d)/".env";link.symlink_to(target)
            with self.assertRaises(ops.OpsError):ops.append_key(link)
            self.assertEqual(target.read_text(),"PRIVATE=keep\n")

    def test_failed_append_rolls_back_without_reading_previous_values(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/".env";old=b"OTHER_PRIVATE=keep\n";path.write_bytes(old)
            write=os.write;calls=[]
            def partial(fd,data):
                if calls:raise OSError("simulated full disk")
                calls.append(True);return write(fd,data[:5])
            with patch.object(ops.os,"write",side_effect=partial):
                with self.assertRaises(ops.OpsError):ops.append_key(path)
            self.assertEqual(path.read_bytes(),old)

    def test_docker_uses_ordered_overlays_and_scrubs_shell_overrides(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            docker=ops.Docker("cisstat-stack-api-1",Path(d)/".env")
            layout=FakeDocker().inspect()
            with patch.dict(os.environ,{"CISSTAT_WORKER_KEY":"never-in-argv","CISSTAT_AUTH_MFA_KEYS":"never-printed"}), \
                 patch.object(ops.secrets,"token_hex",return_value="abcd"), \
                 patch.object(ops.subprocess,"run",side_effect=[
                     subprocess.CompletedProcess([],0,layout["image"]+"\n",""),
                     subprocess.CompletedProcess([],0,"cisstat-pgv-api-pin-probe:abcd\n",""),
                     subprocess.CompletedProcess([],0,"",""),
                 ]) as run:
                docker.restart(layout)
            args=run.call_args.args[0]
            self.assertEqual([args[i+1] for i,x in enumerate(args) if x=="-f"],layout["files"])
            self.assertIn("--no-build",args);self.assertIn("never",args);self.assertEqual(args[-1],"api")
            self.assertNotIn("CISSTAT_WORKER_KEY",run.call_args.kwargs["env"])

    def test_changed_compose_image_is_refused_before_container_operation(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            docker=ops.Docker("cisstat-stack-api-1",Path(d)/".env")
            with patch.object(ops.secrets,"token_hex",return_value="abcd"), \
                 patch.object(ops.subprocess,"run",side_effect=[
                     subprocess.CompletedProcess([],0,"sha256:"+"2"*64,""),
                     subprocess.CompletedProcess([],0,"cisstat-pgv-api-pin-probe:abcd\n",""),
                 ]) as run:
                with self.assertRaisesRegex(ops.OpsError,"active_api_pin_differs"):
                    docker.restart(FakeDocker().inspect())
            self.assertEqual(run.call_count,2)
            self.assertEqual(run.call_args.args[0][-3:],["config","--images","api"])


class ComposeImagePinTests(unittest.TestCase):
    LIVE = "sha256:" + "1" * 64
    OTHER = "sha256:" + "2" * 64

    def check_images(self, api, deps, *, fail_at=None, action="verify_image"):
        docker = ops.Docker("cisstat-stack-api-1", Path("/base/.env"))
        calls = []; probes = []
        def run(args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                images = [api, *deps]
            elif len(calls) == 2:
                last_file = Path(args[max(i for i,a in enumerate(args) if a == "-f") + 1])
                probes.append(last_file)
                model = json.loads(last_file.read_text())
                self.assertEqual(set(model), {"services"})
                self.assertEqual(set(model["services"]), {"api"})
                self.assertEqual(set(model["services"]["api"]), {"image"})
                images = [*reversed(deps), model["services"]["api"]["image"]]
            else:
                self.fail("image preflight must not mutate Docker")
            self.assertEqual(args[-3:], ["config", "--images", "api"])
            self.assertEqual([args[i+1] for i,a in enumerate(args) if a == "-f"][:2], FakeDocker().inspect()["files"])
            return subprocess.CompletedProcess([], 1 if fail_at == len(calls) else 0,
                                               "\n".join(images)+"\n", "private diagnostic withheld")
        try:
            with patch.object(docker, "run", side_effect=run):
                getattr(docker, action)(FakeDocker().inspect())
        finally:
            self.assertTrue(all(not p.exists() for p in probes), "temporary probe must be removed")
        return calls

    def test_operator_vm_api_and_postgres_images_are_valid(self):
        calls = self.check_images(self.LIVE, ["postgres:16"])
        self.assertEqual(len(calls), 2)

    def test_api_image_can_be_repeated_by_a_dependency(self):
        self.check_images(self.LIVE, [self.LIVE, "postgres:16"])

    def test_live_image_only_on_dependency_does_not_hide_changed_api(self):
        with self.assertRaisesRegex(ops.OpsError, "active_api_pin_differs_from_compose"):
            self.check_images(self.OTHER, [self.LIVE, "postgres:16"], action="restart")

    def test_actual_command_and_probe_failure_are_distinct_from_mismatch(self):
        for step in [1, 2]:
            with self.subTest(step=step), self.assertRaisesRegex(ops.OpsError, "compose_image_check_unavailable"):
                self.check_images(self.LIVE, ["postgres:16"], fail_at=step)

    def test_single_image_is_still_supported(self):
        self.check_images(self.LIVE, [])

    def test_bootstrap_does_not_receive_the_probe_overlay(self):
        docker = ops.Docker("cisstat-stack-api-1", Path("/base/.env"))
        layout = FakeDocker().inspect()
        calls = []
        probe_paths = []
        def run(args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                text = self.LIVE + "\npostgres:16\n"
            elif len(calls) == 2:
                path = Path(args[max(i for i,a in enumerate(args) if a == "-f") + 1])
                probe_paths.append(path)
                text = "postgres:16\n" + json.loads(path.read_text())["services"]["api"]["image"]
            else:
                self.assertEqual([args[i+1] for i,a in enumerate(args) if a == "-f"], layout["files"])
                self.assertTrue(all(not p.exists() for p in probe_paths))
                self.assertEqual(args[-5:], ["api", "python", "-m", "apps.api.workers.bootstrap", "ensure"])
                text = json.dumps({"state": "registered", "kinds": ["render"]})
            return subprocess.CompletedProcess([], 0, text, "")
        with patch.object(docker, "run", side_effect=run):
            self.assertEqual(docker.ensure(layout)["state"], "registered")
        self.assertEqual(len(calls), 3)
