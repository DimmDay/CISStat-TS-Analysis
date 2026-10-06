# tests/api/test_progress_progr18.py
"""Task PROGR-18 (spec_progress_v1.1.md §2, категория B) -- носитель
факта прохождения исследований для стадии eda: зеркало PROGR-16-A /
PROGR-17 (тот же паттерн §7.2 -- клиент строит сводку из уже
полученных данных), с РЕШЕНИЕМ ТИМЛИДА по семантике статуса EDA:

    статус `done`/`pending` по факту «аналитик открыл и просмотрел
    результат»; `warning` НЕ вводить (ложная тревога там, где нет
    критерия ошибки -- EDA не проверка качества, а анализ).

Э-1. Носитель факта: тип события eda_check_status в реестре стадии
      eda (trace_events.py §4.1) -- статус исследования В PAYLOAD
      (ключ "status"), тот же паттерн, что upload_stop_status
      (PROGR-13-A4), validation_check_status (PROGR-16-A) и
      preprocessing_check_status (PROGR-17); движок
      (PAYLOAD_STATUS_EVENT_TYPES) читает его -- статус узла панели.
      Движок остаётся общим (whitelist CHECK_STATUS_VALUES); словарь
      ИМЕННО ОТЧЁТА EDA ограничен {"done", "pending"} на эндпоинте.

Э-2. Контракт POST /v1/progress/eda-checks: модуль отчитывает
      снапшот статусов всех 10 исследований общего реестра
      EDA_STAGE_IDS (eda_checks.json §12 п.2), факты пишутся
      СОБЫТИЯМИ eda_check_status, слой 1 + зеркало слоя 2.
      Fail-closed: неизвестное исследование / статус вне словаря
      отчёта EDA (в том числе warning -- решение тимлида) /
      неполная карта -- 422 ДО первой записи (all-or-nothing);
      без датасета -- 400.

Э-3. Потребители без изменений: панель /trace, Наставник,
      admin-аналитика -- единый движок; отчёт §5.4 --
      человекочитаемая строка нового факта с меткой из реестра
      справки (все 10 исследований EDA имеют статьи «Метрики и
      алгоритм») и формулировками факта просмотра (не проверки).
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.node_status import (
    derive_last_active_stage,
    derive_node_statuses,
    resolve_event_status,
)
from app.core.pipeline_graph import STAGE_NODES
from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

client = TestClient(app)

EXPECTED_CHECK_IDS = STAGE_NODES["eda"]


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
    base = datetime(2026, 10, 6, 14, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=seconds)).isoformat()


def _event(
    stage: str,
    node_id: str | None,
    event_type: str,
    ts: str,
    payload: dict | None = None,
) -> dict:
    """Stored-событие канона §4.1 (8 полей + legacy-алиас timestamp)."""
    return {
        "event_id": f"ev-{ts}-{event_type}",
        "run_id": "RUN-PROGR1801",
        "ts": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": dict(payload or {}),
        "actor": "user",
        "timestamp": ts,
    }


def _monitor_csv() -> str:
    import pandas as pd

    idx = pd.date_range("2013-01-01", periods=150, freq="MS")
    frame = pd.DataFrame(
        {"date": idx.strftime("%Y-%m-%d"), "value": [120.0 + i for i in range(150)]}
    )
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


# ── Э-1: носитель факта -- единый движок ─────────────────────────────


def test_resolve_event_status_reads_payload_status():
    """eda_check_status -- payload-статусный тип: статус из
    payload["status"]. Движок ОБЩИЙ (whitelist CHECK_STATUS_VALUES --
    трасса журнал, чужой мусор честно пропускается без фантомных
    статусов); словарь ИМЕННО ОТЧЁТА EDA ({"done", "pending"}, решение
    тимлида) enforced эндпоинтом, не движком -- граница слоёв."""
    event = _event(
        "eda", "descriptive", "eda_check_status", _iso(1),
        {"status": "done"},
    )
    assert resolve_event_status(event) == "done"

    # Словарь отчёта EDA -- {"done", "pending"}: оба проходят движок
    # (он общий для всех payload-статусных типов).
    assert resolve_event_status(
        _event("eda", "correlation", "eda_check_status", _iso(2),
               {"status": "pending"})
    ) == "pending"

    garbage = [
        {"status": "exploded"},           # вне CheckStatus
        {"status": True},                 # не строка
        {},                               # статуса нет
    ]
    for payload in garbage:
        bad = _event(
            "eda", "descriptive", "eda_check_status", _iso(3), payload,
        )
        assert resolve_event_status(bad) is None, payload


def test_eda_check_status_is_node_fact_and_moves_mentor_phase():
    """Узловой факт: движок красит узел eda/<study_id> (id исследований
    EDA сознательно пересекаются с Предобработкой -- stationarity:
    составной ключ "stage/node_id" разводит их); фаза Наставника (B1)
    -- стадия последнего узлового факта."""
    statuses = derive_node_statuses([
        _event("upload", "overview", "upload_completed", _iso(1)),
        _event("eda", "stationarity", "eda_check_status",
               _iso(2), {"status": "done"}),
    ])
    assert statuses["upload/overview"] == "done"
    assert statuses["eda/stationarity"] == "done"
    # Составной ключ: eda/stationarity не растворяется в
    # preprocessing/stationarity (тот же id -- другие узлы графа).
    assert "preprocessing/stationarity" not in statuses

    phase_events = [
        _event("upload", "overview", "upload_completed", _iso(1)),
        _event("eda", "descriptive", "eda_check_status",
               _iso(2), {"status": "done"}),
    ]
    assert derive_last_active_stage(phase_events) == "eda"


# ── Э-2: контракт POST /v1/progress/eda-checks ────────────────────────


def _full_checks_map(status: str = "done") -> dict[str, str]:
    """Снапшот ВСЕХ 10 исследований реестра (модуль отчитывает
    полностью); словарь отчёта EDA -- {"done", "pending"}."""
    assert status in ("done", "pending")
    return {check_id: status for check_id in EXPECTED_CHECK_IDS}


def test_eda_checks_endpoint_full_contract():
    """Контракт Э-2 end-to-end: снапшот модуля -- события в слое 1 И
    зеркале слоя 2; панель показывает ТЕ ЖЕ статусы («панель ==
    модулю»); свёртка стадии -- attention, пока не все исследования
    просмотрены (done+pending -- «в работе», §12 п.10)."""
    _upload()
    checks = {
        "descriptive": "done",
        "correlation": "done",
        "ih_analysis": "done",
        "seasonality": "done",
        "stationarity": "done",
        "distribution": "done",
        "structural": "pending",
        "feature_select": "pending",
        "validation_strategy": "pending",
        "model_matrix": "pending",
    }
    assert set(checks) == set(EXPECTED_CHECK_IDS)

    reported = client.post(
        "/v1/progress/eda-checks", json={"checks": checks}
    )
    assert reported.status_code == 200, reported.text
    body = reported.json()
    assert body["reported"] == 10
    assert body["run_id"] and body["run_id"].startswith("RUN-")

    # Слой 1: 10 событий eda_check_status со статусом в payload.
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    layer1 = [
        event for event in session.pipeline_trace
        if event["event_type"] == "eda_check_status"
    ]
    assert len(layer1) == 10
    by_node = {event["node_id"]: event for event in layer1}
    for check_id, status in checks.items():
        assert by_node[check_id]["payload"]["status"] == status
        assert by_node[check_id]["stage"] == "eda"
        assert by_node[check_id]["run_id"] == body["run_id"]

    # Слой 2 (зеркало §5): Наставник и admin-аналитика видят факты.
    from apps.api.research_runs import get_research_run_store

    stored = get_research_run_store().list_events(body["run_id"])
    mirror = [
        event for event in stored
        if event.event_type == "eda_check_status"
    ]
    assert len(mirror) == 10

    # Панель == модулю.
    trace = _trace()
    for check_id, status in checks.items():
        assert trace["node_statuses"].get(f"eda/{check_id}") == status

    # Свёртка стадии: просмотренные 6 + ожидающие 4 -> attention
    # («в работе»); warning_nodes == 0 -- warning в словаре EDA нет
    # (решение тимлида: ложная тревога там, где нет критерия ошибки).
    stage_state = next(
        s for s in trace["stages"] if s["stage"] == "eda"
    )
    assert stage_state["fold"] == "attention"
    assert stage_state["done_count"] == 6
    assert stage_state["warning_nodes"] == 0
    assert stage_state["total_nodes"] == 10


def test_eda_checks_all_viewed_folds_to_passed():
    """Все 10 исследований просмотрены -- карточка стадии «пройдено»
    (fold passed): факт просмотра EDA не знает warning-замечаний."""
    _upload()
    reported = client.post(
        "/v1/progress/eda-checks",
        json={"checks": _full_checks_map("done")},
    )
    assert reported.status_code == 200, reported.text

    trace = _trace()
    stage_state = next(
        s for s in trace["stages"] if s["stage"] == "eda"
    )
    assert stage_state["fold"] == "passed"
    assert stage_state["done_count"] == 10
    assert stage_state["warning_nodes"] == 0


def test_eda_checks_endpoint_fail_closed_all_or_nothing():
    """Fail-closed (паттерн sanity-check §7.2): неизвестное исследование
    / статус вне словаря отчёта EDA (в том числе ЛЕГАЛЬНЫЙ CheckStatus
    «warning» -- решение тимлида: warning для EDA не вводить) /
    неполная карта -- 422 ДО первой записи; в трассе ни одного события
    отчёта (all-or-nothing)."""
    _upload()
    bad_payloads = [
        # неизвестное исследование -- фантом
        {"checks": {**_full_checks_map(), "phantom_study": "done"}},
        # warning -- статус ВНЕ словаря отчёта EDA (решение тимлида:
        # «warning не вводить -- ложная тревога там, где нет критерия
        # ошибки»); статус легален для CheckStatus, но не для отчёта EDA
        {"checks": {**_full_checks_map(), "descriptive": "warning"}},
        # недопустимый статус -- мусор вне CheckStatus
        {"checks": {**_full_checks_map(), "descriptive": "exploded"}},
        # неполная карта -- не снапшот реестра
        {"checks": {"descriptive": "done"}},
        # пустая карта
        {"checks": {}},
    ]
    for payload in bad_payloads:
        response = client.post(
            "/v1/progress/eda-checks", json=payload
        )
        assert response.status_code == 422, (payload, response.text)

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    assert not [
        event for event in session.pipeline_trace
        if event["event_type"] == "eda_check_status"
    ]


def test_eda_checks_endpoint_requires_dataset():
    """Аналитик без датасета -- честный 400: исследования EDA без
    данных не существуют (паттерн /upload-stops, /validation-checks и
    /preprocessing-checks «Сначала загрузите датасет»)."""
    response = client.post(
        "/v1/progress/eda-checks",
        json={"checks": _full_checks_map()},
    )
    assert response.status_code == 400


def test_eda_checks_endpoint_seeds_run_id_on_first_report():
    """Отчёт исследований -- первый трассируемый факт сессии (запуск
    мог произойти мимо хука): run_id фиксируется по факту первой
    записи (§5, паттерн A4/A16)."""
    _upload()
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    session.run_id = ""
    get_session_store().save(session)

    reported = client.post(
        "/v1/progress/eda-checks",
        json={"checks": _full_checks_map()},
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["run_id"].startswith("RUN-")


def test_eda_checks_last_wins_on_rereport():
    """Повторный отчёт с изменившейся картой просмотра -- хронология
    решает: панель показывает ПОСЛЕДНИЙ снапшот модуля (последнее
    событие узла выигрывает в едином движке). Просмотр монотонен в
    клиенте (set просмотренных растёт), но контракт last-wins --
    свойство движка, не клиента."""
    _upload()
    first = client.post(
        "/v1/progress/eda-checks",
        json={"checks": _full_checks_map("pending")},
    )
    assert first.status_code == 200, first.text

    second_map = _full_checks_map("pending")
    second_map["descriptive"] = "done"
    second = client.post(
        "/v1/progress/eda-checks", json={"checks": second_map}
    )
    assert second.status_code == 200, second.text

    trace = _trace()
    assert trace["node_statuses"].get("eda/descriptive") == "done"
    assert trace["node_statuses"].get("eda/correlation") == "pending"


# ── Э-3: потребители -- отчёт §5.4 без изменений контракта ───────────


def test_report_renders_eda_check_facts_with_registry_labels():
    """Отчёт §5.4 -- та же гранулярность, что у панели:
    человекочитаемая строка факта eda_check_status, метка исследования
    -- из реестра справки (node_label; все 10 исследований EDA имеют
    статьи «Метрики и алгоритм»), без сырых id. Терминология -- факта
    ПРОСМОТРА (EDA -- анализ, не проверка качества; решение тимлида),
    модуль назван ЯВНО -- в журнале отчёта строка однозначно
    отличается от строк «Валидации»/«Предобработки»."""
    from app.core.run_report import build_report_model, render_markdown

    events = [
        _event("upload", "overview", "upload_completed", _iso(1),
               {"name": "monitor.csv", "rows": 150, "columns": 2}),
        _event("eda", "descriptive", "eda_check_status",
               _iso(2), {"status": "done"}),
        _event("eda", "correlation", "eda_check_status",
               _iso(3), {"status": "pending"}),
    ]
    run_meta = {
        "run_id": "RUN-PROGR1801", "dataset_name": "monitor.csv",
        "status": "active", "created_at": _iso(0), "last_active_at": _iso(3),
    }
    model = build_report_model(run_meta, events)
    md = render_markdown(model)

    assert (
        "Статус исследования «Описательные статистики» отчитан модулем "
        "«EDA»: результат просмотрен аналитиком." in md
    )
    assert (
        "Статус исследования «Корреляция (ACF/PACF)» отчитан модулем "
        "«EDA»: ещё не просмотрен аналитиком." in md
    )
