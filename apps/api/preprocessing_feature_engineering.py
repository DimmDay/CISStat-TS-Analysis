"""API-адаптер остановки «Предобработка → Генерация признаков»."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from app.preprocessing.feature_engineering import generate_time_series_features
from apps.api.chart_data import _lttb_indices


DATE_CONFIDENCE_THRESHOLD = 0.7
MIN_OBSERVATIONS = 8
FEATURE_PREVIEW_POINTS = 240


class FeatureGenerationNotApplicable(ValueError):
    pass


def _prepare(
    df: pd.DataFrame, column: str,
) -> tuple[pd.DataFrame, np.ndarray, list[str], str, str | None, str | None, list[str]]:
    if column not in df.columns:
        raise FeatureGenerationNotApplicable(f"Колонка '{column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise FeatureGenerationNotApplicable(f"Колонка '{column}' не числовая")
    numeric = pd.to_numeric(df[column], errors="coerce")
    missing = int(numeric.isna().sum())
    if missing:
        raise FeatureGenerationNotApplicable(
            f"Пропуски в target ({missing}); сначала завершите остановку «Пропуски»"
        )
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise FeatureGenerationNotApplicable("Target содержит бесконечные значения")
    if len(df) < MIN_OBSERVATIONS:
        raise FeatureGenerationNotApplicable(
            f"Для генерации признаков нужно минимум {MIN_OBSERVATIONS} наблюдений"
        )

    frame = df.copy(deep=True)
    order_source = "row_order"
    order_column: str | None = None
    frequency: str | None = None
    warnings = [
        "Временная ось уверенно не определена: лаги измеряются в текущем порядке строк, календарные признаки недоступны."
    ]
    candidates = [
        item for item in score_all_columns_as_date(df)
        if item["name"] != column and float(item["score"]) >= DATE_CONFIDENCE_THRESHOLD
    ]
    if candidates:
        order_column = str(candidates[0]["name"])
        parsed = smart_to_datetime(df[order_column])
        if parsed.isna().any():
            raise FeatureGenerationNotApplicable(
                f"В временной колонке «{order_column}» есть нераспознанные даты"
            )
        if parsed.duplicated().any():
            duplicates = int(parsed.duplicated(keep=False).sum())
            raise FeatureGenerationNotApplicable(
                f"В колонке «{order_column}» повторяются даты ({duplicates} строк): это похоже на панельные данные"
            )
        frequency = detect_column_frequency(parsed)["code"]
        if frequency is None:
            raise FeatureGenerationNotApplicable(
                "Временная сетка нерегулярна; сначала завершите остановку «Регулярность ряда»"
            )
        order = np.argsort(parsed.to_numpy(), kind="stable")
        frame = frame.iloc[order].reset_index(drop=True)
        ordered_dates = smart_to_datetime(frame[order_column])
        labels = [pd.Timestamp(value).isoformat() for value in ordered_dates]
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
        order_source = "time_column"
        warnings = []
    else:
        frame = frame.reset_index(drop=True)
        labels = [str(index + 1) for index in range(len(frame))]
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
    return frame, values, labels, order_source, order_column, frequency, warnings


def _calendar_suggestions(
    frame: pd.DataFrame, date_column: str | None, frequency: str | None,
) -> list[str]:
    if date_column is None:
        return []
    dates = smart_to_datetime(frame[date_column])
    suggestions: list[str] = []
    # time_idx уже предлагает гладкий тренд; raw year по умолчанию не
    # дублируем, но оставляем доступным для осознанного выбора в UI.
    code = (frequency or "").upper()
    subdaily = code.startswith(("H", "BH", "CBH", "T", "MIN", "S", "L", "U", "N"))
    daily = code.startswith(("D", "B"))
    weekly = code.startswith("W")
    if dates.dt.month.nunique() > 1 and not (daily or weekly or subdaily):
        suggestions.append("month_cyclic")
    if (daily or subdaily) and dates.dt.dayofweek.nunique() > 1:
        suggestions.extend(["dayofweek_cyclic", "is_weekend"])
    if (daily or weekly or subdaily) and dates.dt.dayofyear.nunique() > 1 and len(dates) >= 30:
        suggestions.append("dayofyear_cyclic")
    if subdaily and dates.dt.hour.nunique() > 1:
        suggestions.append("hour_cyclic")
    return suggestions


def _spectral_periods(
    selection: dict[str, Any] | None, column: str, n: int,
) -> tuple[list[int], list[str]]:
    if not selection or selection.get("source_column") != column:
        return [], []
    analyzed_on_n = int(selection.get("analyzed_on_n", -1))
    if analyzed_on_n != n:
        return [], [
            f"Сохранённый спектральный выбор устарел: анализ выполнен на N={analyzed_on_n}, сейчас N={n}. Пересчитайте спектр."
        ]
    periods = sorted({
        int(period) for period in selection.get("selected_periods", [])
        if 2 <= int(period) < n
    })
    return periods, []


def _optional(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 6) if np.isfinite(number) else None


def _sample_indices(values: np.ndarray) -> np.ndarray:
    indices = np.arange(len(values), dtype=np.int64)
    if len(values) > FEATURE_PREVIEW_POINTS:
        indices = _lttb_indices(
            np.arange(len(values), dtype=float), values, FEATURE_PREVIEW_POINTS,
        )
    return indices


def _visual_payloads(
    featured: pd.DataFrame,
    values: np.ndarray,
    labels: list[str],
    catalog: list[dict[str, Any]],
    suggested_lags: list[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    lag_names = [item["name"] for item in catalog if item["family"] == "lag"]
    rolling_names = [item["name"] for item in catalog if item["family"] == "rolling" and "_mean_" in item["name"]]
    fourier_names = [item["name"] for item in catalog if item["family"] == "fourier" and item["name"].endswith("_sin")]
    indices = _sample_indices(values)
    preview = [{
        "x": labels[index],
        "target": round(float(values[index]), 6),
        "lag": _optional(featured.iloc[index][lag_names[0]]) if lag_names else None,
        "rolling": _optional(featured.iloc[index][rolling_names[0]]) if rolling_names else None,
        "fourier": _optional(featured.iloc[index][fourier_names[0]]) if fourier_names else None,
    } for index in indices]

    correlation_lags = sorted(set(range(1, min(24, len(values) // 3) + 1)) | set(suggested_lags))
    correlations = []
    for lag in correlation_lags:
        if lag >= len(values) - 2:
            continue
        left, right = values[lag:], values[:-lag]
        correlation = None
        if float(np.std(left)) > 1e-12 and float(np.std(right)) > 1e-12:
            candidate = float(np.corrcoef(left, right)[0, 1])
            correlation = round(candidate, 6) if np.isfinite(candidate) else None
        correlations.append({"lag": lag, "correlation": correlation, "selected": lag in suggested_lags})

    availability = [{
        "name": item["name"], "family": item["family"],
        "available_count": len(featured) - int(item["missing_count"]),
        "missing_count": int(item["missing_count"]), "coverage": float(item["coverage"]),
    } for item in catalog]

    cyclic_names = [
        item["name"] for item in catalog
        if item["family"] in {"calendar", "fourier"}
        and (item["name"].endswith("_sin") or item["name"].endswith("_cos"))
    ][:6]
    cyclic = [
        {"x": labels[index], "feature": name, "value": _optional(featured.iloc[index][name])}
        for name in cyclic_names for index in indices
    ]
    return preview, correlations, availability, cyclic


def _empty_profile(column: str, reason: str) -> dict[str, Any]:
    return {
        "column": column, "applicable": False, "reason": reason,
        "n_observations": 0, "order_source": "row_order", "order_column": None,
        "frequency": None, "regular": False, "spectral_periods": [],
        "suggested_lags": [], "suggested_rolling_windows": [],
        "suggested_calendar_features": [], "suggested_fourier_periods": [],
        "generated": False, "saved_feature_names": [], "max_lookback": 0,
        "preview_feature_count": 0, "preview_points": [], "lag_correlations": [],
        "availability": [], "cyclic_points": [], "catalog": [], "warnings": [],
        "recommendation": reason,
        "methodology_note": (
            "Target-derived признаки должны использовать только прошлые значения; выбор набора признаков повторяется внутри train-fold."
        ),
    }


def build_feature_generation_profile(
    df: pd.DataFrame,
    column: str,
    *,
    spectral_selection: dict[str, Any] | None = None,
    saved_generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Построить рекомендации и визуальный preview без мутации датасета."""
    try:
        frame, values, labels, order_source, order_column, frequency, warnings = _prepare(df, column)
    except FeatureGenerationNotApplicable as exc:
        return _empty_profile(column, str(exc))

    periods, period_warnings = _spectral_periods(spectral_selection, column, len(frame))
    warnings.extend(period_warnings)
    suggested_lags = sorted(set([1, *periods]))
    suggested_windows = [3]
    if periods:
        suggested_windows.append(periods[0])
    elif len(frame) >= 21:
        suggested_windows.append(7)
    suggested_windows = sorted(set(window for window in suggested_windows if window < len(frame)))
    calendar = _calendar_suggestions(frame, order_column, frequency)
    code = (frequency or "").upper()
    if 12 in periods and code.startswith(("M", "BM", "CBM")) and "month_cyclic" in calendar:
        calendar.remove("month_cyclic")
        warnings.append(
            "Month sin/cos не добавлен в Auto-набор: Fourier period=12 на регулярном месячном ряду кодирует тот же базовый цикл."
        )
    if 7 in periods and code.startswith(("D", "B")) and "dayofweek_cyclic" in calendar:
        calendar.remove("dayofweek_cyclic")
        warnings.append(
            "Day-of-week sin/cos не добавлен в Auto-набор: Fourier period=7 уже кодирует ту же первую гармонику."
        )

    saved = saved_generation or {}
    saved_names = [str(name) for name in saved.get("feature_names", [])]
    generated = bool(
        saved.get("source_column") == column
        and int(saved.get("result_rows", -1)) == len(frame)
        and saved_names
        and all(name in frame.columns for name in saved_names)
    )
    preview_source = frame.drop(columns=[name for name in saved_names if name in frame.columns])
    try:
        featured, catalog = generate_time_series_features(
            preview_source, column, date_column=order_column,
            lags=suggested_lags, rolling_windows=suggested_windows,
            rolling_statistics=["mean", "std"], difference_lags=[1],
            calendar_features=calendar, fourier_periods=periods,
            fourier_harmonics=1, include_time_index=True,
        )
    except ValueError as exc:
        result = _empty_profile(column, str(exc))
        result.update(
            n_observations=len(frame), order_source=order_source,
            order_column=order_column, frequency=frequency,
            regular=order_source == "row_order" or frequency is not None,
            warnings=warnings,
        )
        return result
    preview, correlations, availability, cyclic = _visual_payloads(
        featured, values, labels, catalog, suggested_lags,
    )
    max_lookback = max([0, *suggested_lags, *suggested_windows, 2])
    recommendation = (
        "Набор уже применён к активному датасету. Проверяйте его полезность walk-forward/backtest внутри train-fold."
        if generated else
        "Начните с лага 1 и подтверждённых спектральных периодов; удалите избыточные признаки по временной валидации, а не по in-sample корреляции."
    )
    return {
        "column": column, "applicable": True, "reason": None,
        "n_observations": len(frame), "order_source": order_source,
        "order_column": order_column, "frequency": frequency,
        "regular": order_source == "row_order" or frequency is not None,
        "spectral_periods": periods, "suggested_lags": suggested_lags,
        "suggested_rolling_windows": suggested_windows,
        "suggested_calendar_features": calendar,
        "suggested_fourier_periods": periods, "generated": generated,
        "saved_feature_names": saved_names if generated else [],
        "max_lookback": max_lookback, "preview_feature_count": len(catalog),
        "preview_points": preview, "lag_correlations": correlations,
        "availability": availability, "cyclic_points": cyclic, "catalog": catalog,
        "warnings": warnings, "recommendation": recommendation,
        "methodology_note": (
            "Лаги используют pandas shift(k); rolling и разности сначала сдвигают target на 1, поэтому y[t] не входит в X[t]. "
            "Календарь известен заранее, а Fourier использует номер наблюдения и периоды спектрального анализа в наблюдениях. "
            "Формулы каузальны построчно, но выбор лагов/окон/гармоник по полной истории требует повторения внутри train-fold."
        ),
    }


def preview_feature_generation(
    df: pd.DataFrame,
    column: str,
    *,
    lags: list[int] | None = None,
    rolling_windows: list[int] | None = None,
    rolling_statistics: list[str] | None = None,
    difference_lags: list[int] | None = None,
    calendar_features: list[str] | None = None,
    fourier_periods: list[int] | None = None,
    fourier_harmonics: int = 1,
    include_time_index: bool = True,
    drop_warmup_rows: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Проверить конфигурацию на копии и вернуть готовый DataFrame/summary."""
    frame, _, _, order_source, order_column, frequency, warnings = _prepare(df, column)
    featured, catalog = generate_time_series_features(
        frame, column, date_column=order_column, lags=lags or [],
        rolling_windows=rolling_windows or [], rolling_statistics=rolling_statistics or [],
        difference_lags=difference_lags or [], calendar_features=calendar_features or [],
        fourier_periods=fourier_periods or [], fourier_harmonics=fourier_harmonics,
        include_time_index=include_time_index,
    )
    feature_names = [item["name"] for item in catalog]
    rows_before = len(featured)
    missing_rows = featured[feature_names].isna().any(axis=1)
    missing_indices = np.flatnonzero(missing_rows.to_numpy())
    if len(missing_indices) and not np.array_equal(missing_indices, np.arange(len(missing_indices))):
        raise ValueError("Пропуски сгенерированных признаков не ограничены warm-up префиксом")
    if drop_warmup_rows and len(missing_indices):
        featured = featured.iloc[len(missing_indices):].reset_index(drop=True)
    rows_dropped = rows_before - len(featured)
    max_lookback = max((int(item["lookback"]) for item in catalog), default=0)
    metadata = {
        "kind": "feature_generation", "source_column": column,
        "date_column": order_column, "feature_names": feature_names,
        "feature_catalog": catalog, "lags": sorted(lags or []),
        "rolling_windows": sorted(rolling_windows or []),
        "rolling_statistics": list(rolling_statistics or []),
        "difference_lags": sorted(difference_lags or []),
        "calendar_features": list(calendar_features or []),
        "fourier_periods": sorted(fourier_periods or []),
        "fourier_harmonics": int(fourier_harmonics),
        "include_time_index": bool(include_time_index),
        "drop_warmup_rows": bool(drop_warmup_rows),
        "target_shift": 1, "max_lookback": max_lookback,
        "rows_dropped": rows_dropped, "generated_on_n": rows_before,
        "result_rows": len(featured), "order_source": order_source,
        "order_column": order_column, "frequency": frequency,
        "causal": True, "row_level_modeling_safe": True,
        "selection_requires_train_fold": True,
        "forecast_contract": "target-derived лаги требуют наблюдаемую историю или рекурсивные прогнозы после первого горизонта",
    }
    if not drop_warmup_rows and len(missing_indices):
        warnings.append(
            f"Сохранено {len(missing_indices)} warm-up строк с NaN; большинство моделей потребует их исключить внутри train-fold."
        )
    return featured, {
        "column": column, "feature_names": feature_names,
        "feature_count": len(feature_names), "rows_before": rows_before,
        "rows_after": len(featured), "rows_dropped": rows_dropped,
        "max_lookback": max_lookback, "warnings": warnings, "metadata": metadata,
    }
