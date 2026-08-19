# tests/unit/test_detectors_scoring.py
"""
Тесты для app/data/detectors.py::score_all_columns_as_date и
score_all_columns_as_entity_group -- адаптер для контракта фронтенда
{selected, confidence, candidates: [{name, score}]} (см.
apps/api/upload_common.py, комментарий про detect_and_convert_datetime).

Регресс на реальный баг, сообщённый пользователем: TEST_dataset_FAO
(Country, Year, Price) на клиентской позиционной эвристике показывал
абсурдные кандидаты в дату -- Country score 0.90, Year 0.70, Price 0.50
(просто первые 3 колонки файла с искусственно убывающим score). Реальный
контентный скоринг должен дать Year высокий score, Country/Price -- 0.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.data.detectors import score_all_columns_as_date, score_all_columns_as_entity_group


# ── score_all_columns_as_date ──

def test_fao_dataset_year_scores_high_country_and_price_score_zero():
    """Точный регресс на баг из чата: Country/Price НЕ должны получать
    ненулевой score только потому что они первые в файле."""
    df = pd.DataFrame({
        "Country": ["Азербайджан", "Беларусь", "Казахстан"] * 10,
        "Year": list(range(1994, 2024)),
        "Price": [65.9 + i for i in range(30)],
    })
    scores = {r["name"]: r["score"] for r in score_all_columns_as_date(df)}
    assert scores["Year"] > 0.9
    assert scores["Country"] == 0.0
    assert scores["Price"] == 0.0


def test_iso_date_string_column_scores_high():
    df = pd.DataFrame({"date": ["2020-01-01", "2020-01-02", "2020-01-03"], "value": [1, 2, 3]})
    scores = {r["name"]: r["score"] for r in score_all_columns_as_date(df)}
    assert scores["date"] > 0.9


def test_already_datetime_dtype_scores_1():
    df = pd.DataFrame({"date": pd.to_datetime(["2020-01-01", "2020-01-02"]), "value": [1, 2]})
    scores = {r["name"]: r["score"] for r in score_all_columns_as_date(df)}
    assert scores["date"] == 1.0


def test_results_sorted_descending_by_score():
    df = pd.DataFrame({
        "Country": ["RU", "US", "DE"] * 10,
        "Year": list(range(1994, 2024)),
        "Price": [65.9 + i for i in range(30)],
    })
    scores = score_all_columns_as_date(df)
    values = [r["score"] for r in scores]
    assert values == sorted(values, reverse=True)
    assert scores[0]["name"] == "Year"


def test_no_plausible_date_column_all_zero():
    df = pd.DataFrame({"a": ["x", "y", "z"], "b": [1.5, 2.5, 3.5]})
    scores = {r["name"]: r["score"] for r in score_all_columns_as_date(df)}
    # ни одна не похожа на дату по содержимому -- обе низкие/нулевые
    assert scores["b"] < 0.5


def test_all_columns_present_in_result_not_just_matches():
    """Контракт: возвращает ВСЕ колонки (с их score, включая 0.0), не
    только те, что прошли фильтр -- фронт сам решает порог отсечения."""
    df = pd.DataFrame({"a": ["x"], "b": ["y"], "c": [1]})
    scores = score_all_columns_as_date(df)
    assert {r["name"] for r in scores} == {"a", "b", "c"}


# ── score_all_columns_as_entity_group ──

def test_categorical_column_with_reasonable_cardinality_scores_1():
    df = pd.DataFrame({
        "country": ["RU", "US", "DE"] * 10,
        "year": list(range(1994, 2024)),
        "price": [65.9 + i for i in range(30)],
    })
    scores = {r["name"]: r["score"] for r in score_all_columns_as_entity_group(df, date_col="year")}
    assert scores["country"] == 1.0
    assert scores["price"] == 0.0


def test_date_col_excluded_from_candidates():
    df = pd.DataFrame({"country": ["RU", "US"] * 5, "year": list(range(2010, 2020))})
    result_names = {r["name"] for r in score_all_columns_as_entity_group(df, date_col="year")}
    assert "year" not in result_names


def test_too_many_unique_values_scores_zero():
    """>= 100 уникальных значений -- не похоже на группирующую колонку
    (скорее ID или свободный текст)."""
    df = pd.DataFrame({"id": [f"row_{i}" for i in range(150)], "value": range(150)})
    scores = {r["name"]: r["score"] for r in score_all_columns_as_entity_group(df)}
    assert scores["id"] == 0.0


def test_single_unique_value_scores_zero():
    """Константная колонка -- не несёт группирующей информации."""
    df = pd.DataFrame({"flag": ["same"] * 20, "value": range(20)})
    scores = {r["name"]: r["score"] for r in score_all_columns_as_entity_group(df)}
    assert scores["flag"] == 0.0


def test_numeric_column_never_scores_as_entity():
    df = pd.DataFrame({"price": [1.0, 2.0, 3.0] * 10, "category": ["a", "b", "c"] * 10})
    scores = {r["name"]: r["score"] for r in score_all_columns_as_entity_group(df)}
    assert scores["price"] == 0.0
