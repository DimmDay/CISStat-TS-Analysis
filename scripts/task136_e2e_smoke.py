# scripts/task136_e2e_smoke.py
"""Task 136 E2E smoke: полный контур EGARCH (leverage/asymmetry) поверх
volatility-движка Task 135 (переиспользуемого бит-в-бит).

1. каталог: 19 «Подключённых» (was 18) + egarch в dispatch/tuning;
2. реестр: egarch objective="volatility", dependency_group="volatility";
3. одномерный движок отказывает volatility-плану egarch (гейт Task 134);
4. volatility-движок: contract->EWMA->QLIKE->диагностика для EGARCH;
5. asymmetry-блок: fitted gamma, leverage_direction, значимость;
6. EGARCH vs GARCH vs EWMA -- честное QLIKE-ранжирование в одном cohort;
7. cohort volatility != level cohort (изоляция Task 134).
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


def egarch_prices(n: int = 220, seed: int = 33) -> pd.DataFrame:
    """Ценовой ряд поверх EGARCH(1,1,1) returns с классическим leverage
    (gamma<0): отрицательные шоки увеличивают волатильность сильнее."""
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = -0.05, 0.12, -0.15, 0.90
    norm_const = np.sqrt(2.0 / np.pi)
    ln_s2 = omega / (1.0 - beta)
    s2 = float(np.exp(ln_s2))
    log_price = [np.log(100.0)]
    for _ in range(n - 1):
        eps = float(np.sqrt(s2) * rng.standard_normal())
        log_price.append(log_price[-1] + eps)
        e = eps / np.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
        s2 = float(np.exp(ln_s2))
    return pd.DataFrame({
        "date": pd.date_range("2023-01-02", periods=n, freq="D").astype(str),
        "value": np.exp(np.asarray(log_price)),
    })


def _vol_pipeline(model_id: str, model_name: str, frame: pd.DataFrame):
    """Полный volatility-пайплайн контракта Task 134 для модели.

    train_window=100: EGARCH MLE (5 параметров лог-рекурсии) честно
    отказывает на коротких train-срезах (convergence_flag != 0 --
    fail-closed, проверено в этом смоуке на train_window=40); достаточная
    история -- производственное требование модели, а не подмена отказа."""
    series = [float(v) for v in frame["value"]]
    labels = [str(v) for v in frame["date"]]
    returns = price_to_returns(series, method="log")
    returns_frame = pd.DataFrame(
        {"__returns__": returns}, index=pd.to_datetime(labels[1:]),
    )
    returns_validation = build_eda_validation_strategy(
        returns_frame.reset_index(drop=True), "__returns__",
        strategy="expanding", horizon=6, n_splits=2, gap=0, train_window=100,
    )
    target = build_volatility_target(series, method="log", timestamps=labels)
    cohort = volatility_cohort_contract(
        target_column="value", fingerprint="fp-smoke136",
        returns_method="log", n_returns=target.n_returns, seasonal_period=1,
    )
    plan = build_backtest_plan(
        returns_validation, n_observations=target.n_returns,
        fingerprint="fp-smoke136", target_column="value", seasonal_period=1,
        objective="volatility",
        series_fingerprints={"value": "fp-smoke136"},
        cohort_contract_override=cohort,
    )
    result = run_volatility_backtest_plan(
        model_id=model_id, model_name=model_name, family_id="volatility",
        target=target, plan=plan, seasonal_period=1,
    )
    return plan, target, result


def main() -> None:
    # (1) Каталог: 19 production-моделей.
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 19, len(PRODUCTION_BACKTEST_MODEL_IDS)
    assert "egarch" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "egarch" in PRODUCTION_TUNING_MODEL_IDS
    assert "egarch" in _BACKTEST_IMPLEMENTATIONS
    print("(1) каталог: 19 connected, egarch в dispatch/tuning OK")

    # (2) Реестр: volatility-контракт (пара garch/egarch в одном движке).
    d = MODEL_EXECUTION_REGISTRY.describe("egarch")
    assert d["objective"] == "volatility" and d["input_kind"] == "univariate"
    assert d["dependency_group"] == "volatility" and d["engine"] == "arch"
    assert d["adapter_id"] == "arch-egarch"
    print("(2) реестр: egarch objective=volatility/univariate/engine=arch OK")

    # (3) Гейт одномерного движка (Task 134 на месте) для egarch.
    frame = egarch_prices()
    series = [float(v) for v in frame["value"]]
    labels = [str(v) for v in frame["date"]]
    level_validation = build_eda_validation_strategy(
        frame, "value", strategy="expanding", horizon=6, n_splits=2, gap=0,
        train_window=40,
    )
    level_plan = build_backtest_plan(
        level_validation, n_observations=len(series), fingerprint="fp-smoke136",
        target_column="value", seasonal_period=1,
    )
    try:
        run_backtest_plan(
            model_id="egarch", model_name="EGARCH(p,o,q)", family_id="volatility",
            series=series, labels=labels, plan=level_plan, seasonal_period=1,
        )
        raise AssertionError("level engine accepted volatility model")
    except BacktestExecutionError as exc:
        assert "volatility" in str(exc)
    print("(3) гейт: одномерный движок отказал volatility-исполнителю egarch OK")

    # (4) Volatility-движок: контракт -> EGARCH -> QLIKE.
    plan, target, result = _vol_pipeline("egarch", "EGARCH(p,o,q)", frame)
    metrics = result["metrics"]
    assert metrics["qlike"] is not None and np.isfinite(metrics["qlike"])
    assert metrics["primary"] == "qlike"
    assert metrics["realized_proxy"] == "squared_returns"
    oof = result["oof_predictions"]
    stamps = list(target.timestamps)
    assert all(point["label"] == stamps[point["index"] + 1] for point in oof)
    assert all(point["predicted"] > 0 for point in oof)
    print(
        "(4) движок: qlike={:.4f} rmse={:.2e} mae={:.2e} n_points={} OK".format(
            metrics["qlike"], metrics["rmse"], metrics["mae"], metrics["n_points"],
        )
    )

    # (5) Asymmetry-блок: leverage честно восстановлен из фита.
    fold0 = result["folds"][0]["volatility_diagnostics"]
    egarch_block = fold0["egarch"]
    assert egarch_block["convergence_flag"] == 0
    assert egarch_block["adapter_id"] == "arch-egarch"
    asymmetry = egarch_block["asymmetry"]
    assert asymmetry["order"] == 1
    assert "gamma[1]" in asymmetry["gamma_params"]
    assert asymmetry["gamma_params"]["gamma[1]"] < 0
    assert asymmetry["leverage_direction"] == "negative"
    assert asymmetry["asymmetry_significant"] is True
    print(
        "(5) asymmetry: gamma={:+.4f} p={:.2e} direction={} significant={} OK".format(
            asymmetry["gamma_params"]["gamma[1]"],
            asymmetry["gamma_pvalues"]["gamma[1]"],
            asymmetry["leverage_direction"],
            asymmetry["asymmetry_significant"],
        )
    )
    print(
        "    диагностика: beta-persistence={:.3f} cov_stationary={} OK".format(
            egarch_block["persistence"],
            egarch_block["is_covariance_stationary"],
        )
    )

    # (6) Честное QLIKE-ранжирование в одном volatility-cohort:
    # EGARCH (leverage-модель) vs GARCH vs EWMA-baseline на тех же folds.
    baseline = result["volatility_baseline"]["aggregate"]["qlike"]
    _, _, garch_result = _vol_pipeline("garch", "GARCH(p,q)", frame)
    garch_qlike = garch_result["metrics"]["qlike"]
    ranking = sorted([
        ("EGARCH", metrics["qlike"]),
        ("GARCH", garch_qlike),
        ("EWMA", baseline),
    ], key=lambda item: item[1])
    print("(6) cohort QLIKE-ранжирование: " +
          " > ".join(name for name, _ in ranking))
    for _, qlike in ranking:
        assert np.isfinite(qlike)

    # (7) Изоляция cohort: volatility plan.cohort_id != level plan.cohort_id.
    assert plan.cohort_id != level_plan.cohort_id
    assert plan.cohort_contract["objective"] == "volatility"
    assert plan.cohort_contract["metric_policy"]["primary"] == "qlike"
    print("(7) изоляция: volatility cohort != level cohort OK")

    print("E2E SMOKE OK -- 19/24 production, leverage/asymmetry честно репортится")


if __name__ == "__main__":
    main()
