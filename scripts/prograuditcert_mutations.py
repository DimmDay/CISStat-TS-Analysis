"""AUDIT-CERT §19: seven required mutations plus the new rollback defect.

Fresh process per mutant; behavioral assertion failures are required for
a kill. Collection/import/compilation errors never count. All changed
sources are restored byte-for-byte in finally, with SHA256 evidence.
Run from the repository: python scripts/prograuditcert_mutations.py
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
API = "tests/integration/test_progress_audit_cert.py"
UI = "packages/ui/hooks/prograuditcert_delivery.test.tsx"
STORE = "tests/api/test_progress_audit_cert_store.py"


@dataclass
class Mutation:
    name: str
    path: str
    replacements: tuple[tuple[str, str], ...]
    suite: str
    oracle: str


MUTATIONS = [
    Mutation("MC1-reset-reducer", "app/core/effective_target.py", (
        ('        if event_type == _EVENT_TYPE_CLEARED:', '        if False and event_type == _EVENT_TYPE_CLEARED:'),
    ), API, "test_auto_convert_reset_restore_manual_consumers"),
    Mutation("MC2-context-guard", "apps/api/progress_maps.py", (
        ('    if not run_id or envelope.run_id != run_id:', '    if False and (not run_id or envelope.run_id != run_id):'),
        ('    if envelope.context_id != server_context:', '    if False and envelope.context_id != server_context:'),
    ), API, "test_four_maps_form_stale_run_context_duplicate_and_conflict"),
    Mutation("MC3-report-id-dedup", "apps/api/research_runs.py", (
        ('                stored = self._receipts.get(batch.idempotency_key)', '                stored = None  # AUDIT-CERT mutation'),
    ), API, "test_four_maps_form_stale_run_context_duplicate_and_conflict"),
    Mutation("MC4-forecast-identity", "apps/api/routers/progress.py", (
        ('                events.append(canonical)', '                canonical["event_id"] = str(uuid4())\n                events.append(canonical)'),
    ), API, "test_forecast_merge_preserves_id_actor_and_independent_equal_actions"),
    Mutation("MC5-full-projection", "apps/api/routers/progress.py", (
        ('        corpus = canonical_corpus(ledger, layer1, artifacts)', '        corpus = canonical_corpus(layer1, artifacts)'),
    ), API, "test_full_projection_reverse_equal_clocks_forecast_identity"),
    Mutation("MC6-receipt-handling", "packages/ui/hooks/useProgressMapDelivery.ts", (
        ('            if (data && data.mode === "v2" && data.receipt) {', '            if (true) {'),
    ), UI, "CERT receipt: 200 without receipt never claims durable delivery"),
    Mutation("MC7-EDA-protection", "app/core/node_status.py", (
        ('        if context_unchanged:', '        if False and context_unchanged:'),
    ), API, "test_eda_get_remount_pending_seed_failure_and_new_context"),
    Mutation("MC8-outbox-rollback", "apps/api/delivery_outbox.py", (
        ('                self._tasks = previous', '                pass  # rollback deliberately removed'),
    ), STORE, "test_outbox_failure_rolls_back_all_four_surfaces[memory-True]"),
]


def run_oracle(suite, temporary):
    env = dict(os.environ)
    for name in ("DATABASE_URL", "REDIS_URL", "CISSTAT_CERT_LOCAL_PG_DSN", "CISSTAT_TEST_PG_DSN"):
        env.pop(name, None)
    env["TMPDIR"] = str(temporary)
    if suite == UI:
        result_file = temporary / "jest.json"
        proc = subprocess.run(["npx", "jest", "--runInBand", suite, "--json", f"--outputFile={result_file}"],
                              cwd=ROOT, env=env, text=True, capture_output=True, timeout=120)
        report = json.loads(result_file.read_text()) if result_file.exists() else {}
        failures = [a["fullName"] for s in report.get("testResults", [])
                    for a in s.get("assertionResults", []) if a["status"] == "failed"]
        errors = sum(s.get("status") == "failed" and not s.get("assertionResults") for s in report.get("testResults", []))
    else:
        result_file = temporary / "pytest.xml"
        proc = subprocess.run([sys.executable, "-m", "pytest", suite, "-q", "--disable-warnings", f"--junitxml={result_file}"],
                              cwd=ROOT, env=env, text=True, capture_output=True, timeout=120)
        report = ET.parse(result_file).getroot() if result_file.exists() else ET.Element("missing")
        failures = [case.get("name") for case in report.iter("testcase") if case.find("failure") is not None]
        errors = len(list(report.iter("error")))
    return {"exit": proc.returncode, "failures": failures, "errors": errors,
            "tail": (proc.stdout + proc.stderr)[-2500:]}


def main():
    sources = {m.path: (ROOT / m.path).read_bytes() for m in MUTATIONS}
    anchors = {p: hashlib.sha256(data).hexdigest() for p, data in sources.items()}
    results = []
    with tempfile.TemporaryDirectory(prefix="auditcert-mutations-", dir=ROOT.parent) as directory:
        temporary = Path(directory)
        controls = {suite: run_oracle(suite, temporary) for suite in (API, UI, STORE)}
        if any(c["exit"] for c in controls.values()):
            raise RuntimeError("Control channel is not green; mutation campaign cancelled")
        try:
            for mutation in MUTATIONS:
                path = ROOT / mutation.path
                try:
                    code = sources[mutation.path].decode()
                    for old, new in mutation.replacements:
                        if code.count(old) != 1:
                            raise RuntimeError(f"Mutation anchor is not unique: {mutation.name}")
                        code = code.replace(old, new)
                    path.write_text(code)
                    outcome = run_oracle(mutation.suite, temporary)
                    killed = outcome["exit"] == 1 and not outcome["errors"] and any(
                        mutation.oracle in failure for failure in outcome["failures"])
                    results.append({"name": mutation.name, "path": mutation.path,
                                    "oracle": mutation.oracle, "killed": killed, **outcome})
                    print(f"{mutation.name}: {'KILLED by behavioral oracle' if killed else 'NOT KILLED'}", flush=True)
                finally:
                    path.write_bytes(sources[mutation.path])
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == anchors[mutation.path]
        finally:
            for p, data in sources.items():
                (ROOT / p).write_bytes(data)
        restored = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == anchors[p] for p in sources}
        postcontrols = {suite: run_oracle(suite, temporary) for suite in (API, UI, STORE)}
    report = {"base": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "sha256": anchors, "controls": controls, "mutations": results,
              "restored": restored, "postcontrols": postcontrols}
    (ROOT / "scripts/prograuditcert_mutation_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"RESTORE: {all(restored.values())}; KILLED {sum(r['killed'] for r in results)}/{len(results)}")
    return 0 if all(r["killed"] for r in results) and all(restored.values()) and not any(c["exit"] for c in postcontrols.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
