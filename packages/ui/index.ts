// packages/ui/index.ts

// Главная страница (/) — исследовательская карта (Task 24).
// HomeHero: H1 + поддерживающий текст + сетка 3×2 из 6 маршрутов.
export { HomeHero } from "./components/HomeHero";
export { HOME_ROUTES } from "./lib/home-stops";
export type { HomeRoute } from "./lib/home-stops";

// Главная страница (/) — секция «Возможности» (Task 27, правка 2026-08-20).
// HomeCapabilities: Block A (4 stat НАД заголовком) + заголовок H2 +
// Block B (3×2 карточек). Block C (manifesto) и section tag убраны по
// решению тимлида. Подключается ТОЛЬКО в standalone — в embedded
// пользователь уже внутри портала, маркетинговый контекст не нужен.
export { HomeCapabilities } from "./components/HomeCapabilities";
export {
  CAPABILITIES_TITLE,
  CAPABILITIES_SUBTITLE,
  CAPABILITY_STATS,
  CAPABILITIES,
} from "./lib/capabilities";
export type { CapabilityStat, Capability } from "./lib/capabilities";

// Навигатор (/navigator) — герой-секция + Путеводитель.
// Перенесено в начало файла: Навигатор — это точка входа в продукт, без него
// непонятно, как читать остальные экспорты. По решению тимлида (вопрос 1a,
// 2026-08-17) — показывается всегда, без auth-ветвления.
export { NavigatorHero } from "./components/NavigatorHero";
export { TsAnalysisNavigator } from "./components/TsAnalysisNavigator";
export {
  NAVIGATOR_STOPS,
  NAVIGATOR_BADGES,
  AUDIENCE_TEXT,
  PURPOSE_TEXT,
  AUDIENCE_LABEL,
  PURPOSE_LABEL,
  OVERVIEW_EXAMPLE_METRICS,
} from "./lib/navigator-stops";
export type {
  NavigatorStop,
  NavigatorStopItem,
  NumberedBadge,
  OverviewExampleMetric,
} from "./lib/navigator-stops";

export { PortalNavBar } from "./components/PortalNavBar";
export { Button } from "./components/Button";
export { Metric } from "./components/Metric";
export { StatusIcon, STATUS_ICON } from "./components/StatusIcon";
export type { CheckStatus } from "./components/StatusIcon";
export { TsAnalysisPreprocessing } from "./components/TsAnalysisPreprocessing";
export { TsAnalysisValidation } from "./components/TsAnalysisValidation";
export { TsAnalysisEDA } from "./components/TsAnalysisEDA";
export { TsAnalysisUpload } from "./components/TsAnalysisUpload";
export { StructuralClassSchema } from "./components/StructuralClassSchema";
export { classifyStructure } from "./lib/structuralClass";
export type { StructuralClass, StructuralClassResult, PanelBalance } from "./lib/structuralClass";
export { default as tailwindPreset } from "./tailwind-preset";

// Глобальный shell: активный датасет (гидрируется с сервера, см.
// apps/api/session_store.py) + прогресс по этапам + лог событий.
export { AppShellProvider, useAppShell } from "./context/AppShellContext";
export type { LogEntry, ActiveDataset } from "./context/AppShellContext";
export { EventsLogDrawer } from "./components/EventsLogDrawer";

// Sessions-aware Home: общий "Рабочий стол" + embedded-онбординг.
// Standalone-версия (с auth-веткой) живёт в apps/standalone/components --
// см. обсуждение с тимлидом про разные ответственности embedded/standalone.
export { WorkbenchSummary } from "./components/WorkbenchSummary";
export { EmbeddedHome } from "./components/EmbeddedHome";
export { STAGE_DEFS } from "./lib/stages";
export type { StageDef, StageStatus } from "./lib/stages";
export { apiUrl, sessionApiUrl, getApiBase, getApiMode } from "./lib/apiClient";
export type { ApiMode } from "./lib/apiClient";

// Навигация между модулями анализа (Загрузка/Валидация/Предобработка/...).
export { ModuleNav } from "./components/ModuleNav";
export { ModulePlaceholder } from "./components/ModulePlaceholder";

// Контракт Роль/План/Возможности (зеркало apps/api/plans.py) -- только для UX,
// реальная защита на бэкенде.
export { getCapabilities, PLAN_DEFINITIONS } from "./lib/plans";
export type { Role, PlanName, Capabilities } from "./lib/plans";
export { TrainModelButton } from "./components/TrainModelButton";

// Графики распределения (Recharts) -- пункт 3 контракта «Загрузки»,
// первая точка подключения на платформе. Экспортируется отдельно,
// чтобы переиспользовать на EDA/Preprocessing после одобрения
// стейкхолдерами (см. договорённость с тимлидом, следующий шаг --
// масштабирование за пределы «Загрузки»).
export {
  ScatterDistributionChart,
  HistogramDistributionChart,
  KdeDistributionChart,
  SamplingBadge,
} from "./components/DistributionCharts";
export type { DistributionChartData, ScatterPoint, HistogramBin, KdePoint } from "./components/DistributionCharts";

// График сравнения бэктестов (Recharts) -- вкладка «Моделирование»,
// второе подключение после «Загрузки» (2026-08-14). Данные -- уже
// накопленный backtestResults компонента, не новый запрос.
export { BacktestComparisonChart } from "./components/BacktestComparisonChart";

// График детализации проверки (Recharts) -- вкладка «Валидация», третье
// подключение после «Загрузки» и «Моделирования» (2026-08-14).
export { ValidationCheckChart } from "./components/ValidationCheckChart";
export type { ValidationCheckData, ValidationCheckItem } from "./components/ValidationCheckChart";
export { ValidationTypeMatrix } from "./components/ValidationTypeMatrix";
export { ValidationTypePipeline } from "./components/ValidationTypePipeline";
export { ValidationFormatPipeline } from "./components/ValidationFormatPipeline";
export { ValidationRangeOverview } from "./components/ValidationRangeOverview";
export { ValidationRangePipeline } from "./components/ValidationRangePipeline";
export type { RangeProfileItem, RangeProfileResponse } from "./components/ValidationRangeOverview";
export { ValidationConsistencyOverview } from "./components/ValidationConsistencyOverview";
export { ValidationConsistencyPipeline } from "./components/ValidationConsistencyPipeline";
export type {
  ConsistencyProfileItem,
  ConsistencyProfileResponse,
} from "./components/ValidationConsistencyOverview";
export { ValidationUniquenessOverview } from "./components/ValidationUniquenessOverview";
export { ValidationUniquenessPipeline } from "./components/ValidationUniquenessPipeline";
export type {
  UniquenessGroup,
  UniquenessProfile,
  UniquenessProfileResponse,
} from "./components/ValidationUniquenessOverview";
export { ValidationInclusionOverview } from "./components/ValidationInclusionOverview";
export { ValidationInclusionPipeline } from "./components/ValidationInclusionPipeline";
export type {
  InclusionProfileItem,
  InclusionProfileResponse,
} from "./components/ValidationInclusionOverview";
export { ValidationReferentialOverview } from "./components/ValidationReferentialOverview";
export { ValidationReferentialPipeline } from "./components/ValidationReferentialPipeline";
export { ValidationTextQualityOverview } from "./components/ValidationTextQualityOverview";
export { ValidationTextQualityPipeline } from "./components/ValidationTextQualityPipeline";
export { ValidationRegularityOverview } from "./components/ValidationRegularityOverview";
export { ValidationRegularityPipeline } from "./components/ValidationRegularityPipeline";
export type {
  ReferentialProfileItem,
  ReferentialProfileResponse,
} from "./components/ValidationReferentialOverview";
export type {
  TextQualityIssueCounts,
  TextQualityProfileItem,
  TextQualityProfileResponse,
} from "./components/ValidationTextQualityOverview";
export type {
  RegularityGroup,
  RegularityProfile,
  RegularityProfileResponse,
} from "./components/ValidationRegularityOverview";
export type {
  TypeValidationMode,
  ValidationSemanticType,
  ValidationTypeProfileItem,
} from "./components/ValidationTypeMatrix";

// Линейный график + бейджи декомпозиции (Recharts) -- остановка «График»
// вкладки «Загрузка», между «Превью датасета» и «Распределение»
// (2026-08-14).
//
// ⚠️ TODO: компоненты TimeSeriesLineChart.tsx и DecompositionBadges.tsx
//    физически отсутствуют в packages/ui/components/ на момент ремонта
//    этого файла. Экспорты закомментированы до их создания — иначе tsc
//    падает с "Cannot find module". Запланированы в задаче подключения
//    реальных графиков в окно «Обзор» Навигатора и в остановку «График»
//    вкладки «Загрузка». Бэкенд-эндпоинты уже готовы:
//      - GET /v1/session/dataset/timeseries
//      - GET /v1/session/dataset/decomposition
//    (см. apps/api/routers/session.py).
//
export { TimeSeriesLineChart } from "./components/TimeSeriesLineChart";
export type { TimeSeriesPoint, TimeSeriesChartData } from "./components/TimeSeriesLineChart";
export { DecompositionBadges } from "./components/DecompositionBadges";
export type { DecompositionData } from "./components/DecompositionBadges";

// График разложенного ряда (Тренд/Сезонность/Цикличность/Остаток) --
// дополнительный график под бейджами декомпозиции (2026-08-19).
export { DecompositionSeriesChart } from "./components/DecompositionSeriesChart";
export type { DecompositionSeriesData, DecompositionSeriesPoint } from "./components/DecompositionSeriesChart";

// ── Ниже: перенесено без изменений из origin/main (команда, "Моделирование") ──

export { TsAnalysisModeling } from "./components/TsAnalysisModeling";

// Типы моделирования (зеркало apps/api/schemas.py).
export type {
  DataProfile,
  ModelCandidate,
  CandidatesRequest,
  CandidatesResponse,
  CandidatesStatistics,
  ApplicabilityLevel,
  PipelineStage,
  ModelFamily,
  BacktestRequest,
  BacktestMetrics,
  BacktestResponse,
  TargetColumnRequest,
  TargetColumnResponse,
} from "./lib/modeling";
export {
  APPLICABILITY_RANK,
  APPLICABILITY_LABEL,
  APPLICABILITY_BADGE,
  MODEL_FAMILIES,
  PIPELINE_STAGES,
  DEFAULT_PROFILE,
  DOMAINS,
  FREQUENCIES,
  BACKTEST_WEIGHTS,
} from "./lib/modeling";

// Панель «Управление правилами» — рендерится внутри TsAnalysisValidation.
export { RulesManagementPanel } from "./components/RulesManagementPanel";

// Блок-схема «Пайплайн автопревью» (Task 22) — статичная информационная
// схема последовательности шагов автопревью в окне «Обзор» Навигатора.
// Рендерится только при активной паре «Загрузка» + «Автопревью и типы
// колонок» (см. TsAnalysisNavigator.tsx). Чисто презентационная, без
// состояния — данные о шагах вынесены в PIPELINE_STEPS для потенциального
// переиспользования в документации/onboarding-туре.
export { UploadAutoPreviewPipeline, PIPELINE_STEPS } from "./components/UploadAutoPreviewPipeline";
export type { PipelineStep } from "./components/UploadAutoPreviewPipeline";
