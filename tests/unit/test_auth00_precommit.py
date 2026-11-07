"""Real Git index + real inventory fixtures. No commits or pushes are created."""

import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class PrecommitTests(unittest.TestCase):
    def setUp(self):
        fixtures = module(
            ROOT / "tests/unit/test_auth00_inventory.py", "auth00_fixture"
        )
        self.fixture = fixtures.InventoryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.root = self.fixture.root / "repo с пробелами"
        self.fixture.root.mkdir()
        self.root = self.fixture.root
        # Fixtures must not inherit a GUI's GIT_INDEX_FILE or personal filters.
        self.git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        empty_config = self.root.parent / "empty-gitconfig"
        empty_config.write_text("", encoding="utf-8")
        self.git_env.update(
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(empty_config)
        )
        self.fixture.snapshot_fixture()
        self.fixture.put(
            "scripts/auth00/inventory.py",
            (ROOT / "scripts/auth00/inventory.py").read_text(encoding="utf-8"),
        )
        self.fixture.put(
            "scripts/auth00/check_committed.py",
            (ROOT / "scripts/auth00/check_committed.py").read_text(encoding="utf-8"),
        )
        self.git("init", "--quiet")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            check=True,
            env=self.git_env,
        )

    def refresh(self):
        report = self.fixture.mod.build(self.root)
        self.fixture.put(
            "docs/auth00/inventory.json", self.fixture.mod.json_text(report)
        )
        self.fixture.put("docs/auth00/inventory.md", self.fixture.mod.markdown(report))

    def run_check(self, target="index"):
        return subprocess.run(
            [sys.executable, "scripts/auth00/check_committed.py", "--target", target],
            cwd=self.root,
            env=self.git_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def stage(self):
        self.git("add", "-A")

    def test_staged_before_first_commit_passes_without_changing_index(self):
        self.stage()
        before = self.git("ls-files", "--stage").stdout
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("INDEX", result.stdout)
        self.assertEqual(self.git("ls-files", "--stage").stdout, before)
        self.assertNotEqual(
            subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=self.root,
                env=self.git_env,
                capture_output=True,
                check=False,
            ).returncode,
            0,
        )

    def test_empty_index_is_not_pass(self):
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git add", result.stderr)

    def test_unstaged_guard_change_with_same_routes_fails(self):
        self.stage()
        path = self.root / "apps/api/routers/demo.py"
        path.write_bytes(path.read_bytes().replace(b"return False", b"return True"))
        self.refresh()
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("apps/api/routers/demo.py", result.stderr)

    def test_partially_staged_source_with_old_inventory_fails(self):
        self.stage()
        path = self.root / "apps/api/routers/demo.py"
        path.write_bytes(path.read_bytes().replace(b"return False", b"return True"))
        self.refresh()
        self.git("add", "apps/api/routers/demo.py")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("INDEX", result.stderr)

    def test_untracked_reviewed_helper_cannot_be_left_out(self):
        self.fixture.put("apps/api/helper.py", "def decision(): return False\n")
        self.refresh()
        self.stage()
        self.git("rm", "--cached", "apps/api/helper.py")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("INDEX", result.stderr)

    def test_ignored_page_still_blocks_pass(self):
        self.fixture.put(".gitignore", "logs/\n")
        self.fixture.put(
            "apps/embedded/next.config.mjs",
            'const rules = [{source: "/api/:path*", destination: `https://api.example/v1/:path*`}];\n',
        )
        self.fixture.put(
            "apps/embedded/app/admin/logs/page.tsx",
            "export default function Page(){return null;}\n",
        )
        import json

        review_path = self.root / "docs/auth00/policy_review.json"
        review = json.loads(review_path.read_text())
        for e in self.fixture.mod.discovery(self.root):
            review["entries"].setdefault(
                e["id"],
                {
                    "policy": "fixture",
                    "stage": "platform",
                    "stage_namespace": "service",
                    "resource": "fixture",
                    "effects": ["read"],
                    "canonical_operation": e["operation"],
                    "admission": "fixture",
                },
            )
        self.fixture.put("docs/auth00/policy_review.json", json.dumps(review))
        self.refresh()
        self.stage()
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("page:embedded:/admin/logs", result.stderr)

    def test_crlf_worktree_matches_lf_index(self):
        self.git("config", "core.autocrlf", "true")
        self.stage()
        for p in self.root.rglob("*"):
            if (
                p.is_file()
                and ".git" not in p.parts
                and p.suffix in (".py", ".md", ".json")
            ):
                p.write_bytes(
                    p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                )
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_head_does_not_silently_fall_back_to_index(self):
        self.stage()
        result = self.run_check("head")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD", result.stderr)

    def test_local_gate_target_is_explicit_and_does_not_mutate_commands(self):
        gates = module(ROOT / "scripts/local_gates.py", "auth00_local_gates")
        commands = [[sys.executable, "scripts/auth00/check_committed.py"]]
        actual = gates.prepare_commands(commands, "index")
        self.assertEqual(actual[0][-2:], ["--target", "index"])
        self.assertEqual(
            commands, [[sys.executable, "scripts/auth00/check_committed.py"]]
        )
        self.assertEqual(
            gates.prepare_commands(commands, "head")[0][-2:], ["--target", "head"]
        )


if __name__ == "__main__":
    unittest.main()
