"""STL-анализ и безопасный preview/apply для остановки «Декомпозиция ряда».

Математика компонентов переиспользует ``app.preprocessing.decomposition``
(statsmodels STL). В отличие от старых бейджей на вкладке «Загрузка», этот
контур не изобретает отдельную «циклическую» компоненту и не складывает
дисперсии коррелированных слагаемых. Качество описывают strength-метрики
тренда/сезонности и тесты остатка.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.stats.stattools import jarque_bera
from statsmodels.tsa.stattools import acf

from app.data.detectors import smart_to_datetime
from app.preprocessing.decomposition import apply_decomposition
from apps.api.chart_data import (
    EXPANDED_FULL_POINTS_THRESHOLD,
    EXPANDED_TARGET_SAMPLED_POINTS,
    FULL_POINTS_THRESHOLD,
    TARGET_SAMPLED_POINTS,
    _lttb_indices,
)
from apps.api.decomposition_data import _resolve_period
from validation.regularity import profile_regularity


SUPPORTED_OUTPUTS = {"components", "seasonally_adjusted", "detrended"}


def _display_sampling_budget(detail_level: str) -> tuple[int, int]:
    """(порог полного ряда, целевое число точек LTTB) для ОТРИСОВКИ.

    Task 97.3 (spec_max_graf_fix.md §6.2): STL всегда считается по полному
    ряду; detail_level влияет только на объём отдаываемых точек: compact --
    текущее поведение, expanded -- полный ряд до расширенного порога
    (\"без даунсэмплинга, если в разумных пределах\"), выше -- LTTB до
    расширенного потолка (обе константы -- явные и тестируемые, §7.4).
    """
    if detail_level == "expanded":
        return EXPANDED_FULL_POINTS_THRESHOLD, EXPANDED_TARGET_SAMPLED_POINTS
    return FULL_POINTS_THRESHOLD, TARGET_SAMPLED_POINTS


class DecompositionNotApplicable(ValueError):
    pass


def _empty_profile(column: str, reason: str, robust: bool) -> dict[str, Any]:
    return {
        "column": column, "date_column": None, "applicable": False,
        "reason": reason, "method": "STL", "robust": bool(robust),
        "frequency": None, "period": None, "n_points": 0,
        "sampled": False, "original_count": 0,
        "trend_strength": None, "seasonal_strength": None,
        "residual_mean": None, "residual_std": None,
        "ljung_box_lag": None, "ljung_box_pvalue": None,
        "jarque_bera_pvalue": None, "points": [], "seasonal_pattern": [],
        "residual_acf": [], "warnings": [], "recommendation": reason,
        "methodology_note": "STL: observed = trend + seasonal + resid.",
    }


def _prepare(
    df: pd.DataFrame,
    column: str,
    period: int | None,
) -> tuple[pd.Series, pd.Series, str, str, int]:
    if column not in df.columns:
        raise DecompositionNotApplicable(f"Колонка '{column}' отсутствует в датасете")
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise DecompositionNotApplicable(f"Колонка '{column}' не числовая")

    regularity = profile_regularity(df, rules=None)
    date_column = regularity.get("date_column")
    if not date_column:
        raise DecompositionNotApplicable("Не удалось определить колонку времени")

    raw_dates = df[date_column]
    dates = smart_to_datetime(raw_dates)
    values = pd.to_numeric(df[column], errors="coerce")
    invalid_dates = int((raw_dates.notna() & dates.isna()).sum())
    missing_values = int(values.isna().sum())
    if invalid_dates:
        raise DecompositionNotApplicable(
            f"В колонке времени {invalid_dates} некорректных дат; сначала исправьте форматы"
        )
    if missing_values:
        raise DecompositionNotApplicable(
            f"В ряду {missing_values} пропусков; сначала завершите остановку «Пропуски»"
        )
    if dates.duplicated().any():
        raise DecompositionNotApplicable(
            "На одну дату приходится несколько значений — обнаружена панельная структура. "
            "Выберите одну сущность или агрегируйте ряд до одной точки на дату."
        )

    order = np.argsort(dates.to_numpy())
    sorted_dates = dates.iloc[order].reset_index(drop=True)
    sorted_values = values.iloc[order].reset_index(drop=True)
    inferred = pd.infer_freq(sorted_dates)
    if inferred is None:
        raise DecompositionNotApplicable(
            "Временная сетка нерегулярна; сначала завершите остановку «Регулярность ряда»"
        )

    if period is None:
        resolved = _resolve_period(inferred)
        if resolved is None:
            raise DecompositionNotApplicable(
                f"Для частоты {inferred} сезонный период автоматически не определён; укажите его вручную"
            )
        period = resolved[0]
    if isinstance(period, bool) or not isinstance(period, int) or period < 2:
        raise DecompositionNotApplicable("Сезонный период должен быть целым числом не меньше 2")
    minimum = 2 * period
    if len(sorted_values) < minimum:
        raise DecompositionNotApplicable(
            f"Недостаточно наблюдений: нужно минимум {minimum} (два полных периода), доступно {len(sorted_values)}"
        )
    if float(sorted_values.var()) < 1e-12:
        raise DecompositionNotApplicable("Ряд константный — декомпозиция неинформативна")

    series = pd.Series(
        sorted_values.to_numpy(dtype=float),
        index=pd.DatetimeIndex(sorted_dates),
        name=column,
    )
    return series, dates, date_column, inferred, period


def _strength(numerator: pd.Series, residual: pd.Series) -> float:
    denominator = float((numerator + residual).var())
    if not np.isfinite(denominator) or denominator <= 1e-12:
        return 0.0
    value = 1.0 - float(residual.var()) / denominator
    return float(np.clip(value, 0.0, 1.0))


def _analyze(
    df: pd.DataFrame,
    column: str,
    period: int | None,
    robust: bool,
    detail_level: str = "compact",
) -> tuple[dict[str, Any], dict[str, pd.Series], pd.Series]:
    series, original_dates, date_column, inferred, resolved_period = _prepare(df, column, period)
    decomposition = apply_decomposition(
        series, method="STL", period=resolved_period, robust=robust,
    )
    trend = decomposition["trend"].astype(float)
    seasonal = decomposition["seasonal"].astype(float)
    residual = decomposition["resid"].astype(float)

    trend_strength = _strength(trend, residual)
    seasonal_strength = _strength(seasonal, residual)
    nlags = min(2 * resolved_period, len(residual) - 1)
    diagnostic_lag = max(1, min(2 * resolved_period, len(residual) // 5))
    if float(residual.var()) <= 1e-12:
        ljung_pvalue = 1.0
        jb_pvalue = 1.0
        residual_acf_values = np.concatenate(([1.0], np.zeros(nlags)))
    else:
        ljung = acorr_ljungbox(residual, lags=[diagnostic_lag], return_df=True)
        ljung_pvalue = float(ljung["lb_pvalue"].iloc[0])
        jb_pvalue = float(jarque_bera(residual)[1])
        residual_acf_values = acf(residual, nlags=nlags, fft=True, missing="raise")

    n = len(series)
    full_threshold, target_points = _display_sampling_budget(detail_level)
    if n <= full_threshold:
        indices = np.arange(n)
        sampled = False
    else:
        indices = _lttb_indices(
            np.arange(n, dtype=float), residual.to_numpy(dtype=float), target_points,
        )
        sampled = True
    points = [
        {
            "x": series.index[i].isoformat(),
            "observed": float(series.iloc[i]),
            "trend": float(trend.iloc[i]),
            "seasonal": float(seasonal.iloc[i]),
            "resid": float(residual.iloc[i]),
        }
        for i in indices
    ]
    phase = np.arange(n) % resolved_period
    seasonal_pattern = [
        {
            "phase": int(i + 1),
            "label": str(i + 1),
            "value": float(seasonal.to_numpy()[phase == i].mean()),
        }
        for i in range(resolved_period)
    ]
    warnings: list[str] = []
    if ljung_pvalue < 0.05:
        warnings.append(
            "В остатке сохраняется автокорреляция (Ljung–Box p < 0,05): декомпозиция не извлекла всю временную структуру."
        )
    if jb_pvalue < 0.05:
        warnings.append(
            "Нормальность остатка отвергается (Jarque–Bera p < 0,05); это важно для параметрических интервалов, но не блокирует декомпозицию."
        )
    if seasonal_strength < 0.3:
        recommendation = "Сезонность слабая: сезонная корректировка, вероятно, не нужна."
    elif ljung_pvalue < 0.05:
        recommendation = "Сезонность выражена, но остаток ещё структурирован — проверьте период и модель ошибок."
    else:
        recommendation = "Сезонность выражена; компоненты пригодны для диагностического анализа."

    profile = {
        "column": column, "date_column": date_column, "applicable": True,
        "reason": None, "method": "STL", "robust": bool(robust),
        "frequency": inferred, "period": resolved_period, "n_points": n,
        "sampled": sampled, "original_count": n,
        "trend_strength": round(trend_strength, 4),
        "seasonal_strength": round(seasonal_strength, 4),
        "residual_mean": round(float(residual.mean()), 8),
        "residual_std": round(float(residual.std()), 8),
        "ljung_box_lag": diagnostic_lag,
        "ljung_box_pvalue": round(ljung_pvalue, 6),
        "jarque_bera_pvalue": round(jb_pvalue, 6),
        "points": points, "seasonal_pattern": seasonal_pattern,
        "residual_acf": [
            {"lag": int(lag), "value": float(value)}
            for lag, value in enumerate(residual_acf_values)
        ],
        "warnings": warnings, "recommendation": recommendation,
        "methodology_note": (
            "Робастный STL (LOESS): observed = trend + seasonal + resid. "
            "Strength = max(0, 1 − Var(resid) / Var(component + resid)). "
            "Декомпозиция всего ряда диагностическая; в прогнозном backtest её нужно оценивать заново только на train-части."
        ),
    }
    components = {"observed": series, "trend": trend, "seasonal": seasonal, "resid": residual}
    return profile, components, original_dates


def build_preprocessing_decomposition(
    df: pd.DataFrame,
    column: str,
    period: int | None = None,
    robust: bool = True,
    detail_level: str = "compact",
) -> dict[str, Any]:
    try:
        profile, _components, _dates = _analyze(df, column, period, robust, detail_level)
        return profile
    except DecompositionNotApplicable as exc:
        return _empty_profile(column, str(exc), robust)
    except (ValueError, TypeError, np.linalg.LinAlgError) as exc:
        return _empty_profile(column, f"Декомпозиция не выполнена: {exc}", robust)


def preview_decomposition_outputs(
    df: pd.DataFrame,
    column: str,
    period: int | None,
    robust: bool,
    outputs: Iterable[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    requested = list(dict.fromkeys(outputs))
    unknown = sorted(set(requested) - SUPPORTED_OUTPUTS)
    if unknown:
        raise ValueError(f"Неподдерживаемые выходы декомпозиции: {', '.join(unknown)}")
    if not requested:
        raise ValueError("Выберите хотя бы один выход декомпозиции")

    profile, components, original_dates = _analyze(df, column, period, robust)
    names: list[tuple[str, pd.Series]] = []
    if "components" in requested:
        names.extend([
            (f"{column}_trend", components["trend"]),
            (f"{column}_seasonal", components["seasonal"]),
            (f"{column}_resid", components["resid"]),
        ])
    if "seasonally_adjusted" in requested:
        names.append((f"{column}_seasonally_adjusted", _derived_series(components, "seasonally_adjusted")))
    if "detrended" in requested:
        names.append((f"{column}_detrended", _derived_series(components, "detrended")))

    existing = [name for name, _ in names if name in df.columns]
    if existing:
        raise ValueError(f"Колонка '{existing[0]}' уже существует; удалите её или выберите другой выход")

    result = df.copy(deep=True)
    parsed_dates = pd.DatetimeIndex(original_dates)
    for name, values in names:
        result[name] = values.reindex(parsed_dates).to_numpy(dtype=float)
    summary = {
        "column": column, "method": "STL", "robust": bool(robust),
        "period": profile["period"], "outputs": requested,
        "rows_before": int(len(df)), "rows_after": int(len(result)),
        "columns_before": int(len(df.columns)), "columns_after": int(len(result.columns)),
        "added_columns": [name for name, _ in names],
        "profile": profile,
    }
    return result, summary


def _derived_series(
    components: dict[str, pd.Series],
    output: str,
) -> pd.Series:
    observed = components["observed"]
    if output == "seasonally_adjusted":
        return observed - components["seasonal"]
    if output == "detrended":
        return observed - components["trend"]
    raise ValueError(f"Неизвестный выход: {output}")
