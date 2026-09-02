// packages/ui/index.ts

// Главная страница (/) — исследовательская карта (Task 24).
// HomeHero: H1 + поддерживающий текст + сетка 3×2 из 6 маршрутов.
export { HomeHero } from "./components/HomeHero";
export { RouteCard } from "./components/RouteCard";
export type { RouteCardProps } from "./components/RouteCard";
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
export { PlatformIntroduction } from "./components/PlatformIntroduction";
export { AppliedTasksNavigator } from "./components/AppliedTasksNavigator";
export {
  NAVIGATOR_STOPS,
  NAVIGATOR_BADGES,
  NAVIGATOR_SECTION_ROUTES,
  AUDIENCE_TEXT,
  PURPOSE_TEXT,
  AUDIENCE_LABEL,
  PURPOSE_LABEL,
  OVERVIEW_EXAMPLE_METRICS,
} from "./lib/navigator-stops";
export {
  APPLIED_TASK_DOMAINS,
  APPLIED_TASK_KINDS,
  APPLIED_TASK_MATRIX,
  getAppliedTaskExamples,
} from "./lib/applied-tasks";
export type {
  AppliedTaskDomain,
  AppliedTaskDomainId,
  AppliedTaskExample,
  AppliedTaskKind,
  AppliedTaskKindId,
} from "./lib/applied-tasks";
export type {
  NavigatorStop,
  NavigatorStopItem,
  NumberedBadge,
  NavigatorSectionRoute,
  OverviewExampleMetric,
} from "./lib/navigator-stops";

export { PortalNavBar } from "./components/PortalNavBar";
export { Button } from "./components/Button";
export { Metric } from "./components/Metric";
export { StatusIcon, STATUS_ICON } from "./components/StatusIcon";
export type { CheckStatus } from "./components/StatusIcon";
export { TsAnalysisPreprocessing } from "./components/TsAnalysisPreprocessing";
export { PreprocessingDecompositionOverview } from "./components/PreprocessingDecompositionOverview";
export type {
  PreprocessingDecompositionPoint,
  PreprocessingDecompositionProfile,
  PreprocessingDecompositionProfileResponse,
} from "./components/PreprocessingDecompositionOverview";
export { PreprocessingDecompositionPipeline } from "./components/PreprocessingDecompositionPipeline";
export { PreprocessingVarianceOverview } from "./components/PreprocessingVarianceOverview";
export type {
  VarianceMethod,
  VarianceDiagnostics,
  VarianceProfile,
  VarianceProfileResponse,
} from "./components/PreprocessingVarianceOverview";
export { PreprocessingVariancePipeline } from "./components/PreprocessingVariancePipeline";
export { PreprocessingSmoothingOverview } from "./components/PreprocessingSmoothingOverview";
export type {
  SmoothingMethod,
  SmoothingDiagnostics,
  SmoothingProfile,
  SmoothingProfileResponse,
} from "./components/PreprocessingSmoothingOverview";
export { PreprocessingSmoothingPipeline } from "./components/PreprocessingSmoothingPipeline";
export { PreprocessingStationarityOverview } from "./components/PreprocessingStationarityOverview";
export type {
  StationarityConsensus as PreprocessingStationarityConsensus,
  StationarityTransformMethod,
  StationarityProfileMethod,
  StationarityProfile,
  StationarityProfileResponse,
} from "./components/PreprocessingStationarityOverview";
export { PreprocessingStationarityPipeline } from "./components/PreprocessingStationarityPipeline";
export { PreprocessingSpectralOverview } from "./components/PreprocessingSpectralOverview";
export type {
  PreprocessingSpectralProfile,
  PreprocessingSpectralProfileResponse,
  SpectralCandidate,
  SpectralPoint,
  SpectralWelchPoint,
  SpectralWaveletPoint,
} from "./components/PreprocessingSpectralOverview";
export { PreprocessingSpectralPipeline } from "./components/PreprocessingSpectralPipeline";
export type { SpectralParameters } from "./components/PreprocessingSpectralPipeline";
export { PreprocessingFeatureEngineeringOverview } from "./components/PreprocessingFeatureEngineeringOverview";
export type {
  CalendarFeature,
  FeatureCatalogItem,
  FeatureFamily,
  FeatureGenerationProfile,
  FeatureGenerationProfileResponse,
} from "./components/PreprocessingFeatureEngineeringOverview";
export { PreprocessingFeatureEngineeringPipeline } from "./components/PreprocessingFeatureEngineeringPipeline";
export { TsAnalysisValidation } from "./components/TsAnalysisValidation";
export { ValidationSufficiencyOverview } from "./components/ValidationSufficiencyOverview";
export { ValidationSufficiencyPipeline } from "./components/ValidationSufficiencyPipeline";
export type { SufficiencyProfile, SufficiencyGroup, SufficiencyCheck } from "./components/ValidationSufficiencyOverview";
export { TsAnalysisEDA } from "./components/TsAnalysisEDA";
export { EdaDescriptiveOverview } from "./components/EdaDescriptiveOverview";
export type {
  DescriptiveColumnStats,
  DescriptiveStatsResponse,
  DescriptiveStatsValues,
} from "./components/EdaDescriptiveOverview";
export { EdaCorrelationOverview } from "./components/EdaCorrelationOverview";
export type {
  EdaCorrelationPoint,
  EdaCorrelationResponse,
} from "./components/EdaCorrelationOverview";
export { EdaIhOverview } from "./components/EdaIhOverview";
export type {
  EdaIhConditionalRow,
  EdaIhFeature,
  EdaIhParameters,
  EdaIhResponse,
  EdaIhSynergy,
} from "./components/EdaIhOverview";
export { EdaSeasonalityOverview } from "./components/EdaSeasonalityOverview";
export type {
  EdaSeasonalityCandidate,
  EdaSeasonalityParameters,
  EdaSeasonalityPhasePoint,
  EdaSeasonalityResponse,
  EdaSpectrumPoint,
} from "./components/EdaSeasonalityOverview";
export { EdaStationarityOverview } from "./components/EdaStationarityOverview";
export type {
  EdaStationarityParameters,
  EdaStationarityResponse,
  EdaStationarityRollingPoint,
  EdaStationarityTest,
  StationarityConsensus,
} from "./components/EdaStationarityOverview";
export { EdaDistributionOverview } from "./components/EdaDistributionOverview";
export type {
  DistributionNormalityStatus,
  EdaDistributionParameters,
  EdaDistributionResponse,
  EdaDistributionTest,
} from "./components/EdaDistributionOverview";
export { EdaStructuralBreaksOverview } from "./components/EdaStructuralBreaksOverview";
export type {
  EdaStructuralBreaksParameters,
  EdaStructuralBreaksResponse,
} from "./components/EdaStructuralBreaksOverview";
export { EdaFeatureSelectionOverview } from "./components/EdaFeatureSelectionOverview";
export type {
  EdaFeatureSelectionItem,
  EdaFeatureSelectionParameters,
  EdaFeatureSelectionResponse,
  FeatureDecision,
} from "./components/EdaFeatureSelectionOverview";
export { EdaValidationStrategyOverview } from "./components/EdaValidationStrategyOverview";
export type {
  EdaValidationAlternative,
  EdaValidationFold,
  EdaValidationStrategyParameters,
  EdaValidationStrategyResponse,
  ValidationStrategy,
} from "./components/EdaValidationStrategyOverview";
export { EdaModelMatrixOverview } from "./components/EdaModelMatrixOverview";
export type {
  EdaModelCriterion,
  EdaModelMatrixFamily,
  EdaModelMatrixModel,
  EdaModelMatrixParameters,
  EdaModelMatrixResponse,
  ModelCompatibility,
  ModelCriterionStatus,
  ModelMatrixTask,
} from "./components/EdaModelMatrixOverview";
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

// Статичный линейный график для окна «Обзор» остановки «График»
// (id="chart") секции «Этапы модуля» остановки «Загрузка» (Task 2026-08-29).
// Рендерится только при активной паре «Загрузка» + «График»
// (см. TsAnalysisNavigator.tsx). Чисто презентационный, БЕЗ зависимости
// от useAppShell / activeDataset / сети — данные берутся из
// детерминированного генератора демо-датасета demo_finance_ohlcv.csv
// (getDemoFinanceOhlcvVolumeSeries). Отображается при любых условиях,
// даже если сам датасет удалён из сессии.
export { NavigatorChartPreview } from "./components/NavigatorChartPreview";
export {
  NAVIGATOR_CHART_PREVIEW_DATASET_ID,
  NAVIGATOR_CHART_PREVIEW_DATASET_FILE,
  NAVIGATOR_CHART_PREVIEW_FEATURE,
} from "./components/NavigatorChartPreview";
export {
  getDemoFinanceOhlcvVolumeSeries,
} from "./lib/demoDatasets";
export type { NavigatorChartPoint } from "./lib/demoDatasets";

// Статичная блок-схема алгоритма автоопределения структуры для окна
// «Обзор» остановки «Подтверждение автоопределения» (id="structure_confirm")
// секции «Этапы модуля» остановки «Загрузка» (Task 2026-08-30).
// Рендерится только при активной паре «Загрузка» + «Подтверждение
// автоопределения» (см. TsAnalysisNavigator.tsx). Чисто презентационная,
// БЕЗ зависимости от useAppShell / activeDataset / сети — основана на
// РЕАЛЬНОЙ бэкенд-логике (apps/api/routers/session.py::
// get_structure_detection, app/data/detectors.py). Аналитик мгновенно
// понимает алгоритм: 3 параллельных детектора (date / entity / frequency)
// → StructureDetectionResponse → можно поправить вручную.
export { NavigatorStructureConfirmPreview } from "./components/NavigatorStructureConfirmPreview";

// Статичная блок-схема подсчёта счётчиков качества для окна «Обзор»
// остановки «Teaser качества» (id="quality_teaser") секции «Этапы
// модуля» остановки «Загрузка» (Task 2026-08-30).
// Рендерится только при активной паре «Загрузка» + «Teaser качества»
// (см. TsAnalysisNavigator.tsx). Чисто презентационная, БЕЗ зависимости
// от useAppShell / activeDataset / сети — основана на РЕАЛЬНОЙ
// бэкенд-логике (apps/api/upload_common.py::_compute_quality_teaser,
// apps/api/schemas.py::QualityTeaserOut, отдаётся внутри UploadResponse.quality).
// Аналитик мгновенно понимает: 4 счётчика (missing / outliers / rows /
// duplicates) → QualityTeaserOut → статус warning если любой из 3 > 0.
export { NavigatorQualityTeaserPreview } from "./components/NavigatorQualityTeaserPreview";

// Статичная блок-схема технической информации по колонкам для окна
// «Обзор» остановки «Техническая информация» (id="tech_info") секции
// «Этапы модуля» остановки «Загрузка» (Task 2026-08-31).
// Рендерится только при активной паре «Загрузка» + «Техническая
// информация» (см. TsAnalysisNavigator.tsx). Чисто презентационная,
// БЕЗ зависимости от useAppShell / activeDataset / сети — основана на
// РЕАЛЬНОЙ бэкенд-логике (apps/api/upload_common.py::_compute_column_info,
// apps/api/schemas.py::ColumnInfoOut, отдаётся внутри UploadResponse.columns_info).
// Аналитик мгновенно понимает: 4 ветки type_icon по dtype (datetime →
// numeric → categorical → text, if/elif chain) + 3 метрики (non_null /
// nulls / unique) → ColumnInfoOut[] → таблица 5 колонок во вкладке Загрузка.
export { NavigatorTechInfoPreview } from "./components/NavigatorTechInfoPreview";

// Статичная таблица превью 5+5 строк для окна «Обзор» остановки
// «Превью 5+5 строк» (id="preview_5_5") секции «Этапы модуля» остановки
// «Загрузка» (Task 2026-09-01).
// Рендерится только при активной паре «Загрузка» + «Превью 5+5 строк»
// (см. TsAnalysisNavigator.tsx). Чисто презентационная, БЕЗ зависимости
// от useAppShell / activeDataset / сети — данные берутся из
// детерминированного генератора демо-датасета demo_finance_ohlcv.csv
// (getDemoFinanceOhlcvPreview55, тот же seed, что у NavigatorChartPreview).
// Превью закреплено статично как пример и сохраняется вне зависимости,
// удалён датасет или нет.
export { NavigatorPreview55Preview } from "./components/NavigatorPreview55Preview";
export {
  NAVIGATOR_PREVIEW55_DATASET_FILE,
  NAVIGATOR_PREVIEW55_FEATURE,
} from "./components/NavigatorPreview55Preview";
export {
  getDemoFinanceOhlcvPreview55,
} from "./lib/demoDatasets";
export type { Preview55Data } from "./lib/demoDatasets";

// Статичная визуализация распределения для окна «Обзор» остановки
// «Визуализация распределения» (id="distribution") секции «Этапы модуля»
// остановки «Загрузка» (Task 2026-09-02).
// Рендерится только при активной паре «Загрузка» + «Визуализация
// распределения» (см. TsAnalysisNavigator.tsx). Чисто презентационная,
// БЕЗ зависимости от useAppShell / activeDataset / сети — данные берутся
// из детерминированного генератора демо-датасета demo_energy_consumption.csv
// (getDemoEnergyDistributionData, тот же seed, что у демо-датасета
// «Энергопотребление по регионам» во вкладке «Загрузка»). Переиспользует
// существующие ScatterDistributionChart/HistogramDistributionChart/
// KdeDistributionChart из DistributionCharts.tsx + 8 Metric-бейджей.
// Визуализация закреплена статично как пример и сохраняется вне
// зависимости, удалён датасет или нет.
export { NavigatorDistributionPreview } from "./components/NavigatorDistributionPreview";
export {
  NAVIGATOR_DISTRIBUTION_DATASET_FILE,
  NAVIGATOR_DISTRIBUTION_FEATURE,
} from "./components/NavigatorDistributionPreview";
export {
  getDemoEnergyDistributionData,
} from "./lib/demoDatasets";
export type {
  DistributionStats,
  DistributionPreviewData,
} from "./lib/demoDatasets";
