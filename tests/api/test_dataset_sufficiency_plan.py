from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import get_session_store, reset_session_store_for_testing


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _upload() -> None:
    buffer = io.BytesIO()
    pd.DataFrame({
        "Country": ["A"] * 6 + ["B"] * 3,
        "Date": list(pd.date_range("2024-01-01", periods=6, freq="D"))
        + list(pd.date_range("2024-01-01", periods=3, freq="D")),
        "Value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 10.0, 11.0, 12.0],
    }).to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post("/v1/internal/upload", files={"file": ("panel.csv", buffer, "text/csv")})
    assert response.status_code == 200, response.text
    rules = client.put("/v1/session/dataset/validation-rules", json={
        "template_id": "system",
        "overrides": {"sufficiency": {
            "date_column": "Date", "entity_column": "Country", "target_column": "Value",
            "seasonal_period": 2, "min_obs_trend": 4, "min_obs_seasonality": 4,
            "min_obs_arima": 4, "min_obs_fft": 4, "min_obs_ml": 4, "min_seasons": 2,
        }},
    })
    assert rules.status_code == 200, rules.text


def test_profile_and_restrict_models_plan_share_one_contract():
    _upload()

    profile = client.get("/v1/session/dataset/sufficiency-profile")
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert body["rule_source"] == "session"
    assert body["profile"]["insufficient_groups"] == 1
    assert body["profile"]["total_failed_checks"] == 6

    preview = client.post("/v1/session/dataset/sufficiency-plan", json={
        "strategy": "restrict_models", "apply": False,
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["applied"] is False
    assert preview.json()["rows_removed"] == 0
    assert preview.json()["eligible_groups"] == ["A"]
    assert preview.json()["insufficient_groups"] == ["B"]

    applied = client.post("/v1/session/dataset/sufficiency-plan", json={
        "strategy": "restrict_models", "apply": True,
    })
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True
    session = next(iter(get_session_store()._sessions.values()))
    assert session.sufficiency_plan["strategy"] == "restrict_models"
    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["checks"]["sufficiency"]["status"] == "done"
    assert validation["checks"]["sufficiency"]["count"] == 0


def test_flag_strategy_previews_then_adds_group_eligibility_column():
    _upload()

    preview = client.post("/v1/session/dataset/sufficiency-plan", json={
        "strategy": "flag_groups", "apply": False,
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["added_columns"] == ["_sufficiency_eligible"]
    assert "_sufficiency_eligible" not in next(iter(get_session_store()._sessions.values())).dataframe

    applied = client.post("/v1/session/dataset/sufficiency-plan", json={
        "strategy": "flag_groups", "apply": True,
    })
    assert applied.status_code == 200, applied.text
    frame = next(iter(get_session_store()._sessions.values())).dataframe
    assert frame.groupby("Country")["_sufficiency_eligible"].first().to_dict() == {"A": True, "B": False}


def test_sufficiency_rules_reject_unknown_columns_and_invalid_thresholds():
    _upload()
    cases = [
        ({"date_column": "Missing"}, "отсутствует"),
        ({"target_column": "Country"}, "числов"),
        ({"min_obs_arima": 0}, "положительным"),
        ({"seasonal_period": 1.5}, "целым"),
    ]
    for sufficiency, message in cases:
        response = client.put("/v1/session/dataset/validation-rules", json={
            "template_id": "system", "overrides": {"sufficiency": sufficiency},
        })
        assert response.status_code == 422
        assert message in response.json()["detail"].lower()
