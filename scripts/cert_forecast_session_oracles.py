# scripts/cert_forecast_session_oracles.py
# Сертификационный аудит Task FORECAST-1: API-оракулы session-контура
# на СОБСТВЕННЫХ данных аудитора (другой DGP/сетка/имена колонок).
# O18..O24: freshness-гейт, CSV-структура, самодостаточность JSON,
# жизненный цикл стадии, трасса, инвалидация, список карт.
from __future__ import annotations

import csv
import io
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/z/my-project/CISStat-TS-Analysis")

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.session_store import reset_session_store_for_testing  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def check(oracle_id: str, description: str, fn) -> None:
    reset_session_store_for_testing()
    try:
        with TestClient(app) as client:
            fn(client)
        RESULTS.append((oracle_id, "PASS", description))
        print(f"[PASS] {oracle_id}: {description}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((oracle_id, "FAIL", f"{description} :: {type(exc).__name__}: {exc}"))
        print(f"[FAIL] {oracle_id}: {description} :: {exc}")
    finally:
        reset_session_store_for_testing()


def my_csv(n: int = 132) -> str:
    """Собственный DGP аудитора: дневная сетка, квартальный сезонный пик,
    тренд -- имена колонок отличаются от фикстур коллеги."""
    rng = np.random.default_rng(40407)
    t = np.arange(n, dtype=float)
    frame = pd.DataFrame({
        "moment": pd.date_range("2023-01-03", periods=n, freq="D").astype(str),
        "load": 40.0 + 0.09 * t + 6.0 * np.sin(2 * np.pi * t / 91.25) + rng.normal(0, 0.8, n),
    })
    return frame.to_csv(index=False)


def prepare(client: TestClient, horizon: int = 3) -> dict:
    uploaded = client.post(
        "/v1/internal/upload",
        files={"file": ("myload.csv", io.BytesIO(my_csv().encode()), "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post("/v1/session/target-column", json={"column": "load"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "moment"}).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200
    context = client.get("/v1/session/modeling/context?horizon=3&n_splits=2")
    assert context.status_code == 200, context.text

    for model_id in ("naive", "ets"):
        backtest = client.post("/v1/session/modeling/backtest", json={"model_id": model_id})
        assert backtest.status_code == 200, backtest.text
        diagnostics = client.post("/v1/session/modeling/diagnostics", json={"model_id": model_id})
        assert diagnostics.status_code == 200, diagnostics.text
    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text
    selected_id = comparison.json()["ranking"][0]["model_id"]
    evaluation = client.post("/v1/session/modeling/selection/evaluate", json={"min_oof_points": 4}).json()
    selected = client.post("/v1/session/modeling/select", json={
        "model_id": selected_id,
        "selection_analysis_id": evaluation["selection_analysis_id"],
        "selection_signature": evaluation["selection_signature"],
        "acknowledge_baseline_risk": True,
        "acknowledge_selection_bias": True,
    })
    assert selected.status_code == 200, selected.text
    card = client.post("/v1/session/modeling/card", json={})
    assert card.status_code == 200, card.text
    return card.json()


# ── O18: freshness-гейт -- изменённый ряд -> 409 ──────────────────


def o18_freshness_gate(client: TestClient) -> None:
    card = prepare(client)
    # Мутирую ряд: прогноз по stale-карте обязан получить 409.
    client.post(
        "/v1/internal/upload",
        files={"file": ("myload2.csv", io.BytesIO(my_csv(n=140).encode()), "text/csv")},
    )
    response = client.post("/v1/session/modeling/forecast", json={
        "model_card_id": card["card_id"],
    })
    assert response.status_code == 409, f"ожидался 409, получен {response.status_code}: {response.text}"


# ── O19: CSV-экспорт -- структура и согласованность с run ─────────


def o19_csv_structure(client: TestClient) -> None:
    card = prepare(client)
    run = client.post("/v1/session/modeling/forecast", json={
        "model_card_id": card["card_id"], "alpha": 0.10,
    }).json()
    response = client.get(f"/v1/session/modeling/forecast/{run['forecast_id']}/export.csv")
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == ["date", "actual", "forecast", "ci_lower", "ci_upper"], rows[0]
    history = run["history"]
    n_history = len(history["values"])
    body = rows[1:]
    assert len(body) == n_history + run["horizon"], (
        f"строк {len(body)} != история {n_history} + горизонт {run['horizon']}"
    )
    for i, label in enumerate(history["labels"]):
        assert body[i][0] == label
        assert float(body[i][1]) == history["values"][i]
        assert body[i][2] == "" and body[i][3] == "" and body[i][4] == ""
    for j, point in enumerate(run["points"]):
        row = body[n_history + j]
        assert row[0] == point["date"]
        assert row[1] == ""
        assert float(row[2]) == point["value"]
        assert float(row[3]) == point["ci_lower"]
        assert float(row[4]) == point["ci_upper"]


# ── O20: JSON-экспорт самодостаточен (§5.5) ───────────────────────


def o20_json_self_sufficiency(client: TestClient) -> None:
    card = prepare(client)
    run = client.post("/v1/session/modeling/forecast", json={
        "model_card_id": card["card_id"],
    }).json()
    response = client.get(f"/v1/session/modeling/forecast/{run['forecast_id']}/export.json")
    assert response.status_code == 200
    payload = response.json()
    for key in (
        "forecast_id", "model_card_id", "model_id", "generated_at", "horizon",
        "alpha", "ci_method", "points", "expected_accuracy", "warnings",
        "trace_events", "history", "lineage",
    ):
        assert key in payload, f"самодостаточность нарушена: нет {key}"
    assert payload["expected_accuracy"], "expected_accuracy пуст"
    assert payload["history"]["values"], "history пуст -- CSV/график не восстановимы"


# ── O21: жизненный цикл стадии (in_progress -> done после экспорта) ─


def o21_stage_lifecycle(client: TestClient) -> None:
    card = prepare(client)
    run = client.post("/v1/session/modeling/forecast", json={
        "model_card_id": card["card_id"],
    }).json()
    stages_after_forecast = client.get("/v1/session/current").json()["stages"]
    assert stages_after_forecast["forecasting"] == "in_progress", stages_after_forecast
    client.get(f"/v1/session/modeling/forecast/{run['forecast_id']}/export.csv")
    stages_after_export = client.get("/v1/session/current").json()["stages"]
    assert stages_after_export["forecasting"] == "done", stages_after_export


# ── O22: трасса -- forecast_generated, затем exported, ISO-time ───


def o22_trace_events_chain(client: TestClient) -> None:
    from datetime import datetime

    card = prepare(client)
    run = client.post("/v1/session/modeling/forecast", json={
        "model_card_id": card["card_id"], "horizon": 4,
    }).json()
    fid = run["forecast_id"]
    client.get(f"/v1/session/modeling/forecast/{fid}/export.json")
    client.post(f"/v1/session/modeling/forecast/{fid}/trace", json={"format": "png"})
    final = client.get(f"/v1/session/modeling/forecast/{fid}").json()
    types = [event["event_type"] for event in final["trace_events"]]
    assert types == ["forecast_generated", "forecast_exported", "forecast_exported"], types
    for event in final["trace_events"]:
        stamp = datetime.fromisoformat(event["timestamp"])
        assert stamp.tzinfo is not None, "timestamp обязан быть ISO с таймзоной"
    generated = final["trace_events"][0]["payload"]
    assert generated["model_card_id"] == card["card_id"]
    assert generated["horizon"] == 4
    assert generated["ci_method"] == final["ci_method"]
    # Повторный forecast_generated создаёт НОВЫЙ run со своей трассой.
    second = client.post("/v1/session/modeling/forecast", json={
        "model_card_id": card["card_id"], "horizon": 4,
    }).json()
    assert len(second["trace_events"]) == 1
    assert second["forecast_id"] != fid


# ── O23: инвалидация прогнозов вместе с картами ───────────────────


def o23_invalidation_with_cards(client: TestClient) -> None:
    card = prepare(client)
    created = client.post("/v1/session/modeling/forecast", json={
        "model_card_id": card["card_id"],
    }).json()
    assert client.get(f"/v1/session/modeling/forecast/{created['forecast_id']}").status_code == 200
    # Новый бэктест инвалидирует карты -> прогнозы уходят синхронно.
    backtest = client.post("/v1/session/modeling/backtest", json={"model_id": "drift"})
    assert backtest.status_code == 200, backtest.text
    gone = client.get(f"/v1/session/modeling/forecast/{created['forecast_id']}")
    assert gone.status_code == 404, "прогноз пережил инвалидацию карт"
    history = client.get("/v1/session/modeling/forecast").json()
    assert history["forecasts"] == [], "история не очищена"
    stages = client.get("/v1/session/current").json()["stages"]
    assert stages["forecasting"] == "pending", stages


# ── O24: сравнение требует 2..4 существующих различных прогнозов ──


def o24_compare_rules(client: TestClient) -> None:
    card = prepare(client)
    first = client.post("/v1/session/modeling/forecast", json={
        "model_card_id": card["card_id"], "horizon": 3,
    }).json()
    second = client.post("/v1/session/modeling/forecast", json={
        "model_card_id": card["card_id"], "horizon": 4,
    }).json()
    single = client.post("/v1/session/modeling/forecast/compare", json={
        "forecast_ids": [first["forecast_id"]],
    })
    assert single.status_code == 422, single.status_code
    dupes = client.post("/v1/session/modeling/forecast/compare", json={
        "forecast_ids": [first["forecast_id"], first["forecast_id"]],
    })
    assert dupes.status_code == 422, dupes.status_code
    missing = client.post("/v1/session/modeling/forecast/compare", json={
        "forecast_ids": [first["forecast_id"], "no-such-id"],
    })
    assert missing.status_code == 404, missing.status_code
    ok = client.post("/v1/session/modeling/forecast/compare", json={
        "forecast_ids": [first["forecast_id"], second["forecast_id"]],
    })
    assert ok.status_code == 200, ok.text
    returned = ok.json()["forecasts"]
    assert [run["forecast_id"] for run in returned] == [first["forecast_id"], second["forecast_id"]]
    for run in returned:
        assert any(e["event_type"] == "forecast_compared" for e in run["trace_events"])


def main() -> int:
    check("O18", "freshness-гейт: изменённый ряд -> 409", o18_freshness_gate)
    check("O19", "CSV: заголовок/структура/согласованность с run", o19_csv_structure)
    check("O20", "JSON-экспорт самодостаточен (§5.5)", o20_json_self_sufficiency)
    check("O21", "стадия: in_progress -> done после экспорта", o21_stage_lifecycle)
    check("O22", "трасса: generated+exported, ISO-tz, payload честный", o22_trace_events_chain)
    check("O23", "инвалидация прогнозов синхронна с картами", o23_invalidation_with_cards)
    check("O24", "compare: 2..4, без дублей, 404 на отсутствующий", o24_compare_rules)

    passed = sum(1 for _, status, _ in RESULTS if status == "PASS")
    failed = len(RESULTS) - passed
    print(f"\n=== SESSION ORACLE SUMMARY: {passed} PASS / {failed} FAIL из {len(RESULTS)} ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
