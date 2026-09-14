# tests/api/test_forecasting_session.py
# TDD RED: session-контур модуля Прогнозирование (роуты /v1/session/modeling/forecast*).
# Полный пользовательский путь: загрузка → паспорта → контекст → бэктесты →
# диагностика → сравнение → выбор → Model Card → прогноз → история → экспорт →
# сравнение прогнозов → чувствительность.
from __future__ import annotations

import io

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


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _csv(n: int = 96) -> str:
    t = np.arange(n, dtype=float)
    frame = pd.DataFrame({
        "date": pd.date_range("2018-01-01", periods=n, freq="MS").astype(str),
        "value": 100 + 0.4 * t + 7 * np.sin(2 * np.pi * t / 12),
        "driver": 30 + 0.2 * t,
    })
    return frame.to_csv(index=False)


def _prepare_session(client: TestClient, horizon: int = 2, n_splits: int = 2) -> None:
    uploaded = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_csv().encode()), "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200
    context = client.get(
        f"/v1/session/modeling/context?horizon={horizon}&n_splits={n_splits}",
    )
    assert context.status_code == 200, context.text


def _reach_model_card(client: TestClient, horizon: int = 2, n_splits: int = 2) -> dict:
    """Полный путь до Model Card (прецедент test_modeling_workflow)."""
    _prepare_session(client, horizon=horizon, n_splits=n_splits)
    for model_id in ("naive", "ets"):
        backtest = client.post("/v1/session/modeling/backtest", json={"model_id": model_id})
        assert backtest.status_code == 200, backtest.text
        diagnostics = client.post(
            "/v1/session/modeling/diagnostics", json={"model_id": model_id},
        )
        assert diagnostics.status_code == 200, diagnostics.text
    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text
    selected_id = comparison.json()["ranking"][0]["model_id"]
    evaluation = client.post(
        "/v1/session/modeling/selection/evaluate", json={"min_oof_points": 4},
    ).json()
    selected = client.post(
        "/v1/session/modeling/select",
        json={
            "model_id": selected_id,
            "selection_analysis_id": evaluation["selection_analysis_id"],
            "selection_signature": evaluation["selection_signature"],
            "acknowledge_baseline_risk": True,
            "acknowledge_selection_bias": True,
        },
    )
    assert selected.status_code == 200, selected.text
    card = client.post("/v1/session/modeling/card", json={})
    assert card.status_code == 200, card.text
    return card.json()


# ── Список карт (аддитивный GET /card) ────────────────────────────


def test_model_card_list_endpoint_returns_summaries(client: TestClient):
    card = _reach_model_card(client)

    response = client.get("/v1/session/modeling/card")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["cards"]) == 1
    summary = body["cards"][0]
    assert summary["card_id"] == card["card_id"]
    assert summary["model_id"] == card["card"]["model_info"]["model_id"]
    assert summary["selection_kind"] == card["card"]["model_info"]["selection_kind"]
    assert "created_at" in summary


# ── Генерация прогноза ────────────────────────────────────────────


def test_forecast_requires_model_card(client: TestClient):
    _prepare_session(client)

    response = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": "missing-card"},
    )

    assert response.status_code == 404
    assert "Model Card" in response.json()["detail"]


def test_forecast_rejects_ensemble_card_honestly(client: TestClient):
    # Ensemble-карта содержит несколько членов; прогноз ансамбля -- отдельная
    # постановка (v1 честно отказывает вместо фиктивного среднего).
    card = _reach_model_card(client)
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    entry = session.modeling_artifacts["model_cards"][card["card_id"]]
    entry["card"]["model_info"]["selection_kind"] = "ensemble"
    entry["card"]["model_info"]["ensemble_members"] = ["naive", "ets"]
    store.save(session)

    response = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    )

    assert response.status_code == 422
    assert "ансамбл" in response.json()["detail"]


def test_forecast_rejects_models_outside_card_reachable_scope(client: TestClient):
    # var/garch/deepar недостижимы через Model Card (objective-изоляция
    # cohort'ов) -- fail-closed вместо фиктивного прогноза.
    card = _reach_model_card(client)
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    entry = session.modeling_artifacts["model_cards"][card["card_id"]]
    entry["card"]["model_info"]["model_id"] = "garch"
    store.save(session)

    response = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    )

    assert response.status_code == 422
    assert "garch" in response.json()["detail"]


def test_forecast_stale_card_fails_with_409(client: TestClient):
    card = _reach_model_card(client)
    # Ряд изменился после создания карты (имитация мутации данных).
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    entry = session.modeling_artifacts["model_cards"][card["card_id"]]
    entry["card"]["data_summary"]["fingerprint"] = "stale" * 16
    store.save(session)

    response = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    )

    assert response.status_code == 409
    assert "устарел" in response.json()["detail"]


def test_forecast_naive_full_run_shape_and_storage(client: TestClient):
    card = _reach_model_card(client)

    response = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["model_card_id"] == card["card_id"]
    assert run["model_id"] in {"naive", "ets"}
    assert run["ci_method"] in {
        "analytic", "parametric_simulation", "native_adapter", "empirical_oof_quantile",
    }
    assert run["horizon"] >= 1
    assert run["alpha"] == 0.05
    assert len(run["points"]) == run["horizon"]
    for step, point in enumerate(run["points"], 1):
        assert point["step"] == step
        assert point["date"]
        assert point["ci_lower"] <= point["value"] <= point["ci_upper"]
        assert isinstance(point["is_anomalous"], bool)
    # §5.4: expected_accuracy -- ИСТОРИЧЕСКИЕ метрики бэктеста карты + mse.
    assert run["expected_accuracy"]["rmse"] == card["card"]["performance"]["backtest_metrics"]["rmse"]
    assert run["expected_accuracy"]["mse"] == pytest.approx(
        run["expected_accuracy"]["rmse"] ** 2,
    )
    # §5.9: событие forecast_generated с обязательным payload.
    events = run["trace_events"]
    assert events and events[-1]["event_type"] == "forecast_generated"
    payload = events[-1]["payload"]
    assert payload["model_card_id"] == card["card_id"]
    assert payload["forecast_id"] == run["forecast_id"]
    assert "horizon" in payload and "alpha" in payload and "ci_method" in payload
    # Артефакт сохранён в сессии; стадия forecasting -- in_progress.
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert run["forecast_id"] in session.modeling_artifacts.get("forecasts", {})
    assert session.stages["forecasting"] == "in_progress"


def test_forecast_horizon_defaults_to_card_training_horizon(client: TestClient):
    card = _reach_model_card(client, horizon=3)

    response = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["horizon"] == 3


def test_forecast_custom_horizon_and_alpha_are_honored(client: TestClient):
    card = _reach_model_card(client, horizon=2)

    response = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"], "horizon": 5, "alpha": 0.10},
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["horizon"] == 5
    assert run["alpha"] == 0.10
    assert len(run["points"]) == 5
    # Горизонт 5 > validated 2: метод-зависимое предупреждение (§5.1).
    assert any("превышает" in warning or "консервативная" in warning for warning in run["warnings"])


def test_forecast_ets_runs_parametric_simulation_end_to_end(client: TestClient):
    card = _reach_model_card(client)

    response = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"], "horizon": 2},
    )

    assert response.status_code == 200, response.text
    run = response.json()
    if run["model_id"] == "ets":
        assert run["ci_method"] == "parametric_simulation"
        provenance = run["lineage"]["interval_provenance"]
        assert provenance["trajectories"] > 0
        assert provenance["api"] == "HoltWintersResults.simulate"
    else:
        assert run["ci_method"] == "empirical_oof_quantile"
        assert run["prediction_interval_coverage"] is not None


def test_forecast_rejects_alpha_outside_open_unit_interval(client: TestClient):
    card = _reach_model_card(client)

    response = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"], "alpha": 1.5},
    )

    assert response.status_code == 422


def test_forecast_history_returns_all_runs(client: TestClient):
    card = _reach_model_card(client)
    first = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"], "horizon": 2},
    )
    assert first.status_code == 200
    second = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"], "horizon": 3},
    )
    assert second.status_code == 200

    response = client.get("/v1/session/modeling/forecast")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["forecasts"]) == 2
    assert {item["forecast_id"] for item in body["forecasts"]} == {
        first.json()["forecast_id"], second.json()["forecast_id"],
    }


def test_forecast_get_by_id(client: TestClient):
    card = _reach_model_card(client)
    created = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    ).json()

    response = client.get(f"/v1/session/modeling/forecast/{created['forecast_id']}")

    assert response.status_code == 200
    assert response.json()["forecast_id"] == created["forecast_id"]

    missing = client.get("/v1/session/modeling/forecast/unknown")
    assert missing.status_code == 404


# ── Экспорт (§5.5) ────────────────────────────────────────────────


def test_forecast_export_csv_contains_history_and_forecast_columns(client: TestClient):
    card = _reach_model_card(client)
    run = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"], "horizon": 2},
    ).json()

    response = client.get(f"/v1/session/modeling/forecast/{run['forecast_id']}/export.csv")

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0] == "date,actual,forecast,ci_lower,ci_upper"
    # История (96 строк) + прогноз (2 строки) + заголовок.
    assert len(lines) == 96 + 2 + 1
    history_row = lines[1].split(",")
    assert history_row[1] != ""  # actual заполнен в истории
    assert history_row[2] == ""  # forecast пуст в истории
    forecast_row = lines[-1].split(",")
    assert forecast_row[1] == ""
    assert forecast_row[2] != "" and forecast_row[3] != "" and forecast_row[4] != ""


def test_forecast_export_json_is_self_contained_and_logs_event(client: TestClient):
    card = _reach_model_card(client)
    run = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    ).json()

    response = client.get(f"/v1/session/modeling/forecast/{run['forecast_id']}/export.json")

    assert response.status_code == 200
    body = response.json()
    # Самодостаточность (§5.5): прогноз несёт карту-ссылку, метрики, параметры.
    assert body["forecast_id"] == run["forecast_id"]
    assert body["model_card_id"] == card["card_id"]
    assert body["expected_accuracy"]
    assert body["history"]["values"]
    # GET-экспорт фиксирует forecast_exported (§5.9) и завершает этап (§10.5).
    events = body["trace_events"]
    assert any(event["event_type"] == "forecast_exported" for event in events)
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session.stages["forecasting"] == "done"


def test_forecast_png_export_event_is_recorded_via_trace_endpoint(client: TestClient):
    card = _reach_model_card(client)
    run = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    ).json()

    response = client.post(
        f"/v1/session/modeling/forecast/{run['forecast_id']}/trace",
        json={"event_type": "forecast_exported", "format": "png"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert any(
        event["event_type"] == "forecast_exported"
        and event["payload"]["format"] == "png"
        for event in body["trace_events"]
    )


# ── Сравнение прогнозов (§5.6) ────────────────────────────────────


def test_forecast_compare_returns_referenced_runs_and_logs_event(client: TestClient):
    card = _reach_model_card(client)
    first = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"], "horizon": 2},
    ).json()
    second = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"], "horizon": 3},
    ).json()

    response = client.post(
        "/v1/session/modeling/forecast/compare",
        json={"forecast_ids": [first["forecast_id"], second["forecast_id"]]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["forecast_id"] for item in body["forecasts"]} == {
        first["forecast_id"], second["forecast_id"],
    }
    # forecast_compared записан в каждый из сравниваемых прогнозов (§5.9).
    for item in body["forecasts"]:
        compared = [
            event for event in item["trace_events"]
            if event["event_type"] == "forecast_compared"
        ]
        assert compared
        assert set(compared[-1]["payload"]["forecast_ids"]) == {
            first["forecast_id"], second["forecast_id"],
        }


def test_forecast_compare_requires_two_distinct_existing_forecasts(client: TestClient):
    card = _reach_model_card(client)
    single = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    ).json()

    duplicate = client.post(
        "/v1/session/modeling/forecast/compare",
        json={"forecast_ids": [single["forecast_id"], single["forecast_id"]]},
    )
    assert duplicate.status_code == 422

    missing = client.post(
        "/v1/session/modeling/forecast/compare",
        json={"forecast_ids": [single["forecast_id"], "unknown"]},
    )
    assert missing.status_code == 404


# ── Чувствительность (§5.7) ───────────────────────────────────────


def test_forecast_sensitivity_fan_uses_param_space_corners(client: TestClient):
    card = _reach_model_card(client)
    run = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    ).json()
    model_id = run["model_id"]
    if model_id not in {"ets", "ets_damped"}:
        pytest.skip("веер проверяется на модели с непустым param_space")

    response = client.post(
        f"/v1/session/modeling/forecast/{run['forecast_id']}/sensitivity",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    fan = body["sensitivity"]
    assert fan["varied_axes"]
    assert 1 <= len(fan["combos"]) <= 8
    for combo in fan["combos"]:
        assert combo["params"]
        assert len(combo["points"]) == run["horizon"]
    # Событие чувствительности зафиксировано (§5.9).
    assert any(
        event["event_type"] == "forecast_sensitivity_computed"
        for event in body["trace_events"]
    )


def test_forecast_sensitivity_rejects_empty_param_space(client: TestClient):
    card = _reach_model_card(client)
    run = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    ).json()
    # naive (baseline) имеет пустой param_space в rules/modeling.yaml --
    # подменяем model_id артефакта (артефакт-уровень, не карта).
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    session.modeling_artifacts["forecasts"][run["forecast_id"]]["model_id"] = "naive"
    store.save(session)

    response = client.post(
        f"/v1/session/modeling/forecast/{run['forecast_id']}/sensitivity",
    )

    assert response.status_code == 422
    assert "param_space" in response.json()["detail"]


# ── Инвалидация прогнозов вместе с картами ───────────────────────


def test_forecasts_are_invalidated_together_with_model_cards(client: TestClient):
    card = _reach_model_card(client)
    run = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    ).json()
    assert run["forecast_id"]

    # Повторный тюнинг инвалидирует comparison/selection/cards (прецедент
    # test_repeated_tuning_invalidates_stale_downstream_artifacts) --
    # прогнозы, ссылающиеся на карты, обязаны уйти вместе с ними.
    tuned = client.post(
        "/v1/session/modeling/tune",
        json={"model_id": "ets", "max_trials": 1},
    )
    assert tuned.status_code == 200, tuned.text

    state = client.get("/v1/session/modeling/state").json()
    assert state["artifacts"].get("forecasts", {}) == {}
    assert state["pipeline"]["model_card"] == "pending"
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session.stages["forecasting"] == "pending"


# ── Redis-roundtrip артефактов прогноза ──────────────────────────


def test_forecast_run_survives_session_roundtrip(client: TestClient):
    from apps.api.session_store import session_from_dict, session_to_dict

    card = _reach_model_card(client)
    run = client.post(
        "/v1/session/modeling/forecast",
        json={"model_card_id": card["card_id"]},
    ).json()

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    restored = session_from_dict(session_to_dict(session))

    assert run["forecast_id"] in restored.modeling_artifacts.get("forecasts", {})
    points = restored.modeling_artifacts["forecasts"][run["forecast_id"]]["points"]
    assert len(points) == run["horizon"]
