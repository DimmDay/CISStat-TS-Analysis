"""Regression contract for traceable selection in modeling.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "rules" / "modeling.yaml"


def _document() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_selection_uses_primary_oof_loss_and_actual_baseline() -> None:
    document = _document()
    stage = next(item for item in document["pipeline"]["stages"] if item["id"] == "selection")

    assert stage["rules"]["single_rank_by"] == "primary_metric_oof_loss"
    assert stage["rules"]["primary_metric"] == "rmse"
    assert stage["rules"]["baseline_reference"] == "best_actual_oof_baseline"
    assert stage["rules"]["require_selection_signature"] is True
    assert stage["rules"]["independent_holdout"] is False
    assert stage["rules"]["require_selection_bias_acknowledgement"] is True


def test_ensemble_trigger_is_only_a_gate_and_gain_is_verified() -> None:
    ensemble = _document()["ensemble"]
    trigger = ensemble["verified_trigger"]

    assert ensemble["production_strategy"] == "simple_average"
    assert trigger["correlation_role"] == "eligibility_gate_only"
    assert trigger["evaluation_source"] == "exact_aligned_selection_oof"
    assert trigger["recommend_if"]["min_relative_improvement_vs_best_single"] == 0.01
    assert trigger["recommend_if"]["min_fold_win_rate"] == 0.5
    assert trigger["recommend_if"]["must_not_lose_to_best_actual_baseline"] is True
    assert set(trigger["statuses"]) == {"not_eligible", "tested_no_gain", "recommended"}

