from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.eda_stationarity import build_eda_stationarity
from apps.api.schemas import DatasetEdaStationarityResponse


def test_adapter_sorts_regular_time_axis_and_builds_all_overview_payloads():
    rng = np.random.default_rng(3)
    size = 180
    dates = pd.date_range("2022-01-01", periods=size, freq="D")
    frame = pd.DataFrame({"Date": dates[::-1], "Price": rng.normal(size=size)[::-1]})

    result = build_eda_stationarity(frame, "Price", alpha=0.05, rolling_window=12)
    response = DatasetEdaStationarityResponse(**result)

    assert response.applicable is True
    assert response.order_source == "time_column"
    assert response.order_column == "Date"
    assert response.frequency == "D"
    assert response.consensus == "stationary"
    assert {item.id for item in response.tests} == {
        "adf_level", "adf_trend", "kpss_level", "kpss_trend", "pp", "zivot_andrews",
    }
    assert response.rolling[0].label.startswith("2022-01-01")
    assert response.rolling[-1].label.startswith("2022-06-29")
    assert any(point.rolling_mean is not None for point in response.rolling)
    assert response.recommendations


def test_adapter_refuses_irregular_grid_panel_duplicates_and_missing_values():
    irregular_dates = pd.date_range("2024-01-01", periods=80, freq="D").delete(12)
    irregular = build_eda_stationarity(pd.DataFrame({
        "Date": irregular_dates,
        "Price": np.arange(len(irregular_dates), dtype=float),
    }), "Price")
    assert irregular["applicable"] is False
    assert "нерегуляр" in irregular["reason"].lower()

    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    panel = build_eda_stationarity(pd.DataFrame({
        "Date": np.repeat(dates, 2),
        "Price": np.arange(80, dtype=float),
    }), "Price")
    assert panel["applicable"] is False
    assert "панель" in panel["reason"].lower()

    values = np.arange(80, dtype=float)
    values[10] = np.nan
    missing = build_eda_stationarity(pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=80, freq="D"),
        "Price": values,
    }), "Price")
    assert missing["applicable"] is False
    assert missing["missing_count"] == 1


def test_adapter_uses_row_order_with_explicit_warning_when_time_axis_is_unknown():
    rng = np.random.default_rng(21)
    result = build_eda_stationarity(pd.DataFrame({
        "Price": rng.normal(size=120),
        "Volume": rng.normal(size=120),
    }), "Price")

    assert result["applicable"] is True
    assert result["order_source"] == "row_order"
    assert result["order_column"] is None
    assert "поряд" in result["order_warning"].lower()
    assert result["rolling"][0]["label"] is None
