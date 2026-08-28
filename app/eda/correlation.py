# app/eda/correlation.py
"""Корреляционный анализ признаков и временного ряда."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import acf, pacf


MIN_AUTOCORRELATION_OBSERVATIONS = 8


def _autocorrelation_not_applicable(
    series: pd.Series,
    max_lags: int,
    reason: str,
) -> dict:
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    finite_count = int(np.isfinite(numeric).sum())
    return {
        "applicable": False,
        "reason": reason,
        "n_observations": int(len(numeric)),
        "missing_count": int(len(numeric) - finite_count),
        "requested_max_lags": int(max_lags),
        "max_lag": 0,
        "alpha": 0.05,
        "acf": [],
        "pacf": [],
        "significant_acf_lags": [],
        "significant_pacf_lags": [],
        "ljung_box_lag": None,
        "ljung_box_pvalue": None,
        "is_white_noise": None,
        "suggested_p": None,
        "suggested_q": None,
    }


def autocorrelation_not_applicable(series: pd.Series, max_lags: int, reason: str) -> dict:
    """Публичный конструктор честного отказа для API-адаптера порядка."""
    return _autocorrelation_not_applicable(series, max_lags, reason)


def _profile_points(values: np.ndarray, intervals: np.ndarray) -> list[dict]:
    points: list[dict] = []
    for lag, value in enumerate(values):
        raw_lower = float(intervals[lag, 0])
        raw_upper = float(intervals[lag, 1])
        # statsmodels возвращает CI вокруг оценки. Для общего графика
        # переводим его в полосу вокруг нуля, сохраняя статистический
        # критерий значимости по исходному интервалу.
        lower = raw_lower - float(value)
        upper = raw_upper - float(value)
        significant = lag > 0 and (raw_lower > 0 or raw_upper < 0)
        points.append({
            "lag": lag,
            "value": float(value),
            "confidence_lower": float(lower),
            "confidence_upper": float(upper),
            "significant": bool(significant),
        })
    return points


def _cutoff_candidate(points: list[dict]) -> int:
    """Начальный AR/MA-кандидат: подряд значимые лаги от первого."""
    candidate = 0
    for point in points[1:]:
        if not point["significant"]:
            break
        candidate = int(point["lag"])
    return candidate


def analyze_autocorrelation(
    series: pd.Series,
    max_lags: int = 40,
    alpha: float = 0.05,
) -> dict:
    """Рассчитывает ACF/PACF, доверительные интервалы и Ljung–Box.

    Пропуски не удаляются молча: их схлопывание изменило бы смысл лага.
    PACF требует ``nlags < n/2``, поэтому пользовательский горизонт
    ограничивается безопасным максимумом.
    """
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    invalid_count = int((~np.isfinite(numeric)).sum())
    if invalid_count:
        return _autocorrelation_not_applicable(
            series,
            max_lags,
            f"В ряду {invalid_count} пропусков или бесконечных значений. "
            "Сначала обработайте их: удаление здесь исказило бы расстояние между лагами.",
        )
    if len(numeric) < MIN_AUTOCORRELATION_OBSERVATIONS:
        return _autocorrelation_not_applicable(
            series,
            max_lags,
            f"Недостаточно наблюдений: {len(numeric)}, требуется минимум "
            f"{MIN_AUTOCORRELATION_OBSERVATIONS}.",
        )
    if float(np.ptp(numeric)) <= np.finfo(float).eps:
        return _autocorrelation_not_applicable(
            series,
            max_lags,
            "Ряд константный (нулевая дисперсия): ACF/PACF не определены.",
        )

    requested_max_lags = max(1, int(max_lags))
    safe_max_lag = max(1, len(numeric) // 2 - 1)
    actual_max_lag = min(requested_max_lags, safe_max_lag)

    try:
        acf_values, acf_intervals = acf(
            numeric,
            nlags=actual_max_lag,
            alpha=alpha,
            fft=True,
            missing="raise",
        )
        pacf_values, pacf_intervals = pacf(
            numeric,
            nlags=actual_max_lag,
            alpha=alpha,
            method="ywm",
        )
    except (ValueError, np.linalg.LinAlgError, FloatingPointError) as exc:
        return _autocorrelation_not_applicable(
            series,
            max_lags,
            f"ACF/PACF не удалось устойчиво оценить для этого ряда: {exc}",
        )
    if not (
        np.isfinite(acf_values).all()
        and np.isfinite(acf_intervals).all()
        and np.isfinite(pacf_values).all()
        and np.isfinite(pacf_intervals).all()
    ):
        return _autocorrelation_not_applicable(
            series,
            max_lags,
            "ACF/PACF дали нечисловой результат: проверьте структуру и вариативность ряда.",
        )
    acf_points = _profile_points(acf_values, acf_intervals)
    pacf_points = _profile_points(pacf_values, pacf_intervals)
    significant_acf = [point["lag"] for point in acf_points if point["significant"]]
    significant_pacf = [point["lag"] for point in pacf_points if point["significant"]]

    ljung_box_lag = min(10, actual_max_lag)
    try:
        ljung_box = acorr_ljungbox(numeric, lags=[ljung_box_lag], return_df=True)
        raw_ljung_box_pvalue = float(ljung_box["lb_pvalue"].iloc[-1])
        ljung_box_pvalue = raw_ljung_box_pvalue if np.isfinite(raw_ljung_box_pvalue) else None
    except (ValueError, FloatingPointError):
        # ACF/PACF остаются содержательным результатом; omnibus-тест
        # допускает честное null вместо потери всей остановки.
        ljung_box_pvalue = None

    return {
        "applicable": True,
        "reason": None,
        "n_observations": int(len(numeric)),
        "missing_count": 0,
        "requested_max_lags": requested_max_lags,
        "max_lag": actual_max_lag,
        "alpha": float(alpha),
        "acf": acf_points,
        "pacf": pacf_points,
        "significant_acf_lags": significant_acf,
        "significant_pacf_lags": significant_pacf,
        "ljung_box_lag": ljung_box_lag,
        "ljung_box_pvalue": ljung_box_pvalue,
        "is_white_noise": bool(ljung_box_pvalue >= alpha) if ljung_box_pvalue is not None else None,
        "suggested_p": _cutoff_candidate(pacf_points),
        "suggested_q": _cutoff_candidate(acf_points),
    }


def find_significant_correlations(
    df: pd.DataFrame,
    num_cols: List[str],
    threshold: float = 0.5
) -> List[Dict]:
    """
    Находит значимые корреляции между числовыми колонками.
    
    Args:
        df: DataFrame с данными
        num_cols: Список числовых колонок для анализа
        threshold: Порог значимости корреляции (по умолчанию 0.5)
        
    Returns:
        Список словарей с информацией о значимых связях:
        [
            {
                'pair': 'col1 ↔ col2',
                'val': 0.85,
                'desc': 'Сильная прямая связь (r = 0.85)'
            },
            ...
        ]
        
    Examples:
        >>> import pandas as pd
        >>> import numpy as np
        >>> df = pd.DataFrame({'a': [1, 2, 3], 'b': [2, 4, 6]})
        >>> find_significant_correlations(df, ['a', 'b'], threshold=0.5)
        [{'pair': 'a ↔ b', 'val': 1.0, 'desc': 'Сильная прямая связь (r = 1.00)'}]
    """
    if len(num_cols) < 2:
        return []
    
    # Вычисляем матрицу корреляции
    corr_matrix = df[num_cols].corr()
    
    # Ищем значимые связи
    significant_links = []
    for i in range(len(corr_matrix.columns)):
        for j in range(i + 1, len(corr_matrix.columns)):
            val = corr_matrix.iloc[i, j]
            if abs(val) >= threshold:
                col1, col2 = corr_matrix.columns[i], corr_matrix.columns[j]
                strength = "Сильная" if abs(val) >= 0.7 else "Умеренная"
                direction = "прямая (+)" if val > 0 else "обратная (-)"
                significant_links.append({
                    "pair": f"{col1} ↔ {col2}",
                    "val": val,
                    "desc": f"{strength} {direction} связь (`r = {val:.2f}`)"
                })
    
    return significant_links
