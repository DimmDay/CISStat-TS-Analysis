"""Regression contract for traceable comparison in modeling.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "rules" / "modeling.yaml"


def _comparison_stage() -> dict:
    document = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    return next(
        stage for stage in document["pipeline"]["stages"]
        if stage["id"] == "comparison"
    )


def test_comparison_spec_requires_exact_oof_and_current_diagnostics() -> None:
    stage = _comparison_stage()
    assert stage["inputs"] == [
        "comparable_backtests",
        "current_oof_diagnostic_reports",
        "baseline_backtest",
    ]
    assert stage["outputs"] == [
        "traceable_ranking",
        "fold_stability",
        "oof_error_correlation",
    ]
    assert stage["rules"]["require_exact_oof_alignment"] is True
    assert stage["rules"]["require_current_diagnostics"] is True
    assert stage["rules"]["require_baseline_in_pool"] is True


def test_diagnostics_are_separate_evidence_not_an_arbitrary_score_bonus() -> None:
    rules = _comparison_stage()["rules"]
    assert rules["rank_by"] == "weighted_score"
    assert rules["diagnostics_in_score"] is False
    assert rules["diagnostics_policy"] == "current_oof_report_required_not_scored"
    assert "diagnostics_bonus" not in rules
    assert rules["baseline_policy"] == "best_actual_aligned_oof_baseline"
    assert rules["baseline_metric"] == "rmse"
    assert rules["baseline_tolerance_ratio"] == 1.05
    assert rules["mase_role"] == "scale_free_metric_not_baseline_gate"
