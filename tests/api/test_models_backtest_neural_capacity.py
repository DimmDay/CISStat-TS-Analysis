# tests/api/test_models_backtest_neural_capacity.py
"""Task 138c -- HTTP-мэппинг честной деградации нейро-runtime.

Симптом (Render free 512 MB): POST /v1/models/backtest {model_id: 'lstm'}
падал через OOM-kill процесса -> прокси отдавал слепой 502.  После гейта
(neural_resources) legacy-роутер обязан отвечать 503 с действенным
сообщением (инстанс/требование/совет), сервис жив, остальные эндпоинты
не затронуты.
"""
from __future__ import annotations

import os

os.environ["CISSTAT_API_KEYS"] = (
    "test-key:external_user:demo,"
    "pro-key:external_user:professional,"
    "admin-key:admin:"
)

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.neural_contract import NeuralRuntimeCapacityError
from apps.api.routers import models as models_router

client = TestClient(app)

PRO_HEADERS = {"X-API-Key": "pro-key"}  # can_train_models=True

MACRO_PROFILE = {
    "n_observations": 120,
    "n_series": 1,
    "n_exogenous": 0,
    "is_regular": True,
    "frequency": "M",
    "has_seasonality": True,
    "seasonal_periods": [12],
    "is_stationary_or_diffable": True,
    "is_cointegrated": False,
    "has_negative_values": False,
    "has_volatility_clustering": False,
    "domain": "macro",
    "missing_ratio": 0.0,
    "outlier_ratio": 0.0,
}


def test_backtest_lstm_503_with_honest_message_on_insufficient_memory(monkeypatch):
    """Guard срабатывает на маленьком инстансе -> 503 + действенное
    сообщение вместо слепого 502 от OOM-обвала сервиса."""

    def _raise_capacity(*args, **kwargs):
        raise NeuralRuntimeCapacityError(
            "Нейро-runtime не может быть импортирован: инстанс располагает "
            "~512 MB памяти, нейро-модели требуют >= 1024 MB "
            "(memory_class='standard')."
        )

    monkeypatch.setitem(
        models_router._BACKTEST_IMPLEMENTATIONS, "lstm", _raise_capacity,
    )
    response = client.post(
        "/v1/models/backtest",
        headers=PRO_HEADERS,
        json={
            "model_id": "lstm",
            "profile": MACRO_PROFILE,
            "train_ratio": 0.8,
        },
    )
    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert "512 MB" in detail and "1024 MB" in detail


def test_backtest_non_neural_models_unaffected_by_capacity_guard(monkeypatch):
    """Гейт -- только нейро-модели: классика (naive) работает на том же
    маленьком инстансе; сообщение об ошибке не всплывает в чужих путях."""

    response = client.post(
        "/v1/models/backtest",
        headers=PRO_HEADERS,
        json={
            "model_id": "naive",
            "profile": MACRO_PROFILE,
            "train_ratio": 0.8,
        },
    )
    assert response.status_code == 200, response.text
