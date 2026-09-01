"""Диагностика и preview/apply остановки «Сглаживание ряда»."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import periodogram
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import acf

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from app.preprocessing.smoothing import CAUSAL_METHODS, SMOOTHING_METHODS, apply_smoothing_series
from apps.api.chart_data import FULL_POINTS_THRESHOLD, TARGET_SAMPLED_POINTS, _lttb_indices


METHOD_LABELS = {
    "sma": "Trailing SMA",
    "ema": "EMA",
    "wma": "Trailing WMA",
    "median": "Trailing median",
    "savgol": "Savitzky–Golay (offline)",
    "lowess": "LOWESS (offline)",
}


class SmoothingNotApplicable(ValueError):
    pass


def _empty_profile(column: str, reason: str, missing_count: int = 0) -> dict[str, Any]:
    return {
        "column": column, "applicable": False, "reason": reason,
        "n_observations": 0, "missing_count": int(missing_count),
        "order_source": "row_order", "order_column": None,
        "frequency": None, "regular": None, "selected_method": None,
        "selected_parameters": {}, "needs_smoothing": False,
        "diagnostics_before": None, "diagnostics_after": None,
        "candidates": [], "points": [], "spectrum": [], "residual_acf": [],
        "warnings": [], "recommendation": reason,
        "methodology_note": (
            "Сглаживание опционально. Выбор по полному ряду диагностический; "
            "в backtest параметры выбирают только на train."
        ),
    }


def _prepare(
    df: pd.DataFrame, column: str,
) -> tuple[np.ndarray, list[str], np.ndarray, str, str | None, str | None, bool | None]:
    if column not in df.columns:
        raise SmoothingNotApplicable(f"Колонка '{column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise SmoothingNotApplicable(f"Колонка '{column}' не числовая")
    numeric = pd.to_numeric(df[column], errors="coerce")
    missing = int(numeric.isna().sum())
    if missing:
        raise SmoothingNotApplicable(
            f"В ряду {missing} пропусков; сначала завершите остановку «Пропуски»"
        )
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise SmoothingNotApplicable("Ряд содержит бесконечные значения")
    if len(values) < 15:
        raise SmoothingNotApplicable("Для устойчивой диагностики сглаживания нужно минимум 15 наблюдений")
    if float(np.ptp(values)) <= 1e-12:
        raise SmoothingNotApplicable("Ряд константный — сглаживание неинформативно")

    order = np.arange(len(values))
    labels = [str(index + 1) for index in range(len(values))]
    order_source = "row_order"
    order_column: str | None = None
    frequency: str | None = None
    regular: bool | None = None
    date_candidates = [item for item in score_all_columns_as_date(df) if item["name"] != column]
    if date_candidates and float(date_candidates[0]["score"]) >= 0.35:
        date_column = str(date_candidates[0]["name"])
        raw_dates = df[date_column]
        parsed = smart_to_datetime(raw_dates)
        invalid = int((raw_dates.notna() & parsed.isna()).sum())
        missing_dates = int(parsed.isna().sum())
        if missing_dates:
            raise SmoothingNotApplicable(
                f"В колонке времени {missing_dates} пропусков или некорректных дат"
                + (f" ({invalid} некорректных значений)" if invalid else "")
                + "; сначала исправьте временную ось"
            )
        if parsed.duplicated().any():
            raise SmoothingNotApplicable(
                "На одну дату приходится несколько значений — обнаружена панельная структура. "
                "Выберите одну сущность или агрегируйте ряд до одной точки на дату."
            )
        order = np.argsort(parsed.to_numpy(), kind="stable")
        sorted_dates = parsed.iloc[order].reset_index(drop=True)
        labels = [value.isoformat() for value in sorted_dates]
        order_source = "time_column"
        order_column = date_column
        detected = detect_column_frequency(sorted_dates)
        frequency = detected.get("code")
        regular = frequency is not None
    return values[order], labels, order, order_source, order_column, frequency, regular


def _round_optional(value: float | None, digits: int = 6) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def _spectrum(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    frequencies, power = periodogram(values, detrend="linear", scaling="spectrum")
    power = np.asarray(power, dtype=float)
    total = float(power.sum())
    if total > 1e-12:
        power = power / total
    else:
        power = np.zeros_like(power)
    return np.asarray(frequencies, dtype=float), power


def _diagnostics(values: np.ndarray) -> dict[str, Any]:
    variance = float(np.var(values, ddof=1))
    difference = np.diff(values)
    second_difference = np.diff(values, n=2)
    roughness = float(np.mean(second_difference ** 2) / variance) if variance > 1e-12 else 0.0
    difference_ratio = float(np.std(difference, ddof=1) / np.sqrt(variance)) if variance > 1e-12 else 0.0
    lag1 = float(pd.Series(values).autocorr(lag=1)) if len(values) > 2 else None
    frequencies, power = _spectrum(values)
    high_frequency = float(power[frequencies >= 0.25].sum()) if len(power) else None
    return {
        "normalized_roughness": _round_optional(roughness),
        "difference_std_ratio": _round_optional(difference_ratio),
        "lag1_autocorrelation": _round_optional(lag1),
        "high_frequency_power_share": _round_optional(high_frequency),
        "standard_deviation": _round_optional(float(np.std(values, ddof=1))),
    }


def _residual_pvalue(residual: np.ndarray) -> float | None:
    if float(np.var(residual)) <= 1e-12:
        return 1.0
    lag = max(1, min(10, len(residual) // 5))
    try:
        result = acorr_ljungbox(residual, lags=[lag], return_df=True)
        return _round_optional(float(result["lb_pvalue"].iloc[0]))
    except ValueError:
        return None


def _method_parameters(method: str, window: int, span: int, frac: float, polyorder: int) -> str:
    if method == "ema":
        return f"span={span}"
    if method == "lowess":
        return f"frac={frac:g}"
    if method == "savgol":
        return f"window={window}, p={polyorder}"
    return f"window={window}"


def _candidate_profiles(
    values: np.ndarray, window: int, span: int, frac: float, polyorder: int,
) -> list[dict[str, Any]]:
    before = _diagnostics(values)
    result: list[dict[str, Any]] = []
    for method in SMOOTHING_METHODS:
        item: dict[str, Any] = {
            "method": method, "label": METHOD_LABELS[method],
            "causal": method in {"sma", "ema", "wma", "median"},
            "available": True, "reason": None,
            "parameter_label": _method_parameters(method, window, span, frac, polyorder),
            "correlation": None, "roughness_reduction_pct": None,
            "high_frequency_reduction_pct": None, "variance_retained_pct": None,
            "residual_ljung_box_pvalue": None,
        }
        try:
            smoothed, _metadata = apply_smoothing_series(
                values, method, window=window, span=span, frac=frac, polyorder=polyorder,
            )
            after = _diagnostics(smoothed)
            corr = float(np.corrcoef(values, smoothed)[0, 1])
            before_rough = before["normalized_roughness"] or 0.0
            after_rough = after["normalized_roughness"] or 0.0
            before_high = before["high_frequency_power_share"] or 0.0
            after_high = after["high_frequency_power_share"] or 0.0
            before_var = float(np.var(values, ddof=1))
            after_var = float(np.var(smoothed, ddof=1))
            item.update(
                correlation=_round_optional(corr),
                roughness_reduction_pct=_round_optional(100 * (1 - after_rough / before_rough), 2) if before_rough > 1e-12 else 0.0,
                high_frequency_reduction_pct=_round_optional(100 * (1 - after_high / before_high), 2) if before_high > 1e-12 else 0.0,
                variance_retained_pct=_round_optional(100 * after_var / before_var, 2) if before_var > 1e-12 else 0.0,
                residual_ljung_box_pvalue=_residual_pvalue(values - smoothed),
            )
        except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
            item.update(available=False, reason=str(exc))
        result.append(item)
    return result


def build_smoothing_profile(
    df: pd.DataFrame,
    column: str,
    method: str = "auto",
    window: int = 7,
    span: int = 7,
    frac: float = 0.2,
    polyorder: int = 2,
) -> dict[str, Any]:
    missing_count = int(pd.to_numeric(df[column], errors="coerce").isna().sum()) if column in df.columns else 0
    try:
        if method != "auto" and method not in SMOOTHING_METHODS:
            raise SmoothingNotApplicable(f"Неподдерживаемый метод сглаживания: {method}")
        values, labels, _order, order_source, order_column, frequency, regular = _prepare(df, column)
        selected = "ema" if method == "auto" else method
        smoothed, metadata = apply_smoothing_series(
            values, selected, window=window, span=span, frac=frac, polyorder=polyorder,
        )
        before = _diagnostics(values)
        after = _diagnostics(smoothed)
        high = before["high_frequency_power_share"] or 0.0
        roughness = before["normalized_roughness"] or 0.0
        needs_smoothing = bool(high >= 0.35 and roughness >= 1.0)
        residual = values - smoothed
        nlags = min(24, len(values) - 1)
        residual_acf_values = (
            np.concatenate(([1.0], np.zeros(nlags)))
            if float(np.var(residual)) <= 1e-12
            else acf(residual, nlags=nlags, fft=True, missing="raise")
        )
        frequencies, before_power = _spectrum(values)
        after_frequencies, after_power = _spectrum(smoothed)
        spectrum = [
            {"frequency": float(frequency_value), "before": float(before_power[index]), "after": float(after_power[index])}
            for index, frequency_value in enumerate(frequencies)
            if index < len(after_frequencies)
        ]
        n = len(values)
        indices = (
            np.arange(n) if n <= FULL_POINTS_THRESHOLD
            else _lttb_indices(np.arange(n, dtype=float), values, TARGET_SAMPLED_POINTS)
        )
        warnings: list[str] = []
        if regular is False:
            warnings.append(
                "Временная сетка нерегулярна: фильтры рассчитаны по порядку наблюдений, а спектральную шкалу нельзя трактовать как календарную."
            )
        if not metadata["causal"]:
            warnings.append(
                "Выбранный метод некаузален и использует будущие точки; результат допустим для offline-обзора, но не как готовый признак backtest."
            )
        if needs_smoothing:
            recommendation = (
                f"Высокочастотная составляющая выражена; сравните {METHOD_LABELS[selected]} с исходным рядом и подтвердите полезность backtest-ом."
            )
        else:
            recommendation = (
                "Сильного совместного сигнала высокой частоты и roughness не найдено; сглаживание опционально и может удалить полезные краткосрочные колебания."
            )
        return {
            "column": column, "applicable": True, "reason": None,
            "n_observations": n, "missing_count": 0,
            "order_source": order_source, "order_column": order_column,
            "frequency": frequency, "regular": regular,
            "selected_method": selected, "selected_parameters": metadata["parameters"],
            "needs_smoothing": needs_smoothing,
            "diagnostics_before": before, "diagnostics_after": after,
            "candidates": _candidate_profiles(values, window, span, frac, polyorder),
            "points": [
                {"x": labels[index], "original": float(values[index]), "smoothed": float(smoothed[index]), "residual": float(residual[index])}
                for index in indices
            ],
            "spectrum": spectrum,
            "residual_acf": [
                {"lag": int(lag), "value": float(value)}
                for lag, value in enumerate(residual_acf_values)
            ],
            "warnings": warnings, "recommendation": recommendation,
            "methodology_note": (
                "needs_smoothing — прозрачная UI-эвристика: доля periodogram-мощности при f ≥ 0,25 не меньше 0,35 "
                "и mean(Δ²y²)/Var(y) не меньше 1. Это не статистический тест. Trailing SMA/WMA/median и EMA каузальны; "
                "LOWESS/Savitzky–Golay — offline. Любой выбор параметров по полному ряду нужно повторить внутри train-fold."
            ),
        }
    except SmoothingNotApplicable as exc:
        return _empty_profile(column, str(exc), missing_count)
    except (ValueError, TypeError, np.linalg.LinAlgError) as exc:
        return _empty_profile(column, f"Диагностика сглаживания не выполнена: {exc}", missing_count)


def preview_smoothing_transformation(
    df: pd.DataFrame,
    column: str,
    method: str,
    *,
    window: int = 7,
    span: int = 7,
    frac: float = 0.2,
    polyorder: int = 2,
    confirm_non_causal: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if method not in SMOOTHING_METHODS:
        raise ValueError(f"Неподдерживаемый метод сглаживания: {method}")
    if method not in CAUSAL_METHODS and not confirm_non_causal:
        raise ValueError(
            "Выбран некаузальный offline-метод: подтвердите использование будущих наблюдений в историческом обзоре"
        )
    output_column = f"{column}_{method}"
    if output_column in df.columns:
        raise ValueError(f"Колонка '{output_column}' уже существует; удалите её перед повторным применением")
    values, _labels, order, _source, _date, _frequency, _regular = _prepare(df, column)
    smoothed, metadata = apply_smoothing_series(
        values, method, window=window, span=span, frac=frac, polyorder=polyorder,
    )
    restored_order = np.empty(len(smoothed), dtype=float)
    restored_order[order] = smoothed
    result = df.copy(deep=True)
    result[output_column] = restored_order
    stored_metadata = {
        "kind": "smoothing", "source_column": column,
        "output_column": output_column, "method": method,
        "parameters": metadata["parameters"], "causal": metadata["causal"],
        "modeling_safe": metadata["modeling_safe"],
        "inverse_supported": False, "fitted_on_n": int(len(values)),
    }
    return result, {
        "column": column, "method": method, "output_column": output_column,
        "rows_before": int(len(df)), "rows_after": int(len(result)),
        "columns_before": int(len(df.columns)), "columns_after": int(len(result.columns)),
        "metadata": stored_metadata,
    }
