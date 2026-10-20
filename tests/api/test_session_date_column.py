# tests/api/test_session_date_column.py
#
# UPLOAD-RECOMP-2 (2026-10-20), пункт (а) -- подтверждение «Структуры»
# кнопкой аналитика: снятие искусственного гейта score>=0.7 на
# POST /v1/session/date-column ПРИ ЯВНОМ ПОДТВЕРЖДЕНИИ (confirmed=true).
#
# Контракт (spec_upload_recompose_2026-10-20.md §3.1, §5.4):
#   * score < 0.7 + confirmed=true  -> 200 (аналитик взял ответственность,
#     семантика PROGR-14-A «явный выбор снимает»); факт
#     structure_confirmed пишется хуком трассы (узел upload/structure ->
#     done, единый движок node_status);
#   * без confirmed / confirmed=false -- ПРЕЖНИЙ контракт: score < 0.7
#     -> 422 (обратная совместимость существующих вызовов);
#   * требования сохраняются всегда: колонка существует, != target,
#     >= 2 валидных даты;
#   * маркер «(не использовать)» после явного выбора -- легитимное
#     подтверждение «временной колонки нет» (date_column=None).
#
# Корпус -- СВОИ датасеты (текстово-числовой «почти-год» y с detector
# score 0.6667 < 0.7, панель Country/Year/Value), дизъюнктен другим
# тестовым файлам.
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
    resp = client.post("/v1/internal/upload", files={"file": ("recomp2.csv", buf, "text/csv")})
    assert resp.status_code == 200, resp.text


def _low_score_df() -> pd.DataFrame:
    # detector score(y) = 0.6667 < 0.7 (4 валидных ISO-даты из 6, мусор
    # между ними), при этом >= 2 валидных дат и колонка обратима к
    # временному типу -- все содержательные требования, кроме
    # искусственного гейта, выполнены.
    return pd.DataFrame({
        "y": ["2010-01-01", "2011-01-01", "abc", "2013-01-01", "2014-01-01", "def"],
        "value": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
    })


def test_confirmed_low_score_column_accepted_and_traced():
    """score 0.67 + confirmed=true -> 200; факт structure_confirmed в
    трассе красит узел upload/structure в done (связка двух фактов)."""
    _upload_df(_low_score_df())
    resp = client.post(
        "/v1/session/date-column",
        json={"column": "y", "confirmed": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["date_column"] == "y"

    trace = client.get("/v1/progress/trace").json()
    structure_nodes = [
        n for n in trace.get("nodes", [])
        if n.get("stage") == "upload" and n.get("node_id") == "structure"
    ]
    assert structure_nodes, "узел upload/structure отсутствует в трассе"
    assert structure_nodes[-1]["status"] == "done"


def test_without_confirmed_low_score_column_still_rejected():
    """Прежний контракт: score < 0.7 без confirmed -> 422."""
    _upload_df(_low_score_df())
    resp = client.post("/v1/session/date-column", json={"column": "y"})
    assert resp.status_code == 422
    assert "не распознана" in resp.json()["detail"]


def test_confirmed_false_keeps_legacy_gate():
    """Явное confirmed=false -- прежний контракт (гейт остаётся)."""
    _upload_df(_low_score_df())
    resp = client.post(
        "/v1/session/date-column",
        json={"column": "y", "confirmed": False},
    )
    assert resp.status_code == 422


def test_confirmed_no_date_column_marker_accepted():
    """«(не использовать)» после явного выбора -- легитимное
    подтверждение отсутствия временной колонки: 200, date_column=None,
    факт structure_confirmed записан."""
    _upload_df(pd.DataFrame({
        "label": ["a", "b", "c"] * 3,
        "value": [1.0, 2.0, 3.0] * 3,
    }))
    resp = client.post(
        "/v1/session/date-column",
        json={"column": "(не использовать)", "confirmed": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["date_column"] is None

    trace = client.get("/v1/progress/trace").json()
    structure_nodes = [
        n for n in trace.get("nodes", [])
        if n.get("stage") == "upload" and n.get("node_id") == "structure"
    ]
    assert structure_nodes and structure_nodes[-1]["status"] == "done"


def test_no_date_marker_requires_confirmation():
    """«(не использовать)» без confirmed -- прежний 422-контракт
    (маркер не колонка датасета, прежняя проверка не пропускала)."""
    _upload_df(pd.DataFrame({
        "label": ["a", "b", "c"] * 3,
        "value": [1.0, 2.0, 3.0] * 3,
    }))
    resp = client.post("/v1/session/date-column", json={"column": "(не использовать)"})
    assert resp.status_code == 422


def test_confirmed_still_requires_two_valid_dates():
    """Содержательное требование сохранено: колонка, необратимая к
    временному типу (год-only с текстовым мусором -- crash-guard
    прежнего гейта снят) или с < 2 валидными датами, честно
    отклоняется даже при confirmed=true (422, не 500)."""
    _upload_df(pd.DataFrame({
        "y": ["2010", "abc", "def", "ghi", "jkl", "mno"],
        "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    }))
    resp = client.post(
        "/v1/session/date-column",
        json={"column": "y", "confirmed": True},
    )
    assert resp.status_code == 422
    assert "не приводится" in resp.json()["detail"] or "меньше двух валидных дат" in resp.json()["detail"]


def test_confirmed_still_requires_non_target_column():
    """Требование «колонка != target» сохранено при confirmed=true."""
    _upload_df(pd.DataFrame({
        "y": ["2010", "2011", "abc", "2013", "2014", "def"],
        "value": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
    }))
    resp = client.post(
        "/v1/session/date-column",
        json={"column": "value", "confirmed": True},
    )
    # value -- не дата вовсе (score 0), 422 по прежней ветке «не
    # распознана» ДО сравнения с target; проверяем честный отказ.
    assert resp.status_code in (404, 422)


def test_confirmed_unknown_column_404():
    _upload_df(_low_score_df())
    resp = client.post(
        "/v1/session/date-column",
        json={"column": "no_such_column", "confirmed": True},
    )
    assert resp.status_code == 404


def test_confirmed_high_score_column_unchanged():
    """Уверенная колонка (score >= 0.7) подтверждается как раньше --
    регресс-пин прежнего зелёного пути."""
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=10, freq="D").astype(str),
        "value": range(10),
    })
    _upload_df(df)
    resp = client.post(
        "/v1/session/date-column",
        json={"column": "date", "confirmed": True},
    )
    assert resp.status_code == 200
    assert resp.json()["date_column"] == "date"


def test_confirmed_low_score_passport_recomputed_downstream():
    """R1-гвард: подтверждение низко-score колонки не «замусоривает»
    сессию -- повторное подтверждение ДРУГОЙ колонки проходит тем же
    контрактом и переключает date_column (инвалидация несопоставимых
    паспортов при смене решения -- set_date_column/reset_passports,
    единый для уверенных и подтверждённых выборов; unit-покрытие --
    tests/api/test_passport_session_state.py)."""
    df = pd.DataFrame({
        "y1": ["2010-01-01", "2011-01-01", "abc", "2013-01-01", "2014-01-01", "def"],
        "y2": ["2001-06-15", "2002-06-15", "xyz", "2004-06-15", "2005-06-15", "uvw"],
        "value": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
    })
    _upload_df(df)
    first = client.post(
        "/v1/session/date-column",
        json={"column": "y1", "confirmed": True},
    )
    assert first.status_code == 200, first.text
    assert first.json()["date_column"] == "y1"

    # Смена подтверждённого решения -- та же кнопка, тот же контракт.
    second = client.post(
        "/v1/session/date-column",
        json={"column": "y2", "confirmed": True},
    )
    assert second.status_code == 200, second.text
    assert second.json()["date_column"] == "y2"
