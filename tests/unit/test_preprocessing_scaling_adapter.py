from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.preprocessing_scaling import build_scaling_profile, preview_scaling_recipe
from apps.api.schemas import DatasetPreprocessingScalingProfileResponse
from apps.api.session_store import AnalysisSession, session_from_dict, session_to_dict


def _frame(size: int = 80) -> pd.DataFrame:
    x = np.arange(size, dtype=float)
    return pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=size, freq="D"),
        "Price": 100 + x,
        "Price_lag_1": 99 + x,
        "Price_roll_mean_7": 1000 + 20 * x,
        "fourier_p7_k1_sin": np.sin(2 * np.pi * x / 7),
        "is_weekend": (x % 7 >= 5).astype(int),
    })


def _generation() -> dict:
    return {
        "source_column": "Price",
        "feature_names": ["Price_lag_1", "Price_roll_mean_7", "fourier_p7_k1_sin", "is_weekend"],
    }


def test_profile_reuses_generated_x_and_builds_five_visual_payloads():
    profile = build_scaling_profile(
        _frame(), "Price", feature_generation=_generation(), saved_recipe={},
    )
    response = DatasetPreprocessingScalingProfileResponse(
        mode="auto", status="warning", status_reason=None, profile=profile,
    )

    assert response.profile.applicable is True
    assert "Price_lag_1" in response.profile.suggested_columns
    assert "Price_roll_mean_7" in response.profile.suggested_columns
    assert "is_weekend" not in response.profile.suggested_columns
    assert response.profile.preview_points
    assert response.profile.range_points
    assert response.profile.distribution_points
    assert response.profile.box_points
    assert response.profile.correlation_points
    assert len(response.profile.methods) == 5


def test_recipe_preview_does_not_mutate_dataframe_or_persist_full_history_fit():
    frame = _frame()
    original = frame.copy(deep=True)
    summary = preview_scaling_recipe(
        frame,
        "Price",
        columns=["Price_lag_1", "Price_roll_mean_7"],
        method="robust",
        quantile_range=(20.0, 80.0),
    )

    pd.testing.assert_frame_equal(frame, original)
    assert summary["recipe"]["fit_policy"] == "per_train_fold"
    assert summary["recipe"]["modeling_safe"] is True
    assert summary["preview_metadata"]["modeling_safe"] is False
    assert "fitted_statistics" not in summary["recipe"]
    assert summary["metrics"]


def test_quantile_requires_explicit_nonlinear_confirmation():
    with pytest.raises(ValueError, match="нелинейн"):
        preview_scaling_recipe(
            _frame(), "Price", columns=["Price_lag_1"], method="quantile",
            confirm_nonlinear=False,
        )


def test_saved_recipe_is_current_only_for_same_values_and_columns():
    frame = _frame()
    summary = preview_scaling_recipe(
        frame, "Price", columns=["Price_lag_1"], method="standard",
    )
    current = build_scaling_profile(
        frame, "Price", feature_generation=_generation(), saved_recipe=summary["recipe"],
    )
    assert current["configured"] is True

    changed = frame.copy()
    changed.loc[0, "Price_lag_1"] = -999.0
    stale = build_scaling_profile(
        changed, "Price", feature_generation=_generation(), saved_recipe=summary["recipe"],
    )
    assert stale["configured"] is False
    assert any("устар" in warning.lower() for warning in stale["warnings"])


def test_scaling_recipe_roundtrips_and_old_sessions_get_empty_default():
    session = AnalysisSession(session_id="scaling-session")
    session.preprocessing_scaling_recipe = {"method": "standard", "columns": ["x"]}
    payload = session_to_dict(session)
    assert session_from_dict(payload).preprocessing_scaling_recipe["method"] == "standard"

    payload.pop("preprocessing_scaling_recipe")
    assert session_from_dict(payload).preprocessing_scaling_recipe == {}

