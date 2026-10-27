"""Documentation acceptance checks; these do not certify an auth implementation."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
ARCH = ROOT / "spec_auth_architecture.md"
ROLES = ROOT / "docs/ROLES_AND_PLANS_SPEC.md"


class DocumentationContract(unittest.TestCase):
    def setUp(self):
        self.arch = ARCH.read_text() if ARCH.exists() else ""
        self.roles = ROLES.read_text()

    def test_verified_source_and_status(self):
        self.assertIn("ad7dd4b3bcafcccb64d9f5b2f0a97afac7fc965f", self.arch)
        self.assertIn("не является реализацией", self.arch)

    def test_three_specifications_reconciled(self):
        for name in ("spec_auth.md", "spec_billing_accounts.md", "docs/ROLES_AND_PLANS_SPEC.md"):
            self.assertIn(name, self.arch)
        for decision in range(1, 15):
            self.assertIn(f"RP-{decision:02}", self.roles)
            self.assertIn(f"RP-{decision:02}", self.arch)

    def test_task_dependency_graph_and_acceptance(self):
        rows = [line.split("|")[1:-1] for line in self.arch.splitlines()
                if re.match(r"\| AUTH-(?:\d\d|CERT) \|", line)]
        self.assertGreaterEqual(len(rows), 20)
        ids = [row[0].strip() for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        completed = set()
        for row in rows:
            self.assertEqual(len(row), 5, row)
            for dep in re.findall(r"AUTH-(?:\d\d|CERT)", row[1]):
                self.assertIn(dep, completed, f"Not topologically sorted: {row[0]} -> {dep}")
            self.assertGreater(len(row[4].strip()), 25)
            completed.add(row[0].strip())
        self.assertIn("AUTH-CERT", completed)

    def test_source_paths_exist(self):
        section = self.arch.split("<!-- SOURCE_PATHS -->")
        self.assertEqual(len(section), 3)
        paths = re.findall(r"`((?:apps|packages|app|tests)/[^`]+)`", section[1])
        self.assertGreaterEqual(len(paths), 15)
        for path in paths:
            self.assertTrue((ROOT / path).exists(), path)

    def test_required_boundaries(self):
        for token in ("SubjectRef", "authorize_run_access", "owner_account_id", "tenant_id",
                      "AuthSession", "cisstat_session_id", "DemoGrant", "SupportGrant",
                      "outbox", "idempotency", "fencing", "402", "404", "503",
                      "can_run_baseline_models", "can_tune_models", "can_train_custom_models"):
            self.assertIn(token, self.arch)

    def test_cross_document_link_and_current_plan_truth(self):
        self.assertIn("../spec_auth_architecture.md", self.roles)
        self.assertIn("can_train_models", self.roles)
        self.assertIn("не реализовано", self.roles)
        self.assertIn("can_use_api", self.roles)

    def test_markdown_structure(self):
        for text in (self.arch, self.roles):
            self.assertEqual(text.count("```") % 2, 0)
            widths = []
            for line in text.splitlines() + [""]:
                if line.startswith("|"):
                    widths.append(line.count("|"))
                elif widths:
                    self.assertEqual(len(set(widths)), 1, widths)
                    widths = []


if __name__ == "__main__":
    unittest.main(verbosity=2)
