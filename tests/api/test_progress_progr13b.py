# tests/api/test_progress_progr13b.py
"""Task PROGR-13-B (компактная, backend) -- контракты исправлений
дефекта 2 панели «Прогресс» + исключение главного риска плана
(постановка тимлида, 2026-10-02: «без нормализации старого node_id в
Postgres-корпусе панель и admin-аналитика потеряют историю запусков»).

B1. last_active_stage Наставника -- стадия последнего УЗЛОВОГО факта
    решения (EVENT_NODE_STATUS + resolve_node_id единого движка),
    fallback "upload". События УРОВНЯ СТАДИИ (node_id=None:
    target_column_changed, passport_captured, mode_changed, run_*)
    фазу НЕ двигают: target_column_changed мульти-страничен (сеется
    автовыбором хука useTargetColumn на вкладке «Загрузка»),
    passport_captured -- фиксация снимка, не переход на вкладку.
    Корень дефекта 2 @2d2d05c: get_mentor_next_step брал
    events[-1].stage -- последними событиями трассы становятся именно
    stage-level события, и Наставник называл «Валидацию», куда
    аналитик не заходил.

B2. Мисаттрибуция паспортов: маршрут /v1/session/dataset/passport/{stage}
    трассируется со стадией ПО ТОЧКЕ ПАСПОРТА (значение параметра пути):
    start->upload (точка фиксируется на вкладке «Загрузка»),
    validation->validation, exit->eda, modeling_entry->modeling.
    Неизвестная точка -- ни одной строки таблицы -> событие не пишется
    (fail-closed; сам эндпоинт отвечает 404 по PASSPORT_STAGES).
    Реестр STAGE_EVENT_TYPES расширен паспортным типом на
    upload/validation/modeling (паттерн модуля: «сторонние этапы
    регистрируются расширением реестра, а не обходом гейта»).

B3. ГЛАВНЫЙ РИСК ПЛАНА -- исторический корпус слоя 2 (Postgres,
    research_runs.trace_events) хранит node_id="structure_confirmed"
    у ВСЕХ upload-строк. После переименования узла в канонический
    "structure" (выравнивание с id остановки «Структура» модуля
    TsAnalysisUpload.tsx) старые строки корпуса обязаны СЧИТАТЬСЯ:
    нормализация legacy node_id на границе чтения единого движка
    (resolve_node_id -- единственная точка вывода узла: панель,
    Наставник, admin-аналитика, отчёт §5.4). Трасса -- журнал
    (R3 PROGR-1-CERT): записи корпуса не переписываются, нормализация
    -- только на чтении; без неё is_known_node-гейт движка молча
    отбрасывал бы узловые факты старых запусков -- панель показывала
    бы «Загрузка: не начато», Наставник и admin теряли историю.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.research_runs import ResearchRun
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

client = TestClient(app)


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
    base = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
    from datetime import timedelta

    return (base + timedelta(seconds=seconds)).isoformat()


def _event(stage: str, node_id: str | None, event_type: str, ts: str) -> dict:
    """Stored-событие канона §4.1 (8 полей + legacy-алиас timestamp)."""
    return {
        "event_id": f"ev-{ts}",
        "run_id": "RUN-LEGACY0001",
        "ts": ts,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": {},
        "actor": "user",
        "timestamp": ts,
    }


# ── B1: фаза Наставника -- по УЗЛОВЫМ фактам, не по хвосту трассы ────


def test_stage_level_events_do_not_move_phase():
    """События уровня стадии (node_id=None) фазу не двигают: хвост трассы
    -- target_column_changed/mode_changed/passport_captured/run_* -- не
    делает «текущим этапом» их стадию (дефект 2: авто-POST хука
    useTargetColumn сеет target_column_changed со stage="validation")."""
    from app.core.node_status import derive_last_active_stage

    events = [
        _event("upload", "structure", "upload_completed", _iso(1)),
        _event("validation", None, "target_column_changed", _iso(2)),
        _event("validation", None, "mode_changed", _iso(3)),
        _event("upload", None, "passport_captured", _iso(4)),
        _event("upload", None, "run_paused", _iso(5)),
    ]
    assert derive_last_active_stage(events) == "upload"


def test_last_node_level_fact_defines_phase():
    """Последний УЗЛОВОЙ факт решения определяет фазу: коррекция
    Валидации после загрузки -> этап «Валидация»; последующий
    stage-level паспорт фазу не возвращает и не двигает."""
    from app.core.node_status import derive_last_active_stage

    events = [
        _event("upload", "structure", "upload_completed", _iso(1)),
        _event("validation", "data_types", "correction_applied", _iso(2)),
        _event("eda", None, "passport_captured", _iso(3)),
    ]
    assert derive_last_active_stage(events) == "validation"


def test_forecasting_fact_resolved_from_event_type():
    """Forecasting-строки корпуса (node_id=None, узел == тип события,
    контракт PROGR-1) -- узловые факты: фаза «Прогнозирование»."""
    from app.core.node_status import derive_last_active_stage

    events = [
        _event("upload", "structure", "upload_completed", _iso(1)),
        _event("modeling", "backtest", "backtest_run", _iso(2)),
        _event("forecasting", None, "forecast_generated", _iso(3)),
    ]
    assert derive_last_active_stage(events) == "forecasting"


def test_fallback_upload_on_empty_or_stage_level_trace():
    """Пустая трасса / только stage-level события -- честный fallback
    "upload" (происхождение запуска), а не выдуманная стадия."""
    from app.core.node_status import derive_last_active_stage

    assert derive_last_active_stage([]) == "upload"
    assert derive_last_active_stage(
        [_event("validation", None, "target_column_changed", _iso(1))]
    ) == "upload"


def test_legacy_upload_row_counts_for_phase():
    """Старая строка корпуса (node_id="structure_confirmed") -- валидный
    узловой факт стадии upload: БЕЗ нормализации derive_last_active_stage
    пропустил бы её (is_known_node-гейт) и потерял бы узловую историю
    запуска."""
    from app.core.node_status import derive_last_active_stage

    events = [
        _event("upload", "structure_confirmed", "upload_completed", _iso(1)),
        _event("eda", "correlation", "profile_viewed", _iso(2)),
    ]
    assert derive_last_active_stage(events) == "eda"

    only_legacy = [
        _event("upload", "structure_confirmed", "upload_completed", _iso(1))
    ]
    assert derive_last_active_stage(only_legacy) == "upload"


# ── B3: нормализация legacy node_id на границе чтения движка ─────────


def test_normalize_legacy_node_id_contract():
    """Контракт нормализации: legacy -> канонический id; канонический
    проходит насквозь (идемпотентность); неизвестный -- как есть
    (дальнейший is_known_node-гейт решает); маппинг ограничен СВОЕЙ
    стадией (cross-stage перезапись запрещена); None -- None."""
    from app.core.node_status import normalize_legacy_node_id

    assert normalize_legacy_node_id("upload", "structure_confirmed") == "structure"
    assert normalize_legacy_node_id("upload", "structure") == "structure"
    assert normalize_legacy_node_id("upload", "no_such_node") == "no_such_node"
    # чужая стадия -- маппинга нет, значение не переписывается
    assert (
        normalize_legacy_node_id("validation", "structure_confirmed")
        == "structure_confirmed"
    )
    assert normalize_legacy_node_id("upload", None) is None


def test_engine_statuses_normalize_legacy_corpus_row():
    """Панель/Наставник/admin читают статусы одним движком: строка
    корпуса со старым node_id даёт Канонический ключ "upload/structure"
    -- фантомного "upload/structure_confirmed" в выводе нет."""
    from app.core.node_status import derive_node_statuses

    events = [
        _event("upload", "structure_confirmed", "upload_completed", _iso(1)),
        _event("upload", "structure", "upload_completed", _iso(2)),
    ]
    statuses = derive_node_statuses(events)
    assert statuses == {"upload/structure": "done"}


def test_admin_analytics_counts_legacy_rows_without_phantoms():
    """admin-аналитика (тот же движок, PROGR-10) не теряет историю
    старых запусков: legacy-строки участвуют в выводе статусов под
    каноническим ключом, фантомных узлов в топе проблем нет."""
    from app.core.admin_analytics import build_admin_overview
    from app.core.node_status import derive_node_statuses

    events = [
        # исторический корпус: upload со старым node_id
        _event("upload", "structure_confirmed", "upload_completed", _iso(1)),
        # старая warning-строка (юридический журнал-факт прошлого)
        _event(
            "validation", "ranges", "correction_previewed", _iso(2),
        ),
    ]
    events[1] = {**events[1], "payload": {"total_violations": 3}}
    statuses = derive_node_statuses(events)
    assert statuses["upload/structure"] == "done"
    assert statuses["validation/ranges"] == "warning"

    overview = build_admin_overview(
        runs=[ResearchRun(
            run_id="RUN-LEGACY0001", session_id="s1",
            dataset_fingerprint="", dataset_name="old.csv",
        ).to_dict()],
        events_by_run={"RUN-LEGACY0001": events},
        observations=[],
        now=datetime(2026, 10, 2, 13, 0, 0, tzinfo=timezone.utc),
    )
    node_keys = {(n.stage, n.node_id) for n in overview.top_problem_nodes}
    assert ("validation", "ranges") in node_keys
    assert ("upload", "structure_confirmed") not in node_keys  # фантома нет


# ── B2: точка паспорта -> стадия события (TRACE_ROUTES) ──────────────


@pytest.mark.parametrize(
    ("point", "stage"),
    [
        ("start", "upload"),
        ("validation", "validation"),
        ("exit", "eda"),
        ("modeling_entry", "modeling"),
    ],
)
def test_trace_routes_map_passport_point_to_stage(point, stage):
    """B2: каждая точка паспорта трассируется со СВОЕЙ стадией (значение
    параметра пути), payload несёт точку как факт."""
    from apps.api.trace_hook import resolve_trace_route

    spec = resolve_trace_route("POST", f"/v1/session/dataset/passport/{point}")
    assert spec is not None, f"точка паспорта {point!r} не трассируется"
    assert (spec.stage, spec.node_id, spec.event_type) == (
        stage, None, "passport_captured",
    )


def test_unknown_passport_point_fail_closed():
    """Неизвестная точка паспорта -- ни одной строки таблицы: событие
    не пишется (fail-closed, паттерн таблицы трассы)."""
    from apps.api.trace_hook import resolve_trace_route

    assert resolve_trace_route(
        "POST", "/v1/session/dataset/passport/unknown_point"
    ) is None


@pytest.mark.parametrize("stage", ["upload", "validation", "modeling"])
def test_passport_captured_registered_on_stage(stage):
    """Реестр STAGE_EVENT_TYPES расширен паспортным типом (паттерн
    модуля trace_events: сторонние этапы -- расширением реестра, не
    обходом гейта); на eda тип был и остаётся."""
    from apps.api.trace_events import make_trace_event

    event = make_trace_event("passport_captured", stage=stage, run_id="R")
    assert event.stage == stage


# ── API: панель и Наставник на корпусе со старыми node_id ────────────


def _seed_run(store, run_id: str) -> None:
    store.upsert_run(
        ResearchRun(
            run_id=run_id,
            session_id="sess-legacy",
            dataset_fingerprint="fp-legacy",
            dataset_name="forecast_monitor_synthetic_n150.csv",
        )
    )


def test_mentor_phase_for_legacy_corpus_run():
    """Запуск из исторического корпуса (слой 2, node_id
    "structure_confirmed"): Наставник обязан видеть узловой факт
    загрузки. После добавления modeling-факта фаза -- «Моделирование»:
    legacy-строка не ломает более поздние факты."""
    from apps.api import research_runs
    from apps.api.trace_events import make_trace_event

    store = research_runs.get_research_run_store()
    _seed_run(store, "RUN-LEGACY0001")
    store.append_event(
        "RUN-LEGACY0001",
        make_trace_event(
            "upload_completed", stage="upload",
            node_id="structure_confirmed", run_id="RUN-LEGACY0001",
        ),
    )

    response = client.get("/v1/progress/runs/RUN-LEGACY0001/mentor/next-step")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["last_active_stage"] == "upload"
    assert "Загрузка" in data["phase_text"]

    store.append_event(
        "RUN-LEGACY0001",
        make_trace_event(
            "backtest_run", stage="modeling", node_id="backtest",
            run_id="RUN-LEGACY0001",
        ),
    )
    data = client.get(
        "/v1/progress/runs/RUN-LEGACY0001/mentor/next-step"
    ).json()
    assert data["last_active_stage"] == "modeling"


def test_restore_phase_from_node_facts_not_stage_level_tail():
    """PROGR-13-B1 (restore, §5.3): фаза восстановленной сессии -- по
    узловым фактам, не по хвосту трассы: последним событием слоя 2
    является target_column_changed (stage="validation", сеется
    авто-POST хука useTargetColumn на вкладке «Загрузка») -- до
    исправления restore делал «Валидацию» текущим этапом и клал
    run_resumed на стадию validation."""
    client.post("/v1/session/demo")
    # Дословно fetchAndMaybeAutoSelect (useTargetColumn.ts): молчивый
    # POST suggested -- событие уровня стадии stage="validation".
    client.post("/v1/session/target-column", json={"column": "sales"})

    from apps.api import research_runs

    run = research_runs.get_research_run_store().list_runs()[0]

    # «Другое устройство»: чистый клиент без cookie (§5.3).
    fresh = TestClient(app)
    resp = fresh.get(f"/v1/progress/runs/{run.run_id}/restore")
    assert resp.status_code == 200, resp.text

    new_session_id = fresh.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(new_session_id)
    assert session is not None
    assert session.last_active_stage == "upload", (
        "фаза восстановленной сессии выведена из stage-level хвоста "
        "(target_column_changed), а не из узловых фактов запуска"
    )

    store = research_runs.get_research_run_store()
    resumed = store.list_events(run.run_id)[-1]
    assert resumed.event_type == "run_resumed"
    assert resumed.stage == "upload"


def test_panel_keeps_history_for_legacy_layer1_corpus():
    """Слой 1 старой сессии (stored-словари с node_id
    "structure_confirmed"): /trace обязан показать узел "structure"
    done -- факт старого запуска сохранён, фантомного ключа нет.
    Без нормализации панель показывала бы «не начато» -- потеря
    истории запуска. PROGR-13-A: реестр Загрузки -- 5 остановок,
    карточка честно «в работе» 1/5 (легенда-факт -- один из пяти
    узлов), суть теста -- СОХРАННОСТЬ истории -- не меняется."""
    response = client.post("/v1/session/demo")
    assert response.status_code == 200, response.text
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id

    store = get_session_store()
    session = store.get(session_id)
    assert session is not None
    # имитация старого корпуса: переписываем stored-словари на legacy id
    for item in session.pipeline_trace:
        if item.get("event_type") == "upload_completed":
            item["node_id"] = "structure_confirmed"
    store.save(session)

    trace = client.get("/v1/progress/trace").json()
    statuses = trace["node_statuses"]
    assert statuses.get("upload/structure") == "done"
    assert "upload/structure_confirmed" not in statuses
    upload_card = next(
        s for s in trace["stages"] if s["stage"] == "upload"
    )
    assert upload_card["fold"] == "attention"
    assert upload_card["done_count"] == 1
    assert upload_card["total_nodes"] == 5
