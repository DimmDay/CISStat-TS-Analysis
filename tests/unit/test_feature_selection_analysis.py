import numpy as np
import pandas as pd
from app.eda.feature_selection import analyze_feature_selection

def test_feature_selection_separates_signal_collinearity_and_granger():
    rng=np.random.default_rng(7); n=140; x=rng.normal(size=n); y=np.zeros(n)
    for i in range(1,n): y[i]=.7*y[i-1]+.8*x[i-1]+rng.normal(scale=.35)
    frame=pd.DataFrame({"Y":y,"X":x,"X_copy":x+.001*rng.normal(size=n),"Noise":rng.normal(size=n)})
    result=analyze_feature_selection(frame,"Y",max_lag=3)
    assert result["applicable"] is True
    assert result["correlation_matrix"] and result["high_correlation_pairs"]
    assert any(point["significant"] for point in result["granger"] if point["feature"]=="X")
    assert any(item["vif_infinite"] or (item["vif"] or 0)>5 for item in result["features"] if item["name"] in {"X","X_copy"})

def test_feature_selection_blocks_invalid_target_without_compressing_time():
    frame=pd.DataFrame({"Y":np.r_[np.arange(39,dtype=float),np.nan],"X":np.arange(40,dtype=float)})
    result=analyze_feature_selection(frame,"Y")
    assert result["applicable"] is False
    assert "пропуск" in result["reason"].lower()

def test_univariate_series_is_neutral_not_required_case():
    frame = pd.DataFrame({"Y": np.arange(40, dtype=float)})
    result = analyze_feature_selection(frame, "Y")
    assert result["applicable"] is False
    assert result["applicability_status"] == "not_required"
    assert result["excluded_features"] == []
    assert "не требуется" in result["reason"].lower()

def test_present_but_unusable_predictors_require_preprocessing_with_reasons():
    frame = pd.DataFrame({
        "Y": np.arange(40, dtype=float),
        "numeric_with_gap": np.r_[np.arange(39, dtype=float), np.nan],
        "numeric_as_text": [str(value) for value in range(40)],
        "constant": np.ones(40),
    })
    result = analyze_feature_selection(frame, "Y")
    assert result["applicable"] is False
    assert result["applicability_status"] == "requires_preprocessing"
    reasons = {item["name"]: item["reason"] for item in result["excluded_features"]}
    assert set(reasons) == {"numeric_with_gap", "numeric_as_text", "constant"}
    assert "нечислов" in reasons["numeric_as_text"].lower()
