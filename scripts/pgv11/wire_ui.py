#!/usr/bin/env python3
"""PGV-11 UI wiring: подключение VisualExportButton в EDA-обзорах
(шаблонные правки с пер-файловыми якорями; у Lesson PGV-10 -- ref до
ранних возвратов). Запуск: python scripts/pgv11/wire_ui.py"""
from __future__ import annotations

import re
from pathlib import Path

COMPONENTS = Path("/home/z/my-project/CISStat-TS-Analysis/packages/ui/components")

# view_id кнопки (один на файл; FeatureSelection -- переключатель 2 view)
SINGLE_VIEW = {
    "EdaCorrelationOverview.tsx": "eda.correlation.acf_pacf",
    "EdaSeasonalityOverview.tsx": "eda.seasonality.spectrum",
    "EdaDistributionOverview.tsx": "eda.distribution.tests",
    "EdaStationarityOverview.tsx": "eda.stationarity.tests",
    "EdaStructuralBreaksOverview.tsx": "eda.structural.breakpoints",
    "EdaValidationStrategyOverview.tsx": "eda.validation_strategy.windows",
    "EdaModelMatrixOverview.tsx": "eda.model_matrix.applicability",
}
LABELS = {
    "EdaCorrelationOverview.tsx": "ACF/PACF",
    "EdaSeasonalityOverview.tsx": "спектр сезонности",
    "EdaDistributionOverview.tsx": "тесты нормальности",
    "EdaStationarityOverview.tsx": "тесты стационарности",
    "EdaStructuralBreaksOverview.tsx": "структурные сдвиги",
    "EdaValidationStrategyOverview.tsx": "окна валидации",
    "EdaModelMatrixOverview.tsx": "применимость моделей",
}

BUTTON_BLOCK = """<div className="mt-3 flex flex-wrap items-center gap-2">
          <VisualExportButton
            viewId="{view_id}"
            label="Скачать PNG: {label}"
            compact
            getScreenSvg={{() => serializeChartSvgSafe(() => exportSectionRef.current)}}
          />
        </div>
        """

IMPORTS_BLOCK = (
    "// PGV-11 (spec_passport_graphics_visual.md §13 «Export EDA/IH/tasks»):\n"
    "// «Скачать PNG» смешанного сайта (график + таблица из одного\n"
    "// frozen ответа; геометрия -- СВОЙ chart-узел, не первый SVG).\n"
    'import { VisualExportButton } from "./VisualExportButton";\n'
    'import { serializeChartSvgSafe } from "../lib/serializeChartSvg";\n'
)


def wire(file: str, view_id: str, label: str) -> None:
    path = COMPONENTS / file
    src = path.read_text(encoding="utf-8")
    original = src

    # 1) react import: добавить useRef
    src = re.sub(
        r'import \{ ([^}]*?)useState \} from "react";',
        lambda m: (
            'import { ' + m.group(1) + 'useRef, useState } from "react";'
            if "useRef" not in m.group(1)
            else m.group(0)
        ),
        src,
        count=1,
    )
    if "VisualExportButton" not in src:
        # 2) импорты кнопки -- после строки useExpandableChartState
        src = re.sub(
            r'(import \{ useExpandableChartState \} from "../hooks/useExpandableChart";\n)',
            r"\1" + IMPORTS_BLOCK,
            src,
            count=1,
        )

    # 3) ref до ранних возвратов: после ПЕРВОГО useState в inner-компоненте
    #    (первое вхождение useState после строки 'function ...Inner' либо
    #    после 'export function' для файлов без Inner)
    hook_re = re.compile(r"(const \[activeView|const \[view|const \[activeTab)[^\n]*\n")
    match = hook_re.search(src)
    if match is None:
        raise SystemExit(f"{file}: якорь первого useState не найден")
    ref_block = (
        "  // PGV-11: ref СВОЕЙ поверхности рендера (frozen геометрия\n"
        "  // активного представления -- не первый SVG документа);\n"
        "  // объявлен ДО ранних возвратов (урок PGV-10).\n"
        "  const exportSectionRef = useRef<HTMLElement>(null);\n"
    )
    if "exportSectionRef" not in src:
        src = src[: match.end()] + ref_block + src[match.end():]

    # 4) section ref
    src = src.replace(
        '<section className={`relative flex h-[468px]',
        '<section ref={exportSectionRef} className={`relative flex h-[468px]',
        1,
    )

    # 5) кнопка перед tablist (первый <div role="tablist")
    if f'viewId="{view_id}"' not in src:
        block = BUTTON_BLOCK.format(view_id=view_id, label=label)
        src = src.replace('<div role="tablist"', block + '<div role="tablist"', 1)

    if src != original:
        path.write_text(src, encoding="utf-8")
        print(f"OK  {file}")
    else:
        print(f"SKIP {file} (уже подключено)")


for file, view_id in SINGLE_VIEW.items():
    wire(file, view_id, LABELS[file])

# EdaFeatureSelectionOverview: два view (scores -- chart, matrix -- heatmap)
path = COMPONENTS / "EdaFeatureSelectionOverview.tsx"
src = path.read_text(encoding="utf-8")
original = src
src = src.replace(
    'import { useState } from "react";',
    'import { useRef, useState } from "react";',
    1,
)
if "VisualExportButton" not in src:
    src = src.replace(
        'import { useExpandableChartState } from "../hooks/useExpandableChart";\n',
        'import { useExpandableChartState } from "../hooks/useExpandableChart";\n'
        + IMPORTS_BLOCK,
        1,
    )
if "exportSectionRef" not in src:
    src = src.replace(
        ' const [view,setView]=useState<View>("association");',
        ' const [view,setView]=useState<View>("association");\n'
        " // PGV-11: ref СВОЕЙ поверхности рендера; объявлен до ранних\n"
        " // возвратов (урок PGV-10).\n"
        " const exportSectionRef = useRef<HTMLElement>(null);",
        1,
    )
src = src.replace(
    "return <section className={`relative flex h-[468px]",
    "return <section ref={exportSectionRef} className={`relative flex h-[468px]",
    1,
)
if 'viewId={view === "matrix"' not in src:
    block = (
        '<div className="mt-3 flex flex-wrap items-center gap-2">'
        "<VisualExportButton\n"
        '  viewId={view === "matrix" ? "eda.feature_select.matrix" : "eda.feature_select.scores"}\n'
        '  label="Скачать PNG: активное представление"\n'
        "  compact\n"
        '  getScreenSvg={view === "matrix" ? undefined : () => serializeChartSvgSafe(() => exportSectionRef.current)}\n'
        "/></div>\n  "
    )
    src = src.replace('<div role="tablist"', block + '<div role="tablist"', 1)
if src != original:
    path.write_text(src, encoding="utf-8")
    print("OK  EdaFeatureSelectionOverview.tsx")
else:
    print("SKIP EdaFeatureSelectionOverview.tsx (уже подключено)")
