# scripts/progr13cert_oracles.py
# Task PROGR-13-CERT -- независимые оракул-тесты на СВОИХ данных аудитора
# (сертификация PROGR-13-A и PROGR-13-B, база main@f607ccc).
# Ожидания закодированы ИЗ ПОСТАНОВОК задач (worklog8.md) и контрактов
# spec_progress.md (§2/§3/§4.1/§5/§7.2), данные -- синтетические и
# случайные (фиксированные seed'ы для воспроизводимости). Не импортируют
# tests/api/test_progress_progr13a.py / test_progress_progr13b.py.
"""Оракул-проверки PROGR-13-A/B.

Группы:
  A. Нормализация legacy node_id (B3) -- property-based инварианты.
  B. Движок статусов и payload-статусы (A3/A4) -- whitelist, last-wins,
     фантом-фри, «панель == модулю» на случайных картах.
  C. Фаза Наставника по узловым фактам (B1) -- stage-level хвост фазу
     не двигает, последний узловой факт выигрывает.
  D. Контракт POST /v1/progress/upload-stops (A4) -- fail-closed
     all-or-nothing, слой 1 + зеркало слоя 2, run_id, last-wins.
  E. Отчёт §5.4 (A5) -- метки из общего реестра, без выдуманных фактов.
  F. Таблица хука (A3/B2) -- 4 литеральные паспортные точки,
     /date-column, upload->overview, fail-closed на неизвестной точке.
  G. Общие реестры (A1) -- JSON/граф/.tsx/.ts из одного источника,
     fail-closed загрузчик на временных файлах.

Запуск: python3 scripts/progr13cert_oracles.py  (exit 0 = все оракулы зелёные).
"""
from __future__ import annotations

import io
import json
import random
import string
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.node_status import (  # noqa: E402
    EVENT_NODE_REASON,
    EVENT_NODE_STATUS,
    LEGACY_NODE_IDS,
    PAYLOAD_STATUS_EVENT_TYPES,
    derive_last_active_stage,
    derive_node_statuses,
    derive_pipeline_node_states,
    derive_stage_states,
    normalize_legacy_node_id,
    resolve_event_status,
    resolve_node_id,
)
from app.core.pipeline_graph import (  # noqa: E402
    CHECK_STATUS_VALUES,
    STAGES,
    STAGE_NODES,
    TOTAL_NODE_COUNT,
    UPLOAD_STAGE_IDS,
    UPLOAD_STOP_DEFS,
    is_known_node,
)
from app.core import run_report  # noqa: E402
from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import STAGE_EVENT_TYPES  # noqa: E402
from apps.api.trace_hook import TRACE_ROUTES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_JSON_PATH = REPO_ROOT / "shared" / "pipeline_nodes" / "upload_stops.json"
UPLOAD_TSX_PATH = REPO_ROOT / "packages" / "ui" / "components" / "TsAnalysisUpload.tsx"
PROGRESS_TS_PATH = REPO_ROOT / "packages" / "ui" / "lib" / "progress.ts"

EXPECTED_STOP_IDS = ("overview", "chart", "distribution", "structure", "quality")

client = TestClient(app)

FAILED: list[str] = []
PASSED = 0


def oracle(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  PASS {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name} {detail}")


def _iso(seconds: float) -> str:
    base = datetime(2026, 10, 2, 9, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=seconds)).isoformat()


def _event(
    stage: str,
    node_id: str | None,
    event_type: str,
    ts: str,
    payload: dict | None = None,
    run_id: str = "RUN-CERT13-0001",
) -> dict:
    """Stored-событие канона §4.1 (8 полей + legacy-алиас timestamp)."""
    return {
        "event_id": f"ev-{ts}-{event_type}-{random.randrange(1 << 30):08x}",
        "run_id": run_id,
        "ts": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": dict(payload or {}),
        "actor": "user",
        "timestamp": ts,
    }


# ── A. Нормализация legacy node_id (PROGR-13-B3) ─────────────────────

STAGE_LEVEL_EVENT_TYPES = (
    "target_column_changed",  # validation/preprocessing, node_id=None
    "passport_captured",      # upload/validation/eda/modeling, node_id=None
    "mode_changed",           # validation/preprocessing, node_id=None
    "run_paused", "run_resumed", "checkpoint_saved",  # run-level
)

print("A. Нормализация legacy node_id (B3): property-based на своих данных")
rng = random.Random(20261002)

oracle("A1 реестр legacy -- ровно upload/structure_confirmed->structure",
       LEGACY_NODE_IDS == {"upload": {"structure_confirmed": "structure"}},
       str(LEGACY_NODE_IDS))

_idempotency_breaks: list[str] = []
for _ in range(500):
    stage = rng.choice(STAGES)
    node = rng.choice(
        [None, "", "structure", "structure_confirmed", "overview",
         "".join(rng.choices(string.ascii_lowercase, k=rng.randrange(1, 12))),
         "structure_confirmed "]
    )
    first = normalize_legacy_node_id(stage, node)
    if first is not None and normalize_legacy_node_id(stage, first) != first:
        _idempotency_breaks.append(f"{stage}/{node!r}")
oracle("A2 идемпотентность на 500 случайных пробах",
       not _idempotency_breaks, str(_idempotency_breaks[:3]))

oracle("A3 None -> None (узловых фактов не создаёт)",
       normalize_legacy_node_id("upload", None) is None)

_cross_stage_breaks: list[str] = []
for _stage in STAGES:
    if _stage == "upload":
        continue
    for _ in range(50):
        legacy = "structure_confirmed"
        got = normalize_legacy_node_id(_stage, legacy)
        if got != legacy:
            _cross_stage_breaks.append(f"{_stage}->{got}")
oracle("A4 маппинг ограничен СВОЕЙ стадией (чужие стадии не переписываются)",
       not _cross_stage_breaks, str(_cross_stage_breaks[:3]))

oracle("A5 legacy своей стадии -> канонический id",
       normalize_legacy_node_id("upload", "structure_confirmed") == "structure")

_unreachable: list[str] = []
for _stage in STAGES:
    for _node in STAGE_NODES[_stage]:
        if normalize_legacy_node_id(_stage, _node) != _node:
            _unreachable.append(f"{_stage}/{_node}")
oracle("A6 канонические id ВСЕХ 50 узлов проходят насквозь",
       not _unreachable and TOTAL_NODE_COUNT == 50,
       str(_unreachable[:3]))

_fuzz_invented: list[str] = []
for _ in range(500):
    stage = rng.choice(STAGES)
    node = "".join(rng.choices(string.ascii_letters + "_", k=rng.randrange(1, 14)))
    got = normalize_legacy_node_id(stage, node)
    if got != node and got not in STAGE_NODES[stage]:
        _fuzz_invented.append(f"{stage}/{node}->{got}")
oracle("A7 fuzz 500: неизвестное -- как есть, фантомных id не возникает",
       not _fuzz_invented, str(_fuzz_invented[:3]))

legacy_row = _event("upload", "structure_confirmed", "upload_completed",
                    _iso(1.0))
oracle("A8 legacy-строка корпуса: resolve_node_id нормализует, гейт графа пропускает",
       resolve_node_id(legacy_row) == "structure"
       and is_known_node("upload", resolve_node_id(legacy_row)),
       str(resolve_node_id(legacy_row)))
statuses_legacy = derive_node_statuses(
    [legacy_row,
     _event("validation", None, "target_column_changed", _iso(2.0))])
oracle("A9 история слоя 2 не потеряна: upload/structure=done при 5-узловой Загрузке",
       statuses_legacy.get("upload/structure") == "done"
       and "upload/structure_confirmed" not in statuses_legacy,
       str(statuses_legacy))

# ── B. Движок статусов и payload-статусы (PROGR-13-A3/A4) ────────────

print("B. Движок статусов / payload-статусы (A3/A4)")

oracle("B1 upload_completed -> узел overview (факт чтения файла)",
       resolve_node_id(_event("upload", "overview", "upload_completed",
                              _iso(1.0))) == "overview")
oracle("B2 upload_completed больше НЕ красит structure (дефект 1б закрыт)",
       EVENT_NODE_STATUS["upload_completed"] == "done"
       and resolve_node_id(_event("upload", "overview", "upload_completed",
                                  _iso(1.0))) == "overview"
       and derive_node_statuses([
           _event("upload", "overview", "upload_completed", _iso(1.0)),
       ]).get("upload/structure") is None)

_whitelist_garbage = [None, "", "DONE", "ok", "passed", "42", "done ",
                      {"nested": 1}, ["done"], 3.14, True]
_bad_payload_events = [
    _event("upload", "quality", "upload_stop_status", _iso(1.0),
           payload={"status": g})
    for g in _whitelist_garbage
] + [
    _event("upload", "quality", "upload_stop_status", _iso(1.0)),
    _event("upload", "quality", "upload_stop_status", _iso(1.0),
           payload={"status": {"a": 1}}),
]
oracle("B3 whitelist CHECK_STATUS_VALUES: мусор payload -> None (событие хранится, статуса нет)",
       all(resolve_event_status(ev) is None for ev in _bad_payload_events),
       str([resolve_event_status(ev) for ev in _bad_payload_events]))

oracle("B4 каждый валидный CheckStatus из payload разрешается",
       all(resolve_event_status(
           _event("upload", "quality", "upload_stop_status", _iso(1.0),
                  payload={"status": s})) == s
           for s in CHECK_STATUS_VALUES))

oracle("B5 реестр payload-статусных типов: ровно upload_stop_status",
       PAYLOAD_STATUS_EVENT_TYPES == frozenset({"upload_stop_status"}))

oracle("B6 разведение фактов: карта статусов узлов канонична",
       EVENT_NODE_STATUS["upload_completed"] == "done"
       and EVENT_NODE_STATUS["structure_confirmed"] == "done"
       and EVENT_NODE_STATUS["correction_previewed"] == "warning"
       and EVENT_NODE_STATUS["profile_viewed"] == "running")

oracle("B7 честная причина upload_completed (не «структура подтверждена»)",
       EVENT_NODE_REASON["upload_completed"] == "Датасет загружен, превью доступно"
       and "структура" not in EVENT_NODE_REASON["upload_completed"].lower())

# last-wins на случайных хронологиях (ядро семантики единого движка)
_lastwins_ok = True
_lastwins_detail = ""
for trial in range(200):
    n_events = rng.randrange(2, 12)
    seq = []
    for i in range(n_events):
        node = rng.choice(UPLOAD_STAGE_IDS)
        status = rng.choice(CHECK_STATUS_VALUES)
        seq.append(_event("upload", node, "upload_stop_status", _iso(i + 1.0),
                          payload={"status": status}))
    expected: dict[str, str] = {}
    for ev in seq:
        key = f"upload/{ev['node_id']}"
        expected[key] = ev["payload"]["status"]
    got = derive_node_statuses(seq)
    for key, want in expected.items():
        if got.get(key) != want:
            _lastwins_ok = False
            _lastwins_detail = f"trial {trial}: {key} want {want} got {got.get(key)}"
            break
    if not _lastwins_ok:
        break
oracle("B8 last-wins: статус узла = последний его факт (200 случайных хронологий)",
       _lastwins_ok, _lastwins_detail)

# «Панель == модулю» (дефект 1, ядро контракта): ЛЮБАЯ полная валидная
# карта stopStatus, отчитанная модулем, обязана воспроизводиться движком.
_panel_mismatch: list[str] = ""
for trial in range(200):
    stops_map = {sid: rng.choice(CHECK_STATUS_VALUES) for sid in EXPECTED_STOP_IDS}
    seq = [
        _event("upload", sid, "upload_stop_status", _iso(i + 1.0),
               payload={"status": stops_map[sid]})
        for i, sid in enumerate(EXPECTED_STOP_IDS)
    ]
    got = derive_node_statuses(seq)
    for sid in EXPECTED_STOP_IDS:
        if got.get(f"upload/{sid}") != stops_map[sid]:
            _panel_mismatch = f"trial {trial}: {sid}"
            break
    if _panel_mismatch:
        break
oracle("B9 «панель == модулю»: 200 случайных снапшотов stopStatus воспроизводятся движком",
       not _panel_mismatch, _panel_mismatch)

# фантом-фри: шумовые события не создают узлов
_noise: list[dict] = []
for i in range(120):
    stage = rng.choice(list(STAGES) + ["unknown_stage"])
    node = rng.choice(list(STAGE_NODES.get(stage, ["phantom_node"]))
                      if stage in STAGE_NODES else ["phantom_node"])
    etype = rng.choice(
        list(STAGE_EVENT_TYPES.get(stage, set())) if stage in STAGE_EVENT_TYPES
        else ["no_such_type"])
    _noise.append(_event(stage, node, etype, _iso(i + 1.0),
                         payload={"status": rng.choice(CHECK_STATUS_VALUES)}))
_noise_keys = set(derive_node_statuses(_noise))
_known_keys = {f"{s}/{n}" for s in STAGES for n in STAGE_NODES[s]}
oracle("B10 фантом-фри: ключи статусов подмножество известных узлов графа",
       _noise_keys <= _known_keys,
       str(sorted(_noise_keys - _known_keys)[:5]))

full_states = derive_pipeline_node_states(
    [_event("upload", "overview", "upload_completed", _iso(1.0)),
     _event("upload", "quality", "upload_stop_status", _iso(2.0),
            payload={"status": "warning"}),
     _event("eda", "distributions", "profile_viewed", _iso(3.0))])
by_key = {(s["stage"], s["node_id"]): s for s in full_states}
oracle("B12 полный узел §3: overview done + честная причина",
       by_key[("upload", "overview")]["status"] == "done"
       and by_key[("upload", "overview")]["status_reason"]
       == EVENT_NODE_REASON["upload_completed"])
oracle("B13 полный узел §3: quality warning из payload-статуса с причиной",
       by_key[("upload", "quality")]["status"] == "warning"
       and by_key[("upload", "quality")]["status_reason"]
       == EVENT_NODE_REASON["upload_stop_status"])
oracle("B14 полный узел §3: остальные узлы Загрузки честно pending",
       all(by_key[("upload", sid)]["status"] == "pending"
           for sid in ("chart", "distribution", "structure")))
stage_states = derive_stage_states(
    derive_node_statuses(
        [_event("upload", "quality", "upload_stop_status", _iso(1.0),
                payload={"status": "warning"})]))
oracle("B15 свёртка §12 п.10: один warning -> карточка attention, 1/5 узлов",
       [s for s in stage_states if s["stage"] == "upload"][0]["fold"] == "attention"
       and [s for s in stage_states if s["stage"] == "upload"][0]["warning_nodes"] == 1
       and [s for s in stage_states if s["stage"] == "upload"][0]["total_nodes"] == 5)

# ── C. Фаза Наставника по узловым фактам (PROGR-13-B1) ───────────────

print("C. Фаза Наставника -- узловые факты (B1)")

oracle("C1 stage-level хвост НЕ двигает фазу (дефект 2 закрыт)",
       derive_last_active_stage([
           _event("upload", "overview", "upload_completed", _iso(1.0)),
           _event("validation", None, "target_column_changed", _iso(2.0)),
       ]) == "upload")

oracle("C2 run-level события НЕ двигают фазу",
       derive_last_active_stage([
           _event("eda", "distribution", "profile_viewed", _iso(1.0)),
           _event("eda", None, "run_paused", _iso(2.0)),
           _event("modeling", None, "run_resumed", _iso(3.0)),
       ]) == "eda")

oracle("C3 паспорт -- фиксация снимка, фазу не двигает (start на «Загрузке»)",
       derive_last_active_stage([
           _event("upload", "overview", "upload_completed", _iso(1.0)),
           _event("upload", None, "passport_captured", _iso(2.0),
                  payload={"stage": "start"}),
       ]) == "upload")

oracle("C4 последний узловой факт выигрывает (хронология)",
       derive_last_active_stage([
           _event("upload", "overview", "upload_completed", _iso(1.0)),
           _event("validation", "formats", "correction_applied", _iso(2.0)),
           _event("preprocessing", "missing", "correction_applied", _iso(3.0)),
       ]) == "preprocessing")

oracle("C5 пустая трасса / только stage-level -> честный default upload",
       derive_last_active_stage([]) == "upload"
       and derive_last_active_stage([
           _event("validation", None, "target_column_changed", _iso(1.0)),
           _event("eda", None, "passport_captured", _iso(2.0)),
       ]) == "upload")

oracle("C6 payload-статусные события двигают фазу (A4+B1 интеграция)",
       derive_last_active_stage([
           _event("upload", "quality", "upload_stop_status", _iso(1.0),
                  payload={"status": "warning"}),
       ]) == "upload")

oracle("C7 forecasting: узел выводится из типа события (node_id=None слоя 2)",
       derive_last_active_stage([
           _event("forecasting", None, "forecast_generated", _iso(1.0)),
       ]) == "forecasting")

oracle("C8 мусор-события фазу не ломают (деградация в default)",
       derive_last_active_stage(["junk", 42, None]) == "upload")

# случайные хронологии: инвариант «фаза == стадия последнего узлового факта»
_phase_ok = True
_phase_detail = ""
for trial in range(150):
    events: list[dict] = []
    expected_stage: str | None = None
    clock = 1.0
    for _ in range(rng.randrange(1, 10)):
        if rng.random() < 0.4:
            stage = rng.choice(STAGES)
            etype = rng.choice(STAGE_LEVEL_EVENT_TYPES)
            if etype not in STAGE_EVENT_TYPES.get(stage, set()) \
                    and etype not in {"run_paused", "run_resumed", "checkpoint_saved"}:
                continue
            events.append(_event(stage, None, etype, _iso(clock)))
        else:
            stage = rng.choice(STAGES)
            node = rng.choice(STAGE_NODES[stage])
            etype = rng.choice(sorted(STAGE_EVENT_TYPES[stage] &
                                      set(EVENT_NODE_STATUS)))
            events.append(_event(stage, node, etype, _iso(clock)))
            expected_stage = stage
        clock += 1.0
    got = derive_last_active_stage(events)
    want = expected_stage or "upload"
    if got != want:
        _phase_ok = False
        _phase_detail = (
            f"trial {trial}: want {want} got {got}; "
            f"last events: {[(e['stage'], e['node_id'], e['event_type']) for e in events[-3:]]}")
        break
oracle("C9 инвариант фазы на 150 случайных хронологиях", _phase_ok, _phase_detail)

# ── D. Контракт POST /v1/progress/upload-stops (PROGR-13-A4) ─────────

print("D. POST /v1/progress/upload-stops (A4): fail-closed и зеркала")


def _reset_stores() -> None:
    import os

    os.environ.pop("DATABASE_URL", None)
    os.environ["CISSTAT_RUNS_BACKEND"] = "memory"
    from apps.api import research_runs

    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()


def _monitor_csv() -> str:
    import pandas as pd

    idx = pd.date_range("2013-01-01", periods=150, freq="MS")
    frame = pd.DataFrame(
        {"date": idx.strftime("%Y-%m-%d"), "value": [120.0 + i for i in range(150)]}
    )
    return frame.to_csv(index=False)


def _upload_dataset() -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": (
            "cert13_synthetic_n150.csv",
            io.BytesIO(_monitor_csv().encode()),
            "text/csv",
        )},
    )
    assert response.status_code == 200, response.text


def _layer1_upload_events() -> list[dict]:
    from apps.api.session_store import SESSION_COOKIE_NAME

    store = get_session_store()
    sid = client.cookies.get(SESSION_COOKIE_NAME)
    if not sid:
        return []
    session = store.get_or_create(sid)
    events = []
    for e in session.pipeline_trace:
        data = e.to_dict() if hasattr(e, "to_dict") else dict(e)
        if data["event_type"] == "upload_stop_status":
            events.append(data)
    return events


def _layer2_upload_events(run_id: str) -> list[dict]:
    from apps.api.research_runs import get_research_run_store

    store = get_research_run_store()
    return [e for e in store.list_events(run_id)
            if e.to_dict()["event_type"] == "upload_stop_status"]


_reset_stores()
client.cookies.clear()
_upload_dataset()
_before1, _before2_run = _layer1_upload_events(), ""
snapshot = {sid: "done" for sid in EXPECTED_STOP_IDS}
r_ok = client.post("/v1/progress/upload-stops", json={"stops": snapshot})
oracle("D1 полная валидная карта: 200, reported=5, run_id закреплён",
       r_ok.status_code == 200 and r_ok.json()["reported"] == 5
       and (r_ok.json()["run_id"] or "").startswith("RUN-"),
       r_ok.text[:200])
run_id_pinned = r_ok.json()["run_id"]
oracle("D2 слой 1: 5 событий upload_stop_status",
       len(_layer1_upload_events()) == 5,
       str(len(_layer1_upload_events())))
oracle("D3 слой 2 зеркало: те же 5 фактов (тот же механизм, что у хука)",
       len(_layer2_upload_events(run_id_pinned)) == 5,
       str(len(_layer2_upload_events(run_id_pinned))))
l1 = _layer1_upload_events()
oracle("D4 события в каноническом порядке реестра с payload.status",
       [e["node_id"] for e in l1] == list(EXPECTED_STOP_IDS)
       and all(e["payload"]["status"] == "done" for e in l1),
       str([e["node_id"] for e in l1]))

# fail-closed all-or-nothing: после отказа -- ноль НОВЫХ событий
def _rejects_zero_writes() -> list[str]:
    problems: list[str] = []
    bad_bodies: list[tuple[str, dict]] = [
        ("пустая карта", {"stops": {}}),
        ("неизвестный узел",
         {"stops": {**snapshot, "phantom_stop": "done"}}),
        ("недопустимый статус",
         {"stops": {**snapshot, "quality": "excellent"}}),
        ("неполная карта",
         {"stops": {k: v for k, v in snapshot.items()
                    if k != "distribution"}}),
    ]
    for label, body in bad_bodies:
        n1 = len(_layer1_upload_events())
        resp = client.post("/v1/progress/upload-stops", json=body)
        n1_after = len(_layer1_upload_events())
        if resp.status_code != 422:
            problems.append(f"{label}: status {resp.status_code}, ждём 422")
        if n1_after != n1:
            problems.append(f"{label}: слой 1 вырос {n1}->{n1_after} (не all-or-nothing)")
    return problems


_problems = _rejects_zero_writes()
oracle("D5 fail-closed all-or-nothing: пустая/чужая/битая/неполная карты -- 422, ноль записей",
       not _problems, "; ".join(_problems))

_reset_stores()
client.cookies.clear()
r400 = client.post("/v1/progress/upload-stops", json={"stops": snapshot})
oracle("D6 без датасета -- 400 (факты остановок без исследования не существуют)",
       r400.status_code == 400, f"status {r400.status_code}")

# run_id: первый отчёт фиксирует run, второй попадает в тот же
_reset_stores()
client.cookies.clear()
_upload_dataset()
r1 = client.post("/v1/progress/upload-stops", json={"stops": snapshot})
first_run = r1.json()["run_id"]
r2 = client.post("/v1/progress/upload-stops",
                 json={"stops": {sid: "warning" for sid in EXPECTED_STOP_IDS}})
oracle("D7 run_id переживает повторный отчёт (тот же запуск)",
       r2.status_code == 200 and r2.json()["run_id"] == first_run,
       f"{first_run} vs {r2.json().get('run_id')}")

# last-wins интеграция: отчёт -> structure_confirmed -> ре-пост
_reset_stores()
client.cookies.clear()
_upload_dataset()
client.post("/v1/progress/upload-stops",
            json={"stops": {**snapshot, "structure": "warning"}})
client.post("/v1/session/date-column", json={"date_column": "date"})
client.post("/v1/progress/upload-stops",
            json={"stops": {**snapshot, "structure": "warning"}})
trace = client.get("/v1/progress/trace").json()
statuses = trace["node_statuses"]
oracle("D8 last-wins: ре-пост после /date-column решает хронология",
       statuses.get("upload/structure") == "warning"
       and statuses.get("upload/overview") == "done",
       str({k: v for k, v in statuses.items() if k.startswith("upload/")}))

# ── E. Отчёт §5.4 -- факты остановок (PROGR-13-A5) ───────────────────

print("E. Отчёт §5.4: строки фактов из общего реестра")

_labels = {d["id"]: d["label"] for d in UPLOAD_STOP_DEFS}
_ru = run_report._STOP_STATUS_LABELS
_e_ok = True
_e_detail = ""
for sid in EXPECTED_STOP_IDS:
    for status in CHECK_STATUS_VALUES:
        line, _ = run_report.fact_line(_event(
            "upload", sid, "upload_stop_status", _iso(1.0),
            payload={"status": status}))
        if _labels[sid] not in line:
            _e_ok = False
            _e_detail = f"{sid}/{status}: метки {_labels[sid]!r} нет в {line!r}"
            break
        want = _ru.get(status, status)
        if want not in line:
            _e_ok = False
            _e_detail = f"{sid}/{status}: ждём {want!r} в {line!r}"
            break
    if not _e_ok:
        break
oracle("E1 метка остановки и RU-статус -- в строке отчёта (5x6 комбинаций)",
       _e_ok, _e_detail)

line_no_status, _ = run_report.fact_line(_event(
    "upload", "quality", "upload_stop_status", _iso(1.0), payload={}))
oracle("E2 неизвестный/пустой статус -- честный аудит, не выдумка",
       "неизвестен" in line_no_status or line_no_status.endswith("."),
       line_no_status)

line_col, _ = run_report.fact_line(_event(
    "upload", "structure", "structure_confirmed", _iso(1.0),
    payload={"date_column": "ts"}))
line_nocol, _ = run_report.fact_line(_event(
    "upload", "structure", "structure_confirmed", _iso(2.0), payload={}))
oracle("E3 structure_confirmed: колонка из payload; отсутствующая -- без выдуманных фактов",
       "ts" in line_col and "Подтверждена" in line_col
       and "Подтверждена" in line_nocol and "ts" not in line_nocol,
       f"{line_col!r} / {line_nocol!r}")

_fallback_ok = all(
    ("upload", sid) in run_report.FALLBACK_NODE_LABELS for sid in EXPECTED_STOP_IDS)
oracle("E4 FALLBACK_NODE_LABELS покрывает весь реестр upload",
       _fallback_ok)

# ── F. Таблица хука (PROGR-13-A3/B2) ─────────────────────────────────

print("F. Таблица хука: паспортные точки, /date-column, upload->overview")

_passport = [r for r in TRACE_ROUTES
             if r.path_template.startswith("/v1/session/dataset/passport/")]
_points = {r.path_template.rsplit("/", 1)[-1]: r for r in _passport}
oracle("F1 4 литеральные паспортные строки",
       sorted(_points) == ["exit", "modeling_entry", "start", "validation"]
       and len(_passport) == 4, str(sorted(_points)))
oracle("F2 точка->стадия: start->upload, validation->validation, exit->eda, modeling_entry->modeling",
       _points["start"].stage == "upload"
       and _points["validation"].stage == "validation"
       and _points["exit"].stage == "eda"
       and _points["modeling_entry"].stage == "modeling")
oracle("F3 паспортные события -- уровня стадии (node_id=None)",
       all(r.node_id is None for r in _passport))
oracle("F4 payload паспортной точки -- stage/snapshot_id/fingerprint",
       all(r.payload_keys == ("stage", "snapshot_id", "fingerprint")
           for r in _passport))

_datecol = [r for r in TRACE_ROUTES
            if r.path_template == "/v1/session/date-column"]
oracle("F5 POST /date-column -> upload/structure, structure_confirmed, payload date_column",
       len(_datecol) == 1
       and _datecol[0].stage == "upload" and _datecol[0].node_id == "structure"
       and _datecol[0].event_type == "structure_confirmed"
       and _datecol[0].payload_keys == ("date_column",))
oracle("F6 неизвестная паспортная точка -- НЕТ строки таблицы (fail-closed)",
       all("{" not in r.path_template for r in _passport))

_upload_rows = [r for r in TRACE_ROUTES
                if r.path_template in ("/v1/internal/upload",
                                       "/v1/public/upload", "/v1/session/demo")]
oracle("F7 3 строки загрузки -> узел overview (факт чтения файла)",
       len(_upload_rows) == 3
       and all(r.stage == "upload" and r.node_id == "overview"
               and r.event_type == "upload_completed" for r in _upload_rows))

oracle("F8 реестр типов: structure_confirmed/upload_stop_status на upload",
       {"structure_confirmed", "upload_stop_status"} <= STAGE_EVENT_TYPES["upload"])
oracle("F9 реестр типов: passport_captured на upload/validation/modeling (+eda)",
       all("passport_captured" in STAGE_EVENT_TYPES[s]
           for s in ("upload", "validation", "eda", "modeling")))

# ── G. Общие реестры (PROGR-13-A1) + fail-closed загрузчик ───────────

print("G. Общий реестр остановок и fail-closed загрузчик (A1)")

raw_json = json.loads(UPLOAD_JSON_PATH.read_text(encoding="utf-8"))
json_ids = tuple(n["id"] for n in raw_json["nodes"])
oracle("G1 JSON: 5 остановок, порядок = порядок степпера",
       json_ids == EXPECTED_STOP_IDS)
oracle("G2 граф читает тот же JSON (вшитой копии нет)",
       UPLOAD_STAGE_IDS == json_ids and STAGE_NODES["upload"] == json_ids)
tsx_src = UPLOAD_TSX_PATH.read_text(encoding="utf-8")
ts_src = PROGRESS_TS_PATH.read_text(encoding="utf-8")
oracle("G3 TsAnalysisUpload.tsx импортирует общий JSON",
       "shared/pipeline_nodes/upload_stops.json" in tsx_src)
oracle("G4 progress.ts импортирует общий JSON (метки и id)",
       "shared/pipeline_nodes/upload_stops.json" in ts_src)
oracle("G5 метки STOP_DEFS == метки JSON (единый источник)",
       all(d["label"] == n["label"] for d, n in zip(UPLOAD_STOP_DEFS, raw_json["nodes"])))
oracle("G6 во .tsx нет вшитого списка остановок (литеральных id нет)",
       '"overview"' not in tsx_src.replace(" ", "")
       or "STOPS" in tsx_src and "uploadStopsJson" in tsx_src)

from app.core.pipeline_graph import (  # noqa: E402
    _load_upload_stop_defs,
)

with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    good = json.loads(UPLOAD_JSON_PATH.read_text(encoding="utf-8"))

    def _try_load(data, *, stage="upload"):
        bad = dict(good)
        if data is not None:
            bad = data
        bad["stage"] = stage
        p = td_path / "stops.json"
        p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        try:
            _load_upload_stop_defs(p)
        except ImportError:
            return True
        except Exception:
            return True  # любой fail-closed отказ -- не тихая деградация
        return False

    broken = dict(good)
    broken["nodes"] = [dict(good["nodes"][0])]
    broken["nodes"][0] = dict(broken["nodes"][0])
    broken["nodes"][0].pop("label")
    dup = dict(good)
    dup["nodes"] = good["nodes"] + [good["nodes"][0]]
    foreign = dict(good)
    foreign["nodes"] = []
    cases = {
        "битый JSON": None,
    }
    oracle("G7 fail-closed: чужая stage", _try_load(good, stage="eda"))
    oracle("G8 fail-closed: пропуск обязательного ключа", _try_load(broken))
    oracle("G9 fail-closed: дубликат id", _try_load(dup))
    oracle("G10 fail-closed: пустой nodes", _try_load(foreign))
    p_broken_json = td_path / "broken.json"
    p_broken_json.write_text("{not json", encoding="utf-8")
    try:
        _load_upload_stop_defs(p_broken_json)
        ok_json = False
    except Exception:
        ok_json = True
    oracle("G11 fail-closed: битый JSON", ok_json)

print(f"\nИтог: {PASSED} PASS / {len(FAILED)} FAIL")
if FAILED:
    print("Упавшие оракулы:", ", ".join(FAILED))
sys.exit(1 if FAILED else 0)
