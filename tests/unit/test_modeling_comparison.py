from __future__ import annotations

import pytest

from apps.api.modeling_comparison import (
    ComparisonContractError,
    _fold_stability,
    aligned_oof,
    build_comparison,
    diagnostics_signature,
)


def _backtest(model_id: str, fold_rmse: list[float], *, actual_shift: float = 0.0) -> dict:
    folds = []
    points = []
    for fold, rmse in enumerate(fold_rmse, 1):
        folds.append({
            "fold": fold, "train_start": 0, "train_end": fold,
            "test_start": fold + 1, "test_end": fold + 1, "gap": 0,
            "metrics": {"rmse": rmse},
        })
        points.append({
            "fold": fold, "horizon_step": 1, "index": fold + 1,
            "label": f"t{fold}", "actual": 10.0 + fold + actual_shift,
            "predicted": 9.0 + fold, "residual": 1.0 + actual_shift,
        })
    return {
        "model_id": model_id, "folds": folds, "oof_predictions": points,
        "preprocessing": {"evaluation_scale": "value"},
    }


def test_fold_rank_stability_does_not_break_ties_by_model_name() -> None:
    stability = _fold_stability([
        _backtest("z_model", [1.0, 2.0]),
        _backtest("a_model", [1.0, 2.0]),
    ])

    assert stability["z_model"].fold_ranks == [1, 1]
    assert stability["a_model"].fold_ranks == [1, 1]
    assert stability["z_model"].top1_rate == 1
    assert stability["a_model"].top1_rate == 1


def test_aligned_oof_rejects_different_facts_even_with_same_keys() -> None:
    with pytest.raises(ComparisonContractError, match="Фактические значения"):
        aligned_oof([
            _backtest("first", [1.0, 2.0]),
            _backtest("second", [1.0, 2.0], actual_shift=1.0),
        ])


def test_aligned_oof_rejects_different_train_only_mase_scales() -> None:
    first = _backtest("first", [1.0, 2.0])
    second = _backtest("second", [1.0, 2.0])
    first["folds"][0]["mase_scale"] = 1.5
    second["folds"][0]["mase_scale"] = 1.6

    with pytest.raises(ComparisonContractError, match="MASE scales"):
        aligned_oof([first, second])


def test_diagnostics_signature_is_deterministic_and_not_self_referential() -> None:
    report = {
        "model_id": "naive", "cohort_id": "cohort", "backtest_run_id": "run",
        "parameter_signature": "params", "residuals_signature": "oof", "alpha": 0.05,
        "diagnostics": [{"test": "ljung_box", "applicable": True, "status": "pass"}],
    }
    first = diagnostics_signature(report)
    report["diagnostics_signature"] = "stale-value"

    assert diagnostics_signature(report) == first
    assert len(first) == 64


def _rankable_backtest(
    model_id: str, family_id: str, *, mae: float, rmse: float, mase: float,
) -> dict:
    actual = [10.0, 20.0, 30.0, 40.0]
    residuals = [rmse * 0.8, -rmse * 1.1, rmse * 0.9, -rmse * 1.05]
    points = [
        {
            "fold": 1 if index < 2 else 2,
            "horizon_step": index % 2 + 1,
            "index": 20 + index,
            "label": f"t{index}",
            "actual": value,
            "predicted": value - residuals[index],
            "residual": residuals[index],
        }
        for index, value in enumerate(actual)
    ]
    folds = []
    for fold, scale in ((1, 1.5), (2, 1.6)):
        selected = [point for point in points if point["fold"] == fold]
        folds.append({
            "fold": fold, "train_start": 0, "train_end": 9 + fold,
            "test_start": 20 + (fold - 1) * 2,
            "test_end": 21 + (fold - 1) * 2, "gap": 0,
            "metrics": {"rmse": rmse}, "mase_scale": scale,
            "predictions": selected,
        })
    return {
        "model_id": model_id, "model_name": model_id, "family_id": family_id,
        "metrics": {
            "mae": mae, "rmse": rmse, "mape": 5.0, "mase": mase,
            "smape": 5.0, "rmsse": rmse / 2, "mape_valid_points": 4,
            "weighted_score": None,
        },
        "run_id": f"run-{model_id}", "params_source": "model_default",
        "parameter_signature": f"params-{model_id}",
        "oof_signature": f"oof-{model_id}", "tuning_id": None,
        "horizon": 24, "folds": folds, "oof_predictions": points,
        "preprocessing": {"evaluation_scale": "value"},
    }


def test_baseline_gate_uses_same_horizon_oof_rmse_and_mase_is_auditable() -> None:
    backtests = [
        _rankable_backtest("naive", "baselines", mae=2.8, rmse=3.0, mase=2.8),
        _rankable_backtest("ets", "exponential_smoothing", mae=2.2, rmse=2.4, mase=2.5),
        _rankable_backtest("mean", "baselines", mae=5.7, rmse=6.0, mase=6.4),
    ]
    diagnostics = {}
    for item in backtests:
        report = {
            "model_id": item["model_id"], "cohort_id": "cohort",
            "backtest_run_id": item["run_id"],
            "parameter_signature": item["parameter_signature"],
            "residuals_signature": item["oof_signature"], "alpha": 0.05,
            "diagnostics": [],
        }
        report["diagnostics_signature"] = diagnostics_signature(report)
        diagnostics[item["model_id"]] = report

    result = build_comparison(
        fingerprint="fp", cohort_id="cohort", backtests=backtests,
        diagnostics=diagnostics,
        applicability_levels={item["model_id"]: "RECOMMENDED" for item in backtests},
        comparison_id="comparison", seasonal_period=1,
    )

    by_id = {item.model_id: item for item in result.ranking}
    assert all(item.metrics.mase > 1.05 for item in result.ranking)
    assert by_id["ets"].baseline_eligible is True
    assert by_id["ets"].baseline_comparison.baseline_model_id == "naive"
    assert by_id["ets"].baseline_comparison.metric == "rmse"
    assert by_id["ets"].baseline_comparison.loss_ratio == pytest.approx(0.8)
    assert by_id["mean"].baseline_eligible is False
    assert by_id["mean"].baseline_comparison.loss_ratio == pytest.approx(2.0)
    assert result.mase_context.horizon == 24
    assert result.mase_context.seasonal_period == 1
    assert [item.scale for item in result.mase_context.fold_scales] == [1.5, 1.6]
    assert result.mase_context.is_same_horizon_baseline_comparison is False
    assert not any("MASE > 1.05" in warning for warning in result.warnings)
