# tests/api/test_garch_session.py
"""Task 135 -- GARCH: session-контур volatility-модели (API).

Честная проводка volatility-контракта Task 134 в session-пайплайн:
- backtest garch требует ЯВНЫЙ returns_method (скрытый выбор запрещён
  контрактом: «Явное преобразование цены в returns без скрытого выбора»);
- ответ -- objective="volatility", cohort с metric_policy.primary=qlike,
  QLIKE-метрики, EWMA-baseline и volatility_diagnostics по folds;
- tuning garch исполняет bounded grid по metric="qlike";
- comparison отвергает смешение volatility- и level-cohort (уже
  сертифицировано Task 131/134 -- здесь честный smoke).
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


def _garch_csv(n: int = 150, seed: int = 21) -> str:
    """Строго положительный ценовой ряд с ЯВНОЙ кластеризацией волатильности
    (ARCH-LM reject, p_value ~ 0 при nlags=8 -- зафиксировано probe'ом);
    n >= 100 (modeling.yaml::garch min_observations)."""
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
        files={"file": ("series.csv", io.BytesIO(_garch_csv().encode()), "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200
    context = client.get("/v1/session/modeling/context?horizon=6&n_splits=2")
    assert context.status_code == 200, context.text
    body = context.json()
    assert "garch" in body["runnable_shortlist"]
    # Честный профиль данных: evidence кластеризации волатильности.
    assert body["profile"]["has_volatility_clustering"] is True


def test_garch_backtest_requires_explicit_returns_method(client: TestClient):
    """Fail-closed: volatility-модель без returns_method не исполняется --
    скрытый выбор преобразования цены в returns запрещён контрактом."""
    _prepare(client)
    response = client.post("/v1/session/modeling/backtest", json={"model_id": "garch"})
    assert response.status_code == 422
    assert "returns_method" in response.json()["detail"]

    response = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "garch", "returns_method": "auto"},
    )
    assert response.status_code == 422


def test_garch_runs_volatility_session_backtest(client: TestClient):
    _prepare(client)
    response = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "garch", "returns_method": "log"},
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

    # QLIKE-метрики + честный realized-proxy в OOF-точках.
    metrics = body["metrics"]
    # Robust-форма Паттона законно отрицательна для малых дисперсий.
    assert metrics["qlike"] is not None and np.isfinite(metrics["qlike"])
    # realized proxy -- объявление cohort'а (metric_policy.volatility).
    assert volatility_block["realized_proxy"] == "squared_returns"
    points = body["oof_predictions"]
    assert points
    assert all(point["actual"] >= 0 and point["predicted"] > 0 for point in points)
    assert all(
        point["residual"] == pytest.approx(point["actual"] - point["predicted"], abs=1e-12)
        for point in points
    )
    # Лейбл OOF-точки -- дата реализации return (t[i+1] ценовой оси).
    assert points[0]["label"] is not None

    # EWMA-baseline на тех же folds.
    assert body["volatility_baseline"]["aggregate"]["qlike"] is not None
    assert len(body["volatility_baseline"]["folds"]) == len(body["folds"])

    # Fold-local диагностика: GARCH-блок + стандартизованные остатки.
    for fold in body["folds"]:
        diagnostics = fold["volatility_diagnostics"]
        assert diagnostics["garch"]["convergence_flag"] == 0
        assert diagnostics["standardized_residuals"]["available"] is True
        assert diagnostics["volatility_clustering_evidence"]["available"] is True

    # Дублирование в session-артефактах сохраняет volatility-артефакты.
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    stored = get_session_store().get(session_id).modeling_artifacts["backtests"]["garch"]
    assert stored["objective"] == "volatility"
    assert stored["metrics"]["qlike"] is not None


def test_garch_tuning_executes_grid_on_qlike(client: TestClient):
    _prepare(client)
    backtest = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "garch", "returns_method": "log"},
    )
    assert backtest.status_code == 200, backtest.text

    tune = client.post(
        "/v1/session/modeling/tune",
        json={
            "model_id": "garch", "metric": "qlike", "max_trials": 8,
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


def test_garch_level_metric_tuning_mape_fails_honest(client: TestClient):
    """mape на условной дисперсии не определена -- честный отказ tuning."""
    _prepare(client)
    backtest = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "garch", "returns_method": "log"},
    )
    assert backtest.status_code == 200, backtest.text
    tune = client.post(
        "/v1/session/modeling/tune",
        json={
            "model_id": "garch", "metric": "mape", "max_trials": 2,
            "returns_method": "log",
        },
    )
    assert tune.status_code == 422


def test_comparison_rejects_objective_mixing_with_garch(client: TestClient):
    """Сертифицированный гейт Task 134/131: GARCH нельзя ранжировать рядом
    с ETS/ARIMA -- aligned_oof отвергает смешение objective (unit-level
    честный smoke: session-compare закрыт scope-гейтами полного выполнения)."""
    from apps.api.modeling_comparison import ComparisonContractError, aligned_oof

    def _fake_backtest(model_id: str, objective: str) -> dict:
        point = {
            "fold": 1, "horizon_step": 1, "index": 0, "label": "2023-01-02",
            "actual": 0.0004, "predicted": 0.00035, "residual": 0.00005,
            "series": None,
        }
        return {
            "model_id": model_id, "objective": objective,
            "cohort_contract": {"objective": objective, "fingerprint": "fp"},
            "oof_predictions": [point],
            "folds": [{"fold": 1, "train_start": 0, "train_end": 9,
                       "test_start": 10, "test_end": 15, "gap": 0}],
            "preprocessing": {"evaluation_scale": "value"},
        }

    with pytest.raises(ComparisonContractError, match="objective"):
        aligned_oof([
            _fake_backtest("garch", "volatility"),
            _fake_backtest("naive", "level_forecast"),
        ])
