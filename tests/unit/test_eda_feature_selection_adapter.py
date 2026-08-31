import numpy as np
import pandas as pd
from apps.api.eda_feature_selection import build_eda_feature_selection
from apps.api.schemas import DatasetEdaFeatureSelectionResponse

def test_adapter_orders_regular_time_and_returns_typed_profile():
    n=90; dates=pd.date_range("2024-01-01",periods=n,freq="D"); order=np.arange(n)[::-1]
    frame=pd.DataFrame({"Date":dates[order],"Y":np.arange(n)[order]+np.random.default_rng(1).normal(size=n),"X":np.arange(n)[order]})
    response=DatasetEdaFeatureSelectionResponse(**build_eda_feature_selection(frame,"Y"))
    assert response.order_source=="time_column" and response.order_column=="Date" and response.features

def test_adapter_disables_granger_for_panel_but_keeps_other_diagnostics():
    dates=np.repeat(pd.date_range("2024-01-01",periods=40,freq="D"),2)
    result=build_eda_feature_selection(pd.DataFrame({"Date":dates,"Y":np.arange(80.),"X":np.sin(np.arange(80.))}),"Y")
    assert result["applicable"] is True and result["granger_available"] is False
    assert result["features"] and "панель" in result["granger_reason"].lower()

def test_adapter_excludes_detected_date_before_classifying_univariate_series():
    frame = pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=40, freq="D"),
        "Y": np.arange(40, dtype=float),
    })
    result = build_eda_feature_selection(frame, "Y")
    assert result["applicability_status"] == "not_required"
    assert result["excluded_features"] == []
