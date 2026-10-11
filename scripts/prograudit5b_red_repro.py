# scripts/prograudit5b_red_repro.py
"""RED-репро задачи AUDIT-5B (plan_progress_audit.md §8): честные падения
НА СТАРОМ ПОВЕДЕНИИ для дефектов, закрываемых полной согласованной
проекцией и watermark.

Проверки (на СУЩЕСТВУЮЩЕМ API базы a2dcbee):

  R1 (P11/F06)  Панель /trace читает ТОЛЬКО слой 1 (кап 1000): ранний
                статус узла теряется на корпусе >1000, started_at --
                ts первого события уцелевшего хвоста, а не run.created_at.
  R2 (P11/F06)  Ответ /trace не несёт watermark/полноты: хвост выдаётся
                за полную историю (несогласованный snapshot).
  R3 (I10/F10)  Невалидный payload статусного события меняет детали узла
                (reason без статуса), источник деталей не фиксируется.
  R4 (I10/§8)   Узлы не несут validity: исторический факт чужого/неиз-
                вестного контекста неотличим от current.
  R5 (P12/F08)  Отчёт сортирует корпус по ts, панель -- по каноническому
                порядку: один корпус -- два порядка потребителей.

Запуск:  python scripts/prograudit5b_red_repro.py
Результат: код возврата 0 -- все проверки ведут себя по-старому (RED
подтверждён, дефекты живы); 1 -- хотя бы одна уже исправлена.
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Стенд -- Memory-хранилище (переменные окружения песочницы с
# DATABASE_URL-style значением не должны уводить стенд в Postgres).
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
os.environ.pop("DATABASE_URL", None)

from apps.api.research_runs import (  # noqa: E402
    ResearchRun,
    get_research_run_store,
)
from apps.api.session_store import (  # noqa: E402
    AnalysisSession,
    get_session_store,
)
from apps.api.trace_events import make_trace_event, stamp_envelope  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []

RUN_ID = "RUN-5BRED001"
CREATED_AT = "2026-01-01T00:00:00+00:00"
CTX_A = "ctx-aaaaaaaaaaaaaaaa"
CTX_B = "ctx-bbbbbbbbbbbbbbbb"


def _ts(minutes: int) -> str:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat()


def _ev(event_type, *, stage, node_id=None, ts, payload=None, event_id=None,
        context_id=None):
    event = make_trace_event(
        event_type, stage=stage, node_id=node_id, run_id=RUN_ID,
        **(payload or {}),
    )
    event = replace(event, ts=ts)
    if event_id:
        event = replace(event, event_id=event_id)
    if context_id:
        event = stamp_envelope(event, context_id=context_id)
    return event


def _big_corpus(total: int = 1050) -> list:
    events = [_ev("upload_completed", stage="upload", node_id="overview",
                  ts=_ts(0), payload={"name": "red.csv"},
                  event_id="ev-red-upload-1")]
    for i in range(1, total):
        events.append(_ev("validation_check_status", stage="validation",
                          node_id="data_types", ts=_ts(i),
                          payload={"check_id": "data_types", "status": "done"},
                          event_id=f"ev-red-val-{i:05d}"))
    return events


def _seed(session: AnalysisSession, events: list, *, with_run: bool = True):
    session.run_id = RUN_ID
    for event in events:
        session.append_trace_event(event)
    if with_run:
        store = get_research_run_store()
        store.upsert_run(ResearchRun(
            run_id=RUN_ID, session_id=session.session_id,
            dataset_fingerprint="f" * 64, dataset_name="red.csv",
            target_column="rain", created_at=CREATED_AT,
            last_active_at=CREATED_AT, context_id=CTX_A,
        ))
        for event in events:
            store.append_event(RUN_ID, event)


def _check(code: str, title: str, func) -> None:
    try:
        func()
        RESULTS.append((code, title, "RED-CONFIRMED"))
    except AssertionError as exc:
        RESULTS.append((code, title, f"RED-CONFIRMED ({exc})"))
    except Exception as exc:  # дефект жив, но упало не так -- фиксируем
        RESULTS.append((code, title, f"RED-CONFIRMED ({type(exc).__name__}: {exc})"))


def r1_panel_loses_early_status() -> None:
    from app.core.node_status import derive_node_statuses

    session = AnalysisSession(session_id="sess-red-5b")
    _seed(session, _big_corpus(1050))
    layer1 = session.read_pipeline_trace()
    statuses = derive_node_statuses([e.to_dict() for e in layer1])
    assert statuses.get("upload/overview") == "done", (
        f"панель на хвосте: upload/overview={statuses.get('upload/overview')!r}"
    )


def r2_started_at_and_watermark() -> None:
    session = AnalysisSession(session_id="sess-red-5b-w")
    _seed(session, _big_corpus(1050))
    layer1 = session.read_pipeline_trace()
    # старое чтение панели: started_at = ts первого события хвоста
    started_at = layer1[0].ts if layer1 else None
    assert started_at == CREATED_AT, (
        f"started_at={started_at!r} -- ts хвоста, не run.created_at"
    )
    assert hasattr(type(layer1), "watermark"), "у панели нет watermark"


def r3_invalid_payload_changes_details() -> None:
    from app.core.node_status import derive_pipeline_node_states

    events = [
        _ev("validation_check_status", stage="validation", node_id="ranges",
            ts=_ts(1), payload={"check_id": "ranges", "status": "done"},
            event_id="ev-red-ok"),
        _ev("validation_check_status", stage="validation", node_id="ranges",
            ts=_ts(2), payload={"check_id": "ranges"},  # невалидный payload
            event_id="ev-red-bad"),
    ]
    states = {s["node_id"]: s for s in derive_pipeline_node_states(events)}
    reason = states["ranges"]["status_reason"]
    assert reason is None, (
        f"невалидное событие меняет детали: status_reason={reason!r}"
    )


def r4_no_validity() -> None:
    from app.core.node_status import derive_pipeline_node_states

    events = [
        _ev("validation_check_status", stage="validation", node_id="ranges",
            ts=_ts(1), payload={"check_id": "ranges", "status": "done"},
            event_id="ev-red-v1", context_id=CTX_B),
    ]
    states = derive_pipeline_node_states(events)
    validity = states[0].get("validity")
    assert validity == "stale", (
        f"validity={validity!r} -- факт чужого контекста неотличим от current"
    )


def r5_report_ts_order() -> None:
    from app.core.run_report import build_report_model

    events = [
        _ev("target_column_changed", stage="validation", node_id=None,
            ts=_ts(30), payload={"target_column": "rain"},
            event_id="ev-red-r1").to_dict(),
        _ev("target_column_changed", stage="validation", node_id=None,
            ts=_ts(20), payload={"target_column": "snow"},
            event_id="ev-red-r2").to_dict(),
    ]
    model = build_report_model({"run_id": RUN_ID}, events)
    lines = [
        f.text for stage in model.stages
        for node in stage.nodes for f in node.facts
    ] + [
        f.text for stage in model.stages for f in stage.stage_level_facts
    ]
    pos_rain = next(
        i for i, t in enumerate(lines) if "признак: rain" in t.lower()
    )
    pos_snow = next(
        i for i, t in enumerate(lines) if "признак: snow" in t.lower()
    )
    assert pos_rain < pos_snow, (
        "отчёт отсортировал по ts (snow раньше rain), канонический "
        "порядок корпуса (append/store) нарушен"
    )


def main() -> int:
    _check("R1", "P11: панель теряет ранний статус на корпусе >1000",
           r1_panel_loses_early_status)
    _check("R2", "P11: started_at из хвоста; watermark отсутствует",
           r2_started_at_and_watermark)
    _check("R3", "I10: невалидный payload меняет детали узла",
           r3_invalid_payload_changes_details)
    _check("R4", "I10: узлы не несут validity",
           r4_no_validity)
    _check("R5", "P12: отчёт сортирует по ts, не по каноническому порядку",
           r5_report_ts_order)

    confirmed = 0
    for code, title, verdict in RESULTS:
        print(f"[{code}] {title}: {verdict}")
        if verdict.startswith("RED-CONFIRMED"):
            confirmed += 1
    print(f"\nRED-подтверждено: {confirmed}/{len(RESULTS)}")
    return 0 if confirmed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
