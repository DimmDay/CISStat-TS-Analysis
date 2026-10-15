# tests/api/test_missing_manual_editor.py
"""
Ручное исправление пропусков (задача MANUAL-MISSING-1, 2026-10-15,
постановка тимлида): остановка «Пропуски» модуля «Предобработка» получает
режим ручной корректировки датасета -- аналитик восстановил данные из-за
ошибки ввода и правит ячейки руками (перенос функционала legacy app.py:
radio-фильтр «Все/Пропуски/Без пропусков» → st.data_editor → «💾 Сохранить»
(df_work.update(edited_df)), блок ~7760-7930).

Новые аддитивные контракты (существующие не затрагиваются):

1. GET /v1/session/dataset/missing-editor-rows -- источник строк редактора:
   окна по offset/limit; missing_only=True -- только строки хотя бы с одним
   пропуском (legacy-маска df.isnull().any(axis=1)), ПОЗИЦИОННЫЕ row_index
   исходного датафрейма; ячейки -- JSON-нативно: None для NaN/None (честное
   отличие от строк 'nan'/'None' строкового превью /dataset), числа для
   numeric-колонок, строки для остальных; semantic колонок -- ТА ЖЕ
   классификация _semantic_class, что у профиля остановки (вторая
   реализация семантики запрещена -- закреплённая практика платформы).
2. POST /v1/session/dataset/missing-manual-corrections -- применение правок:
   ячеечные правки (row_index, column, value) на КОПИИ; None/"" = очистка
   в NaN (контекст исправления пропусков); numeric-колонки -- честная 422
   на неприводимое значение; last-wins на дубли (row, column); счётчик
   total_changed -- ФАКТИЧЕСКИ изменившиеся ячейки (перебор того же числа
   не считается); no-op apply не повышает data_revision (AUDIT-C,
   единая точка set_dataframe); apply=False -- валидация и счётчики без
   сохранения; профиль ПОСЛЕ -- в канонической области (производные вне
   статуса, PROGR-24-ORIGIN-A).

Корпус дизъюнктен существующим сюитам (метеостанция: recorded_at/temp_c/
humidity/sensor_id; dataset_id не пинится -- свой CSV в каждой проверке).
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


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _weather_df() -> pd.DataFrame:
    """12 строк метеостанции: пропуски в temp_c (строки 1, 5, 8) и
    humidity (строка 6); в sensor_id пропусков нет. Строки с хотя бы
    одним пропуском: 1, 5, 6, 8."""
    return pd.DataFrame(
        {
            "recorded_at": [f"2024-06-{d:02d}" for d in range(1, 13)],
            "temp_c": [12.5, np.nan, 14.1, 13.8, 15.0, np.nan, 16.2, 14.9, np.nan, 13.3, 12.9, 15.4],
            "humidity": [58.0, 61.5, 60.0, 57.5, 59.0, 62.0, np.nan, 55.0, 63.0, 58.5, 60.5, 57.0],
            "sensor_id": [f"MS-{i:02d}" for i in range(1, 13)],
        }
    )


def _upload_df(df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    resp = client.post("/v1/internal/upload", files={"file": ("weather.csv", buf, "text/csv")})
    assert resp.status_code == 200, resp.text


def _current() -> dict:
    resp = client.get("/v1/session/current")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── 1. GET /dataset/missing-editor-rows: контракт окна ───────────────


def test_editor_rows_404_without_dataset():
    resp = client.get("/v1/session/dataset/missing-editor-rows")
    assert resp.status_code == 404, resp.text


def test_editor_rows_full_scope_window_and_meta():
    df = _weather_df()
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/missing-editor-rows",
        params={"offset": 0, "limit": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [c["column"] for c in body["columns"]] == ["recorded_at", "temp_c", "humidity", "sensor_id"]
    semantics = {c["column"]: c["semantic"] for c in body["columns"]}
    # ТА ЖЕ классификация, что у профиля остановки (единая _semantic_class)
    assert semantics == {
        "recorded_at": "text",
        "temp_c": "numeric",
        "humidity": "numeric",
        "sensor_id": "text",
    }
    assert body["total_rows"] == 12
    assert body["returned"] == 5
    assert body["offset"] == 0
    assert body["has_more"] is True
    assert [r["row_index"] for r in body["rows"]] == [0, 1, 2, 3, 4]


def test_editor_rows_cells_json_native_honest():
    """None для NaN (не строка 'nan'!), числа в numeric, строки в text."""
    df = _weather_df()
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/missing-editor-rows",
        params={"offset": 1, "limit": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # строка 1: temp_c = NaN → None; humidity = 61.5 → число 61.5
    row1 = body["rows"][0]
    assert row1["row_index"] == 1
    assert row1["cells"][0] == "2024-06-02"
    assert row1["cells"][1] is None
    assert row1["cells"][2] == 61.5
    assert row1["cells"][3] == "MS-02"
    # строка 2: temp_c = 14.1 → число
    row2 = body["rows"][1]
    assert row2["cells"][1] == 14.1


def test_editor_rows_missing_only_original_indices_and_counters():
    """missing_only=True: только строки с пропусками (legacy-маска
    isnull().any(axis=1)), row_index -- ПОЗИЦИИ исходного датафрейма
    (не подряд), total_rows -- счётчик отфильтрованного множества."""
    df = _weather_df()
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/missing-editor-rows",
        params={"offset": 0, "limit": 50, "missing_only": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # пропуски: строки 1, 5, 6, 8 (0-based) -- ровно 4
    assert body["total_rows"] == 4
    assert [r["row_index"] for r in body["rows"]] == [1, 5, 6, 8]
    assert body["has_more"] is False
    # ячейки строки 1: temp_c None, остальные не тронуты
    row1 = body["rows"][0]
    assert row1["cells"][1] is None
    assert row1["cells"][2] == 61.5


def test_editor_rows_missing_only_pagination_over_filtered_sequence():
    """Пагинация поверх ОТФИЛЬТРОВАННОЙ последовательности: окно
    [offset, offset+limit) фильтра, а не исходного датафрейма."""
    df = _weather_df()
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/missing-editor-rows",
        params={"offset": 1, "limit": 2, "missing_only": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 4
    assert body["returned"] == 2
    assert [r["row_index"] for r in body["rows"]] == [5, 6]
    assert body["has_more"] is True


def test_editor_rows_missing_only_empty_result_when_no_missing():
    """Датасет без пропусков: missing_only даёт честное пустое окно
    (total_rows=0, returned=0), не ошибку."""
    df = pd.DataFrame({"a": [1.0, 2.0], "b": ["x", "y"]})
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/missing-editor-rows",
        params={"offset": 0, "limit": 50, "missing_only": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 0
    assert body["returned"] == 0
    assert body["rows"] == []
    assert body["has_more"] is False


# ── 2. POST /dataset/missing-manual-corrections: применение правок ───


def test_manual_correction_numeric_edit_fixes_missing():
    """Правка ячейки numeric-колонки: NaN → значение; счётчики честные;
    профиль ПОСЛЕ отражает исправление; датасет реально изменён."""
    df = _weather_df()
    _upload_df(df)
    before = _current()
    assert before["data_revision"] == 0

    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={"edits": [{"row_index": 1, "column": "temp_c", "value": 14.6}], "apply": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["total_edited_requested"] == 1
    assert body["total_changed"] == 1
    assert body["total_missing_before"] == 4
    assert body["total_missing_after"] == 3
    profile_cols = {item["column"]: item for item in body["profile"]}
    assert profile_cols["temp_c"]["missing_count"] == 2

    after = _current()
    assert after["data_revision"] == 1  # AUDIT-C: фактическое изменение

    # значение действительно в датасете (через строковое окно /dataset/rows)
    rows = client.get("/v1/session/dataset/rows", params={"offset": 1, "limit": 1}).json()
    assert rows["rows"][0][1] == "14.6"


def test_manual_correction_text_edit_and_clear_to_nan():
    """Текстовая правка сохраняется как строка; пустое значение (null и
    "") очищает ячейку в NaN -- аналитик может ПОМЕТИТЬ пропуск честно."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={
            "edits": [
                {"row_index": 0, "column": "sensor_id", "value": "MS-01-REPLACED"},
                {"row_index": 1, "column": "humidity", "value": None},
                {"row_index": 3, "column": "sensor_id", "value": ""},
            ],
            "apply": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_changed"] == 3
    assert body["total_missing_before"] == 4
    assert body["total_missing_after"] == 6  # +1 humidity, +1 sensor_id
    assert body["applied"] is True

    rows = client.get("/v1/session/dataset/rows", params={"offset": 0, "limit": 4}).json()
    assert rows["rows"][0][3] == "MS-01-REPLACED"
    assert rows["rows"][1][2] == "nan"  # очистка → NaN → строковое 'nan'
    assert rows["rows"][3][3] == "nan"


def test_manual_correction_noop_edit_does_not_bump_revision():
    """Перебор того же числа -- no-op: total_changed=0, ревизия НЕ
    повышается (AUDIT-C, «no-op apply не выдаётся за изменённые данные»)."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={"edits": [{"row_index": 0, "column": "temp_c", "value": 12.5}], "apply": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_edited_requested"] == 1
    assert body["total_changed"] == 0
    assert _current()["data_revision"] == 0


def test_manual_correction_last_wins_on_duplicate_cell():
    """Две правки одной ячейки в одном запросе -- last-wins, меняется
    один раз (одна ячейка = один факт изменения)."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={
            "edits": [
                {"row_index": 2, "column": "temp_c", "value": 10.0},
                {"row_index": 2, "column": "temp_c", "value": 14.6},
            ],
            "apply": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_changed"] == 1
    rows = client.get("/v1/session/dataset/rows", params={"offset": 2, "limit": 1}).json()
    assert rows["rows"][0][1] == "14.6"


def test_manual_correction_preview_apply_false_does_not_change_session():
    """apply=False -- валидация и счётчики БЕЗ сохранения: applied=false,
    датасет и ревизия не тронуты."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={"edits": [{"row_index": 1, "column": "temp_c", "value": 14.6}], "apply": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is False
    assert body["total_changed"] == 1
    assert _current()["data_revision"] == 0
    # значение НЕ применено
    rows = client.get("/v1/session/dataset/rows", params={"offset": 1, "limit": 1}).json()
    assert rows["rows"][0][1] == "nan"


def test_manual_correction_invalid_numeric_honest_422():
    """Неприводимое значение в numeric-колонку -- честная 422 с указанием
    колонки и строки; сессия не меняется."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={"edits": [{"row_index": 2, "column": "temp_c", "value": "abc"}], "apply": True},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "temp_c" in detail and "abc" in detail
    assert _current()["data_revision"] == 0


def test_manual_correction_validation_errors():
    df = _weather_df()
    _upload_df(df)

    # неизвестная колонка
    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={"edits": [{"row_index": 0, "column": "no_such_col", "value": "x"}], "apply": True},
    )
    assert resp.status_code == 422, resp.text
    assert "no_such_col" in resp.json()["detail"]

    # строка за пределами датасета
    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={"edits": [{"row_index": 99, "column": "temp_c", "value": 1.0}], "apply": True},
    )
    assert resp.status_code == 422, resp.text

    # пустой список правок (min_length=1)
    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={"edits": [], "apply": True},
    )
    assert resp.status_code == 422, resp.text


def test_manual_correction_missing_only_then_fix_via_editor_flow():
    """Сквозной сценарий редактора: missing_only-окно показывает строки
    с пропусками; правки по исходным позициям; после apply в датасете
    пропусков меньше, missing_only-окно перечитывается честно."""
    df = _weather_df()
    _upload_df(df)

    # редактор в фильтре «Только с пропусками» видит ровно проблемные строки
    view = client.get(
        "/v1/session/dataset/missing-editor-rows",
        params={"offset": 0, "limit": 50, "missing_only": "true"},
    ).json()
    assert [r["row_index"] for r in view["rows"]] == [1, 5, 6, 8]

    # аналитик исправляет temp_c строк 1 и 8 прямо из этого окна
    resp = client.post(
        "/v1/session/dataset/missing-manual-corrections",
        json={
            "edits": [
                {"row_index": 1, "column": "temp_c", "value": 14.6},
                {"row_index": 8, "column": "temp_c", "value": 13.7},
            ],
            "apply": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_missing_after"] == 2

    # после apply окно «Только с пропусками» честно сузилось (5 и 6)
    view2 = client.get(
        "/v1/session/dataset/missing-editor-rows",
        params={"offset": 0, "limit": 50, "missing_only": "true"},
    ).json()
    assert [r["row_index"] for r in view2["rows"]] == [5, 6]
    assert view2["total_rows"] == 2
