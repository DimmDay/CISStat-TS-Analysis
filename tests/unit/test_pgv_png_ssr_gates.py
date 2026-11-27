"""Keep native PostgreSQL optional and forbid a missing-DSN false PASS."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SsrGateTests(unittest.TestCase):
    def cli(self, *args):
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        env.pop("CISSTAT_AUTH_TEST_DSN", None)
        return subprocess.run([sys.executable, "scripts/local_gates.py", *args], cwd=ROOT,
                              env=env, text=True, encoding="utf-8", capture_output=True)

    def test_native_not_default_but_explicit_flag_selects_it(self):
        default = self.cli("--list")
        self.assertEqual(default.returncode, 0, default.stderr)
        rows = {line.split("<-")[0].strip(): line for line in default.stdout.splitlines() if "<-" in line}
        self.assertIn("* pgv-png-ssr", rows)
        self.assertIn("pgv-png-ssr-postgres", rows)
        enabled = self.cli("--list", "--with-pgv-png-ssr-postgres")
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        self.assertTrue(any(line.strip().startswith("* pgv-png-ssr-postgres") for line in enabled.stdout.splitlines()))

    def test_missing_native_dsn_is_a_failed_gate(self):
        result = self.cli("--only", "pgv-png-ssr-postgres", "--skip-install")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("no tests ran", result.stdout + result.stderr)
        self.assertIn("FAIL", result.stdout)


if __name__ == "__main__":
    unittest.main()
