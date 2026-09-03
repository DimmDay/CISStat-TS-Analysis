# apps/api/schemas.py
"""
Pydantic-схемы запросов/ответов. Форма ответов передаёт структуру,
которую реально возвращают app/core/passport.py и app/validation/regularity.py
(мы её проверяли построчно за этот разговор) -- не выдумана заново.
"""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class SeriesPoint(BaseModel):
    date: str
    value: Optional[float] = None


class PassportRequest(BaseModel):
    series: List[SeriesPoint] = Field(..., min_length=1)
    target_col: Optional[str] = None


class PassportResponse(BaseModel):
    # Соответствует ключам, которые реально возвращает calculate_ts_passport:
    # freq, stationarity, determinism, autocorrelation, normality, trend,
    # correlations, seasonality, seasonal_periods, hurst, fft, periodogram,
    # wavelet, basic_stats, timestamp (+ error_log при передаче).
    freq: Optional[Dict[str, Any]] = None
    stationarity: Optional[Dict[str, Any]] = None
    determinism: Optional[Dict[str, Any]] = None
    autocorrelation: Optional[Dict[str, Any]] = None
    normality: Optional[Dict[str, Any]] = None
    trend: Optional[Dict[str, Any]] = None
    correlations: Optional[Dict[str, Any]] = None
    seasonality: Optional[Dict[str, Any]] = None
    seasonal_periods: Optional[Dict[str, Any]] = None
    hurst: Optional[Dict[str, Any]] = None
    fft: Optional[Dict[str, Any]] = None
    periodogram: Optional[Dict[str, Any]] = None
    wavelet: Optional[Dict[str, Any]] = None
    basic_stats: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    error: Optional[str] = None


class RegularityRequest(BaseModel):
    series: List[SeriesPoint] = Field(..., min_length=1)
    entity_col: Optional[str] = None
    gap_threshold_multiplier: float = 1.5


class RegularityResponse(BaseModel):
    gaps_count: int
    freq_info: Dict[str, Any]
    error: Optional[str] = None


class PreviewData(BaseModel):
    """Предпросмотр данных: первые и последние 5 строк."""
    head: List[List[str]] = Field(..., description="Первые 5 строк (включая заголовки)")
    tail: List[List[str]] = Field(..., description="Последние 5 строк")

class ColumnInfoOut(BaseModel):
    """Техническая информация по колонке -- секция «Техническая информация»
    контракта вкладки «Загрузка» (см. TsAnalysisUpload.tsx)."""
    name: str
    dtype: str
    type_icon: str = Field(..., description="numeric | datetime | categorical | text")
    non_null: int
    nulls: int
    unique: int


class ValidationTypeProfileOut(ColumnInfoOut):
    """Профиль dtype с результатом сверки с пользовательским эталоном."""
    expected_type: Optional[str] = None
    validation_status: Literal["matched", "mismatch", "profile"] = "profile"
    violations: Optional[int] = None


class QualityTeaserOut(BaseModel):
    """Только счётчики -- содержательный анализ проблем качества живёт в
    модуле «Валидация», не здесь (по контракту вкладки «Загрузка")."""
    cols_with_missing: int
    cols_with_outliers: int
    rows_total: int
    duplicates: int
    missing_cols: List[str]
    outlier_cols: List[str]


class UploadResponse(BaseModel):
    """Ответ на загрузку файла."""
    dataset_id: str = Field(..., description="Уникальный идентификатор датасета")
    name: str = Field(..., description="Имя файла")
    rows: int = Field(..., description="Количество строк")
    columns: int = Field(..., description="Количество колонок")
    preview: PreviewData = Field(..., description="Предпросмотр данных")
    columns_info: Optional[List[ColumnInfoOut]] = Field(
        None, description="Тех. информация по каждой колонке (dtype/nulls/unique)"
    )
    quality: Optional[QualityTeaserOut] = Field(
        None, description="Предварительная оценка качества (только счётчики)"
    )
    size_label: Optional[str] = Field(None, description="Размер файла (KB/MB) — для UI")
    parse_warnings: List[str] = Field(
        default_factory=list,
        description="Технические флаги парсинга (кодировка, неверно определённый заголовок) -- пункт 7 контракта вкладки «Загрузка»",
    )
    error: Optional[str] = Field(None, description="Ошибка при загрузке")


class ColumnStatsValues(BaseModel):
    mean: float
    median: float
    std: float
    skewness: Optional[float] = Field(None, description="Недоступно при N < 3")
    kurtosis: Optional[float] = Field(None, description="Недоступно при N < 4")
    q1: float
    q3: float
    iqr: float
    distribution_hint: str = Field(
        ..., description="Грубая эвристика по skew/kurtosis (не замена KS-теста в «Моделировании»)"
    )


class ColumnStatsOut(BaseModel):
    """Описательная статистика по числовой колонке -- пункт 4 контракта
    вкладки «Загрузка». Реальный расчёт (pandas/scipy) над полным
    столбцом, хранящимся в AnalysisSession, а не над превью.

    Колонка МОЖЕТ не иметь статистики (реальные данные часто разрежены --
    например, панельные цены ФАО по странам/годам) -- в этом случае
    stats=None, а non_null_count честно объясняет почему, вместо того
    чтобы колонка тихо пропадала из ответа без объяснения."""
    name: str
    non_null_count: int
    stats: Optional[ColumnStatsValues] = None


class DatasetStatsResponse(BaseModel):
    columns: List[ColumnStatsOut]
    min_non_null_for_stats: int = Field(2, description="Порог непустых значений, ниже которого статистика не считается")


class EdaCorrelationPoint(BaseModel):
    lag: int
    value: float
    confidence_lower: float
    confidence_upper: float
    significant: bool


class DatasetEdaCorrelationResponse(BaseModel):
    """ACF/PACF-профиль одного исследуемого временного ряда."""
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int
    missing_count: int
    requested_max_lags: int
    max_lag: int
    alpha: float
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    order_warning: Optional[str] = None
    frequency: Optional[str] = None
    acf: List[EdaCorrelationPoint] = Field(default_factory=list)
    pacf: List[EdaCorrelationPoint] = Field(default_factory=list)
    significant_acf_lags: List[int] = Field(default_factory=list)
    significant_pacf_lags: List[int] = Field(default_factory=list)
    ljung_box_lag: Optional[int] = None
    ljung_box_pvalue: Optional[float] = None
    is_white_noise: Optional[bool] = None
    suggested_p: Optional[int] = None
    suggested_q: Optional[int] = None


class EdaIhFeatureOut(BaseModel):
    feature: str
    kind: Literal["numeric", "categorical", "lag"]
    dtype: str
    n_observations: int
    r: float
    r_adjusted: float
    mi: float
    h_x: float
    h_y: float
    n_bins_x: int
    n_bins_y: int
    permutation_baseline: float
    p_value: float
    q_value: float
    significant: bool
    error: Optional[str] = None


class EdaIhSynergyOut(BaseModel):
    pair: str
    feature_1: str
    feature_2: str
    r_1: float
    r_2: float
    r_combined: float
    incremental_gain: float
    interaction_delta: float


class EdaIhConditionalRow(BaseModel):
    x_bin: str
    values: List[float]


class DatasetEdaIhResponse(BaseModel):
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int
    features_analyzed: int
    sharpness: float
    min_samples: int
    top_k: int
    max_lag: int
    permutations: int
    target_entropy: Optional[float] = None
    target_bins: int
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    order_warning: Optional[str] = None
    frequency: Optional[str] = None
    lag_features_included: bool
    results: List[EdaIhFeatureOut] = Field(default_factory=list)
    synergies: List[EdaIhSynergyOut] = Field(default_factory=list)
    conditional_feature: Optional[str] = None
    conditional_x_bins: List[str] = Field(default_factory=list)
    conditional_y_bins: List[str] = Field(default_factory=list)
    conditional_matrix: List[EdaIhConditionalRow] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class EdaSpectrumPoint(BaseModel):
    frequency: float
    period: float
    amplitude: Optional[float] = None
    power: Optional[float] = None
    is_peak: bool


class EdaSeasonalityCandidateOut(BaseModel):
    rank: int
    period: float
    period_rounded: int
    frequency: float
    amplitude: float
    power: float
    power_share: float
    prominence: float
    spectral_snr: float
    autocorrelation: float
    seasonal_strength: float
    cycles: float
    confirmed: bool
    calendar_hint: Optional[str] = None
    harmonic_of: Optional[float] = None


class EdaSeasonalityPhasePoint(BaseModel):
    phase: int
    mean: float
    lower: float
    upper: float
    count: int


class DatasetEdaSeasonalityResponse(BaseModel):
    """Спектральный и фазовый профиль одного равномерного временного ряда."""
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int
    missing_count: int
    min_cycles: int
    max_candidates: int
    max_period: Optional[float] = None
    detrend: Literal["linear"]
    window: Literal["hann"]
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    order_warning: Optional[str] = None
    frequency: Optional[str] = None
    spectral_entropy: Optional[float] = None
    dominant_period: Optional[float] = None
    dominant_strength: Optional[float] = None
    confirmed_periods: int
    fft: List[EdaSpectrumPoint] = Field(default_factory=list)
    periodogram: List[EdaSpectrumPoint] = Field(default_factory=list)
    candidates: List[EdaSeasonalityCandidateOut] = Field(default_factory=list)
    phase_period: Optional[int] = None
    phase_profile: List[EdaSeasonalityPhasePoint] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class EdaStationarityTestOut(BaseModel):
    id: Literal[
        "adf_level",
        "adf_trend",
        "kpss_level",
        "kpss_trend",
        "pp",
        "zivot_andrews",
    ]
    label: str
    null_hypothesis: str
    alternative_hypothesis: str
    available: bool
    statistic: Optional[float] = None
    p_value: Optional[float] = None
    lags: Optional[int] = None
    reject_null: Optional[bool] = None
    supports_stationarity: Optional[bool] = None
    critical_values: Dict[str, float] = Field(default_factory=dict)
    note: Optional[str] = None


class EdaStationarityRollingPointOut(BaseModel):
    index: int
    label: Optional[str] = None
    value: float
    rolling_mean: Optional[float] = None
    rolling_std: Optional[float] = None


class DatasetEdaStationarityResponse(BaseModel):
    """Комплементарные unit-root тесты и скользящие диагностики ряда."""
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int
    missing_count: int
    min_observations: int = 30
    alpha: float
    requested_rolling_window: int
    rolling_window: int
    consensus: Optional[Literal[
        "stationary",
        "trend-stationary",
        "non-stationary",
        "inconclusive",
    ]] = None
    recommendation: Optional[str] = None
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    order_warning: Optional[str] = None
    frequency: Optional[str] = None
    breakpoint_index: Optional[int] = None
    breakpoint_label: Optional[str] = None
    tests: List[EdaStationarityTestOut] = Field(default_factory=list)
    rolling: List[EdaStationarityRollingPointOut] = Field(default_factory=list)
    rolling_sampled: bool = False
    rolling_original_count: int
    recommendations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class EdaDistributionTestOut(BaseModel):
    id: Literal["shapiro", "jarque_bera", "lilliefors"]
    label: str
    available: bool
    statistic: Optional[float] = None
    p_value: Optional[float] = None
    adjusted_p_value: Optional[float] = None
    reject_normality: Optional[bool] = None
    n_used: Optional[int] = None
    calibration: Optional[Literal["standard", "monte_carlo", "asymptotic", "table"]] = None
    note: Optional[str] = None


class EdaDistributionHistogramBinOut(BaseModel):
    x0: float
    x1: float
    count: int
    density: float
    normal_expected_count: float


class EdaDistributionDensityPointOut(BaseModel):
    x: float
    empirical: float
    normal: float


class EdaDistributionQqPointOut(BaseModel):
    theoretical: float
    observed: float
    reference: float


class EdaDistributionCdfPointOut(BaseModel):
    x: float
    empirical: float
    normal: float


class DatasetEdaDistributionResponse(BaseModel):
    """Форма распределения, тесты нормальности и графические диагностики."""
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int
    missing_count: int
    min_observations: int = 8
    alpha: float
    requested_bins: int
    bins: int
    is_discrete: bool
    unique_count: int
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    q1: Optional[float] = None
    q3: Optional[float] = None
    iqr: Optional[float] = None
    mad: Optional[float] = None
    skewness: Optional[float] = None
    excess_kurtosis: Optional[float] = None
    shape_label: str
    normality_applicable: bool
    normality_status: Literal["compatible", "departed", "inconclusive", "not_applicable"]
    qq_r: Optional[float] = None
    qq_slope: Optional[float] = None
    qq_intercept: Optional[float] = None
    tests: List[EdaDistributionTestOut] = Field(default_factory=list)
    histogram: List[EdaDistributionHistogramBinOut] = Field(default_factory=list)
    density: List[EdaDistributionDensityPointOut] = Field(default_factory=list)
    qq: List[EdaDistributionQqPointOut] = Field(default_factory=list)
    cdf: List[EdaDistributionCdfPointOut] = Field(default_factory=list)
    recommendation: Optional[str] = None
    recommendations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class EdaStructuralCusumOut(BaseModel):
    statistic: Optional[float] = None
    p_value: Optional[float] = None
    reject_stability: Optional[bool] = None
    critical_values: Dict[str, float] = Field(default_factory=dict)


class EdaStructuralCandidateOut(BaseModel):
    rank: int
    index: int
    label: Optional[str] = None
    level_change: float
    standardized_level_change: float
    slope_before: float
    slope_after: float
    slope_change: float
    rss_gain: float
    chow_statistic: float
    p_value: float
    adjusted_p_value: Optional[float] = None
    chow_reject_stability: Optional[bool] = None
    stability_support: float
    supported: bool


class EdaStructuralSegmentOut(BaseModel):
    id: int
    start_index: int
    end_index: int
    start_label: Optional[str] = None
    end_label: Optional[str] = None
    n_observations: int
    mean: float
    std: float
    slope: float


class EdaStructuralSeriesPointOut(BaseModel):
    index: int
    label: Optional[str] = None
    value: float
    fitted: float
    segment_id: int


class EdaStructuralCusumPointOut(BaseModel):
    index: int
    label: Optional[str] = None
    value: float
    upper: float
    lower: float


class EdaStructuralSensitivityPointOut(BaseModel):
    penalty_multiplier: float
    index: int
    label: Optional[str] = None


class DatasetEdaStructuralBreaksResponse(BaseModel):
    """Глобальная стабильность, локализация режимов и чувствительность."""
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int
    missing_count: int
    min_observations: int = 60
    alpha: float
    requested_min_segment: int
    min_segment: int
    requested_penalty_multiplier: float
    penalty_multiplier: float
    penalty_value: Optional[float] = None
    max_breaks: int
    jump: int
    model: Literal["piecewise_linear"]
    status: Literal["breaks_detected", "candidates_only", "global_instability", "stable", "not_applicable"]
    break_count: int
    supported_count: int
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    order_warning: Optional[str] = None
    frequency: Optional[str] = None
    cusum: EdaStructuralCusumOut
    candidates: List[EdaStructuralCandidateOut] = Field(default_factory=list)
    segments: List[EdaStructuralSegmentOut] = Field(default_factory=list)
    series: List[EdaStructuralSeriesPointOut] = Field(default_factory=list)
    cusum_path: List[EdaStructuralCusumPointOut] = Field(default_factory=list)
    sensitivity: List[EdaStructuralSensitivityPointOut] = Field(default_factory=list)
    series_sampled: bool = False
    series_original_count: int
    cusum_sampled: bool = False
    recommendation: Optional[str] = None
    recommendations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class EdaFeatureCorrelationCellOut(BaseModel):
    row: str
    column: str
    pearson: float
    spearman: float


class EdaFeatureItemOut(BaseModel):
    name: str
    n_observations: int
    pearson: float
    spearman: float
    vif: Optional[float] = None
    vif_infinite: bool
    max_abs_predictor_correlation: float
    granger_available: bool
    best_granger_lag: Optional[int] = None
    granger_p_value: Optional[float] = None
    granger_adjusted_p_value: Optional[float] = None
    granger_significant: bool
    decision: Literal["keep", "review", "low_signal"]
    decision_reason: str


class EdaFeatureGrangerPointOut(BaseModel):
    feature: str
    lag: int
    f_statistic: float
    p_value: float
    adjusted_p_value: float
    significant: bool


class EdaFeatureCorrelationPairOut(BaseModel):
    first: str
    second: str
    correlation: float


class EdaFeatureExcludedOut(BaseModel):
    name: str
    reason: str


class DatasetEdaFeatureSelectionResponse(BaseModel):
    column: str
    applicable: bool
    applicability_status: Literal["applicable", "not_required", "requires_preprocessing", "not_applicable"]
    reason: Optional[str] = None
    n_observations: int
    min_observations: int
    numeric_candidates: int
    analyzed_features: int
    alpha: float
    requested_max_lag: int
    max_lag: int
    correlation_threshold: float
    vif_threshold: float
    difference_order: Literal[0, 1]
    granger_n_observations: int
    granger_available: bool
    granger_reason: Optional[str] = None
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    order_warning: Optional[str] = None
    frequency: Optional[str] = None
    correlation_matrix: List[EdaFeatureCorrelationCellOut] = Field(default_factory=list)
    features: List[EdaFeatureItemOut] = Field(default_factory=list)
    granger: List[EdaFeatureGrangerPointOut] = Field(default_factory=list)
    high_correlation_pairs: List[EdaFeatureCorrelationPairOut] = Field(default_factory=list)
    excluded_features: List[EdaFeatureExcludedOut] = Field(default_factory=list)
    kept_features: List[str] = Field(default_factory=list)
    review_features: List[str] = Field(default_factory=list)
    low_signal_features: List[str] = Field(default_factory=list)
    recommendation: Optional[str] = None
    recommendations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class EdaValidationFoldOut(BaseModel):
    fold: int
    train_start: int
    train_end: int
    train_size: int
    gap_start: Optional[int] = None
    gap_end: Optional[int] = None
    gap_size: int
    test_start: int
    test_end: int
    test_size: int
    train_start_label: Optional[str] = None
    train_end_label: Optional[str] = None
    test_start_label: Optional[str] = None
    test_end_label: Optional[str] = None


class EdaValidationAlternativeOut(BaseModel):
    strategy: Literal["expanding", "sliding", "single"]
    label: str
    suitable: bool
    required_observations: int
    reason: str


class DatasetEdaValidationStrategyResponse(BaseModel):
    column: str
    applicable: bool
    reason: Optional[str] = None
    strategy: Literal["expanding", "sliding", "single"]
    horizon: int
    requested_splits: int
    effective_splits: int
    gap: int
    train_window: int
    min_train_observations: int
    n_observations: int
    missing_count: int
    required_observations: int
    initial_train_size: int
    unused_observations: int
    test_coverage: float
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    order_warning: Optional[str] = None
    frequency: Optional[str] = None
    comparable_duration: bool
    folds: List[EdaValidationFoldOut] = Field(default_factory=list)
    alternatives: List[EdaValidationAlternativeOut] = Field(default_factory=list)
    recommendation: Optional[str] = None
    recommendations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class EdaModelCriterionOut(BaseModel):
    id: str
    label: str
    status: Literal["pass", "attention", "fail", "unknown", "not_required"]
    observed: str
    requirement: str
    conclusion: str
    blocking: bool = False


class EdaModelMatrixModelOut(BaseModel):
    model_id: str
    model_name: str
    family_id: str
    family_name: str
    compatibility: Literal["candidate", "conditional", "blocked"]
    platform_status: Literal["ready", "catalog_only"]
    min_observations: int
    supports_exogenous: bool
    libraries: List[str] = Field(default_factory=list)
    training_time: str
    criteria: List[EdaModelCriterionOut] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)


class EdaModelMatrixFamilyOut(BaseModel):
    family_id: str
    family_name: str
    candidates: int
    conditional: int
    blocked: int
    ready: int
    catalog_only: int


class EdaModelMatrixProfileOut(BaseModel):
    n_observations: int
    missing_count: int
    numeric_series_count: int
    n_exogenous: int
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    frequency: Optional[str] = None
    is_regular: Optional[bool] = None
    temporal_status: Literal["regular", "irregular", "panel", "invalid", "unknown"]
    seasonality_status: Literal["present", "absent", "unknown"]
    seasonal_periods: List[int] = Field(default_factory=list)
    stationarity_status: Literal["stationary", "non_stationary", "inconclusive", "unknown"]
    has_negative_values: bool
    validation_strategy: Literal["expanding", "sliding", "single"]
    initial_train_observations: int
    required_observations: int


class EdaModelMatrixSummaryOut(BaseModel):
    total_models: int
    candidates: int
    conditional: int
    blocked: int
    ready: int
    catalog_only: int


class DatasetEdaModelMatrixResponse(BaseModel):
    column: str
    applicable: bool
    reason: Optional[str] = None
    task: Literal["forecast", "multivariate", "volatility"]
    horizon: int
    spec_version: str
    profile: EdaModelMatrixProfileOut
    summary: EdaModelMatrixSummaryOut
    families: List[EdaModelMatrixFamilyOut] = Field(default_factory=list)
    models: List[EdaModelMatrixModelOut] = Field(default_factory=list)
    shortlist: List[str] = Field(default_factory=list)
    runnable_shortlist: List[str] = Field(default_factory=list)
    recommendation: str
    methodology_note: str
    warnings: List[str] = Field(default_factory=list)


class PanelBalanceResponse(BaseModel):
    """Реальная проверка Balanced/Unbalanced для панельных данных --
    пункт 8 контракта (структурный класс), визуальная схема на
    остановке «Структура». Требует ПОЛНЫЙ датасет (не превью): нужно
    сравнить множества дат у каждой группы, 5+5 строк для этого мало."""
    balanced: bool
    n_entities: int
    n_distinct_date_sets: int


# ── Графики распределения (пункт 3 контракта, apps/api/chart_data.py) ──

class ScatterPoint(BaseModel):
    x: int = Field(..., description="Позиция в очищенном от NaN столбце (0-based)")
    y: float


class HistogramBin(BaseModel):
    x0: float
    x1: float
    count: int


class KdePoint(BaseModel):
    x: float
    y: float


class DistributionChartResponse(BaseModel):
    """Данные для трёх графиков остановки «Распределение» вкладки
    «Загрузка» -- точечный график, гистограмма, KDE. Реальный расчёт
    (numpy/scipy) над ПОЛНЫМ столбцом сессии, не превью -- тот же
    принцип, что и в ColumnStatsOut."""
    column: str
    non_null_count: int
    min: Optional[float] = None
    max: Optional[float] = None
    scatter: List[ScatterPoint]
    scatter_sampled: bool = Field(..., description="True, если scatter прошёл через LTTB-сэмплинг")
    scatter_sampling_method: Optional[str] = Field(None, description="'lttb' | None (не сэмплировано)")
    scatter_original_count: int = Field(..., description="Число точек ДО сэмплинга")
    histogram: List[HistogramBin]
    kde: Optional[List[KdePoint]] = Field(None, description="None -- KDE не определена (<2 значений или нулевая дисперсия)")


# ── График (пункт из чата 2026-08-14: остановка «График» между «Превью
# датасета» и «Распределение», линейный график + бейджи декомпозиции) ──

class TimeSeriesPoint(BaseModel):
    x: str = Field(..., description="ISO-дата точки")
    y: float


class TimeSeriesResponse(BaseModel):
    """Ответ GET /dataset/timeseries -- линейный график исследуемого
    признака с РЕАЛЬНЫМИ датами на оси X (в отличие от /dataset/distribution,
    где x -- позиция в очищенном ряде). was_resorted=True, если исходный
    порядок строк в файле был не хронологическим -- график всегда рисует
    слева направо по возрастанию даты, честно предупреждая об этом."""
    column: str
    date_column: str
    points: List[TimeSeriesPoint]
    sampled: bool
    sampling_method: Optional[str] = None
    original_count: int
    was_resorted: bool = Field(..., description="Исходный порядок строк был не хронологическим")


class DecompositionResponse(BaseModel):
    """Ответ GET /dataset/decomposition -- бейджи Тренд/Сезонность/
    Цикличность/Остаток (доли дисперсии, ~100% суммарно). applicable=False
    -- ЧЕСТНЫЙ отказ (не 0%!), когда декомпозиция технически неприменима:
    годовая/нерегулярная частота (нет внутригодового цикла), панельные
    дубли дат (несколько сущностей на дату), недостаточно точек или
    константный ряд -- reason объясняет причину. См. apps/api/decomposition_data.py.
    cyclical_pct -- ОЦЕНОЧНАЯ эвристика (не строгий метод, как STL для
    trend/seasonal/resid)."""
    applicable: bool
    reason: Optional[str] = None
    frequency: Optional[str] = Field(None, description="pandas-код определённой частоты, например 'MS'")
    frequency_label: Optional[str] = None
    period_used: Optional[int] = None
    n_points: int
    method: Optional[str] = None
    trend_pct: Optional[float] = None
    seasonal_pct: Optional[float] = None
    cyclical_pct: Optional[float] = Field(None, description="Оценочная эвристика, не строгий метод")
    resid_pct: Optional[float] = None


class DecompositionSeriesPoint(BaseModel):
    x: str = Field(..., description="ISO-дата точки")
    trend: float
    seasonal: float
    cyclical: float
    resid: float


class DecompositionSeriesResponse(BaseModel):
    """Ответ GET /dataset/decomposition-series -- РЕАЛЬНЫЕ ряды компонент
    декомпозиции (Тренд/Сезонность/Цикличность/Остаток) для графика под
    бейджами (согласовано с тимлидом 2026-08-19: "визуализировать данный
    декомпозированный ряд на дополнительном графике"). См.
    apps/api/decomposition_data.py::build_decomposition_series --
    переиспользует app/preprocessing/decomposition.py::apply_decomposition
    (реальные ряды, не только дисперсии, как в /dataset/decomposition).

    applicable/reason -- ТОТ ЖЕ гейт (частота/панельные дубли/точки/
    константа), что и в /dataset/decomposition -- не должны расходиться
    на одном и том же датасете."""
    applicable: bool
    reason: Optional[str] = None
    method: Optional[str] = None
    sampled: bool = False
    sampling_method: Optional[str] = None
    original_count: int = 0
    points: List[DecompositionSeriesPoint] = Field(default_factory=list)


class PreprocessingDecompositionPointOut(BaseModel):
    x: str
    observed: float
    trend: float
    seasonal: float
    resid: float


class PreprocessingSeasonalPatternPointOut(BaseModel):
    phase: int
    label: str
    value: float


class PreprocessingResidualAcfPointOut(BaseModel):
    lag: int
    value: float


class PreprocessingDecompositionProfileOut(BaseModel):
    """Диагностический профиль робастного STL без псевдо-компонент.

    ``trend_strength``/``seasonal_strength`` — ограниченные [0, 1]
    strength-метрики через дисперсию остатка, не «проценты дисперсий»,
    которые нельзя честно складывать для коррелированных компонент STL.
    """
    column: str
    date_column: Optional[str] = None
    applicable: bool
    reason: Optional[str] = None
    method: Literal["STL"] = "STL"
    robust: bool = True
    frequency: Optional[str] = None
    period: Optional[int] = None
    n_points: int = 0
    sampled: bool = False
    original_count: int = 0
    trend_strength: Optional[float] = None
    seasonal_strength: Optional[float] = None
    residual_mean: Optional[float] = None
    residual_std: Optional[float] = None
    ljung_box_lag: Optional[int] = None
    ljung_box_pvalue: Optional[float] = None
    jarque_bera_pvalue: Optional[float] = None
    points: List[PreprocessingDecompositionPointOut] = Field(default_factory=list)
    seasonal_pattern: List[PreprocessingSeasonalPatternPointOut] = Field(default_factory=list)
    residual_acf: List[PreprocessingResidualAcfPointOut] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendation: str
    methodology_note: str


class DatasetPreprocessingDecompositionProfileResponse(BaseModel):
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    profile: PreprocessingDecompositionProfileOut


class DatasetPreprocessingDecompositionRequest(BaseModel):
    column: str = Field(..., min_length=1)
    period: Optional[int] = Field(None, ge=2)
    robust: bool = True
    outputs: List[Literal["components", "seasonally_adjusted", "detrended"]] = Field(
        default_factory=lambda: ["components"], min_length=1, max_length=3,
    )
    apply: bool = Field(False, description="False — preview; True — сохранить новые колонки в сессии")


class DatasetPreprocessingDecompositionResponse(BaseModel):
    applied: bool
    column: str
    method: Literal["STL"] = "STL"
    robust: bool
    period: int
    outputs: List[str]
    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int
    added_columns: List[str] = Field(default_factory=list)
    profile: PreprocessingDecompositionProfileOut


VarianceMethod = Literal["box_cox", "yeo_johnson", "log", "log1p", "sqrt"]


class VarianceDiagnosticOut(BaseModel):
    rolling_window: int
    mean_std_correlation: Optional[float] = None
    levene_statistic: Optional[float] = None
    levene_pvalue: Optional[float] = None
    block_variance_ratio: Optional[float] = None
    arch_lm_lag: int
    arch_lm_pvalue: Optional[float] = None
    skewness: Optional[float] = None
    stability_score: float


class VarianceCandidateOut(BaseModel):
    method: VarianceMethod
    label: str
    available: bool
    reason: Optional[str] = None
    lambda_value: Optional[float] = None
    stability_score: Optional[float] = None


class VariancePointOut(BaseModel):
    x: str
    original: float
    transformed: float
    rolling_std_before: Optional[float] = None
    rolling_std_after: Optional[float] = None


class VarianceHistogramPointOut(BaseModel):
    bin: int
    original_x: float
    original_density: float
    transformed_x: float
    transformed_density: float


class PreprocessingVarianceProfileOut(BaseModel):
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int = 0
    missing_count: int = 0
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    order_source: Literal["time_column", "row_order"] = "row_order"
    order_column: Optional[str] = None
    selected_method: Optional[VarianceMethod] = None
    lambda_value: Optional[float] = None
    needs_stabilization: bool = False
    diagnostics_before: Optional[VarianceDiagnosticOut] = None
    diagnostics_after: Optional[VarianceDiagnosticOut] = None
    candidates: List[VarianceCandidateOut] = Field(default_factory=list)
    points: List[VariancePointOut] = Field(default_factory=list)
    histogram: List[VarianceHistogramPointOut] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendation: str
    methodology_note: str


class DatasetPreprocessingVarianceProfileResponse(BaseModel):
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    profile: PreprocessingVarianceProfileOut


class DatasetPreprocessingVarianceRequest(BaseModel):
    column: str = Field(..., min_length=1)
    method: VarianceMethod
    lambda_value: Optional[float] = Field(None, ge=-5, le=5)
    apply: bool = Field(False, description="False — preview; True — сохранить новую колонку и inverse-метаданные")


class VarianceTransformationMetadataOut(BaseModel):
    source_column: str
    output_column: str
    method: VarianceMethod
    lambda_value: Optional[float] = None
    inverse_supported: bool = True
    fitted_on_n: int
    standardized: bool = False
    shift: float = 0.0


class DatasetPreprocessingVarianceResponse(BaseModel):
    applied: bool
    column: str
    method: VarianceMethod
    lambda_value: Optional[float] = None
    output_column: str
    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int
    metadata: VarianceTransformationMetadataOut


SmoothingMethod = Literal["sma", "ema", "wma", "median", "savgol", "lowess"]


class SmoothingDiagnosticOut(BaseModel):
    normalized_roughness: Optional[float] = None
    difference_std_ratio: Optional[float] = None
    lag1_autocorrelation: Optional[float] = None
    high_frequency_power_share: Optional[float] = None
    standard_deviation: Optional[float] = None


class SmoothingCandidateOut(BaseModel):
    method: SmoothingMethod
    label: str
    causal: bool
    available: bool
    reason: Optional[str] = None
    parameter_label: str
    correlation: Optional[float] = None
    roughness_reduction_pct: Optional[float] = None
    high_frequency_reduction_pct: Optional[float] = None
    variance_retained_pct: Optional[float] = None
    residual_ljung_box_pvalue: Optional[float] = None


class SmoothingPointOut(BaseModel):
    x: str
    original: float
    smoothed: float
    residual: float


class SmoothingSpectrumPointOut(BaseModel):
    frequency: float
    before: float
    after: float


class SmoothingAcfPointOut(BaseModel):
    lag: int
    value: float


class PreprocessingSmoothingProfileOut(BaseModel):
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int = 0
    missing_count: int = 0
    order_source: Literal["time_column", "row_order"] = "row_order"
    order_column: Optional[str] = None
    frequency: Optional[str] = None
    regular: Optional[bool] = None
    selected_method: Optional[SmoothingMethod] = None
    selected_parameters: Dict[str, float] = Field(default_factory=dict)
    needs_smoothing: bool = False
    diagnostics_before: Optional[SmoothingDiagnosticOut] = None
    diagnostics_after: Optional[SmoothingDiagnosticOut] = None
    candidates: List[SmoothingCandidateOut] = Field(default_factory=list)
    points: List[SmoothingPointOut] = Field(default_factory=list)
    spectrum: List[SmoothingSpectrumPointOut] = Field(default_factory=list)
    residual_acf: List[SmoothingAcfPointOut] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendation: str
    methodology_note: str


class DatasetPreprocessingSmoothingProfileResponse(BaseModel):
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    profile: PreprocessingSmoothingProfileOut


class DatasetPreprocessingSmoothingRequest(BaseModel):
    column: str = Field(..., min_length=1)
    method: SmoothingMethod
    window: int = Field(7, ge=3, le=501)
    span: int = Field(7, ge=2, le=501)
    frac: float = Field(0.2, gt=0, le=1)
    polyorder: int = Field(2, ge=1, le=10)
    confirm_non_causal: bool = False
    apply: bool = Field(False, description="False — preview; True — сохранить новую колонку и параметры")


class SmoothingTransformationMetadataOut(BaseModel):
    kind: Literal["smoothing"] = "smoothing"
    source_column: str
    output_column: str
    method: SmoothingMethod
    parameters: Dict[str, float] = Field(default_factory=dict)
    causal: bool
    modeling_safe: bool
    inverse_supported: bool = False
    fitted_on_n: int


class DatasetPreprocessingSmoothingResponse(BaseModel):
    applied: bool
    column: str
    method: SmoothingMethod
    output_column: str
    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int
    metadata: SmoothingTransformationMetadataOut


StationarityTransformMethod = Literal[
    "linear_detrend", "first_difference", "second_difference",
    "seasonal_difference", "combined_difference", "log_difference",
]
StationarityProfileMethod = Literal[
    "none", "linear_detrend", "first_difference", "second_difference",
    "seasonal_difference", "combined_difference", "log_difference",
]
StationarityConsensus = Literal[
    "stationary", "trend-stationary", "non-stationary", "inconclusive",
]


class StationarityTestComparisonOut(BaseModel):
    id: Literal["adf_level", "adf_trend", "kpss_level", "kpss_trend", "pp", "zivot_andrews"]
    label: str
    null_hypothesis: str
    before_p_value: Optional[float] = None
    after_p_value: Optional[float] = None
    before_supports_stationarity: Optional[bool] = None
    after_supports_stationarity: Optional[bool] = None


class StationarityCandidateOut(BaseModel):
    method: StationarityTransformMethod
    label: str
    available: bool
    reason: Optional[str] = None
    consensus: Optional[StationarityConsensus] = None
    lost_observations: int = 0
    adf_p_value: Optional[float] = None
    kpss_p_value: Optional[float] = None
    acf_lag1: Optional[float] = None
    variance_ratio: Optional[float] = None
    over_differencing_warning: bool = False


class StationarityPointOut(BaseModel):
    x: str
    original: float
    transformed: Optional[float] = None
    rolling_mean_z_before: Optional[float] = None
    rolling_mean_z_after: Optional[float] = None
    rolling_std_ratio_before: Optional[float] = None
    rolling_std_ratio_after: Optional[float] = None


class StationarityAcfPointOut(BaseModel):
    lag: int
    before: float
    after: float
    confidence_before: float
    confidence_after: float


class PreprocessingStationarityProfileOut(BaseModel):
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int = 0
    missing_count: int = 0
    min_observations: int = 30
    alpha: float = 0.05
    order_source: Literal["time_column", "row_order"] = "row_order"
    order_column: Optional[str] = None
    frequency: Optional[str] = None
    regular: bool = False
    seasonal_period: int = 12
    selected_method: Optional[StationarityProfileMethod] = None
    needs_transformation: bool = False
    consensus_before: Optional[StationarityConsensus] = None
    consensus_after: Optional[StationarityConsensus] = None
    lost_observations: int = 0
    acf_lag1_before: Optional[float] = None
    acf_lag1_after: Optional[float] = None
    variance_before: Optional[float] = None
    variance_after: Optional[float] = None
    over_differencing_warning: bool = False
    tests: List[StationarityTestComparisonOut] = Field(default_factory=list)
    candidates: List[StationarityCandidateOut] = Field(default_factory=list)
    points: List[StationarityPointOut] = Field(default_factory=list)
    acf: List[StationarityAcfPointOut] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendation: str
    methodology_note: str


class DatasetPreprocessingStationarityProfileResponse(BaseModel):
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    profile: PreprocessingStationarityProfileOut


class DatasetPreprocessingStationarityRequest(BaseModel):
    column: str = Field(..., min_length=1)
    method: StationarityTransformMethod
    seasonal_period: int = Field(12, ge=2, le=10000)
    confirm_non_causal: bool = False
    apply: bool = Field(False, description="False — preview; True — добавить колонку и удалить неопределённый префикс")


class StationarityTransformationMetadataOut(BaseModel):
    kind: Literal["stationarity"] = "stationarity"
    source_column: str
    output_column: str
    method: StationarityTransformMethod
    regular_order: int
    seasonal_order: int
    seasonal_period: Optional[int] = None
    domain_transform: Optional[Literal["log"]] = None
    causal: bool
    modeling_safe: bool
    inverse_supported: bool
    lost_observations: int
    fitted_on_n: int
    history_tail: List[float] = Field(default_factory=list)
    trend_intercept: Optional[float] = None
    trend_slope: Optional[float] = None
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    frequency: Optional[str] = None


class DatasetPreprocessingStationarityResponse(BaseModel):
    applied: bool
    column: str
    method: StationarityTransformMethod
    output_column: str
    rows_before: int
    rows_after: int
    rows_dropped: int
    columns_before: int
    columns_after: int
    metadata: StationarityTransformationMetadataOut


class SpectralWelchPointOut(EdaSpectrumPoint):
    power_share: float


class SpectralBandOut(BaseModel):
    id: Literal["low", "mid", "high"]
    label: str
    frequency_min: float
    frequency_max: float
    power_share: float


class SpectralWaveletPointOut(BaseModel):
    x: str
    index: int
    period: float
    power: float
    normalized_power: float
    edge_affected: bool


class SpectralWaveletGlobalOut(BaseModel):
    period: float
    power_share: float


class PreprocessingSpectralProfileOut(BaseModel):
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int = 0
    missing_count: int = 0
    min_cycles: int = 3
    max_candidates: int = 6
    max_period: Optional[float] = None
    detrend: Literal["linear"] = "linear"
    window: Literal["hann"] = "hann"
    order_source: Literal["time_column", "row_order"] = "row_order"
    order_column: Optional[str] = None
    order_warning: Optional[str] = None
    frequency: Optional[str] = None
    spectral_entropy: Optional[float] = None
    dominant_period: Optional[float] = None
    dominant_strength: Optional[float] = None
    confirmed_periods: int = 0
    frequency_resolution: Optional[float] = None
    nyquist_frequency: Optional[float] = None
    welch_segment_length: Optional[int] = None
    welch_segments: int = 0
    wavelet_method: str = "cmor1.5-1.0"
    wavelet_period_min: Optional[float] = None
    wavelet_period_max: Optional[float] = None
    analysis_only: bool = True
    causal: bool = False
    modeling_safe: bool = False
    saved_periods: List[int] = Field(default_factory=list)
    fft: List[EdaSpectrumPoint] = Field(default_factory=list)
    periodogram: List[EdaSpectrumPoint] = Field(default_factory=list)
    welch: List[SpectralWelchPointOut] = Field(default_factory=list)
    bands: List[SpectralBandOut] = Field(default_factory=list)
    candidates: List[EdaSeasonalityCandidateOut] = Field(default_factory=list)
    phase_period: Optional[int] = None
    phase_profile: List[EdaSeasonalityPhasePoint] = Field(default_factory=list)
    wavelet: List[SpectralWaveletPointOut] = Field(default_factory=list)
    wavelet_global: List[SpectralWaveletGlobalOut] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    methodology_note: str


class DatasetPreprocessingSpectralProfileResponse(BaseModel):
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    profile: PreprocessingSpectralProfileOut


class DatasetPreprocessingSpectralSelectionRequest(BaseModel):
    column: str = Field(..., min_length=1)
    periods: List[int] = Field(default_factory=list, max_length=10)
    min_cycles: int = Field(3, ge=2, le=10)
    max_candidates: int = Field(6, ge=1, le=10)
    welch_segment_length: Optional[int] = Field(None, ge=8, le=4096)
    confirm_unconfirmed: bool = False
    apply: bool = Field(False, description="False — preview; True — сохранить аналитическое решение без изменения датасета")


class SpectralSelectionMetadataOut(BaseModel):
    kind: Literal["spectral_selection"] = "spectral_selection"
    source_column: str
    selected_periods: List[int]
    frequencies: List[float]
    confirmed_periods: List[int]
    unconfirmed_periods: List[int]
    min_cycles: int
    max_candidates: int
    welch_segment_length: int
    detrend: Literal["linear"]
    window: Literal["hann"]
    wavelet: str
    analysis_only: bool
    causal: bool
    modeling_safe: bool
    analyzed_on_n: int
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    frequency: Optional[str] = None


class DatasetPreprocessingSpectralSelectionResponse(BaseModel):
    applied: bool
    column: str
    selected_periods: List[int]
    confirmed_periods: List[int]
    unconfirmed_periods: List[int]
    suggested_lags: List[int]
    metadata: SpectralSelectionMetadataOut


FeatureFamily = Literal["lag", "rolling", "difference", "calendar", "fourier", "trend"]
RollingStatistic = Literal["mean", "std", "min", "max"]
CalendarFeature = Literal[
    "year", "quarter", "month_cyclic", "dayofweek_cyclic",
    "dayofyear_cyclic", "hour_cyclic", "is_weekend",
]


class FeatureCatalogItemOut(BaseModel):
    name: str
    family: FeatureFamily
    formula: str
    lookback: int
    known_in_advance: bool
    causal: bool
    missing_count: int
    coverage: float


class FeaturePreviewPointOut(BaseModel):
    x: str
    target: float
    lag: Optional[float] = None
    rolling: Optional[float] = None
    fourier: Optional[float] = None


class FeatureLagCorrelationOut(BaseModel):
    lag: int
    correlation: Optional[float] = None
    selected: bool


class FeatureAvailabilityOut(BaseModel):
    name: str
    family: FeatureFamily
    available_count: int
    missing_count: int
    coverage: float


class FeatureCyclicPointOut(BaseModel):
    x: str
    feature: str
    value: Optional[float] = None


class PreprocessingFeatureGenerationProfileOut(BaseModel):
    column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int = 0
    order_source: Literal["time_column", "row_order"] = "row_order"
    order_column: Optional[str] = None
    frequency: Optional[str] = None
    regular: bool = False
    spectral_periods: List[int] = Field(default_factory=list)
    suggested_lags: List[int] = Field(default_factory=list)
    suggested_rolling_windows: List[int] = Field(default_factory=list)
    suggested_calendar_features: List[CalendarFeature] = Field(default_factory=list)
    suggested_fourier_periods: List[int] = Field(default_factory=list)
    generated: bool = False
    saved_feature_names: List[str] = Field(default_factory=list)
    max_lookback: int = 0
    preview_feature_count: int = 0
    preview_points: List[FeaturePreviewPointOut] = Field(default_factory=list)
    lag_correlations: List[FeatureLagCorrelationOut] = Field(default_factory=list)
    availability: List[FeatureAvailabilityOut] = Field(default_factory=list)
    cyclic_points: List[FeatureCyclicPointOut] = Field(default_factory=list)
    catalog: List[FeatureCatalogItemOut] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendation: str
    methodology_note: str


class DatasetPreprocessingFeatureGenerationProfileResponse(BaseModel):
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    profile: PreprocessingFeatureGenerationProfileOut


class DatasetPreprocessingFeatureGenerationRequest(BaseModel):
    column: str = Field(..., min_length=1)
    lags: List[int] = Field(default_factory=list, max_length=20)
    rolling_windows: List[int] = Field(default_factory=list, max_length=10)
    rolling_statistics: List[RollingStatistic] = Field(default_factory=list, max_length=4)
    difference_lags: List[int] = Field(default_factory=list, max_length=10)
    calendar_features: List[CalendarFeature] = Field(default_factory=list, max_length=7)
    fourier_periods: List[int] = Field(default_factory=list, max_length=10)
    fourier_harmonics: int = Field(1, ge=1, le=5)
    include_time_index: bool = True
    drop_warmup_rows: bool = True
    apply: bool = Field(False, description="False — preview; True — добавить признаки к активному датасету")


class FeatureGenerationMetadataOut(BaseModel):
    kind: Literal["feature_generation"] = "feature_generation"
    source_column: str
    date_column: Optional[str] = None
    feature_names: List[str]
    feature_catalog: List[FeatureCatalogItemOut]
    lags: List[int]
    rolling_windows: List[int]
    rolling_statistics: List[RollingStatistic]
    difference_lags: List[int]
    calendar_features: List[CalendarFeature]
    fourier_periods: List[int]
    fourier_harmonics: int
    include_time_index: bool
    drop_warmup_rows: bool
    target_shift: Literal[1]
    max_lookback: int
    rows_dropped: int
    generated_on_n: int
    result_rows: int
    order_source: Literal["time_column", "row_order"]
    order_column: Optional[str] = None
    frequency: Optional[str] = None
    causal: bool
    row_level_modeling_safe: bool
    selection_requires_train_fold: bool
    forecast_contract: str


class DatasetPreprocessingFeatureGenerationResponse(BaseModel):
    applied: bool
    column: str
    feature_names: List[str]
    feature_count: int
    rows_before: int
    rows_after: int
    rows_dropped: int
    max_lookback: int
    warnings: List[str] = Field(default_factory=list)
    metadata: FeatureGenerationMetadataOut


ScalingMethod = Literal["standard", "minmax", "robust", "maxabs", "quantile"]


class ScalingColumnOut(BaseModel):
    name: str
    role: Literal["target", "generated", "source"]
    dtype: str
    missing_count: int
    unique_count: int
    binary: bool
    constant: bool
    eligible: bool
    recommended: bool
    exclusion_reason: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    mean: Optional[float] = None
    std: Optional[float] = None
    median: Optional[float] = None
    q1: Optional[float] = None
    q3: Optional[float] = None
    iqr: Optional[float] = None
    outlier_pct: Optional[float] = None
    skewness: Optional[float] = None
    scale: Optional[float] = None


class ScalingPreviewPointOut(BaseModel):
    x: str
    original: Optional[float] = None
    scaled: Optional[float] = None


class ScalingRangePointOut(BaseModel):
    column: str
    scale_before: Optional[float] = None
    scale_after: Optional[float] = None
    log_scale_before: Optional[float] = None
    log_scale_after: Optional[float] = None


class ScalingDistributionPointOut(BaseModel):
    x_before: Optional[float] = None
    density_before: Optional[float] = None
    x_after: Optional[float] = None
    density_after: Optional[float] = None


class ScalingBoxPointOut(BaseModel):
    column: str
    stage: Literal["before", "after"]
    minimum: Optional[float] = None
    q1: Optional[float] = None
    median: Optional[float] = None
    q3: Optional[float] = None
    maximum: Optional[float] = None


class ScalingCorrelationPointOut(BaseModel):
    x: str
    y: str
    before: Optional[float] = None
    after: Optional[float] = None
    delta: Optional[float] = None


class ScalingMethodOut(BaseModel):
    method: ScalingMethod
    label: str
    linear: bool
    centers: str
    scales: str
    outlier_robust: bool
    bounded: bool
    preserves_zero: bool
    max_correlation_delta: float
    note: str


class ScalingRecipeOut(BaseModel):
    kind: Literal["scaling_recipe"] = "scaling_recipe"
    target_column: str
    columns: List[str]
    method: ScalingMethod
    parameters: Dict[str, Any]
    fit_policy: Literal["per_train_fold"]
    modeling_safe: bool
    materializes_columns: bool
    configured_on_n: int
    source_signature: str
    target_included: bool
    inverse_transform_required_for_target: bool
    nonlinear: bool


class PreprocessingScalingProfileOut(BaseModel):
    target_column: str
    applicable: bool
    reason: Optional[str] = None
    n_observations: int
    numeric_count: int
    eligible_count: int
    suggested_columns: List[str] = Field(default_factory=list)
    recommended_method: ScalingMethod
    configured: bool
    saved_recipe: Optional[ScalingRecipeOut] = None
    focus_column: Optional[str] = None
    scale_ratio: float
    orders_of_magnitude: float
    columns: List[ScalingColumnOut] = Field(default_factory=list)
    preview_points: List[ScalingPreviewPointOut] = Field(default_factory=list)
    range_points: List[ScalingRangePointOut] = Field(default_factory=list)
    distribution_points: List[ScalingDistributionPointOut] = Field(default_factory=list)
    box_points: List[ScalingBoxPointOut] = Field(default_factory=list)
    correlation_points: List[ScalingCorrelationPointOut] = Field(default_factory=list)
    methods: List[ScalingMethodOut] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendation: str
    methodology_note: str


class DatasetPreprocessingScalingProfileResponse(BaseModel):
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    profile: PreprocessingScalingProfileOut


class DatasetPreprocessingScalingRecipeRequest(BaseModel):
    target_column: str = Field(..., min_length=1)
    columns: List[str] = Field(..., min_length=1, max_length=50)
    method: ScalingMethod = "standard"
    feature_range: List[float] = Field(default_factory=lambda: [0.0, 1.0], min_length=2, max_length=2)
    quantile_range: List[float] = Field(default_factory=lambda: [25.0, 75.0], min_length=2, max_length=2)
    output_distribution: Literal["uniform", "normal"] = "normal"
    n_quantiles: int = Field(1000, ge=10, le=1000)
    confirm_nonlinear: bool = False
    apply: bool = Field(False, description="False — preview; True — сохранить fold-safe рецепт без мутации DataFrame")


class ScalingMetricOut(BaseModel):
    column: str
    minimum_before: Optional[float] = None
    maximum_before: Optional[float] = None
    mean_before: Optional[float] = None
    std_before: Optional[float] = None
    median_before: Optional[float] = None
    q1_before: Optional[float] = None
    q3_before: Optional[float] = None
    iqr_before: Optional[float] = None
    minimum_after: Optional[float] = None
    maximum_after: Optional[float] = None
    mean_after: Optional[float] = None
    std_after: Optional[float] = None
    median_after: Optional[float] = None
    q1_after: Optional[float] = None
    q3_after: Optional[float] = None
    iqr_after: Optional[float] = None
    original_scaled_correlation: Optional[float] = None


class ScalingPreviewMetadataOut(BaseModel):
    method: ScalingMethod
    scaler_class: str
    parameters: Dict[str, Any]
    columns: List[str]
    fitted_on_n: int
    linear: bool
    fit_scope: Literal["full_history_diagnostic"]
    modeling_safe: bool
    applied_to_dataframe: bool
    actual_n_quantiles: Optional[int] = None


class DatasetPreprocessingScalingRecipeResponse(BaseModel):
    applied: bool
    target_column: str
    columns: List[str]
    method: ScalingMethod
    metrics: List[ScalingMetricOut]
    warnings: List[str] = Field(default_factory=list)
    recipe: ScalingRecipeOut
    preview_metadata: ScalingPreviewMetadataOut


# ── Структурная детекция (2026-08-14, найден реальный баг: фронт
# показывал позиционную заглушку "первые 3 колонки файла" вместо
# реального контентного скоринга -- см. app/data/detectors.py) ──

class DetectionCandidateOut(BaseModel):
    name: str
    score: float = Field(..., description="0..1, реальный контентный скоринг (не позиция в файле)")


class ColumnDetectionOut(BaseModel):
    selected: str = Field(..., description="Лучший кандидат, либо '(не использовать)'/'(нет)', если ни одного")
    confidence: int = Field(..., description="round(top_score * 100), 0..100")
    candidates: List[DetectionCandidateOut] = Field(..., description="Отсортировано по score убыв., включает нулевые (фронт решает порог отсечения)")


class FrequencyDetectionOut(BaseModel):
    """Реальная частота date-колонки (pd.infer_freq на уникальных
    отсортированных датах) -- заменяет захардкоженную заглушку
    "D — ежедневная" на фронте (найдено пользователем 2026-08-14 на
    годовом FAO-датасете, см. app/data/detectors.py::detect_column_frequency)."""
    selected: str = Field(..., description="Человекочитаемая метка, '(не определена)' если нерегулярно")
    code: Optional[str] = Field(None, description="Код pandas-частоты, например 'YS-JAN'")
    confidence: int = Field(..., description="100, если pd.infer_freq определил частоту, иначе 0")


class StructureDetectionResponse(BaseModel):
    """Ответ GET /dataset/structure-detection -- РЕАЛЬНАЯ (не клиентская
    позиционная) детекция даты и группирующей колонки. См.
    app/data/detectors.py::score_all_columns_as_date /
    score_all_columns_as_entity_group -- уже существовавшая, протестированная
    (tests/unit/test_detectors.py), но НЕ подключённая к API логика
    (см. историю: комментарий в apps/api/upload_common.py признавал
    этот пробел явно).

    frequency (2026-08-14) -- реальная частота ВЫБРАННОЙ date-колонки
    (date_col.selected), None если date_col не определена уверенно."""
    date_col: ColumnDetectionOut
    entity_col: ColumnDetectionOut
    frequency: Optional[FrequencyDetectionOut] = None


# ── Валидация (10 проверок вкладки «Валидация», validation/engine.py::_run_all_checks) ──

class ValidationCheckItem(BaseModel):
    label: str = Field(..., description="Колонка/правило/группа, к которой относится нарушение")
    count: int = Field(..., description="Число нарушений по этой строке детализации")


class ValidationCheckResult(BaseModel):
    """Один из 10 пунктов CHECKS (TsAnalysisValidation.tsx).

    ``pending`` означает, что принудительно включённой проверке нужна
    настройка; ``skipped`` -- нейтральный пропуск в режиме auto либо
    явное отключение аналитиком. Набор значений синхронизирован с UI.
    """
    status: Literal["done", "warning", "pending", "skipped"] = Field(
        ..., description="Результат проверки либо нейтральный пропуск"
    )
    count: Optional[int] = Field(None, description="Суммарное число нарушений; None при pending/skipped")
    items: List[ValidationCheckItem] = Field(default_factory=list, description="Детализация для графика")
    scope: str = Field("dataset", description="'column' -- учитывает выбранную колонку, 'dataset' -- всегда весь датасет")
    error: Optional[str] = Field(None, description="Текст исключения, если sub-check упал (см. _safe в engine.py)")
    rule_source: Literal["system", "template", "session", "not_applicable"] = Field(
        "system",
        description="Источник эталона именно этой проверки",
    )
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status_reason: Optional[Literal["not_required", "disabled", "needs_rule"]] = None


class DatasetValidateResponse(BaseModel):
    """Ответ GET /dataset/validate -- реальная валидация session.dataframe
    по всем 10 проверкам. rules_source сообщает сводный источник правил:
    system, template либо session; у каждой проверки есть отдельный
    rule_source с учётом неприменимости к конкретному датасету.

    column (2026-08-14) -- эхо переданного query-параметра column, если
    был задан. None значит "весь датасет" (старое поведение, backward
    compatible). Часть проверок (см. ValidationCheckResult.scope) учитывают
    column, часть принципиально нет -- см. validation/engine.py::_run_all_checks.
    """
    is_valid: bool
    rules_source: Literal["system", "template", "session"] = Field(
        "system",
        description="Сводный источник: system | template | session",
    )
    validation_template_id: str = Field("system", description="Активный шаблон правил текущей сессии")
    column: Optional[str] = Field(None, description="Колонка, до которой скоупились применимые проверки; None -- весь датасет")
    total_rows: int
    total_columns: int
    type_validation_mode: Literal["profile", "schema"] = Field(
        "profile",
        description="'profile' -- только фактические типы; 'schema' -- выполнена сверка с ожидаемой Pandera-схемой",
    )
    type_profile: List[ValidationTypeProfileOut] = Field(
        default_factory=list,
        description="Фактический профиль типов колонок; переиспользует контракт columns_info вкладки «Загрузка»",
    )
    checks: Dict[str, ValidationCheckResult]


class TypeConversionSpec(BaseModel):
    column: str = Field(..., min_length=1)
    target_type: Literal["integer", "float", "datetime", "string", "boolean"]


class DatasetTypeConversionRequest(BaseModel):
    conversions: List[TypeConversionSpec] = Field(..., min_length=1, max_length=100)
    invalid_policy: Literal["reject", "coerce"] = "reject"
    apply: bool = Field(False, description="False -- preview без мутации; True -- применить к session.dataframe")


class DatasetTypeSchemaRequest(BaseModel):
    columns: List[TypeConversionSpec] = Field(..., min_length=1, max_length=100)


class DatasetTypeSchemaResponse(BaseModel):
    saved: bool = True
    columns: List[TypeConversionSpec]


class DatasetValidationRulesRequest(BaseModel):
    template_id: Literal["system", "default", "fao_prices", "macro"] = "system"
    overrides: Dict[str, Any] = Field(default_factory=dict)


class DatasetValidationRulesResponse(BaseModel):
    template_id: str
    overrides: Dict[str, Any] = Field(default_factory=dict)


class DatasetValidationCheckModesRequest(BaseModel):
    modes: Dict[str, Literal["auto", "enabled", "disabled"]] = Field(default_factory=dict)


class DatasetValidationCheckModesResponse(BaseModel):
    modes: Dict[str, Literal["auto", "enabled", "disabled"]]


class TypeConversionResultOut(BaseModel):
    column: str
    from_dtype: str
    to_dtype: str
    converted_count: int
    invalid_count: int
    invalid_examples: List[str] = Field(default_factory=list)


class DatasetTypeConversionResponse(BaseModel):
    applied: bool
    invalid_policy: Literal["reject", "coerce"]
    total_invalid: int
    target_column_reset: bool = False
    columns: List[TypeConversionResultOut]
    type_profile: List[ValidationTypeProfileOut]


class FormatProfileItemOut(BaseModel):
    column: str
    pattern: str
    threshold: float
    total_count: int
    valid_count: int
    invalid_count: int
    match_pct: Optional[float] = None
    invalid_examples: List[str] = Field(default_factory=list)


class DatasetFormatProfileResponse(BaseModel):
    rule_source: Literal["system", "template", "session", "not_applicable"]
    columns: List[FormatProfileItemOut] = Field(default_factory=list)


class DatasetFormatCorrectionRequest(BaseModel):
    columns: List[str] = Field(..., min_length=1, max_length=100)
    strategy: Literal["replace_null", "smart_replace", "normalize", "flag"] = "flag"
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class FormatCorrectionResultOut(BaseModel):
    column: str
    invalid_count: int
    changed_count: int
    still_invalid: int
    invalid_examples: List[str] = Field(default_factory=list)
    flag_column: Optional[str] = None


class DatasetFormatCorrectionResponse(BaseModel):
    applied: bool
    strategy: Literal["replace_null", "smart_replace", "normalize", "flag"]
    total_violations: int
    total_changed: int
    total_still_invalid: int
    added_columns: List[str] = Field(default_factory=list)
    columns: List[FormatCorrectionResultOut]
    profile: List[FormatProfileItemOut]


class RangeProfileItemOut(BaseModel):
    column: str
    rule_name: str
    min_allowed: Optional[float] = None
    max_allowed: Optional[float] = None
    actual_min: Optional[float] = None
    actual_max: Optional[float] = None
    total_count: int
    valid_count: int
    invalid_count: int
    invalid_pct: Optional[float] = None
    invalid_examples: List[float] = Field(default_factory=list)


class DatasetRangeProfileResponse(BaseModel):
    rule_source: Literal["system", "template", "session", "not_applicable"]
    columns: List[RangeProfileItemOut] = Field(default_factory=list)


class DatasetRangeCorrectionRequest(BaseModel):
    columns: List[str] = Field(..., min_length=1, max_length=100)
    strategy: Literal["clip", "median", "replace_null", "drop_rows", "flag"] = "clip"
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class RangeCorrectionResultOut(BaseModel):
    column: str
    invalid_count: int
    changed_count: int
    still_invalid: int
    invalid_examples: List[float] = Field(default_factory=list)
    flag_column: Optional[str] = None


class DatasetRangeCorrectionResponse(BaseModel):
    applied: bool
    strategy: Literal["clip", "median", "replace_null", "drop_rows", "flag"]
    total_violations: int
    total_changed: int
    total_still_invalid: int
    rows_removed: int = 0
    added_columns: List[str] = Field(default_factory=list)
    columns: List[RangeCorrectionResultOut]
    profile: List[RangeProfileItemOut]


class MissingProfileItemOut(BaseModel):
    column: str
    dtype: str
    semantic: Literal["numeric", "datetime", "categorical", "text"]
    total_count: int
    missing_count: int
    non_missing_count: int
    missing_pct: Optional[float] = None
    recommended_strategy: Literal[
        "none", "drop_rows", "median_mode", "mean_mode", "constant", "interpolate", "flag"
    ]
    missing_examples: List[int] = Field(default_factory=list)


class MissingRowHistogramItemOut(BaseModel):
    missing_in_row: int
    row_count: int


class DatasetMissingProfileResponse(BaseModel):
    rule_source: Literal["system", "not_applicable"]
    # Режимы остановки «Пропуски» модуля «Предобработка» -- та же семантика
    # auto/enabled/disabled, что и validation_check_modes (Task 47), но
    # применённая к остановке степпера, а не к правилу валидации: у
    # проверки пропусков нет отдельного "правила" для настройки, она
    # безусловна для любого датасета, поэтому auto и enabled расходятся
    # ТОЛЬКО в одном случае -- см. _preprocessing_missing_status в
    # apps/api/routers/session.py.
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    total_rows: int
    total_columns: int
    total_missing: int
    missing_rate_pct: Optional[float] = None
    rows_with_missing: int
    rows_with_missing_pct: Optional[float] = None
    empty_rows: int
    columns: List[MissingProfileItemOut] = Field(default_factory=list)
    row_histogram: List[MissingRowHistogramItemOut] = Field(default_factory=list)


class DatasetMissingCorrectionRequest(BaseModel):
    columns: List[str] = Field(..., min_length=1, max_length=100)
    strategy: Literal["drop_rows", "median_mode", "mean_mode", "constant", "interpolate", "flag"] = "median_mode"
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class MissingColumnStatsOut(BaseModel):
    """Mean/std/median одной колонки -- используется и для "before", и для
    "after" в прогнозе влияния стратегии на статистики (перенос app.py
    "Прогноз влияния на статистики"). Поля Optional по отдельности (не
    весь объект), чтобы отличать "числовая колонка без валидных значений"
    (объект есть, поля None) от "колонка не числовая" (stats_* is None)."""
    mean: Optional[float] = None
    std: Optional[float] = None
    median: Optional[float] = None


class MissingCorrectionResultOut(BaseModel):
    column: str
    missing_count: int
    changed_count: int
    still_missing: int
    missing_examples: List[int] = Field(default_factory=list)
    flag_column: Optional[str] = None
    stats_before: Optional[MissingColumnStatsOut] = None
    stats_after: Optional[MissingColumnStatsOut] = None


class DatasetMissingCorrectionResponse(BaseModel):
    applied: bool
    strategy: str
    total_missing: int
    total_changed: int
    total_still_missing: int
    rows_removed: int = 0
    added_columns: List[str] = Field(default_factory=list)
    columns: List[MissingCorrectionResultOut]
    profile: List[MissingProfileItemOut]


class DatasetPreprocessingCheckModesRequest(BaseModel):
    modes: Dict[str, Literal["auto", "enabled", "disabled"]] = Field(default_factory=dict)


class DatasetPreprocessingCheckModesResponse(BaseModel):
    modes: Dict[str, Literal["auto", "enabled", "disabled"]]


class MissingMatrixBinOut(BaseModel):
    bin_index: int
    row_start: int
    row_end: int
    row_count: int
    missing_share: Dict[str, float]


class DatasetMissingMatrixResponse(BaseModel):
    columns: List[str]
    bins: List[MissingMatrixBinOut] = Field(default_factory=list)
    rows_per_bin: int = 0
    total_rows: int = 0


class DatasetMissingCorrelationResponse(BaseModel):
    columns: List[str]
    matrix: List[List[Optional[float]]] = Field(default_factory=list)


class MissingDistributionGroupOut(BaseModel):
    count: int
    min: float
    q1: float
    median: float
    q3: float
    max: float
    mean: float


class DatasetMissingDistributionResponse(BaseModel):
    value_column: str
    indicator_column: str
    with_missing: Optional[MissingDistributionGroupOut] = None
    without_missing: Optional[MissingDistributionGroupOut] = None


class OutlierBoundsOut(BaseModel):
    lower: float
    upper: float


class OutlierProfileItemOut(BaseModel):
    column: str
    sample_size: int
    outlier_count: int
    outlier_pct: Optional[float] = None
    recommended_method: Literal["iqr", "zscore", "mad", "percentile"]
    bounds: Optional[OutlierBoundsOut] = None
    outlier_examples: List[int] = Field(default_factory=list)
    insufficient_sample: bool = False


class DatasetOutlierProfileResponse(BaseModel):
    rule_source: Literal["system", "not_applicable"]
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    method: Literal["iqr", "zscore", "mad", "percentile"]
    total_rows: int
    total_numeric_columns: int
    total_outliers: int
    outlier_rate_pct: Optional[float] = None
    affected_columns: List[str] = Field(default_factory=list)
    columns: List[OutlierProfileItemOut] = Field(default_factory=list)


class DatasetOutlierCorrectionRequest(BaseModel):
    columns: List[str] = Field(..., min_length=1, max_length=100)
    strategy: Literal["drop_rows", "cap", "median", "flag"] = "cap"
    method: Literal["iqr", "zscore", "mad", "percentile"] = "iqr"
    param: Optional[Any] = None
    use_residual: bool = False
    date_column: Optional[str] = None
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class OutlierCorrectionResultOut(BaseModel):
    column: str
    outlier_count: int
    changed_count: int
    still_outliers: int
    outlier_examples: List[int] = Field(default_factory=list)
    flag_column: Optional[str] = None
    stats_before: Optional[MissingColumnStatsOut] = None
    stats_after: Optional[MissingColumnStatsOut] = None


class OutlierScatterPointOut(BaseModel):
    x: int
    y: float


class DatasetOutlierLineResponse(BaseModel):
    """Точки для «Линейного» графика вкладки визуализаций остановки
    «Выбросы» -- прямое переиспользование build_scatter_series
    (apps/api/chart_data.py), тот же контракт, что и у графика
    распределения на вкладке «Загрузка» (гарантирует сохранение
    глобальных min/max и IQR-выбросов при LTTB-сэмплинге)."""
    points: List[OutlierScatterPointOut] = Field(default_factory=list)
    sampled: bool = False
    sampling_method: Optional[str] = None
    original_count: int = 0


class OutlierHistogramBinOut(BaseModel):
    x0: float
    x1: float
    count: int


class DatasetOutlierHistogramResponse(BaseModel):
    bins: List[OutlierHistogramBinOut] = Field(default_factory=list)
    bounds: Optional[OutlierBoundsOut] = None


class OutlierDensityPointOut(BaseModel):
    x: float
    y: float


class DatasetOutlierDensityResponse(BaseModel):
    points: Optional[List[OutlierDensityPointOut]] = None


class OutlierBoxplotGroupOut(BaseModel):
    count: int
    min: float
    q1: float
    median: float
    q3: float
    max: float
    mean: float


class DatasetOutlierBoxplotResponse(BaseModel):
    column: str
    outliers: Optional[OutlierBoxplotGroupOut] = None
    normal: Optional[OutlierBoxplotGroupOut] = None


class DatasetOutlierCorrectionResponse(BaseModel):
    applied: bool
    strategy: str
    method: str
    used_residual: bool = False
    total_outliers: int
    total_changed: int
    total_still_outliers: int
    rows_removed: int = 0
    added_columns: List[str] = Field(default_factory=list)
    columns: List[OutlierCorrectionResultOut]
    profile: List[OutlierProfileItemOut]


class InclusionInvalidValueOut(BaseModel):
    value: str
    count: int


class InclusionProfileItemOut(BaseModel):
    column: str
    allowed_values: List[Any] = Field(default_factory=list)
    allowed_count: int
    total_count: int
    valid_count: int
    invalid_count: int
    invalid_pct: Optional[float] = None
    invalid_values: List[InclusionInvalidValueOut] = Field(default_factory=list)
    default_value: Optional[Any] = None
    default_valid: bool = False
    supported_actions: List[str] = Field(default_factory=list)


class DatasetInclusionProfileResponse(BaseModel):
    rule_source: Literal["system", "template", "session", "not_applicable"]
    columns: List[InclusionProfileItemOut] = Field(default_factory=list)


class DatasetInclusionCorrectionRequest(BaseModel):
    columns: List[str] = Field(..., min_length=1, max_length=100)
    strategy: Literal["mode", "replace_null", "drop_rows", "replace_default", "flag"] = "mode"
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class InclusionCorrectionResultOut(BaseModel):
    column: str
    invalid_count: int
    changed_count: int
    still_invalid: int
    replacement_value: Optional[Any] = None
    flag_column: Optional[str] = None


class DatasetInclusionCorrectionResponse(BaseModel):
    applied: bool
    strategy: Literal["mode", "replace_null", "drop_rows", "replace_default", "flag"]
    total_violations: int
    total_changed: int
    total_still_invalid: int
    rows_removed: int = 0
    added_columns: List[str] = Field(default_factory=list)
    columns: List[InclusionCorrectionResultOut]
    profile: List[InclusionProfileItemOut]


class ReferentialProfileItemOut(BaseModel):
    rule_index: int
    rule_name: str
    child_column: str
    allowed_values: List[Any] = Field(default_factory=list)
    reference_count: int
    applicable: bool
    applicability_message: Optional[str] = None
    total_count: int
    valid_count: int
    invalid_count: Optional[int] = None
    invalid_pct: Optional[float] = None
    invalid_values: List[InclusionInvalidValueOut] = Field(default_factory=list)
    default_value: Optional[Any] = None
    default_valid: bool = False
    supported_actions: List[str] = Field(default_factory=list)


class DatasetReferentialProfileResponse(BaseModel):
    rule_source: Literal["system", "template", "session", "not_applicable"]
    rules: List[ReferentialProfileItemOut] = Field(default_factory=list)


class DatasetReferentialCorrectionRequest(BaseModel):
    rule_indices: List[int] = Field(..., min_length=1, max_length=100)
    strategy: Literal["mode", "replace_null", "drop_rows", "replace_default", "flag"] = "mode"
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class ReferentialCorrectionResultOut(BaseModel):
    rule_index: int
    rule_name: str
    child_column: str
    invalid_count: int
    changed_count: int
    still_invalid: int
    replacement_value: Optional[Any] = None
    flag_column: Optional[str] = None


class DatasetReferentialCorrectionResponse(BaseModel):
    applied: bool
    strategy: Literal["mode", "replace_null", "drop_rows", "replace_default", "flag"]
    total_violations: int
    total_changed: int
    total_still_invalid: int
    rows_removed: int = 0
    added_columns: List[str] = Field(default_factory=list)
    rules: List[ReferentialCorrectionResultOut]
    profile: List[ReferentialProfileItemOut]


class TextQualityIssueCountsOut(BaseModel):
    garbage: int = 0
    empty: int = 0
    too_short: int = 0
    too_long: int = 0
    whitespace: int = 0
    pattern: int = 0


class TextQualityProfileItemOut(BaseModel):
    column: str
    total_count: int
    valid_count: int
    invalid_count: int
    invalid_pct: Optional[float] = None
    min_length: int
    max_length: int
    issue_counts: TextQualityIssueCountsOut
    invalid_examples: List[str] = Field(default_factory=list)
    supported_actions: List[str] = Field(default_factory=list)


class DatasetTextQualityProfileResponse(BaseModel):
    rule_source: Literal["system", "template", "session", "not_applicable"]
    columns: List[TextQualityProfileItemOut] = Field(default_factory=list)


class DatasetTextQualityCorrectionRequest(BaseModel):
    columns: List[str] = Field(..., min_length=1, max_length=100)
    strategy: Literal["normalize", "replace_null", "drop_rows", "replace_unknown", "flag"] = "normalize"
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class TextQualityCorrectionResultOut(BaseModel):
    column: str
    invalid_count: int
    changed_count: int
    still_invalid: int
    flag_column: Optional[str] = None


class DatasetTextQualityCorrectionResponse(BaseModel):
    applied: bool
    strategy: Literal["normalize", "replace_null", "drop_rows", "replace_unknown", "flag"]
    total_violations: int
    total_changed: int
    total_still_invalid: int
    rows_removed: int = 0
    added_columns: List[str] = Field(default_factory=list)
    columns: List[TextQualityCorrectionResultOut]
    profile: List[TextQualityProfileItemOut]


class RegularityGapExampleOut(BaseModel):
    previous_date: str
    current_date: str
    missing_periods: int


class RegularityGroupOut(BaseModel):
    group: str
    observations: int
    inferred_frequency: Optional[str] = None
    modal_interval: Optional[str] = None
    gap_count: int
    missing_period_count: int
    duplicate_count: int
    sort_violations: int
    gap_examples: List[RegularityGapExampleOut] = Field(default_factory=list)


class RegularityProfileOut(BaseModel):
    applicable: bool
    applicability_message: Optional[str] = None
    date_column: Optional[str] = None
    entity_column: Optional[str] = None
    target_frequency: Optional[str] = None
    detected_frequency: Optional[str] = None
    gap_threshold_multiplier: float = 1.5
    is_sorted: bool
    sort_violations: int
    invalid_date_count: int
    duplicate_count: int
    gap_count: int
    missing_period_count: int
    total_violations: int
    groups: List[RegularityGroupOut] = Field(default_factory=list)
    supported_actions: List[str] = Field(default_factory=list)


class DatasetRegularityProfileResponse(BaseModel):
    rule_source: Literal["system", "template", "session", "not_applicable"]
    profile: RegularityProfileOut


class DatasetRegularityCorrectionRequest(BaseModel):
    strategy: Literal["sort", "interpolate", "ffill", "bfill", "asfreq", "fictitious_zero", "flag"] = "interpolate"
    frequency: Optional[str] = None
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class DatasetRegularityCorrectionResponse(BaseModel):
    applied: bool
    strategy: str
    frequency: Optional[str] = None
    rows_before: int
    rows_after: int
    rows_added: int
    duplicates_aggregated: int
    total_violations_before: int
    total_violations_after: int
    sort_violations_before: int
    sort_violations_after: int
    added_columns: List[str] = Field(default_factory=list)
    profile: RegularityProfileOut


class DatasetPreprocessingRegularityProfileResponse(BaseModel):
    """Обёртка RegularityProfileOut для остановки «Регулярность» модуля
    «Предобработка» -- тот же профиль, что и у «Валидации», но с полями
    mode/status/status_reason режима остановки (auto/enabled/disabled),
    как у DatasetMissingProfileResponse/DatasetOutlierProfileResponse.
    У «Регулярности» тоже нет отдельного настраиваемого «правила»: она
    либо применима (найдена колонка с датой, ≥2 корректных меток), либо
    нет -- то же самое разграничение auto/enabled, что и у Пропусков/
    Выбросов (расходятся только через explicit disabled)."""
    mode: Literal["auto", "enabled", "disabled"] = "auto"
    status: Literal["done", "warning", "pending", "skipped"] = "pending"
    status_reason: Optional[Literal["not_required", "disabled"]] = None
    profile: RegularityProfileOut


class RegularityIntervalBucketOut(BaseModel):
    """Один бин гистограммы интервалов между соседними наблюдениями --
    данные для графика «Интервалы» Обзора остановки «Регулярность»."""
    x0: float
    x1: float
    count: int


class DatasetRegularityIntervalsResponse(BaseModel):
    group: str
    unit: Literal["seconds"] = "seconds"
    bins: List[RegularityIntervalBucketOut] = Field(default_factory=list)
    modal_seconds: Optional[float] = None
    threshold_seconds: Optional[float] = None


class RegularityTimelineEventOut(BaseModel):
    date: str
    kind: Literal["gap", "duplicate", "sort_violation"]
    group: str


class DatasetRegularityTimelineResponse(BaseModel):
    date_column: Optional[str] = None
    entity_column: Optional[str] = None
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    events: List[RegularityTimelineEventOut] = Field(default_factory=list)
    truncated: bool = False


class SufficiencyCheckOut(BaseModel):
    id: str
    label: str
    actual: int
    threshold: int
    unit: str
    passed: bool
    deficit: int
    models: str


class SufficiencyThresholdOut(BaseModel):
    id: str
    label: str
    threshold: int
    unit: str
    models: str


class SufficiencyGroupOut(BaseModel):
    group: str
    rows_total: int
    valid_observations: int
    invalid_target_count: int
    invalid_date_count: int
    unique_timestamps: int
    frequency: Optional[str] = None
    seasonal_period: int
    seasonal_cycles: int
    failed_checks: int
    passed_checks: int
    checks: List[SufficiencyCheckOut] = Field(default_factory=list)
    available_capabilities: List[str] = Field(default_factory=list)
    unavailable_capabilities: List[str] = Field(default_factory=list)


class SufficiencyProfileOut(BaseModel):
    applicable: bool
    applicability_message: Optional[str] = None
    date_column: Optional[str] = None
    entity_column: Optional[str] = None
    target_column: Optional[str] = None
    frequency: Optional[str] = None
    seasonal_period: Optional[int] = None
    groups_total: int
    sufficient_groups: int
    insufficient_groups: int
    total_failed_checks: int
    groups: List[SufficiencyGroupOut] = Field(default_factory=list)
    thresholds: List[SufficiencyThresholdOut] = Field(default_factory=list)
    supported_actions: List[str] = Field(default_factory=list)


class DatasetSufficiencyProfileResponse(BaseModel):
    rule_source: Literal["system", "template", "session", "not_applicable"]
    plan: Dict[str, Any] = Field(default_factory=dict)
    profile: SufficiencyProfileOut


class DatasetSufficiencyPlanRequest(BaseModel):
    strategy: Literal["restrict_models", "flag_groups", "drop_groups"] = "restrict_models"
    apply: bool = Field(False, description="False -- preview; True -- сохранить решение в сессии")


class DatasetSufficiencyPlanResponse(BaseModel):
    applied: bool
    strategy: str
    rows_before: int
    rows_after: int
    rows_removed: int
    added_columns: List[str] = Field(default_factory=list)
    eligible_groups: List[str] = Field(default_factory=list)
    insufficient_groups: List[str] = Field(default_factory=list)
    profile: SufficiencyProfileOut


class ConsistencyProfileItemOut(BaseModel):
    rule_index: int
    rule_name: str
    rule_type: str
    description: Optional[str] = None
    columns: List[str] = Field(default_factory=list)
    time_column: Optional[str] = None
    group_column: Optional[str] = None
    applicable: bool
    applicability_message: Optional[str] = None
    checked_count: int = 0
    valid_count: int = 0
    invalid_count: Optional[int] = None
    affected_rows: int = 0
    invalid_examples: List[str] = Field(default_factory=list)
    supported_actions: List[str] = Field(default_factory=list)


class DatasetConsistencyProfileResponse(BaseModel):
    rule_source: Literal["system", "template", "session", "not_applicable"]
    rules: List[ConsistencyProfileItemOut] = Field(default_factory=list)


class DatasetConsistencyCorrectionRequest(BaseModel):
    rule_indices: List[int] = Field(..., min_length=1, max_length=100)
    strategy: Literal["sort_chronology", "drop_rows", "replace_null", "flag"] = "flag"
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class ConsistencyCorrectionResultOut(BaseModel):
    rule_index: int
    rule_name: str
    invalid_count: int
    affected_rows: int
    changed_count: int
    still_invalid: int
    flag_column: Optional[str] = None


class DatasetConsistencyCorrectionResponse(BaseModel):
    applied: bool
    strategy: Literal["sort_chronology", "drop_rows", "replace_null", "flag"]
    total_violations: int
    total_changed: int
    total_still_invalid: int
    rows_removed: int = 0
    added_columns: List[str] = Field(default_factory=list)
    rules: List[ConsistencyCorrectionResultOut]
    profile: List[ConsistencyProfileItemOut]


class UniquenessGroupOut(BaseModel):
    key_values: Dict[str, str] = Field(default_factory=dict)
    occurrences: int
    redundant_rows: int
    row_numbers: List[int] = Field(default_factory=list)


class UniquenessProfileOut(BaseModel):
    applicable: bool
    applicability_message: Optional[str] = None
    mode: Literal["composite_key", "inferred_key", "full_row"]
    key_columns: List[str] = Field(default_factory=list)
    total_rows: int
    valid_rows: int
    duplicate_rows: Optional[int] = None
    duplicate_groups: Optional[int] = None
    redundant_rows: Optional[int] = None
    duplicate_pct: Optional[float] = None
    groups: List[UniquenessGroupOut] = Field(default_factory=list)
    supported_actions: List[str] = Field(default_factory=list)


class DatasetUniquenessProfileResponse(BaseModel):
    rule_source: Literal["system", "template", "session", "not_applicable"]
    profile: UniquenessProfileOut


class DatasetUniquenessCorrectionRequest(BaseModel):
    strategy: Literal["keep_first", "keep_last", "drop_all", "aggregate", "flag"] = "keep_first"
    apply: bool = Field(False, description="False -- preview; True -- сохранить в сессии")


class DatasetUniquenessCorrectionResponse(BaseModel):
    applied: bool
    strategy: Literal["keep_first", "keep_last", "drop_all", "aggregate", "flag"]
    duplicate_rows: int
    redundant_rows: int
    rows_changed: int
    rows_removed: int
    still_duplicate_rows: int
    added_columns: List[str] = Field(default_factory=list)
    profile: UniquenessProfileOut


class DatasetSummaryOut(BaseModel):
    """Сводка по активному датасету сессии -- для Home page ("Рабочий стол")."""
    dataset_id: str
    name: str
    rows: int
    columns: int
    size_label: str


class SessionStateResponse(BaseModel):
    """Состояние AnalysisSession -- см. apps/api/session_store.py.
    Sessions-aware Home page решает "рабочий стол vs онбординг/маркетинг"
    по полю has_active_dataset.

    Phase 0.5: target_column -- выбранная прогнозируемая колонка (мост
    Upload → Backtest). None, если пользователь ещё не выбрал.
    """
    has_active_dataset: bool
    dataset: Optional[DatasetSummaryOut] = None
    stages: Dict[str, str]
    last_active_stage: Optional[str] = None
    target_column: Optional[str] = None
    date_column: Optional[str] = None
    updated_at: Optional[str] = None


# ── Target column (Phase 0.5) ──

class TargetColumnRequest(BaseModel):
    """Запрос: установить выбранную прогнозируемую колонку."""
    column: str = Field(..., description="Имя колонки в загруженном датасете")


class TargetColumnResponse(BaseModel):
    """Ответ: текущая target_column + список доступных числовых колонок.

    available_columns нужен UI для отрисовки селектора. Содержит ТОЛЬКО
    числовые колонки -- target для TS-прогноза должен быть числовым.

    suggested_column -- эвристический дефолт для UI, когда target_column
    ещё не выбран пользователем (свежий датасет): первая числовая колонка,
    ИСКЛЮЧАЯ похожие на дату/год по имени (см. _suggest_target_column).
    Раньше каждая вкладка (Загрузка/Валидация) считала свой дефолт
    независимо (просто первая числовая колонка без исключений) -- отсюда
    несогласованность между вкладками и выбор 'Year' вместо 'Price' на
    датасетах вида FAO (Country, Year, Price, ...). Единая эвристика на
    бэкенде -- единственный источник истины для ВСЕХ фронтендов.
    None только если available_columns пуст (нет числовых колонок вообще).
    """
    target_column: Optional[str] = None
    suggested_column: Optional[str] = None
    available_columns: List[str] = Field(
        default_factory=list,
        description="Числовые колонки, доступные для выбора как target",
    )
    has_dataset: bool = Field(
        False, description="Загружен ли датасет (если нет -- выбор target невозможен)"
    )
    passport_history_reset: bool = Field(
        False,
        description="Смена target сбросила историю несопоставимых паспортов",
    )


# ── Date column + session passports ──

PassportStage = Literal["start", "validation", "exit", "modeling_entry"]


class DateColumnRequest(BaseModel):
    column: str = Field(..., min_length=1, description="Имя временной колонки")


class DateColumnCandidateOut(BaseModel):
    name: str
    score: float = Field(..., ge=0, le=1)


class DateColumnResponse(BaseModel):
    date_column: Optional[str] = None
    suggested_column: Optional[str] = None
    candidates: List[DateColumnCandidateOut] = Field(default_factory=list)
    has_dataset: bool = False
    passport_history_reset: bool = False


class PassportPointStatusOut(BaseModel):
    captured: bool = False
    captured_at: Optional[str] = None
    is_stale: Optional[bool] = None
    fingerprint: Optional[str] = None
    history_count: int = 0


class PassportCheckpointStatusOut(PassportPointStatusOut):
    checkpoint_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    source_stage: Optional[PassportStage] = None
    reused_snapshot: Optional[bool] = None


class DatasetPassportStatusResponse(BaseModel):
    has_dataset: bool
    target_column: Optional[str] = None
    date_column: Optional[str] = None
    series_ready: bool = False
    reason: Optional[str] = None
    current_fingerprint: Optional[str] = None
    start: PassportPointStatusOut
    validation: PassportPointStatusOut
    exit: PassportPointStatusOut
    modeling_entry: PassportCheckpointStatusOut


class DatasetPassportCaptureResponse(BaseModel):
    snapshot_id: str
    stage: PassportStage
    passport: Dict[str, Any]
    fingerprint: str
    target_column: str
    date_column: Optional[str] = None
    captured_at: str
    checkpoint_id: Optional[str] = None
    source_stage: Optional[PassportStage] = None
    reused_snapshot: bool = False


class PassportComparisonPairOut(BaseModel):
    from_stage: PassportStage
    to_stage: PassportStage
    from_snapshot_id: str
    to_snapshot_id: str
    comparison: Dict[str, Any]


class PassportCheckpointOut(BaseModel):
    checkpoint_id: str
    stage: Literal["modeling_entry"]
    snapshot_id: str
    source_stage: PassportStage
    reused_snapshot: bool
    unchanged_from_previous: bool
    confirmed_at: str


class DatasetPassportCompareResponse(BaseModel):
    target_column: str
    date_column: Optional[str] = None
    path: List[PassportStage]
    comparisons: List[PassportComparisonPairOut]
    checkpoint: Optional[PassportCheckpointOut] = None


# ── Управление правилами валидации ──

class RulesTemplate(BaseModel):
    """Один доступный шаблон правил."""
    id: str = Field(..., description="Идентификатор шаблона (совпадает с именем YAML без расширения)")
    label: str = Field(..., description="Человекочитаемое название")
    description: Optional[str] = Field(None, description="Краткое описание шаблона")


class RulesTemplatesResponse(BaseModel):
    """Ответ: список доступных шаблонов."""
    templates: List[RulesTemplate]


class RangeRule(BaseModel):
    """Одно правило диапазона (ranges[] из YAML)."""
    name: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None
    description: Optional[str] = None


class RulesContent(BaseModel):
    """Содержимое загруженного шаблона правил."""
    ranges: List[RangeRule] = Field(default_factory=list)
    inclusion: Optional[Dict[str, Any]] = None
    consistency: Optional[List[Dict[str, Any]]] = None
    uniqueness: Optional[Dict[str, Any]] = None
    formats: Optional[Dict[str, Any]] = None
    referential: Optional[List[Dict[str, Any]]] = None
    text_quality: Optional[Dict[str, Any]] = None
    regularity: Optional[Dict[str, Any]] = None
    outliers: Optional[Dict[str, Any]] = None
    sufficiency: Optional[Dict[str, Any]] = None


class RulesLoadResponse(BaseModel):
    """Ответ: загруженные правила из шаблона."""
    template_id: str
    rules: RulesContent


class ValidateWithRulesRequest(BaseModel):
    """Запрос: запустить валидацию по шаблону правил."""
    template_id: str = Field(..., description="Идентификатор шаблона")
    series: List[SeriesPoint] = Field(..., min_length=1)


class ValidateSummary(BaseModel):
    """Сводка результатов валидации."""
    total_errors: int = 0
    total_warnings: int = 0
    checks_run: int = 0


class ValidateWithRulesResponse(BaseModel):
    """Ответ: результаты валидации."""
    is_valid: bool
    summary: ValidateSummary
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)


# ── Обновление правил in-memory ──

class RulesUpdateRequest(BaseModel):
    """Запрос: обновить диапазоны правил для шаблона (in-memory, не файл)."""
    template_id: str = Field(..., description="Идентификатор шаблона")
    ranges: List[RangeRule] = Field(..., description="Обновлённый список диапазонов")


class RulesUpdateResponse(BaseModel):
    """Ответ: подтверждение обновления правил."""
    template_id: str
    updated_ranges_count: int
    message: str = "Правила обновлены in-memory. Перезапустите валидацию."
    """Ответ: подтверждение обновления правил."""
    template_id: str
    updated_ranges_count: int
    message: str = "Правила обновлены in-memory. Перезапустите валидацию."


# ── Моделирование: пул кандидатов ──

class DataProfileRequest(BaseModel):
    """Профиль данных — вход движка применимости."""
    n_observations: int = Field(..., ge=1, description="Число наблюдений")
    n_series: int = Field(1, ge=1, description="Число временных рядов")
    n_exogenous: int = Field(0, ge=0, description="Число экзогенных признаков")
    is_regular: bool = Field(True, description="Регулярность временного индекса")
    frequency: str = Field("M", description="Частота ряда (D/W/M/Q/Y)")
    has_seasonality: bool = Field(False, description="Наличие сезонности")
    seasonal_periods: List[int] = Field(default_factory=list, description="Сезонные периоды")
    is_stationary_or_diffable: bool = Field(True, description="Стационарность или дифференцируемость")
    is_cointegrated: bool = Field(False, description="Коинтеграция (для многомерных)")
    has_negative_values: bool = Field(False, description="Наличие отрицательных значений")
    has_volatility_clustering: bool = Field(False, description="Кластеризация волатильности")
    domain: str = Field("other", description="Предметная область (financial/macro/price/other)")
    missing_ratio: float = Field(0.0, ge=0.0, le=1.0, description="Доля пропусков")
    outlier_ratio: float = Field(0.0, ge=0.0, le=1.0, description="Доля выбросов")
    has_holidays: bool = Field(False, description="Наличие праздничных эффектов")
    gpu_available: bool = Field(False, description="Доступность GPU")
    feature_engineering_applied: bool = Field(False, description="Feature engineering выполнен")


class ModelCandidate(BaseModel):
    """Один кандидат в пуле моделирования."""
    model_id: str
    model_name: str
    family_id: str
    level: str = Field(..., description="Уровень применимости")
    rule_id: Optional[str] = Field(None, description="ID правила, определившего уровень")
    message: str = Field("", description="Пояснение уровня применимости")
    rank: int = Field(1, ge=1, description="Ранг уровня (1=RECOMMENDED)")
    platform_status: Literal["ready", "catalog_only"] = Field(
        ..., description="Наличие реальной production-реализации модели",
    )
    available_actions: List[Literal["backtest", "tune", "diagnostics"]] = Field(
        default_factory=list,
        description="Только действия, реально поддержанные backend",
    )
    blocking_reason: Optional[str] = Field(
        None, description="Почему модель нельзя запустить для текущего контекста",
    )


class CandidatesRequest(BaseModel):
    """Запрос: получить пул кандидатов для моделирования."""
    profile: DataProfileRequest
    min_level: Optional[str] = Field(
        "CONDITIONALLY_APPLICABLE",
        description="Минимальный уровень применимости для включения в пул",
    )


class CandidatesStatistics(BaseModel):
    """Статистика по пулу кандидатов."""
    total_candidates: int
    by_level: Dict[str, int] = Field(default_factory=dict)
    total_models_in_spec: int = Field(0, description="Общее число моделей в спецификации")
    runnable_candidates: int = Field(0, description="Кандидаты с доступным production backtest")
    catalog_only_candidates: int = Field(0, description="Модели полного каталога без production backtest")
    blocked_candidates: int = Field(0, description="Production-модели полного каталога, заблокированные текущими данными")


class CandidatesResponse(BaseModel):
    """Ответ: пул кандидатов для моделирования."""
    candidates: List[ModelCandidate]
    catalog: List[ModelCandidate] = Field(
        default_factory=list,
        description=(
            "Полный каталог моделей спецификации, включая NOT_RECOMMENDED "
            "и NOT_APPLICABLE; candidates остаётся профильным shortlist"
        ),
    )
    statistics: CandidatesStatistics
    spec_version: str = Field("", description="Версия спецификации modeling.yaml")


# ── Моделирование: бэктест ──

class BacktestRequest(BaseModel):
    """Запрос: запустить бэктест для одной модели."""
    model_id: str = Field(..., description="Идентификатор модели (из пула кандидатов)")
    profile: DataProfileRequest
    train_ratio: float = Field(
        0.8, ge=0.5, le=0.95,
        description="Доля обучающей выборки (остальное — тест)",
    )


class BacktestMetrics(BaseModel):
    """Метрики бэктеста."""
    mae: float = Field(..., description="Mean Absolute Error")
    rmse: float = Field(..., description="Root Mean Squared Error")
    mape: Optional[float] = Field(None, description="MAPE (%); null, если в holdout нет ненулевых фактов")
    mase: Optional[float] = Field(None, description="MASE с train-only seasonal scale; null при нулевом scale")
    smape: Optional[float] = Field(None, description="Symmetric MAPE (%)")
    rmsse: Optional[float] = Field(None, description="Root Mean Squared Scaled Error")
    mape_valid_points: int = Field(0, ge=0, description="Число OOF-точек, на которых MAPE определена")
    weighted_score: Optional[float] = Field(
        None,
        description=(
            "Legacy score для старых endpoints/tuning. В каноническом backtest null: "
            "нормализация допустима только внутри общего comparison cohort."
        ),
    )


class BacktestPredictionPoint(BaseModel):
    """Одна out-of-fold прогнозная точка."""
    fold: int
    horizon_step: int = Field(..., ge=1)
    index: int = Field(..., ge=0)
    label: Optional[str] = None
    actual: float
    predicted: float
    residual: float


class BacktestFoldResult(BaseModel):
    """Аудируемый результат одного rolling-origin fold."""
    fold: int = Field(..., ge=1)
    status: Literal["success", "failed"]
    train_start: int = Field(..., ge=0)
    train_end: int = Field(..., ge=0)
    test_start: int = Field(..., ge=0)
    test_end: int = Field(..., ge=0)
    gap: int = Field(0, ge=0)
    n_train: int = Field(..., ge=1)
    n_test: int = Field(..., ge=1)
    train_start_label: Optional[str] = None
    train_end_label: Optional[str] = None
    test_start_label: Optional[str] = None
    test_end_label: Optional[str] = None
    metrics: Optional[BacktestMetrics] = None
    predictions: List[BacktestPredictionPoint] = Field(default_factory=list)
    duration_ms: float = Field(..., ge=0)
    error: Optional[str] = None


class BacktestResponse(BaseModel):
    """Ответ: результаты бэктеста модели.

    Phase 0.5: data_source показывает, откуда взят ряд для бэктеста:
      - "synthetic" -- синтетический ряд (поведение до Phase 0.5; /v1/models/backtest)
      - "session"   -- реальный ряд из session.dataframe[target_column]
                        (мост Upload → Backtest; /v1/internal/models/backtest)
    Поле опциональное для backcompat -- старый клиент игнорирует его.
    """
    model_id: str
    model_name: str
    family_id: str
    metrics: BacktestMetrics
    n_train: int = Field(..., description="Число точек обучающей выборки")
    n_test: int = Field(..., description="Число точек тестовой выборки")
    train_ratio: float
    duration_ms: float = Field(..., description="Время расчёта (мс)")
    data_source: Optional[str] = Field(
        None,
        description="Источник ряда: 'session' (реальный из датасета) | 'synthetic' (синтетический)",
    )
    status: Literal["success", "partial"] = "success"
    strategy: Literal["single", "expanding", "sliding"] = "single"
    cohort_id: Optional[str] = Field(None, description="Fingerprint данных и точного набора folds")
    horizon: int = Field(1, ge=1)
    n_folds: int = Field(1, ge=1)
    gap: int = Field(0, ge=0)
    folds: List[BacktestFoldResult] = Field(default_factory=list)
    oof_predictions: List[BacktestPredictionPoint] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    preprocessing: Dict[str, Any] = Field(
        default_factory=dict,
        description="Fold-local preprocessing contract used by this run",
    )
    run_id: Optional[str] = Field(
        None, description="Уникальный идентификатор конкретного исполнения backtest",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict, description="Параметры, фактически использованные во всех folds",
    )
    params_source: Literal["model_default", "tuning", "request"] = Field(
        "model_default", description="Происхождение фактически использованных параметров",
    )
    parameter_signature: Optional[str] = Field(
        None, description="SHA-256 модели и канонического набора параметров",
    )
    tuning_id: Optional[str] = Field(
        None, description="Идентификатор tuning run, если backtest является promoted trial",
    )
    oof_signature: Optional[str] = Field(
        None, description="SHA-256 упорядоченных фактов, прогнозов и остатков OOF",
    )


# ── Моделирование: тюнинг гиперпараметров (Phase 1-C) ───────────────────
#
# POST /v1/models/tune — grid search по param_space модели с expanding-window CV.
# Зависит от Phase 1-A (param_space в спецификации) и Phase 1-B (ExpandingWindowCV).
#
# КОНТРАКТ MAX_TRIALS = 64:
#   - Хардкод-лимит на grid_size (защита от экспоненциального роста).
#   - Если grid_size > MAX_TRIALS → random sampling MAX_TRIALS trials.
#   - Если пользователь запрашивает max_trials < grid_size → random sampling max_trials.
#   - Если пользователь запрашивает max_trials > MAX_TRIALS → clamp до MAX_TRIALS.
#   - Воспроизводимость: random_state (default=42) фиксирует выборку.


class CVConfig(BaseModel):
    """Конфигурация expanding-window cross-validation для tune.

    Все параметры соответствуют apps.api.cv.ExpandingWindowCV.
    None-поля (min_train_size, step) заполняются defaults внутри CV.
    """
    n_splits: int = Field(5, ge=1, description="Число folds CV")
    test_size: int = Field(1, ge=1, description="Длина test-окна в каждом fold")
    min_train_size: Optional[int] = Field(
        None, ge=1,
        description="Размер train в первом fold (default=test_size внутри CV)",
    )
    step: Optional[int] = Field(
        None, ge=1,
        description="Сдвиг test-окна между folds (default=test_size внутри CV)",
    )
    gap: int = Field(
        0, ge=0,
        description="Число наблюдений между train и test для защиты от пограничной утечки",
    )


class TuneRequest(BaseModel):
    """Запрос: grid search гиперпараметров модели через CV.

    Модель должна иметь param_space в спецификации (Phase 1-A).
    Baseline-модели (naive/drift/mean) и модели без гиперпараметров
    (theta) вернут 422 — param_space не задан.

    Серия (series) — фактический временной ряд для CV. Длина должна
    удовлетворять cv.min_samples() (см. apps.api/cv.py).
    """
    model_id: str = Field(..., description="ID модели (должна иметь param_space)")
    series: List[float] = Field(
        ..., min_length=1,
        description="Временной ряд для CV (длина >= cv.min_samples())",
    )
    cv: Optional[CVConfig] = Field(
        None, description="CV config (defaults: n_splits=5, test_size=1)"
    )
    max_trials: Optional[int] = Field(
        None, ge=1,
        description=(
            "Максимум испытаний. None=использовать MAX_TRIALS=64. "
            "Если < grid_size → random sampling. Если > MAX_TRIALS → clamp."
        ),
    )
    metric: Literal["mae", "rmse", "mape", "mase", "weighted_score"] = Field(
        "rmse",
        description="Метрика для выбора лучшего trial'а (minimize)",
    )
    random_state: int = Field(
        42, description="Seed для воспроизводимости random sampling при truncation",
    )


class TuneTrialResult(BaseModel):
    """Один trial grid search'а: одна комбинация params + усреднённые метрики."""
    params: Dict[str, Any] = Field(..., description="Гиперпараметры этого trial'а")
    metrics: BacktestMetrics
    n_folds: int = Field(..., description="Число folds, по которым усреднены метрики")


class TuneFoldPlan(BaseModel):
    """Границы fold, реально исполненные session tuning."""
    fold: int = Field(..., ge=1)
    train_start: int = Field(..., ge=0)
    train_end: int = Field(..., ge=0)
    test_start: int = Field(..., ge=0)
    test_end: int = Field(..., ge=0)
    gap: int = Field(0, ge=0)


class TuneResponse(BaseModel):
    """Ответ: результаты grid search с CV.

    Поля:
      - best_params:  params лучшего trial'а (минимизирует metric).
      - best_metrics: усреднённые метрики лучшего trial'а.
      - best_trial:   index лучшего trial'а в trials[].
      - n_trials:     фактически выполнено trials (после truncation).
      - grid_size:    размер оригинального grid'а (до truncation).
      - truncated:    True, если grid был обрезан max_trials.
      - trials:       все trial'ы с их params и метриками.
    """
    model_id: str
    model_name: str
    family_id: str
    best_params: Dict[str, Any]
    best_metrics: BacktestMetrics
    best_trial: int = Field(..., description="Index лучшего trial'а в trials[]")
    n_trials: int = Field(..., description="Фактически выполнено trials")
    grid_size: int = Field(..., description="Размер оригинального grid'а")
    truncated: bool = Field(..., description="Применён ли max_trials truncation")
    cv_config: CVConfig
    metric: str = Field(..., description="Метрика выбора")
    trials: List[TuneTrialResult] = Field(
        default_factory=list, description="Все trials с params и метриками"
    )
    duration_ms: float = Field(..., description="Время расчёта (мс)")
    strategy: Optional[Literal["single", "expanding", "sliding"]] = None
    cohort_id: Optional[str] = Field(
        None, description="Тот же exact-fold cohort, что использует session backtest",
    )
    folds: List[TuneFoldPlan] = Field(default_factory=list)
    preprocessing: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    tuning_id: Optional[str] = Field(
        None, description="Уникальный идентификатор tuning run",
    )
    parameter_signature: Optional[str] = Field(
        None, description="SHA-256 модели и best_params",
    )
    promoted_backtest: Optional[BacktestResponse] = Field(
        None,
        description="Точный backtest лучшего trial без повторного обучения",
    )
