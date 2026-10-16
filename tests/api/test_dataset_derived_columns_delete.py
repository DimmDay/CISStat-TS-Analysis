# tests/api/test_dataset_derived_columns_delete.py
"""
Интеграционные тесты POST /v1/session/dataset/derived-columns/delete --
сохранение удаления добавленных (производных) колонок из «Редактора
датасета» (дефект-репорт тимлида к DATASET-VIEW-EDITOR-1, 2026-10-16).

Сценарий дефекта: стратегия остановки добавляет в датасет 3 колонки,
аналитик идёт на следующую остановку, стратегия которой рекомендует
удалить одну из добавленных; аналитик удаляет её в «Редакторе датасета»,
но СОХРАНИТЬ не может -- справа от «Вернуть все колонки» нет кнопки
«Сохранить», а на бэкенде НЕТ ни одного эндпоинта, удаляющего колонки
(скрытие в v1 -- клиентское, представления; датасет не менялся).

Контракт сохранения:
- удалять МОЖНО ТОЛЬКО добавленные колонки, присутствующие в датафрейме
  (реестр ∩ кадр, derived_columns_in_frame): исходные (канонические)
  колонки НЕ удаляемы -- 422, датасет не мутирует (главная гарантия
  безопасности источника данных);
- замена датафрейма -- ЕДИНАЯ ТОЧКА set_dataframe (ревизия данных
  повышается ТОЛЬКО при фактическом изменении контента);
- каскад реестра: намеренное удаление через редактор убирает записи из
  session.derived_columns (unregister_derived_columns) -- реестр остаётся
  согласован с фактом; записи о колонках, удалённых МИМО реестра, по-
  прежнему безвредны (append-only совместимость column_origin.py);
- счётчики session.dataset обновляются, touch+save персистируют;
- 404 без активного датасета; 422 на пустой список, неизвестную колонку,
  каноническую колонку, отсутствующую в кадре запись реестра.
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
DELETE_URL = "/v1/session/dataset/derived-columns/delete"


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _three_predictor_frame() -> pd.DataFrame:
    """Детерминированный кадр с тремя числовыми предикторами (с пропусками
    в каждом -- иначе флаг-стратегия колонок не создаёт): стратегия 1
    (флаг-коррекция пропусков по трём колонкам) добавит ровно 3 колонки --
    преамбула сценария дефекта."""
    n = 40
    t = np.arange(n, dtype=float)
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
            "value": np.round(100 + 0.5 * t, 2),
            "temp": np.round(10 + np.sin(t / 5.0), 2),
            "humidity": np.round(60 + np.cos(t / 7.0), 2),
        }
    )
    frame.loc[[3, 17], "value"] = np.nan
    frame.loc[[5, 21], "temp"] = np.nan
    frame.loc[[7, 25], "humidity"] = np.nan
    return frame


def _upload(frame: pd.DataFrame, name: str = "frame.csv") -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _strategy1_adds_three_columns() -> list[str]:
    """Пролог сценария: стратегия «Пропуски» (flag) на трёх колонках --
    в датасете три производные флаг-колонки (реестр знает все три)."""
    _upload(_three_predictor_frame())
    resp = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["value", "temp", "humidity"], "strategy": "flag", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    added = resp.json()["added_columns"]
    assert added == ["value_missing_flag", "temp_missing_flag", "humidity_missing_flag"]
    registry = client.get(URL).json()
    assert registry["total"] == 3
    return added


def _session():
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id, "у тестового клиента нет cookie сессии"
    return get_session_store().get(session_id)


def _data_revision() -> int:
    return int(_session().data_revision)


# ── Гейты входа ──────────────────────────────────────────────────────


def test_404_without_dataset():
    """Без активного датасета -- честная 404 (тот же гейт, что у GET
    derived-columns и /dataset/rows)."""
    resp = client.post(DELETE_URL, json={"columns": ["whatever"]})
    assert resp.status_code == 404


def test_422_empty_columns_list():
    """Пустой список -- 422: сохранение без удаляемых колонок лишено
    смысла (фронт держит кнопку disabled, бэкенд валидирует повторно)."""
    _strategy1_adds_three_columns()
    resp = client.post(DELETE_URL, json={"columns": []})
    assert resp.status_code == 422


def test_422_canonical_column_rejected_dataset_untouched():
    """Главная гарантия безопасности: ИСХОДНУЮ (каноническую) колонку
    удалить нельзя -- 422, датасет не мутирует (состав колонок и
    data_revision без изменений)."""
    _strategy1_adds_three_columns()
    before_revision = _data_revision()
    before_columns = list(_session().dataframe.columns)

    resp = client.post(DELETE_URL, json={"columns": ["temp"]})
    assert resp.status_code == 422
    assert "temp" in resp.json()["detail"]

    session = _session()
    assert list(session.dataframe.columns) == before_columns
    assert _data_revision() == before_revision


def test_422_unknown_column_rejected():
    """Несуществующая колонка -- 422 с честным перечислением offending-имён."""
    _strategy1_adds_three_columns()
    resp = client.post(DELETE_URL, json={"columns": ["no_such_column"]})
    assert resp.status_code == 422
    assert "no_such_column" in resp.json()["detail"]


def test_422_mixed_request_rejected_entirely():
    """Смешанный запрос (производная + каноническая) отклоняется ЦЕЛИКОМ:
    частичное применение маскировало бы отказ по остальным именам."""
    _strategy1_adds_three_columns()
    before_columns = list(_session().dataframe.columns)
    resp = client.post(DELETE_URL, json={"columns": ["temp_missing_flag", "temp"]})
    assert resp.status_code == 422
    assert list(_session().dataframe.columns) == before_columns


def test_422_stale_registry_entry_without_frame_column():
    """Запись реестра о колонке, которой нет в кадре (удалена мимо реестра),
    не делает колонку удаляемой -- 422 (реестр ∩ кадр, честное отсутствие)."""
    _strategy1_adds_three_columns()
    session = _session()
    session.dataframe = session.dataframe.drop(columns=["temp_missing_flag"])

    resp = client.post(DELETE_URL, json={"columns": ["temp_missing_flag"]})
    assert resp.status_code == 422


# ── Основной сценарий ────────────────────────────────────────────────


def test_delete_one_of_three_added_columns():
    """Ядро сценария дефекта: стратегия 1 добавила 3 колонки; сохранение
    удаления одной -- 200, deleted=[имя]; /dataset/rows больше НЕ отдаёт
    колонку; GET derived-columns -- total 2 (каскад реестра)."""
    _strategy1_adds_three_columns()

    resp = client.post(DELETE_URL, json={"columns": ["temp_missing_flag"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] == ["temp_missing_flag"]
    assert body["remaining_total"] == 2

    rows = client.get("/v1/session/dataset/rows", params={"offset": 0, "limit": 5}).json()
    assert "temp_missing_flag" not in rows["columns"]
    assert {"date", "value", "temp", "humidity", "value_missing_flag", "humidity_missing_flag"} == set(rows["columns"])

    registry = client.get(URL).json()
    names = [entry["column"] for entry in registry["columns"]]
    assert names == ["value_missing_flag", "humidity_missing_flag"]
    assert registry["total"] == 2


def test_registry_cascade_removes_entry():
    """Каскад реестра: намеренное удаление через редактор убирает запись
    из session.derived_columns (unregister_derived_columns) -- реестр
    согласован с фактом; исходные записи не затронуты."""
    _strategy1_adds_three_columns()
    session = _session()
    assert set(session.derived_columns) == {
        "value_missing_flag",
        "temp_missing_flag",
        "humidity_missing_flag",
    }

    resp = client.post(DELETE_URL, json={"columns": ["temp_missing_flag"]})
    assert resp.status_code == 200, resp.text
    assert set(session.derived_columns) == {"value_missing_flag", "humidity_missing_flag"}


def test_delete_bumps_data_revision_once():
    """ЕДИНАЯ ТОЧКА set_dataframe: фактическое удаление повышает ревизию
    данных ровно на единицу (digest до/после различаются)."""
    _strategy1_adds_three_columns()
    before = _data_revision()
    resp = client.post(DELETE_URL, json={"columns": ["temp_missing_flag"]})
    assert resp.status_code == 200, resp.text
    assert _data_revision() == before + 1


def test_delete_multiple_columns():
    """Сохранение удаления ДВУХ из трёх добавленных колонок одним
    «Сохранить»: обе удалены, реестр и кадр согласованы."""
    _strategy1_adds_three_columns()
    resp = client.post(
        DELETE_URL,
        json={"columns": ["humidity_missing_flag", "value_missing_flag"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] == ["humidity_missing_flag", "value_missing_flag"]
    assert body["remaining_total"] == 1

    rows = client.get("/v1/session/dataset/rows", params={"offset": 0, "limit": 5}).json()
    # Удалены ТОЛЬКО производные: канонические (включая humidity -- тёзку
    # удалённого флага) и temp_missing_flag остаются.
    assert set(rows["columns"]) == {"date", "value", "temp", "humidity", "temp_missing_flag"}

    registry = client.get(URL).json()
    assert [entry["column"] for entry in registry["columns"]] == ["temp_missing_flag"]


def test_duplicate_names_in_request_are_deduped():
    """Дубли имени в запросе не ломают drop и не удваивают ответ."""
    _strategy1_adds_three_columns()
    resp = client.post(DELETE_URL, json={"columns": ["temp_missing_flag", "temp_missing_flag"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == ["temp_missing_flag"]


def test_dataset_counters_updated_and_persisted():
    """Счётчики session.dataset обновлены (columns), touch+save выполнены:
    updated_at сдвинулся, повторное чтение сессии из хранилища отдаёт
    состав после удаления."""
    _strategy1_adds_three_columns()
    session = _session()
    columns_before = int(session.dataset.columns)
    updated_before = session.updated_at

    resp = client.post(DELETE_URL, json={"columns": ["temp_missing_flag"]})
    assert resp.status_code == 200, resp.text

    assert session.dataset.columns == columns_before - 1
    assert session.updated_at != updated_before

    reloaded = get_session_store().get(session.session_id)
    assert "temp_missing_flag" not in reloaded.dataframe.columns
    assert set(reloaded.derived_columns) == {"value_missing_flag", "humidity_missing_flag"}


def test_delete_then_readd_reregisters_fresh():
    """После сохранения удаления повторный apply той же операции заново
    регистрирует колонку (реестр -- зеркало факта, register_derived_columns
    сравнивает состав до/после): удаление не оставляет скрытых долгов."""
    _strategy1_adds_three_columns()
    assert client.post(DELETE_URL, json={"columns": ["temp_missing_flag"]}).status_code == 200
    assert client.get(URL).json()["total"] == 2

    # Стратегия 1 повторно (flag уже был -- флаг-колонки value/humidity
    # пересоздаются; temp_missing_flag появится заново).
    resp = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["temp"], "strategy": "flag", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["added_columns"] == ["temp_missing_flag"]

    registry = client.get(URL).json()
    names = [entry["column"] for entry in registry["columns"]]
    assert "temp_missing_flag" in names
    assert registry["total"] == 3


def test_response_contract_fields():
    """Контракт ответа: deleted -- список имён, remaining_total -- целое
    число оставшихся производных (не отрицательное, == факту)."""
    _strategy1_adds_three_columns()
    resp = client.post(DELETE_URL, json={"columns": ["value_missing_flag"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["deleted"], list) and body["deleted"] == ["value_missing_flag"]
    assert isinstance(body["remaining_total"], int)
    assert body["remaining_total"] == 2

    remaining = client.get(URL).json()["total"]
    assert body["remaining_total"] == remaining
