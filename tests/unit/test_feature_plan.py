"""Task 126 -- Leakage-safe supervised FeaturePlan: plan construction tests.

The FeaturePlan is the platform-level, immutable description of every
supervised feature column with its leakage role:

- ``historic``     -- target-derived causal transforms (lags, rolling,
  differences).  They exist ONLY for the train slice and may never be
  materialized for the future (recursive strategies feed predictions back
  instead -- see RecursiveFeatureState).
- ``future_known`` -- deterministic calendar/trend/Fourier transforms of the
  timestamp axis.  Known in advance for any horizon by construction, so they
  may be materialized for train AND future.
- ``static``       -- row-constant exogenous attributes (entity, category).

Roles are derived from the authoritative ``known_in_advance`` catalog flag
that Task "Генерация признаков" already stores per feature, never guessed.
"""
from __future__ import annotations

import pytest

from apps.api.feature_plan import (
    FeaturePlan,
    FeaturePlanError,
    build_feature_plan_from_metadata,
    empty_feature_plan,
)


def _metadata(**overrides) -> dict:
    """A realistic preprocessing_feature_generation payload."""
    catalog = [
        {"name": "value_lag_1", "family": "lag", "lookback": 1, "known_in_advance": False},
        {"name": "value_lag_12", "family": "lag", "lookback": 12, "known_in_advance": False},
        {"name": "value_roll_mean_3", "family": "rolling", "lookback": 3, "known_in_advance": False},
        {"name": "value_roll_std_3", "family": "rolling", "lookback": 3, "known_in_advance": False},
        {"name": "value_diff_lagged_1", "family": "difference", "lookback": 2, "known_in_advance": False},
        {"name": "date_month_sin", "family": "calendar", "lookback": 0, "known_in_advance": True},
        {"name": "date_month_cos", "family": "calendar", "lookback": 0, "known_in_advance": True},
        {"name": "date_is_weekend", "family": "calendar", "lookback": 0, "known_in_advance": True},
        {"name": "time_idx", "family": "trend", "lookback": 0, "known_in_advance": True},
        {"name": "value_fourier_12_sin", "family": "fourier", "lookback": 0, "known_in_advance": True},
    ]
    metadata = {
        "kind": "feature_generation",
        "source_column": "value",
        "date_column": "date",
        "feature_names": [item["name"] for item in catalog],
        "feature_catalog": catalog,
        "max_lookback": 12,
        "causal": True,
        "target_shift": 1,
    }
    metadata.update(overrides)
    return metadata


class TestFeaturePlanConstruction:
    def test_roles_are_derived_from_known_in_advance_catalog(self):
        plan = build_feature_plan_from_metadata(_metadata())

        assert plan.historic_names() == [
            "value_lag_1", "value_lag_12", "value_roll_mean_3",
            "value_roll_std_3", "value_diff_lagged_1",
        ]
        assert plan.future_known_names() == [
            "date_month_sin", "date_month_cos", "date_is_weekend",
            "time_idx", "value_fourier_12_sin",
        ]
        assert plan.static_names() == []

    def test_every_feature_keeps_its_kind_and_source_column(self):
        plan = build_feature_plan_from_metadata(_metadata())
        by_name = plan.feature_by_name()

        assert by_name["value_lag_1"].kind == "lag"
        assert by_name["value_lag_1"].source_column == "value"
        assert by_name["value_lag_1"].lookback == 1
        assert by_name["value_roll_mean_3"].kind == "rolling"
        assert by_name["value_roll_std_3"].params["statistic"] == "std"
        assert by_name["date_month_sin"].kind == "calendar"
        assert by_name["time_idx"].kind == "trend"
        assert by_name["value_fourier_12_sin"].kind == "fourier"

    def test_rolling_name_without_parseable_window_is_rejected(self):
        metadata = _metadata()
        metadata["feature_catalog"][2]["name"] = "value_roll_mean_broken"

        with pytest.raises(FeaturePlanError, match="roll"):
            build_feature_plan_from_metadata(metadata)

    def test_explicit_static_role_is_preserved(self):
        metadata = _metadata()
        metadata["feature_catalog"].append(
            {"name": "region_id", "family": "exogenous",
             "lookback": 0, "known_in_advance": True, "static": True},
        )
        metadata["feature_names"].append("region_id")

        plan = build_feature_plan_from_metadata(metadata)

        assert plan.static_names() == ["region_id"]
        assert plan.future_known_names() and plan.historic_names()

    def test_duplicate_feature_names_are_rejected(self):
        metadata = _metadata()
        metadata["feature_catalog"].append(
            {"name": "value_lag_1", "family": "lag", "lookback": 2,
             "known_in_advance": False},
        )

        with pytest.raises(FeaturePlanError, match="уникальн"):
            build_feature_plan_from_metadata(metadata)

    def test_unknown_family_is_rejected_fail_closed(self):
        metadata = _metadata()
        metadata["feature_catalog"][0]["family"] = "quantum"

        with pytest.raises(FeaturePlanError, match="quantum"):
            build_feature_plan_from_metadata(metadata)

    def test_missing_known_in_advance_flag_is_rejected(self):
        metadata = _metadata()
        metadata["feature_catalog"][0].pop("known_in_advance")

        with pytest.raises(FeaturePlanError, match="known_in_advance"):
            build_feature_plan_from_metadata(metadata)

    def test_catalog_without_known_in_advance_authority_is_rejected(self):
        metadata = _metadata()
        metadata.pop("feature_catalog")

        with pytest.raises(FeaturePlanError, match="feature_catalog"):
            build_feature_plan_from_metadata(metadata)

    def test_stale_catalog_names_are_rejected(self):
        metadata = _metadata()
        metadata["feature_names"] = metadata["feature_names"][:-1]

        with pytest.raises(FeaturePlanError, match="feature_catalog"):
            build_feature_plan_from_metadata(metadata)


class TestFeaturePlanIdentity:
    def test_fingerprint_is_stable_and_order_insensitive_within_roles(self):
        first = build_feature_plan_from_metadata(_metadata())
        second = build_feature_plan_from_metadata(_metadata())

        assert first.fingerprint == second.fingerprint
        assert first.plan_id == second.plan_id
        assert first.plan_id.startswith("fp_")

    def test_different_feature_sets_produce_different_fingerprints(self):
        base = build_feature_plan_from_metadata(_metadata())
        trimmed = _metadata()
        trimmed["feature_catalog"] = trimmed["feature_catalog"][:-1]
        trimmed["feature_names"] = trimmed["feature_names"][:-1]
        other = build_feature_plan_from_metadata(trimmed)

        assert base.fingerprint != other.fingerprint

    def test_empty_plan_has_policy_none_and_stable_identity(self):
        plan = empty_feature_plan(source_column="value")

        assert plan.features == ()
        assert plan.policy == "none"
        assert plan.historic_names() == []
        assert plan.future_known_names() == []
        assert plan.static_names() == []
        assert plan.fingerprint

    def test_policy_defaults_to_recursive(self):
        plan = build_feature_plan_from_metadata(_metadata())

        assert plan.policy == "recursive"

    def test_policy_direct_is_explicit_only(self):
        plan = build_feature_plan_from_metadata(_metadata(), policy="direct")

        assert plan.policy == "direct"


class TestFeatureContract:
    def test_contract_binds_plan_identity_and_role_split(self):
        plan = build_feature_plan_from_metadata(_metadata())
        contract = plan.feature_contract()

        assert contract["policy"] == "recursive"
        assert contract["plan_id"] == plan.plan_id
        assert contract["fingerprint"] == plan.fingerprint
        assert contract["historic"] == plan.historic_names()
        assert contract["future_known"] == plan.future_known_names()
        assert contract["static"] == plan.static_names()
        assert contract["version"] == "feature-plan-v1"

    def test_empty_plan_contract_keeps_policy_none(self):
        contract = empty_feature_plan(source_column="value").feature_contract()

        assert contract["policy"] == "none"
        assert contract["historic"] == []
        assert contract["future_known"] == []
        assert contract["static"] == []

    def test_contract_is_json_canonical(self):
        import json

        plan = build_feature_plan_from_metadata(_metadata())
        contract = plan.feature_contract()
        encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"))

        assert plan.plan_id in encoded
        assert json.loads(encoded) == contract


class TestMaxLookback:
    def test_max_lookback_is_taken_from_historic_features(self):
        plan = build_feature_plan_from_metadata(_metadata())

        assert plan.max_lookback == 12

    def test_future_known_only_plan_has_zero_lookback(self):
        metadata = _metadata()
        metadata["feature_catalog"] = [
            item for item in metadata["feature_catalog"]
            if item["known_in_advance"]
        ]
        metadata["feature_names"] = [
            item["name"] for item in metadata["feature_catalog"]
        ]
        plan = build_feature_plan_from_metadata(metadata)

        assert plan.max_lookback == 0

    def test_lookback_above_catalog_value_is_rejected(self):
        metadata = _metadata()
        metadata["feature_catalog"][1]["lookback"] = 13
        metadata["max_lookback"] = 12

        with pytest.raises(FeaturePlanError, match="lookback"):
            build_feature_plan_from_metadata(metadata)
