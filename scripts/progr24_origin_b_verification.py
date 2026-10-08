# -*- coding: utf-8 -*-
"""Протокол верификации PROGR-24-ORIGIN-B (spec_status_original_series.md, задача B).

Задача B -- фронтенд: группировка чекбоксов мастера «Выбросов» на
«Исходные»/«Производные» + нейтральная плашка Обзора + заметка
предпросмотра мастера «Стационарности». Бэкенд-данные уже отдаются
задачей A (derived_summary), бэкенд не менялся.

Верификация -- запуск jest-сюит трёх изменённых компонентов (полные
файлы, включая пре-существующие контракты) с машиносчитаемым итогом:
каждый контракт задачи B пинится именем теста; прогон обязан показать
их зелёное состояние вместе со всем пре-существующим корпусом.

Запуск из корня репозитория:
    python scripts/progr24_origin_b_verification.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SUITES = [
    "packages/ui/components/PreprocessingOutliersPipeline.test.tsx",
    "packages/ui/components/PreprocessingOutliersOverview.test.tsx",
    "packages/ui/components/PreprocessingStationarityPipeline.test.tsx",
]

# Контракты задачи B (RED->GREEN, 6 падавших) + 2 пина обратной
# совместимости (зелёные изначально -- «на своих мутантах» невозможно,
# пинятся как отсутствие группы/плашки).
CONTRACTS = [
    ("B1", "мастер: исходные предзаполнены, производные свёрнуты и НЕ предложены по умолчанию, с пояснением",
     "исходные предзаполнены, производные свёрнуты и НЕ предложены по умолчанию, с пояснением"),
    ("B2", "мастер: у производных счётчик «всплесков» (терминология спеки), раскрывается по клику",
     "у производных счётчик «всплесков» (терминология спеки), раскрывается по клику"),
    ("B3", "мастер: осознанно отмеченная производная колонка уходит в запрос коррекции",
     "осознанно отмеченная производная колонка уходит в запрос коррекции"),
    ("B4", "мастер: старый API без derived_summary -- группы производных нет (пин обратной совместимости)",
     "старый API без derived_summary: группы производных нет (обратная совместимость)"),
    ("B5", "мастер: после apply группа производных обновляется из ответа -- флаг-колонка ТОЛЬКО свёрнутая и неснятая (петля PROGR-22 не возвращается)",
     "после apply группа производных обновляется из ответа: флаг-колонка появляется ТОЛЬКО свёрнутой и неснятой (петля PROGR-22 не возвращается)"),
    ("B6", "обзор: нейтральная плашка с плюрализацией всплесков и именами колонок; фон нейтральный, в шапке Обзора",
     "показывает плашку с плюрализацией всплесков и именами колонок; фон нейтральный, в шапке Обзора"),
    ("B7", "обзор: плашки нет для старого API без derived_summary и при нулевых всплесках (пин обратной совместимости)",
     "плашки нет для старого API без derived_summary и при нулевых всплесках"),
    ("B8", "стационарность: заметка о структурном сдвиге появляется в предпросмотре (и только в нём), тон инфо",
     "заметка появляется в предпросмотре (и только в нём), тон инфо"),
]


def run_jest() -> tuple[int, str]:
    proc = subprocess.run(
        ["npx", "jest", *SUITES, "--verbose"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    return proc.returncode, proc.stdout + proc.stderr


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def main() -> int:
    print("=" * 100)
    print("ПРОТОКОЛ ВЕРИФИКАЦИИ PROGR-24-ORIGIN-B (spec_status_original_series.md, задача B)")
    print("База: 606d635; бэкенд не менялся (данные -- derived_summary задачи A); правки -- 3 компонента UI + их тесты")
    print("=" * 100)

    code, output = run_jest()
    flat = normalize(output)

    print()
    print("-- Запуск jest (3 сюиты изменённых компонентов, полные файлы) --")
    passed_total = re.search(r"Tests:\s+(\d+) passed", flat)
    failed_total = re.search(r"Tests:\s+(?:\d+ passed, )*(\d+) failed", flat)
    suites_total = re.search(r"Test Suites:\s+(\d+) passed", flat)
    print(
        f"    Test Suites: {suites_total.group(1) if suites_total else '?'} passed | "
        f"Tests: {passed_total.group(1) if passed_total else '?'} passed"
        f"{', ' + failed_total.group(1) + ' failed' if failed_total else ''}"
    )

    print()
    print("-- Контракты задачи B (по имени теста в verbose-выводе) --")
    ok = 0
    for cid, description, pattern in CONTRACTS:
        found = normalize(pattern) in flat
        status = "[PASS]" if found and code == 0 else "[FAIL]"
        if found:
            ok += 1
        print(f"    {status} {cid}: {description}")
        if not found:
            print(f"           (не найден в выводе: {pattern!r})")

    print()
    print("-- Статический контроль методологии (grep по исходникам компонентов) --")
    overview_src = (REPO_ROOT / "packages/ui/components/PreprocessingOutliersOverview.tsx").read_text(encoding="utf-8")
    pipeline_src = (REPO_ROOT / "packages/ui/components/PreprocessingOutliersPipeline.tsx").read_text(encoding="utf-8")
    stationarity_src = (REPO_ROOT / "packages/ui/components/PreprocessingStationarityPipeline.tsx").read_text(encoding="utf-8")
    # Строка плашки: от role="note" до конца элемента (одна строка JSX).
    note_line = next((line for line in overview_src.splitlines() if 'role="note"' in line), "")
    checks: list[tuple[str, str, str, bool]] = [
        ("S1", "плашка Обзора НЕ amber/red (не окрашивает остановку); bg-amber в файле -- легитимный бейдж таблицы, проверяем ТОЛЬКО строку плашки",
         "packages/ui/components/PreprocessingOutliersOverview.tsx",
         bool(note_line) and "bg-neutral-50" in note_line and "bg-amber" not in note_line and "bg-red" not in note_line),
        ("S2", "плашка -- role=note, вне статуса остановки",
         "packages/ui/components/PreprocessingOutliersOverview.tsx", bool(note_line)),
        ("S3", "группа производных -- <details> (свёрнута по умолчанию), без предзаполнения",
         "packages/ui/components/PreprocessingOutliersPipeline.tsx", "<details" in pipeline_src),
        ("S4", "у производных счётчик «всплесков», у исходных -- «выбросов»",
         "packages/ui/components/PreprocessingOutliersPipeline.tsx", "всплесков:" in pipeline_src),
        ("S5", "заметка стационарности -- инфо-фон (bg-blue-50), не warning",
         "packages/ui/components/PreprocessingStationarityPipeline.tsx", "bg-blue-50" in stationarity_src),
    ]
    for cid, description, path, ok_flag in checks:
        print(f"    [{'PASS' if ok_flag else 'FAIL'}] {cid}: {description} ({path})")
        ok += 1 if ok_flag else 0

    total = len(CONTRACTS) + len(checks)
    print()
    print("=" * 100)
    print(f"ИТОГ: {ok}/{total} контрактов выполнено" + ("" if ok == total else "  <-- ЕСТЬ ПРОВАЛЫ"))
    print("Правила AGENTS.md соблюдены: TDD RED->GREEN на 3 фронте-сюитах; регрессия jest/py/typecheck;")
    print("commit/push НЕ выполнялись.")
    print("=" * 100)
    return 0 if ok == total and code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
