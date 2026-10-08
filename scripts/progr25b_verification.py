# -*- coding: utf-8 -*-
"""Протокол верификации PROGR-25-B (spec_progress_target_column.md §4-B).

Задача B -- фронтенд: (1) шапка панели «Прогресс» читает признак и его
происхождение из ТОГО ЖЕ ответа /trace, что и трасса (поля введены
задачей PROGR-25-A); три состояния -- «value (авто)» / «value» /
«не выбран — выбрать» (ссылка на селектор /upload); прочерк «—» -- только
при отсутствии датасета; (2) снятие тихого авто-POST хука useTargetColumn
(правка R1 акта сертификации): авто-фиксация -- исключительная компетенция
бэкенда (PROGR-25-A), рекомендация остаётся отображаемой, фиксация --
только ручная.

Верификация -- запуск jest-сюит изменённых файлов с машиносчитаемым
итогом: каждый контракт задачи B пинится именем теста; прогон обязан
показать их зелёное состояние вместе со всем пре-существующим корпусом
сюит. Дополнительно -- 5 статических проверок методологии по коду.

Запуск из корня репозитория:
    python scripts/progr25b_verification.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SUITES = [
    "packages/ui/hooks/useTargetColumn.test.tsx",
    "packages/ui/components/ProgressDrawer.test.tsx",
    "packages/ui/components/TsAnalysisUpload.test.tsx",
    "packages/ui/components/TsAnalysisEDA.test.tsx",
    "packages/ui/components/TsAnalysisPreprocessing.test.tsx",
]

# Контракты задачи B. B1-B8 -- RED->GREEN (падали на базлайне 13c693c);
# INV-* -- инварианты (зелёные и до реализации: честная адаптация
# уведомления о сбросе и семантика «старый корпус -- не авто»).
CONTRACTS = [
    ("B1", "хук: монтирование НЕ выполняет авто-POST при одной числовой и рекомендации (R1)",
     "монтирование НЕ выполняет авто-POST: одна числовая, есть рекомендация (R1, однозначный класс)"),
    ("B2", "хук: монтирование НЕ выполняет авто-POST при нескольких числовых (R1)",
     "монтирование НЕ выполняет авто-POST: несколько числовых (R1, неоднозначный класс)"),
    ("B3", "хук: wasAutoSelected -- честный факт source=auto; ручной setColumn гасит",
     "wasAutoSelected -- из факта бэкенда source=auto; ручной setColumn гасит"),
    ("B4", "хук: ответ без target_column_source (старый корпус) -- не авто",
     "ответ старого бэкенда без target_column_source (undefined) -- не авто"),
    ("B5", "хук: уведомление о сбросе живёт без авто-POST -- newColumn = рекомендация",
     "columnResetNotice живёт без авто-POST: был Price, стал null -- newColumn = рекомендация"),
    ("B6", "хук: уведомление о сбросе без рекомендации -- newColumn: null",
     "columnResetNotice без рекомендации (сuggested null) -- newColumn: null"),
    ("B7", "хук: повторные монтирования/рефетчи -- только GET (ни одного POST)",
     "повторное монтирование с другим datasetKey -- тоже без POST (каждая вкладка)"),
    ("B8", "шапка: source=auto из /trace -- «value (авто)», контекст не приоритетен",
     "source=auto из /trace -- «Признак: value (авто)»"),
    ("B9", "шапка: source=user из /trace -- без пометки «(авто)»",
     "source=user из /trace -- без пометки «(авто)»"),
    ("B10", "шапка: source=null (ручной выбор старого корпуса) -- без пометки",
     "источник без поля source (ручной выбор старого корпуса) -- без пометки"),
    ("B11", "шапка: датасет есть, признака нет -- «не выбран» + ссылка «выбрать» на /upload",
     "датасет есть, признака нет -- «не выбран» и ссылка «выбрать» на селектор (/upload)"),
    ("B12", "шапка: клик «выбрать» закрывает панель",
     "клик «выбрать» закрывает панель (селектор виден на вкладке)"),
    ("B13", "шапка: датасета нет -- «—», ссылки нет",
     "датасета нет -- «—» в признаке, ссылки нет (даже при target_column=null из /trace)"),
    ("B14", "шапка: смена признака на другой вкладке + повторное открытие -- новое значение (Г2 закрыта)",
     "смена признака на другой вкладке + повторное открытие панели -- новое значение без перезагрузки страницы"),
    ("B15", "шапка: старый бэкенд без аддитивных полей -- деградация к контексту (N-3), не «не выбран»",
     "ответ старого бэкенда без аддитивных полей -- деградация к контексту (N-3), не «не выбран»"),
    ("B16", "шапка: при загруженном датасете «—» в признаке нет ни в одном состоянии",
     "новый бэкенд при загруженном датасете НЕ показывает прочерк «—» в признаке ни в одном состоянии"),
    ("B17", "upload: рекомендация отображается в селекторе без персистенции; ни одного POST (R1)",
     "displays suggested_column in the selector without persisting when target_column is not set (PROGR-25-B: авто-POST снят, R1)"),
    ("B18", "upload: бейдж «выбрано автоматически» -- из факта source=auto бэкенда",
     "shows the backend auto-fix origin badge when the backend reports source=auto (PROGR-25-A/B)"),
    ("INV1", "upload: toast сброса признака сохранён (текст честен: «рекомендация») -- адаптация, не регресс",
     "shows a warning toast when a previously selected column is reset by uploading a new dataset"),
]


def run_jest() -> tuple[int, str]:
    proc = subprocess.run(
        ["npx", "jest", *SUITES, "--verbose"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def check_static_pins() -> list[tuple[str, bool, str]]:
    """Статические проверки методологии по коду (S1-S5)."""
    results: list[tuple[str, bool, str]] = []

    hook = (REPO_ROOT / "packages/ui/hooks/useTargetColumn.ts").read_text(encoding="utf-8")
    drawer = (REPO_ROOT / "packages/ui/components/ProgressDrawer.tsx").read_text(encoding="utf-8")
    upload = (REPO_ROOT / "packages/ui/components/TsAnalysisUpload.tsx").read_text(encoding="utf-8")

    # S1: в хуке не осталось POST-ветки авто-выбора (единственный POST --
    # в setColumn, ручной выбор).
    auto_post_gone = (
        "autoSelectInFlight" not in hook
        and "fetchAndMaybeAutoSelect" not in hook
    )
    results.append(("S1", auto_post_gone,
                    "хук: ref autoSelectInFlight и функция fetchAndMaybeAutoSelect удалены"))

    # S2: wasAutoSelected выводится из факта ответа, не из действия хука.
    s2 = 'setWasAutoSelected(data.target_column_source === "auto")' in hook
    results.append(("S2", s2, "хук: wasAutoSelected = (target_column_source === \"auto\")"))

    # S3: шапка читает признак из ответа /trace (тот же fetch-эффект).
    s3 = ("targetColumn: traceData?.target_column" in drawer
          and "targetColumnSource: traceData?.target_column_source" in drawer)
    results.append(("S3", s3, "шапка: target_column/target_column_source читаются из ответа /trace"))

    # S4: прочерк «—» -- только при отсутствии датасета (гейт activeDataset).
    s4 = 'if (!activeDataset) return { kind: "dash" as const };' in drawer
    results.append(("S4", s4, "шапка: «—» только при отсутствии датасета (гейт activeDataset)"))

    # S5: ссылка «выбрать» ведёт на селектор /upload и закрывает панель.
    s5 = ('href="/upload"' in drawer and 'onClick={onClose}' in drawer)
    results.append(("S5", s5, "шапка: ссылка «выбрать» -> /upload с закрытием панели"))

    # S6: селектор Загрузки отображает рекомендацию бэкенда (suggested).
    s6 = "selectedFeature ?? suggestedColumn ?? numericCols[0]" in upload
    results.append(("S6", s6, "upload: селектор = selectedFeature ?? suggestedColumn ?? numericCols[0]"))

    return results


def main() -> int:
    print("=" * 72)
    print("PROGR-25-B верификация: шапка «Прогресс» из /trace + снятие авто-POST (R1)")
    print("=" * 72)

    code, output = run_jest()
    tail = "\n".join(output.strip().splitlines()[-6:])
    print(tail)

    if code != 0:
        print("\nFAIL: jest-прогон сюит задачи завершился с ошибками")
        return 1

    failed_pins: list[str] = []
    for pin_id, description, test_name in CONTRACTS:
        ok = (f"✓ {test_name}" in output) or (f"✓ {test_name} " in output) or (f"✓ {test_name}\n" in output)
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {pin_id}: {description}")
        if not ok:
            failed_pins.append(pin_id)

    print("-" * 72)
    for pin_id, ok, description in check_static_pins():
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {pin_id}: {description}")
        if not ok:
            failed_pins.append(pin_id)

    print("-" * 72)
    total = len(CONTRACTS) + 6
    print(f"ИТОГ: {total - len(failed_pins)}/{total} контрактов/пинов зелёные")
    if failed_pins:
        print(f"УПАЛИ: {', '.join(failed_pins)}")
        return 1
    print("Все контракты задачи PROGR-25-B подтверждены на финальном коде.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
