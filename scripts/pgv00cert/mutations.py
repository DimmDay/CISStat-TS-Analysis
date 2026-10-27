#!/usr/bin/env python3
# scripts/pgv00cert/mutations.py
#
# PGV-00-CERT — каталог мутантов «на своих мутантах».
# Мутации продуктовых файлов поставки PGV-00 (2ef6947): реестр TS, JSON-твин,
# правки родительской спеки, документ инвентаря, guard, экспортёр.
# Каналы убийства: REPO (jest visualExportRegistry.coverage.test.ts +
# check_documents.py) и ORACLE (Class A корпуса сертификатора, 41 оракул).
# Ожидания предрегистрированы; несовпадение факта с ожиданием — находка протокола.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutation:
    mid: str
    file: str
    old: str
    new: str
    expect: str  # DUAL | ORACLE-ONLY | REPO-ONLY
    note: str
    extra: tuple[str, str, str] | None = None  # дополнительная (file, old, new) тем же мутантом


REG = "packages/ui/lib/visualExportRegistry.ts"

MUTATIONS: list[Mutation] = [
    # ── packages/ui/lib/visualExportRegistry.ts (14) ─────────────────
    Mutation("M01", REG,
             'view_id: "tasks.causes.fold_importance",',
             'view_id: "tasks.causes.fold_importance_renamed",',
             "DUAL",
             "переименование view_id в TS: дрейф TS⇄JSON (repo-паритет + set-паритет сертификатора)"),
    Mutation("M02", REG,
             'view_id: "navigator.upload.chart.series",',
             'view_id: "navigator.upload.chart.series_ghost",\n    view_id: "navigator.upload.chart.series",',
             "DUAL",
             "двойной view_id-ключ в записи: счётчик TS-записей 90 и паритет"),
    Mutation("M03", REG,
             'render_site: "packages/ui/components/ForecastExportMenu.tsx",\n    renderer_kind: "recharts_svg",\n    source_adapter: "pgv-12/forecast_menu_rewire",\n    required_refs: ["context_id", "data_revision", "target_column", "forecast_artifact_ref"],\n    view_params: ["origin", "horizon", "alpha"],\n    applicability: "univariate",\n    caption_schema: "pgv.caption/forecast.chart/1",\n    export_status: "legacy_client",',
             'render_site: "packages/ui/components/ForecastExportMenu.tsx",\n    renderer_kind: "recharts_svg",\n    source_adapter: "pgv-12/forecast_menu_rewire",\n    required_refs: ["context_id", "data_revision", "target_column", "forecast_artifact_ref"],\n    view_params: ["origin", "horizon", "alpha"],\n    applicability: "univariate",\n    caption_schema: "pgv.caption/forecast.chart/1",\n    export_status: "planned",',
             "DUAL",
             "legacy_client → planned: честность статуса (легаси PNG спрятан от плана PGV-12); якорь по render_site — caption forecast.chart у двух записей"),
    Mutation("M04", REG,
             'caption_schema: "pgv.caption/modeling.diagnostics/1",\n    export_status: "not_mounted",',
             'caption_schema: "pgv.caption/modeling.diagnostics/1",\n    export_status: "planned",',
             "DUAL",
             "not_mounted → planned: несмонтированный компонент объявлен планируемым"),
    Mutation("M05", REG,
             'reason_class: "operational_list",',
             'reason_class: "scientific_special",',
             "DUAL",
             "класс исключения вне каталога: мультимножество классов TS⇄JSON расходится"),
    Mutation("M06", REG,
             'export const PGV_REGISTRY_SCHEMA_VERSION = "pgv.visual_registry/1";',
             'export const PGV_REGISTRY_SCHEMA_VERSION = "pgv.visual_registry/2";',
             "DUAL",
             "версия схемы TS дрейфует от JSON-твина"),
    Mutation("M07", REG,
             'stop_id: "upload.chart",\n    render_site: "packages/ui/components/NavigatorChartPreview.tsx#series",',
             'stop_id: "upload.charts",\n    render_site: "packages/ui/components/NavigatorChartPreview.tsx#series",',
             "DUAL",
             "stop_id Навигатора вне navigator-stops: разрыв с источником истины"),
    Mutation("M08", REG,
             'render_site: "packages/ui/components/NavigatorChartPreview.tsx#series",\n    renderer_kind: "recharts_svg",',
             'render_site: "packages/ui/components/NavigatorChartPreview.tsx#series",\n    renderer_kind: "html_table",',
             "DUAL",
             "kind-подмена только в TS: repo-паритет TS⇄JSON ловит (предрегистрированное ожидание ORACLE-ONLY было неверным — паритет покрывает все поля записей)"),
    Mutation("M08b", REG,
             'render_site: "packages/ui/components/NavigatorChartPreview.tsx#series",\n    renderer_kind: "recharts_svg",',
             'render_site: "packages/ui/components/NavigatorChartPreview.tsx#series",\n    renderer_kind: "html_table",',
             "ORACLE-ONLY",
             "СОГЛАСОВАНная kind-подмена TS+JSON: паритет проходит, канон допустим — семантику kind-vs-file ловит только сигнатурный оракул сертификатора",
             extra=("config/visual_registry.json",
                    '"view_id": "navigator.upload.chart.series",\n      "module_id": "navigator",\n      "stop_id": "upload.chart",\n      "render_site": "packages/ui/components/NavigatorChartPreview.tsx#series",\n      "renderer_kind": "recharts_svg",',
                    '"view_id": "navigator.upload.chart.series",\n      "module_id": "navigator",\n      "stop_id": "upload.chart",\n      "render_site": "packages/ui/components/NavigatorChartPreview.tsx#series",\n      "renderer_kind": "html_table",')),
    Mutation("M09", REG,
             'render_site: "packages/ui/components/NavigatorChartPreview.tsx#series",\n    renderer_kind: "recharts_svg",\n    source_adapter: "pgv-03/navigator_demo",',
             'render_site: "packages/ui/components/NavigatorChartPreview.tsx#series",\n    renderer_kind: "recharts_svg",\n    source_adapter: "adapter/navigator_demo",',
             "DUAL",
             "канон адаптера pgv-XX/ нарушен (repo-паритет + реген-паритет сертификатора; предрегистрированное REPO-ONLY устарело)"),
    Mutation("M10", REG,
             'caption_schema: "pgv.caption/navigator.chart/1",',
             'caption_schema: "pgv.caption/Navigator.Chart/1",',
             "DUAL",
             "канон caption_schema в TS нарушен (repo-паритет + реген-паритет сертификатора)"),
    Mutation("M11", REG,
             '    required_refs: [...REFS_DEMO],\n    view_params: ["static_layout"],\n    applicability: "static_demo",\n    caption_schema: "pgv.caption/navigator.chart/1",',
             '    required_refs: [],\n    view_params: ["static_layout"],\n    applicability: "static_demo",\n    caption_schema: "pgv.caption/navigator.chart/1",',
             "DUAL",
             "обязательные refs navigator-серии обнулены в TS (repo-паритет + реген-паритет)"),
    Mutation("M12", REG,
             '  {\n    targets: ["packages/ui/components/ForecastHistoryList.tsx"],\n    reason_class: "operational_list",\n    reason: "Операционная история forecast-заданий (очередь/статусы); научное содержимое прогноза зарегистрировано отдельно (ForecastChart/AccuracyPanel/panel_table).",\n  },\n',
             '  /* P0CERT-M12-EXCLUSION-DROPPED */\n',
             "DUAL",
             "запись исключения удалена (инертный маркер сохраняет позицию для обратной замены): пин 9, закрытие скана, мультимножество классов"),
    Mutation("M13", REG,
             'const REFS_DEMO = ["demo_dataset_id"] as const;',
             'const REFS_DEMO = [] as unknown as ["demo_dataset_id"];',
             "DUAL",
             "общий набор демо-refs обнулён (navigator-записи слепые; repo-паритет + реген-паритет)"),
    Mutation("M14", REG,
             'export function visualRegistrySummary(): VisualRegistrySummary {',
             'export function visualRegistrySummary(): VisualRegistrySummary {\n  throw new Error("P0CERT-M14: summary poisoned");',
             "DUAL",
             "сводка реестра отравлена безусловным throw: repo-jest падает (denominator/паритет) и cert-реген-оракул падает (экспортёр вызывает сводку; предрегистрированное REPO-ONLY устарело)"),

    # ── config/visual_registry.json (2) ──────────────────────────────
    Mutation("M15", "config/visual_registry.json",
             '"view_id": "tasks.causes.fold_importance",',
             '"view_id": "tasks.causes.fold_importance_x",',
             "DUAL",
             "JSON-дрейф от TS: repo-паритет toEqual + set-паритет сертификатора"),
    Mutation("M16", "config/visual_registry.json",
             '"total_sites": 89,',
             '"total_sites": 90,',
             "DUAL",
             "denominator JSON завышен"),

    # ── spec_documentation_logging.md (2) ────────────────────────────
    Mutation("M17", "spec_documentation_logging.md",
             'действует **PNG-only**',
             'действует **SVG-first**',
             "DUAL",
             "PNG-only-инвариант §7 подменён (guard и cert-оракул теряют маркер)"),
    Mutation("M18", "spec_documentation_logging.md",
             '**D02 (паспорт-документ) не переименовывается и не равен P01**',
             '**D02 (паспорт-документ) не переименовывается**',
             "ORACLE-ONLY",
             "инвариант D02≠P01 ослаблен: guard проверяет лишь наличие D02/P01 в §12"),

    # ── docs/pgv00_render_site_inventory.md (1) ──────────────────────
    Mutation("M19", "docs/pgv00_render_site_inventory.md",
             '| navigator | 14 |',
             '| navigator | 15 |',
             "ORACLE-ONLY",
             "состав модуля в документе искажён: guard удовлетворяется подстрокой «14» из строки §5"),

    # ── scripts/pgv00/check_documents.py (3) ─────────────────────────
    Mutation("M20", "scripts/pgv00/check_documents.py",
             'EXPECTED_TOTAL = sum(EXPECTED_MODULES.values())',
             'EXPECTED_TOTAL = sum(EXPECTED_MODULES.values()) + 1',
             "DUAL",
             "guard отравлен: собственная проверка падает на честном JSON (repo-канал требует GREEN)"),
    Mutation("M21", "scripts/pgv00/check_documents.py",
             '    check("worklog11.md: запись Task ID: PGV-00", "Task ID: PGV-00" in worklog)',
             '    # MUTANT: worklog-проверка снята',
             "ORACLE-ONLY",
             "секция E guard'а удалена: guard остаётся GREEN, состав ловит cert-токен worklog11.md"),
    Mutation("M22", "scripts/pgv00/check_documents.py",
             '        legacy = [s["view_id"] for s in sites if s.get("export_status") == "legacy_client"]',
             '        legacy = ["p0cert-mutant-blinded"]',
             "DUAL",
             "guard-проверка legacy ослеплена: guard сам падает (legacy != прогнозному меню)"),

    # ── scripts/pgv00/export_registry.ts (1) ─────────────────────────
    Mutation("M23", "scripts/pgv00/export_registry.ts",
             'const outPath = path.join(repoRoot, "config", "visual_registry.json");',
             'const outPath = path.join(repoRoot, "config", "visual_registry_mutant.json");',
             "ORACLE-ONLY",
             "экспортёр пишет мимо твина: repo-канал экспортёр не запускает, cert-оракул ловит мусор дерева"),
]

CONTROLS: list[Mutation] = [
    Mutation("C01", REG,
             '// PGV-00 — machine-readable реестр научных render-sites платформы',
             '// PGV-00 — machine-readable реестр научных render-sites платформы (контроль)',
             "ALIVE",
             "no-op контроль: комментарий в заголовке реестра"),
    Mutation("C02", "docs/pgv00_render_site_inventory.md",
             "# PGV-00 — Инвентарь научных render-sites (документ поставки)",
             "# PGV-00 — Инвентарь научных render-sites (документ поставки; контроль)",
             "ALIVE",
             "no-op контроль: комментарий в заголовке документа"),
    Mutation("C03", "scripts/pgv00/check_documents.py",
             "# Запуск: python3 scripts/pgv00/check_documents.py   (из корня репозитория)",
             "# Запуск: python3 scripts/pgv00/check_documents.py   (из корня репозитория; контроль)",
             "ALIVE",
             "no-op контроль: комментарий в guard'е"),
]
