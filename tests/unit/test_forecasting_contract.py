# tests/unit/test_forecasting_contract.py
# TDD RED: контракт методов доверительных интервалов модуля Прогнозирование
# (spec_forecasting2.md §4 + расширение на все 19 моделей, достижимых через
# Model Card; см. запись Task FORECAST-1 в worklog5.md).
from __future__ import annotations

import pytest

from apps.api.forecasting_contract import (
    CI_METHODS,
    FIXED_ADAPTER_ALPHA,
    FORECASTING_ELIGIBLE_MODEL_IDS,
    NEURAL_ALPHA_MODELS,
    NEURAL_ALPHA_WHITELIST,
    AlphaResolution,
    fixed_adapter_alpha,
    interval_method_for_model,
    resolve_forecast_alpha,
)


# ── Классификация ci_method по моделям ────────────────────────────


def test_empirical_method_is_mandatory_for_baselines():
    # spec_forecasting2.md §4.2: baseline-модели без аналитической формы --
    # ТОЛЬКО эмпирический метод на OOF-остатках бэктеста.
    for model_id in ("naive", "seasonal_naive", "drift", "mean"):
        assert interval_method_for_model(model_id) == "empirical_oof_quantile"


def test_analytic_method_for_statsmodels_state_space_models():
    # §4.1: ARIMA/Auto-ARIMA -- get_forecast().summary_frame(alpha);
    # Theta -- prediction_intervals(steps, theta, alpha) (другой API, §10.3).
    for model_id in ("arima", "auto_arima", "theta"):
        assert interval_method_for_model(model_id) == "analytic"


def test_parametric_simulation_for_ets_family():
    # §4.1a: классический HoltWintersResults не имеет get_forecast/conf_int;
    # интервал -- параметрическая симуляция simulate(nsteps, repetitions).
    for model_id in ("ets", "ets_damped"):
        assert interval_method_for_model(model_id) == "parametric_simulation"


def test_native_adapter_for_models_with_certified_registry_intervals():
    # Расширение §4.1 (Prophet/TBATS) на адаптеры, чьи интервалы уже
    # сертифицированы реестром (tree_ml: quantile 0.1/0.9; neural: conformal
    # /MQLoss). Реестр -- единственная точка исполнения, интервалы
    # переиспользуются как есть.
    for model_id in (
        "prophet", "tbats",
        "random_forest", "xgboost", "lightgbm", "catboost",
        "lstm", "nbeats", "nhits", "tft",
    ):
        assert interval_method_for_model(model_id) == "native_adapter"


def test_eligible_set_is_exactly_nineteen_card_reachable_models():
    # Model Card достижим только из comparison ranking уровня
    # level_forecast (objective-изоляция cohort'ов): vector (var/vecm),
    # volatility (garch/egarch) и panel (deepar) модели в comparison
    # не участвуют => их прогноз через Model Card невозможен (честный 422).
    assert len(FORECASTING_ELIGIBLE_MODEL_IDS) == 19
    for model_id in ("var", "vecm", "garch", "egarch", "deepar"):
        assert model_id not in FORECASTING_ELIGIBLE_MODEL_IDS
    assert set(FORECASTING_ELIGIBLE_MODEL_IDS) == (
        {"naive", "seasonal_naive", "drift", "mean"}
        | {"arima", "auto_arima", "theta"}
        | {"ets", "ets_damped"}
        | {"prophet", "tbats"}
        | {"random_forest", "xgboost", "lightgbm", "catboost"}
        | {"lstm", "nbeats", "nhits", "tft"}
    )


def test_ci_methods_registry_is_exact():
    assert CI_METHODS == {
        "analytic",
        "parametric_simulation",
        "native_adapter",
        "empirical_oof_quantile",
    }


def test_unknown_or_non_eligible_model_fails_closed():
    for model_id in ("var", "garch", "deepar", "unknown_model", ""):
        with pytest.raises(ValueError):
            interval_method_for_model(model_id)


# ── Alpha-разрешение ──────────────────────────────────────────────


def test_neural_alpha_whitelist_is_the_certified_adapter_set():
    # Alpha-ручка нейро-адаптеров сертифицирована с whitelist {0.01, 0.05, 0.10}
    # (Tasks 138-141); прогноз-модуль обязан наследовать ТОТ ЖЕ whitelist.
    assert NEURAL_ALPHA_WHITELIST == {0.01, 0.05, 0.10}
    assert NEURAL_ALPHA_MODELS == {"lstm", "nbeats", "nhits", "tft"}


def test_fixed_adapter_alpha_matches_certified_adapter_defaults():
    # Prophet/TBATS: нативный interval_width=0.8 (прецедент Task 124/125);
    # tree_ml: quantile-интервалы 0.1/0.9 (Tasks 127-130).
    assert fixed_adapter_alpha("prophet") == 0.20
    assert fixed_adapter_alpha("tbats") == 0.20
    for model_id in ("random_forest", "xgboost", "lightgbm", "catboost"):
        assert fixed_adapter_alpha(model_id) == 0.10
    assert set(FIXED_ADAPTER_ALPHA) == {
        "prophet", "tbats", "random_forest", "xgboost", "lightgbm", "catboost",
    }


def test_resolve_alpha_requested_honored_for_empirical_analytic_simulation():
    for model_id in ("naive", "arima", "theta", "ets"):
        resolution = resolve_forecast_alpha(model_id, 0.10, {})
        assert isinstance(resolution, AlphaResolution)
        assert resolution.effective_alpha == 0.10
        assert resolution.alpha_source == "requested"
        assert resolution.request_alpha_honored is True
        assert resolution.warnings == ()


def test_resolve_alpha_default_is_005_when_request_omits_it():
    # spec_forecasting2.md §5.2: alpha -- параметр запроса, по умолчанию 0.05.
    resolution = resolve_forecast_alpha("naive", None, {})
    assert resolution.effective_alpha == 0.05
    assert resolution.alpha_source == "platform_default"
    assert resolution.request_alpha_honored is True


def test_resolve_alpha_neural_uses_card_params_then_request_override():
    card_params = {"alpha": 0.05, "hidden_size": 32}
    base = resolve_forecast_alpha("lstm", None, card_params)
    assert base.effective_alpha == 0.05
    assert base.alpha_source == "card_default"

    overridden = resolve_forecast_alpha("lstm", 0.01, card_params)
    assert overridden.effective_alpha == 0.01
    assert overridden.alpha_source == "requested"
    assert overridden.request_alpha_honored is True


def test_resolve_alpha_neural_rejects_values_outside_whitelist():
    with pytest.raises(ValueError, match="0.02"):
        resolve_forecast_alpha("tft", 0.02, {"alpha": 0.05})


def test_resolve_alpha_fixed_adapter_ignores_requested_with_disclosure():
    resolution = resolve_forecast_alpha("prophet", 0.05, {})
    assert resolution.effective_alpha == 0.20
    assert resolution.alpha_source == "adapter_fixed"
    assert resolution.request_alpha_honored is False
    assert any("80%" in warning for warning in resolution.warnings)
    # Запрошенная alpha совпадает с фиксированной -- без предупреждения.
    same = resolve_forecast_alpha("prophet", 0.20, {})
    assert same.warnings == ()


def test_resolve_alpha_rejects_alpha_outside_open_unit_interval():
    for model_id in ("naive", "arima"):
        for alpha in (0.0, 1.0, -0.05, 1.5):
            with pytest.raises(ValueError):
                resolve_forecast_alpha(model_id, alpha, {})
