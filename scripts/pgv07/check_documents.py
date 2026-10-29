#!/usr/bin/env python3
"""
PGV-07 — doc-contract гвард «документация == поставка»
(паттерн scripts/pgv00/check_documents.py, scripts/pgv01/check_documents.py).

Проверяет:
  1) постановку: строка PGV-07 в spec_passport_graphics_visual.md (§13),
     критерий готовности, зависимость PGV-01;
  2) контрактный документ docs/pgv07_print_layout.md: разделы, AC-привязки,
     ключевые решения, состав файлов;
  3) состав поставки: все перечисленные файлы существуют в репозитории;
  4) связность worklog-записи: Task ID: PGV-07, состав файлов, счётчики.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

DELIVERY_FILES = [
    "packages/ui/print/printTheme.ts",
    "packages/ui/print/printLayout.tsx",
    "packages/ui/print/printSections.tsx",
    "packages/ui/print/printIh.tsx",
    "packages/ui/print/printPassport.tsx",
    "packages/ui/print/printComparison.tsx",
    "packages/ui/print/index.ts",
    "packages/ui/print/printLayout.test.tsx",
    "packages/ui/print/printPassport.test.tsx",
    "docs/pgv07_print_layout.md",
    "scripts/pgv07/check_documents.py",
    "scripts/pgv07/protocols/red_protocol.txt",
]

CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    CHECKS.append((name, ok))


def read(rel: str) -> str:
    path = REPO / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main() -> int:
    spec = read("spec_passport_graphics_visual.md")
    doc = read("docs/pgv07_print_layout.md")
    worklog = read("worklog/worklog11.md")
    red_protocol = read("scripts/pgv07/protocols/red_protocol.txt")

    # 1. Постановка в проектной спеке (§13 строка PGV-07, зависимость PGV-01).
    check(
        "spec §13: строка PGV-07 с зависимостью PGV-01",
        "| PGV-07 | PGV-01 | Shared pure print layout |" in spec,
    )
    check(
        "spec §13: критерий готовности PGV-07",
        "Light фон, labels/legend/HTML IH/полные паспорта, без fetch/animation" in spec,
    )
    check("spec §4.1: общий print bundle переиспользует научную геометрию", "Fetch/state/animation отделяются от pure presentation" in spec)
    check("spec §3: инвариант light-print (непрозрачный белый фон)", "Всегда light-print: непрозрачный белый фон" in spec)
    check("spec §14: приёмочные сценарии AC02/AC04/AC05/AC15/AC16 присутствуют", all(f"PGV-AC{n:02d}" in spec for n in (2, 4, 5, 15, 16)))

    # 2. Контрактный документ.
    for token in [
        "PGV-07 — Shared pure print layout",
        "main@1254e50",
        "AC04",
        "AC05",
        "AC02",
        "chunkTableRows",
        "PrintIhConditionalMatrix",
        "PrintPassportPage",
        "PrintPassportComparisonPage",
        "без fetch/animation",
        "KG",  # маркер лишнего не нужен; проверка состава ниже
    ]:
        if token == "KG":
            continue
        check(f"docs/pgv07_print_layout.md содержит «{token}»", token in doc)
    check(
        "документ: раздел TDD с честным Import-RED",
        "TS2307" in doc and "Import-RED" in doc,
    )
    check(
        "документ: вклад в AC-таблицу",
        "PGV-AC02" in doc and "PGV-AC04" in doc and "PGV-AC15" in doc,
    )

    # 3. Состав поставки — все файлы существуют.
    for rel in DELIVERY_FILES:
        check(f"файл существует: {rel}", (REPO / rel).exists())

    # 4. RED-протокол честности (Import-RED, не вакуумный).
    check("RED-протокол фиксирует TS2307", "TS2307" in red_protocol)

    # 5. Связность worklog-записи.
    check("worklog11: запись Task ID: PGV-07", "Task ID: PGV-07" in worklog)
    check(
        "worklog11: перечислен print-бандл",
        "printTheme.ts" in worklog and "printPassport.test.tsx" in worklog,
    )
    check("worklog11: счётчик 2523/2523", "2523" in worklog)
    check(
        "worklog11: без commit/push (AGENTS.md)",
        "Без commit/push" in worklog,
    )

    # 6. Статическая честность print-бандла: дублируем ключевые запреты
    #    jest-оракула на уровне гварда (защита от «теста мимо исходников»).
    forbidden = ["useEffect(", "useState(", "fetch(", "axios", "Math.random("]
    for rel in DELIVERY_FILES:
        if rel.startswith("packages/ui/print/") and rel.endswith((".ts", ".tsx")) and ".test." not in rel:
            source = read(rel)
            hits = [token for token in forbidden if token in source]
            check(f"print-модуль чист: {rel}", not hits)

    failed = [name for name, ok in CHECKS if not ok]
    passed = len(CHECKS) - len(failed)
    print(f"PGV-07 doc-contract гвард: {passed}/{len(CHECKS)}")
    for name in failed:
        print(f"  FAIL: {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
