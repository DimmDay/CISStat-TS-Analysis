# scripts/doclog8cert/consolidate.py
"""DOCLOG-8-CERT: консолидация протоколов мутационной кампании из
mut_*.json в единый mutations_summary.json с пересчётом MV1/MV2/MV3/MV5
(байт-в-байт md5 продуктового дерева сверяется с git HEAD)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.doclog8cert.mutations import (  # noqa: E402
    MUTANTS, mv1_dry_run, self_test_classifier,
)


def git_head_md5(file_rel: str) -> str:
    blob = subprocess.run(
        ["git", "show", f"HEAD:{file_rel}"], cwd=REPO_ROOT,
        capture_output=True,
    ).stdout
    return hashlib.md5(blob).hexdigest()


def main() -> None:
    entries = []
    for mutant in MUTANTS:
        path = HERE / "protocols" / f"mut_{mutant['id']}.json"
        entry = json.loads(path.read_text("utf-8"))
        # MV3-финал: текущее md5 файла == git HEAD md5.
        entry["restore_ok"] = (
            hashlib.md5((REPO_ROOT / mutant["file"]).read_bytes()).hexdigest()
            == git_head_md5(mutant["file"])
        )
        entries.append(entry)

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    channel_files = {
        "repo": {"test_doclog8_monitoring.py",
                 "test_doclog2_snapshots.py",
                 "test_doclog6_approvals_archive.py"},
        "oracle": {"conftest.py", "test_d8cert_oracle_unit.py",
                   "test_d8cert_oracle_api.py",
                   "test_d8cert_oracle_static.py"},
    }
    tail_scan = []
    for entry in entries:
        if entry.get("control") or entry["status"] in ("ALIVE",
                                                       "PATCH-FAIL"):
            continue
        for channel in ("repo", "oracle"):
            for line in entry.get(f"{channel}_tail", "").splitlines():
                if ((line.startswith("FAILED") or line.startswith("ERROR"))
                        and "::" in line):
                    fname = Path(line.split()[1].split("::")[0]).name
                    if fname not in channel_files[channel]:
                        tail_scan.append({"id": entry["id"],
                                          "channel": channel,
                                          "foreign": fname})

    problems = mv1_dry_run()
    summary = {
        "campaign": "DOCLOG-8-CERT mutations",
        "mv1_anchor_problems": problems,
        "mv1_ok": not problems,
        "mv2_classifier_self_test": self_test_classifier(),
        "mv3_all_restored_head_md5": all(
            e.get("restore_ok", False) for e in entries
        ),
        "mv5_foreign_tails": tail_scan,
        "counts": counts,
        "mutants": entries,
    }
    out = HERE / "protocols" / "mutations_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                   "utf-8")
    print(json.dumps(counts, ensure_ascii=False))
    print("MV1:", "OK" if not problems else problems)
    print("MV2:", summary["mv2_classifier_self_test"])
    print("MV3:", summary["mv3_all_restored_head_md5"])
    print("MV5:", tail_scan or "clean")


if __name__ == "__main__":
    main()
