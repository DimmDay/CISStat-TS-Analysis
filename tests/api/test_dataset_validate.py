# tests/api/test_dataset_validate.py
"""
Интеграционные тесты для GET /v1/session/dataset/validate.

Покрывает:
  1. Нет активного датасета в сессии -- 404.
  2. Ответ содержит все 10 check_id, форма {status, count, items}.
  3. Без ручной настройки используется системный набор правил.
  4. Реальное нарушение диапазона (auto_generate_rules) видно в ranges.
  5. referential всегда "pending" без явного шаблона (честно, не "done").
  6. Дубликаты строк отражаются в uniqueness.
  7. Системный режим назначает исходную схему типов и возвращает профиль.
  8. Ни одна из 10 проверок не падает с 500 на реалистичном "грязном" датасете
     (регресс на баги text_quality/sufficiency, найденные и исправленные
     2026-08-14 при первом реальном подключении этих функций к API).
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing

client = TestClient(app)

EXPECTED_CHECK_IDS = {
    "data_types", "formats", "ranges", "consistency", "uniqueness",
    "inclusion", "referential", "text_quality", "regularity", "sufficiency",
}


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _upload_df(df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    resp = client.post("/v1/internal/upload", files={"file": ("data.csv", buf, "text/csv")})
    assert resp.status_code == 200, resp.text


def test_no_active_dataset_returns_404():
    resp = client.get("/v1/session/dataset/validate")
    assert resp.status_code == 404


def test_response_has_all_10_checks_with_correct_shape():
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=15, freq="D").astype(str),
        "country": ["RU"] * 8 + ["US"] * 7,
        "price": range(15),
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/validate")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert set(body["checks"].keys()) == EXPECTED_CHECK_IDS
    assert body["rules_source"] == "system"
    assert body["total_rows"] == 15
    assert body["total_columns"] == 3
    for check_id, check in body["checks"].items():
        assert check["status"] in ("done", "warning", "pending"), check_id
        assert "count" in check
        assert "items" in check


def test_range_violation_visible_via_auto_generated_rules():
    df = pd.DataFrame({"price": [10.0, 20.0, -999.0, 30.0, 15.0], "label": ["x"] * 5})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/validate")
    body = resp.json()
    ranges = body["checks"]["ranges"]
    assert ranges["status"] == "warning"
    assert ranges["count"] == 1
    assert ranges["items"] == [{"label": "price", "count": 1}]


def test_referential_is_always_pending_without_explicit_template():
    """auto_generate_rules не умеет придумать справочник для сверки --
    честное 'pending' (не 'done'), т.к. физически нечего проверять."""
    df = pd.DataFrame({"value": [1, 2, 3], "label": ["x", "y", "z"]})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/validate")
    body = resp.json()
    assert body["checks"]["referential"] == {
        "status": "pending", "count": None, "items": [], "scope": "column", "error": None,
        "rule_source": "not_applicable",
    }


def test_system_data_types_passes_without_manual_schema_and_returns_profile():
    """Первый общий запуск использует системную схему типов, поэтому
    корректный датасет получает явный зелёный результат без мастера."""
    df = pd.DataFrame({
        "Country": ["RU", "BY", "KZ"],
        "Year": [2022, 2023, 2024],
        "Price": [10.5, 11.0, 12.25],
    })
    _upload_df(df)

    resp = client.get("/v1/session/dataset/validate")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["checks"]["data_types"] == {
        "status": "done", "count": 0, "items": [], "scope": "dataset",
        "error": None, "rule_source": "system",
    }
    assert body["type_validation_mode"] == "schema"
    assert body["type_profile"] == [
        {
            "name": "Country", "dtype": "object", "type_icon": "categorical",
            "non_null": 3, "nulls": 0, "unique": 3,
            "expected_type": "string", "validation_status": "matched", "violations": 0,
        },
        {
            "name": "Year", "dtype": "int64", "type_icon": "numeric",
            "non_null": 3, "nulls": 0, "unique": 3,
            "expected_type": "integer", "validation_status": "matched", "violations": 0,
        },
        {
            "name": "Price", "dtype": "float64", "type_icon": "numeric",
            "non_null": 3, "nulls": 0, "unique": 3,
            "expected_type": "float", "validation_status": "matched", "violations": 0,
        },
    ]


def test_system_rules_use_panel_entity_and_time_as_uniqueness_key():
    df = pd.DataFrame({
        "Country": ["Азербайджан", "Беларусь", "Казахстан"] * 2,
        "Year": [2023, 2023, 2023, 2024, 2024, 2024],
        "Price": [10.0, 20.0, 30.0, 11.0, 21.0, 31.0],
    })
    _upload_df(df)

    body = client.get("/v1/session/dataset/validate").json()
    assert body["checks"]["uniqueness"]["status"] == "done"
    assert body["checks"]["uniqueness"]["count"] == 0
    assert body["checks"]["uniqueness"]["rule_source"] == "system"


def test_duplicate_rows_visible_in_uniqueness():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    _upload_df(df)
    resp = client.get("/v1/session/dataset/validate")
    body = resp.json()
    uniq = body["checks"]["uniqueness"]
    assert uniq["status"] == "warning"
    assert uniq["count"] == 2


def test_no_check_returns_500_on_realistic_dirty_dataset():
    """Регресс: все 10 проверок должны отработать без исключений на
    датасете с несколькими одновременными проблемами (диапазоны, дубли,
    ISO-даты, мусорный символ, панельная группировка) -- ровно тот тип
    данных, где раньше падали text_quality (пустая строка в
    unicode_artifacts) и sufficiency (ISO-строки дат)."""
    n = 40
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n, freq="D").astype(str),
        "country": ["RU"] * 20 + ["US"] * 20,
        "price": [100 + i for i in range(n - 2)] + [-5, 999999],
        "status": ["active"] * (n - 1) + ["unknown"],
    })
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    df.loc[5, "country"] = "RU\x00"
    _upload_df(df)

    resp = client.get("/v1/session/dataset/validate")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for check_id, check in body["checks"].items():
        assert check.get("error") is None, f"{check_id} упала: {check.get('error')}"


# ── column query-параметр (2026-08-14, единый "исследуемый признак") ──

def test_column_param_scopes_ranges_to_that_column_only():
    df = pd.DataFrame({
        "price": [10.0, 20.0, -999.0, 30.0],
        "avg_price": [100.0, 200.0, -500.0, 150.0],
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/validate", params={"column": "price"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["column"] == "price"
    ranges = body["checks"]["ranges"]
    assert ranges["scope"] == "column"
    assert ranges["items"] == [{"label": "price", "count": 1}]  # НЕ avg_price


def test_column_param_missing_column_returns_404():
    df = pd.DataFrame({"price": [10.0, 20.0], "label": ["a", "b"]})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/validate", params={"column": "does_not_exist"})
    assert resp.status_code == 404


def test_without_column_param_response_column_is_null():
    df = pd.DataFrame({"price": [10.0, 20.0], "label": ["a", "b"]})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/validate")
    assert resp.json()["column"] is None


def test_dataset_wide_checks_report_scope_dataset_regardless_of_column_param():
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=10, freq="D").astype(str),
        "price": range(10),
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/validate", params={"column": "price"})
    body = resp.json()
    for check_id in ("data_types", "consistency", "uniqueness", "regularity"):
        assert body["checks"][check_id]["scope"] == "dataset", check_id
