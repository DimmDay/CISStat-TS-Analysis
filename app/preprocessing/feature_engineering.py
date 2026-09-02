"""Каузальная генерация признаков для одномерного временного ряда.

Периоды лагов измеряются в наблюдениях. Все признаки, зависящие от target,
строятся от ``target.shift(1)`` либо более глубокого лага: значение текущей
строки никогда не попадает в её же матрицу признаков.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from app.data.detectors import smart_to_datetime


ROLLING_STATISTICS = ("mean", "std", "min", "max")
CALENDAR_FEATURES = (
    "year", "quarter", "month_cyclic", "dayofweek_cyclic",
    "dayofyear_cyclic", "hour_cyclic", "is_weekend",
)
MAX_GENERATED_FEATURES = 100


def _integers(
    values: Iterable[int], label: str, *, minimum: int = 1, maximum: int = 10000,
) -> list[int]:
    raw = list(values)
    parsed: list[int] = []
    for value in raw:
        if isinstance(value, bool) or int(value) != value:
            raise ValueError(f"{label}: значения должны быть целыми")
        integer = int(value)
        if integer < minimum:
            raise ValueError(f"{label}: значения должны быть положительными и не меньше {minimum}")
        if integer > maximum:
            raise ValueError(f"{label}: значение {integer} превышает максимум {maximum}")
        parsed.append(integer)
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{label}: повторяющиеся значения не допускаются")
    return sorted(parsed)


def _catalog_item(
    name: str,
    family: str,
    formula: str,
    lookback: int,
    known_in_advance: bool,
    values: pd.Series,
) -> dict[str, Any]:
    missing = int(values.isna().sum())
    total = len(values)
    return {
        "name": name,
        "family": family,
        "formula": formula,
        "lookback": int(lookback),
        "known_in_advance": bool(known_in_advance),
        "causal": True,
        "missing_count": missing,
        "coverage": round((total - missing) / total, 6) if total else 0.0,
    }


def _add(
    generated: dict[str, pd.Series],
    catalog: list[dict[str, Any]],
    *,
    name: str,
    values: pd.Series | np.ndarray,
    family: str,
    formula: str,
    lookback: int = 0,
    known_in_advance: bool,
    index: pd.Index,
) -> None:
    series = values if isinstance(values, pd.Series) else pd.Series(values, index=index)
    series = pd.Series(series.to_numpy(), index=index)
    generated[name] = series
    catalog.append(_catalog_item(
        name, family, formula, lookback, known_in_advance, series,
    ))


def generate_time_series_features(
    df: pd.DataFrame,
    column: str,
    *,
    date_column: str | None = None,
    lags: Iterable[int] = (),
    rolling_windows: Iterable[int] = (),
    rolling_statistics: Iterable[str] = (),
    difference_lags: Iterable[int] = (),
    calendar_features: Iterable[str] = (),
    fourier_periods: Iterable[int] = (),
    fourier_harmonics: int = 1,
    include_time_index: bool = False,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Вернуть копию ``df`` с признаками и их машинно-читаемым каталогом."""
    if column not in df.columns:
        raise ValueError(f"Колонка '{column}' отсутствует в датасете")
    target = pd.to_numeric(df[column], errors="coerce")
    if target.isna().any():
        raise ValueError("Target содержит пропуски или нечисловые значения")
    if not np.isfinite(target.to_numpy(dtype=float)).all():
        raise ValueError("Target содержит бесконечные значения")

    parsed_lags = _integers(lags, "Лаги")
    parsed_windows = _integers(rolling_windows, "Rolling-окна", minimum=2)
    parsed_differences = _integers(difference_lags, "Разностные лаги")
    parsed_periods = _integers(fourier_periods, "Fourier-периоды", minimum=2)
    n = len(df)
    if any(lag >= n for lag in parsed_lags):
        raise ValueError(f"Каждый лаг должен быть меньше длины ряда N={n}")
    if any(window >= n for window in parsed_windows):
        raise ValueError(f"Каждое rolling-окно должно быть меньше длины ряда N={n}")
    if any(lag + 1 >= n for lag in parsed_differences):
        raise ValueError(f"Каждый разностный лаг должен оставлять хотя бы одно значение при N={n}")
    if any(period > n for period in parsed_periods):
        raise ValueError(f"Каждый Fourier-период должен быть не больше длины ряда N={n}")
    if isinstance(fourier_harmonics, bool) or int(fourier_harmonics) != fourier_harmonics:
        raise ValueError("Число Fourier-гармоник должно быть целым")
    harmonics = int(fourier_harmonics)
    if harmonics < 1 or harmonics > 5:
        raise ValueError("Число Fourier-гармоник должно быть от 1 до 5")

    stats = list(rolling_statistics)
    if len(set(stats)) != len(stats):
        raise ValueError("Rolling-статистики не должны повторяться")
    unsupported_stats = sorted(set(stats) - set(ROLLING_STATISTICS))
    if unsupported_stats:
        raise ValueError(f"Неподдерживаемые rolling-статистики: {unsupported_stats}")
    if parsed_windows and not stats:
        raise ValueError("Для rolling-окон выберите хотя бы одну статистику")
    if stats and not parsed_windows:
        raise ValueError("Rolling-статистики требуют хотя бы одно окно")

    calendar = list(calendar_features)
    if len(set(calendar)) != len(calendar):
        raise ValueError("Календарные признаки не должны повторяться")
    unsupported_calendar = sorted(set(calendar) - set(CALENDAR_FEATURES))
    if unsupported_calendar:
        raise ValueError(f"Неподдерживаемые календарные признаки: {unsupported_calendar}")
    dates: pd.Series | None = None
    if calendar:
        if not date_column or date_column not in df.columns:
            raise ValueError("Календарные признаки требуют распознанную временную колонку")
        # Переиспользуем общий parser платформы: голые годы 1994…2023
        # нельзя отдавать pd.to_datetime(int) — иначе это наносекунды 1970.
        dates = smart_to_datetime(df[date_column])
        if dates.isna().any():
            raise ValueError(f"В календарной колонке '{date_column}' есть нераспознанные даты")

    index = df.index
    generated: dict[str, pd.Series] = {}
    catalog: list[dict[str, Any]] = []

    for lag in parsed_lags:
        name = f"{column}_lag_{lag}"
        _add(generated, catalog, name=name, values=target.shift(lag), family="lag",
             formula=f"y[t-{lag}]", lookback=lag, known_in_advance=False, index=index)

    past = target.shift(1)
    for window in parsed_windows:
        rolling = past.rolling(window=window, min_periods=window)
        for statistic in stats:
            values = getattr(rolling, statistic)()
            name = f"{column}_roll_{statistic}_{window}"
            _add(generated, catalog, name=name, values=values, family="rolling",
                 formula=f"{statistic}(y[t-{window}:t-1])", lookback=window,
                 known_in_advance=False, index=index)

    for lag in parsed_differences:
        name = f"{column}_diff_lagged_{lag}"
        _add(generated, catalog, name=name, values=past.diff(lag), family="difference",
             formula=f"y[t-1] - y[t-{lag + 1}]", lookback=lag + 1,
             known_in_advance=False, index=index)

    if include_time_index:
        _add(generated, catalog, name="time_idx", values=np.arange(len(df), dtype=float),
             family="trend", formula="t", known_in_advance=True, index=index)

    if dates is not None and date_column is not None:
        prefix = date_column
        if "year" in calendar:
            _add(generated, catalog, name=f"{prefix}_year", values=dates.dt.year.astype(float),
                 family="calendar", formula="year(date)", known_in_advance=True, index=index)
        if "quarter" in calendar:
            _add(generated, catalog, name=f"{prefix}_quarter", values=dates.dt.quarter.astype(float),
                 family="calendar", formula="quarter(date)", known_in_advance=True, index=index)
        cycles = {
            "month_cyclic": (dates.dt.month.astype(float) - 1.0, 12.0, "month"),
            "dayofweek_cyclic": (dates.dt.dayofweek.astype(float), 7.0, "dayofweek"),
            "dayofyear_cyclic": (dates.dt.dayofyear.astype(float) - 1.0, 365.2425, "dayofyear"),
            "hour_cyclic": (dates.dt.hour.astype(float), 24.0, "hour"),
        }
        for feature, (component, period, suffix) in cycles.items():
            if feature not in calendar:
                continue
            angle = 2.0 * np.pi * component / period
            for trig, values in (("sin", np.sin(angle)), ("cos", np.cos(angle))):
                _add(generated, catalog, name=f"{prefix}_{suffix}_{trig}", values=values,
                     family="calendar", formula=f"{trig}(2π·{suffix}/{period:g})",
                     known_in_advance=True, index=index)
        if "is_weekend" in calendar:
            _add(generated, catalog, name=f"{prefix}_is_weekend",
                 values=(dates.dt.dayofweek >= 5).astype(float), family="calendar",
                 formula="1(dayofweek ≥ 5)", known_in_advance=True, index=index)

    time = np.arange(len(df), dtype=float)
    for period in parsed_periods:
        max_harmonic = min(harmonics, period // 2)
        for harmonic in range(1, max_harmonic + 1):
            angle = 2.0 * np.pi * harmonic * time / float(period)
            is_nyquist = period % 2 == 0 and harmonic == period // 2
            if not is_nyquist:
                _add(generated, catalog, name=f"fourier_p{period}_k{harmonic}_sin",
                     values=np.sin(angle), family="fourier",
                     formula=f"sin(2π·{harmonic}·t/{period})", known_in_advance=True, index=index)
            _add(generated, catalog, name=f"fourier_p{period}_k{harmonic}_cos",
                 values=np.cos(angle), family="fourier",
                 formula=f"cos(2π·{harmonic}·t/{period})", known_in_advance=True, index=index)

    if not generated:
        raise ValueError("Не выбран ни один признак для генерации")
    if len(generated) > MAX_GENERATED_FEATURES:
        raise ValueError(
            f"Запрошено {len(generated)} признаков; безопасный максимум — {MAX_GENERATED_FEATURES}"
        )
    collisions = sorted(set(generated) & set(df.columns))
    if collisions:
        raise ValueError(f"Колонки уже существуют в датасете: {collisions}")

    result = df.copy(deep=True)
    for name, values in generated.items():
        result[name] = values
    return result, catalog
