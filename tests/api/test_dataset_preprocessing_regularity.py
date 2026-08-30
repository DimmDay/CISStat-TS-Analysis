from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _upload(df: pd.DataFrame, filename: str = "dataset.csv") -> None:
    buffer = io.BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post("/v1/internal/upload", files={"file": (filename, buffer, "text/csv")})
    assert response.status_code == 200, response.text


def _regular_df_with_gap():
    dates = pd.date_range("2020-01-01", periods=12, freq="MS").tolist()
    with_gap = dates[:6] + dates[7:]  # пропущен один месяц
    return pd.DataFrame({"Date": [d.strftime("%Y-%m-%d") for d in with_gap], "Value": range(len(with_gap))})


def test_profile_reports_gap_and_default_auto_mode():
    _upload(_regular_df_with_gap())

    response = client.get("/v1/session/dataset/preprocessing/regularity-profile")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "auto"
    assert body["status"] == "warning"
    assert body["profile"]["applicable"] is True
    assert body["profile"]["gap_count"] == 1


def test_missing_dataset_returns_404_for_all_four_routes():
    assert client.get("/v1/session/dataset/preprocessing/regularity-profile").status_code == 404
    assert client.get("/v1/session/dataset/preprocessing/regularity-intervals").status_code == 404
    assert client.get("/v1/session/dataset/preprocessing/regularity-timeline").status_code == 404
    response = client.post(
        "/v1/session/dataset/preprocessing/regularity-corrections",
        json={"strategy": "sort", "apply": False},
    )
    assert response.status_code == 404


def test_intervals_endpoint_reports_modal_and_threshold():
    _upload(_regular_df_with_gap())
    response = client.get("/v1/session/dataset/preprocessing/regularity-intervals")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["modal_seconds"] is not None
    assert body["threshold_seconds"] == pytest.approx(body["modal_seconds"] * 1.5)
    assert len(body["bins"]) > 0


def test_timeline_endpoint_reports_gap_event():
    _upload(_regular_df_with_gap())
    response = client.get("/v1/session/dataset/preprocessing/regularity-timeline")
    assert response.status_code == 200, response.text
    body = response.json()
    kinds = {event["kind"] for event in body["events"]}
    assert "gap" in kinds


def test_preview_does_not_mutate_session_dataset():
    _upload(_regular_df_with_gap())

    preview = client.post(
        "/v1/session/dataset/preprocessing/regularity-corrections",
        json={"strategy": "asfreq", "frequency": "MS", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["rows_added"] > 0

    unchanged = client.get("/v1/session/dataset/preprocessing/regularity-profile").json()
    assert unchanged["profile"]["gap_count"] == 1  # сессия не изменилась


def test_apply_persists_correction_and_profile_reflects_it():
    _upload(_regular_df_with_gap())

    applied = client.post(
        "/v1/session/dataset/preprocessing/regularity-corrections",
        json={"strategy": "asfreq", "frequency": "MS", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["profile"]["gap_count"] == 0

    profile = client.get("/v1/session/dataset/preprocessing/regularity-profile").json()
    assert profile["profile"]["gap_count"] == 0
    assert profile["status"] == "done"


def test_disabled_mode_is_skipped_and_excluded_from_status():
    _upload(_regular_df_with_gap())
    put = client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"regularity": "disabled"}},
    )
    assert put.status_code == 200, put.text

    profile = client.get("/v1/session/dataset/preprocessing/regularity-profile").json()
    assert profile["mode"] == "disabled"
    assert profile["status"] == "skipped"
    assert profile["status_reason"] == "disabled"
    assert profile["profile"]["gap_count"] == 1  # данные по-прежнему честны


def test_not_applicable_when_no_date_column_detected():
    _upload(pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": ["x", "y", "z"]}))
    profile = client.get("/v1/session/dataset/preprocessing/regularity-profile").json()
    assert profile["status"] == "skipped"
    assert profile["status_reason"] == "not_required"
    assert profile["profile"]["applicable"] is False


def test_panel_dataset_groups_correctly():
    df = pd.DataFrame({
        "Country": ["A", "A", "A", "B", "B", "B"],
        "Date": ["2024-01-01", "2024-01-02", "2024-01-04", "2024-01-01", "2024-01-02", "2024-01-03"],
        "Value": [1, 2, 4, 10, 20, 30],
    })
    _upload(df)
    profile = client.get("/v1/session/dataset/preprocessing/regularity-profile").json()
    assert profile["profile"]["entity_column"] == "Country"
    assert profile["profile"]["gap_count"] >= 1  # у A пропущена дата 2024-01-03
