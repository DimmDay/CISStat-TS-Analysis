"""API-адаптер графиков и тестов EDA «Распределение»."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.eda.distributions import analyze_distribution
from apps.api.chart_data import build_histogram, build_kde


def build_eda_distribution(
    df: pd.DataFrame,
    column: str,
    alpha: float = 0.05,
    bins: int = 20,
) -> dict[str, Any]:
    """Строит один ответ для всех представлений остановки."""
    series = pd.to_numeric(df[column], errors="coerce")
    result = analyze_distribution(series, alpha=alpha)
    histogram: list[dict[str, Any]] = []
    density: list[dict[str, float]] = []

    if result["applicable"]:
        values = series.astype(float)
        n = len(values)
        mean = float(result["mean"])
        std = float(result["std"])
        for item in build_histogram(values, nbins=bins):
            width = float(item["x1"] - item["x0"])
            histogram.append({
                **item,
                "density": float(item["count"] / (n * width)) if width > 0 else 0.0,
                "normal_expected_count": float(
                    n * (
                        stats.norm.cdf(item["x1"], loc=mean, scale=std)
                        - stats.norm.cdf(item["x0"], loc=mean, scale=std)
                    )
                ),
            })

        kde_points = build_kde(values) or []
        density = [
            {
                "x": float(item["x"]),
                "empirical": float(item["y"]),
                "normal": float(stats.norm.pdf(item["x"], loc=mean, scale=std)),
            }
            for item in kde_points
        ]

    return {
        "column": column,
        **result,
        "requested_bins": bins,
        "bins": bins,
        "histogram": histogram,
        "density": density,
    }
