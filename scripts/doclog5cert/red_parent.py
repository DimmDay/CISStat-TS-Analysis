#!/usr/bin/env python3
"""DOCLOG-5-CERT: RED на родителе (2caf08e) -- оракульный корпус обязан
падать на родительской базе (отсутствие контура DOCLOG-5): ImportError
document_render_worker / HEAVY_RENDITION_FORMATS / отсутствие миграции
0011. Если корпус зелёный на родителе -- он не тестирует DOCLOG-5
(вакуумный корпус -- брак сертификатора)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
PARENT_SHA = "2caf08e"
WORKTREE = Path("/home/z/my-project/cert-red-parent")
CERT_DIR = REPO / "scripts" / "doclog5cert"
PROTOCOLS = CERT_DIR / "protocols"


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "remove", str(WORKTREE), "--force"],
        cwd=REPO, capture_output=True,
    )
    subprocess.run(
        ["git", "worktree", "add", str(WORKTREE), PARENT_SHA],
        cwd=REPO, check=True, capture_output=True,
    )
    # копируем корпус в worktree (родитель его не содержит)
    target = WORKTREE / "scripts" / "doclog5cert"
    shutil.copytree(CERT_DIR, target)
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "scripts/doclog5cert",
            "-q", "--tb=line", "-p", "no:cacheprovider",
        ],
        cwd=WORKTREE, capture_output=True, text=True, timeout=560,
    )
    tail = result.stdout.strip().splitlines()[-8:]
    report = {
        "parent": PARENT_SHA,
        "exit_code": result.returncode,
        "expected": "collection errors / failures (corpus RED)",
        "is_red": result.returncode != 0,
        "tail": tail,
    }
    (PROTOCOLS / "red_parent.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (PROTOCOLS / "red_parent_tail.txt").write_text(
        "\n".join(result.stdout.strip().splitlines()[-25:]),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    subprocess.run(
        ["git", "worktree", "remove", str(WORKTREE), "--force"],
        cwd=REPO, capture_output=True,
    )
    return 0 if report["is_red"] else 1


if __name__ == "__main__":
    sys.exit(main())
