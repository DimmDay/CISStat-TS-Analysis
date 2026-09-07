"""Task 126 -- Prophet regressor contract (future-known and static only).

Task 124 deliberately shipped Prophet without custom regressors and left the
regressor path to Task 126.  The adapter itself stays role-agnostic: the
platform (backtesting + FeaturePlan) guarantees by construction that only
future_known/static columns enter ``train_features``/``future_features``.
Historic target-derived features never reach this module -- that guarantee is
enforced in tests/unit/test_feature_plan_backtest.py.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from apps.api.model_impls.prophet import _prophet_fit_predict


def _monthly_series(n: int = 48) -> tuple[list[float], list[str]]:
    values = [
        100.0 + 0.5 * step + 8.0 * math.sin(2.0 * math.pi * step / 12.0)
        for step in range(n)
    ]
    dates = pd.date_range("2019-01-01", periods=n, freq="MS")
    return values, [value.isoformat() for value in dates]


class TestRegressorContract:
    def test_regressor_columns_flow_into_fit_and_predict(self):
        values, timestamps = _monthly_series(48)
        train_timestamps, future_timestamps = timestamps[:42], timestamps[42:]

        forecast, lower, upper = _prophet_fit_predict(
            y_train=values[:42], horizon=6,
            train_timestamps=train_timestamps, future_timestamps=future_timestamps,
            train_features={"price": [1.0 + 0.01 * step for step in range(42)]},
            future_features={"price": [1.42, 1.43, 1.44, 1.45, 1.46, 1.47]},
        )

        assert len(forecast) == len(lower) == len(upper) == 6
        assert all(math.isfinite(value) for value in forecast)

    def test_train_regressor_length_mismatch_is_rejected(self):
        values, timestamps = _monthly_series(48)

        with pytest.raises(ValueError, match="train length"):
            _prophet_fit_predict(
                y_train=values[:42], horizon=6,
                train_timestamps=timestamps[:42], future_timestamps=timestamps[42:],
                train_features={"price": [1.0] * 41},
                future_features={"price": [1.0] * 6},
            )

    def test_future_regressor_length_must_cover_horizon(self):
        values, timestamps = _monthly_series(48)

        with pytest.raises(ValueError, match="future length"):
            _prophet_fit_predict(
                y_train=values[:42], horizon=6,
                train_timestamps=timestamps[:42], future_timestamps=timestamps[42:],
                train_features={"price": [1.0] * 42},
                future_features={"price": [1.0] * 5},
            )

    def test_future_without_train_counterpart_is_rejected(self):
        values, timestamps = _monthly_series(48)

        with pytest.raises(ValueError, match="train_features"):
            _prophet_fit_predict(
                y_train=values[:42], horizon=6,
                train_timestamps=timestamps[:42], future_timestamps=timestamps[42:],
                future_features={"price": [1.0] * 6},
            )

    def test_nan_regressor_is_rejected_fail_closed(self):
        values, timestamps = _monthly_series(48)
        train_price = [1.0] * 42
        train_price[7] = math.nan

        with pytest.raises(ValueError, match="NaN/Inf"):
            _prophet_fit_predict(
                y_train=values[:42], horizon=6,
                train_timestamps=timestamps[:42], future_timestamps=timestamps[42:],
                train_features={"price": train_price},
                future_features={"price": [1.0] * 6},
            )

    def test_regressor_without_future_values_is_rejected(self):
        values, timestamps = _monthly_series(48)

        with pytest.raises(ValueError, match="future_features"):
            _prophet_fit_predict(
                y_train=values[:42], horizon=6,
                train_timestamps=timestamps[:42], future_timestamps=timestamps[42:],
                train_features={"price": [1.0] * 42},
            )


class TestBackwardCompatibility:
    def test_no_features_keeps_task_124_behavior(self):
        values, timestamps = _monthly_series(48)

        forecast, lower, upper = _prophet_fit_predict(
            y_train=values[:42], horizon=6,
            train_timestamps=timestamps[:42], future_timestamps=timestamps[42:],
        )

        assert len(forecast) == 6
        assert all(lo <= point <= hi for lo, point, hi in zip(lower, forecast, upper))
