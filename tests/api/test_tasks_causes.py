# tests/api/test_tasks_causes.py
#
# TDD RED: вертикальный срез задачи «Причины» (XAI) — v2 первого среза
# (spec_tasks_ia_addendum_v1_1.md §10, §10.1; паттерн C — §11.2).
#
# Контракт: GET /v1/session/tasks/causes[?card_id=] — реестр методов
# объяснения выбранной Model Card с честной маркировкой статусов:
#   - fold_importance — доступен ТОЛЬКО если у карты есть артефакт
#     бэктеста с привязанными fold-записями feature_importance
#     (bind_feature_importance, Task 127); агрегация — средняя доля
#     внутри fold (сырые MDI разных fold несопоставимы);
#   - granger / shap / pdp — not_computed с честной причиной
#     (Granger не persist-ится сессией; SHAP/PDP движок не вычисляет).
# Отказы: нет карт — 409 (прямой URL поверх пустой сессии); неизвестный
# card_id — 404; ensemble-карта — 200 с not_computed (честный отказ
# агрегации по членам, прецедент forecast ensemble-отказа).
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


def _backtest_with_diagnostics(client: TestClient, model_id: str) -> None:
    backtest = client.post("/v1/session/modeling/backtest", json={"model_id": model_id})
    assert backtest.status_code == 200, backtest.text
    diagnostics = client.post("/v1/session/modeling/diagnostics", json={"model_id": model_id})
    assert diagnostics.status_code == 200, diagnostics.text


def _select_and_create_card(client: TestClient, model_id: str | None = None) -> dict:
    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text
    ranking_ids = [item["model_id"] for item in comparison.json()["ranking"]]
    selected_id = model_id if model_id is not None else ranking_ids[0]
    assert selected_id in ranking_ids, (selected_id, ranking_ids)
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


def _reach_model_card_rf(client: TestClient) -> dict:
    """Полный путь до Model Card random_forest — единственного класса
    моделей сессии, чьи fold-бэктесты привязывают feature_importance."""
    _prepare_session(client)
    _backtest_with_diagnostics(client, "naive")
    _backtest_with_diagnostics(client, "random_forest")
    return _select_and_create_card(client, "random_forest")


def _seed_card(client: TestClient, card_id: str, entry: dict) -> None:
    """Посев карточки напрямую в артефакты сессии (ensemble/битые карты —
    полный HTTP-путь до ensemble-карты требует tuning-контур)."""
    current = client.get("/v1/session/current")
    assert current.status_code == 200, current.text
    session_id = client.cookies[SESSION_COOKIE_NAME]
    store = get_session_store()
    session = store.get_or_create(session_id)
    session.modeling_artifacts.setdefault("model_cards", {})[card_id] = entry
    store.save(session)


def _fake_card_entry(card_id: str, model_id: str, selection_kind: str, created_at: str) -> dict:
    return {
        "card_id": card_id,
        "card": {
            "model_info": {
                "model_id": model_id,
                "selection_kind": selection_kind,
                "description": f"Фиктивная карта {model_id}",
            },
            "training": {},
            "created_at": created_at,
        },
    }


# ── Контракт входа: без Model Card задача не работает ─────────────


def test_causes_requires_model_card(client: TestClient):
    _prepare_session(client)

    response = client.get("/v1/session/tasks/causes")

    assert response.status_code == 409, response.text
    assert "Model Card" in response.json()["detail"]


def test_causes_unknown_card_id_returns_404(client: TestClient):
    _reach_model_card_rf(client)

    response = client.get("/v1/session/tasks/causes", params={"card_id": "missing-card"})

    assert response.status_code == 404, response.text
    assert "Model Card" in response.json()["detail"]


# ── Реестр методов: честная маркировка статусов ───────────────────


def test_causes_returns_card_and_full_method_registry(client: TestClient):
    card = _reach_model_card_rf(client)

    response = client.get("/v1/session/tasks/causes")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["card"]["card_id"] == card["card_id"]
    assert body["card"]["model_id"] == "random_forest"
    assert body["card"]["selection_kind"] == "single"

    methods = {m["method_id"]: m for m in body["methods"]}
    assert set(methods) == {"fold_importance", "granger", "shap", "pdp"}

    fold_method = methods["fold_importance"]
    assert fold_method["status"] == "available"
    assert fold_method["reason"] is None

    # Granger/SHAP/PDP не имеют session-артефактов — not_computed
    # с непустой честной причиной (не фиктивные данные).
    for method_id in ("granger", "shap", "pdp"):
        assert methods[method_id]["status"] == "not_computed", method_id
        reason = methods[method_id]["reason"]
        assert isinstance(reason, str) and len(reason) > 0, method_id
        assert methods[method_id]["factors"] is None, method_id


def test_causes_fold_importance_aggregates_mean_share_sorted_desc(client: TestClient):
    _reach_model_card_rf(client)

    body = client.get("/v1/session/tasks/causes").json()

    method = next(m for m in body["methods"] if m["method_id"] == "fold_importance")
    factors = method["factors"]
    assert isinstance(factors, list) and len(factors) > 0

    # Каждая fold-доля внутри fold суммируется в 1 (нормировка внутри
    # fold, а не по общему масштабу несопоставимых MDI).
    n_folds = method["provenance"]["n_folds"]
    assert n_folds >= 1
    for factor in factors:
        assert factor["feature_name"]
        assert 0.0 < factor["mean_share"] <= 1.0
        assert factor["n_folds"] == len(factor["fold_values"])
        fold_ids = [fv["fold"] for fv in factor["fold_values"]]
        assert fold_ids == sorted(fold_ids)

    # Внутри КАЖДОГО fold сумма долей всех факторов = 1 (нормировка
    # внутри fold, а не по общему масштабу несопоставимых MDI);
    # сумма СРЕДНИХ долей по факторам также = 1.
    folds_present = sorted({fv["fold"] for f in factors for fv in f["fold_values"]})
    assert len(folds_present) == n_folds
    for fold_no in folds_present:
        fold_share_sum = sum(
            fv["share"]
            for f in factors
            for fv in f["fold_values"]
            if fv["fold"] == fold_no
        )
        assert abs(fold_share_sum - 1.0) < 1e-9, fold_no
    assert abs(sum(f["mean_share"] for f in factors) - 1.0) < 1e-9
    shares = [f["mean_share"] for f in factors]
    assert shares == sorted(shares, reverse=True)


def test_causes_fold_importance_provenance_bound_to_backtest(client: TestClient):
    _reach_model_card_rf(client)

    body = client.get("/v1/session/tasks/causes").json()

    method = next(m for m in body["methods"] if m["method_id"] == "fold_importance")
    provenance = method["provenance"]
    # Oracle-привязка Task 127: run_id/plan_id из артефакта бэктеста,
    # n_folds — число fold с привязанной важностью.
    assert provenance["backtest_run_id"]
    assert provenance["plan_id"]
    assert provenance["n_folds"] == 2  # fixture: horizon=2, n_splits=2
    first_factor = method["factors"][0]
    assert first_factor["fold_values"][0]["matrix_hash"]


def test_causes_default_card_is_latest_by_created_at(client: TestClient):
    first = _reach_model_card_rf(client)
    # Вторая карта ПОД ТЕМ ЖЕ selection (POST /card дважды подряд):
    # повторный compare/evaluate инвалидирует прежние карты
    # (lineage-дисциплина modeling_session.py:2941/2985), карты
    # сосуществуют только внутри одного сравнения — как в селекторе
    # прогнозирования.
    second_resp = client.post("/v1/session/modeling/card", json={})
    assert second_resp.status_code == 200, second_resp.text
    second = second_resp.json()
    assert first["card_id"] != second["card_id"]

    latest = client.get("/v1/session/tasks/causes").json()["card"]["card_id"]
    pinned = client.get(
        "/v1/session/tasks/causes", params={"card_id": first["card_id"]},
    ).json()["card"]["card_id"]

    assert latest == second["card_id"]
    assert pinned == first["card_id"]


# ── Честные отказы: классические модели, ensemble, битые артефакты ─


def test_causes_classical_model_reports_not_computed_honestly(client: TestClient):
    _prepare_session(client)
    _backtest_with_diagnostics(client, "naive")
    _backtest_with_diagnostics(client, "ets")
    _select_and_create_card(client, "ets")

    body = client.get("/v1/session/tasks/causes").json()

    method = next(m for m in body["methods"] if m["method_id"] == "fold_importance")
    assert method["status"] == "not_computed"
    assert "важност" in method["reason"].lower()
    assert method["factors"] is None
    assert body["card"]["model_id"] == "ets"


def test_causes_ensemble_card_refuses_fold_importance_honestly(client: TestClient):
    _seed_card(client, "fake-ensemble", _fake_card_entry(
        "fake-ensemble", "ensemble_a", "ensemble",
        created_at="2026-09-18T10:00:00+00:00",
    ))

    body = client.get("/v1/session/tasks/causes").json()

    assert body["card"]["selection_kind"] == "ensemble"
    method = next(m for m in body["methods"] if m["method_id"] == "fold_importance")
    assert method["status"] == "not_computed"
    assert "ансамбл" in method["reason"].lower()
    assert method["factors"] is None


def test_causes_missing_backtest_artifact_is_not_500(client: TestClient):
    _seed_card(client, "broken-card", _fake_card_entry(
        "broken-card", "nonexistent_model", "single",
        created_at="2026-09-18T10:00:00+00:00",
    ))

    response = client.get("/v1/session/tasks/causes")

    assert response.status_code == 200, response.text
    body = response.json()
    method = next(m for m in body["methods"] if m["method_id"] == "fold_importance")
    assert method["status"] == "not_computed"
    assert "бэктест" in method["reason"].lower()
    assert method["factors"] is None
