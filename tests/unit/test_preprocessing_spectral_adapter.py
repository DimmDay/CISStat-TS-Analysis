from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.preprocessing_spectral import (
    build_preprocessing_spectral_profile,
    preview_spectral_selection,
)
from apps.api.schemas import DatasetPreprocessingSpectralProfileResponse
from apps.api.session_store import AnalysisSession, session_from_dict, session_to_dict


def _frame(size: int = 240) -> pd.DataFrame:
    time = np.arange(size, dtype=float)
    values = 3 * np.sin(2 * np.pi * time / 12) + np.sin(2 * np.pi * time / 5)
    return pd.DataFrame({
        "Date": pd.date_range("2010-01-01", periods=size, freq="MS"),
        "Price": values,
    })


def test_profile_reuses_eda_candidates_and_adds_five_visual_payloads():
    result = build_preprocessing_spectral_profile(
        _frame(), "Price", min_cycles=3, max_candidates=6,
        welch_segment_length=64, wavelet_scales=20,
    )
    response = DatasetPreprocessingSpectralProfileResponse(
        mode="auto", status="done", status_reason=None, profile=result,
    )

    assert response.profile.applicable is True
    assert response.profile.periodogram
    assert response.profile.fft
    assert response.profile.welch
    assert response.profile.wavelet
    assert response.profile.phase_profile
    assert any(abs(item.period - 12) < 0.7 for item in response.profile.candidates)
    assert response.profile.analysis_only is True
    assert response.profile.causal is False


def test_profile_sorts_time_and_refuses_irregular_panel_missing_and_constant():
    reversed_frame = _frame().iloc[::-1].reset_index(drop=True)
    profile = build_preprocessing_spectral_profile(reversed_frame, "Price")
    assert profile["order_source"] == "time_column"
    assert profile["order_column"] == "Date"

    irregular = _frame(80).drop(index=7).reset_index(drop=True)
    assert "нерегуляр" in build_preprocessing_spectral_profile(irregular, "Price")["reason"].lower()

    panel = pd.concat([_frame(40), _frame(40)], ignore_index=True)
    assert "панель" in build_preprocessing_spectral_profile(panel, "Price")["reason"].lower()

    missing = _frame(80)
    missing.loc[5, "Price"] = np.nan
    assert build_preprocessing_spectral_profile(missing, "Price")["applicable"] is False

    constant = _frame(80)
    constant["Price"] = 1.0
    assert "констант" in build_preprocessing_spectral_profile(constant, "Price")["reason"].lower()


def test_selection_preview_is_non_mutating_and_unconfirmed_needs_opt_in():
    frame = _frame()
    original = frame.copy(deep=True)

    summary = preview_spectral_selection(
        frame, "Price", [12], min_cycles=3, max_candidates=6,
        welch_segment_length=64, confirm_unconfirmed=False,
    )
    pd.testing.assert_frame_equal(frame, original)
    assert summary["selected_periods"] == [12]
    assert summary["confirmed_periods"] == [12]
    assert summary["metadata"]["analysis_only"] is True
    assert summary["metadata"]["modeling_safe"] is False

    with pytest.raises(ValueError, match="не подтвержд"):
        preview_spectral_selection(
            frame, "Price", [5, 7], min_cycles=3, max_candidates=8,
            welch_segment_length=64, confirm_unconfirmed=False,
        )


def test_spectral_selection_roundtrips_and_old_sessions_get_empty_default():
    session = AnalysisSession(session_id="spectral-roundtrip")
    session.preprocessing_spectral_selection = {
        "kind": "spectral_selection", "source_column": "Price", "selected_periods": [12],
    }
    serialized = session_to_dict(session)
    assert session_from_dict(serialized).preprocessing_spectral_selection["selected_periods"] == [12]

    serialized.pop("preprocessing_spectral_selection")
    assert session_from_dict(serialized).preprocessing_spectral_selection == {}
