# scripts/prograudit5bcert_oracles.py
"""Независимая сертификация AUDIT-5B (plan_progress_audit.md §8) — СВОИ
оракулы сертификатора на СВОИХ данных (прецедент PROGR-AUDIT-6A-CERT).

Тема данных сертификатора -- речная гидрология (расход/уровень); все
run_id RUN-C5B-*, event_id c5b-*, контексты c5b-ctx-*, ts и payload
пиннуты детерминированно (урок 6A-CERT: фабрика с новым event_id на
вызов делает «тот же корпус» неопределимым).

Группы оракулов (контракт docs/progress_audit_contract.md §16, план §8):

  CC   канонический корпус: дедуп строго по event_id, приоритет
       идентичности источников, канонический порядок (sequence wins,
       частичный sequence не переупорядочивает, P12-механика), мусор
       честно пропущен, watermark == число фактов
  UR   единый редьюсер: инкрементальный NodeStateFold == батч-развёртки
       (статусы/детали/аномалии), делегирование derive-функций (нет
       второй реализации), last-wins, H1-монотонность, стадий fold
  SN   ProjectionSnapshot: форма, events_total==watermark,
       display_events (I9: cap ограничивает список), JSON-roundtrip,
       restart через from_dict, мусор -> честные дефолты, last_sequence
  EQ   replay полного ledger == snapshot + tail (расщепления корпуса на
       СВОИХ позициях, JSON-checkpoint restart, свежие run_meta,
       tail из TraceEvent, watermark от base по контракту)
  WM   read-after-watermark: ProjectionPendingError в build/advance,
       честный текст позиции, HTTP-форма 409 projection_pending
  ST   started_at == run.created_at (НЕ ts первого события хвоста,
       P11/PR-3); run-less -- честное отсутствие
  VAL  применимость факта (PR-4): current/stale/unknown таблица,
       validity None при отсутствии статусного факта, I4 (факты не
       стираются), пересчёт при сместившемся контексте
  EV   доказательства полей (I10/PR-5/PR-6): source-ссылки
       status/reason/count как РАЗНЫЕ решения, невалидный payload не
       меняет детали (аномалия + касание), evidence_level, mode_source,
       ровно 13 полей узла
  RP   отчёт: canonical_order=True не пересортирует (P12/F08), default
       False -- прежняя ts-сортировка, равные ts стабильны, API-отчёт в
       каноническом порядке
  API  сквозные через живой API (Memory): P11-корпус 1050, 409,
       session_tail-деградация (PR-8), пустая сессия, Наставник на той
       же проекции + watermark, P17-дедуп, anomalies, 13 полей /trace,
       согласованность панель/Наставник/отчёт
  PG   живой PostgreSQL (pgserver): та же committed история (атомарный
       батч 6A) -- одинаковые состояния независимо от store, /trace на
       PG-бэкенде == Memory, session_tail-деградации на живом store нет

Запуск: python3 scripts/prograudit5bcert_oracles.py
Результат: EXIT=0 -- все оракулы PASS; EXIT=1 -- есть FAIL (протокол
пишется в stdout, tee -> scripts/prograudit5bcert_oracles.txt).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Стенд: Memory-хранилище (средовой DATABASE_URL не должен уводить
# проекцию в Postgres; PG-группа управляет окружением сама).
os.environ.pop("DATABASE_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
os.environ.pop("REDIS_URL", None)

from apps.api.main import app  # noqa: E402
from apps.api.research_runs import (  # noqa: E402
    CommitEventBatch,
    ResearchRun,
    get_research_run_store,
    reset_research_run_store_for_testing,
)
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import (  # noqa: E402
    make_trace_event,
    stamp_envelope,
)
from app.core.node_status import (  # noqa: E402
    NodeStateFold,
    derive_node_statuses,
    derive_pipeline_node_states,
    derive_stage_states,
    event_to_dict,
)
from app.core.pipeline_graph import (  # noqa: E402
    VALIDITY_CURRENT,
    VALIDITY_STALE,
    VALIDITY_UNKNOWN,
)
from app.core.run_report import build_report_model  # noqa: E402
from apps.api.progress_projection import (  # noqa: E402
    ProjectionPendingError,
    ProjectionSnapshot,
    advance_projection,
    build_projection,
    canonical_corpus,
    event_context_validity,
)

RESULTS: list[tuple[str, str, str]] = []


# ── Мои данные: гидрология, всё пиннуто ───────────────────────────────

RUN_CREATED_AT = "2026-02-01T00:00:00+00:00"
CTX_A = "c5b-ctx-a1a1a1a1"
CTX_B = "c5b-ctx-b2b2b2b2"
CTX_C = "c5b-ctx-c3c3c3c3"


def _ts(minutes: int) -> str:
    base = datetime(2026, 2, 1, 6, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat()


def _evd(
    event_id: str,
    event_type: str,
    *,
    stage: str,
    node_id: str | None = None,
    ts: str,
    payload: dict | None = None,
    run_id: str | None = None,
    actor: str | None = "analyst",
    context_id: str | None = None,
    sequence: int | None = None,
    evidence_level: str | None = None,
) -> dict:
    """Stored-dict канона §4.1 (форма to_dict: 8 полей + timestamp-алиас
    + ТОЛЬКО заполненные envelope-поля) -- мой собственный формат
    фиксации корпуса; пиннутые id/ts делают корпус детерминированным."""
    data: dict = {
        "event_id": event_id,
        "run_id": run_id or "",
        "ts": ts,
        "timestamp": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": dict(payload or {}),
        "actor": actor,
    }
    if context_id is not None:
        data["context_id"] = context_id
    if sequence is not None:
        data["sequence"] = sequence
    if evidence_level is not None:
        data["evidence_level"] = evidence_level
    return data


def _ev(event_id: str, event_type: str, **kwargs):
    """TraceEvent (форма слоя 1) с пиннутым id/ts -- тот же корпус в
    смешанном представлении (легальный канон §4.1)."""
    ts = kwargs.pop("ts")
    ctx = kwargs.pop("context_id", None)
    level = kwargs.pop("evidence_level", None)
    seq = kwargs.pop("sequence", None)
    stage = kwargs.pop("stage")
    node_id = kwargs.pop("node_id", None)
    run_id = kwargs.pop("run_id", "")
    payload = kwargs.pop("payload", kwargs)
    event = make_trace_event(
        event_type, stage=stage, node_id=node_id, run_id=run_id, **payload
    )
    event = replace(event, ts=ts, event_id=event_id)
    fields: dict = {}
    if ctx is not None:
        fields["context_id"] = ctx
    if level is not None:
        fields["evidence_level"] = level
    if seq is not None:
        fields["sequence"] = seq
    if fields:
        event = stamp_envelope(event, **fields)
    return event


def _run_meta(
    run_id: str,
    *,
    created_at: str | None = RUN_CREATED_AT,
    context_id: str | None = CTX_A,
) -> dict:
    meta: dict = {
        "run_id": run_id,
        "session_id": f"sess-{run_id.lower()}",
        "dataset_fingerprint": "a" * 64,
        "dataset_name": "расход_реки.csv",
        "status": "active",
    }
    if created_at is not None:
        meta["created_at"] = created_at
        meta["last_active_at"] = created_at
    if context_id is not None:
        meta["context_id"] = context_id
    return meta


def _hydro_corpus(total: int = 1050, *, ctx: str | None = CTX_A,
                  seq_from: int = 1) -> list[dict]:
    """Мой нагрузочный корпус: upload первым (ранний прогресс), далее
    проверки Валидации; ts монотонны, id пиннуты."""
    events = [
        _evd(
            "c5b-up-0001", "upload_completed", stage="upload",
            node_id="overview", ts=_ts(0),
            payload={"name": "расход_реки.csv", "rows": total},
            run_id="RUN-C5B-BULK", context_id=ctx, sequence=seq_from,
        )
    ]
    for i in range(1, total):
        events.append(
            _evd(
                f"c5b-val-{i:05d}", "validation_check_status",
                stage="validation", node_id="data_types", ts=_ts(i),
                payload={"check_id": "data_types", "status": "done"},
                run_id="RUN-C5B-BULK", context_id=ctx,
                sequence=seq_from + i,
            )
        )
    return events


# ── Каркас проверок ───────────────────────────────────────────────────


def _check(group: str, code: str, title: str, func) -> None:
    name = f"{group}-{code}"
    try:
        func()
        RESULTS.append((name, title, "PASS"))
        print(f"[{name}] PASS: {title}")
    except AssertionError as exc:
        RESULTS.append((name, title, f"FAIL: {exc}"))
        print(f"[{name}] FAIL: {title} :: {exc}")
    except Exception as exc:  # неожиданное падение -- FAIL, не тишина
        RESULTS.append((name, title, f"FAIL ({type(exc).__name__}: {exc})"))
        print(f"[{name}] FAIL: {title} :: {type(exc).__name__}: {exc}")


def _assert_snapshot_states_equal(
    left: ProjectionSnapshot, right: ProjectionSnapshot, label: str
) -> None:
    """Эквивалентность состояний (приёмка плана §8): статус-карта,
    полные узлы с доказательствами, стадии, watermark, аномалии,
    last_sequence, last_event_id. Корпус может отличаться
    представлением -- состояния обязаны совпадать."""
    assert left.node_statuses == right.node_statuses, (
        f"{label}: node_statuses разошлись"
    )
    assert left.node_states == right.node_states, (
        f"{label}: node_states разошлись"
    )
    assert left.stage_states == right.stage_states, (
        f"{label}: stage_states разошлись"
    )
    assert left.watermark == right.watermark, (
        f"{label}: watermark {left.watermark} != {right.watermark}"
    )
    assert left.anomalies == right.anomalies, (
        f"{label}: anomalies {left.anomalies} != {right.anomalies}"
    )
    assert left.last_sequence == right.last_sequence, (
        f"{label}: last_sequence разошлись"
    )
    assert left.last_event_id == right.last_event_id, (
        f"{label}: last_event_id разошлись"
    )
    assert left.started_at == right.started_at, (
        f"{label}: started_at разошлись"
    )
    assert left.context_id == right.context_id, (
        f"{label}: context_id разошлись"
    )


# ── CC: канонический корпус ───────────────────────────────────────────


def cc1_dedup_strictly_by_event_id() -> None:
    ledger = [
        _evd("c5b-cc1-dup", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(1), payload={"name": "ledger.csv"},
             context_id=CTX_A, sequence=1),
        _evd("c5b-cc1-own", "structure_confirmed", stage="upload",
             node_id="structure", ts=_ts(2), payload={},
             context_id=CTX_A, sequence=2),
    ]
    layer1 = [
        # тот же event_id из слоя 1 -- НЕ второй факт (P17)
        _evd("c5b-cc1-dup", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(1), payload={"name": "слой1.csv"},
             context_id=CTX_A),
        # независимое событие с байт-совпадающим payload чужого -- живёт
        _evd("c5b-cc1-ind", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(1), payload={"name": "ledger.csv"},
             context_id=CTX_A),
    ]
    corpus = canonical_corpus(ledger, layer1)
    ids = [e["event_id"] for e in corpus]
    assert ids.count("c5b-cc1-dup") == 1, f"дубль факта: {ids}"
    assert "c5b-cc1-own" in ids and "c5b-cc1-ind" in ids, (
        f"независимые события потеряны: {ids}"
    )
    assert len(corpus) == 3, f"watermark корпуса: {len(corpus)} != 3"
    # приоритет идентичности: payload ledger-копии
    dup = next(e for e in corpus if e["event_id"] == "c5b-cc1-dup")
    assert dup["payload"] == {"name": "ledger.csv"}, (
        f"слой 1 перезаписал ledger: {dup['payload']}"
    )


def cc2_first_source_wins_in_any_order() -> None:
    first = [_evd("c5b-cc2-e1", "upload_completed", stage="upload",
                  node_id="overview", ts=_ts(1),
                  payload={"who": "первый"}, sequence=1)]
    second = [_evd("c5b-cc2-e1", "upload_completed", stage="upload",
                   node_id="overview", ts=_ts(1),
                   payload={"who": "второй"}, sequence=9)]
    merged = canonical_corpus(first, second)
    assert merged[0]["payload"] == {"who": "первый"}, (
        f"первый источник не приоритетен: {merged[0]['payload']}"
    )
    merged_rev = canonical_corpus(second, first)
    assert merged_rev[0]["payload"] == {"who": "второй"}, (
        "при смене порядка источников приоритет не сместился"
    )


def cc3_sequence_wins_over_ts() -> None:
    # обратный ts против sequence: канонический порядок -- по sequence
    events = [
        _evd("c5b-cc3-s3", "structure_confirmed", stage="upload",
             node_id="structure", ts=_ts(30), payload={},
             context_id=CTX_A, sequence=3),
        _evd("c5b-cc3-s1", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(10), payload={},
             context_id=CTX_A, sequence=1),
        _evd("c5b-cc3-s2", "validation_check_status", stage="validation",
             node_id="data_types", ts=_ts(20),
             payload={"check_id": "data_types", "status": "done"},
             context_id=CTX_A, sequence=2),
    ]
    corpus = canonical_corpus([events[0]], [events[1], events[2]])
    ids = [e["event_id"] for e in corpus]
    assert ids == ["c5b-cc3-s1", "c5b-cc3-s2", "c5b-cc3-s3"], (
        f"sequence не победил ts: {ids}"
    )
    fold = NodeStateFold()
    for e in corpus:
        fold.apply(e)
    assert fold.statuses.get("upload/overview") == "done"
    assert fold.statuses.get("validation/data_types") == "done"


def cc4_partial_sequence_does_not_reorder() -> None:
    # только у одного события есть sequence: корпус НЕ переупорядочивается
    events = [
        _evd("c5b-cc4-b", "structure_confirmed", stage="upload",
             node_id="structure", ts=_ts(20), payload={}, sequence=7),
        _evd("c5b-cc4-a", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(10), payload={}),
    ]
    corpus = canonical_corpus([events[0]], [events[1]])
    ids = [e["event_id"] for e in corpus]
    assert ids == ["c5b-cc4-a", "c5b-cc4-b"], (
        f"частичный sequence переупорядочил корпус: {ids}"
    )


def cc5_garbage_honestly_skipped() -> None:
    good = _evd("c5b-cc5-g1", "upload_completed", stage="upload",
                node_id="overview", ts=_ts(1), payload={})
    corpus = canonical_corpus(
        [good, None, "мусор", 42],  # не-события -- честный пропуск
        [_ev("c5b-cc5-g2", "profile_viewed", stage="eda",
             node_id="stationarity", ts=_ts(2), payload={})],
    )
    ids = [e["event_id"] for e in corpus]
    assert ids == ["c5b-cc5-g1", "c5b-cc5-g2"], (
        f"мусор не отфильтрован/события потеряны: {ids}"
    )
    # dict без event_id -- НЕ мусор: словарная форма канона §4.1 легальна,
    # дедуп возможен только по идентичности (id-less факт сохраняется)
    idless = canonical_corpus([{"event_id": "", "event_type": "x"}])
    assert len(idless) == 1, "id-less словарь утрачен"
    assert idless[0].get("event_id") == ""


def cc6_watermark_counts_facts_not_rows() -> None:
    ledger = [
        _evd(f"c5b-cc6-{i}", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(i), payload={})
        for i in range(1, 6)
    ]
    layer1 = [_evd("c5b-cc6-2", "upload_completed", stage="upload",
                   node_id="overview", ts=_ts(2), payload={})]
    snap = build_projection(ledger, layer1, run_meta=_run_meta("RUN-C5B-CC6"))
    assert snap.watermark == 5, (
        f"watermark считает строки, не факты: {snap.watermark} != 5"
    )
    assert snap.events_total == 5
    assert len(snap.events) == 5


# ── UR: единый редьюсер ───────────────────────────────────────────────


def _mixed_corpus() -> list:
    """Мой смешанный корпус: TraceEvent слоя 1 + stored-dict ledger,
    валидные payload, невалидный payload, stage-level reason."""
    return [
        _ev("c5b-ur-m1", "upload_completed", stage="upload",
            node_id="overview", ts=_ts(1), payload={"name": "река.csv"},
            context_id=CTX_A, sequence=1),
        _evd("c5b-ur-m2", "validation_check_status", stage="validation",
             node_id="data_types", ts=_ts(2),
             payload={"check_id": "data_types", "status": "done",
                      "total_invalid": 0},
             context_id=CTX_A, sequence=2),
        # stage-level reason (node_id=None, PROGR-21)
        _evd("c5b-ur-m3", "target_column_changed", stage="validation",
             node_id=None, ts=_ts(3),
             payload={"target_column": "расход", "source": "user"},
             context_id=CTX_A, sequence=3),
        # невалидный payload статусного типа (I10)
        _evd("c5b-ur-m4", "validation_check_status", stage="validation",
             node_id="data_types", ts=_ts(4),
             payload={"check_id": "data_types", "status": "дырка"},
             context_id=CTX_A, sequence=4),
        _ev("c5b-ur-m5", "profile_viewed", stage="eda",
            node_id="stationarity", ts=_ts(5), payload={},
            context_id=CTX_A, sequence=5),
    ]


def ur1_incremental_fold_equals_batch() -> None:
    corpus = _mixed_corpus()
    fold = NodeStateFold()
    for event in corpus:
        fold.apply(event)
    batch_statuses = derive_node_statuses(corpus)
    batch_states = derive_pipeline_node_states(corpus)
    assert fold.statuses == batch_statuses, (
        "инкрементальная свёртка != батч-статусам"
    )
    assert fold.node_states() == batch_states, (
        "инкрементальные детали != батч-деталям"
    )
    assert fold.anomaly_count == 1, (
        f"аномалии разошлись: {fold.anomaly_count} != 1"
    )
    # доказательства: та же свёртка, дополненная validity/mode_source
    evidenced = fold.node_states_with_evidence(run_context_id=CTX_A)
    for base, full in zip(batch_states, evidenced):
        for key in ("stage", "node_id", "status", "status_reason", "mode",
                    "last_touched_at", "summary_count"):
            assert base[key] == full[key], (
                f"{key}: батч {base[key]!r} != fold-evidence {full[key]!r}"
            )


def ur2_derive_functions_delegate_to_fold() -> None:
    corpus = _mixed_corpus()
    statuses_direct = derive_node_statuses(corpus)
    states_direct = derive_pipeline_node_states(corpus)
    fold = NodeStateFold()
    for event in corpus:
        fold.apply(event)
    assert statuses_direct == fold.statuses
    assert states_direct == fold.node_states()
    # пустой корпус -- честные pending всех узлов графа, не пустая карта
    empty_states = derive_pipeline_node_states([])
    assert empty_states, "пустой корпус потерял узлы графа"
    assert all(s["status"] == "pending" for s in empty_states)


def ur3_last_wins_and_h1_monotonicity() -> None:
    # last-wins: второй статусный факт перекрывает первый
    fold = NodeStateFold()
    fold.apply(_evd("c5b-ur3-a", "validation_check_status",
                    stage="validation", node_id="ranges", ts=_ts(1),
                    payload={"check_id": "ranges", "status": "done"}))
    fold.apply(_evd("c5b-ur3-b", "validation_check_status",
                    stage="validation", node_id="ranges", ts=_ts(2),
                    payload={"check_id": "ranges", "status": "pending"}))
    assert fold.statuses["validation/ranges"] == "pending", (
        "last-wins нарушен"
    )
    # H1-монотонность: повторный GET профиля не понижает done
    fold.apply(_evd("c5b-ur3-c", "eda_check_status", stage="eda",
                    node_id="stationarity", ts=_ts(3),
                    payload={"check_id": "stationarity", "status": "done"}))
    fold.apply(_evd("c5b-ur3-d", "profile_viewed", stage="eda",
                    node_id="stationarity", ts=_ts(4), payload={}))
    assert fold.statuses["eda/stationarity"] == "done", (
        "повторный просмотр понизил честный done (P25)"
    )


def ur4_stage_fold_canonical_order() -> None:
    corpus = _mixed_corpus()
    fold = NodeStateFold()
    for event in corpus:
        fold.apply(event)
    states = derive_stage_states(fold.statuses)
    assert [s["stage"] for s in states] == [
        "upload", "validation", "preprocessing", "eda", "modeling",
        "forecasting",
    ], "стадии не в каноническом порядке §2"
    upload = states[0]
    # overview=done при pending-остальных -- «в работе» (правило 5 §12.10)
    assert upload["fold"] == "attention", f"Загрузка: {upload['fold']}"
    validation = states[1]
    assert validation["fold"] == "attention", (
        f"Валидация с done-фактом: {validation['fold']}"
    )
    # пустой корпус -- все стадии честное «не начато» (not_started)
    empty = derive_stage_states({})
    assert all(s["fold"] == "not_started" for s in empty), (
        "пустой корпус не «не начато»"
    )


# ── SN: ProjectionSnapshot / checkpoint ───────────────────────────────


def sn1_snapshot_shape_and_display_cap() -> None:
    corpus = _hydro_corpus(40)
    snap = build_projection(corpus, run_meta=_run_meta("RUN-C5B-SN1"))
    for field in ("run_id", "watermark", "last_sequence", "started_at",
                  "context_id", "node_statuses", "node_states",
                  "stage_states", "events", "anomalies", "complete",
                  "last_event_id", "fold_state"):
        assert hasattr(snap, field), f"нет поля {field}"
    assert snap.run_id == "RUN-C5B-SN1"
    assert snap.complete is True
    assert snap.events_total == snap.watermark == 40
    assert snap.last_event_id == "c5b-val-00039"
    # I9: cap ограничивает список, не состояния
    display = snap.display_events(10)
    assert len(display) == 10
    assert display[-1]["event_id"] == "c5b-val-00039"
    assert display[0]["event_id"] == "c5b-val-00030"
    assert len(snap.events) == 40, "cap изменил накопленный корпус"
    assert snap.display_events(0) == []
    assert snap.display_events(-5) == []
    # 13 полей узла с доказательствами
    node = snap.node_states[0]
    assert len(node) == 13, f"полей узла: {len(node)} != 13"
    assert set(node) == {
        "stage", "node_id", "status", "status_reason", "mode",
        "last_touched_at", "summary_count", "source_event_id",
        "reason_source_event_id", "count_source_event_id",
        "evidence_level", "validity", "mode_source",
    }


def sn2_to_dict_json_roundtrip() -> None:
    corpus = _hydro_corpus(30)
    snap = build_projection(
        corpus, run_meta=_run_meta("RUN-C5B-SN2"),
        check_modes={"validation": {"data_types": "enabled"}},
    )
    raw = json.dumps(snap.to_dict(), ensure_ascii=False)
    restored = ProjectionSnapshot.from_dict(json.loads(raw))
    assert restored.watermark == 30
    assert restored.node_statuses == snap.node_statuses
    assert restored.node_states == snap.node_states, (
        "checkpoint потерял доказательства узлов"
    )
    assert restored.fold_state == snap.fold_state
    assert restored.last_sequence == snap.last_sequence
    assert restored.started_at == RUN_CREATED_AT
    assert restored.context_id == CTX_A
    assert restored.complete is True
    assert restored.last_event_id == snap.last_event_id
    # JSON-roundtrip и контрольный advance совпадают с живым снапшотом


def sn3_restart_keeps_early_statuses() -> None:
    # RED-критерий плана §8: restart проекции не теряет ранние статусы
    corpus = _hydro_corpus(60)
    full = build_projection(corpus, run_meta=_run_meta("RUN-C5B-SN3"))
    head = build_projection(corpus[:1], run_meta=_run_meta("RUN-C5B-SN3"))
    assert head.node_statuses.get("upload/overview") == "done"
    checkpoint = json.loads(json.dumps(head.to_dict()))
    restored = ProjectionSnapshot.from_dict(checkpoint)
    advanced = advance_projection(restored, list(corpus[1:]),
                                  run_meta=_run_meta("RUN-C5B-SN3"))
    _assert_snapshot_states_equal(advanced, full, "restart-advance")
    assert advanced.node_statuses.get("upload/overview") == "done", (
        "restart потерял ранний статус upload"
    )


def sn4_from_dict_garbage_honest_defaults() -> None:
    # Контейнерный мусор -- честные дефолты (формат наш, корпус не
    # переписывается). Скалярный нечисловой мусор watermark/anomalies
    # поднимает ValueError -- несоответствие докстрингу зафиксировано
    # находкой F-5B2 акта сертификации (граница до AUDIT-6B).
    snap = ProjectionSnapshot.from_dict(
        {"watermark": None, "anomalies": -5, "last_sequence": True,
         "node_statuses": None, "events": None, "fold_state": None}
    )
    assert snap.watermark == 0
    assert snap.anomalies == 0
    assert snap.last_sequence is None, "bool прошёл как sequence"
    assert snap.node_statuses == {}
    assert snap.events == ()
    assert snap.run_id is None and snap.started_at is None
    assert snap.complete is True  # честный дефолт восстановления


def sn5_last_sequence_pinned() -> None:
    corpus = [
        _evd("c5b-sn5-a", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(1), payload={}, sequence=11),
        _evd("c5b-sn5-b", "structure_confirmed", stage="upload",
             node_id="structure", ts=_ts(2), payload={}, sequence=4),
        _evd("c5b-sn5-c", "profile_viewed", stage="validation",
             node_id="ranges", ts=_ts(3), payload={}, sequence=True),
    ]
    snap = build_projection(corpus, run_meta=_run_meta("RUN-C5B-SN5"))
    assert snap.last_sequence == 11, (
        f"last_sequence: {snap.last_sequence} != 11 (bool не позиция)"
    )
    # bool НЕ позиция ledger даже когда она -- максимум материала:
    # честная позиция корпуса [0, True] -- 0, не 1
    bool_corpus = [
        _evd("c5b-sn5-d", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(1), payload={}, sequence=0),
        _evd("c5b-sn5-e", "structure_confirmed", stage="upload",
             node_id="structure", ts=_ts(2), payload={}, sequence=True),
    ]
    snap2 = build_projection(bool_corpus, run_meta=_run_meta("RUN-C5B-SN5B"))
    assert snap2.last_sequence == 0, (
        f"bool принят за позицию ledger: {snap2.last_sequence!r} != 0"
    )
    legacy = [_evd("c5b-sn5-l", "upload_completed", stage="upload",
                   node_id="overview", ts=_ts(1), payload={})]
    legacy_snap = build_projection(legacy)
    assert legacy_snap.last_sequence is None, (
        "legacy-корпус выдумал позицию ledger"
    )


# ── EQ: replay == snapshot + tail ─────────────────────────────────────

EQ_SPLITS = (3, 177, 512, 1024, 1499)


def _equivalence_case(split: int, *, via_json: bool, label: str) -> None:
    corpus = _hydro_corpus(1500)
    full = build_projection(corpus, run_meta=_run_meta("RUN-C5B-EQ"))
    head = build_projection(
        corpus[:split], run_meta=_run_meta("RUN-C5B-EQ")
    )
    if via_json:
        head = ProjectionSnapshot.from_dict(
            json.loads(json.dumps(head.to_dict()))
        )
    advanced = advance_projection(
        head, list(corpus[split:]), run_meta=_run_meta("RUN-C5B-EQ")
    )
    _assert_snapshot_states_equal(advanced, full, label)
    assert advanced.watermark == 1500, (
        f"{label}: watermark {advanced.watermark} != 1500"
    )


def eq1_replay_equals_snapshot_tail_splits() -> None:
    for split in EQ_SPLITS:
        _equivalence_case(
            split, via_json=False, label=f"split={split}"
        )


def eq2_replay_equals_checkpoint_restart() -> None:
    for split in (1, 999, 1499):
        _equivalence_case(
            split, via_json=True, label=f"json-restart split={split}"
        )


def eq3_advance_refreshes_run_meta() -> None:
    corpus = _hydro_corpus(10, ctx=CTX_A)
    head = build_projection(
        corpus[:4], run_meta=_run_meta("RUN-C5B-EQ3", context_id=CTX_A)
    )
    assert head.node_states[0]["validity"] == VALIDITY_CURRENT
    # контекст запуска сместился: свежие run_meta выравнивают validity
    advanced = advance_projection(
        head, corpus[4:], run_meta=_run_meta("RUN-C5B-EQ3", context_id=CTX_B)
    )
    assert advanced.context_id == CTX_B, "контекст не выровнялся свежим run"
    assert advanced.node_states[0]["validity"] == VALIDITY_STALE, (
        "старый факт при сместившемся контексте не помечен stale"
    )


def eq4_tail_accepts_trace_events() -> None:
    corpus = _hydro_corpus(12)
    head = build_projection(corpus[:5], run_meta=_run_meta("RUN-C5B-EQ4"))
    # ОДНИ и те же события в двух представлениях канона §4.1:
    # stored-dict (to_dict) и живой TraceEvent (слой 1)
    tail_events = [
        _ev(
            e["event_id"], e["event_type"], stage=e["stage"],
            node_id=e.get("node_id"), ts=e["ts"],
            payload=e.get("payload") or {},
        )
        for e in corpus[5:]
    ]
    tail_dicts = [e.to_dict() for e in tail_events]
    from_dicts = advance_projection(head, tail_dicts,
                                    run_meta=_run_meta("RUN-C5B-EQ4"))
    from_events = advance_projection(head, tail_events,
                                     run_meta=_run_meta("RUN-C5B-EQ4"))
    _assert_snapshot_states_equal(from_events, from_dicts, "tail-TraceEvent")


def eq5_watermark_position_from_base_not_merge() -> None:
    # контракт advance: позиция -- от base; дедуп хвоста против префикса
    # не выполняется (хвост -- канонический срез; ошибка вызывающего
    # ВИДНА по watermark) -- пиним документированное поведение
    corpus = _hydro_corpus(8)
    head = build_projection(corpus[:5], run_meta=_run_meta("RUN-C5B-EQ5"))
    doubled_tail = list(corpus[5:]) + list(corpus[2:5])
    advanced = advance_projection(head, doubled_tail,
                                  run_meta=_run_meta("RUN-C5B-EQ5"))
    assert advanced.watermark == 5 + len(doubled_tail), (
        "watermark advance не позиция base + хвост"
    )


# ── WM: read-after-watermark ──────────────────────────────────────────


def wm1_build_min_watermark_pending() -> None:
    corpus = _hydro_corpus(10)
    try:
        build_projection(corpus, min_watermark=11)
    except ProjectionPendingError:
        pass
    else:
        raise AssertionError("pending не поднят при недостижимой позиции")
    build_projection(corpus, min_watermark=10)  # ровно позиция -- ок
    build_projection(corpus, min_watermark=1)   # меньше -- ок


def wm2_advance_min_watermark_pending() -> None:
    corpus = _hydro_corpus(10)
    head = build_projection(corpus[:4])
    try:
        advance_projection(head, corpus[4:], min_watermark=11)
    except ProjectionPendingError:
        pass
    else:
        raise AssertionError("advance: pending не поднят")
    ok = advance_projection(head, corpus[4:], min_watermark=10)
    assert ok.watermark == 10
    # хвост НЕ применён к состоянию после отказа: повторный advance с
    # тем же head честен (отказ не потребляет/не портит checkpoint)
    retry = advance_projection(head, corpus[4:])
    assert retry.watermark == 10 and retry.last_event_id == ok.last_event_id


def wm3_pending_message_honest() -> None:
    corpus = _hydro_corpus(4)
    try:
        build_projection(corpus, min_watermark=100)
    except ProjectionPendingError as exc:
        text = str(exc)
        assert "4" in text and "100" in text, (
            f"текст pending не называет позиции: {text!r}"
        )
        assert "projection_pending" in text, (
            f"текст не именует projection_pending: {text!r}"
        )
    else:
        raise AssertionError("pending не поднят")


def wm4_http_409_projection_pending() -> None:
    from fastapi.testclient import TestClient

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    try:
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME)
            session = get_session_store().get_or_create(session_id)
            run_id = "RUN-C5B-WM4"
            session.run_id = run_id
            get_research_run_store().upsert_run(ResearchRun(
                run_id=run_id, session_id=session.session_id,
                dataset_fingerprint="f" * 64,
                dataset_name="расход_реки.csv", target_column="расход",
                created_at=RUN_CREATED_AT, last_active_at=RUN_CREATED_AT,
                context_id=CTX_A,
            ))
            for e in _hydro_corpus(15):
                event = _trace_of(e)
                get_research_run_store().append_event(run_id, event)
                session.append_trace_event(event)
            client.get("/v1/progress/trace")
            reached = client.get("/v1/progress/trace",
                                 params={"after_watermark": 10})
            assert reached.status_code == 200, (
                f"позиция 10 из 15 не отдана: {reached.status_code}"
            )
            pending = client.get("/v1/progress/trace",
                                 params={"after_watermark": 100})
            assert pending.status_code == 409, (
                f"недостижимая позиция не 409: {pending.status_code}"
            )
            assert "projection_pending" in str(pending.json()), (
                f"детали не projection_pending: {pending.json()}"
            )
    finally:
        reset_session_store_for_testing()
        reset_research_run_store_for_testing()


def _trace_of(data: dict):
    """stored-dict -> TraceEvent (запись слоя 1 через append_trace_event)."""
    from apps.api.trace_events import TraceEvent

    return TraceEvent.from_dict(data)


# ── ST: started_at из run.created_at (P11/PR-3) ───────────────────────


def st1_started_at_is_run_created_at() -> None:
    # первый ts корпуса -- 06:00, run.created_at -- 00:00: P11
    corpus = _hydro_corpus(5)
    snap = build_projection(corpus, run_meta=_run_meta("RUN-C5B-ST1"))
    assert snap.started_at == RUN_CREATED_AT, (
        f"started_at={snap.started_at!r} -- не run.created_at"
    )
    assert snap.started_at != corpus[0]["ts"]


def st2_runless_started_at_honest_none() -> None:
    corpus = _hydro_corpus(5)
    snap = build_projection(corpus, run_meta=None)
    assert snap.started_at is None, (
        "хвост начало не выдумывает: без run_meta started_at обязан None"
    )
    assert snap.watermark == 5  # корпус при этом честно спроецирован


def st3_run_meta_garbage_honest() -> None:
    corpus = _hydro_corpus(3)
    snap = build_projection(corpus, run_meta="мусор")  # type: ignore[arg-type]
    assert snap.run_id is None and snap.started_at is None
    assert snap.context_id is None
    snap2 = build_projection(
        corpus, run_meta={"run_id": "RUN-C5B-ST3", "created_at": 42,
                          "context_id": None}
    )
    assert snap2.run_id == "RUN-C5B-ST3"
    assert snap2.started_at is None, "числовой created_at стал строкой"


def st4_session_tail_started_at_none() -> None:
    # деградация PR-8: run_meta нет (хвост слоя 1) -- начало не
    # выдумывается из ts уцелевшего события
    corpus = _hydro_corpus(4)
    fold = NodeStateFold()
    for event in corpus:
        fold.apply(event)
    snap = build_projection(corpus, run_meta=None, corpus_complete=False)
    assert snap.complete is False
    assert snap.started_at is None
    assert snap.node_statuses == fold.statuses


# ── VAL: применимость факта (PR-4) ────────────────────────────────────


def val1_validity_truth_table() -> None:
    assert event_context_validity(None, CTX_A) == VALIDITY_UNKNOWN
    assert event_context_validity(CTX_A, None) == VALIDITY_UNKNOWN
    assert event_context_validity(None, None) == VALIDITY_UNKNOWN
    assert event_context_validity("", CTX_A) == VALIDITY_UNKNOWN
    assert event_context_validity(CTX_A, "") == VALIDITY_UNKNOWN
    assert event_context_validity(CTX_A, CTX_A) == VALIDITY_CURRENT
    assert event_context_validity(CTX_A, CTX_B) == VALIDITY_STALE


def val2_node_validity_levels() -> None:
    events = [
        # current: контекст события == контекст запуска
        _evd("c5b-val2-cur", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(1), payload={},
             context_id=CTX_A),
        # stale: факт другого контекста
        _evd("c5b-val2-stale", "eda_check_status", stage="eda",
             node_id="stationarity", ts=_ts(2),
             payload={"check_id": "stationarity", "status": "done"},
             context_id=CTX_B),
        # unknown: легаси-факт без контекста
        _evd("c5b-val2-unk", "validation_check_status",
             stage="validation", node_id="ranges", ts=_ts(3),
             payload={"check_id": "ranges", "status": "done"}),
    ]
    snap = build_projection(events,
                            run_meta=_run_meta("RUN-C5B-VAL2", context_id=CTX_A))
    overview = next(s for s in snap.node_states
                    if s["stage"] == "upload" and s["node_id"] == "overview")
    stationarity = next(s for s in snap.node_states
                        if s["stage"] == "eda" and s["node_id"] == "stationarity")
    ranges = next(s for s in snap.node_states
                  if s["stage"] == "validation" and s["node_id"] == "ranges")
    assert overview["validity"] == VALIDITY_CURRENT
    assert stationarity["validity"] == VALIDITY_STALE
    assert ranges["validity"] == VALIDITY_UNKNOWN, (
        "легаси-факт без контекста не unknown (PR-4)"
    )
    # узел без статусного факта -- validity None (не unknown!)
    untouched = next(s for s in snap.node_states
                     if s["stage"] == "modeling" and s["node_id"] == "selection")
    assert untouched["validity"] is None, (
        f"узел без факта: validity={untouched['validity']!r} != None"
    )
    assert untouched["source_event_id"] is None


def val3_historical_facts_not_erased_i4() -> None:
    events = [
        _evd("c5b-val3-old", "eda_check_status", stage="eda",
             node_id="stationarity", ts=_ts(1),
             payload={"check_id": "stationarity", "status": "done"},
             context_id=CTX_B),
    ]
    snap = build_projection(events,
                            run_meta=_run_meta("RUN-C5B-VAL3", context_id=CTX_A))
    stationarity = next(s for s in snap.node_states
                        if s["stage"] == "eda"
                        and s["node_id"] == "stationarity")
    assert stationarity["status"] == "done", (
        "исторический факт стёрт (I4)"
    )
    assert stationarity["validity"] == VALIDITY_STALE, (
        "исторический факт не помечен применимостью"
    )


def val4_validity_recomputed_on_context_shift() -> None:
    corpus = _hydro_corpus(6, ctx=CTX_A)
    snap = build_projection(corpus,
                            run_meta=_run_meta("RUN-C5B-VAL4", context_id=CTX_A))
    overview = next(s for s in snap.node_states
                    if s["stage"] == "upload" and s["node_id"] == "overview")
    assert overview["validity"] == VALIDITY_CURRENT
    # тот же корпус против СМЕСТИВШЕГОСЯ контекста запуска
    snap2 = build_projection(
        corpus, run_meta=_run_meta("RUN-C5B-VAL4", context_id=CTX_C)
    )
    overview2 = next(s for s in snap2.node_states
                     if s["stage"] == "upload" and s["node_id"] == "overview")
    assert overview2["validity"] == VALIDITY_STALE, (
        "validity не пересчитана против нового контекста запуска"
    )
    assert overview2["status"] == "done"  # факт остался (I4)


# ── EV: доказательства полей (I10/PR-5/PR-6) ──────────────────────────


def ev1_source_refs_are_separate_decisions() -> None:
    events = [
        _evd("c5b-ev1-status", "correction_applied", stage="preprocessing",
             node_id="outliers", ts=_ts(1),
             payload={"total_outliers_after": 3},
             context_id=CTX_A, sequence=1),
        # отдельное решение: stage-level смена цели -- свой reason
        _evd("c5b-ev1-target", "target_column_changed", stage="validation",
             node_id=None, ts=_ts(2),
             payload={"target_column": "расход", "source": "auto"},
             context_id=CTX_A, sequence=2),
    ]
    snap = build_projection(events, run_meta=_run_meta("RUN-C5B-EV1"))
    outliers = next(s for s in snap.node_states
                    if s["stage"] == "preprocessing"
                    and s["node_id"] == "outliers")
    assert outliers["source_event_id"] == "c5b-ev1-status"
    assert outliers["reason_source_event_id"] == "c5b-ev1-status"
    assert outliers["count_source_event_id"] == "c5b-ev1-status", (
        "счётчик бейджа не ссылается на своё событие (I10)"
    )
    assert outliers["summary_count"] == 3
    sufficiency = next(s for s in snap.node_states
                       if s["stage"] == "validation"
                       and s["node_id"] == "sufficiency")
    assert sufficiency["reason_source_event_id"] == "c5b-ev1-target", (
        "stage-level reason не сослался на свой источник (PROGR-21/I10)"
    )
    assert "расход" in (sufficiency["status_reason"] or "")
    assert sufficiency["source_event_id"] is None, (
        "stage-level reason породил статусный факт (N-2)"
    )


def ev2_invalid_payload_does_not_touch_details() -> None:
    good = _evd("c5b-ev2-good", "validation_check_status",
                stage="validation", node_id="ranges", ts=_ts(1),
                payload={"check_id": "ranges", "status": "done",
                         "total_violations": 2},
                context_id=CTX_A, sequence=1)
    fold = NodeStateFold()
    fold.apply(good)
    for bad_status in ("дырка", None, 1337, True):
        bad = _evd("c5b-ev2-bad", "validation_check_status",
                   stage="validation", node_id="ranges",
                   ts=_ts(2), payload={"check_id": "ranges",
                                       "status": bad_status},
                   context_id=CTX_A, sequence=2)
        fold.apply(bad)
    after = fold.node_states_with_evidence(run_context_id=CTX_A)
    ranges = next(s for s in after
                  if s["stage"] == "validation" and s["node_id"] == "ranges")
    assert ranges["status"] == "done" and ranges["status_reason"], (
        "невалидный payload стёр детали узла"
    )
    assert ranges["count_source_event_id"] == "c5b-ev2-good", (
        "счётчик перезаписан невалидным payload"
    )
    assert ranges["last_touched_at"] == _ts(2), (
        "касание журнала не зафиксировано (last_touched_at)"
    )
    assert ranges["source_event_id"] == "c5b-ev2-good"
    assert fold.anomaly_count == 4, (
        f"невалидные payload не посчитаны аномалиями: {fold.anomaly_count}"
    )
    # невалидный payload не меняет и reason (текст последнего валидного)
    assert "Проверка" in (ranges["status_reason"] or "") or ranges["status_reason"]


def ev3_evidence_level_flows_from_envelope() -> None:
    events = [
        _evd("c5b-ev3-v2", "upload_completed", stage="upload",
             node_id="overview", ts=_ts(1), payload={},
             context_id=CTX_A, evidence_level="server_result"),
        _evd("c5b-ev3-v1", "structure_confirmed", stage="upload",
             node_id="structure", ts=_ts(2), payload={}),  # легаси v1
    ]
    snap = build_projection(events, run_meta=_run_meta("RUN-C5B-EV3"))
    overview = next(s for s in snap.node_states
                    if s["stage"] == "upload" and s["node_id"] == "overview")
    structure = next(s for s in snap.node_states
                     if s["stage"] == "upload" and s["node_id"] == "structure")
    assert overview["evidence_level"] == "server_result", (
        "envelope v2 не дошёл до узла"
    )
    assert structure["evidence_level"] is None, (
        "легаси-факт получил выдуманный уровень (честное отсутствие)"
    )


def ev4_mode_source_session_vs_event() -> None:
    corpus = _hydro_corpus(4)
    snap = build_projection(
        corpus,
        run_meta=_run_meta("RUN-C5B-EV4"),
        check_modes={"validation": {"data_types": "enabled"}},
    )
    data_types = next(s for s in snap.node_states
                      if s["stage"] == "validation"
                      and s["node_id"] == "data_types")
    assert data_types["mode"] == "enabled"
    assert data_types["mode_source"] == "session", (
        "session-режим не помечен отдельно от event-derived (PR-6)"
    )
    assert data_types["source_event_id"], (
        "event-derived статус потерял свой источник"
    )
    # узел без mode из сессии -- mode_source None (не "session")
    overview = next(s for s in snap.node_states
                    if s["stage"] == "upload" and s["node_id"] == "overview")
    assert overview["mode"] is None and overview["mode_source"] is None


def ev5_node_evidence_contract_13_fields() -> None:
    corpus = _hydro_corpus(6)
    snap = build_projection(corpus, run_meta=_run_meta("RUN-C5B-EV5"))
    for state in snap.node_states:
        assert len(state) == 13, (
            f"узел {state['stage']}/{state['node_id']}: "
            f"{len(state)} полей != 13"
        )
    # батч-версия (7 полей) -- прежний публичный контракт
    batch = derive_pipeline_node_states(corpus)
    assert len(batch[0]) == 7, "батч-контракт 7 полей нарушен"


# ── RP: отчёт в каноническом порядке (P12/F08) ────────────────────────


def _report_fact_texts(model) -> list[str]:
    texts = [
        f.text for stage in model.stages
        for node in stage.nodes for f in node.facts
    ]
    texts += [
        f.text for stage in model.stages for f in stage.stage_level_facts
    ]
    return texts


def rp1_report_canonical_order_not_ts() -> None:
    # sequence-порядок: rain по sequence раньше, но ts -- позже (P12)
    events = [
        _evd("c5b-rp1-rain", "target_column_changed", stage="validation",
             node_id=None, ts=_ts(30),
             payload={"target_column": "расход"}, sequence=1),
        _evd("c5b-rp1-snow", "target_column_changed", stage="validation",
             node_id=None, ts=_ts(20),
             payload={"target_column": "уровень"}, sequence=2),
    ]
    model = build_report_model(
        _run_meta("RUN-C5B-RP1"), events, canonical_order=True
    )
    lines = _report_fact_texts(model)
    pos_rain = next(i for i, t in enumerate(lines) if "расход" in t)
    pos_level = next(i for i, t in enumerate(lines) if "уровень" in t)
    assert pos_rain < pos_level, (
        "canonical_order=True пересортировал корпус ts-сортировкой"
    )


def rp2_report_default_keeps_ts_sort() -> None:
    events = [
        _evd("c5b-rp2-rain", "target_column_changed", stage="validation",
             node_id=None, ts=_ts(30),
             payload={"target_column": "расход"}, sequence=1),
        _evd("c5b-rp2-snow", "target_column_changed", stage="validation",
             node_id=None, ts=_ts(20),
             payload={"target_column": "уровень"}, sequence=2),
    ]
    model = build_report_model(_run_meta("RUN-C5B-RP2"), events)
    lines = _report_fact_texts(model)
    pos_rain = next(i for i, t in enumerate(lines) if "расход" in t)
    pos_level = next(i for i, t in enumerate(lines) if "уровень" in t)
    assert pos_rain > pos_level, (
        "default-вызов пересортирован: прежнее поведение потеряно"
    )


def rp3_equal_ts_stable_order() -> None:
    events = [
        _evd("c5b-rp3-first", "target_column_changed", stage="validation",
             node_id=None, ts=_ts(10),
             payload={"target_column": "расход"}, sequence=1),
        _evd("c5b-rp3-second", "target_column_changed", stage="validation",
             node_id=None, ts=_ts(10),
             payload={"target_column": "уровень"}, sequence=2),
    ]
    model = build_report_model(
        _run_meta("RUN-C5B-RP3"), list(events), canonical_order=True
    )
    lines = _report_fact_texts(model)
    pos_rain = next(i for i, t in enumerate(lines) if "расход" in t)
    pos_level = next(i for i, t in enumerate(lines) if "уровень" in t)
    assert pos_rain < pos_level, "равные ts не сохранили порядок входа"


def rp4_api_report_uses_canonical_order() -> None:
    # API-отчёт обязан читать корпус в каноническом порядке (§16.1)
    from fastapi.testclient import TestClient

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    try:
        store = get_research_run_store()
        run_id = "RUN-C5B-RP4"
        store.upsert_run(ResearchRun(
            run_id=run_id, session_id="sess-c5b-rp4",
            dataset_fingerprint="b" * 64, dataset_name="расход_реки.csv",
            target_column="расход", created_at=RUN_CREATED_AT,
            last_active_at=RUN_CREATED_AT, context_id=CTX_A,
        ))
        seq = 1
        for target, minute in (("расход", 30), ("уровень", 20)):
            store.append_event(run_id, _ev(
                f"c5b-rp4-{seq:02d}", "target_column_changed",
                stage="validation", node_id=None, ts=_ts(minute),
                payload={"target_column": target, "source": "user"},
                context_id=CTX_A, sequence=seq, run_id=run_id,
            ))
            seq += 1
        with TestClient(app) as client:
            response = client.get(f"/v1/progress/runs/{run_id}/report")
            assert response.status_code == 200, response.text
            lines = response.text  # отчёт -- markdown (text/markdown)
            # факты смены цели: «Установлен исследуемый признак: X.»
            pos_rain = lines.find("Установлен исследуемый признак: расход")
            pos_level = lines.find("Установлен исследуемый признак: уровень")
            assert pos_rain != -1 and pos_level != -1, (
                f"факты смены цели не найдены: {pos_rain}/{pos_level}"
            )
            assert pos_rain < pos_level, (
                "API-отчёт пересортировал канонический корпус ts-сортировкой"
            )
    finally:
        reset_session_store_for_testing()
        reset_research_run_store_for_testing()


# ── API: сквозные через живой API (Memory) ────────────────────────────


def _api_seed_ledger(session, run_id: str, events: list[dict]) -> None:
    """Зеркалирование моего корпуса в ОБОИХ слоях (панель 5B читает
    полный ledger, слой 1 -- свежие не-зеркалированные)."""
    store = get_research_run_store()
    store.upsert_run(ResearchRun(
        run_id=run_id, session_id=session.session_id,
        dataset_fingerprint="c" * 64, dataset_name="расход_реки.csv",
        target_column="расход", created_at=RUN_CREATED_AT,
        last_active_at=RUN_CREATED_AT, context_id=CTX_A,
    ))
    for data in events:
        event = _trace_of(data)
        store.append_event(run_id, event)
        session.append_trace_event(event)


def api1_p11_full_ledger_projection() -> None:
    from fastapi.testclient import TestClient

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    try:
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME)
            session = get_session_store().get_or_create(session_id)
            run_id = "RUN-C5B-API1"
            session.run_id = run_id
            corpus = _hydro_corpus(1050)
            get_research_run_store().upsert_run(ResearchRun(
                run_id=run_id, session_id=session.session_id,
                dataset_fingerprint="c" * 64,
                dataset_name="расход_реки.csv", target_column="расход",
                created_at=RUN_CREATED_AT, last_active_at=RUN_CREATED_AT,
                context_id=CTX_A,
            ))
            for data in corpus:
                event = _trace_of(data)
                get_research_run_store().append_event(run_id, event)
                session.append_trace_event(event)
            response = client.get("/v1/progress/trace")
            assert response.status_code == 200, response.text
            body = response.json()
            # I9: состояния из полного корпуса; cap -- только список
            assert body["watermark"] == 1050, body["watermark"]
            assert body["events_total"] == 1050
            assert len(body["events"]) == 1000, (
                f"отображаемый список: {len(body['events'])}"
            )
            statuses = body["node_statuses"]
            assert statuses.get("upload/overview") == "done", (
                "ранний прогресс потерян (P11)"
            )
            assert statuses.get("validation/data_types") == "done"
            # P11/PR-3: начало -- run.created_at, не ts хвоста (06:51)
            assert body["started_at"] == RUN_CREATED_AT, body["started_at"]
            assert body["projection_source"] == "ledger"
            assert body["projection_complete"] is True
            assert body["context_id"] == CTX_A
            assert body["run_id"] == run_id
            nodes = body["nodes"]
            assert len(nodes[0]) == 13, f"полей узла /trace: {len(nodes[0])}"
    finally:
        reset_session_store_for_testing()
        reset_research_run_store_for_testing()


def api2_after_watermark_contract() -> None:
    from fastapi.testclient import TestClient

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    try:
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME)
            session = get_session_store().get_or_create(session_id)
            run_id = "RUN-C5B-API2"
            session.run_id = run_id
            corpus = _hydro_corpus(40)
            get_research_run_store().upsert_run(ResearchRun(
                run_id=run_id, session_id=session.session_id,
                dataset_fingerprint="c" * 64,
                dataset_name="расход_реки.csv", target_column="расход",
                created_at=RUN_CREATED_AT, last_active_at=RUN_CREATED_AT,
                context_id=CTX_A,
            ))
            for data in corpus:
                event = _trace_of(data)
                get_research_run_store().append_event(run_id, event)
                session.append_trace_event(event)
            reached = client.get("/v1/progress/trace",
                                 params={"after_watermark": 40})
            assert reached.status_code == 200
            pending = client.get("/v1/progress/trace",
                                 params={"after_watermark": 41})
            assert pending.status_code == 409
            assert "projection_pending" in str(pending.json())
            zero = client.get("/v1/progress/trace",
                              params={"after_watermark": 0})
            assert zero.status_code == 200
    finally:
        reset_session_store_for_testing()
        reset_research_run_store_for_testing()


def api3_session_tail_honest_degradation() -> None:
    from fastapi.testclient import TestClient

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    try:
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME)
            session = get_session_store().get_or_create(session_id)
            run_id = "RUN-C5B-API3"
            session.run_id = run_id
            for data in _hydro_corpus(12):
                session.append_trace_event(_trace_of(data))
            # слой 2 недоступен: запуск не найден (утерян/смена хранилища)
            response = client.get("/v1/progress/trace")
            assert response.status_code == 200, (
                "панель advisory-потребитель: 503 не вводится (§3.6)"
            )
            body = response.json()
            assert body["projection_source"] == "session_tail", body["projection_source"]
            assert body["projection_complete"] is False, (
                "хвост выдан за полную историю (PR-8)"
            )
            assert body["started_at"] is None, (
                "хвост начало не выдумывает (PR-8)"
            )
            assert body["watermark"] == 12
            assert body["node_statuses"].get("upload/overview") == "done"
    finally:
        reset_session_store_for_testing()
        reset_research_run_store_for_testing()


def api4_empty_session_honest() -> None:
    from fastapi.testclient import TestClient

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    try:
        with TestClient(app) as client:
            body = client.get("/v1/progress/trace").json()
            assert body["run_id"] is None
            assert body["events"] == []
            assert body["started_at"] is None
            assert body["watermark"] == 0 and body["events_total"] == 0
            assert body["projection_source"] == "session"
            assert body["projection_complete"] is True
            assert body["nodes"], "пустая сессия потеряла граф"
            assert all(
                node["status"] == "pending" for node in body["nodes"]
            ), "пустая сессия не честное «не начато» (§6.1)"
    finally:
        reset_session_store_for_testing()
        reset_research_run_store_for_testing()


def api5_mentor_same_projection_and_watermark() -> None:
    from fastapi.testclient import TestClient

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    try:
        store = get_research_run_store()
        run_id = "RUN-C5B-API5"
        store.upsert_run(ResearchRun(
            run_id=run_id, session_id="sess-c5b-api5",
            dataset_fingerprint="d" * 64, dataset_name="расход_реки.csv",
            target_column="расход", created_at=RUN_CREATED_AT,
            last_active_at=RUN_CREATED_AT, context_id=CTX_A,
        ))
        for data in _hydro_corpus(20):
            store.append_event(run_id, _trace_of(data))
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME)
            session = get_session_store().get_or_create(session_id)
            session.run_id = run_id
            # панель из ПОЛНОГО ledger (слои совпадают -- зеркалирование)
            trace = client.get("/v1/progress/trace").json()
            mentor = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
            assert mentor.status_code == 200, mentor.text
            body = mentor.json()
            assert body["watermark"] == trace["watermark"] == 20, (
                f"Наставник watermark {body['watermark']} != панели "
                f"{trace['watermark']} (одинаковый snapshot обязателен)"
            )
            assert body["events_total"] == 20
            assert body["last_active_stage"] == "validation", (
                f"фаза по последнему узловому факту: {body['last_active_stage']}"
            )
    finally:
        reset_session_store_for_testing()
        reset_research_run_store_for_testing()


def api6_p17_dedup_in_trace_response() -> None:
    from fastapi.testclient import TestClient

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    try:
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME)
            session = get_session_store().get_or_create(session_id)
            run_id = "RUN-C5B-API6"
            session.run_id = run_id
            get_research_run_store().upsert_run(ResearchRun(
                run_id=run_id, session_id=session.session_id,
                dataset_fingerprint="c" * 64,
                dataset_name="расход_реки.csv", target_column="расход",
                created_at=RUN_CREATED_AT, last_active_at=RUN_CREATED_AT,
                context_id=CTX_A,
            ))
            for data in _hydro_corpus(10):
                event = _trace_of(data)
                get_research_run_store().append_event(run_id, event)
                session.append_trace_event(event)  # зеркало тех же id
            body = client.get("/v1/progress/trace").json()
            assert body["watermark"] == 10, (
                f"зеркала слоя 1 посчитаны вторым фактом: {body['watermark']}"
            )
            assert body["events_total"] == 10
    finally:
        reset_session_store_for_testing()
        reset_research_run_store_for_testing()


def api7_anomalies_in_trace_response() -> None:
    from fastapi.testclient import TestClient

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    try:
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME)
            session = get_session_store().get_or_create(session_id)
            run_id = "RUN-C5B-API7"
            session.run_id = run_id
            get_research_run_store().upsert_run(ResearchRun(
                run_id=run_id, session_id=session.session_id,
                dataset_fingerprint="e" * 64,
                dataset_name="расход_реки.csv", target_column="расход",
                created_at=RUN_CREATED_AT, last_active_at=RUN_CREATED_AT,
                context_id=CTX_A,
            ))
            events = [
                _evd("c5b-api7-ok", "validation_check_status",
                     stage="validation", node_id="ranges", ts=_ts(1),
                     payload={"check_id": "ranges", "status": "done"},
                     context_id=CTX_A),
                _evd("c5b-api7-bad", "validation_check_status",
                     stage="validation", node_id="ranges", ts=_ts(2),
                     payload={"check_id": "ranges", "status": "мусор"},
                     context_id=CTX_A),
            ]
            for data in events:
                event = _trace_of(data)
                get_research_run_store().append_event(run_id, event)
                session.append_trace_event(event)
            body = client.get("/v1/progress/trace").json()
            assert body["anomalies"] == 1, f"anomalies: {body['anomalies']}"
            ranges = next(
                n for n in body["nodes"]
                if n["stage"] == "validation" and n["node_id"] == "ranges"
            )
            assert ranges["status"] == "done"
            assert ranges["source_event_id"] == "c5b-api7-ok", (
                "невалидный payload перезаписал доказательства (I10)"
            )
            assert ranges["last_touched_at"] == _ts(2), (
                "касание журнала потеряно"
            )
    finally:
        reset_session_store_for_testing()
        reset_research_run_store_for_testing()


# ── PG: живой PostgreSQL (pgserver) -- store-независимость ────────────


def _fresh_pg_schema(pg_uri: str) -> None:
    import psycopg

    with psycopg.connect(pg_uri, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")


def pg1_committed_history_same_states_as_memory() -> None:
    """Одна и та же committed история (атомарный батч 6A) даёт те же
    состояния проекции независимо от выбранного store (приёмка §8)."""
    run_id = "RUN-C5B-PG1"
    from apps.api.research_runs import PostgresResearchRunStore

    pg_uri = os.environ["C5B_CERT_PG_URI"]
    _fresh_pg_schema(pg_uri)
    pg_store = PostgresResearchRunStore(dsn=pg_uri)
    run = ResearchRun(
        run_id=run_id, session_id="sess-c5b-pg1",
        dataset_fingerprint="1" * 64, dataset_name="расход_реки.csv",
        target_column="расход", created_at=RUN_CREATED_AT,
        last_active_at=RUN_CREATED_AT, context_id=CTX_A,
    )
    events = tuple(_trace_of(e) for e in _hydro_corpus(25))
    receipt = pg_store.commit_event_batch(CommitEventBatch(
        run=run, events=events, idempotency_key="c5b-cert-pg1",
    ))
    assert receipt is not None and receipt.accepted_event_ids, (
        "committed история не записана в живой PG"
    )
    # проекция из живого PG
    pg_events = [e.to_dict() for e in pg_store.list_events(run_id)]
    pg_snap = build_projection(pg_events, run_meta=run.to_dict())
    # контрольный эталон: те же факты из памяти
    mem_snap = build_projection(
        [e.to_dict() for e in events], run_meta=run.to_dict()
    )
    _assert_snapshot_states_equal(pg_snap, mem_snap, "store-parity")
    assert pg_snap.watermark == 25
    assert pg_snap.last_sequence == 25, (
        f"ledger-позиция: {pg_snap.last_sequence}"
    )
    assert pg_snap.started_at == RUN_CREATED_AT
    assert pg_snap.context_id == CTX_A


def pg2_trace_on_postgres_backend_matches_memory() -> None:
    """/trace на PG-бэкенде: те же состояния, что на Memory (приёмка
    «независимо от выбранного store»), свой корпус и свой run."""
    from fastapi.testclient import TestClient

    pg_uri = os.environ["C5B_CERT_PG_URI"]
    _fresh_pg_schema(pg_uri)
    old_dsn = os.environ.get("DATABASE_URL")
    old_backend = os.environ.get("CISSTAT_RUNS_BACKEND")
    os.environ["DATABASE_URL"] = pg_uri
    os.environ["CISSTAT_RUNS_BACKEND"] = "postgres"
    reset_research_run_store_for_testing()
    reset_session_store_for_testing()
    try:
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME)
            session = get_session_store().get_or_create(session_id)
            run_id = "RUN-C5B-PG2"
            session.run_id = run_id
            get_research_run_store().upsert_run(ResearchRun(
                run_id=run_id, session_id=session.session_id,
                dataset_fingerprint="3" * 64,
                dataset_name="расход_реки.csv", target_column="расход",
                created_at=RUN_CREATED_AT, last_active_at=RUN_CREATED_AT,
                context_id=CTX_A,
            ))
            corpus = _hydro_corpus(30)
            for data in corpus:
                event = _trace_of(data)
                get_research_run_store().append_event(run_id, event)
                session.append_trace_event(event)
            body = client.get("/v1/progress/trace").json()
            assert body["projection_source"] == "ledger", (
                "живой PG не принят за полный ledger"
            )
            assert body["watermark"] == 30
            assert body["node_statuses"].get("upload/overview") == "done"
            assert body["started_at"] == RUN_CREATED_AT
            assert body["context_id"] == CTX_A
            assert body["projection_complete"] is True
    finally:
        if old_dsn is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_dsn
        if old_backend is None:
            os.environ.pop("CISSTAT_RUNS_BACKEND", None)
        else:
            os.environ["CISSTAT_RUNS_BACKEND"] = old_backend
        reset_research_run_store_for_testing()
        reset_session_store_for_testing()


def pg3_session_tail_never_on_live_store() -> None:
    """Живой store с запуском: деградации на хвост быть не должно --
    полная история читается из ledger (PR-8 не срабатывает ложно)."""
    from fastapi.testclient import TestClient

    pg_uri = os.environ["C5B_CERT_PG_URI"]
    _fresh_pg_schema(pg_uri)
    old_dsn = os.environ.get("DATABASE_URL")
    old_backend = os.environ.get("CISSTAT_RUNS_BACKEND")
    os.environ["DATABASE_URL"] = pg_uri
    os.environ["CISSTAT_RUNS_BACKEND"] = "postgres"
    reset_research_run_store_for_testing()
    reset_session_store_for_testing()
    try:
        store = get_research_run_store()
        run_id = "RUN-C5B-PG3"
        store.upsert_run(ResearchRun(
            run_id=run_id, session_id="sess-c5b-pg3",
            dataset_fingerprint="2" * 64, dataset_name="расход_реки.csv",
            created_at=RUN_CREATED_AT, last_active_at=RUN_CREATED_AT,
            context_id=CTX_A,
        ))
        for data in _hydro_corpus(8):
            store.append_event(run_id, _trace_of(data))
        with TestClient(app) as client:
            client.get("/v1/progress/trace")
            session_id = client.cookies.get(SESSION_COOKIE_NAME)
            session = get_session_store().get_or_create(session_id)
            session.run_id = run_id
            body = client.get("/v1/progress/trace").json()
            assert body["projection_source"] == "ledger", body["projection_source"]
            assert body["projection_complete"] is True
            assert body["watermark"] == 8
    finally:
        if old_dsn is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_dsn
        if old_backend is None:
            os.environ.pop("CISSTAT_RUNS_BACKEND", None)
        else:
            os.environ["CISSTAT_RUNS_BACKEND"] = old_backend
        reset_research_run_store_for_testing()
        reset_session_store_for_testing()


# ── Реестр и запуск ───────────────────────────────────────────────────

ORACLE_REGISTRY: list[tuple[str, str, str, object]] = [
    ("CC", "1", "дедуп строго по event_id; независимые события живы", cc1_dedup_strictly_by_event_id),
    ("CC", "2", "первый источник приоритетен при любом порядке", cc2_first_source_wins_in_any_order),
    ("CC", "3", "канонический порядок: sequence побеждает ts", cc3_sequence_wins_over_ts),
    ("CC", "4", "частичный sequence не переупорядочивает корпус", cc4_partial_sequence_does_not_reorder),
    ("CC", "5", "мусор честно пропущен; смешанные представления легальны", cc5_garbage_honestly_skipped),
    ("CC", "6", "watermark == число фактов, не строк", cc6_watermark_counts_facts_not_rows),
    ("UR", "1", "инкрементальный fold == батч-развёрткам (смешанный корпус)", ur1_incremental_fold_equals_batch),
    ("UR", "2", "derive-функции делегируют fold (нет второй реализации)", ur2_derive_functions_delegate_to_fold),
    ("UR", "3", "last-wins + H1-монотонность profile_viewed", ur3_last_wins_and_h1_monotonicity),
    ("UR", "4", "стадийный fold: 6 стадий канонического порядка, warning", ur4_stage_fold_canonical_order),
    ("SN", "1", "форма снапшота; events_total; I9 display cap", sn1_snapshot_shape_and_display_cap),
    ("SN", "2", "to_dict JSON-безопасен; from_dict восстанавливает всё", sn2_to_dict_json_roundtrip),
    ("SN", "3", "restart через from_dict не теряет ранние статусы", sn3_restart_keeps_early_statuses),
    ("SN", "4", "мусор from_dict -- честные дефолты", sn4_from_dict_garbage_honest_defaults),
    ("SN", "5", "last_sequence: max int; bool не позиция; legacy None", sn5_last_sequence_pinned),
    ("EQ", "1", "replay == snapshot+tail на моих расщеплениях", eq1_replay_equals_snapshot_tail_splits),
    ("EQ", "2", "эквивалентность через JSON-checkpoint restart", eq2_replay_equals_checkpoint_restart),
    ("EQ", "3", "advance выравнивает сместившийся run-контекст", eq3_advance_refreshes_run_meta),
    ("EQ", "4", "tail из TraceEvent == tail из dicts", eq4_tail_accepts_trace_events),
    ("EQ", "5", "watermark advance -- позиция base + хвост", eq5_watermark_position_from_base_not_merge),
    ("WM", "1", "build: min_watermark недостижим -- ProjectionPendingError", wm1_build_min_watermark_pending),
    ("WM", "2", "advance: pending не портит checkpoint; retry честен", wm2_advance_min_watermark_pending),
    ("WM", "3", "текст pending честно называет обе позиции", wm3_pending_message_honest),
    ("WM", "4", "HTTP-форма: 200 на позиции / 409 projection_pending", wm4_http_409_projection_pending),
    ("ST", "1", "started_at == run.created_at, не ts хвоста (P11)", st1_started_at_is_run_created_at),
    ("ST", "2", "run-less: started_at None (хвост начало не выдумывает)", st2_runless_started_at_honest_none),
    ("ST", "3", "мусор run_meta -- честные None", st3_run_meta_garbage_honest),
    ("ST", "4", "session_tail: started_at None, complete False", st4_session_tail_started_at_none),
    ("VAL", "1", "таблица истинности event_context_validity", val1_validity_truth_table),
    ("VAL", "2", "validity current/stale/unknown/None по узлам", val2_node_validity_levels),
    ("VAL", "3", "исторический факт не стёрт (I4), помечен stale", val3_historical_facts_not_erased_i4),
    ("VAL", "4", "смещение контекста запуска пересчитывает validity", val4_validity_recomputed_on_context_shift),
    ("EV", "1", "source-ссылки status/reason/count -- разные решения", ev1_source_refs_are_separate_decisions),
    ("EV", "2", "невалидный payload: детали не тронуты, аномалия, касание", ev2_invalid_payload_does_not_touch_details),
    ("EV", "3", "evidence_level из envelope; легаси -- честное None", ev3_evidence_level_flows_from_envelope),
    ("EV", "4", "mode_source=session против event-derived (PR-6)", ev4_mode_source_session_vs_event),
    ("EV", "5", "контракт 13 полей узла; батч -- 7 полей", ev5_node_evidence_contract_13_fields),
    ("RP", "1", "отчёт canonical_order=True не пересортирует (P12)", rp1_report_canonical_order_not_ts),
    ("RP", "2", "default-вызов отчёта хранит прежнюю ts-сортировку", rp2_report_default_keeps_ts_sort),
    ("RP", "3", "равные ts -- стабильный порядок входа", rp3_equal_ts_stable_order),
    ("RP", "4", "API-отчёт читает корпус в каноническом порядке", rp4_api_report_uses_canonical_order),
    ("API", "1", "P11 на живом API: 1050, ранний статус, started_at, watermark", api1_p11_full_ledger_projection),
    ("API", "2", "after_watermark: 200/409/0 контракт", api2_after_watermark_contract),
    ("API", "3", "session_tail: честная деградация без 503 (PR-8)", api3_session_tail_honest_degradation),
    ("API", "4", "пустая сессия: честные «не начато» (§6.1)", api4_empty_session_honest),
    ("API", "5", "Наставник на той же проекции; watermark совпадает", api5_mentor_same_projection_and_watermark),
    ("API", "6", "P17: зеркала слоя 1 не удваивают факты", api6_p17_dedup_in_trace_response),
    ("API", "7", "anomalies в /trace; доказательства не тронуты", api7_anomalies_in_trace_response),
    ("PG", "1", "committed история PG == памяти (store-независимость)", pg1_committed_history_same_states_as_memory),
    ("PG", "2", "/trace на PG-бэкенде == Memory (приёмка §8)", pg2_trace_on_postgres_backend_matches_memory),
    ("PG", "3", "на живом store session_tail не срабатывает ложно", pg3_session_tail_never_on_live_store),
]


def main() -> int:
    print("=== Оракулы сертификации AUDIT-5B: СВОИ данные сертификатора ===")
    # Module-level API-группы (Memory) -- до живого PG.
    for group, code, title, func in ORACLE_REGISTRY:
        if group == "PG":
            continue
        _check(group, code, title, func)

    # PG-группа: живой pgserver (pg_dir в репо; каталог артефактов сессии).
    import pgserver

    pg_dir = os.path.join(REPO, ".c5bcert-pg")
    os.makedirs(pg_dir, exist_ok=True)
    server = pgserver.get_server(pg_dir, cleanup_mode="delete")
    os.environ["C5B_CERT_PG_URI"] = server.get_uri()
    print(f"Живой PG оракулов: {os.environ['C5B_CERT_PG_URI']}")
    for group, code, title, func in ORACLE_REGISTRY:
        if group == "PG":
            _check(group, code, title, func)

    failed = [r for r in RESULTS if r[2].startswith("FAIL")]
    passed = len(RESULTS) - len(failed)
    print("\n=== ИТОГ ===")
    for name, title, verdict in RESULTS:
        if verdict.startswith("FAIL"):
            print(f"  {name:8s} {verdict} :: {title}")
    print(f"=== {passed}/{len(RESULTS)} PASS, {len(failed)} FAIL ===")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
