"""Комплементарная верификация стационарности одного временного ряда.

ADF/PP/Zivot–Andrews проверяют разные варианты H0 о единичном корне,
KPSS — обратную H0 о стационарности. Консенсус строится только по
согласованным ADF и KPSS со спецификациями constant/trend; PP и ZA служат
независимыми подтверждающими диагностиками и не подменяют друг друга.
"""
from __future__ import annotations

import warnings
from inspect import signature
from typing import Any

import numpy as np
import pandas as pd


MIN_OBSERVATIONS = 30
CONSENSUS_VALUES = {
    "stationary",
    "trend-stationary",
    "non-stationary",
    "inconclusive",
}


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _critical_values(values: Any) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    return {
        str(key): finite
        for key, value in values.items()
        if (finite := _finite_float(value)) is not None
    }


def _empty_test(note: str) -> dict[str, Any]:
    return {
        "available": False,
        "stat": None,
        "pvalue": None,
        "lags": None,
        "is_stationary": None,
        "critical_values": {},
        "note": note,
    }


def stationarity_not_applicable(
    series: pd.Series,
    reason: str,
    alpha: float = 0.05,
) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    missing_count = int(numeric.isna().sum())
    return {
        "applicable": False,
        "reason": reason,
        "n_observations": int(len(numeric) - missing_count),
        "missing_count": missing_count,
        "min_observations": MIN_OBSERVATIONS,
        "alpha": float(alpha),
        "adf": _empty_test(reason),
        "adf_trend": _empty_test(reason),
        "kpss": {
            "available": False,
            "stat_level": None,
            "pvalue_level": None,
            "lags_level": None,
            "critical_values_level": {},
            "is_stationary_level": None,
            "note_level": reason,
            "stat_trend": None,
            "pvalue_trend": None,
            "lags_trend": None,
            "critical_values_trend": {},
            "is_stationary_trend": None,
            "note_trend": reason,
        },
        "pp": _empty_test(reason),
        "za": {**_empty_test(reason), "breakpoint": None},
        "consensus": None,
        "recommendation": reason,
        "recommendations": [],
        "warnings": [],
    }


def _run_adf(
    values: pd.Series,
    regression: str,
    alpha: float,
    max_lag: int | None,
) -> dict[str, Any]:
    from statsmodels.tsa.stattools import adfuller

    kwargs: dict[str, Any] = {
        "maxlag": max_lag,
        "regression": regression,
        "autolag": "AIC",
    }
    # statsmodels 0.15 предупреждает о смене tuple-контракта; 0.14 ещё не
    # знает параметр result_object, поэтому включаем его по сигнатуре.
    if "result_object" in signature(adfuller).parameters:
        kwargs["result_object"] = False
    result = adfuller(values, **kwargs)
    pvalue = float(result[1])
    return {
        "available": True,
        "stat": float(result[0]),
        "pvalue": pvalue,
        "lags": int(result[2]),
        "nobs": int(result[3]),
        "is_stationary": bool(pvalue < alpha),
        "critical_values": _critical_values(result[4]),
        "note": None,
    }


def _run_kpss(
    values: pd.Series,
    regression: str,
    alpha: float,
) -> dict[str, Any]:
    from statsmodels.tsa.stattools import kpss

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = kpss(values, regression=regression, nlags="auto")
    notes = list(dict.fromkeys(str(item.message) for item in captured))
    pvalue = float(result[1])
    return {
        "available": True,
        "stat": float(result[0]),
        "pvalue": pvalue,
        "lags": int(result[2]),
        "is_stationary": bool(pvalue >= alpha),
        "critical_values": _critical_values(result[3]),
        "note": " ".join(notes) or None,
    }


def _run_pp(
    values: pd.Series,
    alpha: float,
    max_lag: int | None,
) -> dict[str, Any]:
    try:
        from arch.unitroot import PhillipsPerron
    except (ImportError, ModuleNotFoundError):
        return _empty_test(
            "Phillips–Perron недоступен: установите пакет arch. Результат другого теста не используется как подмена."
        )

    try:
        result = PhillipsPerron(values, lags=max_lag, trend="c", test_type="tau")
        pvalue = float(result.pvalue)
        return {
            "available": True,
            "stat": float(result.stat),
            "pvalue": pvalue,
            "lags": int(result.lags),
            "is_stationary": bool(pvalue < alpha),
            "critical_values": _critical_values(result.critical_values),
            "note": None,
        }
    except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
        return _empty_test(f"Phillips–Perron не рассчитан: {exc}")


def _run_zivot_andrews(
    values: pd.Series,
    alpha: float,
    max_lag: int | None,
) -> dict[str, Any]:
    from statsmodels.tsa.stattools import zivot_andrews

    try:
        result = zivot_andrews(
            values,
            maxlag=max_lag,
            regression="ct",
            autolag="AIC",
        )
        pvalue = float(result[1])
        return {
            "available": True,
            "stat": float(result[0]),
            "pvalue": pvalue,
            "lags": int(result[3]),
            "breakpoint": int(result[4]),
            "is_stationary": bool(pvalue < alpha),
            "critical_values": _critical_values(result[2]),
            "note": None,
        }
    except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
        return {**_empty_test(f"Zivot–Andrews не рассчитан: {exc}"), "breakpoint": None}


def analyze_stationarity(
    series: pd.Series,
    alpha: float = 0.05,
    max_lag: int | None = None,
) -> dict[str, Any]:
    """Запускает ADF(c/ct), KPSS(c/ct), PP и Zivot–Andrews.

    Пропуски не удаляются: для финальной EDA-верификации такое удаление
    сжало бы временную ось и изменило лаговую структуру. Консенсус не
    использует PP, если пакет ``arch`` недоступен, и никогда не выдаёт ADF
    за результат Phillips–Perron.
    """
    if not 0 < alpha < 1:
        raise ValueError("Уровень значимости alpha должен быть между 0 и 1")
    if max_lag is not None and max_lag < 0:
        raise ValueError("max_lag не может быть отрицательным")

    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    missing_count = int(numeric.isna().sum())
    if missing_count:
        return stationarity_not_applicable(
            numeric,
            "В ряду есть пропуски или бесконечные значения. Сначала завершите предобработку; удаление точек внутри теста изменило бы временную ось.",
            alpha,
        )
    if len(numeric) < MIN_OBSERVATIONS:
        return stationarity_not_applicable(
            numeric,
            f"Недостаточно наблюдений: нужно не менее {MIN_OBSERVATIONS}, доступно {len(numeric)}.",
            alpha,
        )
    if float(numeric.max() - numeric.min()) == 0.0:
        return stationarity_not_applicable(
            numeric,
            "Ряд константный: unit-root тесты вырождены и не дают корректного p-value.",
            alpha,
        )

    values = numeric.astype(float).reset_index(drop=True)
    adf_level = _run_adf(values, "c", alpha, max_lag)
    adf_trend = _run_adf(values, "ct", alpha, max_lag)
    kpss_level = _run_kpss(values, "c", alpha)
    kpss_trend = _run_kpss(values, "ct", alpha)
    pp = _run_pp(values, alpha, max_lag)
    za = _run_zivot_andrews(values, alpha, max_lag)

    level_stationary = bool(
        adf_level["is_stationary"] and kpss_level["is_stationary"]
    )
    trend_stationary = bool(
        not level_stationary
        and adf_trend["is_stationary"]
        and kpss_trend["is_stationary"]
    )
    unit_root = bool(
        not adf_level["is_stationary"]
        and not adf_trend["is_stationary"]
        and not kpss_level["is_stationary"]
        and not kpss_trend["is_stationary"]
    )

    if level_stationary:
        consensus = "stationary"
        recommendation = (
            "ADF и KPSS согласованно указывают на стационарность вокруг уровня. "
            "Для ARIMA можно рассматривать d=0, но порядок модели подтвердите временной валидацией и диагностикой остатков."
        )
    elif trend_stationary:
        consensus = "trend-stationary"
        recommendation = (
            "Ряд согласованно стационарен вокруг детерминированного тренда. "
            "Сравните удаление тренда с дифференцированием; автоматически назначать d=1 только по этой проверке нельзя."
        )
    elif unit_root:
        consensus = "non-stationary"
        recommendation = (
            "ADF и KPSS согласованно указывают на единичный корень. "
            "Вернитесь к шагу «Стационарность ряда» в Предобработке, примените обоснованное преобразование и повторите проверку."
        )
    else:
        consensus = "inconclusive"
        recommendation = (
            "ADF и KPSS дают смешанный результат. Проверьте спецификацию тренда, возможный структурный сдвиг и устойчивость вывода на временных подвыборках."
        )

    recommendations = [recommendation]
    analysis_warnings: list[str] = []
    if pp["available"]:
        if pp["is_stationary"] == adf_level["is_stationary"]:
            recommendations.append("Phillips–Perron подтверждает вывод ADF для спецификации с константой.")
        else:
            recommendations.append("Phillips–Perron расходится с ADF; интерпретируйте консенсус осторожно.")
    else:
        analysis_warnings.append(str(pp["note"]))
    if za["available"] and za["is_stationary"]:
        recommendations.append(
            f"Zivot–Andrews отвергает единичный корень с одним разрывом; кандидат точки разрыва — наблюдение {za['breakpoint']}."
        )
    for item in (kpss_level, kpss_trend):
        if item["note"]:
            analysis_warnings.append(str(item["note"]))

    return {
        "applicable": True,
        "reason": None,
        "n_observations": int(len(values)),
        "missing_count": 0,
        "min_observations": MIN_OBSERVATIONS,
        "alpha": float(alpha),
        "adf": adf_level,
        "adf_trend": adf_trend,
        "kpss": {
            "available": True,
            "stat_level": kpss_level["stat"],
            "pvalue_level": kpss_level["pvalue"],
            "lags_level": kpss_level["lags"],
            "critical_values_level": kpss_level["critical_values"],
            "is_stationary_level": kpss_level["is_stationary"],
            "note_level": kpss_level["note"],
            "stat_trend": kpss_trend["stat"],
            "pvalue_trend": kpss_trend["pvalue"],
            "lags_trend": kpss_trend["lags"],
            "critical_values_trend": kpss_trend["critical_values"],
            "is_stationary_trend": kpss_trend["is_stationary"],
            "note_trend": kpss_trend["note"],
        },
        "pp": pp,
        "za": za,
        "consensus": consensus,
        "recommendation": recommendation,
        "recommendations": recommendations,
        "warnings": list(dict.fromkeys(analysis_warnings)),
    }
