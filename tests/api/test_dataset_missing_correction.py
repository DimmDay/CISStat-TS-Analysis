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
    response = client.post(
        "/v1/internal/upload",
        files={"file": (filename, buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_profile_reports_every_column_including_zero_missing():
    _upload(pd.DataFrame({
        "Price": [10.0, None, 30.0, None],
        "Region": ["A", "B", "A", "B"],
    }))

    profile = client.get("/v1/session/dataset/missing-profile")
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert body["rule_source"] == "system"
    assert body["total_missing"] == 2
    assert body["rows_with_missing"] == 2
    columns = {item["column"]: item for item in body["columns"]}
    assert columns["Price"]["missing_count"] == 2
    assert columns["Region"]["missing_count"] == 0


def test_missing_dataset_returns_404():
    assert client.get("/v1/session/dataset/missing-profile").status_code == 404
    response = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["Price"], "strategy": "median_mode", "apply": False},
    )
    assert response.status_code == 404


def test_preview_does_not_mutate_session_dataset():
    _upload(pd.DataFrame({"Price": [10.0, None, 30.0, None], "Region": ["A", "B", "A", "B"]}))

    preview = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["Price"], "strategy": "median_mode", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_changed"] == 2
    assert preview.json()["profile"][0]["missing_count"] == 0

    unchanged = client.get("/v1/session/dataset/missing-profile").json()
    assert unchanged["columns"][0]["missing_count"] == 2


def test_apply_persists_correction_and_profile_reflects_it():
    _upload(pd.DataFrame({"Price": [10.0, None, 30.0, None], "Region": ["A", "B", "A", "B"]}))

    applied = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["Price"], "strategy": "median_mode", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["profile"][0]["missing_count"] == 0
    stats = applied.json()["columns"][0]
    assert stats["stats_before"]["mean"] == pytest.approx(20.0)  # mean(10, 30)
    assert stats["stats_after"]["mean"] == pytest.approx(20.0)  # медиана=20 не меняет mean

    profile = client.get("/v1/session/dataset/missing-profile").json()
    assert profile["columns"][0]["missing_count"] == 0
    assert profile["total_missing"] == 0


def test_drop_rows_updates_session_dataset_metadata():
    _upload(pd.DataFrame({"Price": [10.0, None, 30.0, None], "Region": ["A", "B", "A", "B"]}))

    applied = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["Price"], "strategy": "drop_rows", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["rows_removed"] == 2

    current = client.get("/v1/session/current").json()
    assert current["dataset"]["rows"] == 2


def test_unknown_column_returns_422_without_mutating_session():
    _upload(pd.DataFrame({"Price": [10.0, None], "Region": ["A", "B"]}))

    response = client.post(
        "/v1/session/dataset/missing-corrections",
        json={"columns": ["Nope"], "strategy": "median_mode", "apply": True},
    )
    assert response.status_code == 422

    profile = client.get("/v1/session/dataset/missing-profile").json()
    assert profile["columns"][0]["missing_count"] == 1  # сессия не изменилась


# ── Режимы остановки (Task 47 применён к «Предобработке») ──


def test_default_mode_is_auto_and_status_reflects_real_data():
    _upload(pd.DataFrame({"Price": [10.0, None], "Region": ["A", "B"]}))

    modes = client.get("/v1/session/dataset/preprocessing-check-modes")
    assert modes.status_code == 200, modes.text
    assert modes.json()["modes"]["missing"] == "auto"

    profile = client.get("/v1/session/dataset/missing-profile").json()
    assert profile["mode"] == "auto"
    assert profile["status"] == "warning"
    assert profile["status_reason"] is None


def test_disabled_mode_is_skipped_and_excluded_from_status():
    _upload(pd.DataFrame({"Price": [10.0, None], "Region": ["A", "B"]}))

    put = client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"missing": "disabled"}},
    )
    assert put.status_code == 200, put.text
    assert put.json()["modes"]["missing"] == "disabled"

    profile = client.get("/v1/session/dataset/missing-profile").json()
    assert profile["mode"] == "disabled"
    assert profile["status"] == "skipped"
    assert profile["status_reason"] == "disabled"
    # Реальные данные по-прежнему видны -- отключение скрывает остановку
    # из прогресса/DQ-подобной метрики, а не из самого обзора.
    assert profile["total_missing"] == 1


def test_enabled_mode_behaves_like_auto_when_check_has_no_configurable_rule():
    _upload(pd.DataFrame({"Price": [10.0, None], "Region": ["A", "B"]}))

    client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"missing": "enabled"}},
    )
    profile = client.get("/v1/session/dataset/missing-profile").json()
    assert profile["mode"] == "enabled"
    assert profile["status"] == "warning"  # не "pending needs_rule" -- настраивать нечего


def test_returning_to_auto_removes_explicit_override():
    _upload(pd.DataFrame({"Price": [10.0, None], "Region": ["A", "B"]}))
    client.put("/v1/session/dataset/preprocessing-check-modes", json={"modes": {"missing": "disabled"}})

    put = client.put("/v1/session/dataset/preprocessing-check-modes", json={"modes": {"missing": "auto"}})
    assert put.json()["modes"]["missing"] == "auto"
    profile = client.get("/v1/session/dataset/missing-profile").json()
    assert profile["status"] == "warning"


def test_unknown_check_id_in_mode_update_returns_422():
    _upload(pd.DataFrame({"Price": [10.0, None]}))
    response = client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"not_a_real_check": "disabled"}},
    )
    assert response.status_code == 422


def test_new_dataset_resets_preprocessing_check_modes():
    _upload(pd.DataFrame({"Price": [10.0, None], "Region": ["A", "B"]}))
    client.put("/v1/session/dataset/preprocessing-check-modes", json={"modes": {"missing": "disabled"}})

    _upload(pd.DataFrame({"Price": [1.0, 2.0], "Region": ["A", "B"]}), filename="second.csv")
    modes = client.get("/v1/session/dataset/preprocessing-check-modes").json()
    assert modes["modes"]["missing"] == "auto"
