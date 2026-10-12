# tests/api/test_progress_audit_3.py
"""AUDIT-3 (plan_progress_audit.md §13) -- EDA: показ, запрос и свежесть.

Задача закрывает F17/P25 и H27/H28 по карточке плана §13:

  Р1 (спека §13 п.1): GET означает ЗАПРОС/ВЫЧИСЛЕНИЕ профиля; событие
      показа результата приходит от UI. Ни один GET сам по себе не
      удостоверяет просмотр человеком. Носитель запроса -- НОВЫЙ тип
      profile_requested (троттлинг сохранён); profile_viewed остаётся
      легаси-типом чтения (корпус не переписывается, §3.7).
  Р2 (спека §13 п.2): для одного context/result факт нового запроса
      профиля не отменяет прежнее viewed/done -- контекст-ключевая
      монотонность редьюсера (замена interim-монотонности H1,
      запланированная Донастройкой плана Часть 2).
  Р3 (спека §13 п.6): рутинный pending ПОЛНОЙ карты eda_check_status
      НЕ retract-ит просмотренный done в своём контексте (H27:
      срыв seed не стирает историю). Явный retract -- отдельный
      контракт, здесь НЕ реализуется.
  Р4 (спека §13 п.4): смена контекста (оба контекста известны и
      различны) -- новая применимость: last-wins честен (H28);
      неизвестные контексты (легаси) смену НЕ утверждают -- защита
      done сохраняется (unknown != смена).

Гранулярность оракула: REG (реестр/семантика запроса), CM
(контекст-ключевая монотонность редьюсера, unit), E2E (живой контур:
хук, карты, троттлинг, легаси), RPT (шаблон отчёта). RED-протокол на
базе -- scripts/prograudit3_red_protocol.txt.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.node_status import (
    NodeStateFold,
    derive_node_statuses,
    resolve_event_status,
)
from app.core.pipeline_graph import STAGE_NODES
from app.core.run_report import build_report_model, render_markdown
from apps.api.main import app
from apps.api.session_store import (
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import (
    STAGE_EVENT_TYPES,
    make_trace_event,
    resolve_evidence_level,
)

client = TestClient(app)

CTX_A = "ctx-aaaaaaaaaaaaaaaa"
CTX_B = "ctx-bbbbbbbbbbbbbbbb"


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


def _iso(seconds: float) -> str:
    base = datetime(2026, 10, 13, 9, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=seconds)).isoformat()


def _event(
    stage: str,
    node_id: str | None,
    event_type: str,
    ts: str,
    payload: dict | None = None,
    context_id: str | None = None,
) -> dict:
    """Stored-событие канона §4.1 (+ context_id envelope v2, AUDIT-C)."""
    return {
        "event_id": f"ev-{ts}-{event_type}",
        "run_id": "RUN-AUDIT301",
        "ts": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": dict(payload or {}),
        "actor": "user",
        "timestamp": ts,
        "context_id": context_id,
    }


# ── REG: реестр и семантика запроса (Р1) ─────────────────────────────


def test_profile_requested_registered_on_eda_stage():
    """Новый тип profile_requested зарегистрирован за стадией eda;
    фабрика пропускает его (fail-closed гейт §4.1)."""
    assert "profile_requested" in STAGE_EVENT_TYPES["eda"]
    event = make_trace_event(
        "profile_requested",
        stage="eda",
        node_id="correlation",
        run_id="RUN-AUDIT301",
    )
    assert event.event_type == "profile_requested"
    assert event.stage == "eda"
    assert event.node_id == "correlation"


def test_profile_requested_resolves_running():
    """GET -- узел исследуется (running); семантика карты не менялась:
    running не «просмотр» (показ результата -- факт модуля)."""
    data = {
        "event_type": "profile_requested",
        "stage": "eda",
        "node_id": "correlation",
        "payload": {},
    }
    assert resolve_event_status(data) == "running"


def test_profile_requested_evidence_operational():
    """Уровень доказательности GET-запроса -- operational (авто-факт
    middleware, не client_observation и не user_decision)."""
    assert resolve_evidence_level("profile_requested", {}) == "operational"


def test_profile_viewed_legacy_type_still_read():
    """Легаси-тип profile_viewed остаётся в реестре и читается
    (корпус не переписывается, §3.7); хук его больше не сеет --
    проверяется в E2E."""
    assert "profile_viewed" in STAGE_EVENT_TYPES["eda"]
    assert (
        resolve_event_status(
            {"event_type": "profile_viewed", "stage": "eda", "payload": {}}
        )
        == "running"
    )


# ── CM: контекст-ключевая монотонность редьюсера (Р2/Р3/Р4) ──────────


def test_p25_get_does_not_lower_done_same_context():
    """P25/F17: повторный GET профиля в СВОЁМ контексте не понижает
    done (просмотр сохранён); честный след запроса -- reason и касание."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "done"}, context_id=CTX_A),
        _event("eda", "correlation", "profile_requested", _iso(2),
               context_id=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "done"


def test_p25_legacy_profile_viewed_same_context_protected():
    """Легаси-тип profile_viewed в СВОЁМ контексте -- та же защита
    (монотонность покрывает оба типа запроса)."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "done"}, context_id=CTX_A),
        _event("eda", "correlation", "profile_viewed", _iso(2),
               context_id=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "done"


def test_get_from_pending_sets_running_same_context():
    """Запрос на непросмотренном узле -- running (не понижение)."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "pending"}, context_id=CTX_A),
        _event("eda", "correlation", "profile_requested", _iso(2),
               context_id=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "running"


def test_context_shift_get_refreshes_applicability_h28():
    """H28: GET в НОВОМ контексте (оба известны, различны) --
    новая применимость: last-wins честен, running утверждается."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "done"}, context_id=CTX_A),
        _event("eda", "correlation", "profile_requested", _iso(2),
               context_id=CTX_B),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "running"


def test_h27_routine_pending_does_not_retract_done_same_context():
    """H27/Р3: рутинный pending полной карты eda_check_status в СВОЁМ
    контексте не retract-ит просмотренный done (срыв seed не стирает
    историю). Явный retract -- отдельный контракт (не здесь)."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "done"}, context_id=CTX_A),
        _event("eda", "correlation", "eda_check_status", _iso(2),
               {"status": "pending"}, context_id=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "done"


def test_context_shift_pending_reopens_h28():
    """H28: pending карты в НОВОМ контексте -- новая применимость
    (контекст сменился -- переоткрытие честно)."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "done"}, context_id=CTX_A),
        _event("eda", "correlation", "eda_check_status", _iso(2),
               {"status": "pending"}, context_id=CTX_B),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "pending"


def test_legacy_done_protected_from_stamped_pending():
    """Неизвестный контекст статуса (легаси) НЕ утверждает смену
    контекста: stamped pending легаси-done не retract-ит."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "done"}),
        _event("eda", "correlation", "eda_check_status", _iso(2),
               {"status": "pending"}, context_id=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "done"


def test_legacy_done_protected_from_stamped_get():
    """То же для GET: легаси-done + stamped profile_requested --
    защита (unknown != смена)."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "done"}),
        _event("eda", "correlation", "profile_requested", _iso(2),
               context_id=CTX_A),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "done"


def test_legacy_done_protected_from_legacy_get_interim_h1():
    """Interim-семантика H1 для легаси-корпуса сохранена: легаси-done +
    легаси-GET -- done (регресс легаси-чтения недопустим)."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "done"}),
        _event("eda", "correlation", "profile_viewed", _iso(2)),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "done"


def test_done_from_context_shift_is_last_wins():
    """Повторный отчёт done в новом контексте -- апгрейд без помех;
    статус-источник обновляется на новое событие."""
    events = [
        _event("eda", "correlation", "eda_check_status", _iso(1),
               {"status": "done"}, context_id=CTX_A),
        _event("eda", "correlation", "eda_check_status", _iso(2),
               {"status": "done"}, context_id=CTX_B),
    ]
    assert derive_node_statuses(events)["eda/correlation"] == "done"


def test_warning_and_error_protected_from_get_same_context():
    """Защита распространяется на все статусы честнее running."""
    for status in ("warning", "error", "skipped"):
        events = [
            _event("eda", "correlation", "eda_check_status", _iso(1),
                   {"status": status}, context_id=CTX_A),
            _event("eda", "correlation", "profile_requested", _iso(2),
                   context_id=CTX_A),
        ]
        assert derive_node_statuses(events)["eda/correlation"] == status


def test_upgrade_paths_unaffected():
    """Апгрейды не защищаются: pending -> running, pending -> done,
    running -> done -- last-wins как прежде."""
    cases = (
        ("profile_requested", {}, "running"),
        ("eda_check_status", {"status": "done"}, "done"),
    )
    for event_type, payload, expected in cases:
        events = [
            _event("eda", "correlation", "eda_check_status", _iso(1),
                   {"status": "pending"}, context_id=CTX_A),
            _event("eda", "correlation", event_type, _iso(2),
                   payload, context_id=CTX_A),
        ]
        assert derive_node_statuses(events)["eda/correlation"] == expected


def test_touched_on_protected_event_source_kept():
    """Защищённое событие касания честно: last_touched_at обновляется,
    источник СТАТУСА остаётся событием done (I10: источник не лжёт)."""
    fold = NodeStateFold()
    done_event = _event("eda", "correlation", "eda_check_status", _iso(1),
                        {"status": "done"}, context_id=CTX_A)
    get_event = _event("eda", "correlation", "profile_requested", _iso(2),
                       context_id=CTX_A)
    fold.apply(done_event)
    fold.apply(get_event)
    detail = fold.detail("eda/correlation")
    assert detail["last_touched_at"] == _iso(2)
    assert detail["_status_src"] == done_event["event_id"]
    # reason -- от последнего события решения (запроса)
    assert detail["_status_ctx"] == CTX_A


# ── E2E: живой контур (хук, карты, троттлинг, легаси) ────────────────


def _monitor_csv() -> str:
    import pandas as pd

    idx = pd.date_range("2013-01-01", periods=150, freq="MS")
    frame = pd.DataFrame(
        {
            "date": idx.strftime("%Y-%m-%d"),
            "value": [120.0 + i for i in range(150)],
            "humidity": [40.0 + (i % 7) * 0.5 for i in range(150)],
        }
    )
    return frame.to_csv(index=False)


def _set_target(column: str) -> None:
    response = client.post("/v1/session/target-column", json={"column": column})
    assert response.status_code == 200, response.text


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


def _full_checks_map(status: str = "pending") -> dict:
    return {node_id: status for node_id in STAGE_NODES["eda"]}


def _v2_checks(checks: dict, report_id: str) -> dict:
    """v2-конверт AUDIT-2A: биндинг из /trace (тот же источник, I3)."""
    trace = _trace()
    return {
        "checks": checks,
        "schema_version": 2,
        "run_id": trace["run_id"],
        "context_id": trace["context_id"],
        "report_id": report_id,
    }


def _post_checks(payload: dict) -> None:
    response = client.post("/v1/progress/eda-checks", json=payload)
    assert response.status_code == 200, response.text


def test_e2e_get_seeds_profile_requested_not_viewed():
    """Р1 на живом контуре: GET профиля EDA сеет profile_requested
    (запрос), а не profile_viewed (ложное «просмотрено»)."""
    _upload()
    _set_target("value")
    response = client.get("/v1/session/dataset/eda-correlation?column=value")
    assert response.status_code == 200
    events = _trace()["events"]
    correlation = [
        item for item in events
        if item.get("node_id") == "correlation" and item.get("stage") == "eda"
    ]
    assert correlation, "GET обязан оставлять след трассы"
    assert correlation[-1]["event_type"] == "profile_requested"


def test_e2e_done_map_then_get_keeps_done():
    """P25 e2e: done карты -> GET -> узел остаётся done; последний факт
    узла -- запрос (не просмотр)."""
    _upload()
    checks = _full_checks_map("pending")
    checks["correlation"] = "done"
    _set_target("value")
    _post_checks(_v2_checks(checks, "map-a3-done-1"))
    response = client.get("/v1/session/dataset/eda-correlation?column=value")
    assert response.status_code == 200
    trace = _trace()
    assert trace["node_statuses"].get("eda/correlation") == "done"
    correlation = [
        item for item in trace["events"]
        if item.get("node_id") == "correlation" and item.get("stage") == "eda"
    ]
    assert correlation[-1]["event_type"] == "profile_requested"


def test_e2e_h27_pending_card_does_not_retract_done_v2():
    """H27 e2e (v2): полная pending-карта того же контекста НЕ стирает
    просмотренный done (двойная защита: редьюсер + UI-удержание)."""
    _upload()
    checks = _full_checks_map("pending")
    checks["correlation"] = "done"
    _post_checks(_v2_checks(checks, "map-a3-h27-1"))
    _post_checks(_v2_checks(_full_checks_map("pending"), "map-a3-h27-2"))
    trace = _trace()
    assert trace["node_statuses"].get("eda/correlation") == "done"


def test_e2e_h27_pending_card_does_not_retract_done_legacy():
    """H27 e2e (легаси): то же без конверта -- повтор легаси ПИШЕТ
    события (P07-семантика 2A не тронута), но рутинный pending не
    retract-ит done (unknown != смена контекста)."""
    _upload()
    checks = _full_checks_map("pending")
    checks["correlation"] = "done"
    _post_checks({"checks": checks})
    _post_checks({"checks": _full_checks_map("pending")})
    trace = _trace()
    assert trace["node_statuses"].get("eda/correlation") == "done"


def test_e2e_h28_target_change_new_applicability():
    """H28 e2e: смена цели сдвигает контекст; pending-карта нового
    контекста переоткрывает узел; факт validity -- current у нового
    статуса (непросмотренное и устаревшее различаются)."""
    _upload()
    _set_target("value")
    checks = _full_checks_map("pending")
    checks["correlation"] = "done"
    _post_checks(_v2_checks(checks, "map-a3-h28-1"))
    before = _trace()
    assert before["node_statuses"].get("eda/correlation") == "done"
    _set_target("humidity")
    after = _trace()
    assert after["context_id"] != before["context_id"], (
        "смена цели обязана сдвигать контекст расчёта"
    )
    # Старый done ещё виден (исторические факты не стираются, I4),
    # но его применимость -- stale (устаревшее != непросмотренное).
    stale_nodes = [
        node for node in after["nodes"]
        if node["stage"] == "eda" and node["node_id"] == "correlation"
    ]
    assert stale_nodes and stale_nodes[0]["status"] == "done"
    assert stale_nodes[0]["validity"] == "stale"
    # pending-карта нового контекста -- новая применимость.
    _post_checks(_v2_checks(_full_checks_map("pending"), "map-a3-h28-2"))
    final = _trace()
    assert final["node_statuses"].get("eda/correlation") == "pending"


def test_e2e_throttle_profile_requested():
    """Троттлинг §4.2 переносится на профиль запроса: повторный GET
    узла в окне не плодит события; другой узел -- своё событие."""
    _upload()
    _set_target("value")
    assert client.get("/v1/session/dataset/eda-correlation?column=value").status_code == 200
    assert client.get("/v1/session/dataset/eda-correlation?column=value").status_code == 200
    assert client.get("/v1/session/dataset/eda-stationarity?column=value").status_code == 200
    events = _trace()["events"]
    requested = [
        item for item in events if item.get("event_type") == "profile_requested"
    ]
    nodes = {item.get("node_id") for item in requested}
    assert len([item for item in requested if item.get("node_id") == "correlation"]) == 1
    assert nodes == {"correlation", "stationarity"}


def test_report_template_profile_requested():
    """Отчёт §5.4: у нового типа есть человекочитаемый шаблон
    (не общий fallback «неизвестное событие»)."""
    events = [
        _event("eda", "correlation", "profile_requested", _iso(1),
               context_id=CTX_A),
    ]
    model = build_report_model(
        {"run_id": "RUN-AUDIT301", "created_at": _iso(0)}, events
    )
    text = render_markdown(model)
    assert "запрошен" in text.lower()


# ── Контроль периметра: Валидация/Предобработка не затронуты ─────────


def test_validation_cards_keep_last_wins_out_of_scope():
    """Периметр AUDIT-3 -- EDA: карты Валидации сохраняют last-wins
    (рутинный pending переоткрывает проверку, детерминированные
    статусы профильных ответов)."""
    events = [
        _event("validation", "ranges", "validation_check_status", _iso(1),
               {"status": "done"}, context_id=CTX_A),
        _event("validation", "ranges", "validation_check_status", _iso(2),
               {"status": "pending"}, context_id=CTX_A),
    ]
    assert derive_node_statuses(events)["validation/ranges"] == "pending"
