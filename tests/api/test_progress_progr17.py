# tests/api/test_progress_progr17.py
"""Task PROGR-17 (spec_progress_v1.1.md §2, категория B) -- носитель
факта прохождения этапов для стадии preprocessing: зеркало PROGR-16-A
буквально (зеркало /validation-checks, тот же паттерн §7.2 --
клиент строит сводку из уже полученных данных).

Пр-1. Носитель факта: тип события preprocessing_check_status в реестре
      стадии preprocessing (trace_events.py §4.1) -- статус проверки В
      PAYLOAD (ключ "status", whitelist CHECK_STATUS_VALUES), тот же
      паттерн, что upload_stop_status (PROGR-13-A4) и
      validation_check_status (PROGR-16-A); движок
      (PAYLOAD_STATUS_EVENT_TYPES) читает его -- статус узла панели.

Пр-2. Контракт POST /v1/progress/preprocessing-checks: модуль
      «Предобработка» отчитывает снапшот статусов всех 10 остановок
      реестра PREPROCESSING_CHECK_IDS, факты пишутся СОБЫТИЯМИ
      preprocessing_check_status, слой 1 + зеркало слоя 2. Fail-closed:
      неизвестная остановка / недопустимый статус / неполная карта --
      422 ДО первой записи (all-or-nothing); без датасета -- 400.

Пр-3. Потребители без изменений: панель /trace, Наставник, admin-
      аналитика -- единый движок; отчёт §5.4 -- человекочитаемая строка
      нового факта с меткой из реестра справки (все 10 остановок
      Предобработки имеют статьи «Метрики и алгоритм»).
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

EXPECTED_CHECK_IDS = STAGE_NODES["preprocessing"]


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
        "run_id": "RUN-PROGR1701",
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


# ── Пр-1: носитель факта -- единый движок ────────────────────────────


def test_resolve_event_status_reads_payload_status():
    """preprocessing_check_status -- payload-статусный тип: статус из
    payload["status"] (whitelist CHECK_STATUS_VALUES); мусор честно
    пропускается движком (фантомных статусов нет)."""
    event = _event(
        "preprocessing", "missing", "preprocessing_check_status", _iso(1),
        {"status": "warning"},
    )
    assert resolve_event_status(event) == "warning"

    garbage = [
        {"status": "exploded"},           # вне CheckStatus
        {"status": True},                 # не строка
        {},                               # статуса нет
    ]
    for payload in garbage:
        bad = _event(
            "preprocessing", "missing", "preprocessing_check_status",
            _iso(2), payload,
        )
        assert resolve_event_status(bad) is None, payload


def test_preprocessing_check_status_is_node_fact_and_moves_mentor_phase():
    """Узловой факт: движок красит узел preprocessing/<check_id>; фаза
    Наставника (B1) -- стадия последнего узлового факта."""
    statuses = derive_node_statuses([
        _event("upload", "overview", "upload_completed", _iso(1)),
        _event("preprocessing", "outliers", "preprocessing_check_status",
               _iso(2), {"status": "warning"}),
    ])
    assert statuses["upload/overview"] == "done"
    assert statuses["preprocessing/outliers"] == "warning"

    phase_events = [
        _event("upload", "overview", "upload_completed", _iso(1)),
        _event("preprocessing", "outliers", "preprocessing_check_status",
               _iso(2), {"status": "done"}),
    ]
    assert derive_last_active_stage(phase_events) == "preprocessing"


# ── Пр-2: контракт POST /v1/progress/preprocessing-checks ────────────


def _full_checks_map(missing: str = "done") -> dict[str, str]:
    """Снапшот ВСЕХ 10 остановок реестра (модуль отчитывает полностью)."""
    return {check_id: missing for check_id in EXPECTED_CHECK_IDS}


def test_preprocessing_checks_endpoint_full_contract():
    """Контракт Пр-2 end-to-end: снапшот модуля -- события в слое 1 И
    зеркале слоя 2; панель показывает ТЕ ЖЕ статусы («панель ==
    модулю»); карточка стадии -- attention при warning-остановках
    (§12 п.10)."""
    _upload()
    checks = {
        "missing": "done",
        "outliers": "warning",
        "regularity": "done",
        "decomposition": "done",
        "variance_stab": "warning",
        "smoothing": "done",
        "stationarity": "warning",
        "spectral": "done",
        "feature_eng": "skipped",
        "scaling": "done",
    }
    assert set(checks) == set(EXPECTED_CHECK_IDS)

    reported = client.post(
        "/v1/progress/preprocessing-checks", json={"checks": checks}
    )
    assert reported.status_code == 200, reported.text
    body = reported.json()
    assert body["reported"] == 10
    assert body["run_id"] and body["run_id"].startswith("RUN-")

    # Слой 1: 10 событий preprocessing_check_status со статусом в payload.
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    layer1 = [
        event for event in session.pipeline_trace
        if event["event_type"] == "preprocessing_check_status"
    ]
    assert len(layer1) == 10
    by_node = {event["node_id"]: event for event in layer1}
    for check_id, status in checks.items():
        assert by_node[check_id]["payload"]["status"] == status
        assert by_node[check_id]["stage"] == "preprocessing"
        assert by_node[check_id]["run_id"] == body["run_id"]

    # Слой 2 (зеркало §5): Наставник и admin-аналитика видят факты.
    from apps.api.research_runs import get_research_run_store

    stored = get_research_run_store().list_events(body["run_id"])
    mirror = [
        event for event in stored
        if event.event_type == "preprocessing_check_status"
    ]
    assert len(mirror) == 10

    # Панель == модулю.
    trace = _trace()
    for check_id, status in checks.items():
        assert trace["node_statuses"].get(f"preprocessing/{check_id}") == status

    # Свёртка стадии: любой warning -> attention (§12 п.10).
    stage_state = next(
        s for s in trace["stages"] if s["stage"] == "preprocessing"
    )
    assert stage_state["fold"] == "attention"
    assert stage_state["done_count"] == 6
    assert stage_state["warning_nodes"] == 3
    assert stage_state["total_nodes"] == 10


def test_preprocessing_checks_endpoint_fail_closed_all_or_nothing():
    """Fail-closed (паттерн sanity-check §7.2): неизвестная остановка /
    недопустимый статус / неполная карта -- 422 ДО первой записи; в
    трассе ни одного события отчёта (all-or-nothing)."""
    _upload()
    bad_payloads = [
        # неизвестная остановка -- фантом
        {"checks": {**_full_checks_map(), "phantom_stop": "done"}},
        # недопустимый статус -- вне CheckStatus
        {"checks": {**_full_checks_map(), "missing": "exploded"}},
        # неполная карта -- не снапшот реестра
        {"checks": {"missing": "done"}},
        # пустая карта
        {"checks": {}},
    ]
    for payload in bad_payloads:
        response = client.post(
            "/v1/progress/preprocessing-checks", json=payload
        )
        assert response.status_code == 422, (payload, response.text)

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    assert not [
        event for event in session.pipeline_trace
        if event["event_type"] == "preprocessing_check_status"
    ]


def test_preprocessing_checks_endpoint_requires_dataset():
    """Аналитик без датасета -- честный 400: этапы «Предобработки» без
    исследования не существуют (паттерн /upload-stops и /validation-checks
    «Сначала загрузите датасет»)."""
    response = client.post(
        "/v1/progress/preprocessing-checks",
        json={"checks": _full_checks_map()},
    )
    assert response.status_code == 400


def test_preprocessing_checks_endpoint_seeds_run_id_on_first_report():
    """Отчёт этапов -- первый трассируемый факт сессии (запуск мог
    произойти мимо хука): run_id фиксируется по факту первой записи
    (§5, паттерн A4/A16)."""
    _upload()
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    session.run_id = ""
    get_session_store().save(session)

    reported = client.post(
        "/v1/progress/preprocessing-checks",
        json={"checks": _full_checks_map()},
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["run_id"].startswith("RUN-")


def test_preprocessing_checks_last_wins_on_rereport():
    """Повторный отчёт с изменившимися статусами -- хронология решает:
    панель показывает ПОСЛЕДНИЙ снапшот модуля (последнее событие узла
    выигрывает в едином движке)."""
    _upload()
    first = client.post(
        "/v1/progress/preprocessing-checks",
        json={"checks": _full_checks_map("done")},
    )
    assert first.status_code == 200, first.text

    second_map = _full_checks_map("done")
    second_map["outliers"] = "warning"
    second = client.post(
        "/v1/progress/preprocessing-checks", json={"checks": second_map}
    )
    assert second.status_code == 200, second.text

    trace = _trace()
    assert trace["node_statuses"].get("preprocessing/missing") == "done"
    assert trace["node_statuses"].get("preprocessing/outliers") == "warning"


# ── Пр-3: потребители -- отчёт §5.4 без изменений контракта ──────────


def test_report_renders_preprocessing_check_facts_with_registry_labels():
    """Отчёт §5.4 -- та же гранулярность, что у панели: человекочитаемая
    строка факта preprocessing_check_status, метка остановки -- из
    реестра справки (node_label; все 10 остановок Предобработки имеют
    статьи «Метрики и алгоритм»), без сырых id. Модуль назван явно --
    в журнале отчёта строка однозначно отличается от строки «Валидации»
    (существующий контракт которой не сужается)."""
    from app.core.run_report import build_report_model, render_markdown

    events = [
        _event("upload", "overview", "upload_completed", _iso(1),
               {"name": "monitor.csv", "rows": 150, "columns": 2}),
        _event("preprocessing", "missing", "preprocessing_check_status",
               _iso(2), {"status": "done"}),
        _event("preprocessing", "outliers", "preprocessing_check_status",
               _iso(3), {"status": "warning"}),
    ]
    run_meta = {
        "run_id": "RUN-PROGR1701", "dataset_name": "monitor.csv",
        "status": "active", "created_at": _iso(0), "last_active_at": _iso(3),
    }
    model = build_report_model(run_meta, events)
    md = render_markdown(model)

    assert (
        "Статус проверки «Пропуски» отчитан модулем «Предобработка»: "
        "выполнена." in md
    )
    assert (
        "Статус проверки «Выбросы» отчитан модулем «Предобработка»: "
        "есть замечания." in md
    )


# ── Пр-4 (закрытие находки R4 сертификации PROGR-17): персистентность ──


def test_preprocessing_checks_report_persists_through_store_save(monkeypatch):
    """Находка R4 акта PROGR-17-CERT (мутант BM-H: снятие store.save
    выжило в memory-бэкенде): save() -- носитель персистентности отчёта,
    контракт SessionStore «после мутации -- обязательно save()»
    (apps/api/upload_common.py). В memory-бэкенде save() ненаблюдаем
    (ссылка на session живёт в процессе, мутации видимы по алиасингу),
    поэтому проверка идёт через НАСТОЯЩУЮ границу сериализации:
    RedisSessionStore на fakeredis (паттерн test_session_store.py).
    Отчёт обязан пережить перечитывание из store: 10 событий слоя 1 и
    seeded run_id -- в сериализованном документе, а не только в памяти
    процесса; снятие store.save оставляет документ в состоянии НА момент
    upload -- без событий отчёта (RED на мутанте)."""
    fakeredis = pytest.importorskip("fakeredis")
    from apps.api import session_store as session_store_module
    from apps.api.session_store import RedisSessionStore

    fake_server = fakeredis.FakeServer()
    store = RedisSessionStore(
        client=fakeredis.FakeStrictRedis(server=fake_server), ttl_seconds=3600
    )
    # Эндпоинт берёт store через get_session_store() -- singleton модуля;
    # подменяем его на Redis-бэкенд (monkeypatch откатит после теста).
    monkeypatch.setattr(session_store_module, "_store", store)

    _upload()
    reported = client.post(
        "/v1/progress/preprocessing-checks",
        json={"checks": _full_checks_map("done")},
    )
    assert reported.status_code == 200, reported.text
    run_id = reported.json()["run_id"]
    assert run_id.startswith("RUN-")

    # ПЕРЕзачитать из store -- json.dumps -> redis -> json.loads:
    # объект НЕ тот, что мутировал эндпоинт (свежая десериализация).
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    reread = store.get(session_id)
    assert reread is not None, (
        "сессия отсутствует в store после отчёта -- save() не записал "
        "документ (персистентность отчёта нарушена)"
    )
    persisted = [
        event
        for event in reread.pipeline_trace
        if event["event_type"] == "preprocessing_check_status"
    ]
    assert len(persisted) == 10, (
        "в сериализованном документе нет 10 событий отчёта -- изменения "
        "сессии не пережили границу сериализации (BM-H: store.save снят)"
    )
    by_node = {event["node_id"]: event for event in persisted}
    for check_id in EXPECTED_CHECK_IDS:
        assert by_node[check_id]["payload"]["status"] == "done"
        assert by_node[check_id]["stage"] == "preprocessing"
    # Seeded run_id тоже обязан пережить перечитывание.
    assert reread.run_id == run_id
