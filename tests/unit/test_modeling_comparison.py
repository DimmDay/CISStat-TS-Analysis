from __future__ import annotations

import pytest

from apps.api.modeling_comparison import (
    ComparisonContractError,
    _fold_stability,
    aligned_oof,
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
