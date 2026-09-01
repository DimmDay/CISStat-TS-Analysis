from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.preprocessing.transforms import (
    apply_variance_transform,
    inverse_variance_transform,
)
from apps.api.preprocessing_variance import (
    build_variance_profile,
    preview_variance_transformation,
)


def _multiplicative_frame(n: int = 120) -> pd.DataFrame:
    x = np.arange(n, dtype=float)
    level = np.exp(1.5 + 0.018 * x)
    values = level * (1 + 0.22 * np.sin(2 * np.pi * x / 12))
    return pd.DataFrame({
        "Date": pd.date_range("2016-01-01", periods=n, freq="MS"),
        "Price": values,
    })


@pytest.mark.parametrize("method", ["box_cox", "yeo_johnson", "log", "log1p", "sqrt"])
def test_supported_transforms_have_round_trip(method: str):
    values = np.linspace(1.0, 20.0, 50)
    transformed, fitted_lambda = apply_variance_transform(values, method)
    restored = inverse_variance_transform(transformed, method, fitted_lambda)

    np.testing.assert_allclose(restored, values, rtol=1e-8, atol=1e-8)


def test_domains_are_strict_and_no_hidden_box_cox_shift_is_added():
    with pytest.raises(ValueError, match="строго положительные"):
        apply_variance_transform(np.array([0.0, 1.0, 2.0]), "box_cox")
    with pytest.raises(ValueError, match="строго положительные"):
        apply_variance_transform(np.array([0.0, 1.0, 2.0]), "log")
    with pytest.raises(ValueError, match="неотрицательные"):
        apply_variance_transform(np.array([-1.0, 0.0, 2.0]), "sqrt")

    transformed, fitted_lambda = apply_variance_transform(
        np.array([-3.0, 0.0, 5.0]), "yeo_johnson"
    )
    assert np.isfinite(transformed).all()
    assert fitted_lambda is not None


def test_profile_recommends_box_cox_and_returns_real_comparative_diagnostics():
    result = build_variance_profile(_multiplicative_frame(), "Price")

    assert result["applicable"] is True
    assert result["selected_method"] == "box_cox"
    assert result["lambda_value"] is not None
    assert result["diagnostics_before"]["rolling_window"] >= 5
    assert result["diagnostics_before"]["levene_pvalue"] is not None
    assert result["diagnostics_before"]["arch_lm_pvalue"] is not None
    assert result["diagnostics_after"] is not None
    assert len(result["points"]) == 120
    assert len(result["histogram"]) > 0
    assert {candidate["method"] for candidate in result["candidates"]} == {
        "box_cox", "yeo_johnson", "log", "log1p", "sqrt"
    }


def test_profile_uses_yeo_johnson_when_nonpositive_values_are_present():
    frame = _multiplicative_frame()
    frame["Price"] = frame["Price"] - frame["Price"].median()
    result = build_variance_profile(frame, "Price")

    assert result["applicable"] is True
    assert result["selected_method"] == "yeo_johnson"
    unavailable = {item["method"]: item for item in result["candidates"]}
    assert unavailable["box_cox"]["available"] is False
    assert unavailable["log"]["available"] is False


def test_profile_rejects_missing_and_constant_series_honestly():
    missing = _multiplicative_frame()
    missing.loc[4, "Price"] = np.nan
    missing_result = build_variance_profile(missing, "Price")
    assert missing_result["applicable"] is False
    assert "пропуск" in missing_result["reason"].lower()

    constant = _multiplicative_frame()
    constant["Price"] = 7.0
    constant_result = build_variance_profile(constant, "Price")
    assert constant_result["applicable"] is False
    assert "констант" in constant_result["reason"].lower()


def test_preview_adds_one_column_without_mutating_source_and_keeps_inverse_metadata():
    source = _multiplicative_frame()
    before = source.copy(deep=True)
    transformed, summary = preview_variance_transformation(
        source, column="Price", method="box_cox", lambda_value=None
    )

    pd.testing.assert_frame_equal(source, before)
    assert summary["output_column"] == "Price_box_cox"
    assert summary["metadata"]["source_column"] == "Price"
    assert summary["metadata"]["method"] == "box_cox"
    assert summary["metadata"]["lambda_value"] is not None
    assert summary["metadata"]["inverse_supported"] is True
    restored = inverse_variance_transform(
        transformed["Price_box_cox"].to_numpy(),
        "box_cox",
        summary["metadata"]["lambda_value"],
    )
    np.testing.assert_allclose(restored, source["Price"].to_numpy())


def test_preview_rejects_existing_output_and_unknown_method():
    frame = _multiplicative_frame()
    frame["Price_log"] = 0.0
    with pytest.raises(ValueError, match="уже существует"):
        preview_variance_transformation(frame, "Price", "log", None)
    with pytest.raises(ValueError, match="Неподдерживаемый"):
        preview_variance_transformation(_multiplicative_frame(), "Price", "reciprocal", None)
