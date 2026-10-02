# tests/api/test_progress_progr13a.py
"""Task PROGR-13-A (полнота Загрузки, backend+frontend) -- контракты
закрытия дефекта 1 панели «Прогресс» (постановка тимлида, 2026-10-02:
«в «Прогрессе» -- только одна остановка «Структура данных», и цвет
противоречит модулю; как потом собирать полный report?»).

A1. Общий JSON shared/pipeline_nodes/upload_stops.json (§12 п.2, паттерн
    eda_checks.json): ЕДИНСТВЕННЫЙ источник 5 остановок «Загрузки» --
    его читают и TsAnalysisUpload.tsx (STOPS), и граф бэкенда
    (pipeline_graph.UPLOAD_STAGE_IDS). Вшитых копий id нет.

A2. Канонический id узла structure (PROGR-13-B) с ПОЛНЫМ реестром:
    legacy structure_confirmed корпуса слоя 2 нормализуется на границе
    чтения (LEGACY_NODE_IDS, resolve_node_id) -- история запусков
    сохраняется при 5-узловой Загрузке так же, как при 1-узловой.

A3. Разведение фактов: upload_completed (чтение ФАЙЛА) -> узел overview
    («Превью датасета»); подтверждение структуры аналитиком -- ОТДЕЛЬНОЕ
    событие structure_confirmed (POST /v1/session/date-column -> узел
    structure). Дефект 1б: зелёная «Структура» по факту чтения файла.

A4. Контракт POST /v1/progress/upload-stops (прецедент §7.2 --
    CorrectionOutcomeSummary строит клиент): модуль отчитывает снапшот
    stopStatus, факты пишутся СОБЫТИЯМИ upload_stop_status (статус в
    payload, whitelist CHECK_STATUS_VALUES), слой 1 + зеркало слоя 2.
    Валидация fail-closed: неизвестный узел / недопустимый статус /
    неполная карта -- 422 ДО первой записи (all-or-nothing).

A5. Потребители: отчёт §5.4 -- метки остановок из ОБЩЕГО реестра и
    человекочитаемые строки новых фактов; зеркало progress.ts --
    5 узлов + метки из того же JSON (sync-контур).
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.node_status import (
    derive_last_active_stage,
    derive_node_statuses,
    resolve_event_status,
)
from app.core.pipeline_graph import (
    STAGE_NODES,
    UPLOAD_STAGE_IDS,
    UPLOAD_STOP_DEFS,
    is_known_node,
)
from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

client = TestClient(app)

REPO_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_JSON_PATH = REPO_ROOT / "shared" / "pipeline_nodes" / "upload_stops.json"
UPLOAD_TSX_PATH = REPO_ROOT / "packages" / "ui" / "components" / "TsAnalysisUpload.tsx"
PROGRESS_TS_PATH = REPO_ROOT / "packages" / "ui" / "lib" / "progress.ts"

EXPECTED_STOP_IDS = ("overview", "chart", "distribution", "structure", "quality")


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
        "run_id": "RUN-PROGR13A01",
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


# ── A1: общий JSON -- единственный источник реестра остановок ────────


class TestUploadStopsSharedJson:
    def test_json_exists_with_five_expected_stops(self):
        raw = json.loads(UPLOAD_JSON_PATH.read_text(encoding="utf-8"))
        assert raw["stage"] == "upload"
        assert tuple(node["id"] for node in raw["nodes"]) == EXPECTED_STOP_IDS

    def test_graph_reads_ids_from_shared_json_not_hardcoded_copy(self):
        # §12 п.2 «не дублирует, а ссылается»: граф обязан читать ТОТ ЖЕ
        # файл, что и модуль; вшитой копии кортежа в Python быть не должно.
        raw = json.loads(UPLOAD_JSON_PATH.read_text(encoding="utf-8"))
        json_ids = tuple(node["id"] for node in raw["nodes"])
        assert UPLOAD_STAGE_IDS == json_ids == EXPECTED_STOP_IDS
        assert STAGE_NODES["upload"] == EXPECTED_STOP_IDS

    def test_upload_tsx_imports_shared_json(self):
        # Механизированный маркер синхронизации (паттерн
        # test_eda_tsx_imports_shared_json): в .tsx не остаётся вшитого
        # списка -- он импортирует общий JSON.
        src = UPLOAD_TSX_PATH.read_text(encoding="utf-8")
        assert "shared/pipeline_nodes/upload_stops.json" in src

    def test_progress_ts_uses_shared_json_for_labels(self):
        # Метки остановок -- из того же общего JSON (копии строк нет),
        # id -- текстовый sync-маркер (regex-контракт sync-теста).
        src = PROGRESS_TS_PATH.read_text(encoding="utf-8")
        assert "shared/pipeline_nodes/upload_stops.json" in src

    def test_stop_defs_expose_labels_from_json(self):
        by_id = {node["id"]: node for node in UPLOAD_STOP_DEFS}
        raw = json.loads(UPLOAD_JSON_PATH.read_text(encoding="utf-8"))
        assert len(UPLOAD_STOP_DEFS) == 5
        for node in raw["nodes"]:
            assert by_id[node["id"]]["label"] == node["label"]
            assert by_id[node["id"]]["description"] == node["description"]

    @pytest.mark.parametrize(
        ("payload", "match"),
        [
            (
                {
                    "version": 1, "stage": "upload",
                    "nodes": [
                        {"id": "dup", "label": "A", "description": "..."},
                        {"id": "dup", "label": "B", "description": "..."},
                    ],
                },
                "Дубликат",
            ),
            (
                {
                    "version": 1, "stage": "upload",
                    "nodes": [{"id": "x", "label": "Метка", "description": " "}],
                },
                "description",
            ),
            (
                {
                    "version": 1, "stage": "eda",
                    "nodes": [{"id": "x", "label": "Метка", "description": "описание"}],
                },
                "stage",
            ),
            ({"version": 1, "stage": "upload", "nodes": []}, "nodes"),
        ],
    )
    def test_loader_fail_closed(self, tmp_path, payload, match):
        from app.core.pipeline_graph import _load_upload_stop_defs

        path = tmp_path / "probe_upload.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ImportError, match=match):
            _load_upload_stop_defs(path)


# ── A2: legacy-нормализация корпуса при полном реестре ───────────────


def test_legacy_node_id_normalized_with_full_registry():
    """A2: при 5-узловой Загрузке legacy structure_confirmed корпуса
    слоя 2 нормализуется к каноническому structure -- история старых
    запусков не теряется и при полном реестре (B3 на новых условиях)."""
    from app.core.node_status import normalize_legacy_node_id

    assert normalize_legacy_node_id("upload", "structure_confirmed") == "structure"
    events = [
        _event("upload", "structure_confirmed", "upload_completed", _iso(1)),
    ]
    statuses = derive_node_statuses(events)
    # upload_completed в A3 -- факт узла overview, но явный legacy node_id
    # приоритетен: нормализация переводит строку корпуса на канонический
    # узел structure -- фантомного ключа "upload/structure_confirmed" нет.
    assert statuses == {"upload/structure": "done"}


def test_is_known_node_accepts_all_five_stops():
    for node_id in EXPECTED_STOP_IDS:
        assert is_known_node("upload", node_id) is True
    assert is_known_node("upload", "structure_confirmed") is False


# ── A3: upload_completed -> overview; date-column -> structure ───────


def test_upload_completed_paints_only_overview_done():
    """Факт чтения файла -- узел overview; остальные остановки честно
    pending до своих фактов (дефект 1б: зелёная «Структура» без
    подтверждения аналитиком)."""
    events = [_event("upload", "overview", "upload_completed", _iso(1))]
    statuses = derive_node_statuses(events)
    assert statuses == {"upload/overview": "done"}


def test_structure_confirmed_event_is_node_fact():
    """structure_confirmed -- УЗЛОВОЙ факт решения (узел structure,
    done): фазу двигает (аналитик подтвердил структуру на «Загрузке»)."""
    events = [
        _event("upload", "overview", "upload_completed", _iso(1)),
        _event("upload", "structure", "structure_confirmed", _iso(2)),
    ]
    statuses = derive_node_statuses(events)
    assert statuses["upload/structure"] == "done"
    assert derive_last_active_stage(events) == "upload"


def test_date_column_post_seeds_structure_confirmed_with_payload():
    """API: POST /v1/session/date-column -- факт решения аналитика:
    событие structure_confirmed (upload/structure) с payload-фактом
    date_column из тела ответа (§4.1 -- форма ответа эндпоинта)."""
    _upload()
    date_resp = client.post("/v1/session/date-column", json={"column": "date"})
    assert date_resp.status_code == 200, date_resp.text

    trace = _trace()
    confirmed = [
        event for event in trace["events"]
        if event.get("event_type") == "structure_confirmed"
    ]
    assert confirmed, "structure_confirmed не засеян POST /date-column"
    assert confirmed[-1]["stage"] == "upload"
    assert confirmed[-1]["node_id"] == "structure"
    assert confirmed[-1]["payload"].get("date_column") == "date"

    statuses = trace["node_statuses"]
    assert statuses.get("upload/overview") == "done"
    assert statuses.get("upload/structure") == "done"


def test_date_column_post_success_event_not_written_on_error():
    """Fail-closed хука: неуспешный ответ (422 -- колонка не распознана)
    событие не пишет -- трасса решений, не лог ошибок (§4.2)."""
    _upload()
    bad = client.post("/v1/session/date-column", json={"column": "value"})
    assert bad.status_code == 422
    trace = _trace()
    assert not [
        event for event in trace["events"]
        if event.get("event_type") == "structure_confirmed"
    ]


# ── A4: движок payload-статусов + контракт POST /upload-stops ────────


def test_resolve_event_status_payload_whitelist():
    """Статус upload_stop_status -- ИЗ PAYLOAD, whitelist
    CHECK_STATUS_VALUES: валидный -- как есть; мусор -- None (событие
    хранится, но фантомного статуса не создаёт, R3 PROGR-1-CERT)."""
    assert resolve_event_status(
        _event("upload", "quality", "upload_stop_status", _iso(1), {"status": "warning"})
    ) == "warning"
    assert resolve_event_status(
        _event("upload", "quality", "upload_stop_status", _iso(1), {"status": "exploded"})
    ) is None
    assert resolve_event_status(
        _event("upload", "quality", "upload_stop_status", _iso(1), {"status": 42})
    ) is None
    assert resolve_event_status(
        _event("upload", "quality", "upload_stop_status", _iso(1))
    ) is None


def test_last_wins_client_report_over_backend_fact():
    """Хронология решает: structure_confirmed (done) ПОСЛЕ отчёта модуля
    перекрашивает узел в done; ре-пост отчёта модуля ПОСЛЕ подтверждения
    возвращает warning -- панель == модулю (A5-контракт ре-поста)."""
    report = {"status": "warning"}
    confirm = {}
    events = [
        _event("upload", "structure", "upload_stop_status", _iso(1), report),
        _event("upload", "structure", "structure_confirmed", _iso(2), confirm),
        _event("upload", "structure", "upload_stop_status", _iso(3), report),
    ]
    assert derive_node_statuses(events)["upload/structure"] == "warning"


def test_upload_stop_status_moves_mentor_phase():
    """Отчёт остановок -- действие аналитика на вкладке «Загрузка»:
    узловой факт стадии upload двигает фазу Наставника (и не может
    «перенести» её на чужую вкладку)."""
    events = [
        _event("validation", "formats", "correction_applied", _iso(1)),
        _event("upload", "quality", "upload_stop_status", _iso(2), {"status": "warning"}),
    ]
    assert derive_last_active_stage(events) == "upload"


def test_upload_stops_endpoint_full_contract():
    """Контракт A4 end-to-end: снапшот модуля -- события в слое 1 И
    зеркале слоя 2; панель показывает ТЕ ЖЕ статусы; карточка стадии --
    attention при warning-остановках (§12 п.10)."""
    _upload()
    stops = {
        "overview": "done",
        "chart": "done",
        "distribution": "done",
        "structure": "warning",
        "quality": "warning",
    }
    reported = client.post("/v1/progress/upload-stops", json={"stops": stops})
    assert reported.status_code == 200, reported.text
    body = reported.json()
    assert body["reported"] == 5
    assert body["run_id"] and body["run_id"].startswith("RUN-")

    # Слой 1: 5 событий upload_stop_status со статусом в payload.
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    layer1 = [
        event for event in session.pipeline_trace
        if event["event_type"] == "upload_stop_status"
    ]
    assert len(layer1) == 5
    by_node = {event["node_id"]: event for event in layer1}
    for node_id, status in stops.items():
        assert by_node[node_id]["payload"]["status"] == status
        assert by_node[node_id]["run_id"] == body["run_id"]

    # Слой 2 (зеркало §5): admin-аналитика и Наставник видят факты.
    from apps.api.research_runs import get_research_run_store

    stored = get_research_run_store().list_events(body["run_id"])
    mirror = [event for event in stored if event.event_type == "upload_stop_status"]
    assert len(mirror) == 5

    # Панель == модулю.
    trace = _trace()
    for node_id, status in stops.items():
        assert trace["node_statuses"].get(f"upload/{node_id}") == status


def test_upload_stops_endpoint_fail_closed_all_or_nothing():
    """Fail-closed (паттерн sanity-check §7.2): неизвестный узел /
    недопустимый статус / неполная карта -- 422 ДО первой записи;
    в трассе ни одного события отчёта (all-or-nothing)."""
    _upload()
    bad_payloads = [
        # неизвестный узел -- фантом
        {"stops": {"overview": "done", "chart": "done", "distribution": "done",
                   "structure": "done", "quality": "done", "phantom": "done"}},
        # недопустимый статус -- вне CheckStatus
        {"stops": {"overview": "done", "chart": "done", "distribution": "done",
                   "structure": "exploded", "quality": "done"}},
        # неполная карта -- не снапшот реестра
        {"stops": {"overview": "done"}},
        # пустая карта
        {"stops": {}},
    ]
    for payload in bad_payloads:
        response = client.post("/v1/progress/upload-stops", json=payload)
        assert response.status_code == 422, (payload, response.text)

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    assert not [
        event for event in session.pipeline_trace
        if event["event_type"] == "upload_stop_status"
    ]


def test_upload_stops_endpoint_requires_dataset():
    """Аналитик без датасета -- честный 400: остановки «Загрузки» без
    исследования не существуют (паттерн /date-column «Сначала
    загрузите датасет»)."""
    response = client.post(
        "/v1/progress/upload-stops",
        json={"stops": {node: "done" for node in EXPECTED_STOP_IDS}},
    )
    assert response.status_code == 400


def test_upload_stops_endpoint_seeds_run_id_on_first_report():
    """Отчёт остановок -- первый трассируемый факт сессии (загрузка шла
    мимо хука): run_id фиксируется по факту первой записи (§5)."""
    _upload()
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    session.run_id = ""  # модельная сессия без run_id (загрузка мимо хука)
    get_session_store().save(session)

    reported = client.post(
        "/v1/progress/upload-stops",
        json={"stops": {node: "done" for node in EXPECTED_STOP_IDS}},
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["run_id"].startswith("RUN-")


# ── A5: потребители -- отчёт §5.4 и зеркало фронтенда ────────────────


def test_report_renders_upload_stop_facts_with_registry_labels():
    """Отчёт §5.4 -- та же гранулярность, что у панели: узлы остановок
    с метками из ОБЩЕГО реестра + человекочитаемые строки фактов
    (structure_confirmed/upload_stop_status), без сырых id."""
    from app.core.run_report import build_report_model, render_markdown

    events = [
        _event("upload", "overview", "upload_completed", _iso(1),
               {"name": "monitor.csv", "rows": 150, "columns": 2}),
        _event("upload", "structure", "upload_stop_status", _iso(2), {"status": "warning"}),
        _event("upload", "structure", "structure_confirmed", _iso(3), {"date_column": "date"}),
        _event("upload", "quality", "upload_stop_status", _iso(4), {"status": "warning"}),
    ]
    run_meta = {
        "run_id": "RUN-PROGR13A01", "dataset_name": "monitor.csv",
        "status": "active", "created_at": _iso(0), "last_active_at": _iso(4),
    }
    model = build_report_model(run_meta, events)
    md = render_markdown(model)

    # Метки -- из общего реестра (единый источник с модулем).
    assert "### Превью датасета" in md
    assert "### Структура" in md
    assert "### Качество" in md
    # Строки фактов -- честные, без выдуманных чисел.
    assert "Подтверждена временная колонка «date»." in md
    assert "Статус остановки «Структура» отчитан модулем: есть замечания." in md
    assert "Статус остановки «Качество» отчитан модулем: есть замечания." in md
    assert "Загружен датасет «monitor.csv»: строк: 150, колонок: 2." in md


def test_report_fallback_labels_cover_all_registry_stops():
    """FALLBACK-метки отчёта обязаны покрывать ВЕСЬ общий реестр:
    новая остановка в JSON без метки в отчёте -- сырой id в UI."""
    from app.core.run_report import FALLBACK_NODE_LABELS

    for node in UPLOAD_STOP_DEFS:
        assert FALLBACK_NODE_LABELS[("upload", node["id"])] == node["label"]


def test_frontend_mirror_declares_five_upload_nodes():
    """Sync-контур (RED-контракт задачи A, дублируется контрольным
    прогоном test_progress_defects_progr13): зеркало progress.ts --
    те же 5 id; здесь -- структурная проверка исходника на метки из
    общего JSON и отсутствие вшитой копии меток Загрузки."""
    src = PROGRESS_TS_PATH.read_text(encoding="utf-8")
    # Метки -- из общего JSON (тот же источник, что у модуля и графа).
    assert "uploadStopsJson.nodes" in src
    # Вшитая метка «Структура данных» для upload больше не живёт в .ts:
    # единственный источник -- общий JSON (метка теперь «Структура»).
    assert 'upload: { structure: "Структура данных" }' not in src
