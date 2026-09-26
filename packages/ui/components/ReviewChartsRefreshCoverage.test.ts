// @ts-nocheck

// packages/ui/components/ReviewChartsRefreshCoverage.test.ts
//
// Статический гвард контракта «ревизионный refresh графиков Обзоров»
// (plan_review_charts.md, волна 1; класс дефекта OUTL-1). По прецеденту
// ExpandableChartCoverage.test.ts / AnalysisWorkspaceHeight.test.ts тест НЕ
// рендерит компоненты, а статически проверяет исходники по ЯВНЫМ спискам.
// Списки — единственный источник правды о скоупе: новый Обзор или чарт-источник
// обязан быть классифицирован ровно в одном списке; при переносе файла между
// списками правится ровно одна строка здесь.
//
// Инвариант согласованности (OUTL-1, работаlog8.md 2026-09-25): каждый источник
// данных графика Обзора подписан ТЕМ же сигналом обновления, что профиль/счётчик
// остановки (refreshKey = собственный ключ остановки + datasetVersion), а ревизия
// включается в query как cache-buster — «счётчик обновился ⟹ графики
// перезапросились». Бэкенд не меняется: неизвестный query-параметр FastAPI
// игнорирует.
//
// Четыре списка (факты верифицированы по живому коду @ 564cd95):
//
//  1. REVISION_SUBSCRIBED_CHART_SOURCES (3 файла) — чарт-источники с собственной
//     загрузкой данных (механизм B): каждый export function …Chart обязан
//     принимать refreshKey и включать ревизию в query. Ожидаемое число графиков
//     зафиксировано — появление нового чарта без подписки уронит тест.
//  2. PROFILE_PROP_OVERVIEWS (18 файлов) — Обзоры, чьи графики рендерят данные
//     из profile-пропа контейнера (механизм A): подписка обеспечена deps
//     профильного запроса контейнера. Прямой self-fetch сессионного API
//     (sessionApiUrl) внутри запрещён. Файлы с useChartDetailData
//     (Decomposition/Spectral/StructuralBreaks) — слой C (кэш раскрытия):
//     его инвариант (fingerprint мутации датасета) — волна 2 плана, прямой
//     self-fetch им также запрещён.
//  3. SELF_FETCH_GUARDED_OVERVIEWS (1 файл) — Обзоры с легитимным self-fetch
//     графика, подписанным на refreshKey через requestKey-гвард.
//  4. PROFILE_SELF_FETCH_OVERVIEWS (11 файлов) — Обзоры, самостоятельно
//     запрашивающие СВОЙ профиль с deps [refreshKey] (Пропуски/Выбросы/
//     Регулярность «Предобработки», вся «Валидация»): собственных fetch-ей
//     ДАННЫХ графиков не имеют (таблицы/прогресс-бары; чарты получают
//     refreshKey прокидыванием). Проверяем и самофетч, и подписку.

import { readFileSync, readdirSync } from "fs";
import { join } from "path";

const REVISION_SUBSCRIBED_CHART_SOURCES = [
  // Волна 1 plan_review_charts.md: «Пропуски» — Матрица/Корреляция/Boxplot
  { file: "PreprocessingMissingVisualizations.tsx", charts: 3 },
  // Эталон OUTL-1 (4ed649f): Линейный/Гистограмма/Плотность/Boxplot
  { file: "PreprocessingOutliersVisualizations.tsx", charts: 4 },
  // Подписаны с Task 72 (_r= — функционально тот же cache-buster)
  { file: "PreprocessingRegularityVisualizations.tsx", charts: 2 },
] as const;

const PROFILE_PROP_OVERVIEWS = [
  // Preprocessing — графики из profile-пропа (7)
  "PreprocessingDecompositionOverview.tsx",
  "PreprocessingFeatureEngineeringOverview.tsx",
  "PreprocessingScalingOverview.tsx",
  "PreprocessingSmoothingOverview.tsx",
  "PreprocessingStationarityOverview.tsx",
  "PreprocessingSpectralOverview.tsx",
  "PreprocessingVarianceOverview.tsx",
  // EDA — графики из profile-пропа (9; Descriptive — в списке 3,
  // StructuralBreaks — слой C раскрытия, прямой self-fetch также запрещён)
  "EdaCorrelationOverview.tsx",
  "EdaDistributionOverview.tsx",
  "EdaFeatureSelectionOverview.tsx",
  "EdaIhOverview.tsx",
  "EdaModelMatrixOverview.tsx",
  "EdaSeasonalityOverview.tsx",
  "EdaStationarityOverview.tsx",
  "EdaStructuralBreaksOverview.tsx",
  "EdaValidationStrategyOverview.tsx",
  // Modeling — контекст/действия пользователя (workflow POST-ы — не self-fetch
  // данных графиков сессионного API)
  "ModelingTraceabilityOverview.tsx",
  "ModelingWorkflowOverview.tsx",
] as const;

const SELF_FETCH_GUARDED_OVERVIEWS = [
  // Единственный self-fetch графика в EDA — /dataset/distribution с
  // requestKey-гвардом requestKey = `${refreshKey}:${activeFeature}`
  "EdaDescriptiveOverview.tsx",
] as const;

const PROFILE_SELF_FETCH_OVERVIEWS = [
  // Preprocessing — Обзоры остановок с прокидыванием refreshKey в чарты
  "PreprocessingMissingOverview.tsx",
  "PreprocessingOutliersOverview.tsx",
  "PreprocessingRegularityOverview.tsx",
  // Validation — самофетч профиля с deps [refreshKey={validationVersion}]
  "ValidationConsistencyOverview.tsx",
  "ValidationInclusionOverview.tsx",
  "ValidationRangeOverview.tsx",
  "ValidationReferentialOverview.tsx",
  "ValidationRegularityOverview.tsx",
  "ValidationSufficiencyOverview.tsx",
  "ValidationTextQualityOverview.tsx",
  "ValidationUniquenessOverview.tsx",
] as const;

const FAMILY_RE = /(Overview|Visualizations)\.tsx$/;
const FAMILY_TOTAL = 33;

function chartChunksOf(source: string): Array<{ name: string; body: string }> {
  return source
    .split("export function ")
    .slice(1)
    .map((chunk) => ({
      name: (chunk.match(/^(\w+)\(/) ?? [])[1] ?? "",
      body: chunk,
    }));
}

describe("ReviewChartsRefreshCoverage: гвард подписки графиков Обзоров на refresh", () => {
  it.each(REVISION_SUBSCRIBED_CHART_SOURCES.map((item) => [item.file, item.charts] as const))(
    "каждый чарт источника подписан на refreshKey с ревизией в query: %s",
    (fileName, expectedCharts) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      const chunks = chartChunksOf(source).filter((chunk) => chunk.name.endsWith("Chart"));

      expect(`${fileName}: ровно ${expectedCharts} экспортированных чартов`).toBe(
        `${fileName}: ровно ${chunks.length} экспортированных чартов`
      );

      for (const chunk of chunks) {
        const missing: string[] = [];
        if (!chunk.body.includes("refreshKey")) {
          missing.push("принимает refreshKey");
        }
        if (!/(revision|_r)=\$\{refreshKey/.test(chunk.body)) {
          missing.push("включает ревизию (revision|_r)=${refreshKey} в query");
        }
        expect(`${fileName}/${chunk.name}: ${missing.join(", ")}`).toBe(`${fileName}/${chunk.name}: `);
      }
    }
  );

  it.each(PROFILE_PROP_OVERVIEWS)(
    "графики рендерят profile-проп, прямой self-fetch сессионного API запрещён: %s",
    (fileName) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      expect(source).not.toContain("sessionApiUrl(");
    }
  );

  it.each(SELF_FETCH_GUARDED_OVERVIEWS)(
    "self-fetch графика подписан на refreshKey через requestKey-гвард: %s",
    (fileName) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      expect(source).toContain("sessionApiUrl(");
      expect(source).toContain("refreshKey");
      expect(source).toContain("requestKey");
    }
  );

  it.each(PROFILE_SELF_FETCH_OVERVIEWS)(
    "самофетч СВОЕГО профиля подписан на refreshKey (графиков с собственным fetch нет): %s",
    (fileName) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      expect(source).toContain("sessionApiUrl(");
      expect(source).toContain("refreshKey");
    }
  );

  it("списки подписки покрывают весь инвентарь Обзор/Visualizations-семейства (33 файла), без пропусков и дублей", () => {
    const declared = [
      ...REVISION_SUBSCRIBED_CHART_SOURCES.map((item) => item.file),
      ...PROFILE_PROP_OVERVIEWS,
      ...SELF_FETCH_GUARDED_OVERVIEWS,
      ...PROFILE_SELF_FETCH_OVERVIEWS,
    ];
    const declaredSet = new Set(declared);

    expect(declared.length).toBe(declaredSet.size);
    expect(declaredSet.size).toBe(FAMILY_TOTAL);

    const actual = readdirSync(__dirname).filter(
      (f) => FAMILY_RE.test(f) && !f.includes(".test.")
    );
    expect([...declaredSet].sort()).toEqual(actual.sort());
  });
});
