"""Диагностика и preview/apply остановки «Стационарность ряда»."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import acf

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from app.eda.stationarity import MIN_OBSERVATIONS, analyze_stationarity
from app.preprocessing.stationarity import STATIONARITY_TRANSFORM_METHODS, apply_stationarity_series
from apps.api.chart_data import FULL_POINTS_THRESHOLD, TARGET_SAMPLED_POINTS, _lttb_indices


DATE_CONFIDENCE_THRESHOLD = 0.7
METHOD_ORDER = (
    "linear_detrend", "first_difference", "second_difference",
    "seasonal_difference", "combined_difference", "log_difference",
)
METHOD_LABELS = {
    "linear_detrend": "Линейный detrend",
    "first_difference": "Первая разность",
    "second_difference": "Вторая разность",
    "seasonal_difference": "Сезонная разность",
    "combined_difference": "Сезонная + первая",
    "log_difference": "Log-разность",
}
OUTPUT_SUFFIXES = {
    "linear_detrend": "detrended",
    "first_difference": "diff1",
    "second_difference": "diff2",
    "seasonal_difference": "sdiff",
    "combined_difference": "diff1_sdiff",
    "log_difference": "logdiff",
}


class StationarityNotApplicable(ValueError):
    pass


def _empty_profile(column: str, reason: str, missing_count: int = 0) -> dict[str, Any]:
    return {
        "column": column, "applicable": False, "reason": reason,
        "n_observations": 0, "missing_count": int(missing_count),
        "min_observations": MIN_OBSERVATIONS, "alpha": 0.05,
        "order_source": "row_order", "order_column": None,
        "frequency": None, "regular": False, "seasonal_period": 12,
        "selected_method": None, "needs_transformation": False,
        "consensus_before": None, "consensus_after": None,
        "lost_observations": 0, "acf_lag1_before": None,
        "acf_lag1_after": None, "variance_before": None, "variance_after": None,
        "over_differencing_warning": False, "tests": [], "candidates": [],
        "points": [], "acf": [], "warnings": [], "recommendation": reason,
        "methodology_note": (
            "ADF и KPSS проверяют противоположные H0. Результат тестов не назначает порядок модели автоматически; "
            "используйте минимум необходимых разностей и подтверждайте решение временной валидацией."
        ),
    }


def _prepare(
    df: pd.DataFrame, column: str,
) -> tuple[np.ndarray, list[str], np.ndarray, str, str | None, str | None, list[str]]:
    if column not in df.columns:
        raise StationarityNotApplicable(f"Колонка '{column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise StationarityNotApplicable(f"Колонка '{column}' не числовая")
    numeric = pd.to_numeric(df[column], errors="coerce")
    missing = int(numeric.isna().sum())
    if missing:
        raise StationarityNotApplicable(
            f"В ряду {missing} пропусков; сначала завершите остановку «Пропуски»"
        )
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise StationarityNotApplicable("Ряд содержит бесконечные значения")
    if len(values) < MIN_OBSERVATIONS:
        raise StationarityNotApplicable(
            f"Для тестов стационарности нужно минимум {MIN_OBSERVATIONS} наблюдений"
        )
    if float(np.ptp(values)) <= 1e-12:
        raise StationarityNotApplicable("Ряд константный — unit-root тесты вырождены")

    order = np.arange(len(values), dtype=np.int64)
    labels = [str(index + 1) for index in range(len(values))]
    order_source = "row_order"
    order_column: str | None = None
    frequency: str | None = None
    warnings_out = [
        "Временная ось уверенно не определена: используются текущий порядок строк и лаги в наблюдениях."
    ]
    candidates = [
        item for item in score_all_columns_as_date(df)
        if item["name"] != column and float(item["score"]) >= DATE_CONFIDENCE_THRESHOLD
    ]
    if candidates:
        order_column = str(candidates[0]["name"])
        parsed = smart_to_datetime(df[order_column])
        if parsed.isna().any():
            raise StationarityNotApplicable(
                f"В временной колонке «{order_column}» есть нераспознанные даты"
            )
        if parsed.duplicated().any():
            duplicate_count = int(parsed.duplicated(keep=False).sum())
            raise StationarityNotApplicable(
                f"В колонке «{order_column}» повторяются даты ({duplicate_count} строк): это похоже на панельные данные"
            )
        frequency = detect_column_frequency(parsed)["code"]
        if frequency is None:
            raise StationarityNotApplicable(
                "Временная сетка нерегулярна; сначала завершите остановку «Регулярность ряда»"
            )
        order = np.argsort(parsed.to_numpy(), kind="stable")
        values = values[order]
        labels = [pd.Timestamp(value).isoformat() for value in parsed.iloc[order]]
        order_source = "time_column"
        warnings_out = []
    return values, labels, order, order_source, order_column, frequency, warnings_out


def _resolve_method(consensus: str | None, method: str) -> str:
    if method == "auto":
        if consensus == "stationary":
            return "none"
        if consensus == "trend-stationary":
            return "linear_detrend"
        return "first_difference"
    if method not in STATIONARITY_TRANSFORM_METHODS:
        raise ValueError(f"Неподдерживаемый метод обеспечения стационарности: {method}")
    return method


def _lag1(values: np.ndarray) -> float | None:
    if len(values) < 3 or float(np.std(values)) <= 1e-12:
        return None
    result = float(np.corrcoef(values[:-1], values[1:])[0, 1])
    return result if np.isfinite(result) else None


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


def _test_value(result: dict[str, Any], test_id: str) -> tuple[float | None, bool | None]:
    if test_id == "adf_level":
        return result["adf"].get("pvalue"), result["adf"].get("is_stationary")
    if test_id == "adf_trend":
        return result["adf_trend"].get("pvalue"), result["adf_trend"].get("is_stationary")
    if test_id == "kpss_level":
        return result["kpss"].get("pvalue_level"), result["kpss"].get("is_stationary_level")
    if test_id == "kpss_trend":
        return result["kpss"].get("pvalue_trend"), result["kpss"].get("is_stationary_trend")
    if test_id == "pp":
        return result["pp"].get("pvalue"), result["pp"].get("is_stationary")
    return result["za"].get("pvalue"), result["za"].get("is_stationary")


def _test_comparison(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    definitions = (
        ("adf_level", "ADF (уровень)", "Единичный корень"),
        ("adf_trend", "ADF (тренд)", "Единичный корень"),
        ("kpss_level", "KPSS (уровень)", "Стационарность вокруг уровня"),
        ("kpss_trend", "KPSS (тренд)", "Стационарность вокруг тренда"),
        ("pp", "Phillips–Perron", "Единичный корень"),
        ("zivot_andrews", "Zivot–Andrews", "Единичный корень с одним разрывом"),
    )
    items = []
    for test_id, label, null_hypothesis in definitions:
        before_p, before_support = _test_value(before, test_id)
        after_p, after_support = _test_value(after, test_id)
        items.append({
            "id": test_id, "label": label, "null_hypothesis": null_hypothesis,
            "before_p_value": _round(before_p), "after_p_value": _round(after_p),
            "before_supports_stationarity": before_support,
            "after_supports_stationarity": after_support,
        })
    return items


def _candidate_profiles(values: np.ndarray, alpha: float, seasonal_period: int) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    before_variance = float(np.var(values, ddof=1))
    for method in METHOD_ORDER:
        item: dict[str, Any] = {
            "method": method, "label": METHOD_LABELS[method], "available": True,
            "reason": None, "consensus": None, "lost_observations": 0,
            "adf_p_value": None, "kpss_p_value": None, "acf_lag1": None,
            "variance_ratio": None, "over_differencing_warning": False,
        }
        try:
            transformed, metadata = apply_stationarity_series(
                values, method, seasonal_period=seasonal_period,
            )
            if len(transformed) < MIN_OBSERVATIONS:
                raise ValueError(
                    f"После преобразования останется {len(transformed)} наблюдений; нужно минимум {MIN_OBSERVATIONS}"
                )
            diagnostic = analyze_stationarity(
                pd.Series(transformed), alpha=alpha, include_confirmatory=False,
            )
            adf_p, _ = _test_value(diagnostic, "adf_level")
            kpss_p, _ = _test_value(diagnostic, "kpss_level")
            lag1 = _lag1(transformed)
            item.update(
                consensus=diagnostic.get("consensus"),
                lost_observations=metadata["lost_observations"],
                adf_p_value=_round(adf_p), kpss_p_value=_round(kpss_p),
                acf_lag1=_round(lag1),
                variance_ratio=_round(float(np.var(transformed, ddof=1)) / before_variance),
                over_differencing_warning=bool(lag1 is not None and lag1 < -0.5),
            )
        except (ValueError, TypeError, FloatingPointError, np.linalg.LinAlgError) as exc:
            item.update(available=False, reason=str(exc))
        profiles.append(item)
    return profiles


def _rolling_points(
    labels: list[str], original: np.ndarray, transformed: np.ndarray,
    lost: int, requested_window: int,
) -> tuple[list[dict[str, Any]], int]:
    n = len(original)
    window = min(requested_window, max(3, n // 2))
    aligned = np.full(n, np.nan, dtype=float)
    aligned[lost:] = transformed
    original_series = pd.Series(original)
    transformed_series = pd.Series(aligned)
    before_mean = original_series.rolling(window).mean()
    before_std = original_series.rolling(window).std(ddof=1)
    after_mean = transformed_series.rolling(window).mean()
    after_std = transformed_series.rolling(window).std(ddof=1)
    original_scale = float(np.std(original, ddof=1))
    transformed_scale = float(np.std(transformed, ddof=1))
    original_center = float(np.mean(original))
    transformed_center = float(np.mean(transformed))
    indices = np.arange(n, dtype=np.int64)
    if n > FULL_POINTS_THRESHOLD:
        indices = _lttb_indices(np.arange(n, dtype=float), original, TARGET_SAMPLED_POINTS)

    def optional(value: float) -> float | None:
        return float(value) if np.isfinite(value) else None

    return [
        {
            "x": labels[index], "original": float(original[index]),
            "transformed": optional(aligned[index]),
            "rolling_mean_z_before": optional((before_mean.iloc[index] - original_center) / original_scale),
            "rolling_mean_z_after": optional((after_mean.iloc[index] - transformed_center) / transformed_scale),
            "rolling_std_ratio_before": optional(before_std.iloc[index] / original_scale),
            "rolling_std_ratio_after": optional(after_std.iloc[index] / transformed_scale),
        }
        for index in indices
    ], window


def _acf_comparison(before: np.ndarray, after: np.ndarray) -> list[dict[str, Any]]:
    max_lag = max(1, min(40, len(before) // 4, len(after) // 4))
    before_values = acf(before, nlags=max_lag, fft=True)
    after_values = acf(after, nlags=max_lag, fft=True)
    before_conf = 1.96 / np.sqrt(len(before))
    after_conf = 1.96 / np.sqrt(len(after))
    return [
        {
            "lag": lag, "before": float(before_values[lag]), "after": float(after_values[lag]),
            "confidence_before": float(before_conf), "confidence_after": float(after_conf),
        }
        for lag in range(max_lag + 1)
    ]


def build_stationarity_profile(
    df: pd.DataFrame,
    column: str,
    method: str = "auto",
    *,
    alpha: float = 0.05,
    seasonal_period: int = 12,
    rolling_window: int = 12,
) -> dict[str, Any]:
    missing_count = int(pd.to_numeric(df[column], errors="coerce").isna().sum()) if column in df.columns else 0
    try:
        values, labels, _order, order_source, order_column, frequency, warnings_out = _prepare(df, column)
        before = analyze_stationarity(pd.Series(values), alpha=alpha)
        if not before["applicable"]:
            raise StationarityNotApplicable(str(before["reason"]))
        selected = _resolve_method(before.get("consensus"), method)
        if selected == "none":
            transformed = values.copy()
            metadata = {"lost_observations": 0}
            after = before
        else:
            transformed, metadata = apply_stationarity_series(
                values, selected, seasonal_period=seasonal_period,
            )
            if len(transformed) < MIN_OBSERVATIONS:
                raise StationarityNotApplicable(
                    f"После преобразования останется {len(transformed)} наблюдений; нужно минимум {MIN_OBSERVATIONS}"
                )
            after = analyze_stationarity(pd.Series(transformed), alpha=alpha)

        lost = int(metadata["lost_observations"])
        lag_before = _lag1(values)
        lag_after = _lag1(transformed)
        over_differencing = bool(selected != "none" and lag_after is not None and lag_after < -0.5)
        needs_transformation = before["consensus"] != "stationary"
        if before["consensus"] == "stationary":
            recommendation = (
                "ADF и KPSS согласованно поддерживают стационарность уровня; дополнительное дифференцирование не рекомендуется."
            )
        elif before["consensus"] == "trend-stationary":
            recommendation = (
                "Ряд стационарен вокруг детерминированного тренда. Сравните линейный detrend с моделью, где тренд задан явно; "
                "не назначайте d=1 автоматически."
            )
        elif before["consensus"] == "non-stationary":
            recommendation = (
                "ADF и KPSS согласованно указывают на единичный корень; первая разность — консервативный кандидат. "
                "Сезонную разность применяйте только при подтверждённом периоде."
            )
        else:
            recommendation = (
                "Тесты расходятся. Сначала проверьте детерминированный тренд и структурный разрыв; первая разность показана только для сравнения."
            )
        if selected == "linear_detrend":
            warnings_out.append(
                "Линейный тренд оценён по всей истории для offline-обзора; в backtest коэффициенты переоцениваются только на train."
            )
        if over_differencing:
            warnings_out.append(
                "ACF(1) после преобразования ниже −0,5 — эвристический сигнал возможного over-differencing, не самостоятельный тест."
            )
        warnings_out.extend(before.get("warnings", []))
        if after.get("consensus") not in {"stationary", "trend-stationary"} and selected != "none":
            warnings_out.append("Выбранное преобразование не дало согласованного вывода о стационарности.")

        points, _effective_window = _rolling_points(
            labels, values, transformed, lost, rolling_window,
        )
        return {
            "column": column, "applicable": True, "reason": None,
            "n_observations": len(values), "missing_count": 0,
            "min_observations": MIN_OBSERVATIONS, "alpha": float(alpha),
            "order_source": order_source, "order_column": order_column,
            "frequency": frequency, "regular": frequency is not None,
            "seasonal_period": int(seasonal_period), "selected_method": selected,
            "needs_transformation": needs_transformation,
            "consensus_before": before["consensus"], "consensus_after": after["consensus"],
            "lost_observations": lost, "acf_lag1_before": _round(lag_before),
            "acf_lag1_after": _round(lag_after),
            "variance_before": _round(float(np.var(values, ddof=1))),
            "variance_after": _round(float(np.var(transformed, ddof=1))),
            "over_differencing_warning": over_differencing,
            "tests": _test_comparison(before, after),
            "candidates": _candidate_profiles(values, alpha, seasonal_period),
            "points": points, "acf": _acf_comparison(values, transformed),
            "warnings": list(dict.fromkeys(str(item) for item in warnings_out if item)),
            "recommendation": recommendation,
            "methodology_note": (
                "Консенсус строится по ADF(c/ct) и KPSS(c/ct), имеющим противоположные H0; PP и Zivot–Andrews — подтверждающие диагностики. "
                "Auto не оптимизирует p-value по кандидатам: stationary → без преобразования, trend-stationary → detrend, иначе → Δ. "
                "Сезонный период приходит из аналитического решения, а число разностей должно быть минимальным."
            ),
        }
    except StationarityNotApplicable as exc:
        result = _empty_profile(column, str(exc), missing_count)
        result["alpha"] = float(alpha)
        result["seasonal_period"] = int(seasonal_period)
        return result
    except (ValueError, TypeError, FloatingPointError, np.linalg.LinAlgError) as exc:
        result = _empty_profile(column, f"Диагностика стационарности не выполнена: {exc}", missing_count)
        result["alpha"] = float(alpha)
        result["seasonal_period"] = int(seasonal_period)
        return result


def preview_stationarity_transformation(
    df: pd.DataFrame,
    column: str,
    method: str,
    *,
    seasonal_period: int = 12,
    confirm_non_causal: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if method not in STATIONARITY_TRANSFORM_METHODS:
        raise ValueError(f"Неподдерживаемый метод обеспечения стационарности: {method}")
    if method == "linear_detrend" and not confirm_non_causal:
        raise ValueError(
            "Выбран некаузальный offline-detrend: подтвердите оценивание тренда по полной исторической выборке"
        )
    suffix = OUTPUT_SUFFIXES[method]
    if method in {"seasonal_difference", "combined_difference"}:
        suffix = f"{suffix}{seasonal_period}"
    output_column = f"{column}_{suffix}"
    if output_column in df.columns:
        raise ValueError(f"Колонка '{output_column}' уже существует; удалите её перед повторным применением")

    values, _labels, order, order_source, order_column, frequency, _warnings = _prepare(df, column)
    transformed, metadata = apply_stationarity_series(
        values, method, seasonal_period=seasonal_period,
    )
    if len(transformed) < MIN_OBSERVATIONS:
        raise ValueError(
            f"После преобразования останется {len(transformed)} наблюдений; нужно минимум {MIN_OBSERVATIONS}"
        )
    lost = int(metadata["lost_observations"])
    ordered = df.iloc[order].reset_index(drop=True).copy(deep=True)
    result = ordered.iloc[lost:].reset_index(drop=True).copy(deep=True)
    result[output_column] = transformed
    stored_metadata = {
        "kind": "stationarity", "source_column": column,
        "output_column": output_column, **metadata,
        "fitted_on_n": int(len(values)), "order_source": order_source,
        "order_column": order_column, "frequency": frequency,
    }
    return result, {
        "column": column, "method": method, "output_column": output_column,
        "rows_before": int(len(df)), "rows_after": int(len(result)),
        "rows_dropped": lost, "columns_before": int(len(df.columns)),
        "columns_after": int(len(result.columns)), "metadata": stored_metadata,
    }
