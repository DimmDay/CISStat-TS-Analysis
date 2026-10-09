#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PROGR-AUDIT-S-CERT (2026-10-10) — независимые оракулы аудита задачи
AUDIT-S (plan_progress_audit.md §5) на СВОИХ данных.

Аудитор: отдельная сессия; объект — коммит 4cd68be поверх deaed93.
Оракулы ДИЗЪЮНКТНЫ сюиту разработчика tests/api/test_progress_audit_s.py:
свои датасеты/ids/ts/payload-маркеры/типы-представители; углы проверки
выбраны другие (маркер первого источника при merge, canonical-порядок
ключей материала id, частичная sequence-пимеса, bool-подмена int,
typed-unknown VALUE проходит, API-зеркало дедуплицируется и т.д.).

СВОИ данные:
  * датасет wind_hourly.csv — timestamp,windspeed; 96 часовых точек
    c 2026-03-01T00:00 (сид 20261010, синус+шум, генерируется
    детерминированно в этом скрипте);
  * run_id: RUN-CERTS-W01..W04; session-ключи certs-wind-*;
  * event_id: "c-wind-*"; actor "operator" (не user/system разработчика);
  * ts: 2026-03-15T08:30:00+00:00 / нечитаемый "2026-03-15 08:30 wind";
  * типы-представители уровней: model_card_generated (server_result),
    outliers_profile_status (client_observation), tuning_skipped
    (user_decision), checkpoint_saved (operational) — НЕ пара
    разработчика (upload_completed/profile_viewed).

Режимы:
  --cert  все оракулы обязаны быть PASS (запуск на 4cd68be); exit 0.
  --red   сверка с PRE-REGISTERED таблицей EXPECTED_RED (запуск на
          deaed93 ДО AUDIT-S): KILLER обязан FAIL, GUARD обязан PASS;
          отсутствие новых API (ImportError) честно отмечается как
          ABSENT-FAIL у всех unit-групп; exit 0 при полном совпадении.

Pre-registered EXPECTED_RED (зафиксировано ДО отката):
  KILLER (FAIL на deaed93): все unit-группы I/A/M/E/T/V (новых функций
  нет — ImportError) + S2/S3 (файловых пинов нет в родительских
  редакциях) + API P2 (зеркало дублируется — merge нет), P3 (артефакт
  без event_id/нестабилен), P4 (адаптер теряет идентичность), P5
  (envelope не доходит до /trace: TypeError конструктора/фильтрация).
  GUARD (PASS на обеих базах): P1 (явная идентичность слоя 1 стабильна
  и до AUDIT-S — F11 касался ТОЛЬКО адаптера артефактов), P6 (мусор в
  слое 1 не роняет /trace — деградация и раньше), S1 (git-факт: diff
  commits не трогает инструмент аудита — от чекаута не зависит).
"""
from __future__ import annotations

import io
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())

import requests  # noqa: E402  (только для исключений; TestClient ниже)
from fastapi.testclient import TestClient  # noqa: E402

MODE = "cert"
if "--red" in sys.argv:
    MODE = "red"

RESULTS: list[tuple[str, str, str]] = []  # (id, класс, PASS/FAIL/ABSENT)


def oracle(oid: str, cls: str = "KILLER"):
    def deco(fn):
        def wrapper():
            try:
                fn()
                RESULTS.append((oid, cls, "PASS"))
            except Exception as exc:  # noqa: BLE001
                RESULTS.append((oid, cls, f"FAIL: {type(exc).__name__}: {exc}"[:200]))
        wrapper.__name__ = oid
        ORACLES.append(wrapper)
        return wrapper
    return deco


ORACLES: list = []

# ── Свои данные ────────────────────────────────────────────────────────

MY_TS = "2026-03-15T08:30:00+00:00"
MY_TS2 = "2026-03-15T09:10:00+00:00"
MY_TS3 = "2026-03-15T07:45:00+00:00"
MY_BAD_TS = "2026-03-15 08:30 wind"
MY_BAD_TS2 = "wind-ts-broken-2"
MY_RUN = "RUN-CERTS-W02"
MY_ACTOR = "operator"
MY_EID = "c-wind-canonical-0001"
MY_OP = "op-certs-w-9"


def _wind_csv() -> str:
    """Детерминированный ряд аудита: 96 часовых точек, синус+шум."""
    import random

    rng = random.Random(20261010)
    rows = ["timestamp,windspeed"]
    base = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    for i in range(96):
        ts = base.timestamp() + i * 3600
        stamp = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        value = 8 + 3 * math.sin(2 * math.pi * (i % 24) / 24) + rng.uniform(-0.4, 0.4)
        rows.append(f"{stamp},{value:.2f}")
    return "\n".join(rows) + "\n"


def _new_client():
    os.environ.pop("DATABASE_URL", None)
    os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
    from apps.api.main import app
    from apps.api.session_store import reset_session_store_for_testing

    reset_session_store_for_testing()
    return TestClient(app)


def _upload_wind(client) -> str:
    csv = _wind_csv()
    resp = client.post(
        "/v1/internal/upload",
        files={"file": ("wind_hourly.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    assert resp.status_code == 200, f"upload: {resp.status_code} {resp.text[:200]}"
    return resp.json().get("session_id") or client.cookies.get("cisstat_session_id")


def _canonical_raw(event_id: str = MY_EID, **over) -> dict:
    raw = {
        "event_id": event_id,
        "run_id": MY_RUN,
        "ts": MY_TS,
        "stage": "forecasting",
        "node_id": None,
        "event_type": "forecast_exported",
        "payload": {"source": "wind_station", "fmt": "csv"},
        "actor": MY_ACTOR,
    }
    raw.update(over)
    return raw


def _legacy_raw(**over) -> dict:
    raw = {
        "event_type": "forecast_exported",
        "timestamp": MY_TS,
        "payload": {"source": "wind_station", "fmt": "csv"},
    }
    raw.update(over)
    return raw


def _seed_artifact(session, entries: list[dict], forecast_id: str = "fc-wind-1") -> None:
    forecasts = session.modeling_artifacts.setdefault("forecasts", {})
    forecasts[forecast_id] = {"trace_events": entries}


# ══════════════════ P-группа: живой API (импорты обеих баз) ════════════

@oracle("P1", "GUARD")
def _p1():
    """Загрузка своего CSV → /trace: upload_completed с ЯВНОЙ
    идентичностью, стабильной между чтениями; v1-форма (без envelope)."""
    client = _new_client()
    _upload_wind(client)
    first = client.get("/v1/progress/trace").json()
    again = client.get("/v1/progress/trace").json()
    ev1 = [e for e in first["events"] if e["event_type"] == "upload_completed"]
    ev2 = [e for e in again["events"] if e["event_type"] == "upload_completed"]
    assert len(ev1) == 1 and len(ev2) == 1, "upload_completed не единственный"
    assert ev1[0]["event_id"] and ev1[0]["event_id"] == ev2[0]["event_id"], \
        "идентичность слоя 1 нестабильна"
    envelope_keys = {
        "schema_version", "evidence_level", "sequence", "operation_id",
        "causation_id", "context_id", "result_ref", "method", "time_quality",
    }
    assert not (envelope_keys & set(ev1[0].keys())), \
        "v1-событие несёт envelope — аддитивность нарушена"


@oracle("P2", "KILLER")
def _p2():
    """Зеркало своего прогнозного события (один event_id в слое 1 и
    артефакте) попадает в /trace ОДИН раз (merge_canonical_events)."""
    client = _new_client()
    mirror_id = "c-wind-mirror-777"
    mirrored = {
        **_canonical_raw(mirror_id),
        "node_id": "forecast_exported",
    }
    from apps.api.session_store import get_session_store

    store = get_session_store()
    session = store.get_or_create("certs-wind-mirror")
    session.append_trace_event(
        __import__("apps.api.trace_events", fromlist=["TraceEvent"]).TraceEvent(
            event_type="forecast_exported",
            payload={"source": "wind_station", "fmt": "csv"},
            event_id=mirror_id,
            run_id=MY_RUN,
            ts=MY_TS,
            stage="forecasting",
            node_id=None,
            actor=MY_ACTOR,
        )
    )
    _seed_artifact(session, [dict(mirrored)])
    store.save(session)
    client.cookies.set("cisstat_session_id", "certs-wind-mirror")
    events = client.get("/v1/progress/trace").json()["events"]
    ids = [e["event_id"] for e in events]
    assert ids.count(mirror_id) == 1, f"зеркало не дедуплицировано: {ids.count(mirror_id)}x"


@oracle("P3", "KILLER")
def _p3():
    """Legacy-событие артефакта (3 поля, мои данные) в /trace несёт
    СТАБИЛЬНЫЙ event_id (повторное чтение — тот же), узел из типа,
    run_id не выдумывается."""
    client = _new_client()
    from apps.api.session_store import get_session_store

    store = get_session_store()
    session = store.get_or_create("certs-wind-legacy")
    _seed_artifact(session, [dict(_legacy_raw())], forecast_id="fc-wind-2")
    store.save(session)
    client.cookies.set("cisstat_session_id", "certs-wind-legacy")
    first = client.get("/v1/progress/trace").json()
    again = client.get("/v1/progress/trace").json()
    f1 = [e for e in first["events"] if e["event_type"] == "forecast_exported"]
    f2 = [e for e in again["events"] if e["event_type"] == "forecast_exported"]
    assert len(f1) == 1 and len(f2) == 1, "артефактное событие потеряно/удвоено"
    assert f1[0].get("event_id"), "event_id отсутствует (F11 не исправлен)"
    assert f1[0]["event_id"] == f2[0]["event_id"], "id нестабилен между чтениями"
    assert len(f1[0]["event_id"]) >= 32
    assert f1[0]["node_id"] == "forecast_exported", "узел не из типа"
    assert not f1[0].get("run_id"), "run_id выдуман legacy-артефакту"


@oracle("P4", "KILLER")
def _p4():
    """Канонический stored-артефакт СВОЯ идентичность сохраняется
    адаптером: мои event_id/run_id/actor появляются в /trace как есть."""
    client = _new_client()
    from apps.api.session_store import get_session_store

    store = get_session_store()
    session = store.get_or_create("certs-wind-canonic")
    _seed_artifact(
        session,
        [_canonical_raw("c-wind-fc-0042", ts=MY_TS2)],
        forecast_id="fc-wind-3",
    )
    store.save(session)
    client.cookies.set("cisstat_session_id", "certs-wind-canonic")
    events = client.get("/v1/progress/trace").json()["events"]
    hit = [e for e in events if e["event_id"] == "c-wind-fc-0042"]
    assert len(hit) == 1, "событие с моим id не найдено/удвоено"
    assert hit[0]["run_id"] == MY_RUN, "run_id потерян"
    assert hit[0]["actor"] == MY_ACTOR, "actor потерян"


@oracle("P5", "KILLER")
def _p5():
    """Envelope v2 СВОЕГО события слоя 1 доходит до HTTP-JSON /trace
    (pydantic-фильтрация его не съедает) — мои operation_id/level."""
    client = _new_client()
    from apps.api.session_store import get_session_store
    from apps.api.trace_events import TraceEvent

    store = get_session_store()
    session = store.get_or_create("certs-wind-envelope")
    session.append_trace_event(
        TraceEvent(
            event_type="outliers_profile_status",
            payload={"status": "done", "source": "wind_station"},
            ts=MY_TS,
            stage="preprocessing",
            node_id="outliers",
            actor=MY_ACTOR,
            schema_version=2,
            evidence_level="client_observation",
            operation_id=MY_OP,
        )
    )
    store.save(session)
    client.cookies.set("cisstat_session_id", "certs-wind-envelope")
    events = client.get("/v1/progress/trace").json()["events"]
    hit = [e for e in events if e["event_id"] and e.get("operation_id") == MY_OP]
    assert len(hit) == 1, "envelope не дошёл до /trace (фильтрация съела)"
    assert hit[0]["schema_version"] == 2
    assert hit[0]["evidence_level"] == "client_observation"


@oracle("P6", "GUARD")
def _p6():
    """Мусорный envelope в слое 1 не роняет /trace (деградация, не 500);
    мусор не проходит дальше, валидные канонические поля живы."""
    client = _new_client()
    from apps.api.session_store import get_session_store

    store = get_session_store()
    session = store.get_or_create("certs-wind-garbage")
    raw = {
        **_canonical_raw("c-wind-garbage-1", ts=MY_TS3),
        "schema_version": "wind",
        "sequence": {"x": 1},
        "time_quality": 1.5,
    }
    session.pipeline_trace.append(json.loads(json.dumps(raw)))
    store.save(session)
    client.cookies.set("cisstat_session_id", "certs-wind-garbage")
    resp = client.get("/v1/progress/trace")
    assert resp.status_code == 200, f"/trace упал на мусоре: {resp.status_code}"
    hit = [e for e in resp.json()["events"] if e["event_id"] == "c-wind-garbage-1"]
    assert len(hit) == 1, "событие с мусорным envelope потеряно"
    assert "schema_version" not in hit[0] and "time_quality" not in hit[0], \
        "мусор прошёл границу чтения"


# ══════════════════ unit-группы (новые API AUDIT-S) ═══════════════════
try:
    from apps.api.trace_events import (
        ENVELOPE_FIELDS,
        ENVELOPE_REQUIREMENTS,
        EVIDENCE_LEVEL_BY_EVENT_TYPE,
        EVIDENCE_LEVELS,
        RUN_LEVEL_EVENT_TYPES,
        STAGE_EVENT_TYPES,
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

    HAVE_NEW_API = True
except ImportError as _exc:
    HAVE_NEW_API = False
    _IMPORT_ERROR = str(_exc)


def _require_new_api():
    if not HAVE_NEW_API:
        raise ImportError(f"новые API AUDIT-S отсутствуют: {_IMPORT_ERROR}")


# ── I-группа: стабильная идентичность (I1, F11/P17) ───────────────────

@oracle("I1")
def _i1():
    """derive_stable_event_id на СВОИХ данных: детерминизм,
    чувствительность к содержимому (payload/ts/stage/node/run),
    канонический порядок ключей payload не влияет."""
    _require_new_api()
    base = dict(
        run_id=MY_RUN, ts=MY_TS, stage="forecasting", node_id=None,
        event_type="forecast_exported", payload={"source": "wind_station", "fmt": "csv"},
    )
    first = derive_stable_event_id(**base)
    second = derive_stable_event_id(**base)
    assert first == second and len(first) >= 32, "недетерминирован"
    reordered = derive_stable_event_id(**{**base, "payload": {"fmt": "csv", "source": "wind_station"}})
    assert reordered == first, "порядок ключей payload влияет на id"
    for field, value in (
        ("payload", {"source": "wind_station", "fmt": "json"}),
        ("ts", MY_TS2),
        ("stage", "validation"),
        ("node_id", "forecast_exported"),
        ("run_id", "RUN-CERTS-W03"),
        ("event_type", "forecast_compared"),
    ):
        other = derive_stable_event_id(**{**base, field: value})
        assert other != first, f"id не чувствителен к {field}"


@oracle("I2")
def _i2():
    """normalize legacy СВОЕЙ записи: повторное чтение — тот же id;
    явный id проходит как есть."""
    _require_new_api()
    a = normalize_trace_event_dict(_legacy_raw())
    b = normalize_trace_event_dict(_legacy_raw())
    assert a["event_id"] == b["event_id"] and len(a["event_id"]) >= 32
    explicit = normalize_trace_event_dict(_canonical_raw())
    assert explicit["event_id"] == MY_EID, "явный id подменён"


@oracle("I3")
def _i3():
    """Правило normalize == derive_stable_event_id (одно закреплённое
    правило идентичности) на моей legacy-записи."""
    _require_new_api()
    raw = _legacy_raw()
    out = normalize_trace_event_dict(raw)
    assert out["event_id"] == derive_stable_event_id(
        run_id="",
        ts=MY_TS,
        stage="forecasting",
        node_id=None,
        event_type="forecast_exported",
        payload={"source": "wind_station", "fmt": "csv"},
    )


@oracle("I4")
def _i4():
    """Два моих legacy-события с ОДИНАКОВЫМ ts/типом, но РАЗНЫМИ
    payload — РАЗНЫЕ стабильные id (идентичность чувствительна к
    содержимому; merge их не склеит)."""
    _require_new_api()
    a = normalize_trace_event_dict(_legacy_raw(payload={"source": "wind_station", "fmt": "csv"}))
    b = normalize_trace_event_dict(_legacy_raw(payload={"source": "wind_station", "fmt": "json"}))
    assert a["event_id"] != b["event_id"], "разные факты получили один id"


# ── A-группа: адаптер артефактов ───────────────────────────────────────

@oracle("A1")
def _a1():
    """canonicalize_stored_event сохраняет МОЮ идентичность
    (event_id/run_id/actor), узел из типа, мой envelope проходит."""
    _require_new_api()
    raw = _canonical_raw(MY_EID, operation_id=MY_OP)
    out = canonicalize_stored_event(raw)
    assert out["event_id"] == MY_EID
    assert out["run_id"] == MY_RUN and out["actor"] == MY_ACTOR
    assert out["stage"] == "forecasting" and out["node_id"] == "forecast_exported"
    assert out.get("operation_id") == MY_OP, "мой envelope потерян адаптером"


@oracle("A2")
def _a2():
    """Мой legacy-артефакт: повторная канонизация — тот же стабильный id;
    несловарь и пустой тип — None (fail-safe) на моих значениях."""
    _require_new_api()
    first = canonicalize_stored_event(_legacy_raw())
    second = canonicalize_stored_event(_legacy_raw())
    assert first["event_id"] == second["event_id"]
    assert canonicalize_stored_event(None) is None
    assert canonicalize_stored_event(42) is None
    assert canonicalize_stored_event({"event_type": ""}) is None


# ── M-группа: merge/канонический порядок (мои корпусы) ────────────────

@oracle("M1")
def _m1():
    """Merge дедуплицирует по ОДНОМУ event_id и ВЫЖИВАЕТ копия ПЕРВОГО
    источника (мой payload-маркер origin=layer1 vs origin=artifact)."""
    _require_new_api()
    layer1 = [_canonical_raw(MY_EID, payload={"origin": "layer1"})]
    artifact = [_canonical_raw(MY_EID, payload={"origin": "artifact"})]
    merged = merge_canonical_events(layer1, artifact)
    assert len(merged) == 1, f"дубликат одного id не удалён: {len(merged)}"
    assert merged[0]["payload"]["origin"] == "layer1", "второй источник пережил первый"


@oracle("M2")
def _m2():
    """Два НЕЗАВИСИМЫХ результата с одинаковым payload, мои разные id —
    оба сохранены (dedupe строго по идентичности)."""
    _require_new_api()
    a = _canonical_raw("c-wind-indep-a", ts=MY_TS)
    b = _canonical_raw("c-wind-indep-b", ts=MY_TS)
    merged = merge_canonical_events([a], [b])
    assert {e["event_id"] for e in merged} == {"c-wind-indep-a", "c-wind-indep-b"}


@oracle("M3")
def _m3():
    """Мои byte-идентичные legacy: нормализованные — ОДИН факт (один
    стабильный id → dedupe); другой payload — второй факт."""
    _require_new_api()
    a = normalize_trace_event_dict(_legacy_raw())
    b = normalize_trace_event_dict(_legacy_raw())
    different = normalize_trace_event_dict(_legacy_raw(payload={"source": "wind_station", "fmt": "json"}))
    merged = merge_canonical_events([a], [b, different])
    assert len(merged) == 2, f"ожидалось 2 факта, получено {len(merged)}"


@oracle("M4")
def _m4():
    """Мой корпус в перемешанном порядке → хронология (старые раньше)."""
    _require_new_api()
    corpus = [
        _canonical_raw("c-wind-o-3", ts=MY_TS2),
        _canonical_raw("c-wind-o-1", ts=MY_TS3),
        _canonical_raw("c-wind-o-2", ts=MY_TS),
    ]
    ordered = canonical_event_order(corpus)
    assert [e["event_id"] for e in ordered] == [
        "c-wind-o-1", "c-wind-o-2", "c-wind-o-3",
    ]


@oracle("M5")
def _m5():
    """Мои нечитаемые/пустые ts — в КОНЕЦ, взаимный store-порядок
    сохранён (stable), читаемые — впереди по хронологии."""
    _require_new_api()
    corpus = [
        _canonical_raw("c-wind-bad-1", ts=MY_BAD_TS),
        _canonical_raw("c-wind-ok-1", ts=MY_TS),
        _canonical_raw("c-wind-bad-2", ts=MY_BAD_TS2),
        _canonical_raw("c-wind-empty", ts=""),
    ]
    ordered = canonical_event_order(corpus)
    tail = [e["event_id"] for e in ordered[-3:]]
    assert tail == ["c-wind-bad-1", "c-wind-bad-2", "c-wind-empty"], tail
    assert ordered[0]["event_id"] == "c-wind-ok-1"


@oracle("M6")
def _m6():
    """Полная sequence-пимеса МОИХ чисел [5,1,3] → порядок [1,3,5]."""
    _require_new_api()
    corpus = [
        _canonical_raw("c-wind-s5", sequence=5),
        _canonical_raw("c-wind-s1", sequence=1),
        _canonical_raw("c-wind-s3", sequence=3),
    ]
    ordered = canonical_event_order(corpus)
    assert [e["sequence"] for e in ordered] == [1, 3, 5]


@oracle("M7")
def _m7():
    """ЧАСТИЧНАЯ sequence мой корпус НЕ переупорядочивает (fallback
    хронологии ts; mixing запрещён контрактом §3.3)."""
    _require_new_api()
    corpus = [
        _canonical_raw("c-wind-ps-1", ts=MY_TS2, sequence=1),
        _canonical_raw("c-wind-ps-2", ts=MY_TS3),  # без sequence, ts раньше
    ]
    ordered = canonical_event_order(corpus)
    assert [e["event_id"] for e in ordered] == ["c-wind-ps-2", "c-wind-ps-1"], \
        "частичная sequence переупорядочила корпус"


@oracle("M8")
def _m8():
    """Несловарный мусор (мои None/42/"x") пропускается merge без
    падения; словарные события сливаются."""
    _require_new_api()
    merged = merge_canonical_events(
        [None, 42, "wind", _canonical_raw(MY_EID)],
        [_canonical_raw(MY_EID, payload={"origin": "artifact"})],
    )
    assert len(merged) == 1, f"мусор/дедуп не обработаны: {len(merged)}"


# ── E-группа: уровни доказательности (контракт §12.2) ────────────────

@oracle("E1")
def _e1():
    """Реестр ПОЛОН и БЕЗ лишних: ключи EVIDENCE_LEVEL_BY_EVENT_TYPE ==
    объединение типов стадий и run-level (мой независимый пересчёт)."""
    _require_new_api()
    union = set()
    for types in STAGE_EVENT_TYPES.values():
        union |= set(types)
    union |= set(RUN_LEVEL_EVENT_TYPES)
    registry = set(EVIDENCE_LEVEL_BY_EVENT_TYPE.keys())
    assert registry == union, (
        f"пропущены: {sorted(union - registry)}; лишние: {sorted(registry - union)}"
    )
    assert set(EVIDENCE_LEVELS) == {
        "server_result", "client_observation", "user_decision", "operational",
    }
    assert set(ENVELOPE_REQUIREMENTS.keys()) == set(EVIDENCE_LEVELS)


@oracle("E2")
def _e2():
    """Мои типы-представители всех ЧЕТЫРЁХ уровней (не пара
    разработчика): model_card_generated/outliers_profile_status/
    tuning_skipped/checkpoint_saved."""
    _require_new_api()
    assert resolve_evidence_level("model_card_generated", {}) == "server_result"
    assert resolve_evidence_level("outliers_profile_status", {}) == "client_observation"
    assert resolve_evidence_level("tuning_skipped", {}) == "user_decision"
    assert resolve_evidence_level("checkpoint_saved", {}) == "operational"


@oracle("E3")
def _e3():
    """Payload-aware override target_column_changed на моих payload:
    auto → server_result; user → user_decision; отсутствие →
    user_decision; payload=None → user_decision; дефолтный actor
    вне вывода (мой actor='operator' не влияет)."""
    _require_new_api()
    assert resolve_evidence_level("target_column_changed", {"source": "auto"}) == "server_result"
    assert resolve_evidence_level("target_column_changed", {"source": "user"}) == "user_decision"
    assert resolve_evidence_level("target_column_changed", {"source": "wind"}) == "user_decision"
    assert resolve_evidence_level("target_column_changed", {}) == "user_decision"
    assert resolve_evidence_level("target_column_changed", None) == "user_decision"


@oracle("E4")
def _e4():
    """Неизвестный (выдуманный мной) тип — честный None."""
    _require_new_api()
    assert resolve_evidence_level("wind_recalibrated", {}) is None


@oracle("E5")
def _e5():
    """Таблица обязательности == МОЯ независимая транскрипция контракта
    §12.3 (v0.2-AUDIT-S)."""
    _require_new_api()
    expected = {
        "server_result": ("schema_version", "evidence_level", "operation_id", "result_ref", "method"),
        "client_observation": ("schema_version", "evidence_level", "operation_id"),
        "user_decision": ("schema_version", "evidence_level", "operation_id", "causation_id"),
        "operational": ("schema_version", "evidence_level", "operation_id"),
    }
    assert ENVELOPE_REQUIREMENTS == expected, f"таблица разошлась с контрактом: {ENVELOPE_REQUIREMENTS}"


@oracle("E6")
def _e6():
    """validate_envelope на моих v2-событиях: полный user_decision —
    []; без causation_id — нарушение с именем поля; v1 (без
    schema_version) — ровно одно сообщение «не нарушение»; чужая
    версия/вне реестра — нарушения."""
    _require_new_api()
    full = stamp_envelope(
        make_trace_event("tuning_skipped", stage="modeling"),
        operation_id="op-certs-w-5", causation_id="req-certs-w-5",
    ).to_dict()
    assert validate_envelope(full) == []
    partial = stamp_envelope(
        make_trace_event("tuning_skipped", stage="modeling"),
        operation_id="op-certs-w-5",
    ).to_dict()
    assert any("causation_id" in v for v in validate_envelope(partial))
    v1 = make_trace_event("forecast_exported").to_dict()
    v1_verdicts = validate_envelope(v1)
    assert len(v1_verdicts) == 1 and "не нарушение" in v1_verdicts[0], v1_verdicts
    wrong = dict(full, schema_version=3)
    assert validate_envelope(wrong), "schema_version=3 не замечена"
    alien = dict(full, evidence_level="wind_level")
    assert validate_envelope(alien), "вне-реестровый level не замечен"


# ── T-группа: честное время (F16/P23) на моих ts ──────────────────────

@oracle("T1")
def _t1():
    """Мой нечитаемый ts НЕ подменяется: quality=degraded, raw_ts мой,
    observed_at — читаемый ISO."""
    _require_new_api()
    out = normalize_trace_event_dict(_legacy_raw(timestamp=MY_BAD_TS))
    assert out["ts"] == MY_BAD_TS, "ts подменён"
    tq = out["time_quality"]
    assert tq["quality"] == "degraded" and tq["raw_ts"] == MY_BAD_TS
    datetime.fromisoformat(tq["observed_at"])


@oracle("T2")
def _t2():
    """Мой валидный ts и ПУСТОЙ ts — без time_quality (v1-чтение без
    шума; отсутствие — не «испорчено»)."""
    _require_new_api()
    assert "time_quality" not in normalize_trace_event_dict(_legacy_raw())
    empty = normalize_trace_event_dict({"event_type": "forecast_exported"})
    assert empty["ts"] == "" and "time_quality" not in empty


@oracle("T3")
def _t3():
    """Идемпотентность на моей маркировке: повторная нормализация не
    перемаркирует (observed_at не обновляется)."""
    _require_new_api()
    marked = normalize_trace_event_dict(_legacy_raw(timestamp=MY_BAD_TS))
    reread = normalize_trace_event_dict(marked)
    assert reread["time_quality"] == marked["time_quality"]
    assert reread["event_id"] == marked["event_id"]


@oracle("T4")
def _t4():
    """mark_honest_time: substituted=False (Memory) → degraded;
    substituted=True (Postgres-граница) → substituted; сам ts объекта
    не переписан; мой валидный факт не тронут."""
    _require_new_api()
    ev = TraceEvent(event_type="forecast_exported", ts=MY_BAD_TS)
    mem = mark_honest_time(ev, substituted=False)
    assert mem.ts == MY_BAD_TS and mem.time_quality["quality"] == "degraded"
    assert mem.time_quality["raw_ts"] == MY_BAD_TS
    pg = mark_honest_time(ev, substituted=True)
    assert pg.ts == MY_BAD_TS and pg.time_quality["quality"] == "substituted"
    datetime.fromisoformat(pg.time_quality["observed_at"])
    ok = make_trace_event("forecast_exported")
    assert mark_honest_time(ok, substituted=True).time_quality is None


@oracle("T5")
def _t5():
    """Memory-store на МОЁМ run: append сохраняет raw ts и несёт
    degraded-маркировку; мой валидный event проходит без поля."""
    _require_new_api()
    from apps.api.research_runs import MemoryResearchRunStore

    store = MemoryResearchRunStore()
    store.append_event("RUN-CERTS-W01", TraceEvent(event_type="forecast_exported", ts=MY_BAD_TS))
    store.append_event("RUN-CERTS-W01", make_trace_event("forecast_exported"))
    listed = store.list_events("RUN-CERTS-W01")
    assert listed[0].ts == MY_BAD_TS
    assert listed[0].time_quality["quality"] == "degraded"
    assert listed[0].time_quality["raw_ts"] == MY_BAD_TS
    assert listed[1].time_quality is None


@oracle("T6")
def _t6():
    """Контракт строки БД сохранён: _ts_to_db на моём мусоре и моём
    валидном ISO возвращает datetime (честность — в маркировке)."""
    _require_new_api()
    from apps.api.research_runs import _ts_to_db

    assert isinstance(_ts_to_db(MY_BAD_TS), datetime)
    assert isinstance(_ts_to_db(MY_TS), datetime)


# ── V-группа: envelope v2 — форма/штамп/щит (мои значения) ────────────

@oracle("V1")
def _v1():
    """Моё v1-событие: to_dict — ровно 9 ключей (8 + legacy-алиас),
    ни одного envelope-ключа."""
    _require_new_api()
    raw = make_trace_event("forecast_exported", source="wind_station").to_dict()
    assert set(raw.keys()) == {
        "event_id", "run_id", "ts", "stage", "node_id",
        "event_type", "payload", "actor", "timestamp",
    }


@oracle("V2")
def _v2():
    """stamp_envelope: авто schema_version=2 и авто-уровень МОЕГО типа
    (outliers_profile_status → client_observation); явные значения
    приоритетны; незнакомое моё поле — ValueError."""
    _require_new_api()
    ev = make_trace_event("outliers_profile_status", stage="preprocessing", status="done")
    stamped = stamp_envelope(ev, operation_id=MY_OP)
    assert stamped.schema_version == 2
    assert stamped.evidence_level == "client_observation"
    assert stamped.operation_id == MY_OP
    assert stamped.sequence is None and stamped.context_id is None
    explicit = stamp_envelope(
        make_trace_event("forecast_exported"),
        schema_version=2, evidence_level="operational", sequence=11,
        causation_id="req-certs-w", context_id="ctx-certs-w",
        result_ref={"artifact": "wind.csv"}, method={"algorithm": "export"},
    )
    assert explicit.evidence_level == "operational" and explicit.sequence == 11
    assert explicit.context_id == "ctx-certs-w"
    try:
        stamp_envelope(make_trace_event("forecast_exported"), wind_field="x")
    except ValueError:
        pass
    else:
        raise AssertionError("незнакомое поле принято (fail-closed снят)")


@oracle("V3")
def _v3():
    """Мой v2 to_dict аддитивен (незаполненных ключей нет) и обратим:
    from_dict(to_dict) == dataclass."""
    _require_new_api()
    stamped = stamp_envelope(
        make_trace_event("model_card_generated", stage="modeling"),
        operation_id=MY_OP, result_ref={"artifact": "wind-card"},
    )
    raw = stamped.to_dict()
    assert set(raw.keys()) == {
        "event_id", "run_id", "ts", "stage", "node_id",
        "event_type", "payload", "actor", "timestamp",
        "schema_version", "evidence_level", "operation_id", "result_ref",
    }
    restored = TraceEvent.from_dict(raw)
    assert restored == stamped


@oracle("V4")
def _v4():
    """Щит границы чтения на МОЁМ мусоре: чужие типы отброшены,
    валидно типизированное НЕИЗВЕСТНОЕ ЗНАЧЕНИЕ проходит (журнал, не
    реестр): evidence_level='wind_level', schema_version=9."""
    _require_new_api()
    raw = {
        **_canonical_raw(),
        "schema_version": "wind",
        "evidence_level": 99,
        "sequence": {"x": 1},
        "operation_id": ["op"],
        "causation_id": True,
        "result_ref": "no-ref",
        "method": 7,
        "time_quality": 1.5,
    }
    out = normalize_trace_event_dict(raw)
    for key in ("schema_version", "evidence_level", "sequence", "operation_id",
                "causation_id", "result_ref", "method", "time_quality"):
        assert key not in out, f"мусорное {key} прошло"
    typed_unknown = {
        **_canonical_raw("c-wind-typed-unknown"),
        "evidence_level": "wind_level",
        "schema_version": 9,
    }
    passed = normalize_trace_event_dict(typed_unknown)
    assert passed.get("evidence_level") == "wind_level", "typed-unknown VALUE отфильтрован"
    assert passed.get("schema_version") == 9


@oracle("V5")
def _v5():
    """bool-подмена int отсечена на границе: schema_version=True,
    sequence=False — мусор (bool — подкласс int)."""
    _require_new_api()
    raw = {**_canonical_raw("c-wind-bool"), "schema_version": True, "sequence": False}
    out = normalize_trace_event_dict(raw)
    assert "schema_version" not in out and "sequence" not in out
    assert _has_no_bool_sequence(out)


def _has_no_bool_sequence(data: dict) -> bool:
    return not isinstance(data.get("sequence"), bool)


# ── S-группа: versioned-обновление оракула + нетронутость инструмента ─

@oracle("S1", "GUARD")
def _s1():
    """Git-факт: коммит AUDIT-S (4cd68be) НЕ трогает инструмент аудита
    и его протоколы (план §2: исходный корпус наблюдений сохранён)."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "deaed93..4cd68be"],
        capture_output=True, text=True, check=True,
    ).stdout
    touched = set(out.strip().splitlines())
    forbidden = {
        "scripts/progress_audit_readonly.py",
        "scripts/progress_audit_readonly_results.json",
        "scripts/progress_audit_checks.txt",
    }
    assert not (touched & forbidden), f"инструмент аудита тронут: {touched & forbidden}"


@oracle("S2")
def _s2():
    """Versioned-обновление оракула PROGR-10: новое имя пинит
    исправленный контракт (стабильная идентичность), старое имя
    (пин дефекта F11) удалено. Файловая проверка — новые API не нужны."""
    src = open("tests/api/test_progress_panel.py", encoding="utf-8").read()
    assert "test_artifact_events_carry_stable_identity_not_anchors" in src
    assert "def test_artifact_events_are_not_checkpoint_anchors" not in src


@oracle("S3")
def _s3():
    """TS-кейс «forecasting с id — не якорь» присутствует в
    progress.test.ts (второе плечо versioned-обновления §12.6).
    Файловая проверка — новые API не нужны."""
    src = open("packages/ui/lib/progress.test.ts", encoding="utf-8").read()
    assert "AUDIT-S" in src and "forecasting" in src
    assert 'event_id: "stable-derived"' in src


@oracle("V6")
def _v6():
    """ForecastTraceEventSchema принимает МОЙ envelope аддитивно и
    отдаёт его в JSON (риск карточки §5 «pydantic-фильтрация скрывает
    новые поля» — forecasting-UI-носитель); v1 — поля None.
    (V6 добавлен при сертификации: мутант CM-15 выявил гэп исходного
    набора — предсказание KILLED-BOTH не сбылось, оракул усилен по
    правилу открытой эволюции, прецедент PROGR-24-C-CERT R4.)"""
    _require_new_api()
    from apps.api.schemas import ForecastTraceEventSchema

    stamped = stamp_envelope(
        make_trace_event("forecast_exported"),
        operation_id=MY_OP,
        evidence_level="server_result",
        result_ref={"artifact": "wind.csv", "hash": "sha256:wind"},
    )
    v2 = ForecastTraceEventSchema(**stamped.to_dict())
    assert v2.schema_version == 2 and v2.evidence_level == "server_result"
    assert v2.operation_id == MY_OP
    assert v2.result_ref == {"artifact": "wind.csv", "hash": "sha256:wind"}
    dumped = v2.model_dump()
    assert dumped["operation_id"] == MY_OP, "JSON-выгрузка потеряла envelope"
    v1 = ForecastTraceEventSchema(**_legacy_raw())
    assert v1.schema_version is None and v1.evidence_level is None
    assert v1.timestamp == MY_TS and v1.event_type == "forecast_exported"


# ════════════════════════ запуск ══════════════════════════════════════

def main() -> int:
    if MODE == "cert":
        for fn in ORACLES:
            fn()
    else:  # red: unit-группы при отсутствии API — ABSENT (честный FAIL)
        for fn in ORACLES:
            fn()

    killers = [r for r in RESULTS if r[1] == "KILLER"]
    guards = [r for r in RESULTS if r[1] == "GUARD"]
    print("=" * 72)
    print(f"PROGR-AUDIT-S-CERT: оракулы на СВОИХ данных — режим {MODE}")
    print("=" * 72)
    for oid, cls, status in RESULTS:
        marker = "✅" if status == "PASS" else "❌"
        print(f"  {marker} {oid:4} [{cls:6}] {status}")
    passed = sum(1 for _, _, s in RESULTS if s == "PASS")
    print("-" * 72)
    print(f"ИТОГО: {passed}/{len(RESULTS)} PASS "
          f"(KILLER: {len(killers)}, GUARD: {len(guards)})")

    if MODE == "cert":
        ok = passed == len(RESULTS)
        print("ВЕРДИКТ ОРАКУЛОВ:", "ALL GREEN" if ok else "ЕСТЬ ПРОВАЛЫ")
        return 0 if ok else 1

    # red-режим: сверка с pre-registered таблицей
    mismatches = []
    for oid, cls, status in RESULTS:
        expected_fail = cls == "KILLER"
        actual_fail = status != "PASS"
        if expected_fail != actual_fail:
            mismatches.append((oid, cls, status))
    print("-" * 72)
    if mismatches:
        print("EXPECTED_RED РАСХОЖДЕНИЯ:")
        for oid, cls, status in mismatches:
            print(f"  {oid} [{cls}] — {status}")
        return 1
    print("EXPECTED_RED: полное совпадение "
          f"({len(killers)} KILLER упали, {len(guards)} GUARD зелёные)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
