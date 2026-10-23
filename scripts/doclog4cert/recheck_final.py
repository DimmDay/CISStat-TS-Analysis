# scripts/doclog4cert/recheck_final.py
# DOCLOG-4-CERT: финальная самосогласованная перепроверка M05/M06
# текущим (финальным) оракульным корпусом + GREEN x2 протокол.
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
PROTO = Path(__file__).resolve().parent / "protocols"
RENDITIONS = REPO / "apps" / "api" / "document_renditions.py"

MUTANTS = [
    (
        "M05",
        '            envelope = {\n                "schema_version": JSONL_SCHEMA_VERSION,',
        '            envelope = {\n                "schema_version": "dropped",',
    ),
    (
        "M06",
        '    for section in snapshot.sections:\n        for claim in section.get("claims", []):',
        '    for section in reversed(snapshot.sections):\n        for claim in section.get("claims", []):',
    ),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(args: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        [PY, "-m", "pytest", *args, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    return proc.returncode == 0, " | ".join(tail)


def main() -> int:
    report = {"recheck_final": []}
    original = _sha(RENDITIONS)
    text = RENDITIONS.read_text(encoding="utf-8")
    for mid, old, new in MUTANTS:
        assert old in text, mid
        RENDITIONS.write_text(text.replace(old, new, 1), encoding="utf-8")
        try:
            repo_ok, repo_tail = _run(["tests/api/test_doclog4_document_delivery.py"])
            oracle_args = ["scripts/doclog4cert/", "--deselect",
                           "scripts/doclog4cert/test_doclog4cert_oracle_api.py::TestOrcRedDefectProofs"]
            oracle_ok, oracle_tail = _run(oracle_args)
        finally:
            subprocess.run(["git", "checkout", "--", "apps/api/document_renditions.py"],
                           cwd=REPO, capture_output=True, text=True)
            assert _sha(RENDITIONS) == original, f"RESTORE-FAIL {mid}"
        rk, ok = not repo_ok, not oracle_ok
        status = ("DUAL-KILLED" if rk and ok else "REPO-ONLY" if rk
                  else "ORACLE-ONLY" if ok else "SURVIVED")
        report["recheck_final"].append({
            "id": mid, "status": status,
            "repo_tail": repo_tail, "oracle_tail": oracle_tail,
        })
        print(f"[{mid}] {status}")
        print("  repo  :", repo_tail[-120:])
        print("  oracle:", oracle_tail[-120:])

    # GREEN x2: 57 green-оракулов (RED-блок deselect) дважды на чистом дереве.
    greens = []
    for i in (1, 2):
        ok, tail = _run(["scripts/doclog4cert/", "--deselect",
                         "scripts/doclog4cert/test_doclog4cert_oracle_api.py::TestOrcRedDefectProofs"])
        greens.append({"run": i, "ok": ok, "tail": tail})
        print(f"GREEN x2 run{i}:", tail[-100:])
    # RED x1: полный корпус с RED-блоком (4 доказательства обязаны падать).
    ok, tail = _run(["scripts/doclog4cert/"])
    report["green_x2"] = greens
    report["red_full_run_tail"] = tail
    print("RED full run:", tail[-160:])
    (PROTO / "recheck_final_protocol.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
