# scripts/doclog1cert/red_repro.py
"""DOCLOG-1-CERT: RED-протокол на родителе fb26f6f через git worktree.

Факт, который доказывает RED: оракулы сертификатора проверяют ИМЕННО
контур DOCLOG-1 -- на родительской базе (без artifact_store.py /
artifact_promotion.py / миграции 0007 / artifacts-блока health) корпус
НЕ может быть зелёным. Классы:
  - collection-error (unit-файл: импорт отсутствующих модулей);
  - runtime-RED (API-файл: нет PromotionService/artifacts-блока);
  - честно-зелёные пины (проверки прежнего контракта, GREEN на обеих
    базах: базлайн keeper'а «последних пяти», форма /health/ops).

Worktree выбрасывается после прогона; продуктовый код не меняется.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PARENT_COMMIT = "fb26f6f"
WORKTREE = REPO_ROOT.parent / "cisstat-parent-fb26f6f"
OUT = Path(__file__).resolve().parent / "red_repro_protocol.txt"


def main() -> int:
    if WORKTREE.exists():
        shutil.rmtree(WORKTREE)
    subprocess.run(
        ["git", "worktree", "add", str(WORKTREE), PARENT_COMMIT],
        cwd=REPO_ROOT, check=True, capture_output=True,
    )
    try:
        # оракулы копируются в worktree: rootdir/pytest.ini родителя,
        # apps.api -- родительский (fb26f6f)
        shutil.copytree(Path(__file__).resolve().parent, WORKTREE / "scripts" / "doclog1cert")
        env = {"PATH": "/usr/bin:/bin", "DATABASE_URL": ""}
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "scripts/doclog1cert",
             "-q", "--no-header", "-p", "no:cacheprovider",
             "--continue-on-collection-errors"],
            cwd=WORKTREE, capture_output=True, text=True, timeout=1200,
        )
        OUT.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        print((proc.stdout + proc.stderr)[-3000:])
        return proc.returncode
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(WORKTREE)],
            cwd=REPO_ROOT, capture_output=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())
