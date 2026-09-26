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
// Пять списков (факты верифицированы по живому коду @ befdfcf):
//
//  1. REVISION_SUBSCRIBED_CHART_SOURCES (3 файла) — чарт-источники с собственной
//     загрузкой данных (механизм B): каждый export function …Chart обязан
//     принимать refreshKey и включать ревизию в query. Ожидаемое число графиков
//     зафиксировано — появление нового чарта без подписки уронит тест.
//     С волны 3 (RCH-3) канон ЕДИН: `revision=${refreshKey}` — legacy-параметр
//     `_r=` (Task 72) запрещён явным негативом.
//  2. PROFILE_PROP_OVERVIEWS (18 файлов) — Обзоры, чьи графики рендерят данные
//     из profile-пропа контейнера (механизм A): подписка обеспечена deps
//     профильного запроса контейнера. Прямой self-fetch сессионного API
//     (sessionApiUrl) внутри запрещён. Файлы с useChartDetailData
//     (Decomposition/Spectral/StructuralBreaks) — слой C (кэш раскрытия):
//     его инвариант (fingerprint мутации датасета) — волна 2 плана, прямой
//     self-fetch им также запрещён.
//  3. SELF_FETCH_GUARDED_OVERVIEWS (1 файл) — Обзоры с легитимным self-fetch
//     графика, подписанным на refreshKey через requestKey-гвард; с волны 3
//     URL обязан нести canonical cache-buster `revision=${requestKey}`
//     (URL — чистая функция ключа эффекта).
//  4. PROFILE_SELF_FETCH_OVERVIEWS (11 файлов) — Обзоры, самостоятельно
//     запрашивающие СВОЙ профиль с deps [refreshKey] (Пропуски/Выбросы/
//     Регулярность «Предобработки», вся «Валидация»): собственных fetch-ей
//     ДАННЫХ графиков не имеют (таблицы/прогресс-бары; чарты получают
//     refreshKey прокидыванием). Проверяем и самофетч, и подписку.
//  5. REVISION_SUBSCRIBED_SELF_FETCH_SOURCES — источники self-fetch ВНЕ
//     семейства Обзоров (FAMILY_RE, в инвентарь п.6 не входят), того же
//     класса OUTL-1: самофетч хаба «Задачи» (волна 3). Классифицируются
//     здесь явно; контракт тот же — refreshKey в deps, ревизия в query.

import { readFileSync, readdirSync } from "fs";
import { join } from "path";

const REVISION_SUBSCRIBED_CHART_SOURCES = [
  // Волна 1 plan_review_charts.md: «Пропуски» — Матрица/Корреляция/Boxplot
  { file: "PreprocessingMissingVisualizations.tsx", charts: 3 },
  // Эталон OUTL-1 (4ed649f): Линейный/Гистограмма/Плотность/Boxplot
  { file: "PreprocessingOutliersVisualizations.tsx", charts: 4 },
  // Подписаны с Task 72; волна 3 (RCH-3): канонический revision=
  // (до волны — legacy `_r=`, выведен из обращения негативом ниже)
  { file: "PreprocessingRegularityVisualizations.tsx", charts: 2 },
] as const;

// Список 5 (см. шапку): self-fetch вне семейства Обзоров (не Overview/
// Visualizations — в инвентарь списков 1–4 и п.6 НЕ входит).
const REVISION_SUBSCRIBED_SELF_FETCH_SOURCES = [
  // Волна 3 plan_review_charts.md: срез «Причины» хаба «Задачи» —
  // самофетч /tasks/causes по modelingDone; механика B (refreshKey-проп,
  // revision в query fetchCauses).
  { file: "TasksCauses.tsx", lib: "../lib/tasks.ts" },
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
        // Волна 3 (RCH-3): канон один — revision=${refreshKey}; legacy _r=
        // (Task 72) запрещён явным негативом, чтобы унификация не откатилась.
        if (!/revision=\$\{refreshKey/.test(chunk.body)) {
          missing.push("включает каноническую ревизию revision=${refreshKey} в query");
        }
        if (/_r=\$\{refreshKey/.test(chunk.body)) {
          missing.push("несёт legacy-параметр _r=${refreshKey} — только canonical revision=");
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
    "self-fetch графика подписан на refreshKey через requestKey-гвард с canonical revision=: %s",
    (fileName) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      expect(source).toContain("sessionApiUrl(");
      expect(source).toContain("refreshKey");
      expect(source).toContain("requestKey");
      // Волна 3 (RCH-3): URL — чистая функция ключа эффекта — ревизия
      // включается в query (revision=${requestKey}) против HTTP-кэша.
      expect(source).toMatch(/revision=\$\{requestKey/);
    }
  );

  it.each(REVISION_SUBSCRIBED_SELF_FETCH_SOURCES.map((item) => [item.file, item.lib] as const))(
    "self-fetch вне семейства Обзоров подписан на refreshKey с canonical revision=: %s",
    (fileName, libPath) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      expect(source).toContain("refreshKey");
      expect(source).toContain("fetchCauses(");
      // Ревизия строится в query API-хелпером (lib): единственное место,
      // где URL /tasks/causes обрастает cache-buster-ом.
      const libSource = readFileSync(join(__dirname, libPath), "utf8");
      expect(libSource).toContain("revision");
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
