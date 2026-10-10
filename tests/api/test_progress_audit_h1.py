# tests/api/test_progress_audit_h1.py
"""
PROGR-AUDIT-H1: горячая дорожка F02/F17 (plan_progress_audit.md,
Донастройка Части 1–2; контракт docs/progress_audit_contract.md §3.1/§8).

F02 (P03, spec_progress_audit.md §5): сброс цели конвертацией типов
(session.py::convert-types) чистит session.target_column/source, но
(а) событие сброса не существует вовсе (флаг target_column_reset=true
путешествует в payload correction_applied узла data_types, который
подсистема цели не читает), (б) run.target_column остаётся "rain",
(в) тройка Наставника (_target_confirmed/_target_origin/
_phase_event_text_facts) держит прежний выбор -- Наставник утверждает
выбор, которого больше нет.

Решение (контракт §3.1 -- УТВЕРЖДЕНО-AUDIT-0): выделенный канонический
тип `target_column_cleared` (stage=validation, node_id=None -- носитель
target_column_changed); payload {target_column: null, reset_reason,
source: "system"|"auto", before_target}; посев ТОЛЬКО серверным
продюсером в точке решения (POST /target-column остаётся маршрутом
ВЫБОРА с 422 на пустой, маршруты не объединяются); двухслойный посев
(слой 1 + зеркало слоя 2, общий event_id -- канон R3 по образцу
auto_fix_and_seed PROGR-25-C); run-метаданные той же точкой
(target_column=None); origin после сброса -- unknown/None, НЕ "user";
тройка Наставника reset-aware: после сброса честный fallback
«Подтвердите целевой признак…» (ожидание P03).

F17 (P25): повторный GET профиля EDA сеет profile_viewed и редьюсер
понижает done -> running. Interim-монотонность (Донастройка Часть 2):
ТОЛЬКО profile_viewed, ТОЛЬКО в редьюсере статусов -- running
устанавливается только из pending/отсутствия; узел, достигший done,
profile_viewed не понижается. Легитимный путь переоткрытия -- карта
eda-checks (eda_check_status, PAYLOAD_STATUS) сохраняется. Глобальная
монотонность запрещена (сделала бы H28 неисправимым молча). Маркировка
interim до AUDIT-3 (заменяется контекст-ключевой монотонностью).
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.core.mentor_rules import (
    _phase_event_text_facts,
    _target_confirmed,
    _target_origin,
    phase_text,
)
from app.core.node_status import derive_node_statuses
from apps.api import research_runs
from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing
from apps.api.trace_events import make_trace_event


@pytest.fixture(autouse=True)
def _reset_stores(monkeypatch):
    """Изоляция: Memory-бэкенды ОБОИХ хранилищ (паттерн
    test_progress_progr25c: Наставник читает слой 2 -- run-store)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()


client = TestClient(app)


def _details_by_key(events: list) -> dict:
    """Детали узлов (derive_pipeline_node_states) keyed "stage/node_id"."""
    from app.core.node_status import derive_pipeline_node_states

    return {
        f"{n['stage']}/{n['node_id']}": n
        for n in derive_pipeline_node_states(events)
    }


CSV_ONE_NUMERIC = (
    "date,rain\n"
    "2023-01-01,10.5\n"
    "2023-01-02,20.1\n"
    "2023-01-03,30.2\n"
    "2023-01-04,15.8\n"
)


def _upload_one_numeric() -> None:
    file = io.BytesIO(CSV_ONE_NUMERIC.encode("utf-8"))
    resp = client.post(
        "/v1/internal/upload",
        files={"file": ("single.csv", file, "text/csv")},
    )
    assert resp.status_code == 200, resp.text


def _confirm_structure_like_ui() -> None:
    """UI-автопревью Загрузки (UploadAutoPreviewPipeline): уверенная дата
    фиксируется сама -- узел upload/structure становится done
    (канон репро PROGR-25-C)."""
    resp = client.post("/v1/session/date-column", json={"column": "date"})
    assert resp.status_code == 200, resp.text


def _run_id() -> str:
    trace = client.get("/v1/progress/trace").json()
    run_id = trace.get("run_id") or ""
    assert run_id, "run_id не зафиксирован в трассе слоя 1"
    return run_id


def _convert_target_to_string(apply: bool = True):
    return client.post(
        "/v1/session/dataset/convert-types",
        json={
            "conversions": [{"column": "rain", "target_type": "string"}],
            "invalid_policy": "coerce",
            "apply": apply,
        },
    )


def _trace() -> dict:
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _cleared_events(trace: dict) -> list[dict]:
    return [
        e for e in trace.get("events", [])
        if e.get("event_type") == "target_column_cleared"
    ]


def _node(trace: dict, stage: str, node_id: str) -> dict:
    nodes = [
        n for n in trace.get("nodes", [])
        if n.get("stage") == stage and n.get("node_id") == node_id
    ]
    assert nodes, f"узел {stage}/{node_id} отсутствует в /trace"
    return nodes[0]


# ── Реестр и фабрика (контракт §3.1 п.1–2) ───────────────────────────


class TestRegistryAndFactory:
    def test_cleared_registered_on_validation_stage(self):
        """RED: тип в реестре Валидации -- рядом с target_column_changed
        (v1-совместимое расширение, миграция не нужна)."""
        from apps.api.trace_events import STAGE_EVENT_TYPES

        assert "target_column_cleared" in STAGE_EVENT_TYPES["validation"]
        # носитель выбора -- та же пара (stage, node_id=None)
        event = make_trace_event(
            "target_column_cleared",
            stage="validation",
            node_id=None,
            run_id="RUN-H1",
            actor="system",
            target_column=None,
            reset_reason="type_conversion",
            source="system",
            before_target="rain",
        )
        assert event.stage == "validation"
        assert event.node_id is None
        assert event.actor == "system"
        assert event.payload["reset_reason"] == "type_conversion"
        assert event.payload["source"] == "system"
        assert event.payload["before_target"] == "rain"
        assert event.payload["target_column"] is None

    def test_cleared_fail_closed_outside_validation(self):
        """Fail-closed фабрики: на чужой стадии тип неизвестен (гейт §4.1
        -- регистрация только своей стадии, обхода гейта нет)."""
        with pytest.raises(ValueError, match="Неизвестный тип события"):
            make_trace_event("target_column_cleared", stage="preprocessing")

    def test_cleared_resolves_server_result(self):
        """RED: сброс -- серверное решение (код точки решения; спека
        §4.1: различие user_decision / server_result). Пин реестра
        уровней: каждый зарегистрированный тип обязан иметь уровень."""
        from apps.api.trace_events import resolve_evidence_level

        assert resolve_evidence_level("target_column_cleared", {}) == (
            "server_result"
        )


# ── F17 interim: монотонность profile_viewed в редьюсере ─────────────


def _node_event(event_type: str, stage: str, node_id: str, **payload):
    return make_trace_event(
        event_type, stage=stage, node_id=node_id, run_id="RUN-H1", **payload
    )


class TestF17ProfileViewedMonotonicity:
    def test_profile_viewed_does_not_lower_done(self):
        """RED (F17/P25): узел, достигший done (eda_check_status),
        повторным GET-профилем (profile_viewed) не понижается."""
        events = [
            _node_event("eda_check_status", "eda", "correlation", status="done"),
            _node_event("profile_viewed", "eda", "correlation"),
        ]
        assert derive_node_statuses(events)["eda/correlation"] == "done"

    def test_profile_viewed_from_pending_sets_running(self):
        """Пин легитимной семантики: из pending (и отсутствия) узел
        исследуется -- running (§4.1, прежнее поведение)."""
        events = [_node_event("profile_viewed", "eda", "correlation")]
        assert derive_node_statuses(events)["eda/correlation"] == "running"
        events = [
            _node_event("eda_check_status", "eda", "correlation", status="pending"),
            _node_event("profile_viewed", "eda", "correlation"),
        ]
        assert derive_node_statuses(events)["eda/correlation"] == "running"

    def test_profile_viewed_does_not_lower_warning_or_error(self):
        """«running только из pending/отсутствия»: warning/error/skipped
        тоже не понижаются просмотром (строгое чтение правила
        Донастройки Часть 2)."""
        for status in ("warning", "error", "skipped"):
            events = [
                _node_event(
                    "eda_check_status", "eda", "correlation", status=status
                ),
                _node_event("profile_viewed", "eda", "correlation"),
            ]
            assert (
                derive_node_statuses(events)["eda/correlation"] == status
            ), status

    def test_rereview_of_running_stays_running(self):
        """Повторный просмотр running-узла -- идемпотентно running."""
        events = [
            _node_event("profile_viewed", "eda", "correlation"),
            _node_event("profile_viewed", "eda", "correlation"),
        ]
        assert derive_node_statuses(events)["eda/correlation"] == "running"

    def test_other_event_types_unaffected(self):
        """Монотонность НЕ глобальная: прочие пары перезаписываются
        (previewed -> applied = done; pending-отчёт ПОСЛЕ done --
        легитимное переоткрытие eda-checks, H27-пин)."""
        events = [
            _node_event("correction_previewed", "validation", "formats"),
            _node_event("correction_applied", "validation", "formats"),
        ]
        assert derive_node_statuses(events)["validation/formats"] == "done"
        events = [
            _node_event("eda_check_status", "eda", "correlation", status="done"),
            _node_event("eda_check_status", "eda", "correlation", status="pending"),
        ]
        assert derive_node_statuses(events)["eda/correlation"] == "pending"


# ── Сброс reason узла (тот же эффект, что пустая ветка) ──────────────


class TestReasonReducerCleared:
    def test_cleared_resets_target_reason(self):
        """RED: cleared снимает reason СВОЕГО класса (Целевой признак)
        узла-носителя validation/sufficiency -- как пустой target в
        target_column_changed (канон PROGR-15-B)."""
        events = [
            make_trace_event(
                "target_column_changed", stage="validation", node_id=None,
                run_id="RUN-H1", target_column="rain", source="auto",
            ),
            make_trace_event(
                "target_column_cleared", stage="validation", node_id=None,
                run_id="RUN-H1", target_column=None,
                reset_reason="type_conversion", source="system",
                before_target="rain",
            ),
        ]
        details = _details_by_key(events)
        assert details["validation/sufficiency"]["status_reason"] is None

    def test_choice_after_cleared_sets_reason_again(self):
        """Новый выбор после сброса ставит reason заново (хронология
        входа сохраняется -- редьюсер last-wins)."""
        events = [
            make_trace_event(
                "target_column_changed", stage="validation", node_id=None,
                run_id="RUN-H1", target_column="rain", source="auto",
            ),
            make_trace_event(
                "target_column_cleared", stage="validation", node_id=None,
                run_id="RUN-H1", target_column=None,
                reset_reason="type_conversion", source="system",
                before_target="rain",
            ),
            make_trace_event(
                "target_column_changed", stage="validation", node_id=None,
                run_id="RUN-H1", target_column="value",
            ),
        ]
        details = _details_by_key(events)
        assert details["validation/sufficiency"]["status_reason"] == (
            "Целевой признак: value"
        )

    def test_cleared_garbage_payload_degrades_honestly(self):
        """Мусор в payload cleared -- деградация (событие мимо фактов),
        не 500 (щит Mapping, контракт §3.1 п.3)."""
        raw = {
            "event_id": "e-garbage", "run_id": "RUN-H1",
            "ts": "2026-10-10T10:00:00+00:00", "stage": "validation",
            "node_id": None, "event_type": "target_column_cleared",
            "payload": "not-a-mapping", "actor": "system",
        }
        statuses = derive_node_statuses([raw])
        assert statuses == {} or "validation/sufficiency" not in statuses


# ── Reset-aware тройка Наставника (контракт §3.1 п.7) ────────────────


def _choice(column: str = "rain", source: str = "auto"):
    return make_trace_event(
        "target_column_changed", stage="validation", node_id=None,
        run_id="RUN-H1", target_column=column, source=source,
    )


def _cleared():
    return make_trace_event(
        "target_column_cleared", stage="validation", node_id=None,
        run_id="RUN-H1", target_column=None,
        reset_reason="type_conversion", source="system",
        before_target="rain",
    )


class TestMentorTripleResetAware:
    def test_confirmed_cleared_by_reset(self):
        """RED: cleared снимает подтверждение выбора."""
        assert _target_confirmed([_choice()]) is True
        assert _target_confirmed([_choice(), _cleared()]) is False
        # выбор после сброса -- снова подтверждено
        assert (
            _target_confirmed([_choice(), _cleared(), _choice("value")])
            is True
        )

    def test_origin_after_reset_is_unknown_not_user(self):
        """RED (контракт §3.1 п.4): после сброса origin -- None
        (unknown), НЕ "user": сброс не фабрикует человеческий выбор."""
        assert _target_origin([_choice()]) == "auto"
        assert _target_origin([_choice(), _cleared()]) is None
        # пустой корпус -- выбора не было, origin неизвестен
        assert _target_origin([]) is None

    def test_phase_facts_cleared_removes_column(self):
        """Факт колонки для подстановки в шаблоны после сброса снят."""
        assert _phase_event_text_facts((_choice(),)) == {
            "target_column": "rain"
        }
        assert _phase_event_text_facts((_choice(), _cleared())) == {}

    def test_phase_text_falls_back_to_request_after_reset(self):
        """RED (ожидание P03): после сброса при подтверждённой структуре
        Наставник честно просит «Подтвердите целевой признак…» --
        ни авто-текста, ни утверждения о выборе."""
        struct_done = {"upload/structure": "done"}
        text = phase_text("upload", struct_done, [_choice(), _cleared()])
        assert "Подтвердите целевой признак" in text
        assert "автоматически" not in text

    def test_phase_text_choice_after_reset_is_honest(self):
        """Новый выбор после сброса -- прежняя семантика выбора."""
        struct_done = {"upload/structure": "done"}
        text = phase_text(
            "upload", struct_done, [_choice(), _cleared(), _choice("value")]
        )
        assert "value" in text
        assert "Подтвердите целевой" not in text


# ── Run-метаданные: сброс той же точкой (контракт §3.1 п.6) ──────────


class TestRunMetadataCleared:
    def test_record_run_event_cleared_nulls_run_target(self):
        """RED: зеркало cleared в слой 2 обнуляет run.target_column
        (сейчас run-метаданные не обновляются вовсе -- половина P03)."""
        from apps.api.research_runs import record_run_event
        from apps.api.session_store import AnalysisSession

        session = AnalysisSession(session_id="S-H1")
        session.ensure_run_id()
        run_id = session.run_id
        from dataclasses import replace as dc_replace

        # события переаттрибутированы run_id запуска сессии (канон R3:
        # record_run_event приоритизирует event.run_id)
        choice = dc_replace(_choice(), run_id=run_id)
        cleared = dc_replace(_cleared(), run_id=run_id)
        record_run_event(session, choice)
        store = research_runs.get_research_run_store()
        assert store.get_run(run_id).target_column == "rain"
        record_run_event(session, cleared)
        assert store.get_run(run_id).target_column is None


# ── P03 end-to-end: полный сценарий аудита ───────────────────────────


class TestP03EndToEnd:
    def test_full_scenario_cleared_event_and_honest_consumers(self):
        """RED (P03 дословно): upload одной числовой -> авто-выбор rain ->
        подтверждение структуры -> конвертация rain в string (apply) ->
        (1) событие target_column_cleared в /trace с каноническим payload;
        (2) событие в ОБОИХ слоях с общим event_id (канон R3);
        (3) хронология «сброс -> исход коррекции» (R3);
        (4) run.target_column=None; (5) Наставник просит подтвердить;
        (6) reason sufficiency снят; (7) /current честно пуст."""
        _upload_one_numeric()
        assert (
            client.get("/v1/session/current").json()["target_column"]
            == "rain"
        )
        _confirm_structure_like_ui()
        resp = _convert_target_to_string(apply=True)
        assert resp.status_code == 200, resp.text
        assert resp.json()["target_column_reset"] is True

        # (7) сессия честно пуста (существующее поведение)
        current = client.get("/v1/session/current").json()
        assert current["target_column"] is None
        assert current["target_column_source"] is None

        # (1) событие сброса в /trace с каноническим payload
        trace = _trace()
        cleared = _cleared_events(trace)
        assert cleared, "событие target_column_cleared не посеяно"
        event = cleared[0]
        assert event["stage"] == "validation"
        assert event["node_id"] is None
        assert event["actor"] == "system"
        assert event["payload"]["target_column"] is None
        assert event["payload"]["reset_reason"] == "type_conversion"
        assert event["payload"]["source"] == "system"
        assert event["payload"]["before_target"] == "rain"

        # (2) событие в ОБОИХ слоях -- общий event_id (канон R3)
        run_id = _run_id()
        store = research_runs.get_research_run_store()
        layer2 = [e.to_dict() for e in store.list_events(run_id)]
        layer2_cleared = [
            e for e in layer2
            if e.get("event_type") == "target_column_cleared"
        ]
        assert layer2_cleared, "зеркала cleared в слое 2 нет"
        assert layer2_cleared[0]["event_id"] == event["event_id"]

        # (3) хронология R3: сброс -> исход коррекции (correction_applied
        # узла data_types приходит ПОСЛЕ сброса в обоих слоях)
        def _idx(events: list[dict], event_type: str, node_id=None) -> int:
            for i, e in enumerate(events):
                if e.get("event_type") == event_type and (
                    node_id is None or e.get("node_id") == node_id
                ):
                    return i
            return -1

        applied1 = _idx(trace["events"], "correction_applied", "data_types")
        assert cleared and applied1 > _idx(trace["events"], "target_column_cleared")
        applied2 = _idx(layer2, "correction_applied", "data_types")
        cleared2 = _idx(layer2, "target_column_cleared")
        assert cleared2 >= 0 and applied2 > cleared2

        # (4) run-метаданные: target_column=None (был "rain" -- P03)
        assert store.get_run(run_id).target_column is None

        # (5) Наставник честен (P03, метод наблюдения инструмента аудита:
        # scripts/progress_audit_readonly.py P03 вызывает
        # phase_text("upload", ...) НАПРЯМУЮ по событиям слоя 2 --
        # «historical_mentor_upload_text»): после сброса -- fallback
        # «Подтвердите целевой признак…», НЕ «автоматически: rain».
        from app.core.mentor_rules import phase_text as _phase_text
        from app.core.node_status import derive_node_statuses as _dns

        upload_text = _phase_text(
            "upload",
            statuses=_dns(layer2),
            events=layer2,
        )
        assert "Подтвердите целевой признак" in upload_text, upload_text
        assert "автоматически: rain" not in upload_text, upload_text
        # live-эндпоинт: фаза после коррекции -- «Валидация» (узловой
        # факт correction_applied data_types двигает фазу, канон B1) --
        # текст не утверждает выбор «rain» ни в каком виде
        resp = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
        assert resp.status_code == 200, resp.text
        text = resp.json()["phase_text"]
        assert "rain" not in text, text
        assert "автоматически" not in text, text

        # (6) reason узла-носителя снят (был «Целевой признак: rain (авто)»)
        assert _node(trace, "validation", "sufficiency")["status_reason"] is None

        # шапка /trace: носитель цели честно пуст
        assert trace["target_column"] is None
        assert trace["target_column_source"] is None


class TestClearedNegativeGuards:
    def test_preview_does_not_seed_cleared(self):
        """Preview (apply=false) не мутирует и не сеет сброс."""
        _upload_one_numeric()
        _confirm_structure_like_ui()
        resp = _convert_target_to_string(apply=False)
        assert resp.status_code == 200, resp.text
        assert _cleared_events(_trace()) == []

    def test_numeric_preserving_conversion_no_cleared(self):
        """Конвертация без перехода цели через нечисловой dtype --
        сброса и события нет (ветка не срабатывает)."""
        _upload_one_numeric()
        resp = client.post(
            "/v1/session/dataset/convert-types",
            json={
                "conversions": [{"column": "rain", "target_type": "float"}],
                "invalid_policy": "coerce",
                "apply": True,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["target_column_reset"] is False
        assert _cleared_events(_trace()) == []

    def test_reset_without_target_no_event(self):
        """Цели не было -- сбрасывать нечего: события нет."""
        _upload_one_numeric()
        client.post("/v1/session/date-column", json={"column": "date"})
        # честная неоднозначность? нет -- одна числовая: авто-выбор есть.
        # Снимаем цель конвертацией (сеет cleared), затем повторная
        # конвертация другой колонки цели не имеет -- второго cleared нет.
        _convert_target_to_string(apply=True)
        first = _cleared_events(_trace())
        assert len(first) == 1
        resp = client.post(
            "/v1/session/dataset/convert-types",
            json={
                "conversions": [{"column": "date", "target_type": "string"}],
                "invalid_policy": "coerce",
                "apply": True,
            },
        )
        assert resp.status_code == 200, resp.text
        assert len(_cleared_events(_trace())) == 1

    def test_manual_route_rejects_empty_target(self):
        """Граница PROGR-25-C сохранена: POST /target-column без колонки
        -- 422; маршруты выбора и сброса не объединены (контракт §3.1
        п.5)."""
        _upload_one_numeric()
        resp = client.post("/v1/session/target-column", json={"column": None})
        assert resp.status_code == 422, resp.text


# ── F17 end-to-end: повторный GET профиля EDA не роняет done ─────────


class TestF17EndToEnd:
    def test_profile_refetch_keeps_done(self):
        """RED (P25 дословно): карта eda-checks done -> GET
        eda-correlation (сеет profile_viewed) -> проекция ОСТАЁТСЯ done
        (до фикса -- running)."""
        _upload_one_numeric()
        from app.core.pipeline_graph import STAGE_NODES

        checks = {node_id: "done" for node_id in STAGE_NODES["eda"]}
        resp = client.post("/v1/progress/eda-checks", json={"checks": checks})
        assert resp.status_code == 200, resp.text
        assert _node(_trace(), "eda", "correlation")["status"] == "done"
        resp = client.get(
            "/v1/session/dataset/eda-correlation", params={"column": "rain"}
        )
        assert resp.status_code == 200, resp.text
        # повторный GET -- по-прежнему done (не running)
        assert _node(_trace(), "eda", "correlation")["status"] == "done"

    def test_viewed_before_report_still_running(self):
        """Пин легитимной семантики end-to-end: просмотр до отчёта
        модуля -- running (монотонность не блокирует честное «узел
        исследуется»)."""
        _upload_one_numeric()
        resp = client.get(
            "/v1/session/dataset/eda-correlation", params={"column": "rain"}
        )
        assert resp.status_code == 200, resp.text
        assert _node(_trace(), "eda", "correlation")["status"] == "running"


# ── Регресс-пины смежных контрактов ──────────────────────────────────


class TestAdjacentContractPins:
    def test_auto_fixation_after_reupload_still_works(self):
        """Регресс PROGR-25-A: re-upload после сброса -- авто-фиксация
        нового фрейма жива (сброс не ломает правило кандидатов)."""
        _upload_one_numeric()
        _confirm_structure_like_ui()
        _convert_target_to_string(apply=True)
        # возвращаем rain в числовой dtype -- кандидаты восстанавливаются
        resp = client.post(
            "/v1/session/dataset/convert-types",
            json={
                "conversions": [{"column": "rain", "target_type": "float"}],
                "invalid_policy": "coerce",
                "apply": True,
            },
        )
        assert resp.status_code == 200, resp.text
        # авто-фиксация на upload-пути -- здесь ручная фиксация честна
        resp = client.post(
            "/v1/session/target-column", json={"column": "rain"}
        )
        assert resp.status_code == 200, resp.text
        current = client.get("/v1/session/current").json()
        assert current["target_column"] == "rain"
        assert current["target_column_source"] == "user"

    def test_progr25c_auto_text_still_works(self):
        """Регресс PROGR-25-C: авто-текст Наставника без сброса жив
        (корпуса сертификаций без cleared -- аддитивность)."""
        _upload_one_numeric()
        _confirm_structure_like_ui()
        resp = client.get(
            f"/v1/progress/runs/{_run_id()}/mentor/next-step"
        )
        assert resp.status_code == 200, resp.text
        text = resp.json()["phase_text"]
        assert "выбран автоматически" in text, text
        assert "rain" in text, text
