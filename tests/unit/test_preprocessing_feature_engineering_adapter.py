from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.preprocessing_feature_engineering import (
    build_feature_generation_profile,
    preview_feature_generation,
)
from apps.api.schemas import DatasetPreprocessingFeatureGenerationProfileResponse
from apps.api.session_store import AnalysisSession, session_from_dict, session_to_dict
from apps.api.session_store import AnalysisSession, session_from_dict, session_to_dict


def _frame(size: int = 120) -> pd.DataFrame:
    x = np.arange(size, dtype=float)
    return pd.DataFrame({
        "Date": pd.date_range("2015-01-01", periods=size, freq="MS"),
        "Price": 20 + 0.1 * x + 3 * np.sin(2 * np.pi * x / 12),
    })


def _spectral(size: int = 120) -> dict:
    return {
        "source_column": "Price", "selected_periods": [12],
        "confirmed_periods": [12], "analyzed_on_n": size,
    }


def test_profile_reuses_spectral_periods_and_builds_five_visual_payloads():
    profile = build_feature_generation_profile(
        _frame(), "Price", spectral_selection=_spectral(), saved_generation={},
    )
    response = DatasetPreprocessingFeatureGenerationProfileResponse(
        mode="auto", status="warning", status_reason=None, profile=profile,
    )

    assert response.profile.applicable is True
    assert 12 in response.profile.suggested_lags
    assert response.profile.preview_points
    assert response.profile.lag_correlations
    assert response.profile.availability
    assert response.profile.cyclic_points
    assert response.profile.catalog


def test_preview_is_non_mutating_sorted_causal_and_drops_only_warmup():
    frame = _frame(40).iloc[::-1].reset_index(drop=True)
    original = frame.copy(deep=True)

    result, summary = preview_feature_generation(
        frame,
        "Price",
        lags=[1, 12],
        rolling_windows=[3],
        rolling_statistics=["mean", "std"],
        difference_lags=[1],
        calendar_features=["month_cyclic", "year"],
        fourier_periods=[12],
        fourier_harmonics=1,
        include_time_index=True,
        drop_warmup_rows=True,
    )

    pd.testing.assert_frame_equal(frame, original)
    assert result["Date"].is_monotonic_increasing
    assert summary["rows_dropped"] == 12
    assert result.filter(regex="lag|roll|fourier").notna().all().all()
    assert summary["metadata"]["causal"] is True
    assert summary["metadata"]["target_shift"] == 1
    assert summary["metadata"]["selection_requires_train_fold"] is True


def test_profile_refuses_missing_irregular_panel_and_calendar_without_time_axis():
    missing = _frame()
    missing.loc[3, "Price"] = np.nan
    assert "Пропуски" in build_feature_generation_profile(missing, "Price")["reason"]

    irregular = _frame().drop(index=5).reset_index(drop=True)
    assert "нерегуляр" in build_feature_generation_profile(irregular, "Price")["reason"].lower()

    panel = pd.concat([_frame(40), _frame(40)], ignore_index=True)
    assert "панель" in build_feature_generation_profile(panel, "Price")["reason"].lower()

    row_order = pd.DataFrame({"Price": np.arange(30, dtype=float)})
    with pytest.raises(ValueError, match="[Кк]алендар"):
        preview_feature_generation(
            row_order, "Price", lags=[1], calendar_features=["month_cyclic"],
        )


def test_stale_spectral_selection_is_not_silently_recommended():
    profile = build_feature_generation_profile(
        _frame(100), "Price", spectral_selection=_spectral(120),
    )
    assert 12 not in profile["spectral_periods"]
    assert any("устар" in warning.lower() for warning in profile["warnings"])


def test_feature_generation_metadata_roundtrips_and_old_sessions_get_empty_default():
    session = AnalysisSession(session_id="feature-session")
    session.preprocessing_feature_generation = {
        "source_column": "Price", "feature_names": ["Price_lag_1"],
    }
    payload = session_to_dict(session)
    assert session_from_dict(payload).preprocessing_feature_generation["feature_names"] == ["Price_lag_1"]

    payload.pop("preprocessing_feature_generation")
    assert session_from_dict(payload).preprocessing_feature_generation == {}


def test_feature_generation_metadata_roundtrips_and_old_sessions_get_empty_default():
    session = AnalysisSession(session_id="feature-session")
    session.preprocessing_feature_generation = {
        "source_column": "Price", "feature_names": ["Price_lag_1"],
    }
    serialized = session_to_dict(session)
    assert session_from_dict(serialized).preprocessing_feature_generation["feature_names"] == ["Price_lag_1"]

    serialized.pop("preprocessing_feature_generation")
    assert session_from_dict(serialized).preprocessing_feature_generation == {}
