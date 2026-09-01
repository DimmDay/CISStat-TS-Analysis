"""Диагностика и preview/apply остановки «Стабилизация дисперсии».

Чистые трансформации живут в ``app.preprocessing.transforms``. Этот
модуль добавляет только API-представление: хронологические диагностики,
данные для графиков и безопасное добавление новой колонки без перезаписи
исходного target.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import het_arch

from app.data.detectors import score_all_columns_as_date, smart_to_datetime
from app.preprocessing.transforms import (
    VARIANCE_TRANSFORM_METHODS,
    apply_variance_transform,
)
from apps.api.chart_data import FULL_POINTS_THRESHOLD, TARGET_SAMPLED_POINTS, _lttb_indices


METHOD_LABELS = {
    "box_cox": "Box–Cox",
    "yeo_johnson": "Yeo–Johnson",
    "log": "Log",
    "log1p": "Log1p",
    "sqrt": "Квадратный корень",
}
METHOD_ORDER = ("box_cox", "yeo_johnson", "log", "log1p", "sqrt")


class VarianceNotApplicable(ValueError):
    pass


def _empty_profile(column: str, reason: str, missing_count: int = 0) -> dict[str, Any]:
    return {
        "column": column, "applicable": False, "reason": reason,
        "n_observations": 0, "missing_count": int(missing_count),
        "minimum": None, "maximum": None, "order_source": "row_order",
        "order_column": None, "selected_method": None, "lambda_value": None,
        "needs_stabilization": False, "diagnostics_before": None,
        "diagnostics_after": None, "candidates": [], "points": [],
        "histogram": [], "warnings": [], "recommendation": reason,
        "methodology_note": (
            "Power transform не заменяет модель условной волатильности. "
            "Параметры в backtest следует оценивать только на train-части."
        ),
    }


def _prepare(df: pd.DataFrame, column: str) -> tuple[np.ndarray, list[str], str, str | None]:
    if column not in df.columns:
        raise VarianceNotApplicable(f"Колонка '{column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise VarianceNotApplicable(f"Колонка '{column}' не числовая")
    values = pd.to_numeric(df[column], errors="coerce")
    missing = int(values.isna().sum())
    if missing:
        raise VarianceNotApplicable(
            f"В ряду {missing} пропусков; сначала завершите остановку «Пропуски»"
        )
    array = values.to_numpy(dtype=float)
    if not np.isfinite(array).all():
        raise VarianceNotApplicable("Ряд содержит бесконечные значения")
    if len(array) < 20:
        raise VarianceNotApplicable("Для диагностики дисперсии нужно минимум 20 наблюдений")
    if float(np.ptp(array)) <= 1e-12:
        raise VarianceNotApplicable("Ряд константный — стабилизация дисперсии не требуется")

    order_source = "row_order"
    order_column: str | None = None
    labels = [str(index + 1) for index in range(len(array))]
    candidates = [item for item in score_all_columns_as_date(df) if item["name"] != column]
    if candidates and float(candidates[0]["score"]) >= 0.35:
        date_column = str(candidates[0]["name"])
        parsed = smart_to_datetime(df[date_column])
        if parsed.notna().all():
            order = np.argsort(parsed.to_numpy(), kind="stable")
            array = array[order]
            labels = [value.isoformat() for value in parsed.iloc[order]]
            order_source = "time_column"
            order_column = date_column
    return array, labels, order_source, order_column


def _diagnostics(values: np.ndarray) -> dict[str, Any]:
    n = len(values)
    window = max(5, min(30, n // 5))
    frame = pd.Series(values, dtype=float)
    rolling_mean = frame.rolling(window=window).mean()
    rolling_std = frame.rolling(window=window).std()
    valid = rolling_mean.notna() & rolling_std.notna()
    correlation: float | None = None
    if int(valid.sum()) >= 3 and float(rolling_mean[valid].std()) > 1e-12 and float(rolling_std[valid].std()) > 1e-12:
        value = float(rolling_mean[valid].corr(rolling_std[valid]))
        correlation = value if np.isfinite(value) else None

    blocks = [block for block in np.array_split(values, 4) if len(block) >= 4]
    levene_statistic: float | None = None
    levene_pvalue: float | None = None
    variance_ratio: float | None = None
    if len(blocks) >= 2:
        levene = stats.levene(*blocks, center="median")
        if np.isfinite(levene.statistic) and np.isfinite(levene.pvalue):
            levene_statistic = float(levene.statistic)
            levene_pvalue = float(levene.pvalue)
        variances = np.asarray([np.var(block, ddof=1) for block in blocks], dtype=float)
        positive = variances[variances > 1e-12]
        if len(positive) == len(variances):
            variance_ratio = float(np.max(positive) / np.min(positive))

    arch_lag = max(1, min(10, n // 5))
    arch_pvalue: float | None = None
    try:
        time = np.arange(n, dtype=float)
        trend = np.polyval(np.polyfit(time, values, deg=1), time)
        residual = values - trend
        if float(np.var(residual)) > 1e-12:
            arch_result = het_arch(residual, nlags=arch_lag)
            candidate = float(arch_result[1])
            arch_pvalue = candidate if np.isfinite(candidate) else None
    except (ValueError, np.linalg.LinAlgError):
        arch_pvalue = None

    corr_component = abs(correlation) if correlation is not None else 0.0
    ratio_component = 0.0
    if variance_ratio is not None and variance_ratio > 1:
        ratio_component = min(1.0, float(np.log(variance_ratio) / np.log(10)))
    levene_component = 1.0 if levene_pvalue is not None and levene_pvalue < 0.05 else 0.0
    score = 100 * (0.5 * corr_component + 0.3 * ratio_component + 0.2 * levene_component)
    return {
        "rolling_window": window,
        "mean_std_correlation": _round_optional(correlation, 6),
        "levene_statistic": _round_optional(levene_statistic, 6),
        "levene_pvalue": _round_optional(levene_pvalue, 6),
        "block_variance_ratio": _round_optional(variance_ratio, 6),
        "arch_lm_lag": arch_lag,
        "arch_lm_pvalue": _round_optional(arch_pvalue, 6),
        "skewness": _round_optional(float(stats.skew(values, bias=False)), 6),
        "stability_score": round(float(np.clip(score, 0, 100)), 2),
    }


def _round_optional(value: float | None, digits: int) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def _method_availability(values: np.ndarray, method: str) -> tuple[bool, str | None]:
    minimum = float(np.min(values))
    if method in {"box_cox", "log"} and minimum <= 0:
        return False, "Требуются строго положительные значения"
    if method == "log1p" and minimum <= -1:
        return False, "Требуются значения строго больше −1"
    if method == "sqrt" and minimum < 0:
        return False, "Требуются неотрицательные значения"
    return True, None


def _resolve_method(values: np.ndarray, method: str) -> str:
    if method == "auto":
        return "box_cox" if float(np.min(values)) > 0 else "yeo_johnson"
    if method not in VARIANCE_TRANSFORM_METHODS:
        raise ValueError(f"Неподдерживаемый метод стабилизации: {method}")
    return method


def _candidate_profiles(values: np.ndarray) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for method in METHOD_ORDER:
        available, reason = _method_availability(values, method)
        item: dict[str, Any] = {
            "method": method, "label": METHOD_LABELS[method],
            "available": available, "reason": reason,
            "lambda_value": None, "stability_score": None,
        }
        if available:
            try:
                transformed, fitted = apply_variance_transform(values, method)
                item["lambda_value"] = _round_optional(fitted, 6)
                item["stability_score"] = _diagnostics(transformed)["stability_score"]
            except (ValueError, FloatingPointError, OverflowError) as exc:
                item.update(available=False, reason=str(exc))
        result.append(item)
    return result


def _visual_points(
    labels: list[str], original: np.ndarray, transformed: np.ndarray, window: int,
) -> list[dict[str, Any]]:
    before_std = pd.Series(original).rolling(window).std().to_numpy(dtype=float)
    after_std = pd.Series(transformed).rolling(window).std().to_numpy(dtype=float)
    n = len(original)
    if n <= FULL_POINTS_THRESHOLD:
        indices = np.arange(n)
    else:
        indices = _lttb_indices(np.arange(n, dtype=float), transformed, TARGET_SAMPLED_POINTS)
    return [
        {
            "x": labels[i], "original": float(original[i]),
            "transformed": float(transformed[i]),
            "rolling_std_before": float(before_std[i]) if np.isfinite(before_std[i]) else None,
            "rolling_std_after": float(after_std[i]) if np.isfinite(after_std[i]) else None,
        }
        for i in indices
    ]


def _histogram(original: np.ndarray, transformed: np.ndarray, bins: int = 24) -> list[dict[str, Any]]:
    original_density, original_edges = np.histogram(original, bins=bins, density=True)
    transformed_density, transformed_edges = np.histogram(transformed, bins=bins, density=True)
    return [
        {
            "bin": index + 1,
            "original_x": float((original_edges[index] + original_edges[index + 1]) / 2),
            "original_density": float(original_density[index]),
            "transformed_x": float((transformed_edges[index] + transformed_edges[index + 1]) / 2),
            "transformed_density": float(transformed_density[index]),
        }
        for index in range(bins)
    ]


def build_variance_profile(
    df: pd.DataFrame,
    column: str,
    method: str = "auto",
    lambda_value: float | None = None,
) -> dict[str, Any]:
    missing_count = int(pd.to_numeric(df[column], errors="coerce").isna().sum()) if column in df.columns else 0
    try:
        values, labels, order_source, order_column = _prepare(df, column)
        selected_method = _resolve_method(values, method)
        available, domain_reason = _method_availability(values, selected_method)
        if not available:
            raise VarianceNotApplicable(f"{METHOD_LABELS[selected_method]}: {domain_reason}")
        transformed, fitted_lambda = apply_variance_transform(values, selected_method, lambda_value)
        before = _diagnostics(values)
        after = _diagnostics(transformed)
        needs_stabilization = bool(
            (before["levene_pvalue"] is not None and before["levene_pvalue"] < 0.05)
            or (before["mean_std_correlation"] is not None and abs(before["mean_std_correlation"]) >= 0.5)
        )
        warnings: list[str] = []
        if before["arch_lm_pvalue"] is not None and before["arch_lm_pvalue"] < 0.05:
            warnings.append(
                "ARCH-LM указывает на условную волатильность; power transform может её не устранить — рассмотрите модель ARCH/GARCH."
            )
        if after["stability_score"] >= before["stability_score"]:
            warnings.append("Выбранная трансформация не улучшила диагностический score; сравните методы или оставьте исходную шкалу.")
        if needs_stabilization:
            recommendation = (
                f"Обнаружена нестабильность масштаба; предварительно рекомендуется {METHOD_LABELS[selected_method]}. "
                "Перед моделированием оцените λ заново только на train-части."
            )
        else:
            recommendation = (
                "Сильных признаков изменяющейся дисперсии не найдено; трансформация не обязательна. "
                f"{METHOD_LABELS[selected_method]} показан только для сравнения."
            )
        return {
            "column": column, "applicable": True, "reason": None,
            "n_observations": len(values), "missing_count": 0,
            "minimum": float(np.min(values)), "maximum": float(np.max(values)),
            "order_source": order_source, "order_column": order_column,
            "selected_method": selected_method,
            "lambda_value": _round_optional(fitted_lambda, 6),
            "needs_stabilization": needs_stabilization,
            "diagnostics_before": before, "diagnostics_after": after,
            "candidates": _candidate_profiles(values),
            "points": _visual_points(labels, values, transformed, before["rolling_window"]),
            "histogram": _histogram(values, transformed),
            "warnings": warnings, "recommendation": recommendation,
            "methodology_note": (
                "Brown–Forsythe (Levene с center=median) сравнивает дисперсии четырёх хронологических блоков; "
                "corr(rolling mean, rolling std) диагностирует зависимость масштаба от уровня. ARCH-LM показан отдельно. "
                "Score 0–100 — прозрачная UI-эвристика для сравнения, не отдельный статистический тест."
            ),
        }
    except VarianceNotApplicable as exc:
        return _empty_profile(column, str(exc), missing_count)
    except (ValueError, TypeError, np.linalg.LinAlgError) as exc:
        return _empty_profile(column, f"Диагностика не выполнена: {exc}", missing_count)


def preview_variance_transformation(
    df: pd.DataFrame,
    column: str,
    method: str,
    lambda_value: float | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if method not in VARIANCE_TRANSFORM_METHODS:
        raise ValueError(f"Неподдерживаемый метод стабилизации: {method}")
    if column not in df.columns:
        raise ValueError(f"Колонка '{column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise ValueError(f"Колонка '{column}' не числовая")
    values = pd.to_numeric(df[column], errors="coerce")
    if values.isna().any():
        raise ValueError("Ряд содержит пропуски; сначала завершите остановку «Пропуски»")
    output_column = f"{column}_{method}"
    if output_column in df.columns:
        raise ValueError(f"Колонка '{output_column}' уже существует; удалите её перед повторным применением")
    transformed, fitted_lambda = apply_variance_transform(
        values.to_numpy(dtype=float), method, lambda_value,
    )
    result = df.copy(deep=True)
    result[output_column] = transformed
    metadata = {
        "source_column": column, "output_column": output_column,
        "method": method, "lambda_value": _round_optional(fitted_lambda, 12),
        "inverse_supported": True, "fitted_on_n": int(len(values)),
        "standardized": False, "shift": 0.0,
    }
    summary = {
        "column": column, "method": method,
        "lambda_value": metadata["lambda_value"], "output_column": output_column,
        "rows_before": int(len(df)), "rows_after": int(len(result)),
        "columns_before": int(len(df.columns)), "columns_after": int(len(result.columns)),
        "metadata": metadata,
    }
    return result, summary
