# scripts/doclog4cert/mutations_recheck.py
# DOCLOG-4-CERT: повторный прогон M05/M06 после усиления оракулов
# (урок первой волны: M06 SURVIVED на односекционных данных).
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
PROTO_DIR = Path(__file__).resolve().parent / "protocols"

RENDITIONS = REPO / "apps" / "api" / "document_renditions.py"

MUTANTS = [
    (
        "M05", RENDITIONS,
        '            envelope = {\n                "schema_version": JSONL_SCHEMA_VERSION,',
        '            envelope = {\n                "schema_version": "dropped",',
        "JSONL: envelope теряет schema_version снимка (подмена)",
    ),
    (
        "M06", RENDITIONS,
        '    for section in snapshot.sections:\n        for claim in section.get("claims", []):\n            envelope = {',
        '    for section in reversed(snapshot.sections):\n        for claim in section.get("claims", []):\n            envelope = {',
        "JSONL: порядок секций инвертирован (§7 порядок frozen корпуса)",
    ),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(args: list[str]) -> bool:
    proc = subprocess.run(
        [PY, "-m", "pytest", *args, "-q", "--no-header", "-x", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    return proc.returncode == 0


def main() -> int:
    repo_args = ["tests/api/test_doclog4_document_delivery.py"]
    oracle_args = ["scripts/doclog4cert/", "--deselect",
                   "scripts/doclog4cert/test_doclog4cert_oracle_api.py::TestOrcRedDefectProofs"]
    results = []
    for mid, path, old, new, desc in MUTANTS:
        original = _sha(path)
        text = path.read_text(encoding="utf-8")
        assert old in text, mid
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        try:
            repo_ok = _run(repo_args)
            oracle_ok = _run(oracle_args)
        finally:
            subprocess.run(
                ["git", "checkout", "--", str(path.relative_to(REPO))],
                cwd=REPO, capture_output=True, text=True,
            )
            assert _sha(path) == original, f"RESTORE-FAIL {mid}"
        repo_killed, oracle_killed = not repo_ok, not oracle_ok
        status = (
            "DUAL-KILLED" if repo_killed and oracle_killed
            else "REPO-ONLY" if repo_killed
            else "ORACLE-ONLY" if oracle_killed
            else "SURVIVED"
        )
        results.append({"id": mid, "status": status, "description": desc})
        print(f"[{mid}] {status} -- {desc}", flush=True)
    (PROTO_DIR / "mutations_recheck.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
