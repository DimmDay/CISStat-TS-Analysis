from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.preprocessing.smoothing import apply_smoothing_series
from apps.api.preprocessing_smoothing import (
    build_smoothing_profile,
    preview_smoothing_transformation,
)


def _noisy_frame(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    x = np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "Date": pd.date_range("2016-01-01", periods=n, freq="MS"),
            "Price": 10 + 0.08 * x + 1.5 * np.sin(2 * np.pi * x / 12) + rng.normal(0, 1.8, n),
        }
    )


@pytest.mark.parametrize("method", ["sma", "ema", "wma", "median"])
def test_causal_methods_do_not_change_past_when_future_changes(method: str):
    original = np.arange(1.0, 21.0)
    changed = original.copy()
    changed[10:] = 10_000

    first, first_meta = apply_smoothing_series(original, method, window=5, span=5)
    second, second_meta = apply_smoothing_series(changed, method, window=5, span=5)

    np.testing.assert_allclose(first[:10], second[:10])
    assert first_meta["causal"] is True
    assert second_meta["modeling_safe"] is True


def test_wma_start_uses_only_available_history_instead_of_backfilling_future_window():
    smoothed, _ = apply_smoothing_series(np.array([1.0, 2.0, 3.0, 4.0]), "wma", window=3)
    np.testing.assert_allclose(smoothed, [1.0, 5 / 3, 14 / 6, 20 / 6])


@pytest.mark.parametrize("method", ["savgol", "lowess"])
def test_offline_methods_are_explicitly_marked_non_causal(method: str):
    values = np.sin(np.linspace(0, 4 * np.pi, 41))
    smoothed, metadata = apply_smoothing_series(
        values, method, window=7, polyorder=2, frac=0.25
    )
    assert np.isfinite(smoothed).all()
    assert metadata["causal"] is False
    assert metadata["modeling_safe"] is False


def test_profile_returns_scale_free_noise_diagnostics_and_visual_data():
    result = build_smoothing_profile(_noisy_frame(), "Price")

    assert result["applicable"] is True
    assert result["selected_method"] == "ema"
    assert result["diagnostics_before"]["normalized_roughness"] is not None
    assert result["diagnostics_before"]["high_frequency_power_share"] is not None
    assert result["diagnostics_after"] is not None
    assert {item["method"] for item in result["candidates"]} == {
        "sma", "ema", "wma", "median", "savgol", "lowess"
    }
    assert len(result["points"]) == 120
    assert result["spectrum"]
    assert result["residual_acf"]


def test_profile_rejects_missing_constant_and_duplicate_time_axis_honestly():
    missing = _noisy_frame()
    missing.loc[2, "Price"] = np.nan
    assert "пропуск" in build_smoothing_profile(missing, "Price")["reason"].lower()

    constant = _noisy_frame()
    constant["Price"] = 7.0
    assert "констант" in build_smoothing_profile(constant, "Price")["reason"].lower()

    duplicate = _noisy_frame()
    duplicate.loc[1, "Date"] = duplicate.loc[0, "Date"]
    result = build_smoothing_profile(duplicate, "Price")
    assert result["applicable"] is False
    assert "несколько значений" in result["reason"].lower()


def test_preview_adds_column_without_mutating_source_and_requires_opt_in_for_offline():
    source = _noisy_frame()
    before = source.copy(deep=True)
    transformed, summary = preview_smoothing_transformation(
        source, "Price", "ema", window=7, span=7, frac=0.2, polyorder=2,
        confirm_non_causal=False,
    )

    pd.testing.assert_frame_equal(source, before)
    assert summary["output_column"] == "Price_ema"
    assert summary["metadata"]["causal"] is True
    assert summary["metadata"]["inverse_supported"] is False
    assert transformed["Price_ema"].notna().all()

    with pytest.raises(ValueError, match="некаузаль"):
        preview_smoothing_transformation(
            source, "Price", "lowess", window=7, span=7, frac=0.2,
            polyorder=2, confirm_non_causal=False,
        )

