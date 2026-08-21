# tests/unit/test_apply_decomposition.py
"""
Тесты для app/preprocessing/decomposition.py::apply_decomposition.

Регресс на реальный баг, найденный 2026-08-19 при первом реальном
вызове этой функции (задача "визуализировать декомпозированный ряд"):
statsmodels.tsa.seasonal.STL падает ValueError'ом на ЯВНО переданном
seasonal=None/trend=None, хотя при полностью опущенном параметре
использует свой собственный дефолт без ошибок. apply_decomposition
вызывалась ТОЛЬКО с собственными дефолтами (seasonal_window=None,
trend_window=None) -- т.е. ЛЮБОЙ вызов этой функции без явных окон
падал. Ни одного теста на неё раньше не было (compute_decomposition_stats,
рядом в том же файле, НЕ передаёт seasonal=/trend= вовсе и потому не
задевала этот баг)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.preprocessing.decomposition import apply_decomposition


def _monthly_series(n=48, seed=1):
    dates = pd.date_range("2018-01-01", periods=n, freq="MS")
    rng = np.random.default_rng(seed)
    seasonal = 10 * np.sin(np.arange(n) * 2 * np.pi / 12)
    values = 100 + np.arange(n) * 0.5 + seasonal + rng.normal(size=n)
    return pd.Series(values, index=dates)


def test_stl_with_default_windows_does_not_crash():
    """Регресс: apply_decomposition(series) без seasonal_window/trend_window
    (её же собственные дефолты) раньше падал ValueError."""
    series = _monthly_series()
    result = apply_decomposition(series, method="STL", period=12)
    assert result["method"] == "STL"
    assert len(result["trend"]) == len(series)
    assert len(result["seasonal"]) == len(series)
    assert len(result["resid"]) == len(series)


def test_stl_with_explicit_seasonal_and_trend_window_still_works():
    """Явно переданные ненулевые окна и раньше работали -- не должно
    сломаться после фикса (kwargs теперь собираются условно)."""
    series = _monthly_series()
    result = apply_decomposition(series, method="STL", period=12, seasonal_window=13, trend_window=25)
    assert result["method"] == "STL"
    assert len(result["trend"]) == len(series)


def test_stl_observed_matches_input_series():
    series = _monthly_series()
    result = apply_decomposition(series, method="STL", period=12)
    pd.testing.assert_series_equal(result["observed"], series)


def test_additive_method_still_works():
    series = _monthly_series()
    result = apply_decomposition(series, method="Additive", period=12)
    assert result["method"] == "Additive"
    assert len(result["trend"]) == len(series)


def test_multiplicative_method_still_works():
    series = _monthly_series().abs() + 1  # мультипликативная модель требует положительный ряд
    result = apply_decomposition(series, method="Multiplicative", period=12)
    assert result["method"] == "Multiplicative"


def test_period_auto_inferred_when_not_given():
    series = _monthly_series()
    result = apply_decomposition(series, method="STL")  # period=None -- автоопределение
    assert result["method"] == "STL"
    assert len(result["trend"]) == len(series)


def test_insufficient_data_raises_value_error():
    series = _monthly_series(n=10)  # < 2*12
    with pytest.raises(ValueError, match="Недостаточно данных"):
        apply_decomposition(series, method="STL", period=12)


def test_unknown_method_raises_value_error():
    series = _monthly_series()
    with pytest.raises(ValueError, match="Неизвестный метод"):
        apply_decomposition(series, method="Bogus", period=12)  # type: ignore[arg-type]
