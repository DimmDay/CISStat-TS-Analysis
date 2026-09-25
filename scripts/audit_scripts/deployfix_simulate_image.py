#!/usr/bin/env python3
# scripts/audit_scripts/deployfix_simulate_image.py
#
# Задача DEPLOY-1 (2026-09-25): доказательство root cause ошибки рендера
#   ImportError: Общий реестр EDA не найден: /app/shared/pipeline_nodes/eda_checks.json
#               (§12 п.2); файл обязателен для старта графа пайплайна
#
# Скрипт воспроизводит сборку Docker-образа apps/api БЕЗ запуска docker:
# 1) парсит COPY-инструкции apps/api/Dockerfile;
# 2) копирует перечисленные каталоги во временный "образ" (<tmp>/app-имитация);
# 3) повторяет `RUN touch apps/__init__.py`;
# 4) запускает в subprocess (чистый sys.path, cwd=имитация /app) ТОТ ЖЕ импорт,
#    что делает uvicorn на старте: apps.api.main (через него цепочка
#    trace_hook -> app.core.pipeline_graph -> module-level чтение JSON §12 п.2).
#
# Сценарии:
#   base      -- образ как в HEAD ДО фикса (без shared/)  -> ожидаем ТОЧНО ошибку рендера;
#   fixed     -- + COPY shared/ и build-гвард             -> ожидаем чистый импорт.
#
# Вывод: печатает verdict по каждому сценарию; exit 0, если поведение
# совпало с ожидаемым (base упал с искомой ошибкой, fixed -- зелёный).

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "apps" / "api" / "Dockerfile"

EXPECTED_MSG_SUBSTR = "Общий реестр EDA не найден"
EXPECTED_PATH_SUBSTR = "shared/pipeline_nodes/eda_checks.json"


def parse_copy_dirs(dockerfile: Path) -> list[str]:
    """Извлечь исходные каталоги из COPY-инструкций (только dir -> dir)."""
    dirs: list[str] = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^COPY\s+(\S+)/\s+\./\S*/$", line.strip())
        if m:
            dirs.append(m.group(1))
    return dirs


def build_image_sim(target_root: Path, extra_dirs: list[str] | None = None) -> list[str]:
    """Собрать имитацию образа: только то, что COPY-ит Dockerfile (+extra)."""
    copy_dirs = parse_copy_dirs(DOCKERFILE)
    for name in copy_dirs + (extra_dirs or []):
        src = REPO / name
        dst = target_root / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
    # RUN touch apps/__init__.py -- реплицируем слой образа.
    (target_root / "apps" / "__init__.py").write_text("", encoding="utf-8")
    return copy_dirs


def run_uvicorn_import(image_root: Path) -> subprocess.CompletedProcess:
    """Тот же контракт, что CMD образа: импорт apps.api.main (uvicorn)."""
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "PYTHONPATH": str(image_root),
        "PYTHONUNBUFFERED": "1",
        "HOME": str(image_root),
    }
    code = "from apps.api.main import app; print('IMPORT_OK')  # uvicorn apps.api.main:app"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(image_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def main() -> int:
    print(f"Dockerfile: {DOCKERFILE}")
    print(f"HEAD COPY-каталоги: {parse_copy_dirs(DOCKERFILE)}\n")

    results: list[tuple[str, bool, str]] = []

    # ── Сценарий A: образ ДО фикса (только COPY из Dockerfile) ────────
    with tempfile.TemporaryDirectory(prefix="img-base-") as td:
        root = Path(td) / "app"
        dirs = build_image_sim(root)
        proc = run_uvicorn_import(root)
        tail = (proc.stderr or "").strip().splitlines()
        tail_msg = tail[-1] if tail else "(пусто)"
        matched = (
            proc.returncode != 0
            and EXPECTED_MSG_SUBSTR in (proc.stderr or "")
            and EXPECTED_PATH_SUBSTR in (proc.stderr or "")
        )
        print(f"[A] БАЗА (COPY без shared/, как в HEAD): dirs={dirs}")
        print(f"    exit={proc.returncode}; последняя строка stderr:")
        print(f"      {tail_msg}")
        print(f"    совпадение с ошибкой render.com: {'ДА' if matched else 'НЕТ'}\n")
        results.append(("base-падает-с-искомой-ошибкой", matched, tail_msg))

    # ── Сценарий B: образ ПОСЛЕ фикса (COPY + shared/) ────────────────
    with tempfile.TemporaryDirectory(prefix="img-fixed-") as td:
        root = Path(td) / "app"
        dirs = build_image_sim(root, extra_dirs=["shared"])
        proc = run_uvicorn_import(root)
        ok = proc.returncode == 0 and "IMPORT_OK" in (proc.stdout or "")
        print(f"[B] ФИКС (COPY + shared/): dirs={dirs}")
        print(f"    exit={proc.returncode}; stdout: {(proc.stdout or '').strip()}")
        if not ok:
            print("    stderr tail:")
            for ln in (proc.stderr or "").strip().splitlines()[-5:]:
                print(f"      {ln}")
        print(f"    импорт приложения зелёный: {'ДА' if ok else 'НЕТ'}\n")
        results.append(("fixed-импорт-зелёный", ok, ""))

    all_ok = all(r[1] for r in results)
    print("VERDICT:", "ПОДТВЕРЖДЕНО" if all_ok else "НЕ ПОДТВЕРЖДЕНО",
          "|", "; ".join(f"{n}={'OK' if ok else 'FAIL'}" for n, ok, _ in results))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
