from __future__ import annotations

from copy import deepcopy

import pytest

from apps.api.modeling_comparison import diagnostics_signature
from apps.api.modeling_selection import (
    SelectionContractError,
    SelectionPolicy,
    evaluate_selection,
)


def _points(model_id: str, predicted: list[float]) -> list[dict]:
    actual = [10.0, 20.0, 30.0, 40.0]
    return [
        {
            "fold": 1 if index < 2 else 2,
            "horizon_step": index % 2 + 1,
            "index": index + 20,
            "label": f"t{index}",
            "actual": value,
            "predicted": predicted[index],
            "residual": value - predicted[index],
        }
        for index, value in enumerate(actual)
    ]


def _backtest(model_id: str, family: str, predicted: list[float]) -> dict:
    points = _points(model_id, predicted)
    folds = []
    for fold in (1, 2):
        selected = [point for point in points if point["fold"] == fold]
        residuals = [point["residual"] for point in selected]
        mae = sum(abs(value) for value in residuals) / len(residuals)
        rmse = (sum(value**2 for value in residuals) / len(residuals)) ** 0.5
        folds.append({
            "fold": fold,
            "status": "success",
            "train_start": 0,
            "train_end": 9 + fold,
            "test_start": 20 + (fold - 1) * 2,
            "test_end": 21 + (fold - 1) * 2,
            "gap": 0,
            "n_train": 10 + fold,
            "n_test": 2,
            "metrics": {
                "mae": mae, "rmse": rmse, "mape": 10.0,
                "mase": mae / 2.0, "smape": 10.0,
                "rmsse": rmse / 3.0, "mape_valid_points": 2,
                "weighted_score": None,
            },
            "predictions": selected,
            "duration_ms": 1.0,
            "error": None,
            "mase_scale": 2.0,
            "rmsse_scale": 3.0,
        })
    all_residuals = [point["residual"] for point in points]
    mae = sum(abs(value) for value in all_residuals) / len(all_residuals)
    rmse = (sum(value**2 for value in all_residuals) / len(all_residuals)) ** 0.5
    return {
        "model_id": model_id,
        "model_name": model_id,
        "family_id": family,
        "metrics": {
            "mae": mae, "rmse": rmse, "mape": 10.0,
            "mase": mae / 2.0, "smape": 10.0,
            "rmsse": rmse / 3.0, "mape_valid_points": 4,
            "weighted_score": None,
        },
        "run_id": f"run-{model_id}",
        "parameter_signature": f"params-{model_id}",
        "oof_signature": f"oof-{model_id}",
        "params_source": "model_default",
        "tuning_id": None,
        "cohort_id": "cohort-1",
        "strategy": "expanding",
        "horizon": 2,
        "n_folds": 2,
        "gap": 0,
        "n_train": 12,
        "n_test": 4,
        "train_ratio": 0.75,
        "duration_ms": 2.0,
        "data_source": "session",
        "status": "success",
        "folds": folds,
        "oof_predictions": points,
        "warnings": [],
        "preprocessing": {"fit_policy": "none", "evaluation_scale": "value"},
        "params": {},
    }


def _comparison(backtests: dict[str, dict]) -> dict:
    ordered = sorted(backtests.values(), key=lambda item: item["metrics"]["rmse"])
    diagnostic_reports = _diagnostics(backtests)
    ranking = []
    for rank, item in enumerate(ordered, 1):
        ranking.append({
            "rank": rank,
            "model_id": item["model_id"],
            "model_name": item["model_name"],
            "family_id": item["family_id"],
            "applicability_level": "RECOMMENDED",
            "metrics": item["metrics"],
            "backtest_run_id": item["run_id"],
            "parameter_signature": item["parameter_signature"],
            "oof_signature": item["oof_signature"],
            "diagnostics": {
                "diagnostics_signature": diagnostic_reports[item["model_id"]]["diagnostics_signature"],
            },
        })
    return {
        "comparison_id": "comparison-1",
        "comparison_signature": "comparison-sha",
        "fingerprint": "fingerprint-1",
        "cohort_id": "cohort-1",
        "ranking": ranking,
    }


def _diagnostics(backtests: dict[str, dict]) -> dict[str, dict]:
    reports = {
        model_id: {
            "model_id": model_id,
            "backtest_run_id": item["run_id"],
            "parameter_signature": item["parameter_signature"],
            "residuals_signature": item["oof_signature"],
            "cohort_id": item["cohort_id"],
            "alpha": 0.05,
            "diagnostics": [],
        }
        for model_id, item in backtests.items()
    }
    for report in reports.values():
        report["diagnostics_signature"] = diagnostics_signature(report)
    return reports


def test_equal_weight_ensemble_is_evaluated_as_a_traceable_candidate():
    backtests = {
        "naive": _backtest("naive", "baselines", [8, 22, 28, 42]),
        "ets": _backtest("ets", "exponential_smoothing", [12, 18, 32, 38]),
    }
    result = evaluate_selection(
        comparison=_comparison(backtests),
        backtests=backtests,
        diagnostics=_diagnostics(backtests),
        policy=SelectionPolicy(
            min_oof_points=4,
            max_member_relative_gap=0.01,
            max_error_correlation=0.8,
            min_ensemble_relative_improvement=0.01,
            min_fold_win_rate=0.5,
        ),
    )

    ensemble = result["ensemble"]
    assert ensemble["status"] == "recommended"
    assert ensemble["member_ids"] == ["ets", "naive"]
    assert ensemble["weights"] == [0.5, 0.5]
    assert ensemble["backtest"]["metrics"]["rmse"] == pytest.approx(0.0)
    assert ensemble["backtest"]["oof_predictions"][0]["predicted"] == 10.0
    assert ensemble["backtest"]["oof_signature"]
    assert ensemble["diagnostics"]["diagnostics_signature"]
    assert result["recommended_candidate"]["kind"] == "ensemble"
    assert result["evaluation_contract"]["independent_holdout"] is False
    assert result["selection_signature"]


def test_correlation_is_only_an_eligibility_gate_and_never_a_recommendation_by_itself():
    backtests = {
        "naive": _backtest("naive", "baselines", [9, 18, 29, 38]),
        "ets": _backtest("ets", "exponential_smoothing", [9, 18, 29, 38]),
    }
    result = evaluate_selection(
        comparison=_comparison(backtests),
        backtests=backtests,
        diagnostics=_diagnostics(backtests),
        policy=SelectionPolicy(min_oof_points=4, max_error_correlation=0.8),
    )

    assert result["ensemble"]["status"] == "not_eligible"
    assert "корреляц" in " ".join(result["ensemble"]["reasons"]).lower()
    assert result["recommended_candidate"]["kind"] == "single"


def test_actual_oof_baseline_loss_is_used_instead_of_mase_threshold():
    baseline = _backtest("naive", "baselines", [10.5, 20.5, 30.5, 40.5])
    weak = _backtest("ets", "exponential_smoothing", [12, 22, 32, 42])
    # Deliberately claim an attractive MASE: selection must still use actual OOF loss.
    weak["metrics"]["mase"] = 0.2
    backtests = {"naive": baseline, "ets": weak}

    result = evaluate_selection(
        comparison=_comparison(backtests),
        backtests=backtests,
        diagnostics=_diagnostics(backtests),
        policy=SelectionPolicy(min_oof_points=4),
    )

    assert result["best_baseline"]["model_id"] == "naive"
    assert result["recommended_single"]["model_id"] == "naive"
    assert result["ensemble"]["status"] == "not_eligible"
    assert any("baseline" in reason.lower() for reason in result["ensemble"]["reasons"])


def test_baseline_tolerance_uses_oof_primary_loss_even_when_mase_is_above_one():
    baseline = _backtest("naive", "baselines", [10.5, 20.5, 30.5, 40.5])
    near = _backtest("ets", "exponential_smoothing", [10.52, 20.52, 30.52, 40.52])
    near["metrics"]["mase"] = 9.0
    result = evaluate_selection(
        comparison=_comparison({"naive": baseline, "ets": near}),
        backtests={"naive": baseline, "ets": near},
        diagnostics=_diagnostics({"naive": baseline, "ets": near}),
        policy=SelectionPolicy(min_oof_points=4, baseline_tolerance_ratio=1.05),
    )

    verdict = result["baseline_comparisons"]["ets"]
    assert verdict["metric"] == "rmse"
    assert verdict["loss_ratio"] == pytest.approx(1.04)
    assert verdict["eligible"] is True
    assert verdict["tolerance_ratio"] == 1.05

    far = _backtest("ets", "exponential_smoothing", [10.55, 20.55, 30.55, 40.55])
    far_result = evaluate_selection(
        comparison=_comparison({"naive": baseline, "ets": far}),
        backtests={"naive": baseline, "ets": far},
        diagnostics=_diagnostics({"naive": baseline, "ets": far}),
        policy=SelectionPolicy(min_oof_points=4, baseline_tolerance_ratio=1.05),
    )
    assert far_result["baseline_comparisons"]["ets"]["loss_ratio"] == pytest.approx(1.1)
    assert far_result["baseline_comparisons"]["ets"]["eligible"] is False


def test_selection_signature_is_order_independent_and_binds_policy():
    backtests = {
        "naive": _backtest("naive", "baselines", [8, 22, 28, 42]),
        "ets": _backtest("ets", "exponential_smoothing", [12, 18, 32, 38]),
    }
    comparison = _comparison(backtests)
    first = evaluate_selection(
        comparison=comparison,
        backtests=backtests,
        diagnostics=_diagnostics(backtests),
        policy=SelectionPolicy(min_oof_points=4),
    )
    second = evaluate_selection(
        comparison={**deepcopy(comparison), "ranking": list(reversed(comparison["ranking"]))},
        backtests={"ets": backtests["ets"], "naive": backtests["naive"]},
        diagnostics=_diagnostics(backtests),
        policy=SelectionPolicy(min_oof_points=4),
    )
    changed = evaluate_selection(
        comparison=comparison,
        backtests=backtests,
        diagnostics=_diagnostics(backtests),
        policy=SelectionPolicy(min_oof_points=4, max_error_correlation=0.7),
    )

    assert first["selection_signature"] == second["selection_signature"]
    assert first["selection_signature"] != changed["selection_signature"]


def test_selection_fails_closed_when_diagnostics_lineage_was_tampered():
    backtests = {
        "naive": _backtest("naive", "baselines", [8, 22, 28, 42]),
        "ets": _backtest("ets", "exponential_smoothing", [12, 18, 32, 38]),
    }
    diagnostics = _diagnostics(backtests)
    diagnostics["ets"]["backtest_run_id"] = "another-run"

    with pytest.raises(SelectionContractError, match="Lineage"):
        evaluate_selection(
            comparison=_comparison(backtests),
            backtests=backtests,
            diagnostics=diagnostics,
            policy=SelectionPolicy(min_oof_points=4),
        )
