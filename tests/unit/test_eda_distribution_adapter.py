from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.eda_distribution import build_eda_distribution
from apps.api.schemas import DatasetEdaDistributionResponse


def test_adapter_reuses_histogram_kde_and_builds_all_overview_payloads():
    values = np.random.default_rng(42).normal(size=240)
    result = build_eda_distribution(
        pd.DataFrame({"Price": values}),
        "Price",
        alpha=0.05,
        bins=20,
    )
    response = DatasetEdaDistributionResponse(**result)

    assert response.applicable is True
    assert response.column == "Price"
    assert response.bins == 20
    assert len(response.histogram) == 20
    assert response.density
    assert response.qq
    assert response.cdf
    assert len(response.tests) == 3
    assert all(item.normal_expected_count >= 0 for item in response.histogram)


def test_adapter_preserves_honest_not_applicable_state_without_fake_charts():
    values = np.arange(40, dtype=float)
    values[5] = np.nan
    result = build_eda_distribution(pd.DataFrame({"Price": values}), "Price")
    response = DatasetEdaDistributionResponse(**result)

    assert response.applicable is False
    assert response.missing_count == 1
    assert response.histogram == []
    assert response.density == []
    assert response.qq == []
    assert response.cdf == []
