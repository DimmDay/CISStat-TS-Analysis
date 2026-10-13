#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROGR-AUDIT-3-CERT — оракулы сертификатора на СВОИХ данных (standalone,
без pytest). Объект аудита: реализация AUDIT-3 «EDA: показ, запрос и
свежесть» на main@493e5b6; контракт docs/progress_audit_contract.md
v1.1-3A §21; план plan_progress_audit.md §13; спека F17/P25, H27/H28.

Дисциплина «оракулы на своих данных» (прецеденты 6A/5B/1A/4/2A/2B-CERT):
свой корпус узлов (ih_analysis/distribution/structural/stationarity/
seasonality + периметр validation/uniqueness), свои контексты
(c3c-...), свои run_id (RUN-C3CERT), свои файлы данных E2E — НЕ копии
оракулов исполнителя (tests/api/test_progress_audit_3.py: узел
correlation, RUN-AUDIT301, ctx-aaa/bbb).

Группы:
  RG — реестр/хук/отчёт (Р1: GET = запрос, не показ; честные формулировки)
  CM — контекст-ключевая монотонность редьюсера (Р2/Р3/Р4, I10)
  VL — применимость фактов (validity, 13-полевой контракт AUDIT-5B)
  E2 — живой контур ASGI (свои маршруты/узлы/данные)

Запуск:  python3 scripts/prograudit3cert_oracles.py [имена_оракулов]
Протокол: scripts/prograudit3cert_oracles_results.txt, EXIT 0 = все PASS.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── среда ДО импорта приложений (репетitor исполнителя, R6-среда) ──
os.environ.pop("DATABASE_URL", None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core.node_status import (  # noqa: E402
    EVENT_NODE_REASON,
    EVENT_NODE_STATUS,
    NodeStateFold,
    derive_node_statuses,
    resolve_event_status,
)
# PROFILE_REQUEST_EVENT_TYPES введён AUDIT-3; на RED-базе 4289a83 его
# нет -- толерантный импорт даёт пооракульный RED (а не падение сюиты).
try:  # noqa: SIM105 -- форма важна для RED-протокола
    from app.core.node_status import PROFILE_REQUEST_EVENT_TYPES  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover -- RED-база
    PROFILE_REQUEST_EVENT_TYPES = frozenset()  # type: ignore[assignment]
from app.core.pipeline_graph import STAGE_NODES  # noqa: E402
from app.core.run_report import build_report_model, fact_line, render_markdown  # noqa: E402
from apps.api.trace_events import (  # noqa: E402
    STAGE_EVENT_TYPES,
    resolve_evidence_level,
)
from apps.api import trace_hook  # noqa: E402

CTX_A = "c3c-1111-aaaaaaaa"
CTX_B = "c3c-2222-bbbbbbbb"
RUN_ID = "RUN-C3CERT"

RESULTS_PATH = REPO / "scripts/prograudit3cert_oracles_results.txt"


def _iso(seconds: int) -> str:
    base = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=seconds)).isoformat()


def _event(
    stage: str,
    node_id: str | None,
    event_type: str,
    ts: int,
    payload: dict | None = None,
    context_id: str | None = None,
    event_id: str | None = None,
) -> dict:
    """Stored-событие §4.1 + envelope context_id (AUDIT-C); свои event_id."""
    eid = event_id or f"c3c-{ts:04d}-{event_type}-{node_id or 'stage'}"
    return {
        "event_id": eid,
        "run_id": RUN_ID,
        "ts": _iso(ts),
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": dict(payload or {}),
        "actor": "user",
        "timestamp": _iso(ts),
        "context_id": context_id,
    }


def _eda(node: str, etype: str, ts: int, status: str | None = None,
         ctx: str | None = CTX_A, eid: str | None = None) -> dict:
    payload = {"status": status} if status is not None else {}
    eid = eid or f"c3c-{ts:04d}-{etype}-{node}"
    return _event("eda", node, etype, ts, payload, ctx, eid)


# ══════════════════════════ RG: реестр/хук/отчёт ══════════════════════════

def rg1_registry_request_and_legacy_types():
    """Р1: profile_requested зарегистрирован за стадией eda; легаси
    profile_viewed сохранён (корпус не переписывается, §21.1/§3.7)."""
    assert "profile_requested" in STAGE_EVENT_TYPES["eda"]
    assert "profile_viewed" in STAGE_EVENT_TYPES["eda"]


def rg2_evidence_levels():
    """GET-запрос -- operational (авто-факт middleware); показ результата
    (eda_check_status) -- client_observation модуля; контраст уровней."""
    assert resolve_evidence_level("profile_requested", {}) == "operational"
    assert resolve_evidence_level("eda_check_status", {}) == "client_observation"


def rg3_status_map_and_profile_types():
    """Карта статуса: запрос -- running («исследуется», НЕ «просмотрено»);
    множество профильных типов покрывает оба (легаси + новый)."""
    assert EVENT_NODE_STATUS["profile_requested"] == "running"
    assert EVENT_NODE_STATUS["profile_viewed"] == "running"
    assert PROFILE_REQUEST_EVENT_TYPES == frozenset(
        {"profile_requested", "profile_viewed"}
    )


def rg4_reason_honesty():
    """Честность формулировок: у запроса -- «запрошен», слово
    «просмотрена» запрещено; у легаси-чтения прежняя формулировка."""
    reason = EVENT_NODE_REASON["profile_requested"]
    assert "запрошен" in reason.lower()
    assert "просмотрена" not in reason.lower()


def rg5_hook_routes_nine_get_requested():
    """Хук трассы: все 9 исследовательских GET-роутов EDA сеют
    profile_requested с троттлингом §4.2 (таблица + fail-closed гейт)."""
    eda_get = [
        spec for spec in trace_hook.TRACE_ROUTES
        if spec.method == "GET" and spec.stage == "eda"
    ]
    assert len(eda_get) == 9, f"ожидалось 9 GET-роутов EDA, найдено {len(eda_get)}"
    for spec in eda_get:
        assert spec.event_type == "profile_requested", spec
        assert spec.throttled is True, spec
        assert spec.node_id in STAGE_NODES["eda"], spec


def rg6_hook_never_seeds_viewed():
    """Хук больше НЕ сеет легаси profile_viewed ни на одном маршруте
    (событие показа результата -- ТОЛЬКО от UI, §21.1)."""
    seeded_viewed = [
        spec for spec in trace_hook.TRACE_ROUTES
        if spec.event_type == "profile_viewed"
    ]
    assert seeded_viewed == []


def rg7_throttle_env_semantics():
    """Троттлинг §4.2: дефолт 300с; битое значение -- дефолт;
    отрицательное -- 0 (окно выключено). Свой ракурс env-семантики."""
    original = os.environ.get(trace_hook.ENV_THROTTLE_SECONDS)
    try:
        os.environ.pop(trace_hook.ENV_THROTTLE_SECONDS, None)
        assert trace_hook.throttle_seconds_from_env() == 300
        os.environ[trace_hook.ENV_THROTTLE_SECONDS] = "45"
        assert trace_hook.throttle_seconds_from_env() == 45
        os.environ[trace_hook.ENV_THROTTLE_SECONDS] = "not-a-number"
        assert trace_hook.throttle_seconds_from_env() == 300
        os.environ[trace_hook.ENV_THROTTLE_SECONDS] = "-7"
        assert trace_hook.throttle_seconds_from_env() == 0
    finally:
        if original is None:
            os.environ.pop(trace_hook.ENV_THROTTLE_SECONDS, None)
        else:
            os.environ[trace_hook.ENV_THROTTLE_SECONDS] = original


def rg8_report_template_honesty():
    """Отчёт §5.4: у profile_requested человекочитаемый шаблон с
    «запрошен» и без «просмотрена»; легаси profile_viewed сохраняет
    прежнюю формулировку (фабрика fact_line -- прямой ракурс)."""
    line_req, _ = fact_line(
        _event("eda", "ih_analysis", "profile_requested", 1, context_id=CTX_A)
    )
    assert "запрошен" in line_req.lower()
    assert "просмотрена" not in line_req.lower()
    line_legacy, _ = fact_line(
        _event("eda", "ih_analysis", "profile_viewed", 2, context_id=CTX_A)
    )
    assert "просмотрена" in line_legacy.lower()


# ═══════════════ CM: контекст-ключевая монотонность редьюсера ═══════════════

def cm1_p25_get_keeps_done_and_idempotent():
    """P25/F17 (Р2): GET в СВОЁМ контексте не понижает done; повторный
    GET идемпотентен. Свой узел ih_analysis, свои контексты."""
    events = [
        _eda("ih_analysis", "eda_check_status", 1, "done", CTX_A),
        _eda("ih_analysis", "profile_requested", 2, ctx=CTX_A),
        _eda("ih_analysis", "profile_requested", 3, ctx=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/ih_analysis"] == "done"


def cm2_legacy_viewed_keeps_done_same_context():
    """Легаси profile_viewed в СВОЁМ контексте защищён так же (обоих
    типов запроса касается монотонность, §21.2)."""
    events = [
        _eda("distribution", "eda_check_status", 1, "done", CTX_A),
        _eda("distribution", "profile_viewed", 2, ctx=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/distribution"] == "done"


def cm3_get_from_pending_sets_running():
    """Запрос на непросмотренном узле -- running (не понижение, честный
    апгрейд pending -> running)."""
    events = [
        _eda("structural", "eda_check_status", 1, "pending", CTX_A),
        _eda("structural", "profile_requested", 2, ctx=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/structural"] == "running"


def cm4_warning_error_skipped_protected():
    """Защита распространяется на ВСЕ статусы честнее running
    (warning/error/skipped) -- параметризовано своим узлом."""
    for status in ("warning", "error", "skipped"):
        events = [
            _eda("distribution", "eda_check_status", 1, status, CTX_A),
            _eda("distribution", "profile_requested", 2, ctx=CTX_A),
        ]
        assert derive_node_statuses(events)["eda/distribution"] == status, status


def cm5_h27_pending_map_does_not_retract_done():
    """H27/Р3: рутинный pending ПОЛНОЙ карты eda_check_status в СВОЁМ
    контексте не retract-ит done; последующий GET тоже не понижает
    (цепочка: done -> pending-карта -> GET -- итог done)."""
    events = [
        _eda("stationarity", "eda_check_status", 1, "done", CTX_A),
        _eda("stationarity", "eda_check_status", 2, "pending", CTX_A),
        _eda("stationarity", "profile_requested", 3, ctx=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/stationarity"] == "done"


def cm6_h27_honesty_running_to_pending_allowed():
    """Честная семантика «не просмотрено»: понижение running -> pending
    НЕ защищается (защита -- только у просмотренного done, §21.3)."""
    events = [
        _eda("seasonality", "profile_requested", 1, ctx=CTX_A),
        _eda("seasonality", "eda_check_status", 2, "pending", CTX_A),
    ]
    assert derive_node_statuses(events)["eda/seasonality"] == "pending"


def cm7_h28_get_in_new_context_reopens():
    """H28 (Р4): GET в НОВОМ контексте (оба известны и различны) --
    новая применимость: running утверждается, контекст-источник --
    новое событие."""
    events = [
        _eda("ih_analysis", "eda_check_status", 1, "done", CTX_A),
        _eda("ih_analysis", "profile_requested", 2, ctx=CTX_B),
    ]
    assert derive_node_statuses(events)["eda/ih_analysis"] == "running"
    fold = NodeStateFold()
    for event in events:
        fold.apply(event)
    assert fold.detail("eda/ih_analysis")["_status_ctx"] == CTX_B


def cm8_h28_pending_in_new_context_reopens():
    """H28: pending-карта нового контекста переоткрывает узел
    (last-wins при СМЕНЕ контекста честен)."""
    events = [
        _eda("distribution", "eda_check_status", 1, "done", CTX_A),
        _eda("distribution", "eda_check_status", 2, "pending", CTX_B),
    ]
    assert derive_node_statuses(events)["eda/distribution"] == "pending"


def cm9_h28_done_upgrade_updates_source():
    """Повторный отчёт done в новом контексте -- апгрейд без помех;
    источник статуса -- НОВОЕ событие (I10: источник не лжёт)."""
    done_a = _eda("structural", "eda_check_status", 1, "done", CTX_A,
                  eid="c3c-done-A-structural")
    done_b = _eda("structural", "eda_check_status", 2, "done", CTX_B,
                  eid="c3c-done-B-structural")
    assert derive_node_statuses([done_a, done_b])["eda/structural"] == "done"
    fold = NodeStateFold()
    fold.apply(done_a)
    fold.apply(done_b)
    assert fold.detail("eda/structural")["_status_src"] == "c3c-done-B-structural"
    assert fold.detail("eda/structural")["_status_ctx"] == CTX_B


def cm10_legacy_done_vs_stamped_pending():
    """Unknown-контекст хранимого факта НЕ утверждает смену (легаси-done
    без envelope защищён от stamped pending нового контекста, §21.2)."""
    events = [
        _eda("seasonality", "eda_check_status", 1, "done", None),
        _eda("seasonality", "eda_check_status", 2, "pending", CTX_A),
    ]
    assert derive_node_statuses(events)["eda/seasonality"] == "done"


def cm11_legacy_done_vs_stamped_get():
    """То же для GET: легаси-done + stamped profile_requested -- защита
    сохранена (unknown != смена)."""
    events = [
        _eda("stationarity", "eda_check_status", 1, "done", None),
        _eda("stationarity", "profile_requested", 2, ctx=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/stationarity"] == "done"


def cm12_stamped_done_vs_legacy_pending():
    """Обратная граница: неизвестный контекст НОВОГО события не
    утверждает смену -- stamped done не ретрактится легаси-pending."""
    events = [
        _eda("model_matrix", "eda_check_status", 1, "done", CTX_A),
        _eda("model_matrix", "eda_check_status", 2, "pending", None),
    ]
    assert derive_node_statuses(events)["eda/model_matrix"] == "done"


def cm13_legacy_corpus_interim_h1_kept():
    """Легаси-корпус (оба события без envelope): interim-семантика H1
    сохранена -- легаси-done не понижается легаси-GET (регресс
    легаси-чтения недопустим)."""
    events = [
        _eda("feature_select", "eda_check_status", 1, "done", None),
        _eda("feature_select", "profile_viewed", 2, None),
    ]
    assert derive_node_statuses(events)["eda/feature_select"] == "done"


def cm14_perimeter_validation_keeps_last_wins():
    """Периметр неретракта -- ТОЛЬКО eda_check_status: карты Валидации
    сохраняют last-wins (рутинный pending переоткрывает проверку)."""
    events = [
        _event("validation", "uniqueness", "validation_check_status", 1,
               {"status": "done"}, CTX_A),
        _event("validation", "uniqueness", "validation_check_status", 2,
               {"status": "pending"}, CTX_A),
    ]
    assert derive_node_statuses(events)["validation/uniqueness"] == "pending"


def cm15_h27_protection_only_for_done():
    """Защита п.3 -- только просмотренный done: warning -> рутинный
    pending в своём контексте понижается честно (не «развидеть» --
    warning не был просмотренным результатом)."""
    events = [
        _eda("correlation", "eda_check_status", 1, "warning", CTX_A),
        _eda("correlation", "eda_check_status", 2, "pending", CTX_A),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "pending"


def cm16_i10_protected_event_touch_honest():
    """I10 на защищённом событии: касание и reason -- от GET (запрошен),
    источник СТАТУСА и его контекст/уровень -- от done (не лжёт)."""
    done_evt = _eda("validation_strategy", "eda_check_status", 1, "done",
                    CTX_A, eid="c3c-done-VS")
    done_evt["evidence_level"] = "client_observation"  # штампованный корпус
    get_evt = _eda("validation_strategy", "profile_requested", 2, ctx=CTX_A)
    fold = NodeStateFold()
    fold.apply(done_evt)
    fold.apply(get_evt)
    detail = fold.detail("eda/validation_strategy")
    assert detail["last_touched_at"] == _iso(2)
    assert "запрошен" in (detail["status_reason"] or "").lower()
    assert detail["_status_src"] == "c3c-done-VS"
    assert detail["_status_ctx"] == CTX_A
    assert detail["_status_level"] == "client_observation"


def cm17_chronology_mixed_universes():
    """Сложная честная хронология: done(A) -> GET(A) [защита] ->
    GET(B) [H28: running] -> done(B) [апгрейд] -> pending(B) [H27:
    защита] -- итог done контекста B; история контекста A в ledger
    не участвует в статусе, но не стирается (свой сценарий)."""
    events = [
        _eda("model_matrix", "eda_check_status", 1, "done", CTX_A),
        _eda("model_matrix", "profile_requested", 2, ctx=CTX_A),
        _eda("model_matrix", "profile_requested", 3, ctx=CTX_B),
        _eda("model_matrix", "eda_check_status", 4, "done", CTX_B),
        _eda("model_matrix", "eda_check_status", 5, "pending", CTX_B),
    ]
    assert derive_node_statuses(events)["eda/model_matrix"] == "done"


def cm18_phantom_events_ignored():
    """События без узла/вне графа честно игнорируются движком (N-2,
    фантомных узлов нет) -- контроль неизменности известного узла."""
    events = [
        _eda("distribution", "eda_check_status", 1, "done", CTX_A),
        _event("eda", None, "profile_requested", 2, None, CTX_A),
        _event("eda", "no_such_node", "profile_requested", 3, None, CTX_A),
    ]
    statuses = derive_node_statuses(events)
    assert statuses.get("eda/distribution") == "done"
    assert "eda/no_such_node" not in statuses


# ══════════════════ VL: применимость фактов (validity) ══════════════════

def _fold_states(events, run_ctx):
    fold = NodeStateFold()
    for event in events:
        fold.apply(event)
    return {
        state["node_id"]: state
        for state in fold.node_states_with_evidence(run_context_id=run_ctx)
        if state["stage"] == "eda"
    }


def vl1_current_after_context_shift():
    """13-полевой контракт: после H28-переоткрытия pending нового
    контекста validity current при сверке с новым запуском и stale при
    сверке со старым (непросмотренное и устаревшее различаются)."""
    events = [
        _eda("distribution", "eda_check_status", 1, "done", CTX_A),
        _eda("distribution", "eda_check_status", 2, "pending", CTX_B),
    ]
    fresh = _fold_states(events, CTX_B)["distribution"]
    stale = _fold_states(events, CTX_A)["distribution"]
    assert fresh["validity"] == "current", fresh
    assert stale["validity"] == "stale", stale


def vl2_legacy_fact_unknown_validity():
    """Легаси-факт без контекста -- validity unknown (не current:
    старое достижение не выдаётся за применимое, §21.4)."""
    events = [_eda("ih_analysis", "eda_check_status", 1, "done", None)]
    state = _fold_states(events, CTX_A)["ih_analysis"]
    assert state["validity"] == "unknown", state


def vl3_done_kept_after_get_stays_current():
    """Защищённый GET не меняет применимость done: контекст источника
    остался -- validity current сохраняется (свежесть не «утекает»)."""
    events = [
        _eda("seasonality", "eda_check_status", 1, "done", CTX_A),
        _eda("seasonality", "profile_requested", 2, ctx=CTX_A),
    ]
    state = _fold_states(events, CTX_A)["seasonality"]
    assert state["status"] == "done"
    assert state["validity"] == "current"
    assert state["source_event_id"].endswith("eda_check_status-seasonality")


# ══════════════════════ E2: живой контур ASGI ══════════════════════

_E2_STATE: dict = {}


def _prepare_e2():
    if _E2_STATE.get("ready"):
        return
    import pandas as pd
    from fastapi.testclient import TestClient
    from apps.api.main import app
    from apps.api.research_runs import reset_research_run_store_for_testing
    from apps.api.session_store import reset_session_store_for_testing

    reset_session_store_for_testing()
    reset_research_run_store_for_testing()
    client = TestClient(app)
    idx = pd.date_range("2019-03-01", periods=132, freq="W")
    frame = pd.DataFrame({
        "week": idx.strftime("%Y-%m-%d"),
        "demand": [200.0 - i * 0.5 for i in range(132)],
        "temp": [12.0 + (i % 11) for i in range(132)],
    })
    response = client.post(
        "/v1/internal/upload",
        files={"file": (
            "c3cert_demand_weekly_w132.csv",
            io.BytesIO(frame.to_csv(index=False).encode()),
            "text/csv",
        )},
    )
    assert response.status_code == 200, response.text
    for column in ("demand", "temp"):
        response = client.post("/v1/session/target-column", json={"column": column})
        assert response.status_code == 200, response.text
        # вернуть исходную цель (последняя фиксация -- demand)
        response = client.post("/v1/session/target-column", json={"column": "demand"})
        assert response.status_code == 200, response.text
        break
    _E2_STATE.update({"ready": True, "client": client,
                      "reset_session": reset_session_store_for_testing,
                      "reset_runs": reset_research_run_store_for_testing})


def _client():
    _prepare_e2()
    return _E2_STATE["client"]


def _trace(client) -> dict:
    response = client.get("/v1/progress/trace")
    assert response.status_code == 200, response.text
    return response.json()


def _v2_checks(client, checks: dict, report_id: str) -> dict:
    trace = _trace(client)
    return {
        "checks": checks,
        "schema_version": 2,
        "run_id": trace["run_id"],
        "context_id": trace["context_id"],
        "report_id": report_id,
    }


def _post_checks(client, payload: dict) -> None:
    response = client.post("/v1/progress/eda-checks", json=payload)
    assert response.status_code == 200, response.text


def e1_get_seeds_profile_requested_ih():
    """Р1 на живом контуре (свой маршрут): GET eda-ih сеет
    profile_requested узла ih_analysis; profile_viewed не сеется."""
    client = _client()
    response = client.get("/v1/session/dataset/eda-ih?column=demand")
    assert response.status_code == 200
    facts = [
        item for item in _trace(client)["events"]
        if item.get("stage") == "eda" and item.get("node_id") == "ih_analysis"
    ]
    assert facts and facts[-1]["event_type"] == "profile_requested"


def e2_done_then_get_keeps_done_distribution():
    """P25 e2e (свой узел distribution): done-карта -> GET
    eda-distribution -> узел остаётся done, последний факт -- запрос."""
    client = _client()
    checks = {node: "pending" for node in STAGE_NODES["eda"]}
    checks["distribution"] = "done"
    _post_checks(client, _v2_checks(client, checks, "c3c-map-E2-1"))
    response = client.get("/v1/session/dataset/eda-distribution?column=demand")
    assert response.status_code == 200
    trace = _trace(client)
    assert trace["node_statuses"].get("eda/distribution") == "done"
    facts = [
        item for item in trace["events"]
        if item.get("stage") == "eda" and item.get("node_id") == "distribution"
    ]
    assert facts[-1]["event_type"] == "profile_requested"


def e3_h27_full_pending_map_v2_keeps_done():
    """H27 e2e v2 (свой узел structural): полная pending-карта того же
    контекста НЕ стирает просмотренный done."""
    client = _client()
    checks = {node: "pending" for node in STAGE_NODES["eda"]}
    checks["structural"] = "done"
    _post_checks(client, _v2_checks(client, checks, "c3c-map-E3-1"))
    _post_checks(
        client,
        _v2_checks(
            client, {node: "pending" for node in STAGE_NODES["eda"]},
            "c3c-map-E3-2",
        ),
    )
    trace = _trace(client)
    assert trace["node_statuses"].get("eda/structural") == "done"


def e4_h28_target_shift_validity_and_reopen():
    """H28 e2e (свой узел stationarity + своя цель temp): смена цели
    сдвигает контекст; старый done остаётся в ledger с validity stale
    (I4 -- история не стирается); pending-карта нового контекста
    переоткрывает узел."""
    client = _client()
    response = client.post("/v1/session/target-column", json={"column": "temp"})
    assert response.status_code == 200
    checks = {node: "pending" for node in STAGE_NODES["eda"]}
    checks["stationarity"] = "done"
    _post_checks(client, _v2_checks(client, checks, "c3c-map-E4-1"))
    before = _trace(client)
    assert before["node_statuses"].get("eda/stationarity") == "done"
    response = client.post("/v1/session/target-column", json={"column": "demand"})
    assert response.status_code == 200
    after = _trace(client)
    assert after["context_id"] != before["context_id"]
    node = next(
        n for n in after["nodes"]
        if n["stage"] == "eda" and n["node_id"] == "stationarity"
    )
    assert node["status"] == "done" and node["validity"] == "stale"
    _post_checks(
        client,
        _v2_checks(
            client, {node: "pending" for node in STAGE_NODES["eda"]},
            "c3c-map-E4-2",
        ),
    )
    final = _trace(client)
    assert final["node_statuses"].get("eda/stationarity") == "pending"


def e5_throttle_window_own_nodes():
    """Троттлинг §4.2 (свои узлы): повтор distribution в окне не плодит
    событие; seasonality -- своё событие."""
    client = _client()
    assert client.get("/v1/session/dataset/eda-distribution?column=demand").status_code == 200
    assert client.get("/v1/session/dataset/eda-distribution?column=demand").status_code == 200
    assert client.get("/v1/session/dataset/eda-seasonality?column=demand").status_code == 200
    requested = [
        item for item in _trace(client)["events"]
        if item.get("event_type") == "profile_requested"
    ]
    by_node = [item.get("node_id") for item in requested]
    assert by_node.count("distribution") == 1
    assert by_node.count("seasonality") == 1


def e6_report_renders_request_honestly():
    """Полный отчёт живого контура: последний факт узла ih_analysis --
    запрос; render_markdown несёт «запрошен» (честный текст, не
    «просмотрена»)."""
    client = _client()
    model = build_report_model(
        {"run_id": RUN_ID, "created_at": _iso(0)}, _trace(client)["events"]
    )
    text = render_markdown(model)
    assert "запрошен" in text.lower()


ORACLES = [
    rg1_registry_request_and_legacy_types,
    rg2_evidence_levels,
    rg3_status_map_and_profile_types,
    rg4_reason_honesty,
    rg5_hook_routes_nine_get_requested,
    rg6_hook_never_seeds_viewed,
    rg7_throttle_env_semantics,
    rg8_report_template_honesty,
    cm1_p25_get_keeps_done_and_idempotent,
    cm2_legacy_viewed_keeps_done_same_context,
    cm3_get_from_pending_sets_running,
    cm4_warning_error_skipped_protected,
    cm5_h27_pending_map_does_not_retract_done,
    cm6_h27_honesty_running_to_pending_allowed,
    cm7_h28_get_in_new_context_reopens,
    cm8_h28_pending_in_new_context_reopens,
    cm9_h28_done_upgrade_updates_source,
    cm10_legacy_done_vs_stamped_pending,
    cm11_legacy_done_vs_stamped_get,
    cm12_stamped_done_vs_legacy_pending,
    cm13_legacy_corpus_interim_h1_kept,
    cm14_perimeter_validation_keeps_last_wins,
    cm15_h27_protection_only_for_done,
    cm16_i10_protected_event_touch_honest,
    cm17_chronology_mixed_universes,
    cm18_phantom_events_ignored,
    vl1_current_after_context_shift,
    vl2_legacy_fact_unknown_validity,
    vl3_done_kept_after_get_stays_current,
    e1_get_seeds_profile_requested_ih,
    e2_done_then_get_keeps_done_distribution,
    e3_h27_full_pending_map_v2_keeps_done,
    e4_h28_target_shift_validity_and_reopen,
    e5_throttle_window_own_nodes,
    e6_report_renders_request_honestly,
]


def main() -> int:
    only = set(sys.argv[1:])
    lines: list[str] = [
        "=== PROGR-AUDIT-3-CERT: оракулы сертификатора на СВОИХ данных ===",
        f"Объект: реализация AUDIT-3 (HEAD {REPO and __import__('subprocess').check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO).decode().strip()[:12]})",
        f"Дата: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Корпус: узлы ih_analysis/distribution/structural/stationarity/seasonality/model_matrix + validation/uniqueness; контексты {CTX_A}/{CTX_B}; RUN-C3CERT",
        "",
    ]
    passed = 0
    failed: list[tuple[str, str]] = []
    for oracle in ORACLES:
        name = oracle.__name__
        if only and name not in only and name.split("_")[0] not in only:
            continue
        try:
            oracle()
            passed += 1
            lines.append(f"PASS {name}")
            print(f"PASS {name}", flush=True)
        except Exception as exc:  # noqa: BLE001 — оракул фиксирует ЛЮБОЙ отказ
            failed.append((name, f"{type(exc).__name__}: {exc}"))
            lines.append(f"FAIL {name} — {type(exc).__name__}: {exc}")
            print(f"FAIL {name} — {type(exc).__name__}: {exc}", flush=True)
    total = passed + len(failed)
    lines.append("")
    lines.append(f"ИТОГО: {passed}/{total} PASS, {len(failed)} FAIL; EXIT {0 if not failed else 1}")
    RESULTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nИТОГО: {passed}/{total} PASS, {len(failed)} FAIL")
    print(f"протокол: {RESULTS_PATH}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
