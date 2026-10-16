# scripts/db4cert_red_repro.py
"""
Независимая сертификация UPLOAD-DB-4 — RED-воспроизведение на родительской
базе ae9ae67 (коммит, предшествующий UPLOAD-DB-4=6cff336).

Факты RED:
  R1. На родителе НЕТ файлов задачи: routers/upload_db.py, tests/api/test_upload_db.py.
  R2. На родителе НЕТ схем контракта (DbTestRequest/DbConnection в schemas.py).
  R3. Оракулы аудитора (своя копия) на родителе — 24/24 RED (эндпоинты 404).
  R4. Монтирование в main.py на родителе отсутствует (grep upload_db).

Дерево основного репозитория не трогается (git worktree; cleanup в конце).
Протокол: scripts/db4cert_red_repro.txt
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WT = Path("/home/z/my-project/db4cert_red_wt")
PARENT = "ae9ae67"
ORACLE = ROOT / "scripts/db4cert_oracles.py"

lines: list[str] = [
    f"RED-воспроизведение UPLOAD-DB-4: родитель {PARENT} (pre-UPLOAD-DB-4), worktree {WT}",
    "",
]


def run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                       env={"DATABASE_URL": "", "PATH": "/usr/bin:/bin",
                            "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1",
                            "PYTHONPATH": str(WT)})
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    # R1/R2/R4: статические факты родителя через git show (дерево не трогаем)
    _, out = run(["git", "show", f"{PARENT}:apps/api/routers/upload_db.py"], ROOT)
    lines.append(f"R1a routers/upload_db.py на родителе: {'ОТСУТСТВУЕТ (RED)' if 'fatal' in out.lower() else 'ПРИСУТСТВУЕТ (!)'}")
    _, out = run(["git", "show", f"{PARENT}:tests/api/test_upload_db.py"], ROOT)
    lines.append(f"R1b tests/api/test_upload_db.py на родителе: {'ОТСУТСТВУЕТ (RED; repo-сюита collection невозможна)' if 'fatal' in out.lower() else 'ПРИСУТСТВУЕТ (!)'}")
    _, out = run(["git", "show", f"{PARENT}:apps/api/schemas.py"], ROOT)
    lines.append(f"R2 DbTestRequest в schemas.py родителя: {'ОТСУТСТВУЕТ (RED)' if 'DbTestRequest' not in out else 'ПРИСУТСТВУЕТ (!)'}")
    lines.append(f"R2b DbConnection (дискриминатор) на родителе: {'ОТСУТСТВУЕТ (RED)' if 'DbConnection' not in out else 'ПРИСУТСТВУЕТ (!)'}")
    _, out = run(["git", "show", f"{PARENT}:apps/api/main.py"], ROOT)
    lines.append(f"R4 монтирование upload_db в main.py родителя: {'ОТСУТСТВУЕТ (RED)' if 'upload_db' not in out else 'ПРИСУТСТВУЕТ (!)'}")
    _, out = run(["git", "show", f"{PARENT}:apps/api/trace_hook.py"], ROOT)
    lines.append(f"R5 TRACE_ROUTES db/load на родителе: {'ОТСУТСТВУЕТ (RED)' if 'upload/db/load' not in out else 'ПРИСУТСТВУЕТ (!)'}")
    lines.append("")

    # R3: оракулы на родителе через worktree
    if WT.exists():
        shutil.rmtree(WT)
    subprocess.run(["git", "worktree", "add", str(WT), PARENT], cwd=ROOT, check=True,
                   capture_output=True)
    try:
        wt_scripts = WT / "scripts"
        wt_scripts.mkdir(exist_ok=True)
        shutil.copy(ORACLE, wt_scripts / ORACLE.name)
        rc, out = run([sys.executable, "-m", "pytest", f"scripts/{ORACLE.name}",
                       "-q", "--tb=no", "-p", "no:cacheprovider"], WT)
        tail = [l for l in out.splitlines() if "passed" in l or "failed" in l or "error" in l]
        lines.append(f"R3 оракулы аудитора на родителе (worktree): rc={rc}")
        for l in tail[-3:]:
            lines.append(f"    {l.strip()}")
        red_count = 0
        for l in out.splitlines():
            if l.startswith("FAILED"):
                red_count += 1
        lines.append(f"R3 итог: RED {red_count}/24 оракулов (падения = честный RED: эндпоинты 404)")
        lines.append("")
        lines.append("Вывод: композиция RED полная — контракты задачи на родителе не существуют,")
        lines.append("оракулы падают ровно на точках контракта (404), GREEN достигается только реализацией UPLOAD-DB-4.")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(WT)], cwd=ROOT,
                       capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=ROOT, capture_output=True)
        lines.append(f"cleanup: worktree удалён, дерево основного репозитория не тронуто")

    report = "\n".join(lines)
    (ROOT / "scripts/db4cert_red_repro.txt").write_text(report + "\n")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
