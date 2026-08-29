from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.eda_seasonality import build_eda_seasonality
from apps.api.schemas import DatasetEdaSeasonalityResponse


def test_adapter_sorts_regular_time_axis_and_matches_response_schema():
    size = 120
    time = np.arange(size, dtype=float)
    frame = pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=size, freq="D")[::-1],
        "Price": np.sin(2 * np.pi * time / 12)[::-1],
    })

    result = build_eda_seasonality(frame, "Price", min_cycles=3, max_candidates=5)
    response = DatasetEdaSeasonalityResponse(**result)

    assert response.applicable is True
    assert response.order_source == "time_column"
    assert response.order_column == "Date"
    assert response.frequency == "D"
    assert any(abs(item.period - 12) < 0.7 for item in response.candidates)


def test_adapter_refuses_irregular_grid_and_panel_duplicates():
    irregular_dates = pd.date_range("2024-01-01", periods=50, freq="D").delete(10)
    irregular = build_eda_seasonality(pd.DataFrame({
        "Date": irregular_dates,
        "Price": np.arange(len(irregular_dates), dtype=float),
    }), "Price")
    assert irregular["applicable"] is False
    assert "нерегуляр" in irregular["reason"].lower()

    dates = pd.date_range("2024-01-01", periods=24, freq="MS")
    panel = build_eda_seasonality(pd.DataFrame({
        "Date": np.repeat(dates, 2),
        "Price": np.arange(48, dtype=float),
    }), "Price")
    assert panel["applicable"] is False
    assert "панель" in panel["reason"].lower()
