// @ts-nocheck

// ExpandableChartCoverage.test.ts — контрактный тест покрытия фичей
// раскрытия/схлопывания вложенных графиков «Обзора» (Task 97, Этап 1;
// spec_max_graf_fix.md §7.2).
//
// По прецеденту AnalysisWorkspaceHeight.test.ts / AdaptiveWorkspaceVisualizations.test.ts
// тест НЕ рендерит компоненты, а статически проверяет исходники по ЯВНЫМ
// спискам файлов. Списки — единственный источник правды о скоупе роллаута:
// при переносе файла между списками правится ровно одна строка здесь.
//
// Три списка (факты верифицированы по кодовой базе @ 63b1d7d):
//
//  1. EXPANDABLE_WINDOW_OVERVIEWS (20 файлов) — Обзоры-владельцы окна
//     h-[468px], рендерящие графики данных (Recharts или дочерние
//     chart-компоненты). Требования (правки A–C спеки):
//       a) класс relative в className окна 468px;
//       b) условная пара overflow-hidden / overflow-y-auto по expandedChartId;
//       c) монтируется ExpandableChartsProvider;
//       d) визуальные блоки обёрнуты в ExpandableChartPanel.
//     На момент Этапа 1 ни один файл не адаптирован — тесты сознательно RED
//     (spec_max_graf_fix.md §8, Этап 1): это чек-лист Этапов 2–4. Каждый
//     GREEN-переключатель = один адаптированный Обзор.
//
//  2. CHART_BLOCK_SOURCES (3 файла) — модули, ОПРЕДЕЛЯЮЩИЕ chart-блоки,
//     рендеримые Обзорами из списка 1 (Missing/Outliers/Regularity
//     Visualizations). Обёртка ExpandableChartPanel ставится на уровне
//     ИСПОЛЬЗОВАНИЯ (в Обзоре), поэтому внутри этих файлов панель не нужна.
//     Guard: каждый источник должен импортироваться хотя бы одним Обзором
//     из списка 1 — иначе блок «потерян» для фичи.
//
//  3. OUT_OF_SCOPE_NO_CHARTS (31 файл) — файлы Обзор-семейства БЕЗ
//     визуализаций данных: таблицы/статусы Validation, pipeline-обёртки
//     Preprocessing, статичные схемы Modeling/Upload. Раскрытие графика
//     к ним не применимо (spec_max_graf_fix.md §2: «раскрыть вложенный
//     график»). Negative-guard: случайное появление Provider/Panel здесь —
//     ошибка скоупа; для расширения скоупа тимлид переносит файл в список 1.

import { readFileSync, readdirSync } from "fs";
import { join } from "path";

const EXPANDABLE_WINDOW_OVERVIEWS = [
  // EDA — графики инлайн
  "EdaCorrelationOverview.tsx",
  "EdaDescriptiveOverview.tsx",
  "EdaDistributionOverview.tsx",
  "EdaFeatureSelectionOverview.tsx",
  "EdaIhOverview.tsx",
  "EdaModelMatrixOverview.tsx",
  "EdaSeasonalityOverview.tsx",
  "EdaStationarityOverview.tsx",
  "EdaStructuralBreaksOverview.tsx",
  "EdaValidationStrategyOverview.tsx",
  // Preprocessing — графики инлайн или через Visualizations
  "PreprocessingDecompositionOverview.tsx",
  "PreprocessingFeatureEngineeringOverview.tsx",
  "PreprocessingMissingOverview.tsx",
  "PreprocessingOutliersOverview.tsx",
  "PreprocessingRegularityOverview.tsx",
  "PreprocessingScalingOverview.tsx",
  "PreprocessingSmoothingOverview.tsx",
  "PreprocessingSpectralOverview.tsx",
  "PreprocessingStationarityOverview.tsx",
  "PreprocessingVarianceOverview.tsx",
] as const;

const CHART_BLOCK_SOURCES = [
  "PreprocessingMissingVisualizations.tsx",
  "PreprocessingOutliersVisualizations.tsx",
  "PreprocessingRegularityVisualizations.tsx",
] as const;

const OUT_OF_SCOPE_NO_CHARTS = [
  // Modeling — статичные схемы трассируемости/workflow без графиков данных
  "ModelingTraceabilityOverview.tsx",
  "ModelingWorkflowOverview.tsx",
  // Preprocessing — pipeline-обёртки; окно Обзора с графиками живёт
  // в их Overview-компонентах из списка 1
  "PreprocessingDecompositionPipeline.tsx",
  "PreprocessingFeatureEngineeringPipeline.tsx",
  "PreprocessingMissingPipeline.tsx",
  "PreprocessingOutliersPipeline.tsx",
  "PreprocessingRegularityPipeline.tsx",
  "PreprocessingScalingPipeline.tsx",
  "PreprocessingSmoothingPipeline.tsx",
  "PreprocessingSpectralPipeline.tsx",
  "PreprocessingStationarityPipeline.tsx",
  "PreprocessingVariancePipeline.tsx",
  // Upload — статичная блок-схема автопревью (Navigator), без графиков данных
  "UploadAutoPreviewPipeline.tsx",
  // Validation — контент Обзоров: таблицы/статусы проверок, графиков нет
  "ValidationConsistencyOverview.tsx",
  "ValidationConsistencyPipeline.tsx",
  "ValidationFormatPipeline.tsx",
  "ValidationInclusionOverview.tsx",
  "ValidationInclusionPipeline.tsx",
  "ValidationRangeOverview.tsx",
  "ValidationRangePipeline.tsx",
  "ValidationReferentialOverview.tsx",
  "ValidationReferentialPipeline.tsx",
  "ValidationRegularityOverview.tsx",
  "ValidationRegularityPipeline.tsx",
  "ValidationSufficiencyOverview.tsx",
  "ValidationSufficiencyPipeline.tsx",
  "ValidationTextQualityOverview.tsx",
  "ValidationTextQualityPipeline.tsx",
  "ValidationTypePipeline.tsx",
  "ValidationUniquenessOverview.tsx",
  "ValidationUniquenessPipeline.tsx",
] as const;

const FAMILY_RE = /(Overview|Pipeline|Visualizations)\.tsx$/;
const FAMILY_TOTAL = 54;

// Извлечение className-строк — по образцу AnalysisWorkspaceHeight.test.ts
function classNamesOf(source: string): string[] {
  return Array.from(
    source.matchAll(/className=(?:"([^"]*)"|`([^`]*)`)/gs),
    (match) => match[1] ?? match[2] ?? ""
  );
}

describe("ExpandableChartCoverage: чек-лист роллаута раскрытия графиков", () => {
  it.each(EXPANDABLE_WINDOW_OVERVIEWS)(
    "адаптирован под раскрытие графиков: %s",
    (fileName) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      const classes = classNamesOf(source);

      const missing: string[] = [];
      // (a) правка A: relative в className окна 468px — якорь для absolute inset-0
      if (!classes.some((c) => c.includes("h-[468px]") && /(?:^|\s)relative(?:\s|$)/.test(c))) {
        missing.push("relative в className окна h-[468px]");
      }
      // (b) правка C: условный overflow на время раскрытия
      if (!classes.some((c) => c.includes("overflow-hidden"))) {
        missing.push("overflow-hidden при раскрытом графике");
      }
      if (!classes.some((c) => c.includes("overflow-y-auto"))) {
        missing.push("overflow-y-auto в свёрнутом состоянии");
      }
      // (c) провайдер на уровне Обзора
      if (!source.includes("ExpandableChartsProvider")) {
        missing.push("монтируется ExpandableChartsProvider");
      }
      // (d) обёртка визуальных блоков
      if (!source.includes("ExpandableChartPanel")) {
        missing.push("визуальные блоки обёрнуты в ExpandableChartPanel");
      }

      expect(missing).toEqual([]);
    }
  );

  it("каждый CHART_BLOCK_SOURCES импортируется хотя бы одним Обзором из списка раскрытия", () => {
    const overviewSources = EXPANDABLE_WINDOW_OVERVIEWS.map((fileName) => ({
      fileName,
      source: readFileSync(join(__dirname, fileName), "utf8"),
    }));

    for (const blockFile of CHART_BLOCK_SOURCES) {
      const moduleName = blockFile.replace(/\.tsx$/, "");
      const consumers = overviewSources.filter((item) => item.source.includes(moduleName));
      expect(
        `${moduleName} импортируется Обзорами: [${consumers.map((c) => c.fileName).join(", ")}]`
      ).not.toBe(`${moduleName} импортируется Обзорами: []`);
    }
  });

  it.each(OUT_OF_SCOPE_NO_CHARTS)(
    "вне скоупа раскрытия (нет графиков данных), без преждевременного Adopt'а: %s",
    (fileName) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      expect(source).not.toContain("ExpandableChartsProvider");
      expect(source).not.toContain("ExpandableChartPanel");
    }
  );

  it("списки роллаута покрывают весь инвентарь Обзор-семейства (54 файла), без пропусков и дублей", () => {
    const declared = [
      ...EXPANDABLE_WINDOW_OVERVIEWS,
      ...CHART_BLOCK_SOURCES,
      ...OUT_OF_SCOPE_NO_CHARTS,
    ];
    const declaredSet = new Set(declared);

    // без дублей между списками
    expect(declared.length).toBe(declaredSet.size);
    expect(declaredSet.size).toBe(FAMILY_TOTAL);

    // ровно всё семейство, ничего лишнего и ничего не потеряно
    const actual = readdirSync(__dirname).filter(
      (f) => FAMILY_RE.test(f) && !f.includes(".test.")
    );
    expect([...declaredSet].sort()).toEqual(actual.sort());
  });

  it("Обзоры списка раскрытия сохраняют контракт высоты 468px (Task 88 не сломан)", () => {
    for (const fileName of EXPANDABLE_WINDOW_OVERVIEWS) {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      expect(source).toContain("h-[468px]");
    }
  });
});
