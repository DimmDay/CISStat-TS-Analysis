from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from apps.api.eda_model_matrix import build_eda_model_matrix
from src.catalog.modeling_spec_loader import DataProfile, ModelingSpec


def _seasonal_frame(size: int = 240) -> pd.DataFrame:
    index = np.arange(size, dtype=float)
    return pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=size, freq="MS"),
        "Price": 100 + 0.05 * index + 8 * np.sin(2 * np.pi * index / 12),
        "Volume": 500 + 2 * index,
    })


def _by_id(result: dict, model_id: str) -> dict:
    return next(item for item in result["models"] if item["model_id"] == model_id)


def test_matrix_reuses_all_spec_models_and_separates_compatibility_from_readiness():
    result = build_eda_model_matrix(_seasonal_frame(), "Price", task="forecast", horizon=12)

    assert result["applicable"] is True
    assert result["spec_version"]
    assert len(result["models"]) == 24
    assert len(result["families"]) == 8

    naive = _by_id(result, "naive")
    assert naive["compatibility"] == "candidate"
    assert naive["platform_status"] == "ready"

    # Task 130: catboost стал production-моделью -- все четыре модели
    # tree_ml в production.  Разделение осей сохраняется на самом catboost:
    # compatibility="conditional" (feature engineering даёт attention),
    # но platform_status="ready" -- методологическая совместимость и
    # production-готовность независимы.  Обратное направление оси --
    # lstm: compatibility="blocked" (на этом профиле не хватает истории
    # первому fold'у).  Task 138: lstm -- production-модель (реестр v2,
    # neural-runtime контракта Task 137), platform_status="ready" при
    # установленной опциональной группе; без группы
    # (requirements-neural.txt) -- честный catalog_only.
    catboost = _by_id(result, "catboost")
    assert catboost["compatibility"] == "conditional"
    assert catboost["platform_status"] == "ready"
    assert any(item["id"] == "features" and item["status"] == "attention" for item in catboost["criteria"])

    from apps.api.model_impls.neural_runtime import neuralforecast_runtime_available

    lstm = _by_id(result, "lstm")
    assert lstm["compatibility"] == "blocked"
    assert lstm["platform_status"] == ("ready" if neuralforecast_runtime_available() else "catalog_only")
    # Task 139: nbeats -- тот же neural-семейство (правило < 300 точек
    # блокирует совместимость на этом профиле), та же честная ось
    # platform_status (ready при установленной опциональной группе,
    # catalog_only без неё).
    nbeats = _by_id(result, "nbeats")
    assert nbeats["compatibility"] == "blocked"
    assert nbeats["platform_status"] == ("ready" if neuralforecast_runtime_available() else "catalog_only")
    # Task 140: nhits -- тот же neural-семейство (правило < 300 точек
    # блокирует совместимость на этом профиле), та же честная ось
    # platform_status (ready при установленной опциональной группе,
    # catalog_only без неё).
    nhits = _by_id(result, "nhits")
    assert nhits["compatibility"] == "blocked"
    assert nhits["platform_status"] == ("ready" if neuralforecast_runtime_available() else "catalog_only")
    # Task 141: tft -- тот же neural-семейство (правило < 300 точек
    # блокирует совместимость на этом профиле), та же честная ось
    # platform_status (ready при установленной опциональной группе,
    # catalog_only без неё).
    tft = _by_id(result, "tft")
    assert tft["compatibility"] == "blocked"
    assert tft["platform_status"] == ("ready" if neuralforecast_runtime_available() else "catalog_only")


def test_exogenous_columns_do_not_block_models_that_can_ignore_them():
    result = build_eda_model_matrix(_seasonal_frame(), "Price", task="forecast", horizon=12)

    ets = _by_id(result, "ets")
    exogenous = next(item for item in ets["criteria"] if item["id"] == "exogenous")
    assert exogenous["status"] == "not_required"
    assert ets["compatibility"] != "blocked"

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    profile = DataProfile(n_observations=120, n_exogenous=2)
    assert spec.resolve_applicability("ets", profile).rule_id != "F03"
    assert spec.resolve_applicability("ets", profile, {"exogenous_required": True}).rule_id == "F03"


def test_task_semantics_block_wrong_target_and_keep_volatility_models_conditional():
    result = build_eda_model_matrix(_seasonal_frame(), "Price", task="volatility", horizon=12)

    assert _by_id(result, "naive")["compatibility"] == "blocked"
    garch = _by_id(result, "garch")
    assert garch["compatibility"] == "conditional"
    assert any(item["id"] == "target" and item["status"] == "attention" for item in garch["criteria"])


def test_short_history_and_panel_duplicates_are_explained_per_requirement():
    short = build_eda_model_matrix(_seasonal_frame(40), "Price", task="forecast", horizon=6)
    arima = _by_id(short, "arima")
    assert arima["compatibility"] == "blocked"
    assert any(item["id"] == "history" and item["status"] == "fail" for item in arima["criteria"])

    panel = _seasonal_frame(80)
    panel["Date"] = np.repeat(pd.date_range("2024-01-01", periods=40, freq="D"), 2)
    panel_result = build_eda_model_matrix(panel, "Price")
    assert panel_result["applicable"] is True
    assert panel_result["profile"]["temporal_status"] == "panel"
    assert all(model["compatibility"] == "blocked" for model in panel_result["models"])


def _history_criterion_of(model_out: dict) -> dict:
    return next(item for item in model_out["criteria"] if item["id"] == "history")


def test_soft_history_window_is_attention_and_model_stays_runnable():
    """Task 144: в мягком окне (soft_min <= initial_train < min_observations)
    критерий истории -- attention (blocking=False), совместимость --
    conditional, модель остаётся в shortlist/runnable_shortlist.

    Фрейм n=64, expanding, horizon=2, n_splits=2 -> initial_train=60:
    tbats (soft 50, min 100) и деревья (soft 40, min 100) -- в мягком окне;
    GARCH/VAR/LSTM (без soft) -- по-прежнему fail на 60.
    """
    frame = _seasonal_frame(64)
    result = build_eda_model_matrix(
        frame, "Price", task="forecast", horizon=2, n_splits=2,
    )
    assert result["profile"]["initial_train_observations"] == 60

    soft_ids = ("tbats", "random_forest", "xgboost", "lightgbm", "catboost")
    for model_id in soft_ids:
        model_out = _by_id(result, model_id)
        assert model_out["soft_min_observations"] is not None
        history = _history_criterion_of(model_out)
        assert history["status"] == "attention", model_id
        assert history["blocking"] is False, model_id
        assert "осторожност" in history["conclusion"], model_id
        assert "в пределах мягкого порога" in history["conclusion"], model_id
        assert model_out["compatibility"] == "conditional", model_id
        assert model_id in result["shortlist"], model_id

    # Production-модели из мягкого окна доходят до runnable_shortlist
    # (tbats -- при установленном statsforecast, деревья -- всегда).
    runnable = set(result["runnable_shortlist"])
    assert {"random_forest", "xgboost", "lightgbm", "catboost"} <= runnable
    from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS

    if "tbats" in PRODUCTION_BACKTEST_MODEL_IDS:
        assert "tbats" in runnable

    # Модели БЕЗ soft-порога на том же initial_train=60 -- прежний бинарный
    # fail (директива тимлида: GARCH/VAR/нейросети не трогать).
    for model_id in ("garch", "egarch", "var", "lstm"):
        model_out = _by_id(result, model_id)
        assert model_out["soft_min_observations"] is None, model_id
        history = _history_criterion_of(model_out)
        assert history["status"] == "fail", model_id
        assert history["blocking"] is True, model_id
        assert model_out["compatibility"] == "blocked", model_id


def test_soft_history_floor_below_soft_min_still_blocks():
    """Task 144 (регрессия): ниже мягкого порога блокировка сохраняется.

    Фрейм n=40, expanding, horizon=2, n_splits=2 -> initial_train=36:
    деревья (soft 40) и tbats (soft 50) -- fail/blocked, нижняя граница
    не исчезла.
    """
    result = build_eda_model_matrix(
        _seasonal_frame(40), "Price", task="forecast", horizon=2, n_splits=2,
    )
    assert result["profile"]["initial_train_observations"] == 36

    for model_id in ("tbats", "random_forest", "xgboost", "lightgbm", "catboost"):
        model_out = _by_id(result, model_id)
        history = _history_criterion_of(model_out)
        assert history["status"] == "fail", model_id
        assert history["blocking"] is True, model_id
        assert model_out["compatibility"] == "blocked", model_id
        assert model_id not in result["runnable_shortlist"], model_id


def test_soft_history_boundary_at_soft_min_is_attention():
    """Task 144: граница мягкого окна включительна слева.

    initial_train == soft_min -- уже attention, а не fail.
    Task 145: размер фрейма подстраивается под откалиброванный порог
    (read из спецификации; калибровка 40 -> 60), expanding, horizon=2,
    n_splits=2 -> initial_train = L - 4.
    """
    spec = ModelingSpec.from_yaml(str(
        Path(__file__).resolve().parents[2] / "rules/modeling.yaml"
    ))
    soft_min = spec.get_model("random_forest").soft_min_observations
    result = build_eda_model_matrix(
        _seasonal_frame(soft_min + 4), "Price", task="forecast", horizon=2, n_splits=2,
    )
    assert result["profile"]["initial_train_observations"] == soft_min

    for model_id in ("random_forest", "xgboost", "lightgbm", "catboost"):
        history = _history_criterion_of(_by_id(result, model_id))
        assert history["status"] == "attention", model_id


def test_soft_history_pass_boundary_at_min_is_pass():
    """Task 144: правая граница мягкого окна -- initial_train == min
    означает pass (не attention): мягкое окно открыто только снизу."""
    result = build_eda_model_matrix(
        _seasonal_frame(104), "Price", task="forecast", horizon=2, n_splits=2,
    )
    assert result["profile"]["initial_train_observations"] == 100

    for model_id in ("tbats", "random_forest", "xgboost", "lightgbm", "catboost"):
        model_out = _by_id(result, model_id)
        history = _history_criterion_of(model_out)
        assert history["status"] == "pass", model_id
        assert history["blocking"] is False, model_id


def test_deepar_shape_criterion_is_the_honest_panel_gate():
    """Task 142: shape-критерий DeepAR -- честный panel-гейт по числу
    числовых рядов-кандидатов (target + related датасета).  На фрейме с
    2 числовыми рядами (Price, Volume) панель < min_series=5 --
    fail/blocking с честным сообщением; колонки одного объекта панелью
    НЕ считаются.  До среза 142 критерий был безусловно blocking
    (честный catalog_only)."""
    result = build_eda_model_matrix(_seasonal_frame(), "Price", task="forecast", horizon=12)
    deepar = _by_id(result, "deepar")
    shape = next(item for item in deepar["criteria"] if item["id"] == "shape")
    assert shape["status"] == "fail"
    assert shape["blocking"] is True
    assert "панель" in shape["requirement"].lower()
    assert "нельзя считать панелью" in shape["conclusion"]
    assert deepar["compatibility"] == "blocked"
    from apps.api.model_impls.neural_runtime import neuralforecast_runtime_available

    assert deepar["platform_status"] == (
        "ready" if neuralforecast_runtime_available() else "catalog_only"
    )
