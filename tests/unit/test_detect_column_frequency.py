# tests/unit/test_detect_column_frequency.py
"""
Тесты для app/data/detectors.py::detect_column_frequency.

Регресс на реальный баг, сообщённый пользователем 2026-08-14 на
датасете TEST_dataset_FAO: частота на остановке «Структура» показывала
"D — ежедневная" для годового датасета (захардкоженная заглушка на
фронте, TsAnalysisUpload.tsx::fetchStructureDetection).
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.data.detectors import detect_column_frequency


def test_fao_style_panel_annual_data_detected_as_yearly_not_daily():
    """Точный регресс-кейс: панельные данные (3 страны х 30 лет,
    дублирующиеся года) должны определяться как годовая частота."""
    years = pd.Series(list(range(1994, 2024)) * 3)
    r = detect_column_frequency(years)
    assert "год" in r["selected"].lower()
    assert r["confidence"] == 100


def test_simple_annual_series_no_duplicates():
    years = pd.Series(range(1994, 2024))
    r = detect_column_frequency(years)
    assert "год" in r["selected"].lower()


def test_daily_series_detected_correctly():
    dates = pd.Series(pd.date_range("2020-01-01", periods=100, freq="D"))
    r = detect_column_frequency(dates)
    assert r["code"] == "D"
    assert "дневн" in r["selected"].lower()


def test_monthly_series_detected_correctly():
    dates = pd.Series(pd.date_range("2020-01-01", periods=24, freq="MS"))
    r = detect_column_frequency(dates)
    assert "месячн" in r["selected"].lower()


def test_quarterly_series_detected_correctly():
    dates = pd.Series(pd.date_range("2020-01-01", periods=12, freq="QS"))
    r = detect_column_frequency(dates)
    assert "квартальн" in r["selected"].lower()


def test_irregular_intervals_honestly_undetermined():
    dates = pd.Series(pd.to_datetime(["2020-01-01", "2020-01-05", "2020-03-20", "2020-08-01"]))
    r = detect_column_frequency(dates)
    assert r["code"] is None
    assert r["confidence"] == 0
    assert r["selected"] == "(не определена)"


def test_too_few_unique_dates_undetermined():
    dates = pd.Series(pd.to_datetime(["2020-01-01", "2020-01-01"]))
    r = detect_column_frequency(dates)
    assert r["code"] is None
    assert r["confidence"] == 0


def test_raw_year_integers_not_datetime_dtype():
    """Использует smart_to_datetime внутри -- сырые int-года (как
    реальная колонка Year) не должны падать/давать 1970."""
    years = pd.Series([1994, 1995, 1996, 1997, 1998])
    r = detect_column_frequency(years)
    assert r["code"] is not None
    assert "год" in r["selected"].lower()


def test_empty_series_undetermined_not_error():
    r = detect_column_frequency(pd.Series([], dtype="datetime64[ns]"))
    assert r["confidence"] == 0
    assert r["code"] is None
