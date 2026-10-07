# tests/api/test_progress_progr23.py
"""Task ROGR-22-REPRO-G345 fix (PROGR-23): три исправления по итогам
расследования «жёлтая карточка / зелёный Прогресс» при (iqr, cap)
(worklog9.md, PROGR-22-REPRO-G345):

  Фикс 1 -- ТРАССИРОВКА GET-ПЕРЕСЧЁТОВ (закрытие «окна лжи», Г5/Ф2):
    живой пересчёт карточки «Выбросы» (GET /dataset/outlier-profile)
    сеет payload-статусное событие outliers_profile_status (паттерн
    upload_stop_status PROGR-13-A4); dedupe -- событие пишется только
    при ИЗМЕНЕНИИ картины (status/total_outliers/method/mode), чтобы
    фокус-рефетчи (PROGR-9-FOCUS) шумом не становились.

  Фикс 3 -- СЕМАНТИКА LAST-WINS (честный исход apply, класс C5):
    apply выбросов несёт в ответе карточную шкалу (iqr-1.5, как у
    карточки) ПОСЛЕ коррекции -- status/total_outliers_after; хук
    кладёт их в payload correction_applied; движок (override с
    фолбэком) отдаёт узлу честный статус: частичная коррекция
    оставляет warning, а не безусловный done.

  Фикс 2 -- ЧЕСТНЫЙ БАННЕР (фронт, Г4/Ф3): см.
  packages/ui/components/PreprocessingOutliersPipeline.test.tsx --
  здесь только backend-носители фактов (поля ответа).

Ключевой сценарий G345: полный поток загрузка -> пропуски -> выбросы №1
-> стационарность (производная колонка с выбросами) -> карточка warning
при трейсе done («окно лжи») -> частичная фиксация C5 -> финал
card == trace.
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from app.core.node_status import (
    EVENT_NODE_STATUS,
    derive_pipeline_node_states,
    resolve_event_status,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


# ── helpers ──────────────────────────────────────────────────────────


def _g345_frame() -> pd.DataFrame:
    """Детерминированный аналог forecast_monitor_synthetic_n150.csv
    (генератор scripts/dataset_forecast_monitor.py, без шума): тренд +
    сезон M=12, 4 выброса, 3 пропуска -- на этом датасете
    воспроизводился класс C5."""
    t = np.arange(150, dtype=float)
    value = 120 + 0.55 * t + 18 * np.sin(2.0 * np.pi * (t + 2) / 12.0)
    value[25] += 110
    value[70] += 105
    value[105] += 95
    value[130] -= 135
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2013-01-01", periods=150, freq="MS").strftime("%Y-%m-%d"),
            "value": np.round(value, 2),
        }
    )
    frame.loc[[45, 87, 122], "value"] = np.nan
    return frame


def _two_columns_frame() -> pd.DataFrame:
    """Две числовые колонки с выбросами: база класса C5 без
    стационарности -- частичный выбор колонок."""
    rng = np.random.default_rng(20261007)
    base = rng.normal(0.0, 1.0, 60)
    a = base.copy()
    a[10] = 40.0
    b = base.copy()
    b[30] = -35.0
    return pd.DataFrame({"date": pd.date_range("2024-01-01", periods=60, freq="D").strftime("%Y-%m-%d"), "a": a, "b": b})


def _upload(client_: TestClient, frame: pd.DataFrame) -> None:
    response = client_.post(
        "/v1/internal/upload",
        files={"file": ("g345.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _session() -> Any:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id, "у тестового клиента нет cookie сессии"
    return get_session_store().get(session_id)


def _trace_events() -> list[dict[str, Any]]:
    return _session().pipeline_trace


def _events_of_type(event_type: str, node_id: str | None = None) -> list[dict[str, Any]]:
    return [
        e
        for e in _trace_events()
        if e.get("event_type") == event_type and (node_id is None or e.get("node_id") == node_id)
    ]


def _trace_node(client_: TestClient, stage: str, node_id: str) -> dict[str, Any]:
    response = client_.get("/v1/progress/trace")
    assert response.status_code == 200, response.text
    nodes = {n["node_id"]: n for n in response.json().get("nodes", []) if n.get("stage") == stage}
    return nodes[node_id]


def _card(client_: TestClient) -> dict[str, Any]:
    response = client_.get("/v1/session/dataset/outlier-profile?method=iqr")
    assert response.status_code == 200, response.text
    return response.json()


# ── Контур 1: таблица маршрутов + dedupe (Фикс 1) ────────────────────


class TestRouteTableOutlierProfileGet:
    def test_route_table_has_outlier_profile_get_spec(self):
        from apps.api.trace_hook import TRACE_ROUTES

        specs = [
            s for s in TRACE_ROUTES
            if s.method == "GET" and s.path_template == "/v1/session/dataset/outlier-profile"
        ]
        assert len(specs) == 1, "карточка «Выбросы» трассируется ровно одной строкой таблицы"
        spec = specs[0]
        assert spec.stage == "preprocessing"
        assert spec.node_id == "outliers"
        assert spec.event_type == "outliers_profile_status"
        assert spec.dedupe is True, "без dedupe фокус-рефетчи затопили бы трассу"
        assert set(("status", "total_outliers", "method", "mode")) <= set(spec.payload_keys)

    def test_validate_table_dedupe_requires_payload_keys(self):
        from apps.api.trace_hook import TraceRouteSpec, _validate_table

        bogus = (
            TraceRouteSpec(
                "GET", "/x", "preprocessing", "outliers",
                "outliers_profile_status", dedupe=True,
            ),
        )
        with pytest.raises(ImportError, match="dedupe"):
            _validate_table(bogus)


class TestOutlierProfileGetSeedsFacts:
    def test_get_seeds_status_event_with_payload(self):
        _upload(client, _two_columns_frame())
        card = _card(client)
        assert card["status"] == "warning"

        events = _events_of_type("outliers_profile_status", "outliers")
        assert len(events) == 1, "первый пересчёт карточки сеет событие"
        payload = events[0]["payload"]
        assert payload["status"] == "warning"
        assert payload["total_outliers"] == card["total_outliers"] > 0
        assert payload["method"] == "iqr"
        assert payload["mode"] == "auto"

    def test_get_seeds_done_event_when_clean(self):
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=40, freq="D").strftime("%Y-%m-%d"),
                "value": list(range(40)),
            }
        )
        _upload(client, frame)
        card = _card(client)
        assert card["status"] == "done"
        payload = _events_of_type("outliers_profile_status", "outliers")[0]["payload"]
        assert payload["status"] == "done"
        assert payload["total_outliers"] == 0

    def test_dedupe_skips_identical_consecutive_recalc(self):
        _upload(client, _two_columns_frame())
        _card(client)
        _card(client)
        _card(client)
        assert len(_events_of_type("outliers_profile_status", "outliers")) == 1, \
            "повторные пересчёты с НЕИЗМЕННОЙ картиной не пишутся (dedupe)"

    def test_dedupe_is_picture_based_not_event_based(self):
        """Dedupe сравнивает ПРОИЗВОДНУЮ картину узла, а не последнее
        событие того же типа: apply#1 между двумя пересчётами уже принёс
        трассе актуальную картину (статус и пост-коррекционный счётчик) --
        повторный пересчёт карточки не добавляет информации и не пишется."""
        _upload(client, _two_columns_frame())
        _card(client)
        response = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["a"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
        )
        assert response.status_code == 200, response.text
        card = _card(client)
        events = _events_of_type("outliers_profile_status", "outliers")
        assert len(events) == 1, (
            "картина узла уже актуальна (её принёс честный apply) -- "
            "пересчёт с той же картиной дедуплицируется"
        )
        assert events[0]["payload"]["total_outliers"] != card["total_outliers"], (
            "предусловие: картина между пересчётами ДЕЙСТВИТЕЛЬНО менялась "
            "(иначе тест ничего не доказывает)"
        )
        node = _trace_node(client, "preprocessing", "outliers")
        assert node["status"] == card["status"] == "warning"
        assert node["summary_count"] == card["total_outliers"], \
            "актуальную картину узлу принёс apply, а не пересчёт"

    def test_lie_window_closed_after_stationarity_apply(self):
        """Ядро Г5: после stationarity-apply (производная колонка несёт
        выбросы) живой пересчёт карточки сеет warning -- Прогресс больше
        НЕ показывает done в окне «выбросы появились -> следующая
        коррекция»."""
        _upload(client, _g345_frame())
        client.post("/v1/session/date-column", json={"column": "date"})
        missing = client.get("/v1/session/dataset/missing-profile").json()
        cols = [x["column"] for x in missing["columns"] if x.get("missing_count")]
        assert client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": cols, "strategy": "interpolate", "apply": True},
        ).status_code == 200
        card1 = _card(client)
        assert client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": card1["affected_columns"], "strategy": "cap",
                  "method": "iqr", "param": 1.5, "apply": True},
        ).status_code == 200

        profile = client.get("/v1/session/dataset/preprocessing/stationarity-profile?column=value").json()
        method = profile["profile"]["selected_method"]
        assert client.post(
            "/v1/session/dataset/preprocessing/stationarity-transformations",
            json={"column": "value", "method": method, "apply": True, "confirm_non_causal": True},
        ).status_code == 200

        card2 = _card(client)
        assert card2["status"] == "warning", "предусловие G345: карточка жёлтая"
        node = _trace_node(client, "preprocessing", "outliers")
        assert node["status"] == "warning", (
            "«окно лжи» закрыто: Прогресс показывает warning по факту "
            "пересчёта карточки, а не done от прошлой коррекции"
        )
        assert node["summary_count"] == card2["total_outliers"], \
            "бейдж узла -- то же число, что карточка (§3)"


# ── Контур 2: честный исход apply (Фикс 3, last-wins) ────────────────


class TestApplyCarriesCardScaleOutcome:
    def test_apply_response_carries_card_scale_status(self):
        """Класс C5: колонка 'b' с выбросами НЕ выбрана -- ответ несёт
        карточную шкалу (iqr-1.5) ПОСЛЕ коррекции: warning + счётчик."""
        _upload(client, _two_columns_frame())
        response = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["a"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["applied"] is True
        assert body["status"] == "warning"
        assert body["total_outliers_after"] > 0
        # карточная шкала совпадает с живой карточкой
        card = _card(client)
        assert body["total_outliers_after"] == card["total_outliers"]
        assert body["status"] == card["status"]

    def test_apply_response_done_when_card_clean(self):
        _upload(client, _two_columns_frame())
        response = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["a", "b"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "done"
        assert body["total_outliers_after"] == 0

    def test_apply_event_payload_carries_honest_outcome(self):
        _upload(client, _two_columns_frame())
        client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["a"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
        )
        applied = [e for e in _events_of_type("correction_applied", "outliers")]
        assert len(applied) == 1
        payload = applied[0]["payload"]
        assert payload["status"] == "warning"
        assert payload["total_outliers_after"] > 0

    def test_c5_final_state_card_equals_trace(self):
        """Воспроизведённое расхождение G345 (класс C5) закрыто: после
        частичной фиксации Прогресс показывает warning -- как карточка,
        а не безусловный done."""
        _upload(client, _two_columns_frame())
        client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["a"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
        )
        card = _card(client)
        assert card["status"] == "warning"
        node = _trace_node(client, "preprocessing", "outliers")
        assert node["status"] == "warning"
        assert node["summary_count"] == card["total_outliers"], \
            "бейдж -- пост-коррекционный карточный счётчик, не found мастера (Д4)"

    def test_full_g345_flow_final_card_equals_trace(self):
        """Полный поток G345 (загрузка -> пропуски -> выбросы №1 ->
        стационарность -> частичная фиксация C5): финал card == trace."""
        _upload(client, _g345_frame())
        client.post("/v1/session/date-column", json={"column": "date"})
        missing = client.get("/v1/session/dataset/missing-profile").json()
        cols = [x["column"] for x in missing["columns"] if x.get("missing_count")]
        client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": cols, "strategy": "interpolate", "apply": True},
        )
        card1 = _card(client)
        client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": card1["affected_columns"], "strategy": "cap",
                  "method": "iqr", "param": 1.5, "apply": True},
        )
        profile = client.get("/v1/session/dataset/preprocessing/stationarity-profile?column=value").json()
        client.post(
            "/v1/session/dataset/preprocessing/stationarity-transformations",
            json={"column": "value", "method": profile["profile"]["selected_method"],
                  "apply": True, "confirm_non_causal": True},
        )
        # C5: частичный выбор -- только исходная колонка, производная снята
        apply2 = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["value"], "strategy": "cap", "method": "iqr",
                  "param": 1.5, "apply": True},
        ).json()
        assert apply2["status"] == "warning"
        assert apply2["total_outliers_after"] > 0

        card_final = _card(client)
        node = _trace_node(client, "preprocessing", "outliers")
        assert card_final["status"] == "warning"
        assert node["status"] == card_final["status"], \
            "финальное расхождение «жёлтая карточка / зелёный Прогресс» устранено"


# ── Контур 2b: движок -- override с фолбэком (unit) ──────────────────


def _event_dict(event_type: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "event_id": "E",
        "run_id": "R",
        "ts": "2026-10-07T00:00:00+00:00",
        "stage": "preprocessing",
        "node_id": "outliers",
        "event_type": event_type,
        "payload": payload or {},
        "actor": "user",
        "timestamp": "2026-10-07T00:00:00+00:00",
    }


class TestResolveEventStatusOverride:
    def test_correction_applied_with_valid_payload_status_overrides_map(self):
        data = _event_dict("correction_applied", {"status": "warning", "total_outliers_after": 4})
        assert resolve_event_status(data) == "warning"

    def test_correction_applied_with_garbage_payload_status_falls_back_to_map(self):
        data = _event_dict("correction_applied", {"status": "zebra"})
        assert resolve_event_status(data) == EVENT_NODE_STATUS["correction_applied"]

    def test_correction_applied_without_payload_status_falls_back_to_map(self):
        """Обратная совместимость: весь существующий корпус коррекций
        (ответы без поля status) остаётся done."""
        data = _event_dict("correction_applied", {"total_changed": 3})
        assert resolve_event_status(data) == EVENT_NODE_STATUS["correction_applied"]

    def test_override_does_not_leak_to_other_mapped_types(self):
        """Override -- ТОЛЬКО для реестра override-типов: job-статус в
        payload другого события не переопределяет карту."""
        data = _event_dict("tuning_trial_completed", {"status": "pending"})
        assert resolve_event_status(data) == EVENT_NODE_STATUS["tuning_trial_completed"]

    def test_outliers_profile_status_is_payload_status_type(self):
        assert resolve_event_status(_event_dict("outliers_profile_status", {"status": "warning"})) == "warning"
        assert resolve_event_status(_event_dict("outliers_profile_status", {"status": "done"})) == "done"
        # мусор -- честный пропуск (не фантомный статус)
        assert resolve_event_status(_event_dict("outliers_profile_status", {"status": "zebra"})) is None


class TestEngineLastWinsHonest:
    def test_c5_event_sequence_yields_warning_with_card_count(self):
        events = [
            _event_dict("correction_previewed", {"total_outliers": 0}),
            _event_dict("correction_applied", {"status": "warning", "total_outliers_after": 4}),
        ]
        states = derive_pipeline_node_states(events)
        node = next(n for n in states if n["stage"] == "preprocessing" and n["node_id"] == "outliers")
        assert node["status"] == "warning"
        assert node["summary_count"] == 4
        assert node["status_reason"] is not None

    def test_clean_apply_yields_done(self):
        events = [
            _event_dict("correction_applied", {"status": "done", "total_outliers_after": 0}),
        ]
        states = derive_pipeline_node_states(events)
        node = next(n for n in states if n["stage"] == "preprocessing" and n["node_id"] == "outliers")
        assert node["status"] == "done"
        assert node["summary_count"] == 0

    def test_summary_count_prefers_card_scale_after_master_found(self):
        """Д4: бейдж -- пост-коррекционный карточный счётчик, даже когда
        found мастера в его шкале лежит в том же payload."""
        events = [
            _event_dict("correction_applied", {"total_outliers": 25, "total_outliers_after": 4}),
        ]
        states = derive_pipeline_node_states(events)
        node = next(n for n in states if n["stage"] == "preprocessing" and n["node_id"] == "outliers")
        assert node["summary_count"] == 4

    def test_profile_status_event_moves_reason_and_count(self):
        events = [
            _event_dict("correction_applied", {"status": "done", "total_outliers_after": 0}),
            _event_dict("outliers_profile_status", {"status": "warning", "total_outliers": 4,
                                                    "method": "iqr", "mode": "auto"}),
        ]
        states = derive_pipeline_node_states(events)
        node = next(n for n in states if n["stage"] == "preprocessing" and n["node_id"] == "outliers")
        assert node["status"] == "warning", "last-wins: последний факт решает"
        assert node["summary_count"] == 4
        assert node["status_reason"] == "Живой профиль выбросов пересчитан"
