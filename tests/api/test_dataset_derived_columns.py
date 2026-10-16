# tests/api/test_dataset_derived_columns.py
"""
Интеграционные тесты GET /v1/session/dataset/derived-columns --
read-only реестр производных колонок сессии (задача DATASET-VIEW-EDITOR-1,
2026-10-16, проект решения в worklog10.md; постановка тимлида: кнопка
«Редактор датасета» в Мастера остановок, добавляющих колонки).

Контракт:
- источник истины -- реестр session.derived_columns (PROGR-24-ORIGIN-A),
  ПЕРЕСЕЧЁННЫЙ с фактическими колонками датафрейма
  (derived_columns_in_frame, append-only совместимость: запись о колонке,
  удалённой мимо реестра, не попадает в ответ);
- поля записи: column, stage, source, created_at; сортировка по created_at
  (порядок появления колонок в датасете);
- СТРОГО read-only: ни touch, ни save, ни set_dataframe -- двойной GET не
  меняет data_revision (мутационная безопасность R6 проекта решения);
- старые сессии/свежая загрузка без реестра -- columns: [], total: 0
  (честное отсутствие, задокументированная совместимость column_origin.py);
- 404 без активного датасета;
- /dataset/rows остаётся ЕДИНСТВЕННЫМ источником строк -- этот эндпоинт
  строк НЕ отдаёт (только метаданные колонок).
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

client = TestClient(app)

URL = "/v1/session/dataset/derived-columns"


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _g345_frame() -> pd.DataFrame:
    """Детерминированный кадр с пропуском и выбросом (аналог
    forecast_monitor_synthetic_n150.csv -- общий корпус серии PROGR)."""
    t = np.arange(150, dtype=float)
    value = 120 + 0.55 * t + 18 * np.sin(2.0 * np.pi * (t + 2) / 12.0)
    value[25] += 110  # выброс вверх
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2013-01-01", periods=150, freq="MS").strftime("%Y-%m-%d"),
            "value": np.round(value, 2),
        }
    )
    frame.loc[[45, 87], "value"] = np.nan  # пропуски
    return frame


def _upload(frame: pd.DataFrame, name: str = "frame.csv") -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _session():
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id, "у тестового клиента нет cookie сессии"
    return get_session_store().get(session_id)


def _data_revision() -> int:
    return int(_session().data_revision)


# ── Гейты контракта ──────────────────────────────────────────────────


def test_404_without_dataset():
    """Без активного датасета -- честная 404 (тот же гейт, что у /dataset/rows)."""
    resp = client.get(URL)
    assert resp.status_code == 404


def test_fresh_upload_empty_registry():
    """Свежая загрузка -- пустой реестр: columns: [], total: 0 (честное
    отсутствие производных колонок, НЕ ноль-заглушка)."""
    df = pd.DataFrame({"date": ["2024-01-01", "2024-02-01"], "value": [1.0, 2.0]})
    _upload(df)
    resp = client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == []
    assert body["total"] == 0


def test_missing_flag_registered_with_metadata():
    """После missing-flag -- {col}_missing_flag со stage=missing и
    source=missing_correction:flag:... (паттерн строки source роутера)."""
    _upload(_g345_frame())
    resp = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["value"], "strategy": "flag", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    added = resp.json()["added_columns"]
    assert added == ["value_missing_flag"]

    resp = client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    entry = body["columns"][0]
    assert entry["column"] == "value_missing_flag"
    assert entry["stage"] == "missing"
    assert entry["source"] == "missing_correction:flag:value"
    assert entry["created_at"], "created_at -- непустая метка времени"


def test_outlier_flag_registered_with_metadata():
    """После outlier-flag -- {col}_outlier_flag со stage=outliers."""
    _upload(_g345_frame())
    resp = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["value"], "strategy": "flag", "method": "iqr", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    added = resp.json()["added_columns"]
    assert added == ["value_outlier_flag"]

    resp = client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    entry = body["columns"][0]
    assert entry["column"] == "value_outlier_flag"
    assert entry["stage"] == "outliers"
    assert entry["source"].startswith("outlier_correction:flag:value")


def test_two_operations_ordered_by_created_at():
    """Две операции -- обе колонки, порядок ответа по created_at
    (порядок появления в датасете): сначала missing-flag, потом
    outlier-flag."""
    _upload(_g345_frame())
    r1 = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["value"], "strategy": "flag", "apply": True},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["value"], "strategy": "flag", "method": "iqr", "apply": True},
    )
    assert r2.status_code == 200, r2.text

    resp = client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    names = [entry["column"] for entry in body["columns"]]
    assert names == ["value_missing_flag", "value_outlier_flag"]
    # created_at монотонны по порядку ответа
    stamps = [entry["created_at"] for entry in body["columns"]]
    assert stamps == sorted(stamps)


def test_regularity_resampling_adds_no_columns():
    """Ресемплинг «Регулярности» НЕ добавляет колонок (AUDIT-NEWCOLS-1 H4:
    _resample восстанавливает исходный набор колонок; регистрация в роутере
    -- защитный no-op). Ответ -- columns: [] даже после apply."""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=10, freq="D").strftime("%Y-%m-%d"),
            "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        }
    )
    df.loc[3, "date"] = "2024-01-05"  # пропуск шага -- нерегулярность
    _upload(df)
    resp = client.get("/v1/session/dataset/preprocessing/regularity-profile")
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/v1/session/dataset/preprocessing/regularity-corrections",
        json={"strategy": "interpolate", "frequency": "D", "apply": True},
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == []
    assert body["total"] == 0


def test_strategies_without_new_columns_not_registered():
    """drop_rows (Пропуски) и cap (Выбросы) -- без новых колонок; реестр
    пуст, ответ -- columns: []."""
    _upload(_g345_frame())
    r1 = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["value"], "strategy": "drop_rows", "apply": True},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        "/v1/session/dataset/outlier-corrections",
        json={"columns": ["value"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
    )
    assert r2.status_code == 200, r2.text

    resp = client.get(URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == []
    assert body["total"] == 0


def test_get_is_read_only_data_revision_unchanged():
    """Мутационная безопасность (R6 проекта решения): двойной GET после
    мутаций НЕ меняет data_revision -- эндпоинт не трогает сессию
    (без touch/save/set_dataframe)."""
    _upload(_g345_frame())
    client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["value"], "strategy": "flag", "apply": True},
    )
    before = _data_revision()
    assert client.get(URL).status_code == 200
    assert client.get(URL).status_code == 200
    assert _data_revision() == before


def test_removed_beyond_registry_not_in_response():
    """Append-only ∩ присутствие (derived_columns_in_frame): запись реестра
    о колонке, удалённой мимо реестра, НЕ попадает в ответ. Ситуация
    документирована column_origin.py («реестр -- факультативные метаданные,
    а не истина в последней инстанции: устаревшая запись безвредна, т.к.
    область всегда пересекается с фактическими колонками датафрейма"):
    симулируем прямую мутацию датафрейма сессии (drop) -- реестр остаётся
    append-only, ответ честно пересекает его с фактом."""
    _upload(_g345_frame())
    r1 = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["value"], "strategy": "flag", "apply": True},
    )
    assert r1.status_code == 200, r1.text
    assert client.get(URL).json()["total"] == 1

    # Удаляем флаг-колонку МИМО реестра (прямая мутация dataframe сессии --
    # вне 20 точек set_dataframe; тест хранилища test_status_original_series
    # использует тот же приём прямого доступа к сессии).
    session = _session()
    session.dataframe = session.dataframe.drop(columns=["value_missing_flag"])

    body = client.get(URL).json()
    names = [entry["column"] for entry in body["columns"]]
    assert "value_missing_flag" not in names, (
        "колонка, удалённая мимо реестра, не должна попадать в ответ "
        "(реестр ∩ фактические колонки датафрейма)"
    )


def test_response_matches_rows_contract_shapes():
    """Смежный контракт: /dataset/rows отдаёт строки ПОЛНОГО датасета
    (включая производные колонки) -- источник строк для сетки; этот
    эндпоинт -- ТОЛЬКО метаданные производных. Пин совместного
    использования: после missing-flag /dataset/rows видит колонку,
    derived-columns -- метаданные той же колонки."""
    _upload(_g345_frame())
    client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["value"], "strategy": "flag", "apply": True},
    )
    rows = client.get("/v1/session/dataset/rows", params={"offset": 0, "limit": 5}).json()
    assert "value_missing_flag" in rows["columns"], (
        "/dataset/rows читает живой session.dataframe -- производные колонки в ответе"
    )
    derived = client.get(URL).json()
    assert [e["column"] for e in derived["columns"]] == ["value_missing_flag"]
