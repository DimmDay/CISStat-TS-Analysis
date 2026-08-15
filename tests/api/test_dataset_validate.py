# tests/api/test_dataset_validate.py
"""
Интеграционные тесты для GET /v1/session/dataset/validate.

Покрывает:
  1. Нет активного датасета в сессии -- 404.
  2. Ответ содержит все 10 check_id, форма {status, count, items}.
  3. rules_source == "auto" (пока нет UI выбора шаблона).
  4. Реальное нарушение диапазона (auto_generate_rules) видно в ranges.
  5. referential всегда "pending" без явного шаблона (честно, не "done").
  6. Дубликаты строк отражаются в uniqueness.
  7. Ни одна из 10 проверок не падает с 500 на реалистичном "грязном" датасете
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
    assert body["rules_source"] == "auto"
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
        "status": "pending", "count": None, "items": [], "error": None
    }


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
