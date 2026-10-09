# tests/api/test_progress_audit_s.py
# Task ID: PROGR-AUDIT-S (2026-10-09) -- plan_progress_audit.md §5, задача
# AUDIT-S: версионированная схема событий, идентичность и время.
#
# Основание: spec_progress_audit.md §5 (F11/F16, P17/P23), §8.1 (минимальный
# контракт v2), plan_progress_audit.md §5 (карточка AUDIT-S) + «Донастройка
# плана» (оговорка-разблокировка: «добавление ТИПА события не ждёт AUDIT-S;
# добавление ПОЛЕЙ envelope -- ждёт» -- поля вводятся ИМЕННО здесь) +
# docs/progress_audit_contract.md v0.1-AUDIT-0 §3.2/§3.3/§4/§5.3 (редакция
# контракта для AUDIT-S -- §12 аддендума v0.2-AUDIT-S).
#
# RED-список карточки: P17/P23 с исправленным ожиданием; v1 без source и
# новых полей; повторное чтение legacy возвращает одинаковый id; два
# независимых одинаковых результата сохраняются; невалидная схема не
# изменяет проекцию.
#
# Границы (сознательно, план §5 + контракт §7):
#   * sequence НИКЕМ не присваивается -- авторитетный порядок назначит
#     ledger-store в AUDIT-6A; чтение sequence здесь -- только контракт
#     схемы и ветка порядка «если есть у ВСЕХ событий корпуса»;
#   * строка слоя 2 PostgreSQL остаётся v1 до аддитивной миграции AUDIT-6A:
#     маркировка времени на PG-границе производится ДО записи (честность
#     на границе), durable-хранение envelope -- задача AUDIT-6A;
#   * sort_events_chronologically отчёта не трогается (потребитель отчёта
#     мигрирует на канонический порядок в AUDIT-5B).
"""Контракт AUDIT-S: envelope v2 поверх канона §4.1, стабильная
идентичность legacy, честное время, единое чтение порядка."""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.research_runs import MemoryResearchRunStore, _ts_to_db
from apps.api.session_store import (
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import (
    ENVELOPE_REQUIREMENTS,
    EVIDENCE_LEVELS,
    STAGE_EVENT_TYPES,
    RUN_LEVEL_EVENT_TYPES,
    TraceEvent,
    canonical_event_order,
    canonicalize_stored_event,
    derive_stable_event_id,
    make_trace_event,
    mark_honest_time,
    merge_canonical_events,
    normalize_trace_event_dict,
    resolve_evidence_level,
    stamp_envelope,
    validate_envelope,
)
from app.core.node_status import derive_node_statuses
from app.core.run_report import sort_events_chronologically


# ── Фикстуры ──────────────────────────────────────────────────────


@pytest.fixture()
def client():
    reset_session_store_for_testing()
    with TestClient(app) as test_client:
        yield test_client
    reset_session_store_for_testing()


def _legacy_raw() -> dict:
    """Legacy 3-польная запись (историческая популяция ForecastRun.trace)."""
    return {
        "event_type": "forecast_generated",
        "timestamp": "2026-02-01T10:00:00+00:00",
        "payload": {"horizon": 6},
    }


def _canonical_raw(event_id: str = "e" * 32) -> dict:
    """Канонический stored-dict §4.1 (как event.to_dict у слоя 1)."""
    return {
        "event_id": event_id,
        "run_id": "RUN-A1B2C3D4",
        "ts": "2026-02-01T10:00:00+00:00",
        "stage": "forecasting",
        "node_id": None,
        "event_type": "forecast_generated",
        "payload": {"horizon": 6},
        "actor": "system",
    }


def _seed_forecast_artifact(session, entries: list[dict], forecast_id: str = "fc-1") -> None:
    """Прямая инъекция прогнозных событий в артефакт сессии (паттерн
    N-1 tests/api/test_progress_panel.py::TestProgressTraceMerged)."""
    forecasts = session.modeling_artifacts.setdefault("forecasts", {})
    forecasts[forecast_id] = {"trace_events": entries}


# ── Идентичность: стабильный id legacy при повторном чтении (I1, P17) ──


class TestStableIdentity:
    def test_repeated_normalize_of_legacy_returns_same_id(self):
        """RED (поведение): normalize_trace_event_dict для legacy без id
        сегодня генерирует новый uuid4 на КАЖДОЕ чтение -- I1 нарушен
        (F11/P17). Правило: детерминированный stable-id."""
        a = normalize_trace_event_dict(_legacy_raw())
        b = normalize_trace_event_dict(_legacy_raw())
        assert a["event_id"] == b["event_id"]
        assert len(a["event_id"]) >= 32

    def test_explicit_id_passes_through(self):
        raw = _canonical_raw()
        assert normalize_trace_event_dict(raw)["event_id"] == "e" * 32

    def test_derive_stable_event_id_is_deterministic(self):
        first = derive_stable_event_id(
            run_id="",
            ts="2026-02-01T10:00:00+00:00",
            stage="forecasting",
            node_id=None,
            event_type="forecast_generated",
            payload={"horizon": 6},
        )
        second = derive_stable_event_id(
            run_id="",
            ts="2026-02-01T10:00:00+00:00",
            stage="forecasting",
            node_id=None,
            event_type="forecast_generated",
            payload={"horizon": 6},
        )
        assert first == second
        assert len(first) >= 32
        # payload сравнивается канонически (порядок ключей не влияет)
        third = derive_stable_event_id(
            run_id="",
            ts="2026-02-01T10:00:00+00:00",
            stage="forecasting",
            node_id=None,
            event_type="forecast_generated",
            payload={"horizon": 6, "alpha": 0.05},
        )
        assert third != first

    def test_derived_id_matches_normalize_rule(self):
        """normalize без id derives ровно derive_stable_event_id -- одна
        закреплённая правило идентичности, без скрытых вариантов."""
        raw = _legacy_raw()
        out = normalize_trace_event_dict(raw)
        assert out["event_id"] == derive_stable_event_id(
            run_id="",
            ts="2026-02-01T10:00:00+00:00",
            stage="forecasting",
            node_id=None,
            event_type="forecast_generated",
            payload={"horizon": 6},
        )

    def test_adapter_preserves_existing_identity(self):
        """RED (P17): адаптер сегодня ОТБРАСЫЫВАЕТ event_id/run_id/actor
        канонического события (F11). GREEN: сохраняет как есть."""
        raw = _canonical_raw()
        out = canonicalize_stored_event(raw)
        assert out["event_id"] == "e" * 32
        assert out["run_id"] == "RUN-A1B2C3D4"
        assert out["actor"] == "system"
        # семантика отображения прежняя: узел выводится из типа
        assert out["node_id"] == "forecast_generated"
        assert out["stage"] == "forecasting"

    def test_adapter_legacy_event_gets_stable_id_on_repeated_read(self):
        raw = _legacy_raw()
        first = canonicalize_stored_event(raw)
        second = canonicalize_stored_event(raw)
        assert first["event_id"] == second["event_id"]

    def test_merge_removes_duplicate_of_one_event_id(self):
        """RED (P17, вторая половина): merge сегодня НЕ удаляет дубликат
        того же факта из другого источника. GREEN: один event_id -- один
        экземпляр (первый источник приоритетен)."""
        layer1 = [_canonical_raw()]
        artifacts = [dict(_canonical_raw(), node_id="forecast_generated")]
        merged = merge_canonical_events(layer1, artifacts)
        assert len(merged) == 1
        assert merged[0]["event_id"] == "e" * 32

    def test_merge_keeps_two_independent_identical_results(self):
        """Два НЕЗАВИСИМЫХ действия с одинаковыми payload (разные
        event_id) не склеиваются -- dedupe строго по идентичности."""
        first = _canonical_raw(event_id="a" * 32)
        second = _canonical_raw(event_id="b" * 32)
        merged = merge_canonical_events([first], [second])
        assert len(merged) == 2
        assert {e["event_id"] for e in merged} == {"a" * 32, "b" * 32}

    def test_merge_without_ids_keeps_both_byte_identical_legacies(self):
        """Legacy без id: байт-в-байт одинаковые записи -- один факт по
        определению (стабильное правило выводит один id). РАЗНЫЕ payload
        -- разные факты."""
        same_a = normalize_trace_event_dict(_legacy_raw())
        same_b = normalize_trace_event_dict(_legacy_raw())
        different = normalize_trace_event_dict(
            {**_legacy_raw(), "payload": {"horizon": 12}}
        )
        merged = merge_canonical_events([same_a], [same_b, different])
        assert len(merged) == 2

    def test_trace_endpoint_dedupes_mirrored_forecast_event(self, client: TestClient):
        """Сквозной контракт /trace (фактический JSON, не dataclass):
        прогнозное событие, засеянное в слой 1 И живущее в артефакте под
        ОДНИМ event_id (канон R3 -- общий id двух слоёв), попадает в
        ответ ОДИН раз."""
        shared_id = "d" * 32
        mirrored = TraceEvent(
            event_type="forecast_generated",
            payload={"horizon": 6},
            event_id=shared_id,
            run_id="RUN-A1B2C3D4",
            ts="2026-02-01T10:00:00+00:00",
            stage="forecasting",
            node_id=None,
            actor="system",
        )
        store = get_session_store()
        session = store.get_or_create("audit-s-dedupe")
        session.append_trace_event(mirrored)
        _seed_forecast_artifact(
            session,
            [
                {
                    **mirrored.to_dict(),
                    # артефактная копия -- с отображаемым узлом
                    # (адаптер ставит node_id=event_type)
                }
            ],
        )
        store.save(session)
        client.cookies.set("cisstat_session_id", "audit-s-dedupe")
        resp = client.get("/v1/progress/trace")
        assert resp.status_code == 200
        events = resp.json()["events"]
        ids = [e["event_id"] for e in events]
        assert ids.count(shared_id) == 1


# ── Честное время (I-time, P23/F16) ───────────────────────────────


class TestHonestTime:
    def test_normalize_marks_degraded_for_unreadable_ts(self):
        """RED (P23, граница чтения): нечитаемый ts НЕ подменяется --
        сохраняется raw + маркировка degraded; observed_at -- отдельно."""
        raw = {"event_type": "forecast_generated", "timestamp": "not-a-date"}
        out = normalize_trace_event_dict(raw)
        assert out["ts"] == "not-a-date"  # НЕ заменён
        tq = out["time_quality"]
        assert tq["quality"] == "degraded"
        assert tq["raw_ts"] == "not-a-date"
        # observed_at -- читаемое ISO-время наблюдения (заполнено)
        datetime.fromisoformat(tq["observed_at"])

    def test_normalize_valid_ts_adds_no_time_quality(self):
        """Валидный ts -- время честное само по себе: поле отсутствует
        (v1-чтение остаётся байт-в-байт, без шума)."""
        out = normalize_trace_event_dict(_legacy_raw())
        assert "time_quality" not in out

    def test_normalize_empty_ts_not_marked(self):
        """Отсутствие времени -- честное отсутствие (не «испорчено»):
        пустой ts не получает fake-маркировку degraded."""
        out = normalize_trace_event_dict({"event_type": "forecast_generated"})
        assert out["ts"] == ""
        assert "time_quality" not in out

    def test_normalize_idempotent_on_marked_event(self):
        marked = normalize_trace_event_dict(
            {"event_type": "forecast_generated", "timestamp": "bad-ts"}
        )
        reread = normalize_trace_event_dict(marked)
        assert reread["time_quality"] == marked["time_quality"]
        assert reread["event_id"] == marked["event_id"]

    def test_memory_store_preserves_raw_ts_and_marks(self):
        """RED (P23, граница записи Memory): store, сохраняющий raw,
        маркирует degraded ДО записи (событие объекта, не молчание)."""
        store = MemoryResearchRunStore()
        event = TraceEvent(event_type="forecast_generated", ts="garbage-ts")
        store.append_event("run-1", event)
        listed = store.list_events("run-1")
        assert listed[0].ts == "garbage-ts"  # raw сохранён
        assert listed[0].time_quality["quality"] == "degraded"
        assert listed[0].time_quality["raw_ts"] == "garbage-ts"

    def test_mark_honest_time_substituted_semantics(self):
        """Маркировка для store, ЗАМЕНЯЮЩЕГО значение (Postgres-строка):
        quality=substituted, observed_at=время записи, raw_ts сохранён;
        сам ts события объект НЕ переписывает (строку строит _ts_to_db)."""
        event = TraceEvent(event_type="forecast_generated", ts="broken")
        marked = mark_honest_time(event, substituted=True)
        assert marked.ts == "broken"
        assert marked.time_quality["quality"] == "substituted"
        assert marked.time_quality["raw_ts"] == "broken"
        datetime.fromisoformat(marked.time_quality["observed_at"])
        # маркировка не трогает валидные события
        ok = make_trace_event("forecast_generated")
        assert mark_honest_time(ok, substituted=True).time_quality is None

    def test_marking_not_duplicated(self):
        event = TraceEvent(event_type="forecast_generated", ts="bad")
        once = mark_honest_time(event, substituted=False)
        twice = mark_honest_time(once, substituted=True)
        assert twice.time_quality == once.time_quality

    def test_ts_to_db_row_contract_unchanged(self):
        """Строка БД требует datetime: совместимость точки записи
        сохраняется; честность перенесена в envelope-маркировку
        (durable-хранение маркировки -- миграция AUDIT-6A)."""
        assert isinstance(_ts_to_db("garbage"), datetime)
        assert isinstance(_ts_to_db("2026-02-01T10:00:00+00:00"), datetime)


# ── Уровни доказательности (контракт §4) ──────────────────────────


class TestEvidenceLevels:
    def test_every_registered_type_resolves_a_level(self):
        for stage, types in STAGE_EVENT_TYPES.items():
            for event_type in types:
                level = resolve_evidence_level(event_type, {})
                assert level in EVIDENCE_LEVELS, (stage, event_type, level)
        for event_type in RUN_LEVEL_EVENT_TYPES:
            assert resolve_evidence_level(event_type, {}) in EVIDENCE_LEVELS

    def test_target_changed_payload_aware(self):
        """source=auto -- server_result; отсутствие source у legacy-ВЫБОРА
        -- user_decision (согласованная семантика PROGR-25-A, контракт
        §3.7); дефолтный actor НЕ доказывает осознанный выбор."""
        assert (
            resolve_evidence_level("target_column_changed", {"source": "auto"})
            == "server_result"
        )
        assert resolve_evidence_level("target_column_changed", {}) == "user_decision"
        assert (
            resolve_evidence_level("target_column_changed", {"source": "user"})
            == "user_decision"
        )

    def test_unknown_type_resolves_none(self):
        assert resolve_evidence_level("future_type", {}) is None

    def test_system_act_is_not_user_decision(self):
        assert resolve_evidence_level("upload_completed", {}) == "server_result"
        assert resolve_evidence_level("profile_viewed", {}) == "operational"


# ── Envelope v2: stamp/roundtrip/обязательность (контракт §3.2/§5.3) ──


class TestEnvelopeV2:
    def test_v1_event_to_dict_is_nine_keys(self):
        """Канон §4.1 без envelope -- ровно 8 полей + legacy-алиас:
        аддитивность = v1-корпус не меняет форму (оракул повторен здесь
        рядом с test_trace_events.py)."""
        raw = make_trace_event("forecast_generated", horizon=6).to_dict()
        assert set(raw.keys()) == {
            "event_id", "run_id", "ts", "stage", "node_id",
            "event_type", "payload", "actor", "timestamp",
        }

    def test_stamp_envelope_auto_schema_version_and_evidence(self):
        event = make_trace_event("validation_check_status", stage="validation", status="done")
        stamped = stamp_envelope(event, operation_id="op-1")
        assert stamped.schema_version == 2
        assert stamped.evidence_level == "client_observation"
        assert stamped.operation_id == "op-1"
        # незаполненные поля -- None
        assert stamped.sequence is None
        assert stamped.context_id is None

    def test_stamp_envelope_explicit_values_win(self):
        event = make_trace_event("forecast_generated")
        stamped = stamp_envelope(
            event,
            schema_version=2,
            evidence_level="server_result",
            sequence=7,
            operation_id="op-2",
            causation_id="req-3",
            context_id="ctx-4",
            result_ref={"result_id": "res-1"},
            method={"algorithm": "arima"},
            time_quality={"quality": "ok"},
        )
        assert stamped.schema_version == 2
        assert stamped.evidence_level == "server_result"
        assert stamped.sequence == 7
        assert stamped.operation_id == "op-2"
        assert stamped.causation_id == "req-3"
        assert stamped.context_id == "ctx-4"
        assert stamped.result_ref == {"result_id": "res-1"}
        assert stamped.method == {"algorithm": "arima"}
        assert stamped.time_quality == {"quality": "ok"}

    def test_stamp_envelope_rejects_unknown_field(self):
        event = make_trace_event("forecast_generated")
        with pytest.raises(ValueError):
            stamp_envelope(event, bogus_field="x")

    def test_v2_to_dict_is_additive_nine_plus(self):
        stamped = stamp_envelope(
            make_trace_event("forecast_generated"),
            operation_id="op-1",
            evidence_level="server_result",
        )
        raw = stamped.to_dict()
        assert set(raw.keys()) == {
            "event_id", "run_id", "ts", "stage", "node_id",
            "event_type", "payload", "actor", "timestamp",
            "schema_version", "evidence_level", "operation_id",
        }
        assert raw["schema_version"] == 2
        # незаполненные envelope-ключи НЕ попадают в dict
        assert "sequence" not in raw
        assert "context_id" not in raw

    def test_v2_roundtrip_preserves_envelope(self):
        stamped = stamp_envelope(
            make_trace_event("correction_applied", stage="preprocessing"),
            operation_id="op-9",
            causation_id="req-9",
        )
        restored = TraceEvent.from_dict(stamped.to_dict())
        assert restored == stamped

    def test_requiredness_table_covers_all_levels(self):
        assert set(ENVELOPE_REQUIREMENTS.keys()) == set(EVIDENCE_LEVELS)
        for level, required in ENVELOPE_REQUIREMENTS.items():
            assert "schema_version" in required
            assert "evidence_level" in required

    def test_validate_envelope_flags_missing_required(self):
        user = stamp_envelope(
            make_trace_event(
                "target_column_changed", stage="validation", target_column="temp"
            ),
            operation_id="op-5",
        )
        violations = validate_envelope(user.to_dict())
        assert any("causation_id" in v for v in violations)
        full = stamp_envelope(
            user, causation_id="req-5", schema_version=2,
            evidence_level="user_decision",
        )
        assert validate_envelope(full.to_dict()) == []

    def test_garbage_envelope_sanitized_on_read(self):
        """Мусор в envelope -- деградация («событие мимо фактов», щит
        C-CERT), не 500 и не проход мусора дальше границы чтения."""
        raw = {
            **_canonical_raw(),
            "schema_version": "garbage",
            "evidence_level": 123,
            "sequence": "x",
            "time_quality": "oops",
            "operation_id": "op-keep",
        }
        out = normalize_trace_event_dict(raw)
        assert "schema_version" not in out
        assert "evidence_level" not in out
        assert "sequence" not in out
        assert "time_quality" not in out
        assert out["operation_id"] == "op-keep"  # корректно типизированное -- сохранено

    def test_invalid_envelope_does_not_change_projection(self):
        """RED-критерий карточки: невалидная схема не изменяет проекцию --
        деривация статусов идентична на корпусе с мусорным envelope и
        без него."""
        base = [
            normalize_trace_event_dict(
                {
                    "event_id": f"id-{i}",
                    "run_id": "run-1",
                    "ts": f"2026-02-01T10:0{i}:00+00:00",
                    "stage": "validation",
                    "node_id": None,
                    "event_type": "validation_check_status",
                    "payload": {"check": "formats", "status": "done"},
                    "actor": "user",
                }
            )
            for i in (1, 2)
        ]
        polluted = [
            {**event, "schema_version": {"bad": 1}, "evidence_level": [], "time_quality": 5}
            for event in base
        ]
        assert derive_node_statuses(base) == derive_node_statuses(polluted)


# ── Единое чтение канонического порядка (контракт §3.3) ───────────


class TestCanonicalOrder:
    def _corpus(self) -> list[dict]:
        events = [
            {
                "event_id": f"id-{i}",
                "run_id": "run-1",
                "ts": ts,
                "stage": "validation",
                "node_id": None,
                "event_type": "validation_check_status",
                "payload": {},
                "actor": "user",
            }
            for i, ts in enumerate(
                (
                    "2026-02-01T12:00:00+00:00",
                    "2026-02-01T10:00:00+00:00",
                    "not-a-date",
                    "2026-02-01T11:00:00+00:00",
                    "",
                )
            )
        ]
        return events

    def test_legacy_branch_matches_chronological_sort(self):
        corpus = self._corpus()
        assert canonical_event_order(corpus) == sort_events_chronologically(corpus)

    def test_unreadable_ts_end_stable(self):
        corpus = self._corpus()
        ordered = canonical_event_order(corpus)
        tail = [e["ts"] for e in ordered[-2:]]
        assert tail == ["not-a-date", ""]

    def test_all_sequence_branch_orders_by_sequence(self):
        corpus = [
            {**_canonical_raw(event_id="x" * 32), "sequence": 3},
            {**_canonical_raw(event_id="y" * 32), "sequence": 1},
            {**_canonical_raw(event_id="z" * 32), "sequence": 2},
        ]
        ordered = canonical_event_order(corpus)
        assert [e["sequence"] for e in ordered] == [1, 2, 3]

    def test_mixed_corpus_falls_back_to_legacy_branch(self):
        """Частичный sequence НЕ переупорядочивает корпус: ветка
        включается только когда sequence есть у ВСЕХ событий (план §5:
        новые sequence присваивает store в AUDIT-6A)."""
        corpus = [
            {**_canonical_raw(event_id="x" * 32), "sequence": 3},
            _canonical_raw(event_id="y" * 32),  # без sequence, ts тот же
        ]
        assert canonical_event_order(corpus) == sort_events_chronologically(corpus)

    def test_merge_canonical_events_orders_and_dedupes(self):
        first = _canonical_raw(event_id="a" * 32)
        late = {
            **_canonical_raw(event_id="b" * 32),
            "ts": "2026-02-01T09:00:00+00:00",
        }
        dup = dict(first)  # тот же id, другой источник
        merged = merge_canonical_events([first, late], [dup])
        assert [e["event_id"] for e in merged] == ["b" * 32, "a" * 32]

    def test_merge_preserves_envelope_of_surviving_event(self):
        stamped = stamp_envelope(
            TraceEvent(**{
                "event_type": "forecast_generated",
                "payload": {"horizon": 6},
                "event_id": "c" * 32,
                "ts": "2026-02-01T10:00:00+00:00",
            }),
            operation_id="op-7",
        )
        merged = merge_canonical_events([], [stamped.to_dict()])
        assert merged[0]["operation_id"] == "op-7"


# ── DTO-совместимость: новые поля доходят до UI (фактический JSON) ────


class TestDtoCompat:
    def test_progress_trace_response_passes_envelope_through(self):
        from apps.api.routers.progress import ProgressTraceResponse

        stamped = stamp_envelope(
            make_trace_event(
                "validation_check_status", stage="validation", status="done"
            ),
            operation_id="op-1",
        )
        resp = ProgressTraceResponse(events=[stamped.to_dict()])
        # pydantic-фильтрация НЕ съедает envelope (риск карточки §5)
        assert resp.model_dump()["events"][0]["schema_version"] == 2

    def test_forecast_schema_accepts_envelope_additively(self):
        """Риск карточки: pydantic-фильтрация скрывает новые поля. Схема
        расширяется аддитивно: v2 -- поля заполнены, v1 -- None."""
        from apps.api.schemas import ForecastTraceEventSchema

        stamped = stamp_envelope(
            make_trace_event("forecast_generated"),
            operation_id="op-3",
            evidence_level="server_result",
        )
        v2 = ForecastTraceEventSchema(**stamped.to_dict())
        assert v2.schema_version == 2
        assert v2.evidence_level == "server_result"
        assert v2.operation_id == "op-3"
        v1 = ForecastTraceEventSchema(**_legacy_raw())
        assert v1.schema_version is None
        assert v1.evidence_level is None
        assert v1.event_type == "forecast_generated"
        assert v1.timestamp == "2026-02-01T10:00:00+00:00"

    def test_json_serializable_with_envelope(self):
        stamped = stamp_envelope(
            make_trace_event("forecast_generated"),
            result_ref={"result_id": "res-1", "hash": "sha256:abc"},
            method={"algorithm": "iqr", "rule_version": "3"},
            time_quality={"quality": "ok", "raw_ts": "", "observed_at": ""},
        )
        raw = stamped.to_dict()
        assert json.loads(json.dumps(raw)) == raw
