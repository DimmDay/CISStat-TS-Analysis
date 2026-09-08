"""Task 124 final certification -- arbitrary regressors API and session E2E.

Covers the user-facing entry point of the end-to-end regressor path:

- PUT/GET ``/v1/session/modeling/feature-regressors`` -- declarative,
  fail-closed validation against the active dataset;
- a declared future-known regressor enters the session cohort contract,
  reaches the fold-local FeaturePlan matrices and is passed to the real
  Prophet adapter (fit + predict with add_regressor) on exact EDA folds.
"""
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
    session_from_dict,
    session_to_dict,
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


def _prepare(client: TestClient) -> None:
    uploaded = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_csv().encode()), "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200


def _put(client: TestClient, payload: dict):
    return client.put("/v1/session/modeling/feature-regressors", json=payload)


class TestFeatureRegressorsEndpoint:
    def test_put_then_get_roundtrip(self, client: TestClient):
        _prepare(client)

        saved = _put(client, {
            "regressors": [{"column": "driver", "known_in_advance": True}],
        })

        assert saved.status_code == 200, saved.text
        assert saved.json()["regressors"] == [
            {"column": "driver", "known_in_advance": True, "static": False},
        ]
        fetched = client.get("/v1/session/modeling/feature-regressors")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["regressors"] == [
            {"column": "driver", "known_in_advance": True, "static": False},
        ]

    def test_put_replaces_previous_declarations(self, client: TestClient):
        _prepare(client)
        assert _put(client, {
            "regressors": [{"column": "driver", "known_in_advance": True}],
        }).status_code == 200

        replaced = _put(client, {"regressors": []})

        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["regressors"] == []

    def test_unknown_column_is_rejected(self, client: TestClient):
        _prepare(client)

        saved = _put(client, {
            "regressors": [{"column": "nope", "known_in_advance": True}],
        })

        assert saved.status_code == 422, saved.text
        assert "nope" in saved.json()["detail"]

    def test_target_column_is_rejected(self, client: TestClient):
        _prepare(client)

        saved = _put(client, {
            "regressors": [{"column": "value", "known_in_advance": True}],
        })

        assert saved.status_code == 422, saved.text

    def test_non_numeric_column_is_rejected(self, client: TestClient):
        _prepare(client)
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        store = get_session_store()
        session = store.get(session_id)
        session.dataframe["segment"] = ["eu"] * len(session.dataframe)
        store.save(session)

        saved = _put(client, {
            "regressors": [{"column": "segment", "known_in_advance": True}],
        })

        assert saved.status_code == 422, saved.text
        assert "числов" in saved.json()["detail"]

    def test_duplicate_declarations_are_rejected(self, client: TestClient):
        _prepare(client)

        saved = _put(client, {
            "regressors": [
                {"column": "driver", "known_in_advance": True},
                {"column": "driver", "known_in_advance": False},
            ],
        })

        assert saved.status_code == 422, saved.text

    def test_static_non_constant_column_is_rejected(self, client: TestClient):
        _prepare(client)
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        store = get_session_store()
        session = store.get(session_id)
        session.dataframe["flag"] = np.arange(len(session.dataframe), dtype=float)
        store.save(session)

        saved = _put(client, {
            "regressors": [{"column": "flag", "known_in_advance": True, "static": True}],
        })

        assert saved.status_code == 422, saved.text
        assert "static" in saved.json()["detail"]


class TestRegressorSessionE2E:
    def test_declared_regressor_enters_cohort_and_prophet_receives_it(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ):
        """Полный контур Task 124: объявление -> cohort -> fold-матрицы ->
        regressor-канал реального Prophet (адаптер захватывается для аудита)."""
        captured: list[dict] = []
        from apps.api.model_impls import prophet as prophet_module
        real_fit_predict = prophet_module._prophet_fit_predict

        def spy_fit_predict(**kwargs):
            captured.append({
                "train_features": kwargs.get("train_features"),
                "future_features": kwargs.get("future_features"),
            })
            return real_fit_predict(**kwargs)

        monkeypatch.setattr(prophet_module, "_prophet_fit_predict", spy_fit_predict)

        _prepare(client)
        assert client.get(
            "/v1/session/modeling/context?horizon=3&n_splits=2",
        ).status_code == 200
        saved = _put(client, {
            "regressors": [{"column": "driver", "known_in_advance": True}],
        })
        assert saved.status_code == 200, saved.text

        naive = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})
        assert naive.status_code == 200, naive.text
        contract = naive.json()["cohort_contract"]["feature_contract"]
        assert contract["policy"] == "recursive"
        assert contract["future_known"] == ["driver"]
        assert contract["plan_id"].startswith("fp_")

        prophet = client.post("/v1/session/modeling/backtest", json={"model_id": "prophet"})
        assert prophet.status_code == 200, prophet.text
        prophet_body = prophet.json()
        assert prophet_body["cohort_id"] == naive.json()["cohort_id"]
        for fold in prophet_body["folds"]:
            matrix = fold["feature_matrix"]
            assert matrix is not None
            assert matrix["future_known_columns"] == ["driver"]
            assert matrix["matrix_hash"]
        assert captured, "Prophet adapter must be invoked"
        for call in captured:
            assert list(call["train_features"]) == ["driver"]
            assert list(call["future_features"]) == ["driver"]
            assert all(np.isfinite(call["train_features"]["driver"]))
            assert len(call["future_features"]["driver"]) == 3

    def test_changed_declarations_change_the_cohort(self, client: TestClient):
        _prepare(client)
        assert client.get(
            "/v1/session/modeling/context?horizon=3&n_splits=2",
        ).status_code == 200
        first = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})
        assert first.status_code == 200, first.text
        cohort_without = first.json()["cohort_id"]

        assert _put(client, {
            "regressors": [{"column": "driver", "known_in_advance": True}],
        }).status_code == 200
        second = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})
        assert second.status_code == 200, second.text

        assert second.json()["cohort_id"] != cohort_without
        contract = second.json()["cohort_contract"]["feature_contract"]
        assert contract["future_known"] == ["driver"]


class TestSessionPersistence:
    def test_declarations_survive_serialization_roundtrip(self):
        from apps.api.session_store import AnalysisSession

        session = AnalysisSession(session_id="persist")
        session.modeling_feature_regressors = [
            {"column": "driver", "known_in_advance": True, "static": False},
        ]

        restored = session_from_dict(session_to_dict(session))

        assert restored.modeling_feature_regressors == [
            {"column": "driver", "known_in_advance": True, "static": False},
        ]

    def test_set_dataset_clears_stale_declarations(self, client: TestClient):
        _prepare(client)
        assert _put(client, {
            "regressors": [{"column": "driver", "known_in_advance": True}],
        }).status_code == 200

        reuploaded = client.post(
            "/v1/internal/upload",
            files={"file": ("series.csv", io.BytesIO(_csv().encode()), "text/csv")},
        )
        assert reuploaded.status_code == 200, reuploaded.text

        fetched = client.get("/v1/session/modeling/feature-regressors")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["regressors"] == []
