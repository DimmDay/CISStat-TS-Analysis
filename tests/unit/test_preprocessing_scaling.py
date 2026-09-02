from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler

from app.preprocessing.scaling import fit_transform_scaling


def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "lag": [1.0, 2.0, 3.0, 10.0],
        "rolling": [10.0, 20.0, 30.0, 40.0],
    })


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("standard", lambda x: StandardScaler().fit_transform(x)),
        ("minmax", lambda x: MinMaxScaler(feature_range=(-1, 1)).fit_transform(x)),
        ("robust", lambda x: RobustScaler(quantile_range=(10, 90)).fit_transform(x)),
    ],
)
def test_affine_scalers_match_official_sklearn_implementations(method, expected):
    frame = _frame()
    original = frame.copy(deep=True)
    kwargs = {}
    if method == "minmax":
        kwargs["feature_range"] = (-1.0, 1.0)
    if method == "robust":
        kwargs["quantile_range"] = (10.0, 90.0)

    transformed, metadata = fit_transform_scaling(frame, list(frame.columns), method, **kwargs)

    np.testing.assert_allclose(transformed.to_numpy(), expected(frame.to_numpy()))
    pd.testing.assert_frame_equal(frame, original)
    assert metadata["scaler_class"].endswith("Scaler")
    assert metadata["fitted_on_n"] == len(frame)


def test_quantile_transform_is_deterministic_and_explicitly_nonlinear():
    frame = pd.DataFrame({"x": np.linspace(-3, 7, 60) ** 3})
    first, metadata = fit_transform_scaling(
        frame, ["x"], "quantile", n_quantiles=20, output_distribution="normal",
    )
    second, _ = fit_transform_scaling(
        frame, ["x"], "quantile", n_quantiles=20, output_distribution="normal",
    )

    np.testing.assert_allclose(first, second)
    assert metadata["linear"] is False
    assert metadata["actual_n_quantiles"] == 20


def test_validation_rejects_missing_constant_duplicate_and_invalid_ranges():
    with pytest.raises(ValueError, match="повтор"):
        fit_transform_scaling(_frame(), ["lag", "lag"], "standard")
    with pytest.raises(ValueError, match="констант"):
        fit_transform_scaling(pd.DataFrame({"x": [1.0, 1.0, 1.0]}), ["x"], "standard")
    with pytest.raises(ValueError, match="пропуск"):
        fit_transform_scaling(pd.DataFrame({"x": [1.0, np.nan, 2.0]}), ["x"], "standard")
    with pytest.raises(ValueError, match="feature_range"):
        fit_transform_scaling(_frame(), ["lag"], "minmax", feature_range=(1.0, 1.0))
    with pytest.raises(ValueError, match="quantile_range"):
        fit_transform_scaling(_frame(), ["lag"], "robust", quantile_range=(90.0, 10.0))

