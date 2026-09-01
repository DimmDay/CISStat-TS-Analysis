from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.preprocessing_decomposition import (
    build_preprocessing_decomposition,
    preview_decomposition_outputs,
)
from apps.api.decomposition_data import _resolve_period


def _monthly_frame(n: int = 72) -> pd.DataFrame:
    index = np.arange(n, dtype=float)
    return pd.DataFrame({
        "Date": pd.date_range("2019-01-01", periods=n, freq="MS"),
        "Price": 100 + 0.4 * index + 12 * np.sin(2 * np.pi * index / 12),
        "Volume": 1000 + index,
    })


def test_profile_returns_real_stl_components_strengths_and_residual_acf():
    result = build_preprocessing_decomposition(_monthly_frame(), "Price", period=None, robust=True)

    assert result["applicable"] is True
    assert result["date_column"] == "Date"
    assert result["period"] == 12
    assert result["method"] == "STL"
    assert len(result["points"]) == 72
    assert set(result["points"][0]) == {"x", "observed", "trend", "seasonal", "resid"}
    assert len(result["seasonal_pattern"]) == 12
    assert result["residual_acf"][0] == {"lag": 0, "value": pytest.approx(1.0)}
    assert 0 <= result["trend_strength"] <= 1
    assert 0 <= result["seasonal_strength"] <= 1
    assert result["seasonal_strength"] > 0.8


def test_profile_rejects_irregular_panel_and_missing_series_honestly():
    irregular = _monthly_frame().drop(index=10).reset_index(drop=True)
    assert build_preprocessing_decomposition(irregular, "Price")["applicable"] is False

    panel = pd.concat([_monthly_frame(24).assign(Country="A"), _monthly_frame(24).assign(Country="B")])
    panel_result = build_preprocessing_decomposition(panel, "Price")
    assert panel_result["applicable"] is False
    assert "панель" in panel_result["reason"].lower()

    missing = _monthly_frame()
    missing.loc[5, "Price"] = np.nan
    missing_result = build_preprocessing_decomposition(missing, "Price")
    assert missing_result["applicable"] is False
    assert "пропуск" in missing_result["reason"].lower()


def test_manual_period_is_validated_against_two_complete_cycles():
    result = build_preprocessing_decomposition(_monthly_frame(24), "Price", period=13)
    assert result["applicable"] is False
    assert "26" in result["reason"]


def test_current_pandas_end_anchored_frequency_aliases_are_supported():
    assert _resolve_period("ME") == (12, "месячная (годовая сезонность)")
    assert _resolve_period("QE-DEC") == (4, "квартальная (годовая сезонность)")


def test_preview_adds_requested_outputs_without_mutating_source():
    source = _monthly_frame()
    source_before = source.copy(deep=True)

    corrected, summary = preview_decomposition_outputs(
        source,
        column="Price",
        period=12,
        robust=True,
        outputs=["components", "seasonally_adjusted", "detrended"],
    )

    pd.testing.assert_frame_equal(source, source_before)
    assert len(corrected) == len(source)
    assert summary["added_columns"] == [
        "Price_trend", "Price_seasonal", "Price_resid",
        "Price_seasonally_adjusted", "Price_detrended",
    ]
    np.testing.assert_allclose(
        corrected["Price"],
        corrected["Price_trend"] + corrected["Price_seasonal"] + corrected["Price_resid"],
        atol=1e-7,
    )
    np.testing.assert_allclose(
        corrected["Price_seasonally_adjusted"],
        corrected["Price"] - corrected["Price_seasonal"],
        atol=1e-7,
    )


def test_preview_rejects_existing_output_column_and_unknown_output():
    frame = _monthly_frame()
    frame["Price_trend"] = 0.0
    with pytest.raises(ValueError, match="уже существует"):
        preview_decomposition_outputs(frame, "Price", 12, True, ["components"])
    with pytest.raises(ValueError, match="Неподдерживаемые"):
        preview_decomposition_outputs(_monthly_frame(), "Price", 12, True, ["mystery"])
