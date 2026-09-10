# tests/api/test_egarch_session.py
"""Task 136 -- EGARCH: session-контур volatility-модели (API).

Зеркало test_garch_session.py (Task 135): volatility-движок переиспользуется
бит-в-бит, EGARCH проходит тот же session-пайплайн:
- backtest egarch требует ЯВНЫЙ returns_method (скрытый выбор запрещён);
- ответ -- objective="volatility", cohort qlike, EWMA-baseline и
  volatility_diagnostics с egarch-блоком (ключ = model_id) и
  asymmetry-метаданными leverage;
- tuning egarch исполняет bounded grid по metric="qlike";
- level-метрика (mape) на условной дисперсии -- честный отказ.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _egarch_csv(n: int = 150, seed: int = 21) -> str:
    """Строго положительный ценовой ряд с ЯВНОЙ кластеризацией волатильности
    (тот же генератор, что у garch-тестов: ARCH-LM reject при nlags=8)."""
    rng = np.random.default_rng(seed)
    omega, alpha, beta = 5e-6, 0.25, 0.65
    sigma2 = omega / (1.0 - alpha - beta)
    log_price = [np.log(100.0)]
    for _ in range(n - 1):
        eps = rng.standard_normal() * np.sqrt(sigma2)
        log_price.append(log_price[-1] + eps)
        sigma2 = omega + alpha * eps**2 + beta * sigma2
    frame = pd.DataFrame({
        "date": pd.date_range("2023-01-02", periods=n, freq="D").astype(str),
        "value": np.exp(np.asarray(log_price)),
    })
    return frame.to_csv(index=False)


def _prepare(client: TestClient) -> None:
    uploaded = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_egarch_csv().encode()), "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200
    context = client.get("/v1/session/modeling/context?horizon=6&n_splits=2")
    assert context.status_code == 200, context.text
    body = context.json()
    assert "egarch" in body["runnable_shortlist"]
    assert body["profile"]["has_volatility_clustering"] is True


def test_egarch_backtest_requires_explicit_returns_method(client: TestClient):
    """Fail-closed: volatility-модель без returns_method не исполняется."""
    _prepare(client)
    response = client.post("/v1/session/modeling/backtest", json={"model_id": "egarch"})
    assert response.status_code == 422
    assert "returns_method" in response.json()["detail"]

    response = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "egarch", "returns_method": "auto"},
    )
    assert response.status_code == 422


def test_egarch_runs_volatility_session_backtest(client: TestClient):
    _prepare(client)
    response = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "egarch", "returns_method": "log"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "success"
    assert body["objective"] == "volatility"
    assert body["cohort_contract"]["objective"] == "volatility"
    volatility_block = body["cohort_contract"]["metric_policy"]["volatility"]
    assert volatility_block["returns_method"] == "log"
    assert volatility_block["target_kind"] == "conditional_variance"
    assert volatility_block["realized_proxy"] == "squared_returns"
    assert body["cohort_contract"]["metric_policy"]["primary"] == "qlike"

    metrics = body["metrics"]
    assert metrics["qlike"] is not None and np.isfinite(metrics["qlike"])
    points = body["oof_predictions"]
    assert points
    assert all(point["actual"] >= 0 and point["predicted"] > 0 for point in points)
    assert all(
        point["residual"] == pytest.approx(point["actual"] - point["predicted"], abs=1e-12)
        for point in points
    )
    assert points[0]["label"] is not None

    assert body["volatility_baseline"]["aggregate"]["qlike"] is not None
    assert len(body["volatility_baseline"]["folds"]) == len(body["folds"])

    # Fold-local диагностика: egarch-блок (ключ = model_id) с
    # asymmetry-метаданными leverage + стандартизованные остатки.
    for fold in body["folds"]:
        diagnostics = fold["volatility_diagnostics"]
        egarch_block = diagnostics["egarch"]
        assert egarch_block["convergence_flag"] == 0
        assert egarch_block["adapter_id"] == "arch-egarch"
        asymmetry = egarch_block["asymmetry"]
        assert asymmetry["order"] == 1
        assert "gamma[1]" in asymmetry["gamma_params"]
        assert diagnostics["standardized_residuals"]["available"] is True
        assert diagnostics["volatility_clustering_evidence"]["available"] is True

    # Дублирование в session-артефактах сохраняет volatility-артефакты.
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    stored = get_session_store().get(session_id).modeling_artifacts["backtests"]["egarch"]
    assert stored["objective"] == "volatility"
    assert stored["metrics"]["qlike"] is not None


def test_egarch_tuning_executes_grid_on_qlike(client: TestClient):
    _prepare(client)
    backtest = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "egarch", "returns_method": "log"},
    )
    assert backtest.status_code == 200, backtest.text

    tune = client.post(
        "/v1/session/modeling/tune",
        json={
            "model_id": "egarch", "metric": "qlike", "max_trials": 6,
            "returns_method": "log",
        },
    )
    assert tune.status_code == 200, tune.text
    body = tune.json()
    assert body["objective"] == "volatility"
    assert body["metric"] == "qlike"
    assert body["n_trials"] >= 1
    assert body["best_metrics"]["qlike"] is not None
    promoted = body["promoted_backtest"]
    assert promoted["metrics"]["qlike"] is not None
    assert promoted["objective"] == "volatility"


def test_egarch_level_metric_tuning_mape_fails_honest(client: TestClient):
    """mape на условной дисперсии не определена -- честный отказ tuning."""
    _prepare(client)
    backtest = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "egarch", "returns_method": "log"},
    )
    assert backtest.status_code == 200, backtest.text
    tune = client.post(
        "/v1/session/modeling/tune",
        json={
            "model_id": "egarch", "metric": "mape", "max_trials": 2,
            "returns_method": "log",
        },
    )
    assert tune.status_code == 422
