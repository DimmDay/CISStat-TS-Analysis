# tests/api/test_progress_progr25d.py
"""PROGR-25-D: repo-пины находок сертификаций + оракулы вычетов правила
на СВОИХ данных (spec_progress_target_column.md §4-D,
plan_progress_target_column.md §4 п.3).

Закрывают repo-гэпы, зафиксированные сертификациями:

  TM-11 (PROGR-25-A-CERT R4) -- demo-точка правила не была обозрима
     repo-тестами: встроенный sales_demo.csv ВСЕГДА неоднозначен (две
     числовые), поэтому фиксация на demo-пути проверялась только
     сертификационным оракулом (подмена demo-файла). Пин: подмена
     DEMO_DATASET_PATH своим одночисловым CSV → POST /v1/session/demo
     применяет правило (фиксация source="auto"); двухчисловой -- честная
     неоднозначность (guard R2/O4).
  TM-12 (PROGR-25-A-CERT R4) -- payload_keys маршрута
     POST /v1/session/target-column не пинился repo-тестами: снятие
     "source" из белого списка пережило бы repo-канал. Пин уровня
     таблицы TRACE_ROUTES.
  TM-15 (PROGR-25-A-CERT R4) -- носитель шапки задачи B: поля
     target_column/target_column_source в ответе /trace не были
     покрыты repo-тестами (гэп, критичный задаче B). Пин: схема
     (model_fields) + живое чтение /trace до и после загрузки.
  TB-8 (PROGR-25-B-CERT F1) -- закрыт фронтовым пином
     packages/ui/components/progr25d_toast_pin.test.tsx (вне этого
     файла).

Оракулы вычетов правила (М1/М2-убийцы мутационной матрицы D) -- на
СВОИХ данных (принцип «оракулы на своих данных»): ось t/load и
load/load_detrended, НЕ копируют данные O7/O8 test_progress_progr25a.
Вычеты -- по ФАКТУ (session.date_column и реестр
session.derived_columns), не по имени (канон PROGR-24/R4).
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.research_runs import reset_research_run_store_for_testing
from apps.api.routers.progress import ProgressTraceResponse
from apps.api.session_store import (
    AnalysisSession,
    reset_session_store_for_testing,
)
from apps.api.target_column_rule import (
    auto_fix_and_seed,
    target_column_candidates,
)
from apps.api.trace_hook import TRACE_ROUTES


@pytest.fixture(autouse=True)
def _reset_stores(monkeypatch):
    """Изоляция: Memory-бэкенды ОБОИХ хранилищ (паттерн
    test_progress_progr25c.py)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    yield
    reset_session_store_for_testing()
    reset_research_run_store_for_testing()


client = TestClient(app)


def _upload_csv(csv_content: str, filename: str = "test.csv") -> None:
    file = io.BytesIO(csv_content.encode("utf-8"))
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (filename, file, "text/csv")},
    )
    assert resp.status_code == 200, resp.text


def _trace() -> dict:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ══ TM-11: demo-точка правила (подмена demo-файла СВОИМИ данными) ════


DEMO_SINGLE_NUMERIC = (
    "date,load\n"
    "2024-01-01 00:00,42.5\n"
    "2024-01-01 01:00,43.1\n"
    "2024-01-01 02:00,41.9\n"
)
DEMO_TWO_NUMERIC = (
    "date,load,price\n"
    "2024-01-01 00:00,42.5,100\n"
    "2024-01-01 01:00,43.1,101\n"
    "2024-01-01 02:00,41.9,102\n"
)


class TestDemoPointPin:
    """TM-11: POST /v1/session/demo -- исполнитель правила (R2),
    проверенный подменой DEMO_DATASET_PATH на СВОИ файлы."""

    def test_demo_single_numeric_autofixes_source_auto(
        self, tmp_path, monkeypatch
    ):
        demo_file = tmp_path / "demo_single.csv"
        demo_file.write_text(DEMO_SINGLE_NUMERIC, encoding="utf-8")
        monkeypatch.setattr(
            "apps.api.routers.session.DEMO_DATASET_PATH", demo_file
        )
        resp = client.post("/v1/session/demo")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["has_active_dataset"] is True
        assert data["target_column"] == "load"
        assert data["target_column_source"] == "auto"
        # событие авто-фиксации в трассе demo-пути
        changed = [
            e for e in _trace()["events"]
            if e.get("event_type") == "target_column_changed"
        ]
        assert len(changed) == 1
        assert changed[0]["payload"] == {"target_column": "load", "source": "auto"}

    def test_demo_two_numeric_honest_ambiguity_guard(
        self, tmp_path, monkeypatch
    ):
        demo_file = tmp_path / "demo_two.csv"
        demo_file.write_text(DEMO_TWO_NUMERIC, encoding="utf-8")
        monkeypatch.setattr(
            "apps.api.routers.session.DEMO_DATASET_PATH", demo_file
        )
        resp = client.post("/v1/session/demo")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["target_column"] is None
        assert data["target_column_source"] is None
        assert [
            e for e in _trace()["events"]
            if e.get("event_type") == "target_column_changed"
        ] == []


# ══ TM-12: пин белого списка payload_keys ручного маршрута ═══════════


class TestTraceRoutePayloadKeysPin:
    """TM-12: канал source ручного маршрута должен оставаться
    подготовленным (payload_keys += "source" -- контракт A); снятие
    ключа пережило бы repo-канал (находка сертификации A)."""

    def test_manual_route_spec_carries_source_in_payload_keys(self):
        specs = [
            s
            for s in TRACE_ROUTES
            if s.method == "POST"
            and s.path_template == "/v1/session/target-column"
        ]
        assert len(specs) == 1, "маршрут зафиксирован в таблице однократно"
        spec = specs[0]
        assert spec.event_type == "target_column_changed"
        assert "target_column" in spec.payload_keys
        assert "source" in spec.payload_keys


# ══ TM-15: пин носителя шапки задачи B (схема + живое чтение) ════════


class TestTraceCarrierPin:
    """TM-15: /trace несёт актуальный признак и происхождение --
    единственный источник шапки панели (задача B читает отсюда)."""

    def test_progress_trace_response_schema_carries_fields(self):
        fields = ProgressTraceResponse.model_fields
        assert "target_column" in fields
        assert "target_column_source" in fields

    def test_trace_carries_session_facts_before_and_after_upload(self):
        # до загрузки: честная пустота (шапка «—»)
        fresh = _trace()
        assert fresh["target_column"] is None
        assert fresh["target_column_source"] is None
        # после загрузки одночислового: value/auto наверху ответа
        _upload_csv("date,value\n2023-01-01,10.5\n2023-01-02,20.1\n")
        trace = _trace()
        assert trace["target_column"] == "value"
        assert trace["target_column_source"] == "auto"


# ══ Оракулы вычетов на СВОИХ данных (убийцы М1/М2) ═══════════════════


def _session_with_df(columns: dict, **session_fields) -> AnalysisSession:
    session = AnalysisSession(session_id="progr25d-pin")
    for key, value in session_fields.items():
        setattr(session, key, value)
    session.dataframe = pd.DataFrame(columns)
    return session


class TestFactDeductionsOwnData:
    """Вычеты правила -- по факту (date_column / реестр производных),
    не по имени; данные СВОИ (t/load, load/load_detrended)."""

    def test_m1_date_column_fact_deduction(self):
        """М1-оракул: числовая ось t, ЗАРЕГИСТРИРОВАННАЯ как
        date_column, исключается из кандидатов даже без date-подобного
        имени -- фиксация load."""
        session = _session_with_df(
            {"t": [1, 2, 3], "load": [4.0, 5.0, 6.0]},
            date_column="t",
        )
        assert target_column_candidates(session) == ["load"]
        assert auto_fix_and_seed(session) == "load"
        assert session.target_column == "load"
        assert session.target_column_source == "auto"

    def test_m1_without_deduction_would_be_ambiguous(self):
        """М1-guard: та же пара колонок БЕЗ зарегистрированной даты --
        два кандидата, фиксации нет (дедукция решает поведение)."""
        session = _session_with_df({"t": [1, 2, 3], "load": [4.0, 5.0, 6.0]})
        assert target_column_candidates(session) == ["t", "load"]
        assert auto_fix_and_seed(session) is None
        assert session.target_column is None
        assert session.target_column_source is None

    def test_m2_registry_deduction_decides_not_name(self):
        """М2-оракул: колонка реестра исключается (решает РЕЕСТР,
        канон PROGR-24): без реестра load/load_detrended --
        неоднозначность, с реестром -- фиксация load."""
        session = _session_with_df(
            {"load": [4.0, 5.0, 6.0], "load_detrended": [0.1, 0.2, 0.3]}
        )
        assert auto_fix_and_seed(session) is None  # 2 кандидата
        session.derived_columns = {"load_detrended": {"stage": "preprocessing"}}
        assert auto_fix_and_seed(session) == "load"
        assert session.target_column_source == "auto"
        assert session.pipeline_trace[-1]["payload"] == {
            "target_column": "load",
            "source": "auto",
        }

    def test_m2_derived_like_name_outside_registry_stays_candidate(self):
        """М2-guard: производноподобное ИМЯ вне реестра -- полноценный
        кандидат (канон «не угадываем по суффиксу»)."""
        session = _session_with_df(
            {"load": [4.0, 5.0, 6.0], "value_detrended": [0.1, 0.2, 0.3]}
        )
        assert target_column_candidates(session) == ["load", "value_detrended"]
        assert auto_fix_and_seed(session) is None
