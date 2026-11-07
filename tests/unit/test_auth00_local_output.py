"""AUTH-10-HOTFIX01: actionable precommit failure + durable UTF-8 diagnostics."""

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def runner():
    spec = importlib.util.spec_from_file_location(
        "local_gates_output", ROOT / "scripts/local_gates.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LocalOutputTests(unittest.TestCase):
    def test_auth00_checks_prepared_snapshot_before_slow_unit_suite(self):
        mod = runner()
        commands = next(g[3] for g in mod.GATES if g[0] == "auth00")
        self.assertEqual(commands[0][1], "scripts/auth00/check_committed.py")
        self.assertEqual(commands[-1][1], "scripts/auth00/check_committed.py")
        self.assertEqual(
            mod.prepare_commands(commands, "index")[0][-2:], ["--target", "index"]
        )

    def test_failed_step_and_unicode_output_saved_without_losing_exit(self):
        mod = runner()
        with tempfile.TemporaryDirectory() as tmp:
            mod.ROOT = Path(tmp)
            failed = {}
            command = [
                sys.executable,
                "-c",
                "import sys; print('Ошибка: несовпадение INDEX'); sys.exit(7)",
            ]
            with (
                patch.dict(os.environ, {"PYTHONIOENCODING": "cp1251"}),
                redirect_stdout(io.StringIO()) as out,
            ):
                ok, _ = mod.run_gate("auth00", [command], True, failed)
            self.assertFalse(ok)
            self.assertEqual(failed["auth00"]["command"], command)
            log = (mod.ROOT / "logs/local_gates/auth00.log").read_text(encoding="utf-8")
            self.assertIn("Ошибка: несовпадение INDEX", log)
            self.assertIn("exit 7", log)
            self.assertIn("FAILED STEP", out.getvalue())
            self.assertIn("auth00.log", out.getvalue())

    def test_passed_auth00_log_contains_all_steps(self):
        mod = runner()
        with tempfile.TemporaryDirectory() as tmp:
            mod.ROOT = Path(tmp)
            failed = {}
            commands = [
                [sys.executable, "-c", "print('first')"],
                [sys.executable, "-c", "print('second')"],
            ]
            with redirect_stdout(io.StringIO()):
                ok, _ = mod.run_gate("auth00", commands, True, failed)
            self.assertTrue(ok)
            self.assertFalse(failed)
            log = (mod.ROOT / "logs/local_gates/auth00.log").read_text(encoding="utf-8")
            self.assertIn("first", log)
            self.assertIn("second", log)

    def test_summary_repeats_snapshot_failure_and_manual_staging_hint(self):
        mod = runner()
        with tempfile.TemporaryDirectory() as tmp:
            mod.ROOT = Path(tmp)
            checker = mod.ROOT / "scripts/auth00/check_committed.py"
            checker.parent.mkdir(parents=True)
            checker.write_text(
                "print('INDEX mismatch'); raise SystemExit(1)\n", encoding="utf-8"
            )
            index = mod.ROOT / ".git/index"
            index.parent.mkdir()
            index.write_bytes(b"index must not be modified")
            mod.GATES = [
                (
                    "auth00",
                    "fixture",
                    "fixture",
                    [[sys.executable, "scripts/auth00/check_committed.py"]],
                )
            ]
            with (
                patch.object(
                    sys,
                    "argv",
                    ["local_gates.py", "--only", "auth00", "--skip-install"],
                ),
                redirect_stdout(io.StringIO()) as out,
            ):
                self.assertEqual(mod.main(), 1)
            summary = out.getvalue().split("=== СВОДКА ===", 1)[1]
            self.assertIn("FAILED STEP auth00", summary)
            self.assertIn("auth00.log", summary)
            self.assertIn(
                "git add --pathspec-from-file=scripts/auth10/files.txt", summary
            )
            self.assertIn(
                "git add --pathspec-from-file=scripts/auth10/hotfix01/files.txt",
                summary,
            )
            self.assertEqual(index.read_bytes(), b"index must not be modified")

    def test_other_gate_keeps_original_execution_and_creates_no_auth00_log(self):
        mod = runner()
        with tempfile.TemporaryDirectory() as tmp:
            mod.ROOT = Path(tmp)
            with redirect_stdout(io.StringIO()):
                ok, _ = mod.run_gate("rules", [[sys.executable, "-c", "pass"]], True)
            self.assertTrue(ok)
            self.assertFalse((mod.ROOT / "logs/local_gates/auth00.log").exists())


if __name__ == "__main__":
    unittest.main()
