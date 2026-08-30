from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.eda_structural_breaks import build_eda_structural_breaks
from apps.api.schemas import DatasetEdaStructuralBreaksResponse


def test_adapter_orders_dates_and_builds_all_visualization_payloads():
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=180, freq="D")
    values = np.r_[rng.normal(0, 0.2, 90), rng.normal(3, 0.2, 90)]
    order = np.r_[np.arange(90, 180), np.arange(0, 90)]
    frame = pd.DataFrame({"Date": dates[order], "Price": values[order]})

    response = DatasetEdaStructuralBreaksResponse(**build_eda_structural_breaks(
        frame,
        "Price",
        alpha=0.05,
        min_segment=20,
        penalty_multiplier=2.0,
    ))

    assert response.applicable is True
    assert response.order_source == "time_column"
    assert response.order_column == "Date"
    assert response.frequency == "D"
    assert response.series
    assert response.cusum_path
    assert response.sensitivity
    assert response.segments
    assert response.candidates
    assert response.candidates[0].label is not None


def test_adapter_refuses_irregular_and_panel_axes_without_implicit_aggregation():
    irregular = pd.DataFrame({
        "Date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-05"] * 25),
        "Price": np.arange(75, dtype=float),
    })
    # Уникальные нерегулярные даты, чтобы случай не классифицировался как панель.
    irregular["Date"] = pd.Timestamp("2024-01-01") + pd.to_timedelta(
        np.cumsum(np.tile([1, 1, 3], 25)), unit="D"
    )
    irregular_result = build_eda_structural_breaks(irregular, "Price")
    assert irregular_result["applicable"] is False
    assert "нерегуляр" in irregular_result["reason"].lower()

    panel = pd.DataFrame({
        "Date": np.repeat(pd.date_range("2024-01-01", periods=40, freq="D"), 2),
        "Price": np.arange(80, dtype=float),
    })
    panel_result = build_eda_structural_breaks(panel, "Price")
    assert panel_result["applicable"] is False
    assert "панель" in panel_result["reason"].lower()

