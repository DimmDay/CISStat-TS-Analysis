"""
Загрузчик формальной спецификации модуля «Моделирование».
Парсинг rules/modeling.yaml в Pydantic v2 модели с движком применимости.

Версия: 1.0
Дата:   2026-08-07
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from pathlib import Path
import yaml


# ═══════════════════════════════════════════════════════════
# 1. СЕМЕЙСТВА И МОДЕЛИ
# ═══════════════════════════════════════════════════════════

class FamilyModel(BaseModel):
    """Модель внутри семейства."""
    id: str
    name: str
    description: str
    min_observations: int = Field(..., ge=1)
    supports_exogenous: bool = False
    supports_seasonality: Optional[bool] = None
    supports_prediction_intervals: bool = False
    requires_seasonality: Optional[bool] = None
    requires_stationarity: Optional[str] = None   # "required" / "optional"
    requires_multiple_series: Optional[bool] = None
    requires_feature_engineering: Optional[bool] = None
    requires_gpu: Optional[bool] = None
    requires_regularity: Optional[str] = None     # "required" / "optional"
    domain: Optional[str] = None                  # "financial" etc.
    min_series: Optional[int] = None
    libraries: List[str] = Field(default_factory=list)
    training_time: str = "seconds"

    # ── Phase 1-A: пространство параметров для тюнинга ──
    #
    # Опциональный dict: имя_параметра → список кандидат-значений.
    # Декартово произведение всех списков даёт grid для POST /v1/models/tune.
    #
    # None (по умолчанию) = модель не поддерживает тюнинг (baseline-модели
    # naive/drift/mean, или модели без публичных гиперпараметров).
    #
    # Значения в списках могут быть str/int/float/bool/None. None — валидное
    # значение (например, seasonal=None отключает сезонность в ETS).
    #
    # Контракт для дальнейших Phase 1-подзадач:
    #   - POST /v1/models/tune читает param_space через get_model(model_id)
    #   - max_trials защита: product(len(v) for v in param_space.values())
    #     не должен превышать MAX_TRIALS (64). Если превышает — grid
    #     обрезается random-сэмплированием.
    param_space: Optional[Dict[str, List[Any]]] = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError("ID должен содержать только буквы, цифры и _")
        return v.lower()


class Family(BaseModel):
    """Расширяемое семейство моделей."""
    id: str
    name: str
    priority: int = Field(..., ge=1)
    required: bool = False
    description: str = ""
    models: List[FamilyModel] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError("ID семейства должен содержать только буквы, цифры и _")
        return v.lower()


# ═══════════════════════════════════════════════════════════
# 2. УРОВНИ ПРИМЕНИМОСТИ
# ═══════════════════════════════════════════════════════════

class ApplicabilityLevel(BaseModel):
    """Уровень применимости модели."""
    id: str
    name: str
    color: str
    rank: int = Field(..., ge=1)
    description: str = ""
    ui_badge: str = "default"


# ═══════════════════════════════════════════════════════════
# 3. ДВИЖОК ПРИМЕНИМОСТИ — правила
# ═══════════════════════════════════════════════════════════

class ApplicabilityRule(BaseModel):
    """Правило определения уровня применимости."""
    id: str
    description: str = ""
    condition: str
    result: str   # RECOMMENDED / CONDITIONALLY_APPLICABLE / NOT_RECOMMENDED / NOT_APPLICABLE
    message: str = ""


class ApplicabilityEngine(BaseModel):
    """Движок применимости: 4 секции правил (по приоритету)."""
    forbidden: List[ApplicabilityRule] = Field(default_factory=list)
    discouraged: List[ApplicabilityRule] = Field(default_factory=list)
    conditional: List[ApplicabilityRule] = Field(default_factory=list)
    preferred: List[ApplicabilityRule] = Field(default_factory=list)

    def total_rules_count(self) -> int:
        return (
            len(self.forbidden) + len(self.discouraged) +
            len(self.conditional) + len(self.preferred)
        )


# ═══════════════════════════════════════════════════════════
# 4. ПАЙПЛАЙН
# ═══════════════════════════════════════════════════════════

class PipelineStage(BaseModel):
    """Стадия пайплайна моделирования."""
    id: str
    name: str
    order: int = Field(..., ge=1)
    description: str = ""
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    required: Optional[bool] = None
    failure_action: Optional[str] = None


class Pipeline(BaseModel):
    """Пайплайн моделирования из 11 стадий."""
    id: str = "modeling_pipeline"
    version: str = "1.0"
    stages: List[PipelineStage] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 5. МЕТРИКИ
# ═══════════════════════════════════════════════════════════

class MetricDef(BaseModel):
    """Определение метрики."""
    id: str
    name: str
    formula: str = ""
    scale_dependent: Optional[bool] = None
    robust_to_outliers: Optional[bool] = None
    direction: str = "minimize"   # minimize / maximize / target
    weight_in_ranking: float = 0.0
    use_in_ranking: Optional[bool] = None
    undefined_when: Optional[str] = None
    caveat: str = ""
    interpretation: str = ""
    target: Optional[float] = None
    description: str = ""


class PIMetricDef(BaseModel):
    """Метрика доверительного интервала."""
    id: str
    name: str
    formula: str = ""
    direction: str = "minimize"
    target: Optional[float] = None
    description: str = ""
    caveat: str = ""


class RankingFormula(BaseModel):
    """Формула ранжирования моделей."""
    description: str = ""
    weights: Dict[str, float] = Field(default_factory=dict)
    normalization: str = "min_max"
    baseline_filter_threshold: float = 1.05


class MetricsConfig(BaseModel):
    """Конфигурация метрик."""
    primary: List[MetricDef] = Field(default_factory=list)
    secondary: List[MetricDef] = Field(default_factory=list)
    prediction_interval: List[PIMetricDef] = Field(default_factory=list)
    ranking_formula: RankingFormula = Field(default_factory=RankingFormula)


# ═══════════════════════════════════════════════════════════
# 6. PREDICTION INTERVALS
# ═══════════════════════════════════════════════════════════

class PIMethodFamily(BaseModel):
    """Метод генерации PI для семейства моделей."""
    method: str
    description: str = ""


class PredictionIntervalsConfig(BaseModel):
    """Конфигурация доверительных интервалов прогноза."""
    description: str = ""
    default_confidence_level: float = 0.95
    available_levels: List[float] = Field(default_factory=lambda: [0.80, 0.90, 0.95, 0.99])
    methods_by_family: Dict[str, PIMethodFamily] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# 7. MODEL CARD
# ═══════════════════════════════════════════════════════════

class ModelCardField(BaseModel):
    """Поле шаблона Model Card."""
    path: str
    type: str
    description: str = ""
    values: Optional[List[str]] = None


class ModelCardTemplate(BaseModel):
    """Шаблон Model Card."""
    required_fields: List[ModelCardField] = Field(default_factory=list)
    optional_fields: List[ModelCardField] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 8. ЖИЗНЕННЫЕ ЦИКЛЫ
# ═══════════════════════════════════════════════════════════

class LifecyclePhase(BaseModel):
    """Фаза жизненного цикла (моделирование или прогнозирование)."""
    description: str = ""
    trigger: Optional[str] = None
    frequency: Optional[str] = None
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    stages: Optional[str] = None
    monitoring: Optional[List[str]] = None


class LifecycleSeparation(BaseModel):
    """Разделение жизненных циклов: моделирование ≠ прогнозирование."""
    modeling: LifecyclePhase
    forecasting: LifecyclePhase


# ═══════════════════════════════════════════════════════════
# 9. АНСАМБЛИ
# ═══════════════════════════════════════════════════════════

class EnsembleStrategy(BaseModel):
    """Стратегия ансамблирования."""
    id: str
    name: str
    formula: str = ""
    applicability: str = ""
    weights: Optional[str] = None
    meta_learner: Optional[str] = None
    description: str = ""


class AutoEnsembleTrigger(BaseModel):
    """Условия автоматического предложения ансамбля."""
    description: str = ""
    conditions: Dict[str, Any] = Field(default_factory=dict)
    min_models_with_mase_below_1: int = 2
    max_score_gap: float = 0.05
    max_error_correlation: float = 0.8


class EnsembleConfig(BaseModel):
    """Конфигурация ансамблирования."""
    description: str = ""
    strategies: List[EnsembleStrategy] = Field(default_factory=list)
    auto_ensemble_trigger: Optional[AutoEnsembleTrigger] = None


# ═══════════════════════════════════════════════════════════
# 10. ПРЕДОБРАБОТКА
# ═══════════════════════════════════════════════════════════

class PreprocessingRule(BaseModel):
    """Правило автоматической предобработки перед моделированием."""
    trigger: str
    action: str
    description: str = ""
    code: Optional[str] = None
    fallback: Optional[str] = None
    note: Optional[str] = None
    method: Optional[str] = None
    features: Optional[List[str]] = None


# ═══════════════════════════════════════════════════════════
# 11. UI КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════

class ModelCardDisplay(BaseModel):
    show_applicability_badge: bool = True
    show_mase_vs_baseline: bool = True
    show_prediction_intervals: bool = True
    show_diagnostics_summary: bool = True
    show_feature_importance: bool = True


class ComparisonTable(BaseModel):
    primary_sort: str = "weighted_score"
    columns: List[str] = Field(default_factory=list)


class UIFilter(BaseModel):
    id: str
    label: str
    options: List[str] = Field(default_factory=list)


class ForecastingPanel(BaseModel):
    default_horizon: Optional[int] = None
    max_horizon_warning: float = 0.5
    confidence_levels: List[float] = Field(default_factory=lambda: [0.80, 0.90, 0.95, 0.99])
    default_confidence: float = 0.95


class UIConfig(BaseModel):
    """Конфигурация пользовательского интерфейса модуля."""
    model_card_display: ModelCardDisplay = Field(default_factory=ModelCardDisplay)
    comparison_table: ComparisonTable = Field(default_factory=ComparisonTable)
    filters: List[UIFilter] = Field(default_factory=list)
    forecasting_panel: ForecastingPanel = Field(default_factory=ForecastingPanel)


# ═══════════════════════════════════════════════════════════
# 12. ПРОФИЛЬ ДАННЫХ (вход движка применимости)
# ═══════════════════════════════════════════════════════════

class DataProfile(BaseModel):
    """Профиль данных — вход движка применимости."""
    n_observations: int = Field(..., ge=1)
    n_series: int = Field(1, ge=1)
    n_exogenous: int = Field(0, ge=0)
    is_regular: bool = True
    frequency: str = "M"
    has_seasonality: bool = False
    seasonal_periods: List[int] = Field(default_factory=list)
    is_stationary_or_diffable: bool = True
    is_cointegrated: bool = False
    has_negative_values: bool = False
    has_volatility_clustering: bool = False
    domain: str = "other"
    missing_ratio: float = Field(0.0, ge=0.0, le=1.0)
    outlier_ratio: float = Field(0.0, ge=0.0, le=1.0)
    # Дополнительные контекстные флаги
    has_holidays: bool = False
    gpu_available: bool = False
    feature_engineering_applied: bool = False


# ═══════════════════════════════════════════════════════════
# 13. РЕЗУЛЬТАТ ОЦЕНКИ ПРИМЕНИМОСТИ
# ═══════════════════════════════════════════════════════════

class ApplicabilityResult(BaseModel):
    """Результат оценки применимости модели."""
    model_id: str
    model_name: str
    family_id: str
    level: str          # RECOMMENDED / CONDITIONALLY_APPLICABLE / NOT_RECOMMENDED / NOT_APPLICABLE
    rule_id: Optional[str] = None
    message: str = ""
    rank: int = 1       # ранг уровня (1=лучший)


# ═══════════════════════════════════════════════════════════
# 14. МЕТАДАННЫЕ
# ═══════════════════════════════════════════════════════════

class Metadata(BaseModel):
    """Метаданные спецификации."""
    version: str = "1.0.0-draft"
    last_updated: str = ""
    author: str = ""
    description: str = ""


# ═══════════════════════════════════════════════════════════
# 15. КОРНЕВАЯ МОДЕЛЬ — ModelingSpec
# ═══════════════════════════════════════════════════════════

class ModelingSpec(BaseModel):
    """
    Корневая Pydantic-модель спецификации модуля «Моделирование».

    Загружается из rules/modeling.yaml через ModelingSpec.from_yaml().
    Содержит все секции спецификации и движок применимости.
    """
    metadata: Metadata
    families: List[Family] = Field(default_factory=list)
    applicability_levels: List[ApplicabilityLevel] = Field(default_factory=list)
    applicability_engine: ApplicabilityEngine = Field(default_factory=ApplicabilityEngine)
    pipeline: Pipeline = Field(default_factory=Pipeline)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    prediction_intervals: PredictionIntervalsConfig = Field(default_factory=PredictionIntervalsConfig)
    model_card_template: ModelCardTemplate = Field(default_factory=ModelCardTemplate)
    lifecycle_separation: LifecycleSeparation
    ensemble: EnsembleConfig = Field(default_factory=EnsembleConfig)
    preprocessing_rules: List[PreprocessingRule] = Field(default_factory=list)
    ui_config: UIConfig = Field(default_factory=UIConfig)

    # ── ЗАГРУЗКА ───────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str) -> "ModelingSpec":
        """Загрузка спецификации из YAML-файла."""
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"YAML-файл не найден: {path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"YAML-файл пуст: {path}")

        return cls(**data)

    def to_yaml(self, path: str) -> None:
        """Сохранение спецификации в YAML-файл."""
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                self.model_dump(),
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )

    # ── ДОСТУП К СЕМЕЙСТВАМ И МОДЕЛЯМ ─────────────────────

    def get_family(self, family_id: str) -> Optional[Family]:
        """Получить семейство по ID."""
        for family in self.families:
            if family.id == family_id:
                return family
        return None

    def get_model(self, model_id: str) -> Optional[FamilyModel]:
        """Получить модель по ID (поиск по всем семействам)."""
        for family in self.families:
            for model in family.models:
                if model.id == model_id:
                    return model
        return None

    def get_family_for_model(self, model_id: str) -> Optional[Family]:
        """Получить семейство, содержащее модель."""
        for family in self.families:
            for model in family.models:
                if model.id == model_id:
                    return family
        return None

    def total_model_count(self) -> int:
        """Общее число моделей во всех семействах."""
        return sum(len(f.models) for f in self.families)

    def get_baselines(self) -> List[FamilyModel]:
        """Получить все baseline-модели."""
        baselines = self.get_family("baselines")
        if baselines:
            return baselines.models
        return []

    # ── УРОВНИ ПРИМЕНИМОСТИ ────────────────────────────────

    def get_applicability_level(self, level_id: str) -> Optional[ApplicabilityLevel]:
        """Получить уровень применимости по ID."""
        for level in self.applicability_levels:
            if level.id == level_id:
                return level
        return None

    # ── ДВИЖОК ПРИМЕНИМОСТИ ────────────────────────────────

    def resolve_applicability(
        self,
        model_id: str,
        profile: DataProfile,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> ApplicabilityResult:
        """
        Определить уровень применимости модели для профиля данных.

        Правила проверяются в порядке приоритета:
          1. forbidden → NOT_APPLICABLE
          2. discouraged → NOT_RECOMMENDED
          3. conditional → CONDITIONALLY_APPLICABLE
          4. preferred → RECOMMENDED
          5. default → RECOMMENDED (если ни одно правило не сработало)

        Args:
            model_id: идентификатор модели
            profile: профиль данных (DataProfile)
            constraints: опциональные ограничения (gpu, time, и т.д.)

        Returns:
            ApplicabilityResult с уровнем, правилом и сообщением
        """
        model = self.get_model(model_id)
        family = self.get_family_for_model(model_id)

        if model is None or family is None:
            return ApplicabilityResult(
                model_id=model_id,
                model_name=model_id,
                family_id="unknown",
                level="NOT_APPLICABLE",
                rule_id=None,
                message=f"Модель {model_id} не найдена в спецификации",
                rank=4,
            )

        # Объединяем constraints с profile для удобной передачи в правила
        ctx = self._build_context(model, family, profile, constraints or {})

        # Проверяем правила в порядке приоритета
        for section, result_level in [
            ("forbidden", "NOT_APPLICABLE"),
            ("discouraged", "NOT_RECOMMENDED"),
            ("conditional", "CONDITIONALLY_APPLICABLE"),
            ("preferred", "RECOMMENDED"),
        ]:
            rules = getattr(self.applicability_engine, section, [])
            for rule in rules:
                if self._evaluate_rule(rule, ctx):
                    level_obj = self.get_applicability_level(result_level)
                    return ApplicabilityResult(
                        model_id=model_id,
                        model_name=model.name,
                        family_id=family.id,
                        level=result_level,
                        rule_id=rule.id,
                        message=rule.message,
                        rank=level_obj.rank if level_obj else 4,
                    )

        # Ни одно правило не сработало → RECOMMENDED по умолчанию
        return ApplicabilityResult(
            model_id=model_id,
            model_name=model.name,
            family_id=family.id,
            level="RECOMMENDED",
            rule_id=None,
            message="",
            rank=1,
        )

    def resolve_all_applicability(
        self,
        profile: DataProfile,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, ApplicabilityResult]:
        """
        Оценить применимость всех моделей.

        Returns:
            Словарь {model_id: ApplicabilityResult}
        """
        results = {}
        for family in self.families:
            for model in family.models:
                results[model.id] = self.resolve_applicability(
                    model.id, profile, constraints
                )
        return results

    def get_candidate_pool(
        self,
        profile: DataProfile,
        constraints: Optional[Dict[str, Any]] = None,
        min_level: str = "CONDITIONALLY_APPLICABLE",
    ) -> List[ApplicabilityResult]:
        """
        Сформировать пул кандидатов для моделирования.

        Исключает NOT_APPLICABLE модели. Baselines включаются всегда.
        Сортируются по уровню применимости (RECOMMENDED первыми).

        Args:
            profile: профиль данных
            constraints: опциональные ограничения
            min_level: минимальный уровень применимости
                       (по умолчанию — включать CONDITIONALLY_APPLICABLE и выше)

        Returns:
            Список ApplicabilityResult, отсортированный по rank
        """
        all_results = self.resolve_all_applicability(profile, constraints)

        # Ранги уровней для фильтрации
        level_ranks = {l.id: l.rank for l in self.applicability_levels}
        min_rank = level_ranks.get(min_level, 2)

        # Baseline-модели всегда включаются (если не NOT_APPLICABLE)
        baseline_ids = {m.id for m in self.get_baselines()}

        candidates = []
        for model_id, result in all_results.items():
            # NOT_APPLICABLE — всегда исключаем
            if result.level == "NOT_APPLICABLE":
                continue

            # Baseline — всегда включаем
            if model_id in baseline_ids:
                candidates.append(result)
                continue

            # Остальные — по минимальному уровню
            if level_ranks.get(result.level, 4) <= min_rank:
                candidates.append(result)

        # Сортировка: RECOMMENDED первыми
        candidates.sort(key=lambda r: r.rank)
        return candidates

    # ── ВНУТРЕННИЕ МЕТОДЫ ДВИЖКА ПРИМЕНИМОСТИ ──────────────

    def _build_context(
        self,
        model: FamilyModel,
        family: Family,
        profile: DataProfile,
        constraints: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Построить контекст для оценки правил."""
        return {
            # Модель
            "model_id": model.id,
            "model_name": model.name,
            "model_family": family.id,
            "model.min_observations": model.min_observations,
            "model.supports_exogenous": model.supports_exogenous,
            "model.domain": model.domain,
            "model.min_series": model.min_series,
            "model.requires_gpu": model.requires_gpu,
            "model.requires_multiple_series": model.requires_multiple_series,
            "model.requires_feature_engineering": model.requires_feature_engineering,
            "model.requires_regularity": model.requires_regularity,
            "model.requires_stationarity": model.requires_stationarity,
            # Данные
            "n_observations": profile.n_observations,
            "n_series": profile.n_series,
            "n_exogenous": profile.n_exogenous,
            "data.is_regular": profile.is_regular,
            "data.domain": profile.domain,
            "data.has_seasonality": profile.has_seasonality,
            "data.is_stationary_or_diffable": profile.is_stationary_or_diffable,
            "data.is_cointegrated": profile.is_cointegrated,
            "data.has_negative_values": profile.has_negative_values,
            "data.has_volatility_clustering": profile.has_volatility_clustering,
            "data.has_holidays": profile.has_holidays,
            "data.has_exogenous": profile.n_exogenous > 0,
            "data.is_stationary": profile.is_stationary_or_diffable,
            # Ограничения
            "gpu_available": profile.gpu_available,
            "feature_engineering_applied": profile.feature_engineering_applied,
            # Удобные сокращения
            "model.id": model.id,
            "model.family": family.id,
        }

    def _evaluate_rule(self, rule: ApplicabilityRule, ctx: Dict[str, Any]) -> bool:
        """
        Оценить правило применимости в контексте.

        Реализует мини-DSL для condition-строк из YAML:
          - Сравнения: n_observations < 300, n_series == 1
          - AND/OR: condition1 AND condition2
          - Равенства строк: model.domain == 'financial'
          - Доступ к атрибутам через точку: model.family == 'arima'

        Для сложных правил, не покрываемых DSL, используется fallback
        к предопределённым handlers по rule.id.
        """
        # Предопределённые handlers для всех правил спецификации
        handlers = {
            # ── Forbidden (NOT_APPLICABLE) ────────────────
            "F01": lambda: ctx["n_series"] == 1 and (ctx.get("model.requires_multiple_series") or ctx.get("model.min_series", 0) is not None and (ctx.get("model.min_series") or 0) > 1),
            "F02": lambda: ctx.get("model.domain") == "financial" and ctx.get("data.domain") != "financial",
            "F03": lambda: ctx.get("model.supports_exogenous") is False and ctx["n_exogenous"] > 0,
            "F04": lambda: ctx["n_observations"] < ctx["model.min_observations"],
            "F05": lambda: ctx.get("model_id") == "deepar" and ctx["n_series"] < (ctx.get("model.min_series") or 5),

            # ── Discouraged (NOT_RECOMMENDED) ─────────────
            "D01": lambda: ctx.get("model.family") == "arima" and ctx["n_observations"] > 5000,
            "D02": lambda: ctx.get("model.family") == "neural" and ctx["n_observations"] < 300,
            "D03": lambda: ctx.get("model.family") == "tree_ml" and not ctx.get("feature_engineering_applied", False),
            "D04": lambda: ctx.get("model.family") == "volatility" and ctx.get("data.domain") != "financial",
            "D05": lambda: ctx.get("model_id") == "tbats" and ctx["n_observations"] < 200,
            "D06": lambda: ctx.get("model.requires_gpu") is True and not ctx.get("gpu_available", False),

            # ── Conditional (CONDITIONALLY_APPLICABLE) ────
            "C01": lambda: ctx.get("model.family") == "arima" and 30 <= ctx["n_observations"] < 50,
            "C02": lambda: (
                ctx.get("model.family") == "exponential_smoothing"
                and ctx.get("data.has_negative_values", False)
            ),
            "C03": lambda: ctx.get("model_id") == "var" and ctx["n_series"] > 5,
            "C04": lambda: ctx.get("model.family") == "neural" and 300 <= ctx["n_observations"] < 500,
            "C05": lambda: ctx.get("model_id") == "prophet" and ctx.get("forecast_horizon", 12) <= 3,

            # ── Preferred (RECOMMENDED) ───────────────────
            "P01": lambda: (
                ctx.get("model.family") == "exponential_smoothing"
                and ctx["n_observations"] < 100
                and ctx.get("data.has_seasonality", False)
            ),
            "P02": lambda: (
                ctx.get("model.family") == "arima"
                and 50 <= ctx["n_observations"] <= 1000
                and ctx.get("data.is_stationary_or_diffable", False)
            ),
            "P03": lambda: (
                ctx.get("model_id") == "prophet"
                and not ctx.get("data.is_regular", True)
                and ctx.get("data.has_holidays", False)
            ),
            "P04": lambda: (
                ctx.get("model.family") == "volatility"
                and ctx.get("data.domain") == "financial"
                and ctx.get("data.has_volatility_clustering", False)
            ),
            "P05": lambda: (
                ctx.get("model_id") == "vecm"
                and ctx.get("data.is_cointegrated", False)
            ),
            "P06": lambda: (
                ctx.get("model.family") == "tree_ml"
                and ctx["n_observations"] >= 200
                and ctx["n_exogenous"] >= 1
                and ctx.get("feature_engineering_applied", False)
            ),
            "P07": lambda: (
                ctx.get("model_id") == "tft"
                and ctx["n_series"] >= 2
                and ctx["n_exogenous"] >= 1
                and ctx["n_observations"] >= 500
            ),
        }

        handler = handlers.get(rule.id)
        if handler:
            try:
                return bool(handler())
            except Exception:
                return False

        # Fallback: простая оценка condition через safe eval
        return self._eval_condition_fallback(rule.condition, ctx)

    def _eval_condition_fallback(self, condition: str, ctx: Dict[str, Any]) -> bool:
        """
        Fallback-оценка condition-строки.

        Поддерживает простые сравнения вида:
          - n_observations < 300
          - model.family == 'arima' AND n_observations > 5000
        """
        try:
            # Подставляем переменные из контекста
            expr = condition
            for key, value in ctx.items():
                placeholder = key
                if isinstance(value, str):
                    expr = expr.replace(placeholder, repr(value))
                elif isinstance(value, bool):
                    expr = expr.replace(placeholder, str(value))
                elif value is None:
                    expr = expr.replace(placeholder, "None")
                else:
                    expr = expr.replace(placeholder, str(value))

            # Заменяем AND/OR на Python-операторы
            expr = expr.replace(" AND ", " and ")
            expr = expr.replace(" OR ", " or ")

            # Safe eval — только сравнения и логические операции
            allowed_chars = set("0123456789.+-*/()<>=!&|abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_'\" ")
            if not all(c in allowed_chars for c in expr):
                return False

            result = eval(expr)  # noqa: S307 — safe по построению
            return bool(result)
        except Exception:
            return False

    # ── СТАТИСТИКА И ЦЕЛОСТНОСТЬ ───────────────────────────

    def get_statistics(self) -> Dict[str, Any]:
        """Статистика по спецификации."""
        return {
            "version": self.metadata.version,
            "total_families": len(self.families),
            "total_models": self.total_model_count(),
            "applicability_rules": self.applicability_engine.total_rules_count(),
            "pipeline_stages": len(self.pipeline.stages),
            "primary_metrics": len(self.metrics.primary),
            "ensemble_strategies": len(self.ensemble.strategies),
        }

    def validate_integrity(self) -> List[str]:
        """Проверка целостности спецификации."""
        issues = []

        # Нет дубликатов model_id
        all_ids = []
        for family in self.families:
            for model in family.models:
                all_ids.append(model.id)
        duplicates = [x for x in all_ids if all_ids.count(x) > 1]
        if duplicates:
            issues.append(f"Дубликаты model_id: {set(duplicates)}")

        # Baselines обязателен
        baselines = self.get_family("baselines")
        if baselines is None:
            issues.append("Семейство baselines отсутствует")
        elif not baselines.required:
            issues.append("Семейство baselines должно быть required=true")

        # 4 уровня применимости
        expected_levels = {"RECOMMENDED", "CONDITIONALLY_APPLICABLE",
                          "NOT_RECOMMENDED", "NOT_APPLICABLE"}
        actual_levels = {l.id for l in self.applicability_levels}
        if actual_levels != expected_levels:
            issues.append(f"Уровни применимости: ожидается {expected_levels}, найдено {actual_levels}")

        # Веса метрик
        total_weight = sum(m.weight_in_ranking for m in self.metrics.primary)
        if abs(total_weight - 1.0) > 0.01:
            issues.append(f"Сумма весов primary-метрик = {total_weight:.3f}, ожидается 1.0")

        return issues

    def __repr__(self) -> str:
        stats = self.get_statistics()
        return (
            f"ModelingSpec(v{stats['version']}, "
            f"families={stats['total_families']}, "
            f"models={stats['total_models']}, "
            f"rules={stats['applicability_rules']})"
        )
