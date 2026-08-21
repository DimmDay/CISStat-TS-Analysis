# tests/unit/test_decomposition_series.py
"""
Тесты для apps/api/decomposition_data.py::build_decomposition_series --
график разложенного ряда (Тренд/Сезонность/Цикличность/Остаток),
согласовано с тимлидом 2026-08-19: "визуализировать данный
декомпозированный ряд на дополнительном графике".

Переиспользует app/preprocessing/decomposition.py::apply_decomposition
(тот же вызов, что и compute_decomposition_stats внутри build_decomposition,
см. общий гейтинг _prepare_decomposable_series) -- гейт (частота/панельные
дубли/точки) должен давать ОДИНАКОВЫЙ applicable, что и у бейджей.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.decomposition_data import build_decomposition, build_decomposition_series
from apps.api.chart_data import FULL_POINTS_THRESHOLD


def _monthly_series_with_seasonality(n=48, seed=2):
    dates = pd.Series(pd.date_range("2018-01-01", periods=n, freq="MS"))
    seasonal = 10 * np.sin(np.arange(n) * 2 * np.pi / 12)
    rng = np.random.default_rng(seed)
    values = pd.Series(100 + np.arange(n) * 0.5 + seasonal + rng.normal(size=n))
    return dates, values


def test_monthly_data_applicable_with_all_four_components_per_point():
    dates, values = _monthly_series_with_seasonality()
    r = build_decomposition_series(dates, values, "price")
    assert r["applicable"] is True
    assert r["method"] == "STL"
    assert r["sampled"] is False
    assert len(r["points"]) == 48
    for p in r["points"]:
        assert set(p.keys()) == {"x", "trend", "seasonal", "cyclical", "resid"}
        assert isinstance(p["trend"], float)


def test_points_dates_are_real_not_1970():
    dates, values = _monthly_series_with_seasonality()
    r = build_decomposition_series(dates, values, "price")
    xs = [p["x"] for p in r["points"]]
    assert xs[0] == "2018-01-01T00:00:00"
    assert all(not x.startswith("1970") for x in xs)


def test_applicability_matches_badges_endpoint_for_annual_data():
    """Гейт ОБЩИЙ (см. _prepare_decomposable_series) -- график и бейджи
    должны согласованно говорить 'неприменимо' на одних и тех же данных,
    не противоречить друг другу."""
    years = pd.Series(range(1994, 2024))
    prices = pd.Series([65.9 + i for i in range(30)])
    badges = build_decomposition(years, prices, "price")
    series_chart = build_decomposition_series(years, prices, "price")
    assert badges["applicable"] is False
    assert series_chart["applicable"] is False
    assert series_chart["points"] == []


def test_applicability_matches_badges_endpoint_for_panel_duplicate_dates():
    years = pd.Series(list(range(1994, 2024)) * 3)
    prices = pd.Series(np.random.default_rng(1).normal(100, 10, size=90))
    badges = build_decomposition(years, prices, "price")
    series_chart = build_decomposition_series(years, prices, "price")
    assert badges["applicable"] is False
    assert series_chart["applicable"] is False


def test_applicability_matches_badges_for_valid_monthly_data():
    dates, values = _monthly_series_with_seasonality()
    badges = build_decomposition(dates, values, "price")
    series_chart = build_decomposition_series(dates, values, "price")
    assert badges["applicable"] is True
    assert series_chart["applicable"] is True


def test_large_series_is_sampled_and_components_stay_aligned():
    n = FULL_POINTS_THRESHOLD + 1000
    dates = pd.Series(pd.date_range("2015-01-01", periods=n, freq="D"))
    rng = np.random.default_rng(3)
    values = pd.Series(100 + np.arange(n) * 0.02 + 5 * np.sin(np.arange(n) * 2 * np.pi / 365) + rng.normal(size=n))
    r = build_decomposition_series(dates, values, "price")
    assert r["applicable"] is True
    assert r["sampled"] is True
    assert r["sampling_method"] == "lttb"
    assert r["original_count"] == n
    assert 0 < len(r["points"]) < n
    # x строго возрастают -- LTTB не должен ломать хронологический порядок
    xs = [p["x"] for p in r["points"]]
    assert xs == sorted(xs)
    assert len(set(xs)) == len(xs)  # без дублей


def test_cyclical_uses_same_formula_as_badges_stats():
    """cyclical в графике -- РЯД по той же формуле (trend - rolling(30)
    mean тренда), что compute_decomposition_stats сворачивает в
    cyclical_var -- дисперсия ряда из графика должна примерно совпадать
    с cyclical_pct долей (в пределах, т.к. один -- var, другой -- pct)."""
    dates, values = _monthly_series_with_seasonality(n=60)
    badges = build_decomposition(dates, values, "price")
    series_chart = build_decomposition_series(dates, values, "price")
    assert badges["applicable"] and series_chart["applicable"]
    cyclical_values = [p["cyclical"] for p in series_chart["points"]]
    # Начальные точки: rolling(30, min_periods=1) на первой точке равно
    # самой точке -> cyclical[0] должен быть ровно 0.0
    assert cyclical_values[0] == 0.0


def test_constant_series_not_applicable_not_500():
    dates = pd.Series(pd.date_range("2020-01-01", periods=30, freq="MS"))
    values = pd.Series([5.0] * 30)
    r = build_decomposition_series(dates, values, "price")
    assert r["applicable"] is False
    assert r["points"] == []


def test_raw_year_integers_do_not_crash_and_stay_not_applicable():
    """Регресс на смежный баг (голые int-года -> 1970 на build_timeseries_points) --
    здесь достаточно не упасть; applicable=False ожидаемо (годовая частота)."""
    dates = pd.Series(list(range(1994, 2024)))
    values = pd.Series([65.9 + i for i in range(30)])
    r = build_decomposition_series(dates, values, "price")
    assert r["applicable"] is False
    assert r["reason"] is not None
