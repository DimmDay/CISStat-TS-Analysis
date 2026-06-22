# app/eda/ih_analysis.py
"""
Модуль информационно-энтропийного анализа (IH-анализ).
Оценка информативности признаков через теорию информации Шеннона.
Метрика R(Y|X) = I(X;Y) / H(Y) ∈ [0;1].

⚠️ ВАЖНО: Этот модуль НЕ импортирует streamlit.
Все функции принимают явные аргументы (pd.Series, pd.DataFrame).
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, List

def discretize_feature(series: pd.Series, sharpness: float, min_samples: int) -> pd.Series:
    """
    Адаптивная дискретизация с параметром sharpness.
    Меньший sharpness → больше интервалов.
    """
    if isinstance(series.dtype, pd.CategoricalDtype) or series.nunique() <= 10:
        return series.astype(str)

    clean = series.dropna()
    if len(clean) < min_samples * 2:
        return series.astype(str)  # fallback

    n_bins = max(2, min(50, int(1 / sharpness)))

    try:
        bins = pd.qcut(clean, q=n_bins, duplicates='drop', labels=False)
        result = pd.Series(index=series.index, dtype=object)
        result[clean.index] = bins.astype(str)
        result[series.isna()] = '_MISSING_'
        return result
    except Exception:
        bins = pd.cut(clean, bins=n_bins, labels=False)
        result = pd.Series(index=series.index, dtype=object)
        result[clean.index] = bins.astype(str)
        result[series.isna()] = '_MISSING_'
        return result


def shannon_entropy(probabilities: np.ndarray, base: float = 2) -> float:
    """Вычисление энтропии Шеннона."""
    probabilities = probabilities[probabilities > 0]
    return -np.sum(probabilities * np.log(probabilities) / np.log(base))


def mutual_information(x_disc: pd.Series, y_disc: pd.Series, base: float = 2) -> float:
    """
    Оценка взаимной информации через совместное распределение.
    """
    joint = pd.crosstab(x_disc, y_disc)
    joint_prob = joint.values / joint.values.sum()

    px = joint_prob.sum(axis=1)
    py = joint_prob.sum(axis=0)

    mi = 0.0
    for i in range(joint_prob.shape[0]):
        for j in range(joint_prob.shape[1]):
            if joint_prob[i, j] > 0 and px[i] > 0 and py[j] > 0:
                mi += joint_prob[i, j] * np.log(joint_prob[i, j] / (px[i] * py[j]))
                
    return mi / np.log(base)


def compute_r_metric(x: pd.Series, y: pd.Series, sharpness: float, min_samples: int) -> Dict[str, Any]:
    """
    Вычисление нормированной меры связи R(Y|X) = I(X;Y) / H(Y).
    """
    x_disc = discretize_feature(x, sharpness, min_samples)
    y_disc = discretize_feature(y, sharpness, min_samples)

    if x_disc.nunique() <= 1:
        return {
            "R": 0.0, "MI": 0.0, "H_X": 0.0, "H_Y": 0.0, 
            "n_bins_X": 1, "n_bins_Y": y_disc.nunique(),
            "error": "Признак X константен"
        }
    
    _, counts_y = np.unique(y_disc, return_counts=True)
    py = counts_y / counts_y.sum()
    h_y = shannon_entropy(py)

    if h_y < 1e-10:
        return {"R": 0.0, "MI": 0.0, "H_X": 0.0, "H_Y": 0.0, "error": "H(Y) ≈ 0"}

    mi = mutual_information(x_disc, y_disc)
    r_value = min(1.0, mi / h_y)

    _, counts_x = np.unique(x_disc, return_counts=True)
    px = counts_x / counts_x.sum()
    h_x = shannon_entropy(px)

    return {
        "R": r_value,
        "MI": mi,
        "H_X": h_x,
        "H_Y": h_y,
        "n_bins_X": x_disc.nunique(),
        "n_bins_Y": y_disc.nunique()
    }