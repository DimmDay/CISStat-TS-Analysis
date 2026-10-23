# scripts/doclog4cert/m06_adjudication.py
# DOCLOG-4-CERT: независимая перепроверка вердикта M06 (SURVIVED в recheck).
# Применяет мутанта M06 (reversed(snapshot.sections)) и прогоняет
# оба канала текущими версиями сюит (оракул мог быть усилен ПОСЛЕ recheck).
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
RENDITIONS = REPO / "apps" / "api" / "document_renditions.py"

OLD = (
    "    for section in snapshot.sections\n"
    "        for claim in section.get(\"claims\", []):"
)
OLD = '    for section in snapshot.sections:\n        for claim in section.get("claims", []):'
NEW = '    for section in reversed(snapshot.sections):\n        for claim in section.get("claims", []):'


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(args: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        [PY, "-m", "pytest", *args, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-4:]
    return proc.returncode == 0, " | ".join(tail)


def main() -> int:
    original = _sha(RENDITIONS)
    text = RENDITIONS.read_text(encoding="utf-8")
    assert OLD in text, "M06 marker not found"
    RENDITIONS.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    try:
        repo_ok, repo_tail = _run(["tests/api/test_doclog4_document_delivery.py"])
        oracle_ok, oracle_tail = _run(["scripts/doclog4cert/"])
        full_oracle_ok, full_tail = _run(
            ["scripts/doclog4cert/", "-k", "order_and_text"]
        )
    finally:
        subprocess.run(
            ["git", "checkout", "--", "apps/api/document_renditions.py"],
            cwd=REPO, capture_output=True, text=True,
        )
        assert _sha(RENDITIONS) == original, "RESTORE-FAIL M06"
    print("REPO killed:", not repo_ok, "|", repo_tail)
    print("ORACLE(full incl RED) killed:", not oracle_ok, "|", oracle_tail)
    print("ORACLE(order-test) killed:", not full_oracle_ok, "|", full_tail)
    verdict = (
        "DUAL-KILLED" if (not repo_ok and not oracle_ok)
        else "REPO-ONLY" if not repo_ok
        else "ORACLE-ONLY" if not oracle_ok
        else "SURVIVED"
    )
    print("M06 VERDICT:", verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
