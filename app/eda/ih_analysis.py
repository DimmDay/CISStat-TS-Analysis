# app/eda/ih_analysis.py
"""
Модуль информационно-энтропийного анализа (IH-анализ).
Оценка информативности признаков через теорию информации Шеннона.
Метрика R(Y|X) = I(X;Y) / H(Y) ∈ [0;1].

⚠️ ВАЖНО: Этот модуль НЕ импортирует streamlit.
Все функции принимают явные аргументы (pd.Series, pd.DataFrame).
"""
import logging
from typing import Any, Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MISSING_TOKEN = "_MISSING_"


def _categorical_values(series: pd.Series) -> pd.Series:
    result = series.astype("string")
    # Не смешиваем реальный текст "_MISSING_" с системным уровнем.
    literal_missing = result.eq(MISSING_TOKEN).fillna(False)
    result = result.mask(literal_missing, "_VALUE_MISSING_")
    return result.fillna(MISSING_TOKEN).astype(str)


def discretize_feature(series: pd.Series, sharpness: float, min_samples: int) -> pd.Series:
    """
    Адаптивная дискретизация с параметром sharpness.
    Меньший sharpness → больше интервалов.
    """
    if not 0 < sharpness <= 1:
        raise ValueError("sharpness должен находиться в интервале (0; 1]")
    if min_samples < 1:
        raise ValueError("min_samples должен быть положительным")

    is_numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
    if isinstance(series.dtype, pd.CategoricalDtype) or not is_numeric or series.nunique(dropna=True) <= 10:
        return _categorical_values(series)

    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    clean = numeric.dropna()
    max_reliable_bins = len(clean) // min_samples
    if max_reliable_bins < 2:
        # Не превращаем каждое число короткого ряда в отдельную категорию:
        # это искусственно даёт R≈1. Один общий интервал честнее.
        result = pd.Series(MISSING_TOKEN, index=series.index, dtype=object)
        result.loc[clean.index] = "0"
        return result

    # Актуальная реализация ih-coverage описывает число интервалов как
    # примерно 2/sharpness. Ограничение min_samples делает параметр
    # реальным контролем покрытия, а не только подписью в UI.
    requested_bins = max(2, min(50, int(np.ceil(2 / sharpness))))
    n_bins = min(requested_bins, max_reliable_bins, int(clean.nunique()))

    try:
        bins = pd.qcut(clean, q=n_bins, duplicates="drop", labels=False)
    except (ValueError, TypeError):
        try:
            bins = pd.cut(clean, bins=n_bins, duplicates="drop", labels=False)
        except (ValueError, TypeError):
            bins = pd.Series(0, index=clean.index)

    result = pd.Series(MISSING_TOKEN, index=series.index, dtype=object)
    result.loc[clean.index] = bins.astype("Int64").astype(str)
    return result


def shannon_entropy(probabilities: np.ndarray, base: float = 2) -> float:
    """Вычисление энтропии Шеннона."""
    probabilities = probabilities[probabilities > 0]
    if base <= 0 or np.isclose(base, 1.0):
        raise ValueError("Основание логарифма должно быть положительным и не равно 1")
    return float(-np.sum(probabilities * np.log(probabilities) / np.log(base)))


def mutual_information(x_disc: pd.Series, y_disc: pd.Series, base: float = 2) -> float:
    """
    Оценка взаимной информации через совместное распределение.
    """
    if len(x_disc) != len(y_disc):
        raise ValueError("X и Y должны иметь одинаковое число наблюдений")
    if len(x_disc) == 0:
        return 0.0

    x_codes, _ = pd.factorize(x_disc.reset_index(drop=True), sort=False)
    y_codes, _ = pd.factorize(y_disc.reset_index(drop=True), sort=False)
    valid = (x_codes >= 0) & (y_codes >= 0)
    if not valid.any():
        return 0.0
    x_codes = x_codes[valid]
    y_codes = y_codes[valid]
    n_x = int(x_codes.max()) + 1
    n_y = int(y_codes.max()) + 1
    counts = np.bincount(x_codes * n_y + y_codes, minlength=n_x * n_y).reshape(n_x, n_y)
    joint_prob = counts / counts.sum()
    px = joint_prob.sum(axis=1, keepdims=True)
    py = joint_prob.sum(axis=0, keepdims=True)
    expected = px @ py
    mask = joint_prob > 0
    return float(np.sum(joint_prob[mask] * np.log(joint_prob[mask] / expected[mask])) / np.log(base))


def _metrics_from_discrete(x_disc: pd.Series, y_disc: pd.Series) -> Dict[str, Any]:
    x_disc = x_disc.reset_index(drop=True)
    y_disc = y_disc.reset_index(drop=True)
    if len(x_disc) != len(y_disc):
        raise ValueError("X и Y должны иметь одинаковое число наблюдений")

    px = x_disc.value_counts(normalize=True, dropna=False).to_numpy(dtype=float)
    py = y_disc.value_counts(normalize=True, dropna=False).to_numpy(dtype=float)
    h_x = shannon_entropy(px)
    h_y = shannon_entropy(py)
    n_bins_x = int(x_disc.nunique(dropna=False))
    n_bins_y = int(y_disc.nunique(dropna=False))
    base_result = {
        "H_X": h_x,
        "H_Y": h_y,
        "n_bins_X": n_bins_x,
        "n_bins_Y": n_bins_y,
        "n_observations": len(x_disc),
    }
    if n_bins_x <= 1:
        return {"R": 0.0, "MI": 0.0, **base_result, "error": "Признак X константен"}
    if h_y < 1e-10:
        return {"R": 0.0, "MI": 0.0, **base_result, "error": "H(Y) ≈ 0"}

    mi = mutual_information(x_disc, y_disc)
    return {
        "R": float(np.clip(mi / h_y, 0.0, 1.0)),
        "MI": mi,
        **base_result,
    }


def compute_r_metric(x: pd.Series, y: pd.Series, sharpness: float, min_samples: int) -> Dict[str, Any]:
    """
    Вычисление нормированной меры связи R(Y|X) = I(X;Y) / H(Y).
    """
    if len(x) != len(y):
        raise ValueError("X и Y должны иметь одинаковое число наблюдений")
    x_disc = discretize_feature(x.reset_index(drop=True), sharpness, min_samples)
    y_disc = discretize_feature(y.reset_index(drop=True), sharpness, min_samples)
    return _metrics_from_discrete(x_disc, y_disc)


def permutation_test_r_metric(
    x: pd.Series,
    y: pd.Series,
    sharpness: float,
    min_samples: int,
    n_permutations: int = 49,
    seed: int = 42,
) -> Dict[str, Any]:
    """R с перестановочным baseline и воспроизводимым p-value."""
    if n_permutations < 1:
        raise ValueError("n_permutations должен быть положительным")
    x_disc = discretize_feature(x.reset_index(drop=True), sharpness, min_samples)
    y_disc = discretize_feature(y.reset_index(drop=True), sharpness, min_samples)
    observed = _metrics_from_discrete(x_disc, y_disc)
    if observed.get("error") or observed["H_Y"] < 1e-10:
        return {
            **observed,
            "R_adjusted": 0.0,
            "permutation_baseline": 0.0,
            "p_value": 1.0,
        }

    rng = np.random.default_rng(seed)
    y_values = y_disc.to_numpy(copy=True)
    permuted_r = np.empty(n_permutations, dtype=float)
    for index in range(n_permutations):
        permuted = pd.Series(rng.permutation(y_values))
        permuted_mi = mutual_information(x_disc, permuted)
        permuted_r[index] = float(np.clip(permuted_mi / observed["H_Y"], 0.0, 1.0))
    baseline = float(permuted_r.mean())
    p_value = float((1 + np.count_nonzero(permuted_r >= observed["R"] - 1e-12)) / (n_permutations + 1))
    return {
        **observed,
        "R_adjusted": max(0.0, float(observed["R"]) - baseline),
        "permutation_baseline": baseline,
        "p_value": p_value,
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
        return pd.DataFrame(columns=[
            "pair", "R1", "R2", "R_combined", "synergy", "synergy_pct",
            "incremental_gain", "interaction_delta",
        ])
    
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
                x_combined = x1_disc.reset_index(drop=True).astype(str) + "||" + x2_disc.reset_index(drop=True).astype(str)
                y_disc = discretize_feature(y_series.reset_index(drop=True), sharpness, min_samples)
                r_combined = _metrics_from_discrete(x_combined, y_disc)["R"]
                interaction_delta = r_combined - (r1 + r2)
                incremental_gain = r_combined - max(r1, r2)
                
                synergy_results.append({
                    "pair": f"{f1} + {f2}",
                    "R1": r1,
                    "R2": r2,
                    "R_combined": r_combined,
                    # Старые имена сохранены для legacy Streamlit.
                    "synergy": interaction_delta,
                    "synergy_pct": interaction_delta * 100,
                    "incremental_gain": incremental_gain,
                    "interaction_delta": interaction_delta,
                })
            except Exception as e:
                logger.warning(f"Failed to compute synergy for {f1} + {f2}: {e}")
                continue
    
    if not synergy_results:
        return pd.DataFrame(columns=[
            "pair", "R1", "R2", "R_combined", "synergy", "synergy_pct",
            "incremental_gain", "interaction_delta",
        ])
    return pd.DataFrame(synergy_results).sort_values("incremental_gain", ascending=False).reset_index(drop=True)


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
