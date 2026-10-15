# tests/api/test_outlier_manual_editor.py
"""
Ручное исправление выбросов (задача MANUAL-OUTLIERS-1, 2026-10-15,
постановка тимлида): остановка «Выбросы» модуля «Предобработка» получает
режим ручной корректировки датасета по паттерну MANUAL-MISSING-1 --
аналитик восстановил данные из-за ошибки ввода и правит ячейки руками
(перенос функционала legacy app.py: radio-фильтр «Все/Только выбросы/
Только норма» → st.data_editor с маркировкой «Выброс/Норма» →
«💾 Сохранить» (df.update(edited_df)), блок ~8256-8334) с улучшениями.

Новые аддитивные контракты (существующие не затрагиваются):

1. GET /v1/session/dataset/outlier-editor-rows -- источник строк редактора:
   окна по offset/limit; outliers_only=True -- только строки хотя бы с одним
   выбросом; маска -- числовые колонки КАНОНИЧЕСКОЙ области (PROGR-24-
   ORIGIN-A: производные не окрашивают остановку) в КАРДОЧНОЙ шкале
   iqr-1.5 -- той же, что у карточки Обзора и статуса остановки (профиль
   фиксированным методом карточки, PROGR-23); ПОЗИЦИОННЫЕ row_index
   исходного датафрейма; ячейки -- JSON-нативно: None для NaN/None, числа
   для numeric-колонок, строки для остальных (переиспользование
   _editor_cell_value/semantic-классификации MANUAL-MISSING-1 -- вторая
   реализация семантики запрещена).
2. POST /v1/session/dataset/outlier-manual-corrections -- применение правок:
   ячеечные правки (row_index, column, value) на КОПИИ; тот же контракт
   применения, что у пропусков (last-wins на дубли; numeric -- честная 422
   на неприводимое значение; счётчик total_changed -- ФАКТИЧЕСКИ
   изменившиеся ячейки; no-op apply не повышает data_revision -- AUDIT-C;
   apply=False -- валидация и счётчики без сохранения). None/"" = очистка
   в NaN честно и здесь: аналитик может решить, что значение -- ошибка
   ввода вообще без замены (пропуск подхватит остановка «Пропуски»).
   Профиль ПОСЛЕ и счётчики выбросов -- кард-шкала (iqr-1.5) канонической
   области: редактор живёт в шкале карточки, у мастера выбросов шкала
   выбирается методом -- здесь метода нет, честная фиксированная шкала.
   derived_summary в ответе НЕТ: ячеечные правки структурно не добавляют
   колонок, производный состав не меняется (fresh derived_summary отдаёт
   GET /dataset/outlier-profile, который Обзор перечитывает каскадом
   datasetVersion).

Корпус дизъюнктен существующим сюитам (метеостанция с выбросами:
recorded_at/temp_c/humidity/sensor_id; выбросы iqr-1.5 в temp_c на
строках 1 и 8; dataset_id не пинится -- свой CSV в каждой проверке).
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
    """12 строк метеостанции: выбросы iqr-1.5 в temp_c на строках 1 (41.0)
    и 8 (-8.0); humidity и sensor_id чистые. Q1=12.75, Q3=13.425,
    границы [11.7375, 14.4375] -- только 41.0 и -8.0 за пределами."""
    return pd.DataFrame(
        {
            "recorded_at": [f"2024-06-{d:02d}" for d in range(1, 13)],
            "temp_c": [12.5, 41.0, 13.1, 12.8, 13.4, 12.9, 13.7, 12.6, -8.0, 13.2, 13.0, 13.5],
            "humidity": [58.0, 61.5, 60.0, 57.5, 59.0, 62.0, 63.0, 55.0, 63.0, 58.5, 60.5, 57.0],
            "sensor_id": [f"MS-{i:02d}" for i in range(1, 13)],
        }
    )


def _spike_df() -> pd.DataFrame:
    """12 строк (порог _MIN_SAMPLE_SIZE=10), выброс в колонке b на строке
    11 (500.0; границы iqr-1.5 [-4.5, 17.5]): маска редактора обязана
    ловить выброс ЛЮБОЙ числовой колонки канонической области, не только
    первой."""
    return pd.DataFrame(
        {
            "day": [f"2024-07-{d:02d}" for d in range(1, 13)],
            "b": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 500.0],
        }
    )


def _upload_df(df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    resp = client.post("/v1/internal/upload", files={"file": ("weather-outliers.csv", buf, "text/csv")})
    assert resp.status_code == 200, resp.text


def _current() -> dict:
    resp = client.get("/v1/session/current")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── 1. GET /dataset/outlier-editor-rows: контракт окна ───────────────


def test_outlier_editor_rows_404_without_dataset():
    resp = client.get("/v1/session/dataset/outlier-editor-rows")
    assert resp.status_code == 404, resp.text


def test_outlier_editor_rows_full_scope_window_and_meta():
    df = _weather_df()
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/outlier-editor-rows",
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


def test_outlier_editor_rows_cells_json_native_honest():
    """None для NaN (не строка 'nan'!), числа в numeric, строки в text."""
    df = _weather_df()
    df.loc[2, "humidity"] = np.nan  # честный NaN в не-выбросной ячейке
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/outlier-editor-rows",
        params={"offset": 1, "limit": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # строка 1: temp_c = 41.0 (выброс) -- число, не строка
    row1 = body["rows"][0]
    assert row1["row_index"] == 1
    assert row1["cells"][0] == "2024-06-02"
    assert row1["cells"][1] == 41.0
    assert row1["cells"][3] == "MS-02"
    # строка 2: humidity = NaN → None (честное отличие от строкового 'nan')
    row2 = body["rows"][1]
    assert row2["cells"][2] is None


def test_outlier_editor_rows_outliers_only_original_indices_and_counters():
    """outliers_only=True: только строки хотя бы с одним выбросом
    (маска iqr-1.5 канонической области), row_index -- ПОЗИЦИИ исходного
    датафрейма (не подряд), total_rows -- счётчик отфильтрованного
    множества."""
    df = _weather_df()
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/outlier-editor-rows",
        params={"offset": 0, "limit": 50, "outliers_only": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # выбросы: строки 1 (41.0) и 8 (-8.0) -- ровно 2
    assert body["total_rows"] == 2
    assert [r["row_index"] for r in body["rows"]] == [1, 8]
    assert body["has_more"] is False
    # ячейки строки 1 несут исходные значения всей строки
    row1 = body["rows"][0]
    assert row1["cells"][1] == 41.0
    assert row1["cells"][2] == 61.5


def test_outlier_editor_rows_outliers_only_pagination_over_filtered_sequence():
    """Пагинация поверх ОТФИЛЬТРОВАННОЙ последовательности: окно
    [offset, offset+limit) фильтра, а не исходного датафрейма."""
    df = _weather_df()
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/outlier-editor-rows",
        params={"offset": 1, "limit": 1, "outliers_only": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 2
    assert body["returned"] == 1
    assert body["offset"] == 1
    assert [r["row_index"] for r in body["rows"]] == [8]
    assert body["has_more"] is False


def test_outlier_editor_rows_outliers_only_empty_when_no_outliers():
    """Датасет без выбросов: outliers_only даёт честное пустое окно
    (total_rows=0, returned=0), не ошибку."""
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 2.5, 1.5], "b": ["x", "y", "z", "w", "v"]})
    _upload_df(df)
    resp = client.get(
        "/v1/session/dataset/outlier-editor-rows",
        params={"offset": 0, "limit": 50, "outliers_only": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 0
    assert body["returned"] == 0
    assert body["rows"] == []
    assert body["has_more"] is False


def test_outlier_editor_rows_mask_covers_any_numeric_column():
    """Маска -- ИЛИ по всем числовым колонкам канонической области:
    выброс в ЛЮБОЙ колонке включает строку (не только в первой)."""
    _upload_df(_spike_df())
    resp = client.get(
        "/v1/session/dataset/outlier-editor-rows",
        params={"offset": 0, "limit": 50, "outliers_only": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 1
    assert [r["row_index"] for r in body["rows"]] == [11]
    assert body["rows"][0]["cells"][1] == 500.0


def test_outlier_editor_rows_mask_ignores_derived_columns():
    """PROGR-24-ORIGIN-A: производные колонки не окрашивают остановку --
    маска outliers_only считается по КАНОНИЧЕСКОЙ области. Производная
    флаг-колонка (humidity_missing_flag, 1.0 на строке 3) дискриминирует:
    учтись она в маске -- строка 3 попала бы в окно (границы [0,0] делают
    единицу выбросом), но по канонической области строка 3 чиста."""
    df = _weather_df()
    df.loc[3, "humidity"] = np.nan  # пропуск БЕЗ выброса на строке 3
    _upload_df(df)
    # официальная apply-операция регистрирует флаг-колонку как ПРОИЗВОДНУЮ
    flag_resp = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["humidity"], "strategy": "flag", "apply": True},
    )
    assert flag_resp.status_code == 200, flag_resp.text
    assert "humidity_missing_flag" in flag_resp.json()["added_columns"]

    resp = client.get(
        "/v1/session/dataset/outlier-editor-rows",
        params={"offset": 0, "limit": 50, "outliers_only": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # только канонические выбросы temp_c (1, 8); строка 3 (флаг производной
    # в окне) НЕ включена -- маска по канонической области
    assert body["total_rows"] == 2
    assert [r["row_index"] for r in body["rows"]] == [1, 8]


# ── 2. POST /dataset/outlier-manual-corrections: применение правок ───


def test_outlier_manual_correction_numeric_edit_fixes_outliers():
    """Правка ячеек numeric-колонок: выбросы → нормальные значения;
    счётчики честные (before/after в кард-шкале); профиль ПОСЛЕ отражает
    исправление; ревизия повышена (AUDIT-C: фактическое изменение)."""
    df = _weather_df()
    _upload_df(df)
    before = _current()
    assert before["data_revision"] == 0

    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={
            "edits": [
                {"row_index": 1, "column": "temp_c", "value": 13.3},
                {"row_index": 8, "column": "temp_c", "value": 13.05},
            ],
            "apply": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["total_edited_requested"] == 2
    assert body["total_changed"] == 2
    assert body["total_outliers_before"] == 2
    assert body["total_outliers_after"] == 0
    profile_cols = {item["column"]: item for item in body["profile"]}
    assert profile_cols["temp_c"]["outlier_count"] == 0
    assert profile_cols["humidity"]["outlier_count"] == 0

    after = _current()
    assert after["data_revision"] == 1  # AUDIT-C: фактическое изменение

    # значения действительно в датасете (через строковое окно /dataset/rows)
    rows1 = client.get("/v1/session/dataset/rows", params={"offset": 1, "limit": 1}).json()
    assert rows1["rows"][0][1] == "13.3"
    rows8 = client.get("/v1/session/dataset/rows", params={"offset": 8, "limit": 1}).json()
    assert rows8["rows"][0][1] == "13.05"


def test_outlier_manual_correction_fix_one_outlier_narrows_mask():
    """Исправление одного выброса сужает outliers_only-окно честно:
    маска пересчитывается по фактическому состоянию датасета."""
    df = _weather_df()
    _upload_df(df)

    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={"edits": [{"row_index": 1, "column": "temp_c", "value": 13.3}], "apply": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_outliers_before"] == 2
    assert body["total_outliers_after"] == 1

    view = client.get(
        "/v1/session/dataset/outlier-editor-rows",
        params={"offset": 0, "limit": 50, "outliers_only": "true"},
    ).json()
    assert [r["row_index"] for r in view["rows"]] == [8]
    assert view["total_rows"] == 1


def test_outlier_manual_correction_text_edit_and_clear_to_nan():
    """Текстовая правка сохраняется как строка; пустое значение (null и
    "") очищает ячейку в NaN -- аналитик честно решает, что значение --
    ошибка ввода без замены (пропуск подхватит остановка «Пропуски»)."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={
            "edits": [
                {"row_index": 0, "column": "sensor_id", "value": "MS-01-REPLACED"},
                {"row_index": 2, "column": "humidity", "value": None},
                {"row_index": 3, "column": "sensor_id", "value": ""},
            ],
            "apply": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_changed"] == 3
    assert body["applied"] is True
    # выбросы не изменились (temp_c не тронут)
    assert body["total_outliers_before"] == 2
    assert body["total_outliers_after"] == 2

    rows = client.get("/v1/session/dataset/rows", params={"offset": 0, "limit": 4}).json()
    assert rows["rows"][0][3] == "MS-01-REPLACED"
    assert rows["rows"][2][2] == "nan"  # очистка → NaN → строковое 'nan'
    assert rows["rows"][3][3] == "nan"


def test_outlier_manual_correction_noop_edit_does_not_bump_revision():
    """Перебор того же числа -- no-op: total_changed=0, ревизия НЕ
    повышается (AUDIT-C, «no-op apply не выдаётся за изменённые данные»)."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={"edits": [{"row_index": 0, "column": "temp_c", "value": 12.5}], "apply": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_edited_requested"] == 1
    assert body["total_changed"] == 0
    assert _current()["data_revision"] == 0


def test_outlier_manual_correction_last_wins_on_duplicate_cell():
    """Две правки одной ячейки в одном запросе -- last-wins, меняется
    один раз (одна ячейка = один факт изменения)."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={
            "edits": [
                {"row_index": 1, "column": "temp_c", "value": 10.0},
                {"row_index": 1, "column": "temp_c", "value": 13.3},
            ],
            "apply": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_changed"] == 1
    rows = client.get("/v1/session/dataset/rows", params={"offset": 1, "limit": 1}).json()
    assert rows["rows"][0][1] == "13.3"


def test_outlier_manual_correction_preview_apply_false_does_not_change_session():
    """apply=False -- валидация и счётчики БЕЗ сохранения: applied=false,
    датасет и ревизия не тронуты."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={"edits": [{"row_index": 1, "column": "temp_c", "value": 13.3}], "apply": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is False
    assert body["total_changed"] == 1
    assert body["total_outliers_after"] == 1  # гипотетический счётчик
    assert _current()["data_revision"] == 0
    # значение НЕ применено
    rows = client.get("/v1/session/dataset/rows", params={"offset": 1, "limit": 1}).json()
    assert rows["rows"][0][1] == "41.0"


def test_outlier_manual_correction_invalid_numeric_honest_422():
    """Неприводимое значение в numeric-колонку -- честная 422 с указанием
    колонки и строки; сессия не меняется."""
    df = _weather_df()
    _upload_df(df)
    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={"edits": [{"row_index": 2, "column": "temp_c", "value": "abc"}], "apply": True},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "temp_c" in detail and "abc" in detail
    assert _current()["data_revision"] == 0


def test_outlier_manual_correction_validation_errors():
    df = _weather_df()
    _upload_df(df)

    # неизвестная колонка
    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={"edits": [{"row_index": 0, "column": "no_such_col", "value": "x"}], "apply": True},
    )
    assert resp.status_code == 422, resp.text
    assert "no_such_col" in resp.json()["detail"]

    # строка за пределами датасета
    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={"edits": [{"row_index": 99, "column": "temp_c", "value": 1.0}], "apply": True},
    )
    assert resp.status_code == 422, resp.text

    # пустой список правок (min_length=1)
    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={"edits": [], "apply": True},
    )
    assert resp.status_code == 422, resp.text


def test_outlier_editor_then_fix_via_editor_flow():
    """Сквозной сценарий редактора: outliers_only-окно показывает ровно
    строки с выбросами; правки по исходным позициям; после apply окно
    перечитывается честно (сузилось до фактических выбросов)."""
    df = _weather_df()
    _upload_df(df)

    # редактор в фильтре «Только с выбросами» видит ровно проблемные строки
    view = client.get(
        "/v1/session/dataset/outlier-editor-rows",
        params={"offset": 0, "limit": 50, "outliers_only": "true"},
    ).json()
    assert [r["row_index"] for r in view["rows"]] == [1, 8]

    # аналитик исправляет temp_c строк 1 и 8 прямо из этого окна
    resp = client.post(
        "/v1/session/dataset/outlier-manual-corrections",
        json={
            "edits": [
                {"row_index": 1, "column": "temp_c", "value": 13.3},
                {"row_index": 8, "column": "temp_c", "value": 13.05},
            ],
            "apply": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_outliers_after"] == 0

    # после apply окно «Только с выбросами» честно опустело
    view2 = client.get(
        "/v1/session/dataset/outlier-editor-rows",
        params={"offset": 0, "limit": 50, "outliers_only": "true"},
    ).json()
    assert view2["rows"] == []
    assert view2["total_rows"] == 0
