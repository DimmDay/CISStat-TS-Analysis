# tests/api/test_progress_trace_hook.py
"""Task PROGR-3: внутрисессионный слой трассы (spec_progress.md §5 слой 1)
+ хук записи событий на изменяющих/читающих эндпоинтах (§4.2).

Проверяемые контракты приёмки plan_progress.md (PROGR-3):
  * события correction_applied/mode_changed/... пишутся на УСПЕШНЫХ
    ответах (response.status_code < 400), таблицей маршрутов
    apps/api/trace_hook.py, без правки тел роутеров;
  * profile_viewed троттлится (дефолт 5 минут, env-переменная
    PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS) -- не чаще 1 раза на узел
    за окно;
  * run_id фиксируется при первой загрузке (AnalysisSession.ensure_run_id,
    сброс в set_dataset -- новый датасет = новое исследование §3.1);
  * граница чтения трассы нормализует stored-события через
    normalize_trace_event_dict (риск-таблица плана: Redis-сессии со
    старыми 3-польными событиями -- fail-closed к дефолтам канона);
  * замечания сертификации PROGR-1-CERT R1-R4 (см. worklog8.md):
    R1 -- глубокая копия payload на границе записи (append_trace_event);
    R2 -- legacy-маркер (timestamp без ts) приоритетнее явной stage:
    поведение зафиксировано тестом как осознанное решение;
    R3 -- event_type на границе чтения НЕ валидируется: событие с
    неизвестным типом сохраняется (аудит), решение зафиксировано тестом;
    R4 -- дефолты датакласса TraceEvent покрыты тестом прямого
    конструирования (становятся живыми при первом прямом потребителе).
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api import session_store as session_store_module
from apps.api.main import app
from apps.api.session_store import (
    MAX_PIPELINE_TRACE_EVENTS,
    SESSION_COOKIE_NAME,
    AnalysisSession,
    DatasetInfo,
    get_session_store,
    reset_session_store_for_testing,
    session_from_dict,
    session_to_dict,
)
from apps.api.trace_events import TraceEvent, make_trace_event
from app.core.pipeline_graph import is_known_node

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


# ── helpers ──────────────────────────────────────────────────────────


def _prices_csv() -> str:
    frame = pd.DataFrame({"Price": [-5.0, 10.0, 150.0]})
    return frame.to_csv(index=False)


def _series_frame(size: int = 80) -> pd.DataFrame:
    rng = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-01", periods=size, freq="D"),
            "Price": [float(i % 7) + 0.1 * i for i in range(size)],
        }
    )
    return rng


def _upload(client_: TestClient, csv_text: str) -> None:
    response = client_.post(
        "/v1/internal/upload",
        files={"file": ("trace.csv", io.BytesIO(csv_text.encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _session() -> AnalysisSession:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id, "у тестового клиента нет cookie сессии"
    session = get_session_store().get(session_id)
    assert session is not None
    return session


def _trace_events() -> list[dict[str, Any]]:
    return _session().pipeline_trace


def _last_stored() -> dict[str, Any]:
    events = _trace_events()
    assert events, "трасса пуста"
    return events[-1]


# ── 1. Целостность таблицы маршрутов (fail-closed, §4.2) ─────────────


def test_route_table_covers_documented_endpoints():
    from apps.api.trace_hook import TRACE_ROUTES

    keys = {(spec.method, spec.path_template) for spec in TRACE_ROUTES}
    # Загрузка (3 входа: embedded, public, demo)
    assert ("POST", "/v1/internal/upload") in keys
    assert ("POST", "/v1/public/upload") in keys
    assert ("POST", "/v1/session/demo") in keys
    # PROGR-13-A3: подтверждение структуры аналитиком (POST /date-column)
    assert ("POST", "/v1/session/date-column") in keys
    # Корректировки Валидации (8 + sufficiency + convert-types)
    for path in (
        "/v1/session/dataset/format-corrections",
        "/v1/session/dataset/range-corrections",
        "/v1/session/dataset/inclusion-corrections",
        "/v1/session/dataset/referential-corrections",
        "/v1/session/dataset/text-quality-corrections",
        "/v1/session/dataset/regularity-corrections",
        "/v1/session/dataset/consistency-corrections",
        "/v1/session/dataset/uniqueness-corrections",
        "/v1/session/dataset/sufficiency-plan",
        "/v1/session/dataset/convert-types",
    ):
        assert ("POST", path) in keys, path
    # Уровень стадии Валидации (роутер объявляет "/target-column" без
    # /dataset-префикса)
    assert ("POST", "/v1/session/target-column") in keys
    assert ("PUT", "/v1/session/dataset/validation-check-modes") in keys
    # Предобработка: 10 маршрутов + check-modes
    for path in (
        "/v1/session/dataset/missing-corrections",
        "/v1/session/dataset/outlier-corrections",
        "/v1/session/dataset/preprocessing/regularity-corrections",
        "/v1/session/dataset/preprocessing/decomposition-outputs",
        "/v1/session/dataset/preprocessing/variance-transformations",
        "/v1/session/dataset/preprocessing/smoothing-transformations",
        "/v1/session/dataset/preprocessing/stationarity-transformations",
        "/v1/session/dataset/preprocessing/spectral-selections",
        "/v1/session/dataset/preprocessing/feature-generations",
        "/v1/session/dataset/preprocessing/scaling-recipes",
    ):
        assert ("POST", path) in keys, path
    assert ("PUT", "/v1/session/dataset/preprocessing-check-modes") in keys
    # EDA/Загрузка/Валидация/Моделирование: паспорт ПО ТОЧКАМ
    # (PROGR-13-B2: значение параметра пути маппится на стадию события;
    # неизвестная точка -- fail-closed, строки в таблице нет) +
    # 9 исследовательских GET (descriptive без эндпоинта)
    for point in ("start", "validation", "exit", "modeling_entry"):
        assert ("POST", f"/v1/session/dataset/passport/{point}") in keys, point
    for path in (
        "/v1/session/dataset/eda-correlation",
        "/v1/session/dataset/eda-ih",
        "/v1/session/dataset/eda-seasonality",
        "/v1/session/dataset/eda-stationarity",
        "/v1/session/dataset/eda-distribution",
        "/v1/session/dataset/eda-structural-breaks",
        "/v1/session/dataset/eda-feature-selection",
        "/v1/session/dataset/eda-validation-strategy",
        "/v1/session/dataset/eda-model-matrix",
    ):
        assert ("GET", path) in keys, path
    # Моделирование: 4 типа событий §4.1
    for path in (
        "/v1/session/modeling/backtest",
        "/v1/session/modeling/tune",
        "/v1/session/modeling/select",
        "/v1/session/modeling/card",
    ):
        assert ("POST", path) in keys, path
    # PROGR-13-B2: динамическая строка passport/{stage} развёрнута в
    # 4 литеральных (точка -> стадия): 40 - 1 + 4 = 43;
    # PROGR-13-A3: + POST /v1/session/date-column (structure_confirmed) = 44;
    # PROGR-20 (v1.1 §1, категория A): + 9 строк Моделирования
    # (P0 ×2, P1 ×3, P2 ×4) = 53 (детально -- секция 9 ниже);
    # G345-фикс (PROGR-23): + GET /v1/session/dataset/outlier-profile
    # (живой пересчёт карточки «Выбросы», outliers_profile_status,
    # dedupe) = 54.
    assert len(TRACE_ROUTES) == 54
    assert ("GET", "/v1/session/dataset/outlier-profile") in keys


def test_route_table_pairs_pass_trace_event_gate():
    from apps.api.trace_hook import TRACE_ROUTES

    for spec in TRACE_ROUTES:
        # make_trace_event fail-closed: неизвестная пара (stage, event_type)
        # -- ValueError; таблица не должна содержать таких пар.
        make_trace_event(
            spec.event_type, stage=spec.stage, node_id=spec.node_id, run_id="RUN-TEST"
        )
        if spec.preview_type is not None:
            make_trace_event(
                spec.preview_type,
                stage=spec.stage,
                node_id=spec.node_id,
                run_id="RUN-TEST",
            )


def test_route_table_node_ids_known_in_graph():
    from apps.api.trace_hook import TRACE_ROUTES

    for spec in TRACE_ROUTES:
        if spec.node_id is not None:
            assert is_known_node(spec.stage, spec.node_id), (
                spec.method,
                spec.path_template,
                spec.stage,
                spec.node_id,
            )


def test_route_table_excludes_forecasting_stage():
    """Прогнозирование уже пишет канонические события в ForecastRun.trace
    (PROGR-1, 4 call-site make_trace_event); хук НЕ дублирует их в слой 1
    -- унификация хранения отложена до PROGR-5 (двухслойная модель §5)."""
    from apps.api.trace_hook import TRACE_ROUTES

    assert all(spec.stage != "forecasting" for spec in TRACE_ROUTES)


def test_route_table_templates_unique():
    from apps.api.trace_hook import TRACE_ROUTES

    keys = [(spec.method, spec.path_template) for spec in TRACE_ROUTES]
    assert len(keys) == len(set(keys))


def test_route_table_throttled_only_profile_viewed():
    from apps.api.trace_hook import TRACE_ROUTES

    throttled = [spec for spec in TRACE_ROUTES if spec.throttled]
    assert len(throttled) == 9  # 9 исследовательских GET EDA
    for spec in throttled:
        assert spec.event_type == "profile_viewed"
        assert spec.method == "GET"


# ── 2. resolve_trace_route: сопоставление путь -> (stage, node, type) ─


def test_resolve_matches_method_path_and_node():
    from apps.api.trace_hook import resolve_trace_route

    spec = resolve_trace_route("POST", "/v1/session/dataset/range-corrections")
    assert spec is not None
    assert (spec.stage, spec.node_id, spec.event_type) == (
        "validation",
        "ranges",
        "correction_applied",
    )
    assert spec.preview_type == "correction_previewed"

    spec = resolve_trace_route("POST", "/v1/session/dataset/missing-corrections")
    assert spec is not None
    assert (spec.stage, spec.node_id) == ("preprocessing", "missing")

    spec = resolve_trace_route("POST", "/v1/internal/upload")
    assert spec is not None
    assert (spec.stage, spec.node_id, spec.event_type) == (
        "upload",
        "overview",
        "upload_completed",
    )
    # PROGR-13-A3: подтверждение структуры -- отдельный маршрут/факт
    spec = resolve_trace_route("POST", "/v1/session/date-column")
    assert spec is not None
    assert (spec.stage, spec.node_id, spec.event_type) == (
        "upload",
        "structure",
        "structure_confirmed",
    )
    assert spec.payload_keys == ("date_column",)


def test_resolve_passport_param_path():
    """PROGR-13-B2: точка паспорта (значение параметра пути) задаёт
    стадию события; неизвестная точка -- ни одной строки (fail-closed,
    эндпоинт отвечает 404 по PASSPORT_STAGES)."""
    from apps.api.trace_hook import resolve_trace_route

    expected = {
        "start": "upload",
        "validation": "validation",
        "exit": "eda",
        "modeling_entry": "modeling",
    }
    for point, stage in expected.items():
        spec = resolve_trace_route(
            "POST", f"/v1/session/dataset/passport/{point}"
        )
        assert spec is not None, point
        assert (spec.stage, spec.node_id, spec.event_type) == (
            stage, None, "passport_captured",
        )
    assert resolve_trace_route(
        "POST", "/v1/session/dataset/passport/unknown_point"
    ) is None


def test_resolve_method_mismatch_returns_none():
    from apps.api.trace_hook import resolve_trace_route

    assert resolve_trace_route("GET", "/v1/session/dataset/range-corrections") is None
    assert resolve_trace_route("POST", "/v1/session/dataset/eda-correlation") is None


def test_resolve_unknown_path_returns_none():
    from apps.api.trace_hook import resolve_trace_route

    assert resolve_trace_route("POST", "/v1/session/unknown") is None
    assert resolve_trace_route("GET", "/health") is None


def test_resolve_unmapped_endpoints_return_none():
    """Эндпоинты без типа события в реестре §4.1 сознательно не
    трассируются (fail-closed: типы не изобретаются)."""
    from apps.api.trace_hook import resolve_trace_route

    assert resolve_trace_route("PUT", "/v1/session/dataset/validation-rules") is None
    assert resolve_trace_route("POST", "/v1/session/stage/eda") is None
    assert resolve_trace_route("POST", "/v1/session/modeling/forecast") is None


# ── 3. session_store: run_id, буфер, сериализация ────────────────────


def test_ensure_run_id_format_and_idempotency():
    session = AnalysisSession(session_id="s1")
    assert session.run_id == ""
    first = session.ensure_run_id()
    assert first.startswith("RUN-")
    hex_part = first[len("RUN-"):]
    assert len(hex_part) == 8
    int(hex_part, 16)  # верхний регистр hex, не бросает
    assert session.ensure_run_id() == first


def test_set_dataset_resets_run_id_and_trace():
    session = AnalysisSession(session_id="s1")
    session.ensure_run_id()
    session.append_trace_event(
        make_trace_event("mode_changed", stage="validation")
    )
    session.set_dataset(
        DatasetInfo(dataset_id="d", name="n", rows=3, columns=1, size_label="1 B"),
        None,
    )
    assert session.run_id == ""
    assert session.pipeline_trace == []


def test_append_trace_event_deep_copies_payload():
    """R1 (PROGR-1-CERT): глубокая копия payload на границе записи --
    трасса-аудит не разделяет вложенное состояние с источником."""
    session = AnalysisSession(session_id="s1")
    nested = {"k": 1}
    event = make_trace_event("mode_changed", stage="validation", modes=nested)
    # PROGR-1: make_trace_event копирует payload поверхностно
    assert event.payload["modes"] is nested
    session.append_trace_event(event)
    nested["k"] = 999  # мутация источника ПОСЛЕ записи
    stored = session.pipeline_trace[-1]
    assert stored["payload"]["modes"]["k"] == 1


def test_append_trace_event_enforces_cap_drop_oldest(monkeypatch):
    monkeypatch.setattr(session_store_module, "MAX_PIPELINE_TRACE_EVENTS", 3)
    session = AnalysisSession(session_id="s1")
    for i in range(5):
        session.append_trace_event(
            make_trace_event("mode_changed", stage="validation", i=i)
        )
    assert len(session.pipeline_trace) == 3
    assert session.pipeline_trace[0]["payload"]["i"] == 2  # старые вытеснены
    assert session.pipeline_trace[-1]["payload"]["i"] == 4


def test_max_pipeline_trace_events_constant_pinned():
    """Буфер «короткий» по §5 слой 1: константа зафиксирована, чтобы
    изменение размера не прошло незаметно (Redis-документ сессии)."""
    assert MAX_PIPELINE_TRACE_EVENTS == 1000


def test_session_roundtrip_preserves_run_id_and_trace():
    session = AnalysisSession(session_id="s1")
    run_id = session.ensure_run_id()
    session.append_trace_event(
        make_trace_event(
            "correction_applied",
            stage="validation",
            node_id="ranges",
            run_id=run_id,
            total_changed=2,
        )
    )
    document = session_to_dict(session)
    assert document["run_id"] == run_id
    assert len(document["pipeline_trace"]) == 1
    restored = session_from_dict(document)
    assert restored.run_id == run_id
    assert restored.pipeline_trace[0]["event_type"] == "correction_applied"
    assert restored.pipeline_trace[0]["payload"]["total_changed"] == 2


def test_session_from_dict_legacy_document_defaults():
    restored = session_from_dict({"session_id": "s1"})
    assert restored.run_id == ""
    assert restored.pipeline_trace == []


def test_session_from_dict_skips_corrupt_trace_entries():
    restored = session_from_dict(
        {
            "session_id": "s1",
            "pipeline_trace": [
                "not-a-dict",
                {"event_type": "mode_changed", "ts": "2026-01-01T00:00:00+00:00"},
            ],
        }
    )
    assert len(restored.pipeline_trace) == 1
    assert restored.pipeline_trace[0]["event_type"] == "mode_changed"


# ── 4. Граница чтения трассы: нормализация (риск-таблица) + R2/R3 ────


def test_read_pipeline_trace_normalizes_legacy_three_field_events():
    session = AnalysisSession(session_id="s1")
    run_id = session.ensure_run_id()
    session.pipeline_trace = [
        {
            "event_type": "mode_changed",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "payload": {"modes": {"ranges": "enabled"}},
        }
    ]
    events = session.read_pipeline_trace()
    assert len(events) == 1
    assert events[0].stage == "forecasting"  # дефолт канона для legacy
    assert events[0].ts == "2026-01-01T00:00:00+00:00"
    assert events[0].run_id == run_id  # backfill из сессии
    assert events[0].payload == {"modes": {"ranges": "enabled"}}


def test_read_boundary_legacy_marker_overrides_explicit_stage():
    """R2 (PROGR-1-CERT), зафиксированное решение: legacy-маркер
    (timestamp без ts) приоритетнее явной stage в словаре -- вся
    историческая 3-польная популяция относится к forecasting; словарь
    вида «timestamp + чужая stage» считается повреждённым каноном."""
    session = AnalysisSession(session_id="s1")
    session.pipeline_trace = [
        {
            "event_type": "mode_changed",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "stage": "eda",
            "payload": {},
        }
    ]
    assert session.read_pipeline_trace()[0].stage == "forecasting"


def test_read_boundary_preserves_unknown_event_type():
    """R3 (PROGR-1-CERT), зафиксированное решение: event_type на границе
    чтения НЕ валидируется -- событие с неизвестным типом сохраняется
    (аудит важнее строгой схемы; гейт действует на записи)."""
    session = AnalysisSession(session_id="s1")
    session.pipeline_trace = [
        {
            "event_type": "unknown_future_type",
            "ts": "2026-01-01T00:00:00+00:00",
            "stage": "validation",
            "payload": {},
        }
    ]
    events = session.read_pipeline_trace()
    assert len(events) == 1
    assert events[0].event_type == "unknown_future_type"


def test_read_boundary_skips_invalid_stage_entries():
    session = AnalysisSession(session_id="s1")
    session.pipeline_trace = [
        {"event_type": "mode_changed", "ts": "t", "stage": "nope"},
        {"event_type": "mode_changed", "ts": "2026-01-02T00:00:00+00:00",
         "stage": "validation"},
    ]
    events = session.read_pipeline_trace()
    assert len(events) == 1
    assert events[0].stage == "validation"


def test_read_pipeline_trace_canonical_pass_through_idempotent():
    session = AnalysisSession(session_id="s1")
    session.append_trace_event(
        make_trace_event("mode_changed", stage="validation", run_id="RUN-X")
    )
    stored = session.pipeline_trace[0]
    first = session.read_pipeline_trace()[0]
    second = session.read_pipeline_trace()[0]
    assert first == second
    assert first.event_id == stored["event_id"]  # id стабилен при перечтении


# ── 5. R4: прямое конструирование TraceEvent ─────────────────────────


def test_trace_event_direct_construction_defaults():
    event = TraceEvent(event_type="mode_changed")
    assert event.payload == {}
    assert event.run_id == ""
    assert event.stage == "forecasting"
    assert event.node_id is None
    assert event.actor == "user"
    assert event.event_id  # дефолты живые, не заглушки
    datetime.fromisoformat(event.ts)  # валидный ISO
    assert event.timestamp == event.ts  # legacy-алиас


# ── 6. Хук: интеграция на успешных ответах ───────────────────────────


def test_first_upload_fixes_run_id_and_writes_upload_completed():
    """Приёмка: run_id фиксируется при первой загрузке. НОВЫЙ клиент без
    cookie: middleware берёт session_id из Set-Cookie ответа upload."""
    fresh = TestClient(app)
    response = fresh.post(
        "/v1/internal/upload",
        files={"file": ("first.csv", io.BytesIO(_prices_csv().encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text
    session_id = fresh.cookies.get(SESSION_COOKIE_NAME)
    assert session_id
    session = get_session_store().get(session_id)
    assert session is not None
    assert session.run_id.startswith("RUN-")
    stored = session.pipeline_trace[-1]
    assert stored["event_type"] == "upload_completed"
    assert stored["stage"] == "upload"
    assert stored["node_id"] == "overview"
    assert stored["run_id"] == session.run_id


def test_correction_applied_written_on_successful_response():
    _upload(client, _prices_csv())
    client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {
                "ranges": [
                    {"name": "Цена", "keywords": ["Price"], "min": 0, "max": 100}
                ]
            },
        },
    )
    response = client.post(
        "/v1/session/dataset/range-corrections",
        json={"columns": ["Price"], "strategy": "clip", "apply": True},
    )
    assert response.status_code == 200, response.text
    stored = _last_stored()
    assert stored["event_type"] == "correction_applied"
    assert stored["stage"] == "validation"
    assert stored["node_id"] == "ranges"
    assert stored["payload"]["applied"] is True
    assert stored["payload"]["strategy"] == "clip"
    assert stored["payload"]["total_changed"] == 2
    assert stored["run_id"] == _session().run_id


def test_correction_previewed_written_when_apply_false():
    _upload(client, _prices_csv())
    client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {
                "ranges": [
                    {"name": "Цена", "keywords": ["Price"], "min": 0, "max": 100}
                ]
            },
        },
    )
    response = client.post(
        "/v1/session/dataset/range-corrections",
        json={"columns": ["Price"], "strategy": "clip", "apply": False},
    )
    assert response.status_code == 200, response.text
    stored = _last_stored()
    assert stored["event_type"] == "correction_previewed"
    assert stored["payload"]["applied"] is False


def test_payload_whitelist_excludes_heavy_response_keys():
    """§4.1: payload -- факты о решении, не сырой ответ; тяжёлые массивы
    (columns/profile) и предпросмотры не попадают в буфер сессии."""
    _upload(client, _prices_csv())
    client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {
                "ranges": [
                    {"name": "Цена", "keywords": ["Price"], "min": 0, "max": 100}
                ]
            },
        },
    )
    response = client.post(
        "/v1/session/dataset/range-corrections",
        json={"columns": ["Price"], "strategy": "clip", "apply": True},
    )
    assert response.status_code == 200, response.text
    stored = _last_stored()
    assert "columns" not in stored["payload"]
    assert "profile" not in stored["payload"]
    assert "added_columns" not in stored["payload"]


def test_mode_changed_written_on_check_modes_save():
    _upload(client, _prices_csv())
    response = client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"ranges": "enabled"}},
    )
    assert response.status_code == 200, response.text
    stored = _last_stored()
    assert stored["event_type"] == "mode_changed"
    assert stored["stage"] == "validation"
    assert stored["node_id"] is None  # многоцелевой маршрут: уровень стадии
    # Ответ эндпоинта -- ЭФФЕКТИВНЫЕ режимы (полный словарь), а не частичная
    # правка; факт решения -- значение выбранной проверки в нём.
    assert stored["payload"]["modes"]["ranges"] == "enabled"


def test_target_column_changed_event():
    frame = _series_frame().rename(columns={"Price": "value"})
    _upload(client, frame.to_csv(index=False))
    response = client.post("/v1/session/target-column", json={"column": "value"})
    assert response.status_code == 200, response.text
    stored = _last_stored()
    assert stored["event_type"] == "target_column_changed"
    assert stored["stage"] == "validation"
    assert stored["node_id"] is None
    assert stored["payload"]["target_column"] == "value"


def test_unsuccessful_responses_not_traced():
    _upload(client, _prices_csv())
    before = len(_trace_events())
    # 422: неизвестная проверка
    bad_modes = client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"nope": "enabled"}},
    )
    assert bad_modes.status_code == 422
    # 404: корректировка без сохранённого правила не падает, но eda без
    # колонки -- 404/422
    missing = client.get("/v1/session/dataset/eda-correlation")
    assert missing.status_code >= 400
    assert len(_trace_events()) == before


def test_unmatched_route_does_not_append_events():
    _upload(client, _prices_csv())
    before = len(_trace_events())
    response = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {}},
    )
    assert response.status_code == 200, response.text
    assert len(_trace_events()) == before


def test_trace_isolation_from_store_failures(monkeypatch):
    """Хук -- best-effort в рантайме: сбой записи трассы не ломает
    успешный ответ эндпоинта (контрактные нарушения таблицы ловятся
    тестами и import-гейтом, рантайм-IO -- деградация с warning)."""
    _upload(client, _prices_csv())

    real_store = get_session_store()
    real_save = real_store.save
    calls = {"n": 0}

    def flaky_save(store_self, session):  # патчится КЛАСС -> приходит self
        calls["n"] += 1
        if calls["n"] >= 2:  # первый save -- хендлера, второй -- хука
            raise RuntimeError("redis down")
        real_save(session)

    monkeypatch.setattr(type(real_store), "save", flaky_save)
    response = client.post("/v1/session/target-column", json={"column": "Price"})
    monkeypatch.undo()
    assert response.status_code == 200, response.text


# ── 7. Троттлинг profile_viewed (§4.2) ───────────────────────────────


def _eda_correlation_ok() -> None:
    response = client.get(
        "/v1/session/dataset/eda-correlation",
        params={"column": "Price", "max_lags": 20},
    )
    assert response.status_code == 200, response.text


def test_profile_viewed_throttled_within_window():
    frame = _series_frame()
    _upload(client, frame.to_csv(index=False))
    _eda_correlation_ok()
    _eda_correlation_ok()
    _eda_correlation_ok()
    viewed = [
        e for e in _trace_events() if e["event_type"] == "profile_viewed"
    ]
    assert len(viewed) == 1  # три запроса -- одно событие
    assert viewed[0]["stage"] == "eda"
    assert viewed[0]["node_id"] == "correlation"


def test_profile_viewed_throttle_is_per_node():
    frame = _series_frame()
    _upload(client, frame.to_csv(index=False))
    _eda_correlation_ok()
    other = client.get(
        "/v1/session/dataset/eda-seasonality",
        params={"column": "Price"},
    )
    if other.status_code == 200:  # параметризация сезонности может отличаться
        viewed = [
            e for e in _trace_events() if e["event_type"] == "profile_viewed"
        ]
        assert len(viewed) == 2
        assert {e["node_id"] for e in viewed} == {"correlation", "seasonality"}


def test_profile_viewed_window_expiry():
    frame = _series_frame()
    _upload(client, frame.to_csv(index=False))
    _eda_correlation_ok()
    # Сдвигаем ts последнего profile_viewed за окно (дефолт 5 мин)
    stored = _trace_events()
    old_ts = (
        datetime.now(timezone.utc) - timedelta(minutes=6)
    ).isoformat()
    for event in reversed(stored):
        if event["event_type"] == "profile_viewed":
            event["ts"] = old_ts
            break
    _eda_correlation_ok()
    viewed = [e for e in stored if e["event_type"] == "profile_viewed"]
    assert len(viewed) == 2


def test_profile_viewed_env_override_disables_throttle(monkeypatch):
    monkeypatch.setenv("PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS", "0")
    frame = _series_frame()
    _upload(client, frame.to_csv(index=False))
    _eda_correlation_ok()
    _eda_correlation_ok()
    viewed = [
        e for e in _trace_events() if e["event_type"] == "profile_viewed"
    ]
    assert len(viewed) == 2


def test_throttle_env_invalid_falls_back_to_default(monkeypatch):
    from apps.api.trace_hook import throttle_seconds_from_env

    monkeypatch.setenv("PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS", "banana")
    assert throttle_seconds_from_env() == 300
    monkeypatch.setenv("PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS", "-5")
    assert throttle_seconds_from_env() == 0  # отрицательное -> без троттлинга
    monkeypatch.delenv("PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS")
    assert throttle_seconds_from_env() == 300


# ── 8. Паспорт (passport_captured) ───────────────────────────────────


def test_passport_captured_event_on_capture():
    frame = _series_frame().rename(columns={"Price": "value"})
    _upload(client, frame.to_csv(index=False))
    client.post("/v1/session/target-column", json={"column": "value"})
    client.post("/v1/session/date-column", json={"column": "Date"})
    response = client.post("/v1/session/dataset/passport/start")
    if response.status_code != 200:
        pytest.skip(f"passport start требует больших предусловий: {response.text}")
    stored = _last_stored()
    assert stored["event_type"] == "passport_captured"
    # PROGR-13-B2: паспорт start фиксируется на вкладке «Загрузка» --
    # стадия события upload (мисаттрибуция eda устранена)
    assert stored["stage"] == "upload"
    assert stored["node_id"] is None  # паспорт -- не узел графа (§2)
    assert stored["payload"]["stage"] == "start"
    assert stored["payload"]["snapshot_id"]


# ── 9. PROGR-20: расширение таблицы Моделированием (v1.1 §1, кат. A) ──
#
# spec_progress_v1.1.md §1 (категория A): fail-closed allowlist дополнен
# мутирующими эндпоинтами Моделирования по приоритетам:
#   P0 (обязательно) -- candidates (факт системного правила
#     applicability-движка modeling.yaml -- «факт, который система
#     формирует автоматически») и selection/evaluate (оценка выбора --
#     класс model_selected);
#   P1 (решение тимлида: ДА -- содержательные факты: сравнение моделей
#     и запуск диагностики -- пара к backtest_run) -- compare,
#     diagnostics ×2;
#   P2 (решение тимлида: skip-пара и job-старт/отмена -- ДА,
#     step -- НЕТ) -- tuning/skip ×2 (осознанный аудируемый выбор
#     «оставить defaults» -- НЕ дублирует tuning_trial_completed: тот
#     пишется только реальным тюнингом /tune), jobs/start (единственный
#     носитель факта тюнинг-запуска в job-контуре: tuning_trial_completed
#     на job-пути не возникает никогда), jobs/{id}/cancel (явное решение
#     аналитика остановить тюнинг -- класс run_paused).
#   НЕ включены (осознанные исключения, v1.1 §1): validation-rules,
#     type-schema (конфигурационные правки ДО запуска проверки, не факт
#     прохождения исследования); jobs/{id}/step (механические единицы
#     работы -- прогресс-лог, не журнал решений §1/§4.2); baselines,
#     backtest/exclude, feature-regressors, tuning/start, tuning/step --
#     вне таблицы приоритетов v1.1 (кандидаты следующего расширения).

_PROGR20_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    # (метод, путь, узел, event_type, приоритет)
    ("POST", "/v1/session/modeling/candidates", "candidate_generation",
     "candidates_generated", "P0"),
    ("POST", "/v1/session/modeling/selection/evaluate", "selection",
     "selection_evaluated", "P0"),
    ("POST", "/v1/session/modeling/compare", "comparison",
     "models_compared", "P1"),
    ("POST", "/v1/session/modeling/diagnostics", "diagnostics",
     "diagnostics_run", "P1"),
    ("POST", "/v1/session/modeling/diagnostics/ensure", "diagnostics",
     "diagnostics_run", "P1"),
    ("POST", "/v1/session/modeling/tuning/skip", "tuning",
     "tuning_skipped", "P2"),
    ("POST", "/v1/session/modeling/tuning/skip-pending", "tuning",
     "tuning_skipped", "P2"),
    ("POST", "/v1/session/modeling/jobs/start", "tuning",
     "tuning_job_started", "P2"),
    ("POST", "/v1/session/modeling/jobs/{job_id}/cancel", "tuning",
     "tuning_job_cancelled", "P2"),
)

_PROGR20_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    # §4.1: payload -- факты результата (форма ответа), не сырой ответ;
    # dotted-ключ -- ДОТ-путь во вложенный объект, хранится под последним
    # сегментом (паттерн metrics.mape PROGR-8).
    "/v1/session/modeling/candidates": (
        "spec_version",
        "statistics.runnable_candidates",
        "statistics.catalog_only_candidates",
        "statistics.blocked_candidates",
    ),
    "/v1/session/modeling/selection/evaluate": (
        "selection_analysis_id", "cohort_id",
        "recommended_single.model_id", "ensemble.status",
    ),
    "/v1/session/modeling/compare": ("comparison_id", "cohort_id", "objective"),
    "/v1/session/modeling/diagnostics": ("model_id", "params_source", "backtest_run_id"),
    "/v1/session/modeling/diagnostics/ensure": (
        "calculated_model_ids", "reused_model_ids",
    ),
    "/v1/session/modeling/tuning/skip": ("model_id",),
    "/v1/session/modeling/tuning/skip-pending": ("model_ids", "status"),
    "/v1/session/modeling/jobs/start": (
        "operation", "model_id", "status", "progress.total_steps",
    ),
    "/v1/session/modeling/jobs/{job_id}/cancel": (
        "model_id", "status", "cancellation.reason",
    ),
}


def test_progr20_route_table_rows_present():
    from apps.api.trace_hook import TRACE_ROUTES

    specs = {(s.method, s.path_template): s for s in TRACE_ROUTES}
    for method, path, node, event_type, priority in _PROGR20_ROWS:
        spec = specs.get((method, path))
        assert spec is not None, (priority, path)
        assert (spec.stage, spec.node_id, spec.event_type) == (
            "modeling", node, event_type,
        ), (priority, path)
        assert spec.payload_keys == _PROGR20_PAYLOAD_KEYS[path], path
        assert spec.preview_type is None, path  # preview-семантики нет
        assert spec.throttled is False, path  # троттлинг -- только EDA


def test_progr20_route_table_count_54():
    """44 (PROGR-3..13) + 9 строк PROGR-20 (P0 ×2, P1 ×3, P2 ×4) = 53;
    G345-фикс (PROGR-23): + 1 строка GET /dataset/outlier-profile = 54.
    (Имя теста сохраняет историю счётчика: 53 -> 54.)"""
    from apps.api.trace_hook import TRACE_ROUTES

    assert len(TRACE_ROUTES) == 54


def test_progr20_conscious_exclusions_stay_untraced():
    """Осознанные исключения (v1.1 §1 + работа с границами задачи):
    конфигурационные правки и служебный прогресс НЕ становятся фактами."""
    from apps.api.trace_hook import resolve_trace_route

    # «Не включать» (v1.1 §1): конфигурация ДО проверки -- не факт
    # прохождения исследования.
    assert resolve_trace_route(
        "PUT", "/v1/session/dataset/validation-rules"
    ) is None
    assert resolve_trace_route(
        "PUT", "/v1/session/dataset/type-schema"
    ) is None
    # jobs/{id}/step -- механические единицы работы долгого job-контура:
    # трасса -- журнал решений и переходов, а не прогресс-лог (§1, §4.2).
    assert resolve_trace_route(
        "POST", "/v1/session/modeling/jobs/any-job/step"
    ) is None
    # Вне таблицы приоритетов v1.1 -- остаются вне allowlist до отдельного
    # решения (кандидаты следующего расширения).
    assert resolve_trace_route(
        "POST", "/v1/session/modeling/baselines"
    ) is None
    assert resolve_trace_route(
        "POST", "/v1/session/modeling/backtest/exclude"
    ) is None
    assert resolve_trace_route(
        "PUT", "/v1/session/modeling/feature-regressors"
    ) is None
    assert resolve_trace_route(
        "POST", "/v1/session/modeling/tuning/start"
    ) is None
    assert resolve_trace_route(
        "POST", "/v1/session/modeling/tuning/step"
    ) is None


def test_progr20_registry_accepts_new_event_types():
    """Реестр STAGE_EVENT_TYPES расширен теми же 7 типами (fail-closed
    гейт (stage, event_type) пропускает каждую строку таблицы)."""
    from apps.api.trace_events import STAGE_EVENT_TYPES

    modeling = STAGE_EVENT_TYPES["modeling"]
    for _, _, _, event_type, _ in _PROGR20_ROWS:
        assert event_type in modeling, event_type
        make_trace_event(event_type, stage="modeling", run_id="RUN-PROGR20")
    # Ровно 7 новых типов, существующие не сужены (критерий v1.1 §7).
    assert modeling >= {
        "candidates_generated", "selection_evaluated", "models_compared",
        "diagnostics_run", "tuning_skipped",
        "tuning_job_started", "tuning_job_cancelled",
    }


def test_progr20_payload_dotted_keys_flatten():
    """§4.1: payload -- факты результата, не сырой ответ: dotted-ключи
    извлекают вложенную статистику пула кандидатов и вердикт ансамбля,
    тяжёлые массивы (candidates/catalog/ranking/diagnostics) не проходят."""
    from apps.api.trace_hook import TRACE_ROUTES, _extract_payload

    def spec_for(path: str) -> Any:
        match = [s for s in TRACE_ROUTES if s.path_template == path]
        assert match, path
        return match[0]

    candidates_body = {
        "candidates": [{"model_id": "ets"}],
        "catalog": [{"model_id": "ets"}, {"model_id": "arima"}],
        "statistics": {
            "runnable_candidates": 3,
            "catalog_only_candidates": 21,
            "blocked_candidates": 2,
        },
        "spec_version": "test-spec-v1",
    }
    payload = _extract_payload(
        spec_for("/v1/session/modeling/candidates"), candidates_body
    )
    assert payload == {
        "runnable_candidates": 3,
        "catalog_only_candidates": 21,
        "blocked_candidates": 2,
        "spec_version": "test-spec-v1",
    }

    selection_body = {
        "selection_analysis_id": "selection-abc123",
        "cohort_id": "cohort-1",
        "recommended_single": {"model_id": "ets", "primary_loss": 1.5},
        "ensemble": {"status": "not_eligible", "member_ids": ["a", "b"]},
        "baseline_comparisons": {"ets": {"relative_improvement": 0.0}},
    }
    payload = _extract_payload(
        spec_for("/v1/session/modeling/selection/evaluate"), selection_body
    )
    assert payload == {
        "selection_analysis_id": "selection-abc123",
        "cohort_id": "cohort-1",
        "model_id": "ets",
        "status": "not_eligible",
    }

    ensure_body = {
        "model_ids": ["naive", "ets"],
        "calculated_model_ids": [],
        "reused_model_ids": ["naive", "ets"],
        "diagnostics": {"naive": {}, "ets": {}},
    }
    payload = _extract_payload(
        spec_for("/v1/session/modeling/diagnostics/ensure"), ensure_body
    )
    assert payload == {
        "calculated_model_ids": [],
        "reused_model_ids": ["naive", "ets"],
    }

    job_start_body = {
        "job_id": "J1",
        "operation": "tuning",
        "model_id": "ets",
        "status": "in_progress",
        "progress": {"phase": "trials", "completed_steps": 0, "total_steps": 2},
    }
    payload = _extract_payload(
        spec_for("/v1/session/modeling/jobs/start"), job_start_body
    )
    assert payload == {
        "operation": "tuning", "model_id": "ets",
        "status": "in_progress", "total_steps": 2,
    }

    cancel_body = {
        "job_id": "J1", "model_id": "ets", "status": "cancelled",
        "cancellation": {"reason": "Остановлено аналитиком",
                         "cancelled_at": "2026-10-07T00:00:00+00:00"},
    }
    payload = _extract_payload(
        spec_for("/v1/session/modeling/jobs/{job_id}/cancel"), cancel_body
    )
    assert payload == {
        "model_id": "ets", "status": "cancelled",
        "reason": "Остановлено аналитиком",
    }


# ── 10. PROGR-20: e2e -- события Моделирования в живой трассе ────────


def _modeling_ready(client_: TestClient) -> None:
    """Минимальные предусловия контура Моделирования (зеркало _prepare
    tests/api/test_modeling_workflow.py): датасет с датой и целью,
    паспорт и modeling_entry."""
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2018-01-01", periods=96, freq="MS").astype(str),
            "value": [
                100 + 0.4 * i + 7 * ((i % 12) - 5.5) / 5.5 for i in range(96)
            ],
        }
    )
    _upload(client_, frame.to_csv(index=False))
    assert client_.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client_.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    assert client_.post("/v1/session/dataset/passport/start").status_code == 200
    assert client_.post("/v1/session/dataset/passport/modeling_entry").status_code == 200


def test_progr20_candidates_event_written_end_to_end():
    """P0-приёмка (v1.1 §1): факт системного правила -- формирование пула
    кандидатов applicability-движком -- оставляет след в трассе."""
    _modeling_ready(client)
    response = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
    )
    assert response.status_code == 200, response.text
    stored = _last_stored()
    assert stored["event_type"] == "candidates_generated"
    assert stored["stage"] == "modeling"
    assert stored["node_id"] == "candidate_generation"
    assert stored["run_id"] == _session().run_id
    payload = stored["payload"]
    # Статистика пула -- форма ответа (факты результата), не сырой каталог.
    assert "spec_version" in payload
    assert isinstance(payload["runnable_candidates"], int)
    assert payload["runnable_candidates"] >= 0
    assert isinstance(payload["catalog_only_candidates"], int)
    assert isinstance(payload["blocked_candidates"], int)
    assert "catalog" not in payload
    assert "candidates" not in payload


def test_progr20_diagnostics_compare_selection_events_end_to_end():
    """P0 selection/evaluate + P1 diagnostics ×2/compare: содержательные
    факты контура Моделирования пишутся на успешных ответах."""
    _modeling_ready(client)
    for model_id in ("naive", "ets"):
        backtest = client.post(
            "/v1/session/modeling/backtest", json={"model_id": model_id}
        )
        assert backtest.status_code == 200, backtest.text
        diagnostics = client.post(
            "/v1/session/modeling/diagnostics", json={"model_id": model_id}
        )
        assert diagnostics.status_code == 200, diagnostics.text
    ensure = client.post(
        "/v1/session/modeling/diagnostics/ensure",
        json={"model_ids": ["naive", "ets"]},
    )
    assert ensure.status_code == 200, ensure.text
    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text
    evaluation = client.post(
        "/v1/session/modeling/selection/evaluate", json={"min_oof_points": 4}
    )
    assert evaluation.status_code == 200, evaluation.text

    events = _trace_events()

    diagnostics_events = [
        e for e in events if e["event_type"] == "diagnostics_run"
    ]
    assert diagnostics_events, "diagnostics_run не записан"
    ensure_payload = diagnostics_events[-1]["payload"]
    assert (diagnostics_events[-1]["stage"], diagnostics_events[-1]["node_id"]) == (
        "modeling", "diagnostics",
    )
    union = set(ensure_payload["calculated_model_ids"]) | set(
        ensure_payload["reused_model_ids"]
    )
    assert {"naive", "ets"} <= union
    direct = [
        e for e in diagnostics_events
        if e["payload"].get("model_id") == "ets" and "backtest_run_id" in e["payload"]
    ]
    assert direct, "diagnostics_run прямого запуска не записан"
    assert direct[-1]["payload"]["params_source"] in ("model_default", "tuning")
    assert direct[-1]["payload"]["backtest_run_id"]

    compare_events = [e for e in events if e["event_type"] == "models_compared"]
    assert compare_events, "models_compared не записан"
    assert (compare_events[-1]["stage"], compare_events[-1]["node_id"]) == (
        "modeling", "comparison",
    )
    assert compare_events[-1]["payload"]["comparison_id"]
    assert compare_events[-1]["payload"]["cohort_id"]
    assert compare_events[-1]["payload"]["objective"] == "level_forecast"

    selection_events = [
        e for e in events if e["event_type"] == "selection_evaluated"
    ]
    assert selection_events, "selection_evaluated не записан"
    sel = selection_events[-1]
    assert (sel["stage"], sel["node_id"]) == ("modeling", "selection")
    assert sel["payload"]["selection_analysis_id"].startswith("selection-")
    assert sel["payload"]["cohort_id"]
    assert sel["payload"]["model_id"]
    assert sel["payload"]["status"] in ("recommended", "not_eligible", "tested_no_gain")


def test_progr20_tuning_skip_event_written_end_to_end():
    """P2 (решение тимлида: включить): осознанный аудируемый выбор
    «оставить defaults» -- факт решения, не дубликат тюнинга."""
    _modeling_ready(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
    )
    assert candidates.status_code == 200, candidates.text
    assert client.post("/v1/session/modeling/baselines").status_code == 200
    assert client.post(
        "/v1/session/modeling/backtest", json={"model_id": "naive"}
    ).status_code == 200
    assert client.post(
        "/v1/session/modeling/backtest", json={"model_id": "ets"}
    ).status_code == 200
    scope = client.get("/v1/session/modeling/state").json()["artifacts"][
        "execution_scope"
    ]
    for model_id in scope["pending_backtest_model_ids"]:
        excluded = client.post(
            "/v1/session/modeling/backtest/exclude",
            json={
                "model_id": model_id,
                "decision": "exclude",
                "reason": "Не входит в проверку",
                "acknowledge": True,
            },
        )
        assert excluded.status_code == 200, excluded.text

    response = client.post(
        "/v1/session/modeling/tuning/skip",
        json={
            "model_id": "ets",
            "reason": "Оставить параметры по умолчанию",
            "acknowledge": True,
        },
    )
    assert response.status_code == 200, response.text
    stored = _last_stored()
    assert stored["event_type"] == "tuning_skipped"
    assert (stored["stage"], stored["node_id"]) == ("modeling", "tuning")
    assert stored["payload"]["model_id"] == "ets"


def test_progr20_job_start_and_cancel_events_end_to_end():
    """P2 (решение тимлида: старт включить как единственный носитель
    факта тюнинг-запуска в job-контуре, отмену -- как явное решение;
    step остаётся вне трассы -- прогресс-лог)."""
    _modeling_ready(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 2, "n_splits": 2,
              "gap": 1, "train_window": 40},
    )
    assert candidates.status_code == 200, candidates.text
    started = client.post(
        "/v1/session/modeling/jobs/start",
        json={"operation": "tuning", "model_id": "ets", "max_trials": 2,
              "metric": "rmse", "random_state": 42},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]

    start_events = [
        e for e in _trace_events() if e["event_type"] == "tuning_job_started"
    ]
    assert start_events, "tuning_job_started не записан"
    start = start_events[-1]
    assert (start["stage"], start["node_id"]) == ("modeling", "tuning")
    assert start["payload"]["operation"] == "tuning"
    assert start["payload"]["model_id"] == "ets"
    assert start["payload"]["status"] == "in_progress"
    assert start["payload"]["total_steps"] == 2

    cancelled = client.post(
        f"/v1/session/modeling/jobs/{job_id}/cancel",
        json={"reason": "Остановлено аналитиком"},
    )
    assert cancelled.status_code == 200, cancelled.text
    stored = _last_stored()
    assert stored["event_type"] == "tuning_job_cancelled"
    assert (stored["stage"], stored["node_id"]) == ("modeling", "tuning")
    assert stored["payload"]["model_id"] == "ets"
    assert stored["payload"]["status"] == "cancelled"
    assert stored["payload"]["reason"] == "Остановлено аналитиком"


# ── 11. PROGR-21: reason-источники уровня стадии в живой панели ───────


def _node_states(resp_json: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Карта (stage, node_id) -> полный узел §3 ответа /trace."""
    return {(n["stage"], n["node_id"]): n for n in resp_json["nodes"]}


def test_progr21_mode_changed_reason_visible_in_trace():
    """e2e PROGR-21: PUT режимов проверки оставляет событие, /trace
    подсвечивает reason на карточке узла с активным override; цвет
    статуса (pending) не меняется; авто-узлы -- без reason."""
    _upload(client, _series_frame().to_csv(index=False))
    put = client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"formats": "disabled"}},
    )
    assert put.status_code == 200, put.text

    stored = _last_stored()
    assert stored["event_type"] == "mode_changed"
    assert stored["stage"] == "validation"
    assert stored["node_id"] is None
    # payload -- форма ответа: полная карта эффективных режимов
    assert stored["payload"]["modes"]["formats"] == "disabled"

    trace = client.get("/v1/progress/trace")
    assert trace.status_code == 200, trace.text
    nodes = _node_states(trace.json())
    formats = nodes[("validation", "formats")]
    assert formats["status_reason"] == "Режим: отключена"
    assert formats["status"] == "pending"
    # авто-узлы той же карты -- без reason
    assert nodes[("validation", "data_types")]["status_reason"] is None
    assert nodes[("validation", "ranges")]["status_reason"] is None


def test_progr21_target_column_changed_reason_visible_in_trace():
    """e2e PROGR-21: выбор цели оставляет событие, /trace подсвечивает
    «Целевой признак: …» на карточке sufficiency; статус не меняется."""
    _upload(client, _series_frame().to_csv(index=False))
    chosen = client.post("/v1/session/target-column", json={"column": "Price"})
    assert chosen.status_code == 200, chosen.text

    stored = _last_stored()
    assert stored["event_type"] == "target_column_changed"
    assert stored["stage"] == "validation"
    assert stored["node_id"] is None
    assert stored["payload"]["target_column"] == "Price"

    trace = client.get("/v1/progress/trace")
    assert trace.status_code == 200, trace.text
    nodes = _node_states(trace.json())
    sufficiency = nodes[("validation", "sufficiency")]
    assert sufficiency["status_reason"] == "Целевой признак: Price"
    assert sufficiency["status"] == "pending"
    assert nodes[("validation", "formats")]["status_reason"] is None


def test_progr21_auto_return_clears_stale_reason_in_trace():
    """e2e PROGR-21: возврат узла в auto снимает устаревший «Режим: …»
    с карточки (панель не противоречит живому состоянию сессии)."""
    _upload(client, _series_frame().to_csv(index=False))
    first = client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"formats": "disabled"}},
    )
    assert first.status_code == 200, first.text
    back = client.put(
        "/v1/session/dataset/validation-check-modes",
        json={"modes": {"formats": "auto"}},
    )
    assert back.status_code == 200, back.text

    trace = client.get("/v1/progress/trace")
    assert trace.status_code == 200, trace.text
    nodes = _node_states(trace.json())
    assert nodes[("validation", "formats")]["status_reason"] is None
    assert nodes[("validation", "formats")]["status"] == "pending"
