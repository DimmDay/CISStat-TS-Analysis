# tests/api/test_progress_defects_progr13.py
"""Task PROGR-13: дефекты панели «Прогресс», воспроизведённые на
forecast_monitor_synthetic_n150.csv (постановка тимлида, 2026-10-02).

Сценарий (дословно):
  1. Загружаю датасет forecast_monitor_synthetic_n150.csv; модуль
     «Загрузка» показывает Превью/График/Распределение зелёными,
     Структуру и Качество -- жёлтыми. Фиксирую свойства в Паспорте.
  2. Открываю «Прогресс»: стадия «Загрузка» содержит ТОЛЬКО остановку
     «Структура данных», помеченную ЗЕЛЁНОЙ (в модуле -- ЖЁЛТАЯ);
     остальные остановки в прогрессе отсутствуют.  [ДЕФЕКТ 1]
  3. «Наставник» сообщает «Идёт этап «Валидация»», хотя аналитик НЕ
     открывал вкладку «Валидация».                            [ДЕФЕКТ 2]

Корни (верифицировано по коду @2d2d05c, scripts/progr13_repro_defects.py):
  * ДЕФЕКТ 1а: pipeline_graph.UPLOAD_STAGE_IDS = ("structure_confirmed",)
    -- реестр графа не отражает фактический степпер модуля
    TsAnalysisUpload.tsx::STOPS (5 остановок: overview/chart/distribution/
    structure/quality; спека §2 «нет CHECKS-массива» устарела);
  * ДЕФЕКТ 1б: upload_completed (факт ЗАГРУЗКИ ФАЙЛА) маппится движком
    в done узла structure_confirmed -- статус «зелёная Структура»
    противоречит факту модуля (confidence<70 -> warning);
  * ДЕФЕКТ 2: get_mentor_next_step выводит last_active_stage из
    events[-1].stage. Последними событиями трассы становятся события
    УРОВНЯ СТАДИИ (node_id=None), засеянные ДЕЙСТВИЯМИ НА ВКЛАДКЕ
    «ЗАГРУЗКА»: авто-POST /target-column хука useTargetColumn
    (stage="validation") и POST /dataset/passport/start
    (stage="eda" -- МИСАТРИБУЦИЯ: паспорты точки start фиксируются
    на вкладке «Загрузка»). Пользователь ни одну из этих вкладок не
    открывал.

Тесты фиксируют КОНТРАКТ корректного поведения (RED до исправления).
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.core import node_status
from app.core.pipeline_graph import STAGE_NODES
from apps.api.main import app
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


def _auto_target_column() -> None:
    """Дословно fetchAndMaybeAutoSelect (useTargetColumn.ts): GET ->
    target_column null, suggested есть -> МОЛЧИВЫЙ POST suggested."""
    current = client.get("/v1/session/target-column").json()
    if current.get("target_column") is None and current.get("suggested_column"):
        posted = client.post(
            "/v1/session/target-column", json={"column": current["suggested_column"]}
        )
        assert posted.status_code == 200, posted.text


def _confirm_date_and_passport() -> None:
    """Остановка «Структура» (подтверждение даты) + «Зафиксировать» в Паспорте."""
    date_resp = client.post("/v1/session/date-column", json={"column": "date"})
    assert date_resp.status_code == 200, date_resp.text
    capture = client.post("/v1/session/dataset/passport/start")
    assert capture.status_code == 200, capture.text


def _trace() -> dict:
    response = client.get("/v1/progress/trace")
    assert response.status_code == 200, response.text
    return response.json()


# ── ДЕФЕКТ 1а: граф стадии «Загрузка» не отражает степпер модуля ────


def test_upload_stage_graph_covers_all_module_stops():
    """Спека §2 «не изобретает список -- агрегирует существующий реестр»:
    реестр модуля «Загрузка» -- TsAnalysisUpload.tsx::STOPS, ПЯТЬ остановок
    (overview/chart/distribution/structure/quality). Граф обязан их
    отражать, иначе панель «Прогресс» дезинформирует (1/5 остановок)."""
    assert STAGE_NODES["upload"] == (
        "overview", "chart", "distribution", "structure", "quality",
    )


def test_frontend_progress_copy_syncs_upload_nodes():
    """Зеркало графа на фронте (packages/ui/lib/progress.ts) обязано
    показывать те же 5 остановок стадии «Загрузка» (sync-контур
    test_progress_panel)."""
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "packages" / "ui" / "lib" / "progress.ts"
    ).read_text(encoding="utf-8")
    match = re.search(r'"upload":\s*\[([^\]]*)\]', source)
    assert match, "PROGRESS_STAGE_NODES.upload не найден в progress.ts"
    ids = re.findall(r'"([a-z_]+)"', match.group(1))
    assert ids == [
        "overview", "chart", "distribution", "structure", "quality",
    ]


# ── ДЕФЕКТ 1б: upload_completed красит «Структуру» в зелёный ─────────


def test_upload_completed_alone_does_not_paint_structure_done():
    """upload_completed -- факт чтения ФАЙЛА, не факт подтверждения
    структуры: узел structure не может быть done до подтверждения
    аналитиком (в модуле остановка жёлтая при confidence<70).
    Превью датасета при этом честно зелёное (файл прочитан)."""
    _upload()
    trace = _trace()
    statuses = trace["node_statuses"]
    structure_status = statuses.get("upload/structure", statuses.get(
        "upload/structure_confirmed", "pending"
    ))
    assert structure_status != "done", (
        "«Структура» зелёная в Прогрессе без подтверждения аналитиком -- "
        "расхождение с модулем (жёлтая при confidence<70)"
    )


def test_upload_completed_paints_overview_done():
    """Зелёная карточка Превью -- честный факт upload_completed
    (файл прочитан, превью доступно): фиксируем, что исправление
    маппинга не потеряет зелёную «Загрузку» целиком."""
    _upload()
    trace = _trace()
    assert trace["node_statuses"].get("upload/overview") == "done"


# ── ДЕФЕКТ 2: Наставник называет стадию, где аналитик не был ─────────


def test_mentor_phase_stays_upload_after_upload_page_actions():
    """Полный сценарий пользователя: загрузка + автовыбор признака
    (АВТО-POST хука, стадия события validation) + подтверждение даты +
    фиксация паспорта start (событие с stage=eda). Аналитик НЕ покидал
    вкладку «Загрузка» -> Наставник обязан описывать этап «Загрузка»."""
    _upload()
    _auto_target_column()
    _confirm_date_and_passport()

    trace = _trace()
    run_id = trace.get("run_id")
    assert run_id, "run_id не зафиксирован"

    mentor = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step").json()
    assert mentor["last_active_stage"] == "upload", (
        f"Наставник называет этап {mentor['last_active_stage']!r}, "
        "хотя аналитик не покидал вкладку «Загрузка»: last_active_stage "
        "выводится из stage-level событий (target_column_changed / "
        "passport_captured), а не из фактов прохождения узлов"
    )
    assert "Загрузка" in mentor["phase_text"]


def test_mentor_phase_not_validation_without_passport():
    """Минимальный вариант: загрузка + автовыбор признака, Паспорт не
    фиксировался. Воспроизведение дословной жалобы тимлида: Наставник
    НЕ должен сообщать «Идёт этап «Валидация»»."""
    _upload()
    _auto_target_column()

    trace = _trace()
    run_id = trace.get("run_id")
    mentor = client.get(f"/v1/progress/runs/{run_id}/mentor/next-step").json()
    assert mentor["last_active_stage"] != "validation", (
        "target_column_changed (stage=validation) засеян авто-POST хука "
        "useTargetColumn на вкладке «Загрузка» -- Наставник называет "
        "«Валидацию», куда аналитик не заходил"
    )
    assert mentor["last_active_stage"] == "upload"


def test_passport_start_event_attributed_to_upload_stage():
    """Паспорт точки start фиксируется на вкладке «Загрузка»; событие
    passport_captured не может приписываться стадии eda -- это миса-
    трибуция, искажающая и трассу, и фазу Наставника, и отчёт §5.4."""
    _upload()
    _auto_target_column()
    _confirm_date_and_passport()

    trace = _trace()
    passport_events = [
        event for event in trace["events"]
        if event.get("event_type") == "passport_captured"
    ]
    assert passport_events, "passport_captured не засеян"
    assert passport_events[-1]["stage"] == "upload", (
        f"passport_captured(start) атрибутирован стадии "
        f"{passport_events[-1]['stage']!r} вместо upload"
    )


# ── ДЕФЕКТ 1 (полнота): остановки модуля в Прогрессе = фактам модуля ──


def test_upload_stop_facts_reach_panel_statuses():
    """После засева фактов остановок (контракт POST /v1/progress/upload-stops:
    фронтенд отчитывает stopStatus, вычисленный из ответа загрузки --
    прецедент §7.2 CorrectionOutcomeSummary) панель обязана показывать
    ТЕ ЖЕ статусы, что и модуль: quality=warning (счётчики проблем),
    structure=warning (confidence<70) -- зелёных «1/1» быть не может."""
    _upload()
    stops = {
        "overview": "done",
        "chart": "done",
        "distribution": "done",
        "structure": "warning",
        "quality": "warning",
    }
    reported = client.post("/v1/progress/upload-stops", json={"stops": stops})
    assert reported.status_code == 200, (
        "Не реализован контракт отчёта фактов остановок «Загрузки»: "
        f"HTTP {reported.status_code}"
    )

    trace = _trace()
    statuses = trace["node_statuses"]
    for node_id, expected in stops.items():
        assert statuses.get(f"upload/{node_id}") == expected, (
            f"upload/{node_id}: панель {statuses.get(f'upload/{node_id}')!r}, "
            f"модуль {expected!r} -- расхождение фактов"
        )
    upload_stage = next(s for s in trace["stages"] if s["stage"] == "upload")
    assert upload_stage["fold"] == "attention", (
        "При жёлтых «Структуре»/«Качестве» карточка стадии «Загрузка» "
        "не может быть зелёной (§12 п.10: любой warning делает карточку жёлтой)"
    )
