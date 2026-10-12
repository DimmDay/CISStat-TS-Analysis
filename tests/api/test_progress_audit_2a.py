# tests/api/test_progress_audit_2a.py
"""Task PROGR-AUDIT-2A (plan_progress_audit.md §11, контракт
docs/progress_audit_contract.md аддендум v0.9-2A §19) -- API-карты:
контекст и идемпотентность.

Проблема (F04/F07; P06/P07/P24):

  * карты статусов не привязаны к контексту расчёта -- старое тело
    отчёта принимается новым запуском (P24), отчёт прошлого контекста
    принимается после смены цели/ревизии того же запуска;
  * повтор отчёта не идемпотентен (P07) -- каждый POST рождает новые
    event_id, дедуп store'а не активируется, Memory и Postgres ведут
    себя по-разному;
  * карты пишутся v1-событиями -- «клиентское наблюдение» не
    маркировано envelope'ом (доказательность I10 не выражена);
  * у доставки нет receipt -- клиент не различает «принято»/«записано».

Решение -- ЕДИНЫЙ механизм v2-конверта для ЧЕТЫРЁХ эндпоинтов
(upload-stops/validation-checks/preprocessing-checks/eda-checks):

  V-1. Обязательный v2-конверт: schema_version=2, run_id, context_id,
       report_id (+ result_refs там, где они имеются). Форма -- 422 до
       первой записи.
  V-2. Контекстные гейты ДО записи: совпадение run (409 stale_run) и
       контекста (409 stale_context -- против durable run.context_id,
       того же, что клиент видит в GET /trace). 409/422 -- НОЛЬ
       изменений в слоях 1 и 2.
  V-3. Идемпотентность по report_id: ключ report:{run_id}:{report_id},
       отпечаток ТЕЛА (без event_id/ts). Повтор того же тела -- прежний
       receipt, ноль новых событий (включая слой 1). Тот же ключ с
       другим телом -- 409. НОВЫЙ ключ с тем же телом -- новое
       клиентское наблюдение (явное основание -- новый отчёт).
  V-4. События v2 штампуются envelope'ом: schema_version=2,
       evidence_level=client_observation, operation_id=report_id,
       context_id; result_ref -- для узлов со ссылками.
  V-5. Легаси-режим (тело без schema_version) -- прежнее поведение
       байт-в-байт, ответ помечен mode="legacy"; P24 для old-write пути
       НЕ закрыт (compatibility mode, план §20.2 п.4).
  V-6. Транзакционность v2: строгий commit слоя 2 (CAS контекста)
       ПЕРЕД слоем 1 -- все отказы до/на commit оставляют ноль
       частичных узлов.

Ссылки: spec_progress_audit.md §5 (F04/F07), §6.1 (H06/H07/H24), §8.3
(идемпотентность), §9 (AUDIT-2 строка), план §11, §20.2 п.4.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.pipeline_graph import CHECK_STATUS_VALUES, STAGE_NODES
from apps.api.main import app
from apps.api.routers.progress import EDA_CHECK_STATUS_VALUES
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_stores(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    from apps.api import research_runs

    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()


# ── карты и хелперы ──────────────────────────────────────────────────

ENDPOINT_MAPS: dict[str, dict[str, Any]] = {
    # endpoint -> {key, registry, statuses}
    "/upload-stops": {
        "key": "stops",
        "registry": STAGE_NODES["upload"],
        "statuses": CHECK_STATUS_VALUES,
    },
    "/validation-checks": {
        "key": "checks",
        "registry": STAGE_NODES["validation"],
        "statuses": CHECK_STATUS_VALUES,
    },
    "/preprocessing-checks": {
        "key": "checks",
        "registry": STAGE_NODES["preprocessing"],
        "statuses": CHECK_STATUS_VALUES,
    },
    "/eda-checks": {
        "key": "checks",
        "registry": STAGE_NODES["eda"],
        "statuses": EDA_CHECK_STATUS_VALUES,
    },
}

MAP_EVENT_TYPE = {
    "/upload-stops": "upload_stop_status",
    "/validation-checks": "validation_check_status",
    "/preprocessing-checks": "preprocessing_check_status",
    "/eda-checks": "eda_check_status",
}


def _full_map(endpoint: str, fill: str = "done") -> dict[str, str]:
    spec = ENDPOINT_MAPS[endpoint]
    values = list(spec["statuses"])
    return {
        node_id: (
            fill if fill in spec["statuses"] else values[i % len(values)]
        )
        for i, node_id in enumerate(spec["registry"])
    }


def _monitor_csv() -> str:
    idx = [datetime(2026, 2, 1) + timedelta(days=i) for i in range(150)]
    frame_rows = {"date": [d.strftime("%Y-%m-%d") for d in idx]}
    frame_rows["value"] = [120.0 + i for i in range(150)]
    frame_rows["humidity"] = [40.0 + (i % 7) * 0.5 for i in range(150)]
    import pandas as pd

    frame = pd.DataFrame(frame_rows)
    return frame.to_csv(index=False)


def _upload() -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": (
            "forecast_monitor_synthetic_n150.csv",
            io.BytesIO(_monitor_csv().encode()),
            "text/csv",
        )},
    )
    assert response.status_code == 200, response.text


def _trace() -> dict:
    response = client.get("/v1/progress/trace")
    assert response.status_code == 200, response.text
    return response.json()


def _seed() -> tuple[str, str]:
    """Загрузка + seed контекста: (run_id, context_id) из GET /trace --
    тот же источник, что у UI-продюсера (AUDIT-2B)."""
    _upload()
    trace = _trace()
    run_id = trace.get("run_id") or ""
    context_id = trace.get("context_id") or ""
    assert run_id, "seed: run_id должен быть зафиксирован загрузкой"
    assert context_id, "seed: контекст расчёта должен быть вычислен (AUDIT-C)"
    return run_id, context_id


def _v2_body(
    endpoint: str,
    *,
    run_id: str,
    context_id: str,
    report_id: str,
    checks: dict[str, str] | None = None,
    result_refs: dict[str, str] | None = None,
    schema_version: int | None = 2,
) -> dict[str, Any]:
    spec = ENDPOINT_MAPS[endpoint]
    body: dict[str, Any] = {
        spec["key"]: checks if checks is not None else _full_map(endpoint),
        "schema_version": schema_version,
        "run_id": run_id,
        "context_id": context_id,
        "report_id": report_id,
    }
    if result_refs is not None:
        body["result_refs"] = result_refs
    return body


def _post(endpoint: str, body: dict[str, Any]):
    return client.post(f"/v1/progress{endpoint}", json=body)


def _layer1_events(run_id: str, event_type: str) -> list[dict]:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    return [
        event for event in session.pipeline_trace
        if event.get("event_type") == event_type
    ]


def _layer2_events(run_id: str, event_type: str) -> list:
    from apps.api.research_runs import get_research_run_store

    stored = get_research_run_store().list_events(run_id)
    return [event for event in stored if event.event_type == event_type]


def _map_counts(run_id: str, event_type: str) -> tuple[int, int]:
    return (
        len(_layer1_events(run_id, event_type)),
        len(_layer2_events(run_id, event_type)),
    )


def _assert_zero_changes(run_id: str, event_type: str, before: tuple[int, int], panel_before: dict | None = None):
    assert _map_counts(run_id, event_type) == before, (
        "409/422/отказ обязаны давать НОЛЬ изменений (план §11 GREEN)"
    )
    if panel_before is not None:
        assert _trace()["node_statuses"] == panel_before


# ── V-1/V-4: приёмка v2-отчёта, receipt, envelope-штамп ─────────────


class TestV2Acceptance:
    def test_v2_report_accepted_with_receipt_and_envelope(self):
        """V-1/V-4 (RED): v2-отчёт принимается, ответ несёт receipt
        (idempotency_key/accepted_event_ids/committed_watermark), события
        в слоях 1 и 2 штампованы envelope'ом client_observation
        (schema_version=2, operation_id=report_id, context_id)."""
        run_id, context_id = _seed()
        report_id = "rep-val-001"
        body = _v2_body(
            "/validation-checks", run_id=run_id, context_id=context_id,
            report_id=report_id,
        )
        response = _post("/validation-checks", body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["mode"] == "v2"
        assert result["reported"] == len(STAGE_NODES["validation"])
        assert result["run_id"] == run_id
        assert result["report_id"] == report_id
        assert result["context_id"] == context_id
        assert result["deduplicated"] is False
        receipt = result["receipt"]
        assert receipt["idempotency_key"] == f"report:{run_id}:{report_id}"
        assert len(receipt["accepted_event_ids"]) == len(
            STAGE_NODES["validation"]
        )
        assert receipt["committed_watermark"] > 0
        assert receipt["run_id"] == run_id

        event_type = MAP_EVENT_TYPE["/validation-checks"]
        layer1 = _layer1_events(run_id, event_type)
        assert len(layer1) == len(STAGE_NODES["validation"])
        for event in layer1:
            assert event["schema_version"] == 2
            assert event["evidence_level"] == "client_observation"
            assert event["operation_id"] == report_id
            assert event["context_id"] == context_id
        layer2 = _layer2_events(run_id, event_type)
        assert len(layer2) == len(STAGE_NODES["validation"])
        for event in layer2:
            data = event.to_dict()
            assert data["schema_version"] == 2
            assert data["evidence_level"] == "client_observation"
            assert data["operation_id"] == report_id
            assert data["context_id"] == context_id

    def test_v2_retry_same_report_id_returns_receipt_without_writes(self):
        """V-3/P07 (RED): повтор ТОГО ЖЕ v2-тела (потерянный ответ) --
        прежний receipt, deduplicated=true, НОЛЬ новых событий в слоях
        1 и 2."""
        run_id, context_id = _seed()
        report_id = "rep-val-retry"
        body = _v2_body(
            "/validation-checks", run_id=run_id, context_id=context_id,
            report_id=report_id,
        )
        first = _post("/validation-checks", body)
        assert first.status_code == 200, first.text
        first_result = first.json()
        event_type = MAP_EVENT_TYPE["/validation-checks"]
        before = _map_counts(run_id, event_type)
        assert before[0] == len(STAGE_NODES["validation"])

        second = _post("/validation-checks", body)
        assert second.status_code == 200, second.text
        second_result = second.json()
        assert second_result["mode"] == "v2"
        assert second_result["deduplicated"] is True
        assert second_result["receipt"] == first_result["receipt"]
        assert _map_counts(run_id, event_type) == before, (
            "повтор доставки не добавляет факты (P07/F07)"
        )

    def test_v2_same_key_different_body_conflict_409(self):
        """V-3 (RED): тот же report_id с ДРУГИМ телом -- 409 без записи
        (план §11 RED: «прежний ключ с другим телом»)."""
        run_id, context_id = _seed()
        report_id = "rep-val-conflict"
        first = _post("/validation-checks", _v2_body(
            "/validation-checks", run_id=run_id, context_id=context_id,
            report_id=report_id,
        ))
        assert first.status_code == 200, first.text
        event_type = MAP_EVENT_TYPE["/validation-checks"]
        before = _map_counts(run_id, event_type)
        panel_before = _trace()["node_statuses"]

        changed = _full_map("/validation-checks")
        changed["data_types"] = "warning"
        second = _post("/validation-checks", _v2_body(
            "/validation-checks", run_id=run_id, context_id=context_id,
            report_id=report_id, checks=changed,
        ))
        assert second.status_code == 409, second.text
        _assert_zero_changes(run_id, event_type, before, panel_before)

    def test_v2_new_key_same_body_is_new_observation(self):
        """V-3 (RED): НОВЫЙ report_id с тем же телом -- новое клиентское
        наблюдение (явное основание -- новый отчёт): события
        записываются, deduplicated=false."""
        run_id, context_id = _seed()
        event_type = MAP_EVENT_TYPE["/validation-checks"]
        first = _post("/validation-checks", _v2_body(
            "/validation-checks", run_id=run_id, context_id=context_id,
            report_id="rep-obs-1",
        ))
        assert first.status_code == 200
        before = _map_counts(run_id, event_type)
        second = _post("/validation-checks", _v2_body(
            "/validation-checks", run_id=run_id, context_id=context_id,
            report_id="rep-obs-2",
        ))
        assert second.status_code == 200, second.text
        assert second.json()["deduplicated"] is False
        after = _map_counts(run_id, event_type)
        assert after[0] == before[0] * 2
        assert after[1] == before[1] * 2


# ── V-2: контекстные гейты (P24/F04) ─────────────────────────────────


class TestContextGates:
    def test_v2_report_a_rejected_after_upload_b(self):
        """P24/F04 (RED): отчёт запуска A повторно доставляется после
        загрузки B -- 409 stale_run, НОЛЬ изменений в запуске B, старый
        снапшот не повышает текущий прогресс."""
        run_id_a, context_id_a = _seed()
        stale_body = _v2_body(
            "/upload-stops", run_id=run_id_a, context_id=context_id_a,
            report_id="rep-upload-a",
        )
        first = _post("/upload-stops", stale_body)
        assert first.status_code == 200, first.text

        # Загрузка B: новый датасет = новое исследование (новый run).
        _upload()
        trace_b = _trace()
        run_id_b = trace_b["run_id"]
        assert run_id_b and run_id_b != run_id_a, (
            "новая загрузка -- новый запуск (§3.1)"
        )
        event_type = MAP_EVENT_TYPE["/upload-stops"]
        before = _map_counts(run_id_b, event_type)
        panel_before = trace_b["node_statuses"]

        replay = _post("/upload-stops", stale_body)
        assert replay.status_code == 409, replay.text
        assert "stale_run" in replay.text
        _assert_zero_changes(run_id_b, event_type, before, panel_before)

    def test_v2_same_run_changed_target_rejected(self):
        """P24/F04 (RED): тот же запуск, сменилась цель -- старый контекст
        отклоняется ДО записи (409 stale_context); повторное доставление
        старого снапшота не поднимает прогресс нового контекста.

        Цель меняется на ДРУГУЮ колонку (value -> humidity): компоненты
        контекста (data/target/temporal) сдвигаются; ручной выбор ТОЙ ЖЕ
        колонки контекст не сдвигает (origin в контекст не входит --
        контракт AUDIT-C §3.4)."""
        run_id, context_id = _seed()
        stale_body = _v2_body(
            "/validation-checks", run_id=run_id, context_id=context_id,
            report_id="rep-ctx-1",
        )
        first = _post("/validation-checks", stale_body)
        assert first.status_code == 200, first.text

        shifted = client.post(
            "/v1/session/target-column", json={"column": "humidity"}
        )
        assert shifted.status_code == 200, shifted.text
        trace_after = _trace()
        assert trace_after["context_id"] != context_id, (
            "смена цели -- другой контекст расчёта (AUDIT-C)"
        )
        event_type = MAP_EVENT_TYPE["/validation-checks"]
        before = _map_counts(run_id, event_type)
        panel_before = trace_after["node_statuses"]

        replay = _post("/validation-checks", stale_body)
        assert replay.status_code == 409, replay.text
        assert "stale_context" in replay.text
        _assert_zero_changes(run_id, event_type, before, panel_before)

    def test_v2_requires_known_run_409(self):
        """V-2 (RED): v2-отчёт с неизвестным серверу запуском -- 409;
        run_id клиента НЕ сеется из тела (привязка не фабрикуется)."""
        _upload()
        _, context_id = run_ctx = _seed()  # noqa: F841 -- контекст реальный
        body = _v2_body(
            "/validation-checks",
            run_id="RUN-FABRICATED",
            context_id=context_id,
            report_id="rep-fabricated",
        )
        response = _post("/validation-checks", body)
        assert response.status_code == 409, response.text
        assert "stale_run" in response.text

    def test_v2_rejections_leave_no_layer1_facts(self):
        """Общий инвариант (RED): любой отказ v2 (422 формы / 409
        контекста) -- в слое 1 НОЛЬ событий отчёта (all-or-nothing)."""
        run_id, context_id = _seed()
        event_type = MAP_EVENT_TYPE["/validation-checks"]
        before = _map_counts(run_id, event_type)

        bad_bodies = [
            # отсутствие run_id
            {"checks": _full_map("/validation-checks"),
             "schema_version": 2, "context_id": context_id,
             "report_id": "rep-x1"},
            # отсутствие context_id
            {"checks": _full_map("/validation-checks"),
             "schema_version": 2, "run_id": run_id,
             "report_id": "rep-x2"},
            # отсутствие report_id
            {"checks": _full_map("/validation-checks"),
             "schema_version": 2, "run_id": run_id,
             "context_id": context_id},
            # пустой report_id
            _v2_body("/validation-checks", run_id=run_id,
                     context_id=context_id, report_id=""),
            # schema_version=3 -- поддерживается только 2
            _v2_body("/validation-checks", run_id=run_id,
                     context_id=context_id, report_id="rep-x4",
                     schema_version=3),
            # schema_version=1 -- legacy-писатели шлют тело БЕЗ поля
            _v2_body("/validation-checks", run_id=run_id,
                     context_id=context_id, report_id="rep-x5",
                     schema_version=1),
        ]
        for bad in bad_bodies:
            response = _post("/validation-checks", bad)
            assert response.status_code == 422, (bad, response.text)
            _assert_zero_changes(run_id, event_type, before)


# ── result_refs: ссылки на результаты там, где они имеются ───────────


class TestResultRefs:
    def test_v2_result_refs_recorded_in_envelope(self):
        """V-4 (RED): валидные result_refs записываются в envelope
        события соответствующего узла (result_ref.report_ref); узлы без
        ссылки поле не получают."""
        run_id, context_id = _seed()
        refs = {"data_types": f"{context_id}@validate-result-1"}
        body = _v2_body(
            "/validation-checks", run_id=run_id, context_id=context_id,
            report_id="rep-refs-1", result_refs=refs,
        )
        response = _post("/validation-checks", body)
        assert response.status_code == 200, response.text
        event_type = MAP_EVENT_TYPE["/validation-checks"]
        by_node = {
            event["node_id"]: event
            for event in _layer1_events(run_id, event_type)
        }
        assert by_node["data_types"]["result_ref"] == {
            "report_ref": refs["data_types"],
        }
        assert "result_ref" not in by_node["formats"]

    def test_v2_result_ref_foreign_context_409(self):
        """RED (план §11: «result принадлежит чужому контексту»): ссылка
        с встроенным контекстом другого расчёта -- 409, ноль изменений."""
        run_id, context_id = _seed()
        before = _map_counts(
            run_id, MAP_EVENT_TYPE["/validation-checks"]
        )
        foreign = "ctx-0123456789abcdef@validate-result-9"
        body = _v2_body(
            "/validation-checks", run_id=run_id, context_id=context_id,
            report_id="rep-refs-foreign",
            result_refs={"data_types": foreign},
        )
        response = _post("/validation-checks", body)
        assert response.status_code == 409, response.text
        _assert_zero_changes(
            run_id, MAP_EVENT_TYPE["/validation-checks"], before
        )

    def test_v2_result_refs_form_gates_422(self):
        """Форма ссылок: фантомный узел / пустое значение -- 422 до
        записи."""
        run_id, context_id = _seed()
        before = _map_counts(
            run_id, MAP_EVENT_TYPE["/validation-checks"]
        )
        bad_refs = [
            {"phantom_node": f"{context_id}@r"},      # фантомный узел
            {"data_types": ""},                        # пустая ссылка
        ]
        for refs in bad_refs:
            body = _v2_body(
                "/validation-checks", run_id=run_id, context_id=context_id,
                report_id="rep-refs-bad", result_refs=refs,
            )
            response = _post("/validation-checks", body)
            assert response.status_code == 422, (refs, response.text)
            _assert_zero_changes(
                run_id, MAP_EVENT_TYPE["/validation-checks"], before
            )


# ── ЕДИНЫЙ механизм на четырёх эндпоинтах (план §11 GREEN) ───────────


class TestFourEndpointsSharedMechanism:
    @pytest.mark.parametrize("endpoint", list(ENDPOINT_MAPS))
    def test_v2_contract_per_endpoint(self, endpoint):
        """Контракт v2 на каждом из четырёх эндпоинтов: приёмка+receipt,
        дедуп повтора, форма-гейты 422 -- ОДИН механизм."""
        run_id, context_id = _seed()
        report_id = f"rep{endpoint.replace('-', '')}"
        body = _v2_body(endpoint, run_id=run_id, context_id=context_id,
                        report_id=report_id)
        first = _post(endpoint, body)
        assert first.status_code == 200, first.text
        result = first.json()
        assert result["mode"] == "v2"
        assert result["deduplicated"] is False
        assert result["receipt"]["idempotency_key"] == (
            f"report:{run_id}:{report_id}"
        )
        registry = ENDPOINT_MAPS[endpoint]["registry"]
        assert result["reported"] == len(registry)

        event_type = MAP_EVENT_TYPE[endpoint]
        layer1 = _layer1_events(run_id, event_type)
        assert len(layer1) == len(registry)
        assert all(
            event["schema_version"] == 2
            and event["evidence_level"] == "client_observation"
            and event["operation_id"] == report_id
            for event in layer1
        )

        before = _map_counts(run_id, event_type)
        second = _post(endpoint, body)
        assert second.status_code == 200, second.text
        assert second.json()["deduplicated"] is True
        assert _map_counts(run_id, event_type) == before

    def test_eda_vocabulary_enforced_in_v2(self):
        """Словарь EDA (done/pending) действует и в v2: warning -- 422
        (решение тимлида v1.1 §2 не обходится конвертом)."""
        run_id, context_id = _seed()
        checks = _full_map("/eda-checks", fill="done")
        checks[list(STAGE_NODES["eda"])[0]] = "warning"
        body = _v2_body(
            "/eda-checks", run_id=run_id, context_id=context_id,
            report_id="rep-eda-warning", checks=checks,
        )
        response = _post("/eda-checks", body)
        assert response.status_code == 422, response.text

    def test_v2_requires_dataset_400(self):
        """v2-отчёт без датасета -- честный 400 (факты без исследования
        не существуют; конверт не отменяет гейт)."""
        body = _v2_body(
            "/validation-checks", run_id="RUN-NONE",
            context_id="ctx-none", report_id="rep-nods",
        )
        response = _post("/validation-checks", body)
        assert response.status_code == 400, response.text


# ── V-5: легаси-режим (ограниченный режим старых писателей) ─────────


class TestLegacyMode:
    def test_legacy_body_marked_and_unchanged(self):
        """V-5 (RED-пин): тело без schema_version -- прежний контракт
        (200, run_id, reported); ответ честно помечен mode="legacy",
        receipt/report_id не выдаются."""
        run_id, context_id = _seed()
        body = {ENDPOINT_MAPS["/validation-checks"]["key"]:
                _full_map("/validation-checks")}
        response = _post("/validation-checks", body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["mode"] == "legacy"
        assert result["reported"] == len(STAGE_NODES["validation"])
        assert result["receipt"] is None
        assert result["deduplicated"] is False

    def test_legacy_repeat_still_appends_events_p07_open(self):
        """V-5 (пин честности): в легаси-режиме повтор отчёта по-прежнему
        даёт новые события (P07 НЕ закрыт для old-write пути) -- это
        ОСОЗНАННОЕ ограничение rollout (план §20.2 п.4), пин фиксирует
        границу, а не одобряет дефект."""
        run_id, context_id = _seed()
        event_type = MAP_EVENT_TYPE["/validation-checks"]
        body = {ENDPOINT_MAPS["/validation-checks"]["key"]:
                _full_map("/validation-checks")}
        first = _post("/validation-checks", body)
        assert first.status_code == 200
        assert first.json()["mode"] == "legacy"
        first_counts = _map_counts(run_id, event_type)
        second = _post("/validation-checks", body)
        assert second.status_code == 200
        assert second.json()["mode"] == "legacy"
        second_counts = _map_counts(run_id, event_type)
        assert second_counts[0] == first_counts[0] * 2
        assert second_counts[1] == first_counts[1] * 2

    def test_legacy_stale_body_still_accepted_p24_open(self):
        """V-5 (пин честности P24): старое тело легаси-писателя после
        новой загрузки по-прежнему принимается в новый запуск (200) --
        P24 для old-write пути НЕ закрыт; закрытие -- отключение легаси-
        режима (решение тимлида после AUDIT-2B, контракт §19.5)."""
        run_id_a, _ = _seed()
        body = {ENDPOINT_MAPS["/upload-stops"]["key"]:
                _full_map("/upload-stops")}
        first = _post("/upload-stops", body)
        assert first.status_code == 200
        _upload()
        run_id_b = _trace()["run_id"]
        assert run_id_b != run_id_a
        replay = _post("/upload-stops", body)
        assert replay.status_code == 200, replay.text
        assert replay.json()["mode"] == "legacy"
        assert replay.json()["run_id"] == run_id_b


# ── ЕДИНЫЙ модуль механизма (импорт-контракт) ────────────────────────


class TestSharedModule:
    def test_progress_maps_module_contract(self):
        """Единый механизм -- отдельный модуль apps/api/progress_maps.py:
        accept_map_report/MapSpec/report_body_fingerprint/MapReportV2.
        Четыре эндпоинта -- потребители ОДНОЙ реализации (план §11:
        «четыре endpoint contract tests на общем механизме»)."""
        from apps.api import progress_maps

        assert hasattr(progress_maps, "accept_map_report")
        assert hasattr(progress_maps, "MapSpec")
        assert hasattr(progress_maps, "MapReportV2")
        assert hasattr(progress_maps, "report_body_fingerprint")

    def test_report_body_fingerprint_stable_and_body_sensitive(self):
        """Отпечаток тела v2-отчёта: детерминирован (повтор -- тот же
        fp), чувствителен к карте/report_id/контексту и НЕ зависит от
        сгенерированных event_id/ts (база дедупа «тот же ключ + другое
        тело»)."""
        from apps.api.progress_maps import report_body_fingerprint

        fp1 = report_body_fingerprint(
            run_id="RUN-1", context_id="ctx-a", report_id="rep-1",
            payload_map={"n1": "done", "n2": "pending"},
            result_refs=None,
        )
        fp2 = report_body_fingerprint(
            run_id="RUN-1", context_id="ctx-a", report_id="rep-1",
            payload_map={"n2": "pending", "n1": "done"},
            result_refs=None,
        )
        assert fp1 == fp2, "порядок ключей карты не меняет отпечаток"
        assert report_body_fingerprint(
            run_id="RUN-1", context_id="ctx-a", report_id="rep-2",
            payload_map={"n1": "done", "n2": "pending"},
            result_refs=None,
        ) != fp1, "другой report_id -- другой отпечаток"
        assert report_body_fingerprint(
            run_id="RUN-1", context_id="ctx-a", report_id="rep-1",
            payload_map={"n1": "warning", "n2": "pending"},
            result_refs=None,
        ) != fp1, "другое тело карты -- другой отпечаток"
        assert report_body_fingerprint(
            run_id="RUN-1", context_id="ctx-b", report_id="rep-1",
            payload_map={"n1": "done", "n2": "pending"},
            result_refs=None,
        ) != fp1, "другой контекст -- другой отпечаток"
        assert report_body_fingerprint(
            run_id="RUN-1", context_id="ctx-a", report_id="rep-1",
            payload_map={"n1": "done", "n2": "pending"},
            result_refs={"n1": "ctx-a@r1"},
        ) != fp1, "ссылки на результаты -- часть тела"
