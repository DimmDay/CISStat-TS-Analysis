"""TDD-контракт этапа 3: session API паспортов временного ряда."""
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


def _series_csv(n: int = 84, *, duplicate_date: bool = False) -> str:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="D").astype(str).tolist()
    if duplicate_date:
        dates[-1] = dates[-2]
    x = np.arange(n)
    values = 20 + 0.05 * x + 3 * np.sin(2 * np.pi * x / 7) + rng.normal(0, 0.4, n)
    companion = values * 0.7 + rng.normal(0, 0.2, n)
    frame = pd.DataFrame({"date": dates, "value": values, "companion": companion})
    return frame.to_csv(index=False)


def _upload(client: TestClient, csv: str | None = None) -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO((csv or _series_csv()).encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _select_series(client: TestClient) -> None:
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200


def _mutate_target(client: TestClient, delta: float = 5.0) -> None:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id
    store = get_session_store()
    session = store.get(session_id)
    assert session is not None and session.dataframe is not None
    session.dataframe.loc[session.dataframe.index[0], "value"] += delta
    session.touch()
    store.save(session)


class TestDateColumnApi:
    def test_get_without_dataset_is_safe(self, client: TestClient):
        response = client.get("/v1/session/date-column")

        assert response.status_code == 200
        assert response.json() == {
            "date_column": None,
            "suggested_column": None,
            "candidates": [],
            "has_dataset": False,
            "passport_history_reset": False,
        }

    def test_selects_and_persists_date_column(self, client: TestClient):
        _upload(client)

        before = client.get("/v1/session/date-column")
        assert before.status_code == 200
        assert before.json()["suggested_column"] == "date"
        assert before.json()["candidates"][0] == {"name": "date", "score": 1.0}

        saved = client.post("/v1/session/date-column", json={"column": "date"})

        assert saved.status_code == 200
        assert saved.json()["date_column"] == "date"
        assert client.get("/v1/session/current").json()["date_column"] == "date"

    def test_rejects_missing_or_unparseable_date_column(self, client: TestClient):
        _upload(client)
        missing = client.post("/v1/session/date-column", json={"column": "absent"})
        unparseable = client.post("/v1/session/date-column", json={"column": "companion"})

        assert missing.status_code == 404
        assert unparseable.status_code == 422

    def test_date_change_resets_history_and_reports_it(self, client: TestClient):
        frame = pd.read_csv(io.StringIO(_series_csv()))
        frame["other_date"] = frame["date"]
        _upload(client, frame.to_csv(index=False))
        _select_series(client)
        assert client.post("/v1/session/dataset/passport/start").status_code == 200

        response = client.post("/v1/session/date-column", json={"column": "other_date"})

        assert response.status_code == 200
        assert response.json()["passport_history_reset"] is True
        assert client.get("/v1/session/dataset/passport/status").json()["start"]["captured"] is False

    def test_numeric_year_column_keeps_calendar_semantics(self, client: TestClient):
        years = np.arange(1980, 2020)
        frame = pd.DataFrame({
            "Year": years,
            "value": 10 + np.sin(np.arange(len(years)) / 3),
        })
        _upload(client, frame.to_csv(index=False))
        assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
        assert client.post("/v1/session/date-column", json={"column": "Year"}).status_code == 200

        response = client.post("/v1/session/dataset/passport/start")

        assert response.status_code == 200
        passport = response.json()["passport"]
        assert passport["freq"]["value"].startswith("YS")
        assert passport["seasonality"]["applicable"] is False


class TestPassportCaptureAndStatus:
    def test_status_before_selection_explains_not_ready(self, client: TestClient):
        _upload(client)

        response = client.get("/v1/session/dataset/passport/status")

        assert response.status_code == 200
        body = response.json()
        assert body["series_ready"] is False
        assert body["current_fingerprint"] is None
        assert "целевая" in body["reason"].lower()
        assert body["start"] == {
            "captured": False,
            "captured_at": None,
            "is_stale": None,
            "fingerprint": None,
            "history_count": 0,
        }

    def test_captures_start_with_complete_passport_and_metadata(self, client: TestClient):
        _upload(client)
        _select_series(client)

        response = client.post("/v1/session/dataset/passport/start")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stage"] == "start"
        assert body["target_column"] == "value"
        assert body["date_column"] == "date"
        assert len(body["fingerprint"]) == 64
        assert body["snapshot_id"]
        assert body["captured_at"]
        assert body["passport"]["basic_stats"]["n"] == 84
        for section in ("correlations", "seasonal_periods", "fft", "periodogram", "wavelet"):
            assert section in body["passport"]

        status = client.get("/v1/session/dataset/passport/status").json()
        assert status["series_ready"] is True
        assert status["start"]["captured"] is True
        assert status["start"]["is_stale"] is False
        assert status["start"]["history_count"] == 1

    @pytest.mark.parametrize("stage", ["validation", "exit"])
    def test_later_stage_requires_start(self, client: TestClient, stage: str):
        _upload(client)
        _select_series(client)

        response = client.post(f"/v1/session/dataset/passport/{stage}")

        assert response.status_code == 409
        assert "start" in response.json()["detail"]

    def test_validation_requires_changed_series_and_appends_history(self, client: TestClient):
        _upload(client)
        _select_series(client)
        assert client.post("/v1/session/dataset/passport/start").status_code == 200

        unchanged = client.post("/v1/session/dataset/passport/validation")
        assert unchanged.status_code == 409
        assert "не измен" in unchanged.json()["detail"].lower()

        _mutate_target(client)
        status = client.get("/v1/session/dataset/passport/status").json()
        assert status["start"]["is_stale"] is True

        first = client.post("/v1/session/dataset/passport/validation")
        assert first.status_code == 200
        _mutate_target(client)
        second = client.post("/v1/session/dataset/passport/validation")
        assert second.status_code == 200

        status = client.get("/v1/session/dataset/passport/status").json()
        assert status["validation"]["history_count"] == 2
        assert status["validation"]["is_stale"] is False

    def test_exit_may_skip_validation_but_requires_a_change(self, client: TestClient):
        _upload(client)
        _select_series(client)
        assert client.post("/v1/session/dataset/passport/start").status_code == 200
        assert client.post("/v1/session/dataset/passport/exit").status_code == 409

        _mutate_target(client)
        response = client.post("/v1/session/dataset/passport/exit")

        assert response.status_code == 200
        assert response.json()["stage"] == "exit"

    def test_start_cannot_be_rewritten_after_later_stage(self, client: TestClient):
        _upload(client)
        _select_series(client)
        assert client.post("/v1/session/dataset/passport/start").status_code == 200
        _mutate_target(client)
        assert client.post("/v1/session/dataset/passport/validation").status_code == 200

        response = client.post("/v1/session/dataset/passport/start")

        assert response.status_code == 409

    def test_validation_cannot_be_captured_after_exit(self, client: TestClient):
        _upload(client)
        _select_series(client)
        assert client.post("/v1/session/dataset/passport/start").status_code == 200
        _mutate_target(client)
        assert client.post("/v1/session/dataset/passport/exit").status_code == 200
        _mutate_target(client)

        response = client.post("/v1/session/dataset/passport/validation")

        assert response.status_code == 409

    def test_capture_maps_missing_context_and_invalid_series_to_http_errors(self, client: TestClient):
        no_dataset = client.post("/v1/session/dataset/passport/start")
        assert no_dataset.status_code == 404

        _upload(client, _series_csv(n=29))
        no_selection = client.post("/v1/session/dataset/passport/start")
        assert no_selection.status_code == 404
        _select_series(client)
        too_short = client.post("/v1/session/dataset/passport/start")
        assert too_short.status_code == 422
        assert "30" in too_short.json()["detail"]

    def test_duplicate_dates_are_rejected_instead_of_silently_aggregated(self, client: TestClient):
        _upload(client, _series_csv(duplicate_date=True))
        _select_series(client)

        response = client.post("/v1/session/dataset/passport/start")

        assert response.status_code == 422
        assert "повторяющиеся даты" in response.json()["detail"].lower()

    def test_target_change_resets_history_and_reports_it(self, client: TestClient):
        _upload(client)
        _select_series(client)
        assert client.post("/v1/session/dataset/passport/start").status_code == 200

        response = client.post("/v1/session/target-column", json={"column": "companion"})

        assert response.status_code == 200
        assert response.json()["passport_history_reset"] is True
        assert client.get("/v1/session/dataset/passport/status").json()["start"]["captured"] is False

    def test_type_conversion_that_clears_target_also_clears_history(self, client: TestClient):
        _upload(client)
        _select_series(client)
        assert client.post("/v1/session/dataset/passport/start").status_code == 200

        converted = client.post(
            "/v1/session/dataset/convert-types",
            json={
                "conversions": [{"column": "value", "target_type": "string"}],
                "invalid_policy": "reject",
                "apply": True,
            },
        )

        assert converted.status_code == 200
        assert converted.json()["target_column_reset"] is True
        status = client.get("/v1/session/dataset/passport/status").json()
        assert status["target_column"] is None
        assert status["start"]["captured"] is False


class TestPassportCompare:
    def _capture_full_path(self, client: TestClient) -> None:
        _upload(client)
        _select_series(client)
        assert client.post("/v1/session/dataset/passport/start").status_code == 200
        _mutate_target(client, 3)
        assert client.post("/v1/session/dataset/passport/validation").status_code == 200
        _mutate_target(client, 4)
        assert client.post("/v1/session/dataset/passport/exit").status_code == 200

    def test_validation_comparison_has_one_pair(self, client: TestClient):
        self._capture_full_path(client)

        response = client.get("/v1/session/dataset/passport/compare", params={"to": "validation"})

        assert response.status_code == 200
        body = response.json()
        assert body["path"] == ["start", "validation"]
        assert len(body["comparisons"]) == 1
        assert body["comparisons"][0]["from_stage"] == "start"
        assert body["comparisons"][0]["to_stage"] == "validation"
        assert "metrics" in body["comparisons"][0]["comparison"]

    def test_exit_comparison_returns_full_trajectory_or_explicit_pair(self, client: TestClient):
        self._capture_full_path(client)

        trajectory = client.get("/v1/session/dataset/passport/compare", params={"to": "exit"})
        direct = client.get(
            "/v1/session/dataset/passport/compare",
            params={"to": "exit", "from": "start"},
        )

        assert trajectory.status_code == 200
        assert trajectory.json()["path"] == ["start", "validation", "exit"]
        assert len(trajectory.json()["comparisons"]) == 2
        assert direct.status_code == 200
        assert direct.json()["path"] == ["start", "exit"]
        assert len(direct.json()["comparisons"]) == 1

    def test_exit_trajectory_skips_missing_validation(self, client: TestClient):
        _upload(client)
        _select_series(client)
        assert client.post("/v1/session/dataset/passport/start").status_code == 200
        _mutate_target(client)
        assert client.post("/v1/session/dataset/passport/exit").status_code == 200

        response = client.get("/v1/session/dataset/passport/compare", params={"to": "exit"})

        assert response.status_code == 200
        assert response.json()["path"] == ["start", "exit"]

    def test_compare_rejects_missing_snapshots_and_invalid_pair(self, client: TestClient):
        _upload(client)
        _select_series(client)
        missing = client.get("/v1/session/dataset/passport/compare", params={"to": "validation"})
        invalid = client.get(
            "/v1/session/dataset/passport/compare",
            params={"to": "validation", "from": "validation"},
        )

        assert missing.status_code == 409
        assert invalid.status_code == 422


def test_existing_stateless_passport_response_no_longer_drops_spectral_sections(
    client: TestClient,
):
    frame = pd.read_csv(io.StringIO(_series_csv()))
    payload = {
        "series": [
            {"date": row.date, "value": row.value}
            for row in frame[["date", "value"]].itertuples(index=False)
        ]
    }

    response = client.post("/v1/internal/passport", json=payload)

    assert response.status_code == 200
    for section in ("correlations", "seasonal_periods", "fft", "periodogram", "wavelet"):
        assert section in response.json()


def test_passport_is_not_a_preprocessing_check_mode(client: TestClient):
    _upload(client)

    response = client.get("/v1/session/dataset/preprocessing-check-modes")

    assert response.status_code == 200
    assert "passport" not in response.json()["modes"]
