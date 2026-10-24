# scripts/doclog9cert/red_parent.py
"""DOCLOG-9-CERT: RED корпуса на РОДИТЕЛЕ поставки DOCLOG-9.

Родитель 06b920c -- 659db3d (DOCLOG-7-CERT). Корпус через git-worktree
на родителе обязан падать при СБОРКЕ (import apps.api.doc_profiles) --
доказательство, что корпус не вакуумный: тестирует именно поверхность
DOCLOG-9.

Запуск:  /home/z/.venv/bin/python -m scripts.doclog9cert.red_parent
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PROTOCOLS = HERE / "protocols"
PY = sys.executable
WORKTREE = Path("/tmp/d9cert-red-parent")


def main() -> None:
    PROTOCOLS.mkdir(exist_ok=True)
    target = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
        capture_output=True, text=True,
    ).stdout.strip()
    parent = subprocess.run(
        ["git", "rev-parse", "--short", "06b920c^"], cwd=REPO_ROOT,
        capture_output=True, text=True,
    ).stdout.strip()
    if WORKTREE.exists():
        subprocess.run(["git", "worktree", "remove", "--force",
                        str(WORKTREE)], cwd=REPO_ROOT, capture_output=True)
    add = subprocess.run(
        ["git", "worktree", "add", str(WORKTREE), parent],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert add.returncode == 0, add.stderr
    try:
        # Копируем корпус сертификатора в worktree (корпуса нет в родителе).
        dst = WORKTREE / "scripts" / "doclog9cert"
        dst.mkdir(parents=True, exist_ok=True)
        for src_file in HERE.glob("*.py"):
            (dst / src_file.name).write_text(
                src_file.read_text("utf-8"), "utf-8"
            )
        started = time.time()
        proc = subprocess.run(
            [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "scripts/doclog9cert"],
            cwd=WORKTREE, capture_output=True, text=True, timeout=600,
        )
        elapsed = round(time.time() - started, 2)
        tail = "\n".join(proc.stdout.strip().splitlines()[-15:])
        payload = {
            "target_head": target,
            "parent": parent,
            "exit": proc.returncode,
            "seconds": elapsed,
            "summary": proc.stdout.strip().splitlines()[-1] if proc.stdout else "?",
            "tail": tail,
        }
        verdict = (
            proc.returncode != 0
            and ("ModuleNotFoundError" in proc.stdout
                 or "No module named" in proc.stdout
                 or "ImportError" in proc.stdout)
            and "doc_profiles" in proc.stdout
        )
        payload["RED"] = bool(verdict)
        (PROTOCOLS / "red_parent.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            "utf-8",
        )
        (PROTOCOLS / "red_parent.txt").write_text(proc.stdout[-12000:], "utf-8")
        print(json.dumps({k: payload[k] for k in
                          ("target_head", "parent", "exit", "seconds",
                           "summary", "RED")}, ensure_ascii=False))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force",
                        str(WORKTREE)], cwd=REPO_ROOT, capture_output=True)


if __name__ == "__main__":
    main()
