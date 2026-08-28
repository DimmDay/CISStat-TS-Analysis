# tests/unit/test_ih_analysis.py
import pytest
import pandas as pd
import numpy as np
from app.eda.ih_analysis import (
    discretize_feature, 
    shannon_entropy, 
    mutual_information, 
    compute_r_metric,
    compute_synergy,
    permutation_test_r_metric,
)

# ──────────────────────────────────────────────
# 1. ТЕСТЫ ШЕННОНА И ВЗАИМНОЙ ИНФОРМАЦИИ
# ──────────────────────────────────────────────

def test_shannon_entropy_fair_coin():
    """Энтропия честной монеты (50/50) должна быть ровно 1 бит."""
    probs = np.array([0.5, 0.5])
    assert np.isclose(shannon_entropy(probs, base=2), 1.0)

def test_shannon_entropy_deterministic():
    """Энтропия детерминированного события (100%) должна быть 0."""
    probs = np.array([1.0, 0.0])
    assert shannon_entropy(probs, base=2) == 0.0

def test_mutual_information_independent():
    """MI для независимых переменных должна быть близка к 0."""
    np.random.seed(42)
    x = pd.Series(np.random.choice(['A', 'B'], 1000))
    y = pd.Series(np.random.choice(['X', 'Y'], 1000))
    mi = mutual_information(x, y)
    assert mi < 0.05  # Должна быть почти нулевой

def test_mutual_information_identical():
    """MI для идентичных переменных должна быть равна их энтропии."""
    x = pd.Series(['A', 'B', 'C', 'A', 'B', 'C'] * 10)
    mi = mutual_information(x, x)
    h_x = shannon_entropy(np.array([1/3, 1/3, 1/3]))
    assert np.isclose(mi, h_x, atol=1e-5)

# ──────────────────────────────────────────────
# 2. ТЕСТЫ ДИСКРЕТИЗАЦИИ
# ──────────────────────────────────────────────

def test_discretize_categorical_unchanged():
    """Категориальные признаки не должны дискретизироваться."""
    s = pd.Series(['cat', 'dog', 'cat', 'bird'])
    res = discretize_feature(s, sharpness=0.5, min_samples=5)
    assert res.tolist() == ['cat', 'dog', 'cat', 'bird']

def test_discretize_handles_missing():
    """Пропуски должны кодироваться как '_MISSING_' для серий с > 10 уникальными значениями."""
    # Создаем серию с > 10 уникальными значениями, чтобы сработала логика дискретизации
    s = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0])
    res = discretize_feature(s, sharpness=0.5, min_samples=2)
    assert '_MISSING_' in res.values

# ──────────────────────────────────────────────
# 3. ТЕСТЫ R-МЕТРИКИ (Граничные случаи)
# ──────────────────────────────────────────────

def test_r_metric_constant_feature():
    """Если признак X константен, R должна быть 0, а в ответе должен быть error."""
    x = pd.Series([5.0] * 100)
    y = pd.Series(np.random.rand(100))
    res = compute_r_metric(x, y, sharpness=0.5, min_samples=5)
    assert res["R"] == 0.0
    assert "error" in res

def test_r_metric_perfect_correlation():
    """Если X и Y линейно зависят, R должна быть близка к 1.0."""
    x = pd.Series(np.arange(100))
    y = pd.Series(np.arange(100) * 2 + 1) # Идеальная линейная зависимость
    res = compute_r_metric(x, y, sharpness=0.2, min_samples=5)
    assert res["R"] > 0.95  # Должна быть очень высокой


def test_high_cardinality_categorical_feature_is_not_sent_to_numeric_binning():
    x = pd.Series([f"category-{index}" for index in range(15)] * 4)
    y = pd.Series([index % 3 for index in range(60)])

    discretized = discretize_feature(x, sharpness=0.25, min_samples=5)
    result = compute_r_metric(x, y, sharpness=0.25, min_samples=5)

    assert discretized.nunique() == 15
    assert 0.0 <= result["R"] <= 1.0


def test_min_samples_reliably_caps_the_number_of_numeric_bins():
    series = pd.Series(np.arange(100, dtype=float))
    discretized = discretize_feature(series, sharpness=0.1, min_samples=25)

    assert discretized.nunique() == 4
    assert discretized.value_counts().min() >= 25


def test_missing_values_are_a_separate_signal_for_low_cardinality_features():
    series = pd.Series(["A", "B", None, "A"])
    discretized = discretize_feature(series, sharpness=0.25, min_samples=2)

    assert "_MISSING_" in discretized.tolist()


def test_synergy_handles_combined_features_with_more_than_ten_states():
    frame = pd.DataFrame({
        "x1": np.tile(np.arange(6), 20),
        "x2": np.repeat(np.arange(4), 30),
    })
    frame["target"] = (frame["x1"] + frame["x2"]) % 3

    result = compute_synergy(
        frame,
        target_col="target",
        features=["x1", "x2"],
        sharpness=0.25,
        min_samples=5,
    )

    assert len(result) == 1
    assert np.isfinite(result.loc[0, "R_combined"])
    assert "incremental_gain" in result.columns
    assert "interaction_delta" in result.columns


def test_permutation_baseline_distinguishes_signal_from_chance_deterministically():
    rng = np.random.default_rng(42)
    x = pd.Series(np.linspace(-2, 2, 240))
    y = pd.Series(x.to_numpy() ** 2 + rng.normal(0, 0.03, len(x)))

    first = permutation_test_r_metric(x, y, 0.25, 20, n_permutations=49, seed=7)
    second = permutation_test_r_metric(x, y, 0.25, 20, n_permutations=49, seed=7)

    assert first == second
    assert first["R"] > 0.5
    assert first["R_adjusted"] > 0.4
    assert first["p_value"] <= 0.05
