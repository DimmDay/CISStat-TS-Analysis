# tests/unit/test_ih_synergy.py
import pytest
import pandas as pd
import numpy as np
from app.eda.ih_analysis import compute_synergy, generate_ih_recommendations


@pytest.fixture
def sample_df():
    """Создаёт тестовый DataFrame с известными зависимостями."""
    np.random.seed(42)
    n = 100
    # X1 сильно коррелирует с Y
    x1 = np.random.rand(n)
    y = x1 * 2 + np.random.randn(n) * 0.1
    
    # X2 не коррелирует с Y (шум)
    x2 = np.random.randn(n)
    
    # X3 даёт синергию с X1
    x3 = x1 + np.random.randn(n) * 0.2
    
    df = pd.DataFrame({
        "target": y,
        "feature_strong": x1,
        "feature_noise": x2,
        "feature_synergy": x3
    })
    return df


def test_compute_synergy_returns_dataframe(sample_df):
    """Проверяет, что функция возвращает DataFrame с правильными колонками."""
    features = ["feature_strong", "feature_noise", "feature_synergy"]
    result = compute_synergy(sample_df, "target", features, sharpness=0.5, min_samples=5)
    
    assert isinstance(result, pd.DataFrame)
    assert "pair" in result.columns
    assert "synergy" in result.columns
    assert len(result) == 3  # 3 пары из 3 признаков


def test_compute_synergy_detects_redundancy(sample_df):
    """Проверяет, что функция обнаруживает избыточность (отрицательная синергия)."""
    # feature_strong и feature_synergy сильно коррелируют → синергия должна быть отрицательной
    features = ["feature_strong", "feature_synergy"]
    result = compute_synergy(sample_df, "target", features, sharpness=0.5, min_samples=5)
    
    assert len(result) == 1
    # Синергия должна быть отрицательной (избыточность)
    assert result.iloc[0]["synergy"] < 0


def test_generate_ih_recommendations_strong_predictors():
    """Проверяет, что рекомендации формируются для сильных предикторов."""
    df_ih = pd.DataFrame({
        "feature": ["A", "B", "C"],
        "R": [0.8, 0.6, 0.1],
        "H_X": [1.0, 1.0, 1.0]
    })
    
    recs = generate_ih_recommendations(df_ih)
    assert any("Сильные предикторы" in rec for rec in recs)
    assert any("`A`" in rec for rec in recs)


def test_generate_ih_recommendations_weak_features():
    """Проверяет, что рекомендации формируются для слабых признаков."""
    df_ih = pd.DataFrame({
        "feature": ["A", "B", "C", "D"],
        "R": [0.05, 0.03, 0.02, 0.01],
        "H_X": [1.0, 1.0, 1.0, 1.0]
    })
    
    recs = generate_ih_recommendations(df_ih)
    assert any("слабых признаков" in rec for rec in recs)


def test_generate_ih_recommendations_with_synergy():
    """Проверяет, что рекомендации учитывают синергию."""
    df_ih = pd.DataFrame({
        "feature": ["A", "B"],
        "R": [0.3, 0.3],
        "H_X": [1.0, 1.0]
    })
    
    synergy_df = pd.DataFrame({
        "pair": ["A + B"],
        "synergy": [0.15],
        "R_combined": [0.75]
    })
    
    recs = generate_ih_recommendations(df_ih, synergy_df)
    assert any("Синергия" in rec for rec in recs)
    assert any("A + B" in rec for rec in recs)