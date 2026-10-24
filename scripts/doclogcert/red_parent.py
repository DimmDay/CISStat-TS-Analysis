# scripts/doclogcert/red_parent.py
"""DOCLOG-CERT: RED на родителе (cc5c14e, pre-DOCLOG) через git-worktree.

Ожидание: сбор корпуса НЕ вакуумный -- collection-ошибки (ImportError
apps.api.identity / doclog-модулей отсутствуют до DOCLOG-0).

Запуск:  python -m scripts.doclogcert.red_parent
Результат: protocols/red_parent_summary.txt + red_parent.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PROTOCOLS = HERE / "protocols"
PY = sys.executable
RED_PARENT = "cc5c14e8c749898daff214d87280d72908a02139"
WORKTREE = Path("/tmp/e2cert-red-parent")


def main() -> None:
    PROTOCOLS.mkdir(exist_ok=True)
    if WORKTREE.exists():
        subprocess.run(["git", "worktree", "remove", "--force",
                        str(WORKTREE)], cwd=REPO_ROOT, capture_output=True)
    subprocess.run(
        ["git", "worktree", "add", str(WORKTREE), RED_PARENT],
        cwd=REPO_ROOT, capture_output=True, check=True,
    )
    # Корпус сертификатора не закоммичен -- копируем его в worktree:
    # pytest собирает ОРАКУЛЫ из чистой базы cc5c14e (родителя DOCLOG-0),
    # продукт которой ещё не содержит doclog-модулей.
    import shutil

    shutil.copytree(
        REPO_ROOT / "scripts" / "doclogcert",
        WORKTREE / "scripts" / "doclogcert",
        ignore=shutil.ignore_patterns("protocols", "__pycache__"),
    )
    started = time.time()
    try:
        proc = subprocess.run(
            [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "scripts/doclogcert"],
            cwd=WORKTREE, capture_output=True, text=True, timeout=600,
        )
    finally:
        subprocess.run(["git", "worktree", "remove", "--force",
                        str(WORKTREE)], cwd=REPO_ROOT, capture_output=True)
    tail = "\n".join(proc.stdout.strip().splitlines()[-25:])
    payload = {
        "parent": RED_PARENT,
        "exit": proc.returncode,
        "seconds": round(time.time() - started, 2),
        "red_is_collection_error": (
            proc.returncode != 0
            and ("error" in proc.stdout.lower())
            and ("passed" not in proc.stdout.splitlines()[-1])
        ),
        "tail": tail,
    }
    (PROTOCOLS / "red_parent.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    (PROTOCOLS / "red_parent_summary.txt").write_text(
        proc.stdout[-4000:], "utf-8")
    print(json.dumps({k: payload[k] for k in
                      ("parent", "exit", "red_is_collection_error")},
                     ensure_ascii=False))
    print(tail)


if __name__ == "__main__":
    main()
