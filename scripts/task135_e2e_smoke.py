# scripts/task135_e2e_smoke.py
"""Task 135 E2E smoke: полный контур GARCH поверх контракта Task 134.

1. каталог: 18 «Подключённых» (was 17) + группа «Волатильность» активна;
2. реестр: garch objective="volatility", dependency_group="volatility";
3. одномерный движок отказывает volatility-плану (гейт Task 134 на месте);
4. volatility-движок: мини-пайплайн contract->EWMA->QLIKE->диагностика;
5. GARCH лучше/хуже baseline -- честное QLIKE-ранжирование;
6. cohort volatility != level cohort (изоляция Task 134).
"""
import sys

sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from apps.api.backtesting import (
    BacktestExecutionError,
    build_backtest_plan,
    run_backtest_plan,
    run_volatility_backtest_plan,
)
from apps.api.eda_validation_strategy import build_eda_validation_strategy
from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
from apps.api.model_readiness import (
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
)
from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS
from apps.api.volatility_contract import (
    build_volatility_target,
    price_to_returns,
    volatility_cohort_contract,
    volatility_naive_baseline,
)


def garch_prices(n: int = 160, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    omega, alpha, beta = 5e-6, 0.25, 0.65
    sigma2 = omega / (1.0 - alpha - beta)
    log_price = [np.log(100.0)]
    for _ in range(n - 1):
        eps = rng.standard_normal() * np.sqrt(sigma2)
        log_price.append(log_price[-1] + eps)
        sigma2 = omega + alpha * eps**2 + beta * sigma2
    return pd.DataFrame({
        "date": pd.date_range("2023-01-02", periods=n, freq="D").astype(str),
        "value": np.exp(np.asarray(log_price)),
    })


def main() -> None:
    # (1) Каталог: 18 production-моделей.
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 18, len(PRODUCTION_BACKTEST_MODEL_IDS)
    assert "garch" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "garch" in PRODUCTION_TUNING_MODEL_IDS
    assert "garch" in _BACKTEST_IMPLEMENTATIONS
    print("(1) каталог: 18 connected, garch в dispatch/tuning OK")

    # (2) Реестр: volatility-контракт.
    d = MODEL_EXECUTION_REGISTRY.describe("garch")
    assert d["objective"] == "volatility" and d["input_kind"] == "univariate"
    assert d["dependency_group"] == "volatility" and d["engine"] == "arch"
    print("(2) реестр: garch objective=volatility/univariate/engine=arch OK")

    # (3) Гейт одномерного движка (Task 134 на месте).
    frame = garch_prices()
    series = [float(v) for v in frame["value"]]
    labels = [str(v) for v in frame["date"]]
    level_validation = build_eda_validation_strategy(
        frame, "value", strategy="expanding", horizon=6, n_splits=2, gap=0,
        train_window=40,
    )
    level_plan = build_backtest_plan(
        level_validation, n_observations=len(series), fingerprint="fp-smoke",
        target_column="value", seasonal_period=1,
    )
    try:
        run_backtest_plan(
            model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
            series=series, labels=labels, plan=level_plan, seasonal_period=1,
        )
        raise AssertionError("level engine accepted volatility model")
    except BacktestExecutionError as exc:
        assert "volatility" in str(exc)
    print("(3) гейт: одномерный движок отказал volatility-исполнителю OK")

    # (4) Volatility-движок: контракт -> GARCH -> EWMA -> QLIKE.
    prices = series
    returns = price_to_returns(prices, method="log")
    returns_frame = pd.DataFrame({"__returns__": returns}, index=pd.to_datetime(labels[1:]))
    returns_validation = build_eda_validation_strategy(
        returns_frame.reset_index(drop=True), "__returns__",
        strategy="expanding", horizon=6, n_splits=2, gap=0, train_window=40,
    )
    target = build_volatility_target(prices, method="log", timestamps=labels)
    cohort = volatility_cohort_contract(
        target_column="value", fingerprint="fp-smoke",
        returns_method="log", n_returns=target.n_returns, seasonal_period=1,
    )
    plan = build_backtest_plan(
        returns_validation, n_observations=target.n_returns,
        fingerprint="fp-smoke", target_column="value", seasonal_period=1,
        objective="volatility",
        series_fingerprints={"value": "fp-smoke"},
        cohort_contract_override=cohort,
    )
    result = run_volatility_backtest_plan(
        model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
        target=target, plan=plan, seasonal_period=1,
    )
    metrics = result["metrics"]
    assert metrics["qlike"] is not None and np.isfinite(metrics["qlike"])
    assert metrics["primary"] == "qlike"
    assert metrics["realized_proxy"] == "squared_returns"
    oof = result["oof_predictions"]
    stamps = list(target.timestamps)
    assert all(
        point["label"] == stamps[point["index"] + 1] for point in oof
    )
    assert all(point["predicted"] > 0 for point in oof)
    print(
        "(4) движок: qlike={:.4f} rmse={:.2e} mae={:.2e} n_points={} OK".format(
            metrics["qlike"], metrics["rmse"], metrics["mae"], metrics["n_points"],
        )
    )

    # (5) EWMA-baseline на тех же folds -- честное ранжирование.
    baseline = result["volatility_baseline"]["aggregate"]["qlike"]
    print(
        "(5) baseline: GARCH qlike={:.4f} vs EWMA qlike={:.4f} -> {}".format(
            metrics["qlike"], baseline,
            "GARCH лучше" if metrics["qlike"] < baseline else "EWMA лучше",
        )
    )

    # (6) Изоляция cohort: volatility plan.cohort_id != level plan.cohort_id.
    assert plan.cohort_id != level_plan.cohort_id
    assert plan.cohort_contract["objective"] == "volatility"
    assert plan.cohort_contract["metric_policy"]["primary"] == "qlike"
    print("(6) изоляция: volatility cohort != level cohort OK")

    # (7) Диагностика fold'а.
    fold0 = result["folds"][0]["volatility_diagnostics"]
    assert fold0["garch"]["convergence_flag"] == 0
    assert fold0["standardized_residuals"]["available"] is True
    assert fold0["volatility_clustering_evidence"]["available"] is True
    print(
        "(7) диагностика: persistence={:.3f} cov_stationary={} OK".format(
            fold0["garch"]["persistence"],
            fold0["garch"]["is_covariance_stationary"],
        )
    )

    print("E2E SMOKE OK -- 18/24 production, volatility-cohort изолирован")


if __name__ == "__main__":
    main()
