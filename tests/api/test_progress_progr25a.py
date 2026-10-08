# tests/api/test_progress_progr25a.py
"""
PROGR-25-A: авто-фиксация исследуемого признака на бэкенде при загрузке.

Спека: spec_progress_target_column.md §4-A (сертифицированная редакция,
база main@3bd6044; план plan_progress_target_column.md §1).

Контракты задачи:
  - после upload И demo бэкенд фиксирует признак при ровно одном кандидате;
    кандидаты = числовые колонки фрейма − session.date_column − реестр
    производных (канон PROGR-24: по факту реестра, не по суффиксу);
  - событие target_column_changed сеется программно (прецедент
    run_resumed): payload {target_column, source:"auto"}, stage="validation",
    node_id=None; фиктивный вызов POST-маршрута запрещён;
  - неоднозначность (2+ кандидатов) -- честное «не выбран», события нет;
  - restore и set_dataset -- без изменений; ручной выбор -- source="user"
    (last-wins); старый корпус без source читается как user.

TDD RED → GREEN. Оракулы O1–O12; пометка «guard» -- оракул, который
зелёный уже до реализации (фиксирует честную семантику от регресса).
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    AnalysisSession,
    reset_session_store_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_store():
    """Изолируем тесты -- каждый стартует с пустым Memory store."""
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


client = TestClient(app)


def _upload_csv(csv_content: str, filename: str = "test.csv"):
    """Хелпер: загрузить CSV через internal endpoint."""
    file = io.BytesIO(csv_content.encode("utf-8"))
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (filename, file, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp


def _trace_events() -> list[dict]:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


def _target_column_changed(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("event_type") == "target_column_changed"]


# ── Датасеты ────────────────────────────────────────────────────────

CSV_ONE_NUMERIC = (
    "date,value\n"
    "2023-01-01,10.5\n"
    "2023-01-02,20.1\n"
    "2023-01-03,30.2\n"
)
CSV_TWO_NUMERIC = (
    "date,value,price\n"
    "2023-01-01,10.5,100\n"
    "2023-01-02,20.1,200\n"
    "2023-01-03,30.2,300\n"
)
CSV_YEAR_VALUE = (
    "year,value\n"
    "2021,10.5\n"
    "2022,20.1\n"
    "2023,30.2\n"
)


# ── O1: upload одной числовой → авто-фиксация source="auto" ─────────


class TestAutoFixOnUpload:
    def test_o1_current_reports_target_and_source_auto(self):
        """O1 (RED): upload → /current.target_column=value, source=auto."""
        _upload_csv(CSV_ONE_NUMERIC)
        resp = client.get("/v1/session/current")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_column"] == "value"
        assert data["target_column_source"] == "auto"

    def test_o1b_target_column_endpoint_reports_source_auto(self):
        """O1b (RED): GET /target-column зеркалит target_column_source."""
        _upload_csv(CSV_ONE_NUMERIC)
        resp = client.get("/v1/session/target-column")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_column"] == "value"
        assert data["target_column_source"] == "auto"

    def test_o2_seeds_target_column_changed_event(self):
        """O2 (RED): upload сеет target_column_changed {target_column,
        source:"auto"}, stage=validation, node_id=None; run_id общий
        с upload_completed (первая запись трассы фиксирует run_id)."""
        _upload_csv(CSV_ONE_NUMERIC)
        events = _trace_events()
        fixed = _target_column_changed(events)
        assert len(fixed) == 1, f"ожидалось ровно одно событие, есть: {len(fixed)}"
        event = fixed[0]
        assert event["stage"] == "validation"
        assert event["node_id"] is None
        assert event["payload"] == {"target_column": "value", "source": "auto"}
        upload_completed = [e for e in events if e.get("event_type") == "upload_completed"]
        assert upload_completed, "upload_completed отсутствует в трассе"
        assert event["run_id"] == upload_completed[0]["run_id"]
        assert event["run_id"] != ""

    def test_o11_payload_is_exactly_target_and_source(self):
        """O11 (RED): payload события авто -- ровно {target_column, source}
        (без расширения канона фактов)."""
        _upload_csv(CSV_ONE_NUMERIC)
        event = _target_column_changed(_trace_events())[0]
        assert set(event["payload"].keys()) == {"target_column", "source"}

    def test_o3_two_numerics_honest_ambiguity(self):
        """O3 (RED): две числовые → фиксации нет, события нет."""
        _upload_csv(CSV_TWO_NUMERIC)
        data = client.get("/v1/session/current").json()
        assert data["target_column"] is None
        assert data["target_column_source"] is None
        assert _target_column_changed(_trace_events()) == []

    def test_o12_year_value_without_registered_date_is_ambiguous(self):
        """O12 (RED): имя-исключение date-подобных СНЯТО (R4) --
        [year,value] без зарегистрированной даты -- два кандидата:
        фиксации нет; рекомендация = первый кандидат (year)."""
        _upload_csv(CSV_YEAR_VALUE)
        data = client.get("/v1/session/current").json()
        assert data["target_column"] is None
        assert data["target_column_source"] is None
        assert _target_column_changed(_trace_events()) == []
        suggestion = client.get("/v1/session/target-column").json()["suggested_column"]
        assert suggestion == "year"

    def test_reupload_autofixes_new_dataset(self):
        """Спека-пин: re-upload → set_dataset сбрасывает цель и трассу
        слоя 1 (канон PROGR-3: новый датасет = новое исследование),
        правило фиксирует заново по НОВОМУ фрейму (обновлённый контракт
        TestTargetColumnResetOnReupload, см. правки в test_target_column.py)."""
        _upload_csv(CSV_ONE_NUMERIC)
        other_csv = "ts,price\n2023-01-01,100\n2023-01-02,200\n2023-01-03,300\n"
        _upload_csv(other_csv, "other.csv")
        data = client.get("/v1/session/current").json()
        assert data["target_column"] == "price"
        assert data["target_column_source"] == "auto"
        # трасса слоя 1 перезапущена set_dataset: ровно одно событие
        # фиксации -- от НОВОЙ загрузки (старая трасса вытеснена каноном)
        fixed = _target_column_changed(_trace_events())
        assert len(fixed) == 1
        assert fixed[0]["payload"] == {"target_column": "price", "source": "auto"}


# ── O4: demo-эндпоинт применяет то же правило ───────────────────────


class TestDemoEndpointRule:
    def test_o4_demo_builtin_sales_demo_is_ambiguous_guard(self):
        """O4 (guard): встроенный sales_demo.csv имеет ДВЕ числовые
        (sales, profit) -- правило даёт честное «не выбран», события нет.
        Пин от регресса: правило ПРИМЕНЯЕТСЯ и на demo-пути (R2)."""
        resp = client.post("/v1/session/demo")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["has_active_dataset"] is True
        assert data["target_column"] is None
        assert data["target_column_source"] is None
        assert _target_column_changed(_trace_events()) == []

    def test_o4b_manual_fix_after_demo_works(self):
        """Demo → ручной выбор → source=user (селектор остаётся путём)."""
        client.post("/v1/session/demo")
        resp = client.post("/v1/session/target-column", json={"column": "sales"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["target_column"] == "sales"
        assert data["target_column_source"] == "user"


# ── O5: ручной выбор после авто -- last-wins, source=user ───────────


class TestManualAfterAuto:
    def test_o5_manual_after_auto_is_user(self):
        """O5 (RED): ручной выбор после авто → source="user"."""
        _upload_csv(CSV_ONE_NUMERIC)
        assert client.get("/v1/session/current").json()["target_column_source"] == "auto"
        resp = client.post("/v1/session/target-column", json={"column": "value"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_column"] == "value"
        assert data["target_column_source"] == "user"
        # /current зеркалит
        assert client.get("/v1/session/current").json()["target_column_source"] == "user"

    def test_o5b_manual_event_payload_has_no_source_legacy_semantics(self):
        """Guard: событие ручного маршрута (hook по TRACE_ROUTES) --
        payload без source (ответ маршрута не несёт ключ source) --
        читается потребителями как user (обратная совместимость)."""
        _upload_csv(CSV_ONE_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})
        manual_events = [
            e for e in _target_column_changed(_trace_events())
            if e["payload"].get("source") != "auto"
        ]
        assert len(manual_events) == 1
        assert "source" not in manual_events[0]["payload"]
        assert manual_events[0]["payload"]["target_column"] == "value"


# ── O6/O7/O8/O9: юнит-контракты единой точки правила ─────────────────


class TestTargetColumnRuleUnit:
    """Юнит-контракты модуля единой точки (target_column_rule)."""

    def _session_with_df(self, columns: dict, **session_fields) -> AnalysisSession:
        import pandas as pd

        session = AnalysisSession(session_id="unit-test")
        for key, value in session_fields.items():
            setattr(session, key, value)
        session.dataframe = pd.DataFrame(columns)
        return session

    def test_o6_source_defaults_to_none_legacy(self):
        """O6 (guard): target_column_source по умолчанию None --
        старый корпус (Redis-документы без поля) читается как user."""
        session = AnalysisSession(session_id="legacy")
        assert session.target_column_source is None

    def test_o7_derived_registry_excluded_original_derived_like_kept(self):
        """O7 (RED): колонка реестра исключается; производноподобная
        ИСХОДНАЯ (вне реестра) -- кандидат (канон PROGR-24)."""
        from apps.api.target_column_rule import auto_fix_and_seed

        session = self._session_with_df(
            {"spike_removed_value": [1, 2, 3], "value": [4.0, 5.0, 6.0]}
        )
        # без реестра: обе числовые -- неоднозначность (фиксации/события нет)
        assert auto_fix_and_seed(session) is None
        assert session.target_column is None
        assert session.pipeline_trace == []
        # колонка в реестре производных -- исключена: остаётся одна
        session.derived_columns = {"spike_removed_value": {"stage": "preprocessing"}}
        assert auto_fix_and_seed(session) == "value"
        assert session.target_column == "value"
        assert session.target_column_source == "auto"
        assert session.pipeline_trace[-1]["payload"] == {
            "target_column": "value",
            "source": "auto",
        }

    def test_o8_date_column_excluded_even_without_date_like_name(self):
        """O8 (RED): session.date_column исключается -- факт, не имя
        (колонка 'n' как дата-ось)."""
        from apps.api.target_column_rule import auto_fix_and_seed

        session = self._session_with_df({"n": [1, 2, 3], "value": [4.0, 5.0, 6.0]})
        session.date_column = "n"
        assert auto_fix_and_seed(session) == "value"
        assert session.target_column_source == "auto"

    def test_o9_direct_set_target_column_does_not_fixate(self):
        """O9 (guard): restore-контракт -- прямой set_target_column
        (путь restore) НЕ сеет событие и НЕ ставит source; source
        выставляет вызывающий (маршрут -- user, авто-фиксация -- auto)."""
        import pandas as pd

        session = AnalysisSession(session_id="restore-like")
        session.dataframe = pd.DataFrame({"value": [1.0, 2.0]})
        session.set_target_column("value")
        assert session.target_column == "value"
        assert session.target_column_source is None
        assert session.pipeline_trace == []


# ── O10: convert-types сброс цели → источник тоже сброшен ───────────


class TestConvertTypesResetsSource:
    def test_o10_type_conversion_reset_clears_source(self):
        """O10 (RED): конвертация типа делает цель нечисловой →
        target_column=None И target_column_source=None."""
        _upload_csv(CSV_ONE_NUMERIC)
        assert client.get("/v1/session/current").json()["target_column_source"] == "auto"
        resp = client.post(
            "/v1/session/dataset/convert-types",
            json={
                "conversions": [{"column": "value", "target_type": "string"}],
                "invalid_policy": "coerce",
                "apply": True,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["target_column_reset"] is True
        data = client.get("/v1/session/current").json()
        assert data["target_column"] is None
        assert data["target_column_source"] is None
