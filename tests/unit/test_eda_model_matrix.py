from __future__ import annotations

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
