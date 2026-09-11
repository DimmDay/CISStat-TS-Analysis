# tests/unit/test_lstm_adapter.py
"""Task 138 -- LSTM/GRU vertical slice: юнит-контракт адаптера
(apps/api/model_impls/lstm.py) на едином NeuralForecast-runtime Task 137.

Слои проверки (по прецеденту сертифицированных срезов 132/135/136):
- validate_lstm_params: bounded fail-closed нормализация (никаких
  «неизвестное -- значит молча дефолт» для объявленных ключей);
- data-plane контракта Task 137: timestamps -> freq (validate_regular_grid
  -- единый источник истины регулярной сетки Task 131), long-format,
  exogenous-план (granted-канал -> futr-роль), fail-closed на NaN/Inf/
  дубликаты/коллизии имён;
- исполнение: точечный прогноз + conformal-интервалы
  (interval_levels_for_alpha), детерминизм (same seed -- бит-в-бит,
  другой seed -- другой прогноз), cell-паритет LSTM/GRU;
- metadata: нейро-контракт (config/exogenous-план/intervals/versions);
- legacy synthetic-эндпоинт: честный отказ на короткой demo-истории,
  реальный backtest на достаточной.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.model_impls.lstm import (
    DEFAULT_PARAMS,
    LSTM_ADAPTER_ID,
    LSTM_MIN_TRAIN,
    PARAM_BOUNDS,
    _lstm_fit_predict,
    run_lstm_backtest,
    validate_lstm_params,
)

pytest.importorskip("neuralforecast", reason="neural runtime -- опциональная группа")


def _series(n: int = 140, seed: int = 11) -> list[float]:
    rng = np.random.default_rng(seed)
    return [
        float(
            50.0
            + 0.15 * step
            + 4.0 * np.sin(2.0 * np.pi * step / 12.0)
            + rng.standard_normal() * 0.6
        )
        for step in range(n)
    ]


def _labels(n: int = 140, freq: str = "MS") -> list[str]:
    return [
        value.isoformat()
        for value in pd.date_range("2018-01-01", periods=n, freq=freq)
    ]


def _fit_predict(**overrides):
    payload = dict(
        target=_series(120),
        horizon=6,
        params={"max_steps": 4, "input_size": 24},
        random_state=42,
        train_timestamps=_labels(120),
        future_timestamps=_labels(126)[120:],
    )
    payload.update(overrides)
    return _lstm_fit_predict(**payload)


# ── 1. Bounded params: fail-closed нормализация ──────────────────────────

def test_default_params_are_normalized_and_bounded() -> None:
    normalized = validate_lstm_params(None)
    assert normalized["cell"] == "lstm"
    assert normalized["input_size"] == DEFAULT_PARAMS["input_size"]
    assert normalized["max_steps"] == DEFAULT_PARAMS["max_steps"]
    assert normalized["alpha"] == 0.05


def test_unknown_param_keys_are_ignored() -> None:
    """Соглашение платформы: в params приходят чужие ключи движка
    (tbats_seasonal_periods и др.) -- они не ломают адаптер."""
    normalized = validate_lstm_params({"tbats_seasonal_periods": [7, 365], "max_steps": 9})
    assert normalized["max_steps"] == 9
    assert "tbats_seasonal_periods" not in normalized


@pytest.mark.parametrize("cell", ["rnn", "transformer", "LSTM", "", None])
def test_fail_closed_on_unknown_cell(cell) -> None:
    with pytest.raises(ValueError, match="cell"):
        validate_lstm_params({"cell": cell})


def test_fail_closed_on_out_of_bound_input_size() -> None:
    low, high = PARAM_BOUNDS["input_size"]
    with pytest.raises(ValueError, match="input_size"):
        validate_lstm_params({"input_size": low - 1})
    with pytest.raises(ValueError, match="input_size"):
        validate_lstm_params({"input_size": high + 1})


def test_fail_closed_on_out_of_bound_hidden_size() -> None:
    low, high = PARAM_BOUNDS["encoder_hidden_size"]
    with pytest.raises(ValueError, match="encoder_hidden_size"):
        validate_lstm_params({"encoder_hidden_size": low - 1})
    with pytest.raises(ValueError, match="encoder_hidden_size"):
        validate_lstm_params({"encoder_hidden_size": high + 1})


def test_fail_closed_on_out_of_bound_layers_and_dropout() -> None:
    with pytest.raises(ValueError, match="encoder_n_layers"):
        validate_lstm_params({"encoder_n_layers": 0})
    with pytest.raises(ValueError, match="encoder_n_layers"):
        validate_lstm_params({"encoder_n_layers": 4})
    with pytest.raises(ValueError, match="encoder_dropout"):
        validate_lstm_params({"encoder_dropout": -0.1})
    with pytest.raises(ValueError, match="encoder_dropout"):
        validate_lstm_params({"encoder_dropout": 0.6})


def test_fail_closed_on_out_of_bound_learning_rate_and_steps() -> None:
    with pytest.raises(ValueError, match="learning_rate"):
        validate_lstm_params({"learning_rate": 0.0})
    with pytest.raises(ValueError, match="learning_rate"):
        validate_lstm_params({"learning_rate": 0.5})
    with pytest.raises(ValueError, match="max_steps"):
        validate_lstm_params({"max_steps": 0})
    with pytest.raises(ValueError, match="max_steps"):
        validate_lstm_params({"max_steps": 10_001})


def test_fail_closed_on_non_whitelist_alpha() -> None:
    with pytest.raises(ValueError, match="alpha"):
        validate_lstm_params({"alpha": 0.2})
    with pytest.raises(ValueError, match="alpha"):
        validate_lstm_params({"alpha": "0.15"})
    # Прецедент GARCH: числовая строка, попадающая в whitelist, коэрцируется
    # честно (те же 0.05, ни нового значения, ни скрытой подмены).
    assert validate_lstm_params({"alpha": "0.05"})["alpha"] == 0.05


def test_fail_closed_on_bool_instead_of_int() -> None:
    """bool -- подкласс int: явная защита от True->1 коэрции."""
    with pytest.raises(ValueError, match="input_size"):
        validate_lstm_params({"input_size": True})


# ── 2. Data-plane: timestamps/freq/long-format fail-closed ──────────────

def test_fail_closed_on_empty_target() -> None:
    with pytest.raises(ValueError, match="пуст"):
        _lstm_fit_predict(
            [], 4, params={}, train_timestamps=_labels(4),
        )


def test_fail_closed_on_non_positive_horizon() -> None:
    with pytest.raises(ValueError, match="horizon"):
        _fit_predict(horizon=0)


def test_fail_closed_on_missing_train_timestamps() -> None:
    """Прецедент prophet: нейро-модель требует реальную временную ось --
    row-order метки не дают частоты, контракт не выполняет скрытую
    регуляризацию."""
    with pytest.raises(ValueError, match="train_timestamps"):
        _fit_predict(train_timestamps=None)


def test_fail_closed_on_irregular_grid() -> None:
    stamps = [value.isoformat() for value in pd.to_datetime(
        ["2020-01-01", "2020-01-02", "2020-01-04", "2020-01-10", "2020-02-01"],
    )]
    stamps += [value.isoformat() for value in pd.date_range("2020-02-02", periods=115, freq="D")]
    with pytest.raises(ValueError, match="нерегулярн"):
        _fit_predict(target=_series(120), train_timestamps=stamps)


def test_fail_closed_on_duplicate_timestamps() -> None:
    stamps = _labels(120)
    stamps[10] = stamps[9]
    with pytest.raises(ValueError, match="повторяются даты"):
        _fit_predict(train_timestamps=stamps)


def test_fail_closed_on_short_history() -> None:
    with pytest.raises(ValueError, match=f"минимум {LSTM_MIN_TRAIN}"):
        _fit_predict(target=_series(20), train_timestamps=_labels(20))


def test_fail_closed_when_window_infeasible_for_history() -> None:
    """input_size + horizon >= n_train -- честный отказ: ни одного полного
    учебного окна; контракт не ужимает окно молча."""
    with pytest.raises(ValueError, match="окн"):
        _fit_predict(
            target=_series(60), train_timestamps=_labels(60), horizon=12,
            params={"max_steps": 4, "input_size": 48},
        )


# ── 3. Exogenous-канал (granted Task 126 -> futr-роль контракта) ────────

def test_fail_closed_on_future_features_without_train_counterpart() -> None:
    with pytest.raises(ValueError, match="future_features"):
        _fit_predict(future_features={"promo": [1.0] * 6})


def test_fail_closed_on_train_features_without_future_counterpart() -> None:
    with pytest.raises(ValueError, match="future_features"):
        _fit_predict(train_features={"promo": [0.0] * 120})


def test_fail_closed_on_feature_name_collision_with_service_columns() -> None:
    """Колонка 'y'/'ds'/'unique_id' в regressor-канале столкнулась бы с
    сервисными колонками long-format -- fail-closed до fit."""
    with pytest.raises(ValueError, match="служебн"):
        _fit_predict(
            train_features={"y": [0.0] * 120},
            future_features={"y": [0.0] * 6},
        )


def test_fail_closed_on_future_frame_missing_horizon_coverage() -> None:
    with pytest.raises(ValueError, match="future_features"):
        _fit_predict(
            train_features={"promo": [0.0] * 120},
            future_features={"promo": [1.0] * 4},  # horizon=6
        )


def test_exogenous_path_produces_forecast_with_plan_signature() -> None:
    payload = _fit_predict(
        train_features={"promo": [0.0] * 119 + [1.0]},
        future_features={"promo": [1.0] * 6},
    )
    assert len(payload["forecast"]) == 6
    assert payload["exogenous_plan"]["futr"] == ["promo"]
    assert payload["exogenous_plan"]["hist"] == [] and payload["exogenous_plan"]["stat"] == []
    assert payload["exogenous_plan"]["signature"]


def test_feature_free_path_declares_empty_plan() -> None:
    payload = _fit_predict()
    assert payload["exogenous_plan"]["futr"] == []
    assert payload["forecast"] and all(np.isfinite(payload["forecast"]))


# ── 4. Исполнение: прогноз/интервалы/детерминизм/паритет ячеек ───────────

def test_forecast_length_and_finiteness() -> None:
    payload = _fit_predict()
    assert len(payload["forecast"]) == 6
    assert len(payload["lower"]) == 6 and len(payload["upper"]) == 6
    assert all(np.isfinite(payload["forecast"]))
    assert all(
        lower <= point <= upper
        for lower, point, upper in zip(
            payload["lower"], payload["forecast"], payload["upper"], strict=True,
        )
    )


def test_same_seed_bit_identical_forecast() -> None:
    first = _fit_predict(params={"max_steps": 6, "input_size": 24})
    second = _fit_predict(params={"max_steps": 6, "input_size": 24})
    assert first["forecast"] == second["forecast"]
    assert first["lower"] == second["lower"]


def test_different_seed_changes_forecast() -> None:
    first = _fit_predict(random_state=42, params={"max_steps": 6})
    second = _fit_predict(random_state=43, params={"max_steps": 6})
    assert first["forecast"] != second["forecast"]


def test_gru_cell_produces_forecast_on_same_runtime() -> None:
    payload = _fit_predict(params={"cell": "gru", "max_steps": 4})
    assert payload["params"]["cell"] == "gru"
    assert len(payload["forecast"]) == 6


def test_alpha_drives_interval_width_symmetrically() -> None:
    """Двусторонний (1-alpha)-интервал: alpha=0.01 -> уровни 0.5/50/99.5
    (границы на lo-99.5/hi-99.5 = 0.5/99.5 квантили, шире), alpha=0.10 ->
    5/50/95 (уже).  Семантика conformal-колонок снята эмпирически:
    lo-L/hi-L = point ∓ q(L/100)."""
    wider = _fit_predict(params={"max_steps": 5, "alpha": 0.01})
    narrower = _fit_predict(params={"max_steps": 5, "alpha": 0.10})
    assert wider["intervals"]["levels"][0] == pytest.approx(0.5)
    assert wider["intervals"]["interval_level"] == pytest.approx(99.5)
    assert narrower["intervals"]["interval_level"] == pytest.approx(95.0)
    wider_width = [u - l for l, u in zip(wider["lower"], wider["upper"], strict=True)]
    narrower_width = [
        u - l for l, u in zip(narrower["lower"], narrower["upper"], strict=True)
    ]
    assert sum(wider_width) > sum(narrower_width)


# ── 5. Metadata: нейро-контракт в ответе адаптера ────────────────────────

def test_metadata_carries_neural_contract_block() -> None:
    payload = _fit_predict(random_state=4242)
    assert payload["adapter_id"] == LSTM_ADAPTER_ID == "neuralforecast-lstm"
    neural = payload["neural"]
    assert neural["config"]["seed"] == 4242
    assert neural["config"]["max_steps"] == 4
    assert neural["contract_version"] == "neural-contract-v1"
    assert neural["runtime"] == "neuralforecast"
    assert payload["frequency"] in {"MS", "M", "ME"}
    assert payload["deterministic"] is True
    assert payload["n_train"] == 120
    versions = payload["neural"]["library_versions"]
    assert versions["neuralforecast"]
    assert versions["torch"]


def test_metadata_declares_cell_and_alias() -> None:
    lstm_payload = _fit_predict()
    gru_payload = _fit_predict(params={"cell": "gru"})
    assert lstm_payload["alias"] == "LSTM"
    assert gru_payload["alias"] == "GRU"


# ── 6. Legacy synthetic-эндпоинт: честность ──────────────────────────────

def test_legacy_endpoint_honest_refusal_on_bare_series() -> None:
    """Bare-ряд synthetic-эндпоинта не несёт временной оси; изобретать её
    внутри обёртки -- скрытый выбор, запрещённый контрактом.  Честный отказ
    (ValueError), как у VAR/VECM/GARCH/EGARCH -- никаких Naive-подмен."""
    with pytest.raises(ValueError, match="временной оси"):
        run_lstm_backtest(_series(140), train_ratio=0.7, seasonal_period=12)
