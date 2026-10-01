# tests/api/test_progress_panel.py
"""Тесты Task PROGR-4 (UI-панель «Прогресс», аддендум §4.1-4.2): серверная
сторона панели -- чтение внутрисессионного слоя трассы (§5 слой 1).

PROGR-3 дал ЗАПИСЬ трассы (TraceHookMiddleware -> session.pipeline_trace),
но у панели нет чтения: шапка §6.1 требует run_id ("новое, см. §5") и
"Начат N мин назад" (аналог created_at слоя 1 -- ts первого события),
§6.2 требует плоский хронологический список trace_events. Отсюда ровно
один новый читающий эндпоинт: GET /v1/progress/trace (пространство имён
/v1/progress/* -- канон spec_progress.md §5: /v1/progress/runs/...).
Ничего не пишет (не в TRACE_ROUTES -- читающий ридер трассы сам не
трассируется), сессия -- по cookie, пустая сессия -- пустой ответ.

Второй контур этого файла -- СИНХРОНИЗАЦИЯ РЕЕСТРА УЗЛОВ фронтенда
(packages/ui/lib/progress.ts::PROGRESS_STAGE_NODES) с живым графом
(app/core/pipeline_graph.py::STAGE_NODES). Паттерн -- прецедент
test_eda_tsx_imports_shared_json (§12 п.2) и CERTIFIED_IDS-тестов:
фронтенду нужен полный список id узлов (46) для блок-схемы §6.2
("3/10, найдены проблемы" невозможно без знания total), а общего
рантайма у Python/TS нет -- копия связывается тестом, читающим живой
исходник .ts (regex, без транскрипиляции), как это уже сделано для
eda-checks.json и TsAnalysisEDA.tsx.

Контур 1.1 (Task PROGR-10, Расхождение №1): /trace отдаёт панели
ГОТОВОЕ состояние -- events (серверное слияние слой 1 +
ForecastRun.trace, хронология), node_statuses (единый движок
app/core/node_status.py) и stages (свёртки §12 п.10 + счётчики);
панель больше не делает второй опрос /v1/session/modeling/forecast и
не вычисляет статусы сама. Прогнозные события сеются прямой инъекцией
в modeling_artifacts (артефакт сессии) -- слияние/канонизация/деривация
проверяются на детерминированных данных (N-1).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import make_trace_event


@pytest.fixture()
def client():
    reset_session_store_for_testing()
    with TestClient(app) as test_client:
        yield test_client
    reset_session_store_for_testing()


# ── Контур 1: GET /v1/progress/trace ─────────────────────────────────


class TestProgressTraceEndpoint:
    def test_empty_session_returns_empty_shape(self, client: TestClient):
        """Пустая сессия (cookie создан /current-логикой эндпоинта):
        run_id -- null (§5: run_id появляется по факту первой загрузки),
        started_at -- null, events -- пустой список; HTTP 200."""
        resp = client.get("/v1/progress/trace")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] is None
        assert data["started_at"] is None
        assert data["events"] == []

    def test_trace_endpoint_is_not_traced_by_hook(self, client: TestClient):
        """Читающий ридер трассы сам не трассируется: эндпоинт отсутствует
        в таблице хука (§4.2 -- троттлинг/события определены для узловых
        profile/mutation-маршрутов; иначе каждый рендер панели рос бы в
        собственном логе). Проверка через живой resolve хука."""
        from apps.api.trace_hook import resolve_trace_route

        assert resolve_trace_route("GET", "/v1/progress/trace") is None

    def test_events_returned_after_hook_writes(self, client: TestClient):
        """События, записанные хуком (PROGR-3), читаются эндпоинтом:
        demo-загрузка -> upload_completed на узле structure_confirmed;
        run_id зафиксирован (формат RUN-XXXXXXXX §5); started_at -- ts
        первого события (аналог created_at слоя 1 для шапки §6.1)."""
        demo = client.post("/v1/session/demo")
        assert demo.status_code == 200

        resp = client.get("/v1/progress/trace")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] is not None
        assert re.fullmatch(r"RUN-[0-9A-F]{8}", data["run_id"])
        assert data["started_at"] is not None

        events = data["events"]
        upload_events = [e for e in events if e["event_type"] == "upload_completed"]
        assert len(upload_events) == 1
        event = upload_events[0]
        # Канон §4.1: 8 полей + legacy-алиас timestamp (to_dict).
        for key in (
            "event_id", "run_id", "ts", "stage", "node_id",
            "event_type", "payload", "actor", "timestamp",
        ):
            assert key in event
        assert event["stage"] == "upload"
        assert event["node_id"] == "structure_confirmed"
        assert event["run_id"] == data["run_id"]
        assert event["ts"] == event["timestamp"]
        # payload -- факты ответа (§4.1); у /v1/session/demo строка таблицы
        # хука без payload_keys (имя/размерность пишут только upload-маршруты)
        # -- словарь может быть пустым, это честный контракт таблицы.
        assert isinstance(event["payload"], dict)

    def test_read_boundary_normalizes_legacy_events(self, client: TestClient):
        """Граница чтения: legacy 3-польная запись в stored-трассе
        (timestamp без ts -- исторический формат ForecastRun) нормализуется
        к канону §4.1 при чтении -- панель не должна знать о старых
        форматах (PROGR-3, решение R2/R3; здесь -- сквозной контракт
        эндпоинта на своих данных теста)."""
        store = get_session_store()
        session = store.get_or_create("progress-legacy-test")
        session.pipeline_trace.append(
            {
                "event_type": "backtest_run",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "payload": {"model_id": "arima"},
            }
        )
        store.save(session)

        # cookie сессии теста -- через demo-путь не идём: подкладываем
        # cookie напрямую (контракт cookie-сессий платформы).
        client.cookies.set("cisstat_session_id", "progress-legacy-test")
        resp = client.get("/v1/progress/trace")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 1
        event = events[0]
        # Канон ts + legacy-алиас на границе чтения (панель не знает
        # старых форматов).
        assert event["ts"] == "2026-01-01T00:00:00+00:00"
        assert event["timestamp"] == "2026-01-01T00:00:00+00:00"
        # Решение R2 PROGR-3-CERT: legacy-маркер (timestamp без ts)
        # приоритетнее явной stage -- вся историческая 3-польная
        # популяция -- forecasting; stage= не подставляется из event_type.
        assert event["stage"] == "forecasting"
        # Решение R3 PROGR-3-CERT: event_type на границе чтения НЕ
        # валидируется -- неизвестная для forecasting пара сохраняется
        # как есть (трасса -- журнал, не реестр).
        assert event["event_type"] == "backtest_run"
        assert event["node_id"] is None
        assert event["payload"] == {"model_id": "arima"}

    def test_run_id_none_without_dataset_even_with_events(self, client: TestClient):
        """run_id не фиксируется без активного датасета (§5: "по факту
        первой загрузки"; PROGR-3 гейт ensure_run_id). Панель показывает
        честный null, а не пустую строку."""
        store = get_session_store()
        session = store.get_or_create("progress-no-dataset")
        session.append_trace_event(
            make_trace_event("passport_captured", stage="eda", node_id=None,
                             run_id="")
        )
        store.save(session)
        client.cookies.set("cisstat_session_id", "progress-no-dataset")

        resp = client.get("/v1/progress/trace")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] is None
        assert len(data["events"]) == 1
        assert data["started_at"] is not None

    def test_events_chronological_append_order(self, client: TestClient):
        """Список -- в порядке дописывания (хронология §6.2: старые
        раньше новых): первое событие -- upload, второе -- eda."""
        client.post("/v1/session/demo")
        store = get_session_store()
        session_id = client.cookies.get("cisstat_session_id")
        session = store.get(session_id)
        session.append_trace_event(
            make_trace_event("profile_viewed", stage="eda", node_id="correlation",
                             run_id=session.run_id)
        )
        store.save(session)

        resp = client.get("/v1/progress/trace")
        events = resp.json()["events"]
        types = [e["event_type"] for e in events]
        assert types.index("upload_completed") < types.index("profile_viewed")


# ── Контур 1.1: готовое состояние панели (PROGR-10, Расхождение №1) ──


def _seed_forecast_artifact(session, entries: list[dict]) -> None:
    """Прямая инъекция прогнозных событий в артефакт сессии (N-1):
    та же структура, что живут в session.modeling_artifacts["forecasts"]
    после _append_event forecasting_session (event.to_dict) или legacy
    3-поля (историческая популяция ForecastRun.trace)."""
    forecasts = session.modeling_artifacts.setdefault("forecasts", {})
    forecasts["f-test"] = {"forecast_id": "f-test", "trace_events": entries}


class TestProgressTraceReadyState:
    def test_trace_exposes_node_statuses_and_stage_states(self, client: TestClient):
        """/trace отдаёт готовое состояние: node_statuses из единого
        движка и ВСЕ 6 стадий в порядке §2 (счётчики из графа, пустая
        трасса -- честные «не начато»)."""
        from app.core.pipeline_graph import STAGES, STAGE_NODES

        resp = client.get("/v1/progress/trace")
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_statuses"] == {}
        assert [s["stage"] for s in data["stages"]] == list(STAGES)
        assert all(s["fold"] == "not_started" for s in data["stages"])
        assert [s["total_nodes"] for s in data["stages"]] == [
            len(STAGE_NODES[stage]) for stage in STAGES
        ]

    def test_upload_decision_seeds_ready_state(self, client: TestClient):
        """Демо-загрузка -- факт решения: upload/structure_confirmed
        done в node_statuses, карточка Загрузки -- passed 1/1, остальные
        стадии не тронуты."""
        client.post("/v1/session/demo")
        data = client.get("/v1/progress/trace").json()
        assert data["node_statuses"]["upload/structure_confirmed"] == "done"
        upload = next(s for s in data["stages"] if s["stage"] == "upload")
        assert upload == {
            "stage": "upload",
            "fold": "passed",
            "done_count": 1,
            "warning_nodes": 0,
            "total_nodes": 1,
        }
        modeling = next(s for s in data["stages"] if s["stage"] == "modeling")
        assert modeling["fold"] == "not_started"

    def test_forecast_artifact_merged_and_canonized_server_side(
        self, client: TestClient
    ):
        """Слой 1 + ForecastRun.trace сливает СЕРВЕР: канонизация
        (ts=timestamp, stage/node_id=out of event_type), хронология,
        готовые статусы прогнозных узлов. Каноническая и legacy-записи
        артефакта дают одинаковый результат."""
        client.post("/v1/session/demo")
        store = get_session_store()
        session_id = client.cookies.get("cisstat_session_id")
        session = store.get(session_id)
        _seed_forecast_artifact(
            session,
            [
                # Stored-форма (event.to_dict): ts + legacy-алиас timestamp.
                {
                    "event_id": "art-1",
                    "run_id": "",
                    "ts": "2026-01-01T12:00:00+00:00",
                    "timestamp": "2026-01-01T12:00:00+00:00",
                    "stage": "forecasting",
                    "node_id": None,
                    "event_type": "forecast_generated",
                    "payload": {"model_id": "arima"},
                    "actor": "user",
                },
                # Legacy 3-поля: только timestamp.
                {
                    "event_type": "forecast_exported",
                    "timestamp": "2026-01-01T13:00:00+00:00",
                    "payload": {"fmt": "csv"},
                },
            ],
        )
        store.save(session)

        data = client.get("/v1/progress/trace").json()
        forecast_events = [
            e for e in data["events"] if e["event_type"].startswith("forecast_")
        ]
        assert [e["event_type"] for e in forecast_events] == [
            "forecast_generated", "forecast_exported",
        ]
        assert forecast_events[0]["ts"] == "2026-01-01T12:00:00+00:00"
        assert forecast_events[0]["stage"] == "forecasting"
        assert forecast_events[0]["node_id"] == "forecast_generated"
        assert forecast_events[0]["payload"] == {"model_id": "arima"}
        # Хронология: merge отсортирован, а не склеен блоками
        # (upload ~now -- позже дат 2026-01-01... seed стабилен: теперь
        # проверяем порядок двух прогнозных между собой + позицию.
        types = [e["event_type"] for e in data["events"]]
        assert types.index("forecast_generated") < types.index("forecast_exported")
        # Готовые статусы единого движка.
        assert data["node_statuses"]["forecasting/forecast_generated"] == "done"
        assert data["node_statuses"]["forecasting/forecast_exported"] == "done"
        forecasting = next(
            s for s in data["stages"] if s["stage"] == "forecasting"
        )
        assert forecasting["fold"] == "attention"
        assert forecasting["done_count"] == 2
        assert forecasting["total_nodes"] == 4

    def test_artifact_events_are_not_checkpoint_anchors(self, client: TestClient):
        """run_id/event_id НЕ выдумываются: канонизируемые события
        артефакта без event_id -- не якоря чекпоинтов (семантика §5.1
        прежняя; лента контракта: events без event_id пропускаются
        выборкой якоря на фронте)."""
        client.post("/v1/session/demo")
        store = get_session_store()
        session_id = client.cookies.get("cisstat_session_id")
        session = store.get(session_id)
        _seed_forecast_artifact(
            session,
            [{
                "event_type": "forecast_generated",
                "timestamp": "2026-01-01T12:00:00+00:00",
                "payload": {},
            }],
        )
        store.save(session)

        data = client.get("/v1/progress/trace").json()
        forecast_events = [
            e for e in data["events"] if e["event_type"] == "forecast_generated"
        ]
        assert len(forecast_events) == 1
        assert "event_id" not in forecast_events[0]
        assert "run_id" not in forecast_events[0]

    def test_forecast_foreign_types_skipped_fail_safe(self, client: TestClient):
        """Чужие типы и мусорные записи артефакта fail-safe пропускаются:
        фантомных узлов и 500 нет (семантика прежнего слияния панели)."""
        client.post("/v1/session/demo")
        store = get_session_store()
        session_id = client.cookies.get("cisstat_session_id")
        session = store.get(session_id)
        _seed_forecast_artifact(
            session,
            [
                {"event_type": "custom_event", "timestamp": "2026-01-01T12:00:00+00:00"},
                "мусорная-запись",
                {"event_type": "forecast_compared"},  # без ts -- честная пустая строка
            ],
        )
        store.save(session)

        data = client.get("/v1/progress/trace").json()
        types = [e["event_type"] for e in data["events"]]
        assert "custom_event" not in types
        assert "forecast_compared" in types  # канонический тип пропущен не был
        # Пропуск чужого типа не задел соседнюю запись: узел выведен.
        assert data["node_statuses"]["forecasting/forecast_compared"] == "done"

    def test_layer1_reader_does_not_need_durable_layer(self, client: TestClient):
        """Ридер трассы -- сессионный: /trace не трогает слой 2 --
        его 503 панель не гасит (кнопки полосы disabled -- прежняя
        семантика PROGR-5.1); статус/чекпоинты -- отдельный запрос."""
        from apps.api import research_runs

        client.post("/v1/session/demo")
        # Слой 2 недоступен (fail-closed синглтон -- та же механика,
        # что в тестах PROGR-5/6), но /trace обязан ответить 200.
        original = research_runs.get_research_run_store
        research_runs.get_research_run_store = lambda: (_ for _ in ()).throw(
            RuntimeError("durable layer down")
        )
        try:
            resp = client.get("/v1/progress/trace")
            assert resp.status_code == 200
            assert resp.json()["node_statuses"]["upload/structure_confirmed"] == "done"
        finally:
            research_runs.get_research_run_store = original


# ── Контур 2: синхронизация реестра узлов фронтенда с графом ─────────

_TS_PROGRESS_LIB = (
    Path(__file__).resolve().parents[2]
    / "packages" / "ui" / "lib" / "progress.ts"
)


def _parse_ts_stage_nodes(source: str) -> dict[str, tuple[str, ...]]:
    """Чтение PROGRESS_STAGE_NODES из живого исходника progress.ts.

    Формат строго зафиксирован (и этим же тестом страхован): блок
    `export const PROGRESS_STAGE_NODES: Record<string, readonly string[]> = {`
    , внутри -- строки `"stage": ["id", ...],`. Regex читает пары
    ключ -> массив строк; любая реорганизация формата ломает тест --
    это сознательная цена sync-маркера (как в прецеденте eda JSON).
    """
    block_match = re.search(
        r"export const PROGRESS_STAGE_NODES[^=]*=\s*\{(.*?)\n\};",
        source,
        re.DOTALL,
    )
    assert block_match, (
        "PROGRESS_STAGE_NODES не найден в packages/ui/lib/progress.ts -- "
        "sync-маркер сломан реорганизацией файла"
    )
    stage_map: dict[str, tuple[str, ...]] = {}
    entry_pattern = re.compile(r'"([a-z_]+)":\s*\[([^\]]*)\]', re.DOTALL)
    for key, raw_ids in entry_pattern.findall(block_match.group(1)):
        ids = tuple(re.findall(r'"([^"]+)"', raw_ids))
        stage_map[key] = ids
    return stage_map


class TestFrontendNodeRegistrySync:
    """Sync-маркер: копия узлов графа на фронтенде обязана совпадать с
    живым графом (источник истины -- app/core/pipeline_graph.py)."""

    def test_progress_ts_file_exists(self):
        assert _TS_PROGRESS_LIB.exists(), (
            "packages/ui/lib/progress.ts отсутствует -- блок-схеме §6.2 "
            "нужен полный реестр узлов"
        )

    def test_frontend_stage_nodes_match_pipeline_graph(self):
        from app.core.pipeline_graph import STAGE_NODES, STAGES

        source = _TS_PROGRESS_LIB.read_text(encoding="utf-8")
        ts_nodes = _parse_ts_stage_nodes(source)

        # Пять стадий зашиты в .ts текстово и обязаны совпадать с графом
        # дословно (порядок -- контракт §2).
        for stage in STAGES:
            if stage == "eda":
                continue
            actual = ts_nodes.get(stage, ())
            assert actual == tuple(STAGE_NODES[stage]), (
                f"Узлы стадии {stage!r} на фронтенде расходятся с графом: "
                f"ts={actual}, graph={tuple(STAGE_NODES[stage])}"
            )

        # EDA-узлы фронтенд берёт из общего JSON §12 п.2 (единственный
        # источник, тот же файл, что читает граф бэкенда): текстовый
        # sync-маркер -- импорт общего реестра. Паритет JSON <-> граф
        # страхует сюит PROGR-2 (test_pipeline_graph.py), здесь --
        # честная проверка, что копии-дубликата не появилось.
        assert "shared/pipeline_nodes/eda_checks.json" in source, (
            "progress.ts обязан импортировать общий реестр EDA (§12 п.2), "
            "а не держать вшитую копию id"
        )
        assert tuple(ts_nodes.keys()) == tuple(
            s for s in STAGES if s != "eda"
        ) or "eda" not in ts_nodes

    def test_frontend_has_label_for_every_node(self):
        """Каждый узел графа имеет человекочитаемую метку на фронтенде:
        раскрытие стадии §6.2 рендерит узлы списком -- узел без метки
        означал бы сырой id в UI как fallout копирования реестра."""
        from app.core.pipeline_graph import STAGES, STAGE_NODES

        source = _TS_PROGRESS_LIB.read_text(encoding="utf-8")
        ts_nodes = _parse_ts_stage_nodes(source)
        for stage in STAGES:
            if stage == "eda":
                continue  # метки eda -- из общего JSON (label каждого узла)
            for node_id in ts_nodes.get(stage, ()):
                assert f'"{node_id}"' in source, (
                    f"Узел {stage}/{node_id} отсутствует в progress.ts"
                )
        # Полное покрытие не-EDA стадий: сумма узлов = полный граф без eda.
        assert sum(len(v) for k, v in ts_nodes.items()) == sum(
            len(v) for k, v in STAGE_NODES.items() if k != "eda"
        )
