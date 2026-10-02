# tests/api/test_progress_progr13c.py
"""Task PROGR-13-C (граница PROGR-13-B, осознанная граница из записи
worklog8.md) -- стадия run-level событий (run_paused/run_resumed/
checkpoint_saved) выводится из фактов решения единого движка, а не из
хвоста трассы.

КОРЕНЬ. stage_for_run_level_event (apps/api/research_runs.py) брала
events[-1].stage -- последними событиями трассы регулярно становятся
события УРОВНЯ СТАДИИ (node_id=None): target_column_changed сеется
авто-POST хука useTargetColumn на вкладке «Загрузка» со
stage="validation", passport_captured -- фиксация снимка,
mode_changed/run_* -- служебные. Штамп run-события уводился на стадию,
куда аналитик не заходил: «Пауза» после загрузки датасета попадала в
корпус слоя 2 как пауза НА СТАДИИ ВАЛИДАЦИИ -- тот же корень, что у
дефекта 2 Наставника (исправлен в PROGR-13-B1 функцией
derive_last_active_stage), только у атрибуции run-событий.

ПРАВИЛО (C): стадия run-события -- стадия последнего ФАКТА РЕШЕНИЯ:
событие, чей статус выводится каноническим гейтом движка
(resolve_event_status -- ЕДИНСТВЕННАЯ точка решения «узловой ли это
факт», PROGR-13-A4: карта EVENT_NODE_STATUS либо payload-статус из
PAYLOAD_STATUS_EVENT_TYPES), а его стадия известна графу
(STAGE_KEYS == KNOWN_STAGES -- import-инвариант test_pipeline_graph).
Гейт ПО ТИПУ, без требования узла: атрибутируется СТАДИЯ, а не узел --
сертифицированный контракт E6 (PROGR-5-CERT): backtest_run с
node_id=None -> "modeling" -- сохраняется дословно. Пустая трасса /
только stage-level события -- честный fallback "upload" (происхождение
запуска), не выдуманная стадия.

ЦИКЛ. Верхнеуровневый импорт движка в research_runs создаёт цикл
research_runs -> node_status -> pipeline_graph -> routers.session ->
research_runs (подтверждён эмпирически в задаче); разрыв -- ленивый
импорт внутри функции (прецедент модуля: modeling_session.py,
forecasting_session.py). Чистая часть вывода живёт в движке
(node_status.derive_last_decision_stage) -- research_runs не заводит
вторую реализацию гейта.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
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
    return (base + timedelta(seconds=seconds)).isoformat()


def _event(stage: str, node_id: str | None, event_type: str, ts: float) -> dict:
    """Stored-событие канона §4.1 (8 полей + legacy-алиас timestamp)."""
    iso = _iso(ts)
    return {
        "event_id": f"ev-{iso}",
        "run_id": "RUN-C0000001",
        "ts": iso,
        "stage": stage,
        "node_id": node_id,
        "event_type": event_type,
        "payload": {},
        "actor": "user",
        "timestamp": iso,
    }


# ── Чистый движок: derive_last_decision_stage ─────────────────────────


def test_empty_trace_defaults_to_upload():
    """Пустая трасса -- честный fallback "upload" (происхождение запуска),
    не выдуманная стадия (тот же контракт, что у derive_last_active_stage
    и certified E6: пустая трасса -> upload)."""
    from app.core.node_status import derive_last_decision_stage

    assert derive_last_decision_stage([]) == "upload"


def test_stage_level_only_defaults_to_upload():
    """Трасса из ТОЛЬКО stage-level событий (node_id=None, не факты
    решения) -- фазу не двигает: fallback "upload". Именно этот случай
    делал «Паузу после загрузки» паузой на Валидации."""
    from app.core.node_status import derive_last_decision_stage

    events = [
        _event("validation", None, "target_column_changed", 1),
        _event("eda", None, "mode_changed", 2),
        _event("upload", None, "passport_captured", 3),
    ]
    assert derive_last_decision_stage(events) == "upload"


def test_last_decision_fact_wins():
    """Хронология дописывания: последний факт решения выигрывает
    (тот же контракт, что у derive_node_statuses/derive_last_active_stage)."""
    from app.core.node_status import derive_last_decision_stage

    events = [
        _event("upload", "overview", "upload_completed", 1),
        _event("validation", "missing_values", "correction_applied", 2),
    ]
    assert derive_last_decision_stage(events) == "validation"


def test_stage_level_tail_does_not_shift_stage():
    """Канонический сценарий дефекта: узловой факт загрузки, ЗАТЕМ
    stage-level target_column_changed (сеется авто-POST хука
    useTargetColumn на вкладке «Загрузка») -- стадия остаётся upload,
    а не validation (до исправления штамп уводило на хвост трассы)."""
    from app.core.node_status import derive_last_decision_stage

    events = [
        _event("upload", "overview", "upload_completed", 1),
        _event("validation", None, "target_column_changed", 2),
    ]
    assert derive_last_decision_stage(events) == "upload"


def test_nodeless_decision_fact_counts_by_type():
    """Сертифицированный контракт E6 (PROGR-5-CERT), дословно: факт
    решения по ТИПУ без узла (backtest_run, node_id=None) атрибутирует
    СТАДИЮ modeling. Гейт -- по типу (resolve_event_status), без
    требования узла: атрибутируется стадия, а не узел."""
    from app.core.node_status import derive_last_decision_stage

    events = [
        _event("upload", "overview", "upload_completed", 1),
        _event("modeling", None, "backtest_run", 2),
    ]
    assert derive_last_decision_stage(events) == "modeling"


def test_forecasting_nodeless_fact_counts():
    """События Прогнозирования слоя 2 (node_id=None, стадия forecasting)
    -- факты решения: штамп run-события после прогноза -- forecasting."""
    from app.core.node_status import derive_last_decision_stage

    events = [
        _event("upload", "overview", "upload_completed", 1),
        _event("forecasting", None, "forecast_generated", 2),
    ]
    assert derive_last_decision_stage(events) == "forecasting"


def test_payload_status_type_counts():
    """Payload-статусные типы (PROGR-13-A4: upload_stop_status) -- тоже
    факты решения для атрибуции стадии (отчёт остановок модулем
    «Загрузка» держит штамп run-события на upload)."""
    from app.core.node_status import derive_last_decision_stage

    event = _event("upload", "structure", "upload_stop_status", 1)
    event["payload"] = {"status": "warning"}
    assert derive_last_decision_stage([event]) == "upload"


def test_unknown_stage_on_fact_skipped():
    """Факт решения с НЕИЗВЕСТНОЙ стадией не может атрибутировать стадию
    (журнал -- R3: мусор хранится, но штамп не уводит); выигрывает
    последний факт с известной стадией; только мусор -- fallback."""
    from app.core.node_status import derive_last_decision_stage

    events = [
        _event("upload", "overview", "upload_completed", 1),
        _event("bogus_stage", "backtest", "backtest_run", 2),
    ]
    assert derive_last_decision_stage(events) == "upload"

    only_garbage = [_event("bogus_stage", "backtest", "backtest_run", 1)]
    assert derive_last_decision_stage(only_garbage) == "upload"


def test_run_level_events_do_not_shift_stage():
    """Сами run-события (run_paused/run_resumed/checkpoint_saved) -- не
    факты решения: серия пауза/возобновление/чекпоинт не «держит» и не
    двигает стадию -- следующий штамп снова выводится из последнего
    факта (до исправления хвост трассы из run_* воспроизводил их
    стадию дальше по трассе)."""
    from app.core.node_status import derive_last_decision_stage

    events = [
        _event("validation", "missing_values", "correction_applied", 1),
        _event("upload", None, "run_paused", 2),
        _event("upload", None, "run_resumed", 3),
        _event("preprocessing", None, "checkpoint_saved", 4),
    ]
    assert derive_last_decision_stage(events) == "validation"


def test_legacy_node_id_does_not_block_stage():
    """Исторический корпус слоя 2 (node_id="structure_confirmed", B3):
    гейт атрибуции -- ПО ТИПУ, узел не требуется -- стадия legacy-факта
    считается без нормализации узла (нормализация ортогональна)."""
    from app.core.node_status import derive_last_decision_stage

    events = [
        _event("upload", "structure_confirmed", "upload_completed", 1),
        _event("validation", None, "target_column_changed", 2),
    ]
    assert derive_last_decision_stage(events) == "upload"


# ── stage_for_run_level_event (research_runs) -- публичный контракт ──


def _own_run(run_id: str):
    from apps.api import research_runs
    from apps.api.research_runs import ResearchRun

    store = research_runs.get_research_run_store()
    store.upsert_run(ResearchRun(run_id=run_id, status="active"))
    return store


def test_stage_for_run_level_event_empty_trace_upload():
    """Публичный контракт функции (certified E6): пустая трасса ->
    "upload"."""
    from apps.api.research_runs import stage_for_run_level_event

    store = _own_run("RUN-C0000011")
    assert stage_for_run_level_event(store, "RUN-C0000011") == "upload"


def test_stage_for_run_level_event_nodeless_decision_fact():
    """Сценарий certified E6 дословно: после append backtest_run
    (stage="modeling", node_id=None) функция обязана вернуть "modeling".
    До исправления этот контракт выполнялся хвостом трассы, ПОСЛЕ --
    выполняется фактом решения (E6 остаётся зелёным на новой
    реализации -- датированное свидетельство приёмки не ломается)."""
    from apps.api.research_runs import stage_for_run_level_event
    from apps.api.trace_events import make_trace_event

    store = _own_run("RUN-C0000012")
    store.append_event(
        "RUN-C0000012",
        make_trace_event(
            "backtest_run", stage="modeling", node_id=None,
            run_id="RUN-C0000012",
        ),
    )
    assert stage_for_run_level_event(store, "RUN-C0000012") == "modeling"


def test_stage_for_run_level_event_ignores_stage_level_tail():
    """Исправленный корень: трасса [upload_completed(upload/overview),
    target_column_changed(validation, node_id=None)] -- стадия для
    run-события upload, а не хвост validation (дефект 2 у атрибуции
    run-событий)."""
    from apps.api.research_runs import stage_for_run_level_event
    from apps.api.trace_events import make_trace_event

    store = _own_run("RUN-C0000013")
    store.append_event(
        "RUN-C0000013",
        make_trace_event(
            "upload_completed", stage="upload", node_id="overview",
            run_id="RUN-C0000013",
        ),
    )
    store.append_event(
        "RUN-C0000013",
        make_trace_event(
            "target_column_changed", stage="validation", node_id=None,
            run_id="RUN-C0000013",
        ),
    )
    assert stage_for_run_level_event(store, "RUN-C0000013") == "upload"


# ── HTTP-интеграция: штампы run-эндпоинтов слоя 2 ─────────────────────


def _demo_run_with_stage_level_tail():
    """Сценарий дефекта по шагам фронтенда: демо-датасет (hook сеет
    upload_completed на upload/overview -- узловой факт), затем АВТО-POST
    /target-column хука useTargetColumn (stage-level
    target_column_changed, stage="validation" -- аналитик на Валидацию
    НЕ заходил). Возвращает (run_id, store)."""
    client.post("/v1/session/demo")
    client.post("/v1/session/target-column", json={"column": "sales"})

    from apps.api import research_runs

    run = research_runs.get_research_run_store().list_runs()[0]
    return run.run_id, research_runs.get_research_run_store()


def test_run_paused_stage_is_last_decision_fact():
    """«Пауза» после загрузки -- пауза на СТАДИИ ЗАГРУЗКИ (последний факт
    решения upload_completed), а не на Валидации: хвост трассы
    (target_column_changed от авто-POST хука) штамп не уводит. До
    исправления корпус слоя 2 хранил run_paused.stage="validation" --
    ложь о маршруте аналитика (дефект 2 у атрибуции run-событий)."""
    run_id, store = _demo_run_with_stage_level_tail()

    resp = client.post(f"/v1/progress/runs/{run_id}/pause")
    assert resp.status_code == 200, resp.text

    paused = store.list_events(run_id)[-1]
    assert paused.event_type == "run_paused"
    assert paused.stage == "upload", (
        "штамп run_paused выведен из хвоста трассы "
        "(stage-level target_column_changed), а не из последнего факта "
        "решения: корпус слоя 2 хранит паузу на Валидации, куда аналитик "
        "не заходил"
    )


def test_run_resumed_stage_is_last_decision_fact():
    """«Возобновить» -- тот же корень: run_resumed штампуется по последнему
    факту решения, а не по хвосту (который к моменту resume состоит из
    upload_completed -> target_column_changed -> run_paused)."""
    run_id, store = _demo_run_with_stage_level_tail()

    assert client.post(f"/v1/progress/runs/{run_id}/pause").status_code == 200
    resp = client.post(f"/v1/progress/runs/{run_id}/resume")
    assert resp.status_code == 200, resp.text

    resumed = store.list_events(run_id)[-1]
    assert resumed.event_type == "run_resumed"
    assert resumed.stage == "upload", (
        "штамп run_resumed выведен из хвоста трассы (включая "
        "run_paused-событие -- run_* не факты решения), а не из "
        "последнего факта решения"
    )


def test_checkpoint_saved_stage_is_last_decision_fact():
    """Чекпоинт, сохранённый на вкладке «Загрузка», -- checkpoint_saved
    на стадии upload: ссылка (event_id) указывает на событие загрузки,
    и штамп чекпоинта не уводит stage-level хвост трассы."""
    run_id, store = _demo_run_with_stage_level_tail()
    upload_event = next(
        event for event in store.list_events(run_id)
        if event.event_type == "upload_completed"
    )

    resp = client.post(
        f"/v1/progress/runs/{run_id}/checkpoints",
        json={"event_id": upload_event.event_id, "label": "перед Валидацией"},
    )
    assert resp.status_code == 201, resp.text

    saved = store.list_events(run_id)[-1]
    assert saved.event_type == "checkpoint_saved"
    assert saved.stage == "upload", (
        "штамп checkpoint_saved выведен из хвоста трассы "
        "(stage-level target_column_changed), а не из последнего факта "
        "решения"
    )


def test_new_decision_fact_after_pause_moves_stamp():
    """Последний факт выигрывает: факт решения, дописанный между паузой и
    возобновлением (легальный писатель слоя 2 -- _append_event
    Прогнозирования), двигает штамп run_resumed; стадия run_paused-события
    штамп «не держит» (run_* -- не факты)."""
    run_id, store = _demo_run_with_stage_level_tail()
    from apps.api.trace_events import make_trace_event

    assert client.post(f"/v1/progress/runs/{run_id}/pause").status_code == 200
    store.append_event(
        run_id,
        make_trace_event(
            "correction_applied", stage="validation",
            node_id="missing_values", run_id=run_id,
        ),
    )
    assert client.post(f"/v1/progress/runs/{run_id}/resume").status_code == 200

    resumed = store.list_events(run_id)[-1]
    assert resumed.event_type == "run_resumed"
    assert resumed.stage == "validation"


def test_run_level_stamp_agrees_with_mentor_phase():
    """Единство движка (решение B1/C): после одного и того же сценария
    фаза Наставника (derive_last_active_stage) и штамп run-события
    (derive_last_decision_stage) называют ОДНУ стадию -- на реальных
    корпусах гейты совпадают (все факты хука несут узлы)."""
    run_id, _store = _demo_run_with_stage_level_tail()

    resp = client.post(f"/v1/progress/runs/{run_id}/pause")
    assert resp.status_code == 200, resp.text
    paused_stage = resp.json()["event"]["stage"]

    mentor = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
    assert mentor.status_code == 200, mentor.text
    assert mentor.json()["last_active_stage"] == paused_stage == "upload"
