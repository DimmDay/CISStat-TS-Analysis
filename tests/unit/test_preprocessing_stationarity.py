from __future__ import annotations

import numpy as np
import pytest

from app.preprocessing.stationarity import apply_stationarity_series


def test_integer_differences_use_order_not_lag_and_report_lost_prefix():
    values = np.array([1.0, 2.0, 4.0, 7.0, 11.0])

    first, first_meta = apply_stationarity_series(values, "first_difference")
    second, second_meta = apply_stationarity_series(values, "second_difference")

    np.testing.assert_allclose(first, [1.0, 2.0, 3.0, 4.0])
    np.testing.assert_allclose(second, [1.0, 1.0, 1.0])
    assert first_meta["regular_order"] == 1
    assert first_meta["lost_observations"] == 1
    assert second_meta["regular_order"] == 2
    assert second_meta["lost_observations"] == 2


def test_seasonal_and_combined_differences_have_exact_operator_contract():
    values = np.array([1.0, 2.0, 4.0, 7.0, 11.0])

    seasonal, seasonal_meta = apply_stationarity_series(
        values, "seasonal_difference", seasonal_period=2,
    )
    combined, combined_meta = apply_stationarity_series(
        values, "combined_difference", seasonal_period=2,
    )

    np.testing.assert_allclose(seasonal, [3.0, 5.0, 7.0])
    np.testing.assert_allclose(combined, [2.0, 2.0])
    assert seasonal_meta["seasonal_order"] == 1
    assert seasonal_meta["lost_observations"] == 2
    assert combined_meta["regular_order"] == 1
    assert combined_meta["seasonal_order"] == 1
    assert combined_meta["lost_observations"] == 3


def test_log_difference_validates_domain_and_is_reversible_from_anchor():
    values = np.exp(np.array([1.0, 1.2, 1.5, 1.9]))
    transformed, metadata = apply_stationarity_series(values, "log_difference")

    np.testing.assert_allclose(transformed, [0.2, 0.3, 0.4])
    assert metadata["domain_transform"] == "log"
    assert metadata["inverse_supported"] is True
    assert metadata["history_tail"] == pytest.approx([values[-1]])

    with pytest.raises(ValueError, match="положитель"):
        apply_stationarity_series([1.0, 0.0, 2.0], "log_difference")


def test_linear_detrend_is_explicitly_offline_and_preserves_all_rows():
    values = 2.0 + 3.0 * np.arange(30, dtype=float)
    transformed, metadata = apply_stationarity_series(values, "linear_detrend")

    np.testing.assert_allclose(transformed, np.zeros(30), atol=1e-10)
    assert metadata["causal"] is False
    assert metadata["modeling_safe"] is False
    assert metadata["lost_observations"] == 0
    assert metadata["trend_intercept"] == pytest.approx(2.0)
    assert metadata["trend_slope"] == pytest.approx(3.0)


def test_invalid_input_and_period_are_rejected_without_hidden_cleaning():
    with pytest.raises(ValueError, match="конечн"):
        apply_stationarity_series([1.0, np.nan, 2.0], "first_difference")
    with pytest.raises(ValueError, match="период"):
        apply_stationarity_series(np.arange(20.0), "seasonal_difference", seasonal_period=1)
    with pytest.raises(ValueError, match="наблюден"):
        apply_stationarity_series(np.arange(10.0), "seasonal_difference", seasonal_period=10)
