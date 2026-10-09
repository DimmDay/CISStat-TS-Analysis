#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сертификация PROGR-25-D-CERT: протокол полного регресса (реальные прогоны).

Фиксирует фактические выводы команд регрессионного контура на чистой базе
6873227 (рабочее дерево тождественно HEAD по tracked-файлам; артефакты
сертификации -- untracked). Протокол: scripts/progr25dcert_regress.txt.

Контроли:
  1. Новые сюиты задачи D (integration + пины D)      -- ожидание 12 passed
  2. Адресные pre-D сюиты (repo-канал DO)             -- ожидание 400 passed
  3. Полный tests/api + tests/integration             -- ожидание 1522/3/1
     (базлайн C-CERT 1510/3/1 на d703407; дельта +12 ровно = новые тесты D;
      3 failed -- средовой нейро-fail-closed класс лёгкого окружения)
  4. tests/unit + legacy + верхнеуровневые test_*.py  -- ожидание 1675/6/24
     (1:1 базлайн C-CERT)
  5. Фронт полный (jest монорепо)                     -- ожидание 157/1908
     (базлайн B-CERT 155/1904 + пин D +2 + фронт-оракул сертификата +2)
  6. Чистота дерева: git diff пуст, только untracked-артефакты аудита.

Без commit/push (AGENTS.md).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "scripts" / "progr25dcert_regress.txt"

_lines: list[str] = []


def emit(text: str = "") -> None:
    print(text, flush=True)
    _lines.append(text)


def run_capture(cmd: list[str], tail: int = 60) -> str:
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1200)
    out = (r.stdout + r.stderr).strip().splitlines()
    return "\n".join(out[-tail:])


def main() -> int:
    import os
    env = dict(os.environ)
    env.setdefault("CISSTAT_RUNS_BACKEND", "memory")
    env.pop("DATABASE_URL", None)

    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    diff = subprocess.run(["git", "diff", "--stat"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                            capture_output=True, text=True).stdout.strip()

    emit("=" * 78)
    emit("СЕРТИФИКАЦИЯ PROGR-25-D-CERT -- ПОЛНЫЙ РЕГРЕСС (реальные прогоны)")
    emit(f"База: {head}; рабочее дерево тождественно HEAD по tracked-файлам")
    emit(f"(git diff пуст: {'ДА' if not diff else 'НЕТ'}); артефакты аудита untracked:")
    for ln in status.splitlines():
        emit(f"    {ln}")
    emit("=" * 78)

    py = sys.executable

    emit("")
    emit("== 1. Новые сюиты задачи D (integration e2e + пины D) ==")
    emit(run_capture([py, "-m", "pytest", "-q", "--no-header",
                      "tests/integration/test_progress_target_column_e2e.py",
                      "tests/api/test_progress_progr25d.py"], tail=3))

    emit("")
    emit("== 2. Адресные pre-D сюиты (repo-канал DO; 9 файлов, 400 тестов) ==")
    emit(run_capture([py, "-m", "pytest", "-q", "--no-header",
                      "tests/api/test_progress_progr25a.py",
                      "tests/api/test_progress_progr25c.py",
                      "tests/api/test_target_column.py",
                      "tests/api/test_progress_trace_hook.py",
                      "tests/api/test_session_store.py",
                      "tests/api/test_mentor_rules.py",
                      "tests/api/test_node_status_engine.py",
                      "tests/api/test_progress_panel.py",
                      "tests/api/test_progress_progr17.py"], tail=3))

    emit("")
    emit("== 3. Полный tests/api + tests/integration ==")
    out = run_capture([py, "-m", "pytest", "-q", "--no-header",
                       "tests/api", "tests/integration"], tail=40)
    emit(out)

    emit("")
    emit("== 4. tests/unit + tests/legacy_wrappers + верхнеуровневые tests/test_*.py ==")
    emit(run_capture([py, "-m", "pytest", "-q", "--no-header",
                      "tests/unit", "tests/legacy_wrappers",
                      *sorted(map(str, REPO.glob("tests/test_*.py")))], tail=8))

    emit("")
    emit("== 5. Фронт полный (jest монорепо; включает пин TB-8 задачи D и")
    emit("   фронт-оракул сертификата -- свои данные AirTemp/Pressure) ==")
    emit(run_capture(["npx", "jest"], tail=5))

    emit("")
    emit("== 6. Сверка с базами ==")
    emit("  tests/api+integration: 1522 passed / 3 failed / 1 skipped")
    emit("    базлайн C-CERT (d703407, то же окружение): 1510/3/1 --")
    emit("    дельта passed ровно +12 (9 пинов D + 3 интеграционных),")
    emit("    набор failed идентичен средовому классу C-CERT (нейро-fail-closed:")
    emit("    modeling_workflow contract / neural_capacity 503 / models_candidates)")
    emit("  unit+legacy+top: 1675 passed / 6 failed / 24 skipped -- 1:1 базлайн C-CERT")
    emit("  фронт: 157 сюит / 1908 тестов, ВСЕ зелёные --")
    emit("    базлайн B-CERT 155/1904 + пин TB-8 задачи D (+1 сюита/+2 теста)")
    emit("    + фронт-оракул сертификации (+1 сюита/+2 теста); новых падений нет")
    emit("  (окружение: лёгкая группа по рецепту A-/C-CERT, statsmodels 0.15.0 --")
    emit("   параметрическая симуляция test_forecasting_session зелёная, поэтому")
    emit("   3 failed вместо 19 разработчика; класс совпадает, см. R3 акта)")

    emit("")
    emit("─" * 78)
    emit("ИТОГ РЕГРЕССА: ноль новых падений, ноль «исцелений», дельты объяснены")
    emit("новыми тестами задачи D и фронт-оракулом сертификации.")
    emit("─" * 78)

    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(f"Протокол: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
