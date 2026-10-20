# tests/api/test_panel_transforms.py
#
# UPLOAD-RECOMP-2 (2026-10-20), пункт (в) -- панельные микросервисы
# преобразования на остановке «Структура» модуля «Загрузка»:
#   * POST /v1/session/dataset/entity-filter -- сведение панели к одному
#     ряду одной сущности (preview/apply по сертифицированному паттерну
#     regularity/sufficiency: payload.apply, честный summary);
#   * POST /v1/session/dataset/panel-aggregate -- агрегация по времени
#     (mean/sum/median/min/max по числовым, first по нечисловым,
#     entity-колонка удаляется с пометкой).
#
# Методологические запреты (spec_upload_recompose_2026-10-20.md §3.3):
# молчаливой агрегации нет -- preview (apply=false) НЕ мутирует сессию
# ни байтом; валидации fail-closed; честные счётчики (rows/dates/
# skipped). Корпус -- СВОИ панельные фикстуры, дизъюнктен другим файлам.
from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _upload_df(df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    resp = client.post("/v1/internal/upload", files={"file": ("panel_recomp2.csv", buf, "text/csv")})
    assert resp.status_code == 200, resp.text


def _panel_df() -> pd.DataFrame:
    """Сбалансированная панель: 2 сущности x 36 дат (обе сущности выше
    паспортного минимума 30 точек однорядного контура), 2 числовые
    колонки + 1 нечисловая (проверка first-агрегации)."""
    dates = pd.date_range("2024-01-01", periods=36, freq="D").astype(str)
    rows = []
    for i, d in enumerate(dates):
        rows.append({"date": d, "region": "north", "sales": float(10 + i), "label": f"n{i}"})
        rows.append({"date": d, "region": "south", "sales": float(50 + i), "label": f"s{i}"})
    return pd.DataFrame(rows)


def _rows_snapshot() -> list:
    resp = client.get("/v1/session/dataset/rows?offset=0&limit=1000")
    assert resp.status_code == 200, resp.text
    return resp.json()["rows"]


# ── entity-filter: доступные значения (селектор UI) ─────────────────────

def test_entity_filter_preview_without_value_lists_available_values():
    _upload_df(_panel_df())
    resp = client.post(
        "/v1/session/dataset/entity-filter",
        json={"entity_col": "region", "value": None, "apply": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is False
    assert body["available_values"] == ["north", "south"]
    # Превью без выбранного значения честно не показывает статистики
    # сведение-результата.
    assert body["n_rows_after"] is None


# ── entity-filter: preview не мутирует ──────────────────────────────────

def test_entity_filter_preview_returns_stats_without_mutation():
    _upload_df(_panel_df())
    before = _rows_snapshot()

    resp = client.post(
        "/v1/session/dataset/entity-filter",
        json={"entity_col": "region", "date_col": "date", "value": "north", "apply": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is False
    assert body["n_rows_before"] == 72
    assert body["n_rows_after"] == 36
    assert body["n_dates"] == 36
    assert body["date_min"] == "2024-01-01"
    assert body["date_max"] == "2024-02-05"

    # Побайтная честность preview: строки датасета не изменились.
    after = _rows_snapshot()
    assert after == before


# ── entity-filter: apply сводит панель к одной сущности ─────────────────

def test_entity_filter_apply_keeps_only_entity_rows():
    _upload_df(_panel_df())
    resp = client.post(
        "/v1/session/dataset/entity-filter",
        json={"entity_col": "region", "value": "south", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["n_rows_before"] == 72
    assert body["n_rows_after"] == 36

    rows = _rows_snapshot()
    assert len(rows) == 36
    columns = client.get("/v1/session/dataset/rows?offset=0&limit=1").json()["columns"]
    # Колонка region: все строки -- выбранная сущность.
    region_idx = columns.index("region")
    regions = {row[region_idx] for row in rows}
    assert regions == {"south"}


def test_entity_filter_apply_persists_in_session():
    _upload_df(_panel_df())
    resp = client.post(
        "/v1/session/dataset/entity-filter",
        json={"entity_col": "region", "value": "north", "apply": True},
    )
    assert resp.status_code == 200
    # Сессия сохранена: повторное чтение датасета отдаёт 20 строк.
    dataset = client.get("/v1/session/dataset").json()
    assert dataset["rows"] == 36


# ── entity-filter: fail-closed валидации ────────────────────────────────

def test_entity_filter_unknown_value_422():
    _upload_df(_panel_df())
    resp = client.post(
        "/v1/session/dataset/entity-filter",
        json={"entity_col": "region", "value": "east", "apply": False},
    )
    assert resp.status_code == 422
    assert "east" in resp.json()["detail"]


def test_entity_filter_missing_entity_column_422():
    _upload_df(_panel_df())
    resp = client.post(
        "/v1/session/dataset/entity-filter",
        json={"entity_col": "nope", "value": None, "apply": False},
    )
    assert resp.status_code == 422


def test_entity_filter_below_passport_minimum_422():
    """После фильтра остаётся меньше паспортного минимума (30 точек) --
    честный отказ ДО apply (preview и apply оба)."""
    full = _panel_df()
    df = pd.concat(
        [full[full["region"] == "south"], full[full["region"] == "north"].head(10)],
        ignore_index=True,
    )
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/entity-filter",
        json={"entity_col": "region", "value": "north", "apply": False},
    )
    assert resp.status_code == 422
    assert "30" in resp.json()["detail"]


def test_entity_filter_no_dataset_404():
    resp = client.post(
        "/v1/session/dataset/entity-filter",
        json={"entity_col": "region", "value": None, "apply": False},
    )
    assert resp.status_code == 404


# ── panel-aggregate: preview/apply ──────────────────────────────────────

def test_panel_aggregate_preview_without_mutation():
    _upload_df(_panel_df())
    before = _rows_snapshot()
    resp = client.post(
        "/v1/session/dataset/panel-aggregate",
        json={"date_col": "date", "entity_col": "region", "func": "mean", "apply": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is False
    assert body["n_rows_before"] == 72
    assert body["n_dates"] == 36
    assert _rows_snapshot() == before


def test_panel_aggregate_apply_mean_numeric_first_non_numeric():
    _upload_df(_panel_df())
    resp = client.post(
        "/v1/session/dataset/panel-aggregate",
        json={"date_col": "date", "entity_col": "region", "func": "mean", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["n_rows_before"] == 72
    assert body["n_rows_after"] == 36
    assert body["n_dates"] == 36
    assert body["n_dates_skipped"] == 0
    # Entity-колонка удалена из результата с честной пометкой.
    assert "region" in body["dropped_columns"]
    assert "sales" in body["numeric_columns"]
    assert "label" in body["first_kept_columns"]

    rows_resp = client.get("/v1/session/dataset/rows?offset=0&limit=1").json()
    rows = client.get("/v1/session/dataset/rows?offset=0&limit=1000").json()["rows"]
    assert len(rows) == 36
    columns = rows_resp["columns"]
    # Честная арифметика mean: (10 + 50) / 2 = 30 для первой даты.
    sales_idx = columns.index("sales")
    assert abs(float(rows[0][sales_idx]) - 30.0) < 1e-9


def test_panel_aggregate_apply_sum_semantics():
    _upload_df(_panel_df())
    resp = client.post(
        "/v1/session/dataset/panel-aggregate",
        json={"date_col": "date", "entity_col": "region", "func": "sum", "apply": True},
    )
    assert resp.status_code == 200
    rows_resp = client.get("/v1/session/dataset/rows?offset=0&limit=5").json()
    rows, columns = rows_resp["rows"], rows_resp["columns"]
    assert rows and columns
    sales_idx = columns.index("sales")
    assert abs(float(rows[0][sales_idx]) - 60.0) < 1e-9  # 10 + 50


def test_panel_aggregate_nan_policy_skips_empty_dates():
    """Дата, где у ВСЕХ сущностей пропуски в числовых, честно
    отбрасывается со счётчиком n_dates_skipped."""
    df = _panel_df()
    # 2024-01-01: обе сущности -- NaN в sales.
    mask = df["date"] == "2024-01-01"
    df.loc[mask, "sales"] = None
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/panel-aggregate",
        json={"date_col": "date", "entity_col": "region", "func": "mean", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["n_dates_skipped"] == 1
    assert body["n_dates"] == 35
    assert body["n_rows_after"] == 35


def test_panel_aggregate_no_numeric_columns_422():
    _upload_df(pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=6, freq="D").astype(str),
        "region": ["a", "b"] * 3,
        "label": ["x", "y", "z"] * 2,
    }))
    resp = client.post(
        "/v1/session/dataset/panel-aggregate",
        json={"date_col": "date", "entity_col": "region", "func": "mean", "apply": False},
    )
    assert resp.status_code == 422
    assert "числовых" in resp.json()["detail"]


def test_panel_aggregate_unknown_date_column_404():
    _upload_df(_panel_df())
    resp = client.post(
        "/v1/session/dataset/panel-aggregate",
        json={"date_col": "nope", "entity_col": "region", "func": "mean", "apply": False},
    )
    assert resp.status_code == 404


def test_panel_aggregate_invalid_func_422():
    _upload_df(_panel_df())
    resp = client.post(
        "/v1/session/dataset/panel-aggregate",
        json={"date_col": "date", "entity_col": "region", "func": "median_of_medians", "apply": False},
    )
    assert resp.status_code == 422


def test_panel_aggregate_no_dataset_404():
    resp = client.post(
        "/v1/session/dataset/panel-aggregate",
        json={"date_col": "date", "entity_col": "region", "func": "mean", "apply": False},
    )
    assert resp.status_code == 404
