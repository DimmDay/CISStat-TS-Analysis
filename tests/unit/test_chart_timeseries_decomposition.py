# tests/unit/test_chart_timeseries_decomposition.py
"""
Тесты для apps/api/chart_data.py::build_timeseries_points и
apps/api/decomposition_data.py::build_decomposition -- остановка «График»
вкладки «Загрузка» (согласовано с тимлидом 2026-08-14).

Покрывает найденные вручную баги/ловушки:
  - build_timeseries_points: сортировка по дате, детект was_resorted,
    отброс NaN-пар, LTTB+сохранение экстремумов с реальными датами.
  - build_decomposition: ЧЕСТНЫЙ гейт по частоте (годовые данные --
    applicable=False, а НЕ фейковая "сезонность" из period=12 по
    умолчанию -- воспроизведённый вручную баг с 30-точечным годовым
    рядом), защита от панельных дублей дат, floating-point шум STL на
    константном ряде (~1e-30, не ровный 0.0 -- строгое "<=0" не ловит).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.chart_data import build_timeseries_points, FULL_POINTS_THRESHOLD
from apps.api.decomposition_data import build_decomposition


# ── build_timeseries_points ──

def test_small_series_no_sampling_all_points_present():
    dates = pd.Series(pd.date_range("2020-01-01", periods=10, freq="D"))
    values = pd.Series(np.arange(10, dtype=float))
    r = build_timeseries_points(dates, values)
    assert r["sampled"] is False
    assert len(r["points"]) == 10
    assert r["points"][0]["x"] == "2020-01-01T00:00:00"
    assert r["points"][0]["y"] == 0.0


def test_unsorted_input_is_sorted_and_flagged():
    dates = pd.Series(pd.to_datetime(["2020-01-03", "2020-01-01", "2020-01-02"]))
    values = pd.Series([3.0, 1.0, 2.0])
    r = build_timeseries_points(dates, values)
    assert r["was_resorted"] is True
    xs = [p["x"] for p in r["points"]]
    assert xs == sorted(xs)
    # После сортировки по дате значения идут в хронологическом порядке 1,2,3
    assert [p["y"] for p in r["points"]] == [1.0, 2.0, 3.0]


def test_already_sorted_input_not_flagged():
    dates = pd.Series(pd.date_range("2020-01-01", periods=5, freq="D"))
    values = pd.Series(range(5))
    r = build_timeseries_points(dates, values)
    assert r["was_resorted"] is False


def test_nan_pairs_dropped():
    dates = pd.Series(pd.to_datetime(["2020-01-01", None, "2020-01-03"]))
    values = pd.Series([1.0, 2.0, None])
    r = build_timeseries_points(dates, values)
    # Строка 1 (date=NaT) и строка 2 (value=NaN) обе отброшены -- валидна только строка 0
    assert r["original_count"] == 1
    assert len(r["points"]) == 1


def test_empty_after_dropna_returns_empty_not_error():
    dates = pd.Series(pd.to_datetime([None, None]))
    values = pd.Series([1.0, 2.0])
    r = build_timeseries_points(dates, values)
    assert r["points"] == []
    assert r["original_count"] == 0


def test_large_series_sampled_preserves_outlier_with_real_date():
    n = FULL_POINTS_THRESHOLD + 3000
    rng = np.random.default_rng(7)
    dates = pd.Series(pd.date_range("1994-01-01", periods=n, freq="D"))
    values = pd.Series(rng.normal(size=n))
    outlier_pos = 4321
    values.iloc[outlier_pos] = 777.0

    r = build_timeseries_points(dates, values)
    assert r["sampled"] is True
    assert r["sampling_method"] == "lttb"
    ys = [p["y"] for p in r["points"]]
    assert max(ys) == 777.0
    outlier_date = dates.iloc[outlier_pos].isoformat()
    assert outlier_date in [p["x"] for p in r["points"]]


# ── build_decomposition: частотный гейт (главная защита от фейковых цифр) ──

def test_annual_data_not_applicable_no_fake_seasonality():
    """Регресс на воспроизведённый вручную баг: 30 годовых точек с
    period=12 по умолчанию давали 'сезонность' из чистого шума."""
    dates = pd.Series(pd.date_range("1994-01-01", periods=30, freq="YS"))
    rng = np.random.default_rng(0)
    values = pd.Series(65.9 + np.arange(30) * 2.0 + rng.normal(size=30) * 5)
    r = build_decomposition(dates, values, "Price")
    assert r["applicable"] is False
    assert "годов" in r["reason"].lower() or "не поддерживает" in r["reason"].lower()
    assert r["trend_pct"] is None
    assert r["seasonal_pct"] is None


def test_panel_data_duplicate_dates_not_applicable():
    """Реальный кейс FAO-датасета: несколько стран на один год --
    'один ряд на одну дату' не определено без агрегации."""
    dates = pd.Series(list(pd.date_range("2014-01-01", periods=10, freq="YS")) * 3)
    values = pd.Series(np.random.default_rng(1).normal(100, 10, size=30))
    r = build_decomposition(dates, values, "Price")
    assert r["applicable"] is False
    assert "панельные" in r["reason"].lower() or "несколько значений" in r["reason"].lower()


def test_monthly_data_with_seasonality_is_applicable_and_sums_to_100():
    dates = pd.Series(pd.date_range("2018-01-01", periods=48, freq="MS"))
    seasonal = 10 * np.sin(np.arange(48) * 2 * np.pi / 12)
    rng = np.random.default_rng(2)
    values = pd.Series(100 + np.arange(48) * 0.5 + seasonal + rng.normal(size=48))
    r = build_decomposition(dates, values, "Price")
    assert r["applicable"] is True
    assert r["method"] == "STL"
    assert r["period_used"] == 12
    total = r["trend_pct"] + r["seasonal_pct"] + r["cyclical_pct"] + r["resid_pct"]
    assert 99.0 <= total <= 101.0  # округление до 1 знака, допуск
    # Сезонность реально заложена в данные -- должна быть заметной долей
    assert r["seasonal_pct"] > 10


def test_insufficient_points_for_detected_frequency_not_applicable():
    dates = pd.Series(pd.date_range("2023-01-01", periods=10, freq="MS"))  # нужно >= 24
    values = pd.Series(np.arange(10, dtype=float))
    r = build_decomposition(dates, values, "Price")
    assert r["applicable"] is False
    assert "недостаточно" in r["reason"].lower()


def test_constant_series_not_applicable_not_500():
    """STL даёт floating-point шум (~1e-30) на константе, не ровный
    0.0 -- строгая проверка '<=0' это не ловит (регресс)."""
    dates = pd.Series(pd.date_range("2020-01-01", periods=30, freq="MS"))
    values = pd.Series([5.0] * 30)
    r = build_decomposition(dates, values, "Price")
    assert r["applicable"] is False
    assert "констант" in r["reason"].lower()


def test_irregular_frequency_not_applicable():
    dates = pd.Series(pd.to_datetime(["2020-01-01", "2020-01-05", "2020-03-20", "2020-08-01", "2021-01-15"]))
    values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    r = build_decomposition(dates, values, "Price")
    assert r["applicable"] is False


def test_empty_input_not_applicable_not_error():
    r = build_decomposition(pd.Series([], dtype="datetime64[ns]"), pd.Series([], dtype=float), "Price")
    assert r["applicable"] is False
