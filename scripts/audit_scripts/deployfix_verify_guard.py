#!/usr/bin/env python3
# scripts/audit_scripts/deployfix_verify_guard.py
#
# DEPLOY-1: верификация build-гварда apps/api/Dockerfile.
#
# Гвард -- строка RUN в Dockerfile:
#   RUN python -c "from app.core.pipeline_graph import EDA_STAGE_IDS; \
#                  print('pipeline graph OK, EDA nodes from shared JSON:', len(EDA_STAGE_IDS))"
#
# Проверяем в имитации образа (как это исполнит docker на этапе сборки):
#   [A] образ БЕЗ shared/ (состояние до фикса)  -> RUN падает с ImportError
#       «Общий реестр EDA не найден» == инцидент был бы пойман НА СБОРКЕ,
#       а не мёртвым контейнером в проде;
#   [B] образ С shared/ (после фикса)           -> RUN зелёный, печатает
#       количество EDA-узлов из общего JSON.
#
# Гвард вытаскивается ИЗ Dockerfile парсером (не дублируется строкой),
# чтобы тест не разошёлся с реальным RUN.

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "apps" / "api" / "Dockerfile"


def extract_guard_code(dockerfile: Path) -> str:
    """Достать python-код из RUN-гварда DEPLOY-1 (секции между маркерами)."""
    text = dockerfile.read_text(encoding="utf-8")
    m = re.search(
        r"RUN python -c \"(.*?)\"\n", text.replace(" \\\n               ", " "), re.S
    )
    if not m or "EDA_STAGE_IDS" not in m.group(1):
        raise SystemExit("гвард DEPLOY-1 в Dockerfile не найден/изменён -- обнови скрипт")
    return m.group(1)


def build_sim(target: Path, with_shared: bool) -> None:
    dirs = ["app", "validation", "src", "apps/api", "rules"] + (["shared"] if with_shared else [])
    for name in dirs:
        shutil.copytree(REPO / name, target / name, dirs_exist_ok=True)
    (target / "apps" / "__init__.py").parent.mkdir(parents=True, exist_ok=True)
    (target / "apps" / "__init__.py").write_text("", encoding="utf-8")


def run_guard(image_root: Path, code: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(image_root),
        "PYTHONPATH": str(image_root),
        "PYTHONUNBUFFERED": "1",
    }
    return subprocess.run(
        [sys.executable, "-c", code], cwd=str(image_root), env=env,
        capture_output=True, text=True, timeout=180,
    )


def main() -> int:
    code = extract_guard_code(DOCKERFILE)
    print(f"Гвард из Dockerfile: python -c \"{code}\"")

    with tempfile.TemporaryDirectory(prefix="guard-no-shared-") as td:
        root = Path(td) / "app"
        build_sim(root, with_shared=False)
        proc = run_guard(root, code)
        msg = (proc.stderr or "").strip().splitlines()
        tail = msg[-1] if msg else "(пусто)"
        ok = proc.returncode != 0 and "Общий реестр EDA не найден" in (proc.stderr or "")
        print(f"[A] без shared/: exit={proc.returncode}; {tail}")
        print(f"    сборка честно падает на гварде: {'ДА' if ok else 'НЕТ'}\n")
        results = [("no-shared-падает-на-сборке", ok)]

    with tempfile.TemporaryDirectory(prefix="guard-with-shared-") as td:
        root = Path(td) / "app"
        build_sim(root, with_shared=True)
        proc = run_guard(root, code)
        ok = proc.returncode == 0 and "pipeline graph OK" in (proc.stdout or "")
        print(f"[B] с shared/: exit={proc.returncode}; {(proc.stdout or '').strip()}")
        print(f"    гвард зелёный: {'ДА' if ok else 'НЕТ'}\n")
        results.append(("with-shared-зелёный", ok))

    all_ok = all(r[1] for r in results)
    print("VERDICT:", "OK" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
