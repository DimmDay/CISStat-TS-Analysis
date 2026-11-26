"""Linux VM: safe worker check/repair using the active pinned Compose inputs.

Run from the repository root. No credentials, digests or raw Docker output are
printed. `repair` is explicit: only a missing key is generated; existing valid
configuration is reused, and revoked/expired/invalid credentials are refused.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time


class OpsError(RuntimeError):
    pass


def ready(health):
    return (health.get("credential_state") in {"present", "registered"}
            and "render" in (health.get("kinds") or [])
            and health.get("worker_ok") is True and health.get("renderer_ok") is True)


class Docker:
    def __init__(self, container, env_file):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
            raise OpsError("invalid_container_name")
        self.container, self.env_file = container, env_file

    def run(self, args, timeout=120):
        env = dict(os.environ)
        for key in ("CISSTAT_WORKER_KEY", "CISSTAT_AUTH_MFA_KEYS", "CISSTAT_AUTH_MFA_ACTIVE_KEY"):
            env.pop(key, None)  # Compose must use its private .env, not stale exports.
        try:
            return subprocess.run(["docker", *args], env=env, capture_output=True,
                                  text=True, encoding="utf-8", timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise OpsError("docker_operation_unavailable") from None

    @staticmethod
    def decode(result):
        try:
            value = json.loads(result.stdout)
            if not isinstance(value, dict): raise ValueError()
            return value
        except (ValueError, TypeError):
            raise OpsError("docker_safe_response_unavailable") from None

    def inspect(self):
        # Select metadata only; never request Config.Env or all inspect fields.
        fmt = ('{"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
               '"files":{{json (index .Config.Labels "com.docker.compose.project.config_files")}},'
               '"image":{{json .Image}}}')
        response = self.run(["inspect", "--format", fmt, self.container])
        if response.returncode: raise OpsError("api_container_unavailable")
        data = self.decode(response)
        if data.get("project") != "cisstat-stack" or not re.fullmatch(r"sha256:[0-9a-f]{64}", data.get("image", "")):
            raise OpsError("unexpected_api_project_or_image")
        raw = data.get("files")
        if not isinstance(raw, str): raise OpsError("missing_compose_labels")
        files = [str(Path(p).resolve()) for p in raw.split(",") if p]
        expected = str(self.env_file.parent / "docker-compose.yml")
        if not files or files[0] != expected or any(not Path(p).is_file() for p in files):
            raise OpsError("active_compose_inputs_unavailable")
        data["files"] = files
        return data

    def compose(self, layout):
        args = ["compose", "--project-directory", str(self.env_file.parent),
                "--env-file", str(self.env_file), "-p", layout["project"]]
        for path in layout["files"]: args += ["-f", path]
        return args

    def health(self):
        code = (
            "import http.client,json; c=http.client.HTTPConnection('127.0.0.1',8000,timeout=4);"
            "c.request('GET','/health/ops');r=c.getresponse();assert r.status==200;"
            "d=json.loads(r.read());w=d.get('worker_credential',{});"
            "q=d.get('document_render_worker',{});p=d.get('print_renderer',{});"
            "print(json.dumps({'credential_state':w.get('state'), 'kinds':w.get('kinds'),"
            "'worker_ok':bool(q.get('running') and q.get('last_run_at') and q.get('consecutive_errors')==0),"
            "'renderer_ok':p.get('readiness',{}).get('ok') is True}))"
        )
        response = self.run(["exec", self.container, "python", "-c", code], timeout=10)
        if response.returncode: raise OpsError("api_health_unavailable")
        return self.decode(response)

    def verify_image(self, layout):
        # Select image names only. Never request a resolved config/env dump.
        result = self.run(self.compose(layout) + ["config", "--images", "api"])
        if result.returncode or result.stdout.split() != [layout["image"]]:
            raise OpsError("active_api_pin_differs_from_compose")

    def ensure(self, layout):
        self.verify_image(layout)
        result = self.run(self.compose(layout) + ["run", "--rm", "--no-deps", "--pull", "never", "-T",
                                                "api", "python", "-m", "apps.api.workers.bootstrap", "ensure"])
        body = self.decode(result)
        return {"state": body.get("state"), "kinds": body.get("kinds")}

    def restart(self, layout):
        self.verify_image(layout)
        result = self.run(self.compose(layout) + ["up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", "api"])
        if result.returncode: raise OpsError("api_recreate_failed")


def append_key(path):
    """Append only the generated setting: do not read/copy existing secrets."""
    if os.name != "posix": raise OpsError("repair_requires_linux_vm")
    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise OpsError("private_env_unavailable_or_symlink") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise OpsError("private_env_not_regular")
        os.fchmod(fd, 0o600)
        original_size = os.fstat(fd).st_size
        # Compose uses the last definition. No previous values are read or returned.
        data = ("\nCISSTAT_WORKER_KEY=cwk_" + secrets.token_urlsafe(32) + "\n").encode()
        try:
            while data:
                written = os.write(fd, data)
                if written <= 0: raise OSError()
                data = data[written:]
            os.fsync(fd)
        except BaseException:
            os.ftruncate(fd, original_size)
            os.fsync(fd)
            raise OpsError("private_env_write_failed") from None
    finally:
        os.close(fd)


def repair(docker, env_file, wait_seconds=45):
    current = docker.health()
    if ready(current): return {"ready": True, "changed": False}
    if current.get("credential_state") != "missing" or not current.get("renderer_ok"):
        raise OpsError("only_missing_credential_can_be_repaired")
    layout = docker.inspect()
    lock = env_file.with_name(env_file.name + ".pgv-worker.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        raise OpsError("operator_lock_unavailable") from None
    try:
        state = docker.ensure(layout)
        if state.get("state") == "missing":
            append_key(env_file)
            state = docker.ensure(layout)
        if state.get("state") not in {"present", "registered"} or "render" not in (state.get("kinds") or []):
            raise OpsError("credential_not_usable_no_automatic_rotation")
        if docker.inspect() != layout: raise OpsError("active_inputs_changed")
        docker.restart(layout)
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                health = docker.health()
                if ready(health):
                    if docker.inspect() != layout: raise OpsError("image_or_inputs_changed")
                    return {"ready": True, "changed": True, "api_image_preserved": True,
                            "ordered_overlays_preserved": True}
            except OpsError as exc:
                if str(exc) != "api_health_unavailable": raise
            time.sleep(1)
        raise OpsError("worker_cycle_not_ready_check_locally")
    finally:
        os.close(fd)
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "repair"])
    parser.add_argument("--api-container", default="cisstat-stack-api-1")
    parser.add_argument("--env-file", type=Path, default=Path("deployment/cisstat-stack/.env"))
    args = parser.parse_args()
    env_file = args.env_file.absolute()
    try:
        docker = Docker(args.api_container, env_file)
        if args.action == "repair": result = repair(docker, env_file)
        else:
            result = docker.health(); result["ready"] = ready(result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("ready") else 2
    except OpsError as exc:
        print(json.dumps({"ready": False, "reason": str(exc)}))
        return 2
    except Exception:
        print(json.dumps({"ready": False, "reason": "operator_check_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
