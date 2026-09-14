# scripts/task_forecast1_e2e_smoke.py
"""E2E-смоук этапа «Прогнозирование» на актуальном session-контуре.

Полный пользовательский путь (TestClient поверх реального FastAPI-приложения):
  upload -> паспорта (start + modeling_entry) -> контекст -> backtest (naive+ets)
  -> diagnostics -> compare -> selection/evaluate -> select -> Model Card
  -> forecast (empirical_oof_quantile) -> forecast (parametric_simulation)
  -> история -> compare прогнозов -> sensitivity -> export.csv -> export.json
  -> инвалидация прогнозов повторным тюнингом.

Запуск: python scripts/task_forecast1_e2e_smoke.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from apps.api.session_store import reset_session_store_for_testing  # noqa: E402


def _csv(n: int = 96) -> str:
    t = np.arange(n, dtype=float)
    frame = pd.DataFrame({
        "date": pd.date_range("2018-01-01", periods=n, freq="MS").astype(str),
        "value": 100 + 0.4 * t + 7 * np.sin(2 * np.pi * t / 12),
        "driver": 30 + 0.2 * t,
    })
    return frame.to_csv(index=False)


def main() -> None:
    reset_session_store_for_testing()
    checks = 0

    def ok(condition: bool, label: str) -> None:
        nonlocal checks
        assert condition, f"СМОУК ПАЛ: {label}"
        checks += 1
        print(f"  [{checks:02d}] OK -- {label}")

    with TestClient(app) as client:
        print("== 1. Подготовка сессии ==")
        uploaded = client.post(
            "/v1/internal/upload",
            files={"file": ("series.csv", io.BytesIO(_csv().encode()), "text/csv")},
        )
        ok(uploaded.status_code == 200, "upload датасета")
        for payload in ({"column": "value"}, {"column": "date"}):
            endpoint = "target-column" if payload["column"] == "value" else "date-column"
            ok(
                client.post(f"/v1/session/{endpoint}", json=payload).status_code == 200,
                f"колонка {endpoint}",
            )
        ok(client.post("/v1/session/dataset/passport/start").status_code == 200, "паспорт start")
        ok(
            client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200,
            "паспорт modeling_entry",
        )
        context = client.get("/v1/session/modeling/context?horizon=2&n_splits=2")
        ok(context.status_code == 200, "modeling context (H=2, folds=2)")

        print("== 2. Бэктесты + диагностика + сравнение + выбор + карта ==")
        for model_id in ("naive", "ets"):
            backtest = client.post("/v1/session/modeling/backtest", json={"model_id": model_id})
            ok(backtest.status_code == 200, f"backtest {model_id}")
            diagnostics = client.post("/v1/session/modeling/diagnostics", json={"model_id": model_id})
            ok(diagnostics.status_code == 200, f"diagnostics {model_id}")
        comparison = client.post("/v1/session/modeling/compare", json={})
        ok(comparison.status_code == 200, "compare")
        selected_id = comparison.json()["ranking"][0]["model_id"]
        evaluation = client.post(
            "/v1/session/modeling/selection/evaluate", json={"min_oof_points": 4},
        ).json()
        ok(
            client.post(
                "/v1/session/modeling/select",
                json={
                    "model_id": selected_id,
                    "selection_analysis_id": evaluation["selection_analysis_id"],
                    "selection_signature": evaluation["selection_signature"],
                    "acknowledge_baseline_risk": True,
                    "acknowledge_selection_bias": True,
                },
            ).status_code == 200,
            f"select {selected_id}",
        )
        card = client.post("/v1/session/modeling/card", json={})
        ok(card.status_code == 200, "Model Card создана")
        card_id = card.json()["card_id"]
        card_model = card.json()["card"]["model_info"]["model_id"]
        card_horizon = card.json()["card"]["training"]["horizon"]

        summaries = client.get("/v1/session/modeling/card")
        ok(
            summaries.status_code == 200
            and summaries.json()["cards"][0]["card_id"] == card_id,
            "GET /card -- список карт",
        )

        print("== 3. Прогнозы (метод-зависимые проверки по выбранной карте) ==")
        run_first = client.post(
            "/v1/session/modeling/forecast",
            json={"model_card_id": card_id, "horizon": 2, "alpha": 0.05},
        )
        ok(run_first.status_code == 200, f"forecast по карте ({card_model})")
        first_body = run_first.json()
        if card_model in {"naive", "seasonal_naive", "drift", "mean"}:
            ok(
                first_body["ci_method"] == "empirical_oof_quantile",
                "ci_method baseline -- эмпирический (§4.2)",
            )
            ok(
                first_body["prediction_interval_coverage"] is not None,
                "coverage заполнен для эмпирического метода (§4.3)",
            )
        elif card_model in {"ets", "ets_damped"}:
            provenance = first_body["lineage"]["interval_provenance"]
            ok(
                first_body["ci_method"] == "parametric_simulation",
                "ci_method ets -- параметрическая симуляция (§4.1a)",
            )
            ok(provenance["trajectories"] > 0, "симуляция с траекториями > 0")
            ok(
                first_body["lineage"].get("parity_gate") == "ok",
                "паритет-гейт реестр vs интервальный фит",
            )
        ok(
            all(
                point["ci_lower"] <= point["value"] <= point["ci_upper"]
                for point in first_body["points"]
            ),
            "границы упорядочены (lower <= point <= upper)",
        )
        ok(
            first_body["trace_events"][-1]["event_type"] == "forecast_generated",
            "событие forecast_generated (§5.9)",
        )
        ok(
            first_body["expected_accuracy"]["rmse"] is not None
            and first_body["expected_accuracy"]["mse"] is not None,
            "expected_accuracy из бэктеста карты + mse (§5.4)",
        )

        # ETS-карта -- отдельная сессия-ветка невозможна в одном клиенте,
        # поэтому параметрическая симуляция проверяется прогнозом второй
        # карты из отдельного полного прохода (быстрая сборка).
        # Здесь вместо неё -- горизонт за validated_horizon (warning §5.1).
        run_far = client.post(
            "/v1/session/modeling/forecast",
            json={"model_card_id": card_id, "horizon": 4},
        )
        ok(run_far.status_code == 200, "forecast с горизонтом 4 > validated 2")
        ok(
            any("консервативная" in warning or "превышает" in warning for warning in run_far.json()["warnings"]),
            "метод-зависимое предупреждение о горизонте (§5.1)",
        )

        print("== 5. Сравнение, история, чувствительность, экспорт ==")
        history = client.get("/v1/session/modeling/forecast")
        ok(history.status_code == 200 and len(history.json()["forecasts"]) == 2, "история прогнозов (2)")

        compared = client.post(
            "/v1/session/modeling/forecast/compare",
            json={"forecast_ids": [first_body["forecast_id"], run_far.json()["forecast_id"]]},
        )
        ok(compared.status_code == 200, "compare двух прогнозов (§5.6)")
        ok(
            all(
                any(event["event_type"] == "forecast_compared" for event in run["trace_events"])
                for run in compared.json()["forecasts"]
            ),
            "событие forecast_compared в каждом прогнозе",
        )

        sensitivity = client.post(
            f"/v1/session/modeling/forecast/{first_body['forecast_id']}/sensitivity",
        )
        if card_model in {"ets", "ets_damped"}:
            ok(sensitivity.status_code == 200, "sensitivity ets -- веер по границам param_space (§5.7)")
            fan = sensitivity.json()["sensitivity"]
            ok(
                1 <= len(fan["combos"]) <= 8 and fan["varied_axes"],
                "веер: до 8 комбинаций, оси param_space",
            )
            ok(
                any(
                    event["event_type"] == "forecast_sensitivity_computed"
                    for event in sensitivity.json()["trace_events"]
                ),
                "событие forecast_sensitivity_computed",
            )
        else:
            ok(sensitivity.status_code == 422, "sensitivity baseline -- честный 422 (пустой param_space)")

        export_csv = client.get(f"/v1/session/modeling/forecast/{first_body['forecast_id']}/export.csv")
        ok(export_csv.status_code == 200 and "text/csv" in export_csv.headers["content-type"], "export.csv")
        lines = export_csv.text.strip().splitlines()
        ok(
            lines[0] == "date,actual,forecast,ci_lower,ci_upper" and len(lines) == 96 + 2 + 1,
            "CSV: история 96 + прогноз 2 + заголовок",
        )
        export_json = client.get(f"/v1/session/modeling/forecast/{first_body['forecast_id']}/export.json")
        ok(export_json.status_code == 200 and export_json.json()["history"]["values"], "export.json самодостаточен")
        ok(
            any(event["event_type"] == "forecast_exported" for event in export_json.json()["trace_events"]),
            "событие forecast_exported",
        )
        trace_png = client.post(
            f"/v1/session/modeling/forecast/{first_body['forecast_id']}/trace",
            json={"event_type": "forecast_exported", "format": "png"},
        )
        ok(trace_png.status_code == 200, "клиентский PNG-экспорт фиксируется /trace")

        print("== 6. Инвалидация прогнозов вместе с картами ==")
        tuned = client.post("/v1/session/modeling/tune", json={"model_id": "ets", "max_trials": 1})
        ok(tuned.status_code == 200, "повторный тюнинг")
        state = client.get("/v1/session/modeling/state").json()
        ok(state["artifacts"].get("forecasts", {}) == {}, "прогнозы инвалидированы вместе с картами")

        print("== 7. Параметрическая симуляция (ETS) -- отдельный полный проход ==")
        reset_session_store_for_testing()
        client2 = TestClient(app)
        client2.post(
            "/v1/internal/upload",
            files={"file": ("series2.csv", io.BytesIO(_csv().encode()), "text/csv")},
        )
        client2.post("/v1/session/target-column", json={"column": "value"})
        client2.post("/v1/session/date-column", json={"column": "date"})
        client2.post("/v1/session/dataset/passport/start")
        client2.post("/v1/session/dataset/passport/modeling_entry")
        client2.get("/v1/session/modeling/context?horizon=2&n_splits=2")
        # Прямая карта ets: только её бэктест нужен для selection из 2 моделей --
        # добираем naive как baseline.
        for model_id in ("naive", "ets"):
            assert client2.post("/v1/session/modeling/backtest", json={"model_id": model_id}).status_code == 200
            assert client2.post("/v1/session/modeling/diagnostics", json={"model_id": model_id}).status_code == 200
        comparison2 = client2.post("/v1/session/modeling/compare", json={})
        ranking = comparison2.json()["ranking"]
        selected2 = next((item["model_id"] for item in ranking if item["model_id"] == "ets"), ranking[0]["model_id"])
        evaluation2 = client2.post(
            "/v1/session/modeling/selection/evaluate", json={"min_oof_points": 4},
        ).json()
        assert client2.post(
            "/v1/session/modeling/select",
            json={
                "model_id": selected2,
                "selection_analysis_id": evaluation2["selection_analysis_id"],
                "selection_signature": evaluation2["selection_signature"],
                "acknowledge_baseline_risk": True,
                "acknowledge_selection_bias": True,
            },
        ).status_code == 200
        card2 = client2.post("/v1/session/modeling/card", json={}).json()
        run_ets = client2.post(
            "/v1/session/modeling/forecast",
            json={"model_card_id": card2["card_id"], "horizon": 2},
        )
        ok(run_ets.status_code == 200, "forecast ets")
        ets_body = run_ets.json()
        if ets_body["model_id"] == "ets":
            provenance = ets_body["lineage"]["interval_provenance"]
            ok(ets_body["ci_method"] == "parametric_simulation", "ci_method ets -- симуляция")
            ok(provenance["trajectories"] > 0, "симуляция с траекториями > 0")
            ok(provenance["api"] == "HoltWintersResults.simulate", "API -- HoltWintersResults.simulate")
            ok(
                ets_body["lineage"].get("parity_gate") == "ok",
                "паритет-гейт реестр vs интервальный фит (§3/§4.1a)",
            )
        else:
            print("  -- карта выбрана как naive; симуляция покрыта unit-тестами")

    print(f"\nE2E SMOKE OK -- {checks} проверок пройдено")


if __name__ == "__main__":
    main()
