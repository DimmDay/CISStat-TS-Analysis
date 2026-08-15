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
    seasonality: Optional[Dict[str, Any]] = None
    hurst: Optional[Dict[str, Any]] = None
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
    skewness: float
    kurtosis: float
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


# ── Валидация (10 проверок вкладки «Валидация», validation/engine.py::_run_all_checks) ──

class ValidationCheckItem(BaseModel):
    label: str = Field(..., description="Колонка/правило/группа, к которой относится нарушение")
    count: int = Field(..., description="Число нарушений по этой строке детализации")


class ValidationCheckResult(BaseModel):
    """Один из 10 пунктов CHECKS (TsAnalysisValidation.tsx). status --
    'done' (0 нарушений) | 'warning' (>0) | 'pending' (проверка неприменима:
    нет нужной колонки/справочника для этого датасета -- см. StatusIcon.tsx,
    набор значений НЕ менять без синхронизации с фронтом)."""
    status: str = Field(..., description="'done' | 'warning' | 'pending'")
    count: Optional[int] = Field(None, description="Суммарное число нарушений; None при status='pending'")
    items: List[ValidationCheckItem] = Field(default_factory=list, description="Детализация для графика")
    error: Optional[str] = Field(None, description="Текст исключения, если sub-check упал (см. _safe в engine.py)")


class DatasetValidateResponse(BaseModel):
    """Ответ GET /dataset/validate -- реальная валидация session.dataframe
    по всем 10 проверкам. rules_source сообщает фронту, откуда взяты
    правила: 'auto' (auto_generate_rules по именам колонок, без явного
    шаблона) -- до появления UI выбора шаблона (см. RulesManagementPanel,
    пока не подключена к сессии)."""
    is_valid: bool
    rules_source: str = Field("auto", description="'auto' -- rules сгенерированы автоматически по колонкам")
    total_rows: int
    total_columns: int
    checks: Dict[str, ValidationCheckResult]


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
    updated_at: Optional[str] = None


# ── Target column (Phase 0.5) ──

class TargetColumnRequest(BaseModel):
    """Запрос: установить выбранную прогнозируемую колонку."""
    column: str = Field(..., description="Имя колонки в загруженном датасете")


class TargetColumnResponse(BaseModel):
    """Ответ: текущая target_column + список доступных числовых колонок.

    available_columns нужен UI для отрисовки селектора. Содержит ТОЛЬКО
    числовые колонки -- target для TS-прогноза должен быть числовым.
    """
    target_column: Optional[str] = None
    available_columns: List[str] = Field(
        default_factory=list,
        description="Числовые колонки, доступные для выбора как target",
    )
    has_dataset: bool = Field(
        False, description="Загружен ли датасет (если нет -- выбор target невозможен)"
    )


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
    formats: Optional[Dict[str, Any]] = None
    referential: Optional[List[Dict[str, Any]]] = None
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


class CandidatesResponse(BaseModel):
    """Ответ: пул кандидатов для моделирования."""
    candidates: List[ModelCandidate]
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
    mape: float = Field(..., description="Mean Absolute Percentage Error (%)")
    mase: float = Field(..., description="Mean Absolute Scaled Error")
    weighted_score: float = Field(
        ..., description="Взвешенный итог: 0.35*MAE_n + 0.25*RMSE_n + 0.20*MAPE_n + 0.20*MASE_n"
    )


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