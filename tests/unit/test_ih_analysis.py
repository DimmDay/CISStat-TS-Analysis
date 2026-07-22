# tests/unit/test_ih_analysis.py
import pytest
import pandas as pd
import numpy as np
from app.eda.ih_analysis import (
    discretize_feature, 
    shannon_entropy, 
    mutual_information, 
    compute_r_metric
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