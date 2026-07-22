# app/eda/ih_analysis.py
"""
Модуль информационно-энтропийного анализа (IH-анализ).
Оценка информативности признаков через теорию информации Шеннона.
Метрика R(Y|X) = I(X;Y) / H(Y) ∈ [0;1].

⚠️ ВАЖНО: Этот модуль НЕ импортирует streamlit.
Все функции принимают явные аргументы (pd.Series, pd.DataFrame).
"""
import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


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


def compute_synergy(
    df: pd.DataFrame,
    target_col: str,
    features: List[str],
    sharpness: float,
    min_samples: int
) -> pd.DataFrame:
    """
    Вычисляет синергию для всех пар признаков.
    Синергия = R(X1+X2; Y) - [R(X1; Y) + R(X2; Y)]
    
    Args:
        df: DataFrame с данными
        target_col: имя целевой переменной
        features: список имён признаков для анализа
        sharpness: параметр дискретизации
        min_samples: минимальное число наблюдений на бин
    
    Returns:
        DataFrame с колонками: pair, R1, R2, R_combined, synergy, synergy_pct
    """
    if len(features) < 2:
        return pd.DataFrame(columns=["pair", "R1", "R2", "R_combined", "synergy", "synergy_pct"])
    
    synergy_results = []
    y_series = df[target_col].copy()
    
    individual_r = {}
    for feat in features:
        try:
            x_series = df[feat].copy()
            metrics = compute_r_metric(x_series, y_series, sharpness, min_samples)
            individual_r[feat] = metrics["R"]
        except Exception as e:
            logger.warning(f"Failed to compute R for {feat}: {e}")
            individual_r[feat] = 0.0
    
    for i in range(len(features)):
        for j in range(i + 1, len(features)):
            f1, f2 = features[i], features[j]
            try:
                r1 = individual_r[f1]
                r2 = individual_r[f2]
                
                x1_disc = discretize_feature(df[f1], sharpness, min_samples)
                x2_disc = discretize_feature(df[f2], sharpness, min_samples)
                x_combined = x1_disc.astype(str) + "||" + x2_disc.astype(str)
                
                r_combined = compute_r_metric(x_combined, y_series, sharpness, min_samples)["R"]
                
                synergy = r_combined - (r1 + r2)
                
                synergy_results.append({
                    "pair": f"{f1} + {f2}",
                    "R1": r1,
                    "R2": r2,
                    "R_combined": r_combined,
                    "synergy": synergy,
                    "synergy_pct": synergy * 100
                })
            except Exception as e:
                logger.warning(f"Failed to compute synergy for {f1} + {f2}: {e}")
                continue
    
    return pd.DataFrame(synergy_results).sort_values("synergy", ascending=False).reset_index(drop=True)


def generate_ih_recommendations(
    df_ih: pd.DataFrame,
    synergy_df: pd.DataFrame = None
) -> List[str]:
    """
    Генерирует автоматические рекомендации на основе результатов IH-анализа.
    
    Args:
        df_ih: DataFrame с результатами IH-анализа
        synergy_df: DataFrame с результатами анализа синергии (опционально)
    
    Returns:
        Список строк рекомендаций
    """
    recommendations = []
    
    if df_ih.empty:
        return ["ℹ️ Нет данных для анализа"]
    
    high_r = df_ih[df_ih["R"] >= 0.5]
    if not high_r.empty:
        rec_list = ", ".join([f"`{r}`" for r in high_r["feature"].head(3)])
        recommendations.append(f"✅ **Сильные предикторы**: {rec_list} (R ≥ 0.5) → используйте как основные признаки в моделях")
    
    low_r = df_ih[df_ih["R"] < 0.1]
    if not low_r.empty and len(low_r) > len(df_ih) * 0.3:
        recommendations.append("⚠️ **Много слабых признаков**: рассмотрите отбор признаков или агрегацию")
    
    if "H_X" in df_ih.columns:
        noisy = df_ih[(df_ih["H_X"] > df_ih["H_X"].quantile(0.75)) & (df_ih["R"] < 0.15)]
        if not noisy.empty:
            rec_list = ", ".join([f"`{r}`" for r in noisy["feature"].head(3)])
            recommendations.append(f"⚡ **Высокая энтропия, низкая связь**: {rec_list} → возможен шум, проверьте качество данных")
    
    if synergy_df is not None and not synergy_df.empty:
        best_syn = synergy_df.loc[synergy_df["synergy"].idxmax()]
        if best_syn["synergy"] > 0.1:
            recommendations.append(
                f"🤝 **Синергия**: пара `{best_syn['pair']}` даёт +{best_syn['synergy']*100:.1f}% информации вместе → создайте комбинированный признак"
            )
    
    if not recommendations:
        recommendations.append("ℹ️ Явных паттернов не обнаружено — начните с признаков с наибольшим R")
    
    return recommendations