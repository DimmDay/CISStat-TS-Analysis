"""Task 126 -- fold-local feature matrix invariants (leakage guards).

These tests encode the failure modes found in the rejected Task 126 attempt:

1. Oracle leakage  -- future target values must never appear inside historic
   feature rows, neither in train (rolling must not include y[t]) nor in any
   future payload (future historic features are simply NOT materialized).
2. Dead recursive path -- the train tail must remain reachable so a recursive
   strategy can extend historic features over the horizon step by step.
3. Global preprocessing fit -- imputer/scaler/one-hot statistics must be
   fitted per EDA fold on the train slice only.

Column channels: target-derived features (lag/rolling/difference) are always
recomputed causally from the fold train slice; every other feature column is
provided by the platform via ``feature_columns`` (materialized dataset
columns aligned with the passport series axis).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from apps.api.backtesting import BacktestFoldPlan
from apps.api.feature_plan import (
    FeaturePlan,
    FeaturePlanError,
    FoldFeatureMatrixBuilder,
    RecursiveFeatureState,
    build_feature_plan_from_metadata,
    empty_feature_plan,
)


def _plan(**overrides) -> FeaturePlan:
    catalog = [
        {"name": "value_lag_1", "family": "lag", "lookback": 1, "known_in_advance": False},
        {"name": "value_lag_2", "family": "lag", "lookback": 2, "known_in_advance": False},
        {"name": "value_roll_mean_3", "family": "rolling", "lookback": 3, "known_in_advance": False},
        {"name": "date_month_sin", "family": "calendar", "lookback": 0, "known_in_advance": True},
        {"name": "time_idx", "family": "trend", "lookback": 0, "known_in_advance": True},
    ]
    metadata = {
        "kind": "feature_generation",
        "source_column": "value",
        "date_column": "date",
        "feature_names": [item["name"] for item in catalog],
        "feature_catalog": catalog,
        "max_lookback": 3,
        "causal": True,
        "target_shift": 1,
    }
    metadata.update(overrides)
    return build_feature_plan_from_metadata(metadata)


def _series(n: int = 24) -> tuple[list[float], list[str]]:
    values = [float(index) + 1.0 for index in range(n)]  # y[t] = t + 1
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    return values, [value.isoformat() for value in dates]


def _columns(values: list[float], labels: list[str]) -> dict[str, list[float]]:
    dates = pd.Series(pd.to_datetime(labels))
    month = dates.dt.month.to_numpy(dtype=float) - 1.0
    return {
        "date_month_sin": list(np.sin(2.0 * np.pi * month / 12.0)),
        "time_idx": [float(index) for index in range(len(labels))],
    }


def _fold(train_end: int, horizon: int = 3, gap: int = 0) -> BacktestFoldPlan:
    """Expanding-origin fold: train [0..train_end], test directly afterwards."""
    train_indices = list(range(0, train_end + 1))
    test_indices = list(range(train_end + gap + 1, train_end + gap + 1 + horizon))
    return BacktestFoldPlan(
        fold=1, train_indices=train_indices, test_indices=test_indices, gap=gap,
    )


class TestCausalTrainMatrix:
    def test_lag_rows_match_shift_definition_inside_fold(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        matrix = builder.train_matrix()
        columns = matrix["columns"]
        rows = matrix["rows"]
        lag1 = [row[columns.index("value_lag_1")] for row in rows]

        # Train slice starts at index 3 (warm-up: rolling_3 needs shift(1)
        # plus 3 past points, lag_2 needs 2 -- the strictest wins);
        # lag_1 row for observation t must equal y[t-1] -- never y[t].
        for row_index, observation in enumerate(range(3, 16)):
            assert lag1[row_index] == values[observation - 1]

    def test_rolling_excludes_current_observation(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        matrix = builder.train_matrix()
        columns = matrix["columns"]
        rows = matrix["rows"]
        rolling = [row[columns.index("value_roll_mean_3")] for row in rows]

        for row_index, observation in enumerate(range(3, 16)):
            window = values[observation - 3 : observation]  # y[t-3..t-1]
            assert rolling[row_index] == pytest.approx(sum(window) / 3)

    def test_no_train_row_contains_its_own_target(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        matrix = builder.train_matrix()
        historic = [
            name for name in matrix["columns"] if name.startswith("value_")
        ]
        for row_index, observation in enumerate(range(3, 16)):
            for name in historic:
                value = matrix["rows"][row_index][matrix["columns"].index(name)]
                assert value != values[observation]

    def test_warmup_rows_are_dropped_not_imputed(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        matrix = builder.train_matrix()

        assert matrix["observation_indices"] == list(range(3, 16))
        assert all(
            math.isfinite(value)
            for row in matrix["rows"] for value in row
        )

    def test_target_column_is_excluded_from_feature_matrix(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        matrix = builder.train_matrix()

        assert "value" not in matrix["columns"]
        assert matrix["target"] == values[3:16]

    def test_train_matrix_cannot_contain_future_rows(self):
        values, labels = _series()
        fold = _fold(15)
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, fold, feature_columns=_columns(values, labels),
        )

        matrix = builder.train_matrix()

        assert matrix["observation_indices"][-1] == fold.train_indices[-1]
        assert len(matrix["rows"]) == len(fold.train_indices) - 3

    def test_train_matrix_stays_inside_fold_train_slice(self):
        """Oracle guard: the rejected implementation computed historic rows
        over the full series, letting test facts flow into train rows."""
        values, labels = _series()
        fold = _fold(15)
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, fold, feature_columns=_columns(values, labels),
        )

        matrix = builder.train_matrix()
        rows = matrix["rows"]

        assert rows[-1][0] == values[14]  # lag_1 of the last train point
        for row, observation in zip(rows, range(3, 16)):
            lag_values = row[:3]
            assert all(value < values[observation] + 1e-12 for value in lag_values)


class TestFuturePayload:
    def test_future_matrix_contains_only_future_known_columns(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        matrix = builder.future_matrix()
        columns = matrix["columns"]

        assert columns == ["date_month_sin", "time_idx"]
        assert len(matrix["rows"]) == 3  # gap(0) + horizon(3)

    def test_future_matrix_never_materializes_target_derived_features(self):
        """Oracle guard: the rejected implementation produced future lag rows
        from the real test window.  The platform contract is stricter -- the
        builder must not even carry a path that could do it."""
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        matrix = builder.future_matrix()

        assert not any(
            name.startswith("value_") for name in matrix["columns"]
        )

    def test_future_matrix_covers_gap_plus_horizon(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15, gap=2), feature_columns=_columns(values, labels),
        )

        matrix = builder.future_matrix()

        assert len(matrix["rows"]) == 5  # gap(2) + horizon(3)

    def test_future_matrix_slices_platform_columns_at_future_positions(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        matrix = builder.future_matrix()
        time_col = [row[matrix["columns"].index("time_idx")] for row in matrix["rows"]]

        assert time_col == [16.0, 17.0, 18.0]

    def test_future_matrix_is_empty_for_historic_only_plan(self):
        values, labels = _series()
        plan = _plan()
        historic_only = FeaturePlan(
            plan_id=plan.plan_id,
            features=tuple(spec for spec in plan.features if spec.role == "historic"),
            policy=plan.policy,
            fingerprint=plan.fingerprint,
            source_column=plan.source_column,
        )
        builder = FoldFeatureMatrixBuilder(historic_only).fit_fold(
            values, labels, _fold(15),
        )

        assert builder.future_matrix()["columns"] == []
        assert builder.future_matrix()["rows"] == []

    def test_missing_future_known_column_fails_closed(self):
        values, labels = _series()

        with pytest.raises(FeaturePlanError, match="time_idx"):
            FoldFeatureMatrixBuilder(_plan()).fit_fold(
                values, labels, _fold(15),
                feature_columns={"date_month_sin": [0.0] * len(labels)},
            )

    def test_nan_in_provided_column_fails_closed(self):
        values, labels = _series()
        columns = _columns(values, labels)
        columns["time_idx"][10] = math.nan

        with pytest.raises(FeaturePlanError, match="time_idx"):
            FoldFeatureMatrixBuilder(_plan()).fit_fold(
                values, labels, _fold(15), feature_columns=columns,
            )

    def test_provided_column_length_mismatch_fails_closed(self):
        values, labels = _series()
        columns = _columns(values, labels)
        columns["time_idx"] = columns["time_idx"][:-1]

        with pytest.raises(FeaturePlanError, match="time_idx"):
            FoldFeatureMatrixBuilder(_plan()).fit_fold(
                values, labels, _fold(15), feature_columns=columns,
            )


class TestRecursiveFeatureState:
    def test_state_starts_from_train_tail(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )
        state = builder.recursive_state()

        assert state.history()[-1] == values[15]
        assert state.columns() == [
            "value_lag_1", "value_lag_2", "value_roll_mean_3",
        ]

    def test_first_recursive_row_uses_train_tail_not_test_facts(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )
        state = builder.recursive_state()

        row = state.next_row(prediction=values[16])
        columns = state.columns()

        assert row[columns.index("value_lag_1")] == values[15]
        assert row[columns.index("value_lag_2")] == values[14]
        assert row[columns.index("value_roll_mean_3")] == pytest.approx(
            (values[13] + values[14] + values[15]) / 3,
        )

    def test_recursive_row_never_reads_actual_test_values(self):
        """The core recursive contract: step h+1 uses predictions, and the
        real y[16] supplied as a distractor must be ignored."""
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )
        state = builder.recursive_state()

        first = state.next_row(prediction=1000.0)
        second = state.next_row(prediction=1001.0)
        columns = state.columns()

        assert first[columns.index("value_lag_1")] == values[15]
        assert second[columns.index("value_lag_1")] == 1000.0
        assert second[columns.index("value_lag_1")] != values[16]

    def test_state_is_immutable_to_external_history_mutation(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )
        state = builder.recursive_state()

        history = state.history()
        history.append(-1.0)

        assert state.history()[-1] == values[15]

    def test_recursive_state_respects_exogenous_historic_columns(self):
        values, labels = _series()
        driver = [50.0 + 2 * index for index in range(24)]
        catalog = [
            {"name": "value_lag_1", "family": "lag", "lookback": 1, "known_in_advance": False},
            {"name": "driver", "family": "exogenous", "lookback": 0, "known_in_advance": False},
        ]
        plan = build_feature_plan_from_metadata({
            "kind": "feature_generation",
            "source_column": "value", "date_column": "date",
            "feature_names": [item["name"] for item in catalog],
            "feature_catalog": catalog,
            "max_lookback": 1, "causal": True, "target_shift": 1,
        })
        builder = FoldFeatureMatrixBuilder(plan).fit_fold(
            values, labels, _fold(15), feature_columns={"driver": driver},
        )
        state = builder.recursive_state()

        assert state.columns() == ["value_lag_1", "driver"]
        # Future exogenous values are unknown for a recursive strategy, so
        # the state carries NaN placeholders instead of the true series.
        row = state.next_row(prediction=1000.0)
        assert row[0] == values[15]
        assert math.isnan(row[1])


class TestFoldLocalPreprocessingFit:
    @staticmethod
    def _exogenous_plan() -> FeaturePlan:
        catalog = [
            {"name": "driver", "family": "exogenous",
             "lookback": 0, "known_in_advance": False},
            {"name": "region", "family": "exogenous",
             "lookback": 0, "known_in_advance": True},
        ]
        return build_feature_plan_from_metadata({
            "kind": "feature_generation",
            "source_column": "value", "date_column": "date",
            "feature_names": [item["name"] for item in catalog],
            "feature_catalog": catalog,
            "max_lookback": 0, "causal": True, "target_shift": 1,
        })

    def test_numeric_exogenous_is_imputed_with_train_median_per_fold(self):
        values, labels = _series()
        driver = [10.0 + index for index in range(24)]
        driver[10] = math.nan  # inside fold-1 train slice
        driver[20] = math.nan  # inside fold-2 train slice only
        plan = self._exogenous_plan()

        first = FoldFeatureMatrixBuilder(plan).fit_fold(
            values, labels, _fold(15), feature_columns={"driver": driver},
        )
        second = FoldFeatureMatrixBuilder(plan).fit_fold(
            values, labels, _fold(20), feature_columns={"driver": driver},
        )

        first_median = float(np.nanmedian(driver[:16]))
        second_median = float(np.nanmedian(driver[:21]))
        assert first_median != second_median

        first_matrix = first.train_matrix()
        second_matrix = second.train_matrix()
        assert first_matrix["rows"][10][first_matrix["columns"].index("driver")] == pytest.approx(first_median)
        assert second_matrix["rows"][20][second_matrix["columns"].index("driver")] == pytest.approx(second_median)

    def test_scaler_is_fit_on_train_slice_of_this_fold_only(self):
        values, labels = _series()
        driver = [10.0 + index for index in range(24)]
        plan = self._exogenous_plan()

        builder = FoldFeatureMatrixBuilder(
            plan, scale_exogenous=True,
        ).fit_fold(values, labels, _fold(15), feature_columns={"driver": driver})

        matrix = builder.train_matrix()
        column = [row[matrix["columns"].index("driver")] for row in matrix["rows"]]

        train_part = driver[:16]
        expected_mean = float(np.mean(train_part))
        expected_std = float(np.std(train_part, ddof=0))
        transformed = (np.asarray(driver[:16]) - expected_mean) / expected_std
        assert np.allclose(column, transformed, atol=1e-9)

    def test_one_hot_encoder_is_fit_on_train_categories_of_this_fold(self):
        values, labels = _series()
        # 'region' is declared known_in_advance, but only its train slice may
        # shape the encoder: fold-1 train never sees 'east'.
        region = ["north"] * 12 + ["south"] * 6 + ["east"] * 6
        plan = self._exogenous_plan()

        first = FoldFeatureMatrixBuilder(plan).fit_fold(
            values, labels, _fold(15),
            feature_columns={"region": region, "driver": [1.0] * 24},
        )

        first_matrix = first.train_matrix()
        assert first_matrix["columns"] == ["driver", "region=north", "region=south"]
        north_index = first_matrix["columns"].index("region=north")
        assert all(row[north_index] == 1.0 for row in first_matrix["rows"][:12])
        assert all(row[north_index] == 0.0 for row in first_matrix["rows"][12:])

    def test_future_known_categorical_uses_platform_future_values(self):
        values, labels = _series()
        region = ["north"] * 12 + ["south"] * 6 + ["east"] * 6
        plan = self._exogenous_plan()

        first = FoldFeatureMatrixBuilder(plan).fit_fold(
            values, labels, _fold(15),
            feature_columns={"region": region, "driver": [1.0] * 24},
        )

        future_matrix = first.future_matrix()
        assert future_matrix["columns"] == ["region=north", "region=south"]
        assert future_matrix["rows"][0][future_matrix["columns"].index("region=south")] == 1.0

    def test_second_fold_encoder_learns_categories_absent_in_first_fold(self):
        values, labels = _series()
        region = ["north"] * 12 + ["south"] * 6 + ["east"] * 6
        plan = self._exogenous_plan()

        second = FoldFeatureMatrixBuilder(plan).fit_fold(
            values, labels, _fold(20, horizon=3),
            feature_columns={"region": region, "driver": [1.0] * 24},
        )

        assert second.train_matrix()["columns"] == [
            "driver", "region=north", "region=south", "region=east",
        ]

    def test_fold_statistics_are_not_shared_between_folds(self):
        values, labels = _series()
        driver = [10.0 + index for index in range(24)]
        driver[10] = math.nan
        plan = self._exogenous_plan()

        first = FoldFeatureMatrixBuilder(plan).fit_fold(
            values, labels, _fold(15), feature_columns={"driver": driver},
        )
        second = FoldFeatureMatrixBuilder(plan).fit_fold(
            values, labels, _fold(20), feature_columns={"driver": driver},
        )

        assert first.statistics()["imputer"] is not None
        assert first.statistics()["imputer"] != second.statistics()["imputer"]

    def test_static_column_must_be_constant_within_train_slice(self):
        values, labels = _series()
        catalog = [
            {"name": "region", "family": "exogenous", "lookback": 0,
             "known_in_advance": True, "static": True},
        ]
        plan = build_feature_plan_from_metadata({
            "kind": "feature_generation",
            "source_column": "value", "date_column": "date",
            "feature_names": ["region"], "feature_catalog": catalog,
            "max_lookback": 0, "causal": True, "target_shift": 1,
        })

        with pytest.raises(FeaturePlanError, match="static"):
            FoldFeatureMatrixBuilder(plan).fit_fold(
                values, labels, _fold(15),
                feature_columns={"region": ["north", "south"] * 12},
            )


class TestMatrixLineage:
    def test_matrix_hash_is_stable_and_fold_specific(self):
        values, labels = _series()
        first = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )
        second = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(20), feature_columns=_columns(values, labels),
        )

        assert first.matrix_hash()
        assert first.matrix_hash() != second.matrix_hash()
        assert first.matrix_hash() == FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        ).matrix_hash()

    def test_matrix_hash_changes_when_train_data_changes(self):
        values, labels = _series()
        base = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )
        shifted = list(values)
        shifted[5] += 1.0
        other = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            shifted, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        assert base.matrix_hash() != other.matrix_hash()

    def test_lineage_record_binds_plan_fold_and_matrix(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )

        lineage = builder.lineage_record(fold=1)

        assert lineage["fold"] == 1
        assert lineage["plan_id"].startswith("fp_")
        assert lineage["matrix_hash"] == builder.matrix_hash()
        assert lineage["columns"] == builder.train_matrix()["columns"]
        assert lineage["future_known_columns"] == builder.future_matrix()["columns"]
        assert lineage["fit_policy"] == "per_train_fold"

    def test_importance_binding_rejects_foreign_columns(self):
        from apps.api.feature_plan import bind_feature_importance

        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(_plan()).fit_fold(
            values, labels, _fold(15), feature_columns=_columns(values, labels),
        )
        lineage = builder.lineage_record(fold=1)

        bound = bind_feature_importance(
            lineage,
            [{"feature_name": "value_lag_1", "importance": 0.7}],
        )
        assert bound["matrix_hash"] == lineage["matrix_hash"]

        with pytest.raises(FeaturePlanError, match="oracle_feature"):
            bind_feature_importance(
                lineage,
                [{"feature_name": "oracle_feature", "importance": 0.9}],
            )


class TestEmptyPlan:
    def test_empty_plan_builder_yields_empty_matrices(self):
        values, labels = _series()
        builder = FoldFeatureMatrixBuilder(
            empty_feature_plan(source_column="value"),
        ).fit_fold(values, labels, _fold(15))

        assert builder.train_matrix()["columns"] == []
        assert builder.future_matrix()["columns"] == []
        assert builder.recursive_state() is None
        assert builder.matrix_hash() is None
