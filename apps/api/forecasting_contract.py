# apps/api/forecasting_contract.py
"""Контракт методов доверительных интервалов этапа Прогнозирование
(spec_forecasting2.md §4, §5.1, §5.2 + расширение Task FORECAST-1).

Единого способа посчитать интервал для всех моделей реестра не существует --
метод выбирается АВТОМАТИЧЕСКИ по model_id (spec_forecasting2.md §4). Классификация
расширена относительно версии 3 спецификации с 11 до 19 моделей: spec писалась
до production-адаптеров tree_ml (Tasks 127-130) и нейро-срезов (Tasks 138-141),
у которых интервалы уже сертифицированы на уровне реестра исполнения.

Достижимый через Model Card набор -- ровно 19 univariate level_forecast моделей:
comparison/selection валидируют objective == "level_forecast" (routers/
modeling_session.py::_migrate_modeling_artifacts), поэтому vector (var/vecm),
volatility (garch/egarch) и panel (deepar) карты в принципе не образуют --
их прогноз через Model Card невозможен и отклоняется fail-closed.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Методы интервалов (§4 + расширение) ───────────────────────────

CI_METHODS = {
    "analytic",                 # §4.1: statsmodels state-space API (по факту 3 разных API)
    "parametric_simulation",    # §4.1a: HoltWintersResults.simulate (Monte-Carlo инноваций)
    "native_adapter",           # интервалы, сертифицированные на уровне адаптера реестра
    "empirical_oof_quantile",   # §4.2: эмпирические квантили OOF-остатков бэктеста
}

FORECASTING_EMPIRICAL_MODEL_IDS = {"naive", "seasonal_naive", "drift", "mean"}
FORECASTING_ANALYTIC_MODEL_IDS = {"arima", "auto_arima", "theta"}
FORECASTING_SIMULATION_MODEL_IDS = {"ets", "ets_damped"}
# Prophet/TBATS -- нативные интервалы адаптера (прецедент §4.1); tree_ml --
# квантильные интервалы регрессии (Tasks 127-130); нейро-четвёрка -- conformal
# (Tasks 138-140) / MQLoss-квантили (Task 141).
FORECASTING_NATIVE_MODEL_IDS = {
    "prophet", "tbats",
    "random_forest", "xgboost", "lightgbm", "catboost",
    "lstm", "nbeats", "nhits", "tft",
}

FORECASTING_ELIGIBLE_MODEL_IDS = (
    FORECASTING_EMPIRICAL_MODEL_IDS
    | FORECASTING_ANALYTIC_MODEL_IDS
    | FORECASTING_SIMULATION_MODEL_IDS
    | FORECASTING_NATIVE_MODEL_IDS
)

# ── Alpha-политика (§5.2 + дисклоужер фиксированных alpha) ────────

# Нейро-адаптеры принимают alpha параметром с сертифицированным whitelist
# (Tasks 138-141, ALPHA_OPTIONS адаптеров) -- запрошенная alpha прокидывается.
NEURAL_ALPHA_MODELS = {"lstm", "nbeats", "nhits", "tft"}
NEURAL_ALPHA_WHITELIST = {0.01, 0.05, 0.10}

# Адаптеры с ФИКСИРОВАННОЙ alpha: Prophet/TBATS -- interval_width=0.8
# (Task 124/125, «для единообразия Model Card»); tree_ml -- quantile
# 0.1/0.9 (bounded scope, не тюнится). Запрошенная alpha не подменяется
# другим методом: интервал отдаётся как есть с честным предупреждением.
FIXED_ADAPTER_ALPHA: dict[str, float] = {
    "prophet": 0.20,
    "tbats": 0.20,
    "random_forest": 0.10,
    "xgboost": 0.10,
    "lightgbm": 0.10,
    "catboost": 0.10,
}

PLATFORM_DEFAULT_ALPHA = 0.05


@dataclass(frozen=True)
class AlphaResolution:
    """Результат разрешения запрошенной alpha для конкретной модели."""

    effective_alpha: float       # alpha, на которой фактически отдаётся интервал
    alpha_source: str            # "requested" | "card_default" | "platform_default" | "adapter_fixed"
    request_alpha_honored: bool
    warnings: tuple[str, ...] = ()


def interval_method_for_model(model_id: str) -> str:
    """Метод интервалов по model_id. Fail-closed на неизвестной модели."""
    if model_id in FORECASTING_EMPIRICAL_MODEL_IDS:
        return "empirical_oof_quantile"
    if model_id in FORECASTING_ANALYTIC_MODEL_IDS:
        return "analytic"
    if model_id in FORECASTING_SIMULATION_MODEL_IDS:
        return "parametric_simulation"
    if model_id in FORECASTING_NATIVE_MODEL_IDS:
        return "native_adapter"
    raise ValueError(
        f"Модель '{model_id}' недостижима через Model Card этапа Прогнозирование "
        "(объектив cohort'а не level_forecast) или не существует; фиктивный "
        "интервал запрещён"
    )


def fixed_adapter_alpha(model_id: str) -> float:
    """Фиксированная alpha адаптера. Fail-closed вне карты фиксированных."""
    if model_id not in FIXED_ADAPTER_ALPHA:
        raise ValueError(f"Модель '{model_id}' не имеет фиксированной alpha адаптера")
    return FIXED_ADAPTER_ALPHA[model_id]


def _validate_open_unit_interval(alpha: float) -> float:
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise ValueError(f"alpha должна быть числом, получено: {alpha!r}")
    value = float(alpha)
    if not 0.0 < value < 1.0:
        raise ValueError(
            f"alpha должна лежать в открытом интервале (0, 1), получено: {value}"
        )
    return value


def resolve_forecast_alpha(
    model_id: str,
    requested_alpha: float | None,
    card_params: dict | None,
) -> AlphaResolution:
    """Разрешить alpha запроса для модели (§5.2 + политика native-адаптеров).

    - empirical/analytic/parametric_simulation: запрошенная alpha любая в (0, 1);
      по умолчанию -- платформенная 0.05 (spec §5.2).
    - нейро-модели: alpha -- сертифицированная ручка адаптера с whitelist
      {0.01, 0.05, 0.10}; вне whitelist -- честный отказ, не молчаливый перенос.
    - prophet/tbats/tree_ml: alpha адаптера фиксирована; запрошенная alpha
      НЕ подменяется другим методом -- интервал отдаётся как есть с дисклоужером.
    """
    method = interval_method_for_model(model_id)

    if method == "native_adapter" and model_id in NEURAL_ALPHA_MODELS:
        card_alpha = (card_params or {}).get("alpha")
        if requested_alpha is not None:
            alpha = _validate_open_unit_interval(requested_alpha)
            source = "requested"
        elif card_alpha is not None:
            alpha = _validate_open_unit_interval(card_alpha)
            source = "card_default"
        else:
            alpha = PLATFORM_DEFAULT_ALPHA
            source = "platform_default"
        if alpha not in NEURAL_ALPHA_WHITELIST:
            allowed = ", ".join(str(value) for value in sorted(NEURAL_ALPHA_WHITELIST))
            raise ValueError(
                f"Для модели '{model_id}' допустима alpha только из набора "
                f"{{{allowed}}}; запрошено: {alpha} (сертифицированный whitelist "
                "адаптера, Tasks 138-141)"
            )
        return AlphaResolution(
            effective_alpha=alpha, alpha_source=source,
            request_alpha_honored=requested_alpha is not None,
        )

    if method == "native_adapter":
        adapter_alpha = fixed_adapter_alpha(model_id)
        warnings: list[str] = []
        if requested_alpha is not None and float(requested_alpha) != adapter_alpha:
            level = round(100 * (1 - adapter_alpha), 2)
            requested = _validate_open_unit_interval(requested_alpha)
            warnings.append(
                f"Интервал отдаётся нативным адаптером модели '{model_id}' на "
                f"фиксированном уровне {level:g}% (alpha={adapter_alpha}); "
                f"запрошенная alpha={requested} игнорируется без подмены "
                "метода интервала"
            )
        return AlphaResolution(
            effective_alpha=adapter_alpha, alpha_source="adapter_fixed",
            request_alpha_honored=False, warnings=tuple(warnings),
        )

    if requested_alpha is not None:
        return AlphaResolution(
            effective_alpha=_validate_open_unit_interval(requested_alpha),
            alpha_source="requested", request_alpha_honored=True,
        )
    return AlphaResolution(
        effective_alpha=PLATFORM_DEFAULT_ALPHA,
        alpha_source="platform_default", request_alpha_honored=True,
    )
