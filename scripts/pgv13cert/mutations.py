"""Two-channel check of executable mutants, positive oracle controls only.
Pre-registration: control=both green; each mutation=independent oracle RED.
Repo survival is reported as coverage finding, not hidden by a combined total.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "protocols" / "mutations"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "apps/api/passport_documents.py"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    channels = {
        "repo": ["tests/api/test_pgv13_passport_documents.py"],
        "oracle": ["scripts/pgv13cert/test_contracts.py", "-k", "all_groups_survive or exact_request or valid_renderer"],
    }
    matrix = []
    for mutant in ("control", "drop_group", "wrong_source_hash", "wrong_job_id"):
        row = {"mutant": mutant}
        for channel, selection in channels.items():
            env = {**os.environ, "PGV13_CERT_MUTANT": mutant}
            env.pop("CISSTAT_PGV13_CERT_DSN", None)
            junit = OUT / f"{mutant}-{channel}.xml"
            junit.unlink(missing_ok=True)
            cmd = [sys.executable, "-m", "pytest", "-p", "scripts.pgv13cert.mutator", *selection, "-q", "--basetemp=" + str(ROOT.parent / ("pgv13-mutant-" + mutant + "-" + channel)), "--junitxml=" + str(junit)]
            with (OUT / f"{mutant}-{channel}.txt").open("w", encoding="utf-8") as log:
                run = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            row[channel + "_exit"] = run.returncode
            cases = list(ET.parse(junit).iter("testcase")) if junit.exists() else []
            row[channel + "_counts"] = {
                "tests": len(cases),
                **{kind: sum(case.find(kind) is not None for case in cases)
                   for kind in ("failure", "error", "skipped")},
            }
        matrix.append(row)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    report = {"kind": "subprocess runtime-wrapper mutants", "pre_registered": "control both green; three mutants independent-oracle RED", "source_sha256_before_after": before, "matrix": matrix}
    (OUT / "matrix.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    valid = True
    for row in matrix:
        for channel in channels:
            counts = row[channel + "_counts"]
            valid &= counts["tests"] == (39 if channel == "repo" else 3)
            valid &= counts["error"] == counts["skipped"] == 0
        if row["mutant"] == "control":
            valid &= row["repo_exit"] == row["oracle_exit"] == 0
        else:
            # A collection/setup error or an empty run is not a killed mutant.
            valid &= row["oracle_exit"] == 1 and row["oracle_counts"]["failure"] > 0
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
