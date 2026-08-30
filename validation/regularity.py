"""Профиль равномерности временного шага для engine/API/UI.

Модуль использует существующие детекторы структуры, но не зависит от
Streamlit. Одна и та же маска причин применяется общей валидацией,
обзором и строгим preview/apply мастера исправления.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.data.detectors import (
    score_all_columns_as_date,
    score_all_columns_as_entity_group,
    smart_to_datetime,
)


DEFAULT_GAP_MULTIPLIER = 1.5
SUPPORTED_ACTIONS = ("sort", "interpolate", "ffill", "bfill", "asfreq", "fictitious_zero", "flag")


def normalize_frequency(value: Any) -> str | None:
    """Проверяет pandas-частоту и возвращает её каноническое представление."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return pd.tseries.frequencies.to_offset(str(value).strip()).freqstr
    except (TypeError, ValueError) as ex:
        raise ValueError(f"Некорректная частота временного ряда: {value}") from ex


def _regularity_config(rules: dict[str, Any] | None) -> dict[str, Any]:
    raw = (rules or {}).get("regularity", {})
    return raw if isinstance(raw, dict) else {}


def _detect_columns(df: pd.DataFrame, config: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    configured_date = config.get("date_column") or config.get("date_col")
    if configured_date:
        date_column = str(configured_date)
        if date_column not in df.columns:
            return date_column, None, f"Временная колонка '{date_column}' отсутствует в датасете"
    else:
        candidates = score_all_columns_as_date(df)
        best = candidates[0] if candidates and candidates[0]["score"] > 0 else None
        date_column = best["name"] if best else None
        if date_column is None:
            return None, None, "Не определена временная колонка"

    configured_entity = config.get("entity_column") or config.get("entity_col")
    if configured_entity:
        entity_column = str(configured_entity)
        if entity_column not in df.columns:
            return date_column, entity_column, f"Группирующая колонка '{entity_column}' отсутствует в датасете"
        if entity_column == date_column:
            return date_column, entity_column, "Временная и группирующая колонки должны различаться"
    else:
        candidates = score_all_columns_as_entity_group(df, date_col=date_column)
        best = next((item for item in candidates if item["score"] > 0), None)
        entity_column = best["name"] if best else None
    return date_column, entity_column, None


def _interval_to_frequency(interval: pd.Timedelta | None) -> str | None:
    if interval is None or pd.isna(interval) or interval <= pd.Timedelta(0):
        return None
    seconds = interval.total_seconds()
    day = 86400
    if 364 * day <= seconds <= 367 * day:
        return "YS"
    if 89 * day <= seconds <= 93 * day:
        return "QS"
    if 27 * day <= seconds <= 32 * day:
        return "MS"
    if 6.5 * day <= seconds <= 7.5 * day:
        return "W"
    if 0.9 * day <= seconds <= 1.1 * day:
        return "D"
    if 3500 <= seconds <= 3700:
        return "h"
    if 50 <= seconds <= 70:
        return "min"
    try:
        return pd.tseries.frequencies.to_offset(interval).freqstr
    except (TypeError, ValueError):
        return None


def _missing_between(previous: pd.Timestamp, current: pd.Timestamp, frequency: str | None, modal: pd.Timedelta) -> int:
    if frequency:
        try:
            return max(len(pd.date_range(previous, current, freq=frequency)) - 2, 0)
        except (TypeError, ValueError):
            pass
    if modal <= pd.Timedelta(0):
        return 0
    return max(int(round((current - previous) / modal)) - 1, 0)


def _group_label(entity_column: str | None, group_value: Any) -> str:
    return "Весь датасет" if entity_column is None else str(group_value)


def _empty_profile(message: str, date_column: str | None = None, entity_column: str | None = None) -> dict[str, Any]:
    return {
        "applicable": False,
        "applicability_message": message,
        "date_column": date_column,
        "entity_column": entity_column,
        "target_frequency": None,
        "detected_frequency": None,
        "gap_threshold_multiplier": DEFAULT_GAP_MULTIPLIER,
        "is_sorted": True,
        "sort_violations": 0,
        "invalid_date_count": 0,
        "duplicate_count": 0,
        "gap_count": 0,
        "missing_period_count": 0,
        "total_violations": 0,
        "groups": [],
        "supported_actions": list(SUPPORTED_ACTIONS),
    }


def _group_frames(df: pd.DataFrame, entity_column: str | None):
    if entity_column is None:
        yield None, df
        return
    for value, group in df.groupby(entity_column, dropna=False, sort=False):
        yield value, group


def profile_regularity(df: pd.DataFrame, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Строит профиль сортировки, дублей и разрывов внутри каждой группы."""
    config = _regularity_config(rules)
    date_column, entity_column, detection_error = _detect_columns(df, config)
    if detection_error:
        return _empty_profile(detection_error, date_column, entity_column)
    assert date_column is not None

    converted = smart_to_datetime(df[date_column])
    invalid_date_count = int((df[date_column].notna() & converted.isna()).sum())
    if int(converted.notna().sum()) < 2:
        profile = _empty_profile(
            "Недостаточно корректных временных меток для оценки шага",
            date_column,
            entity_column,
        )
        profile["invalid_date_count"] = invalid_date_count
        profile["total_violations"] = invalid_date_count
        return profile

    working = df.copy(deep=False)
    working = working.assign(**{date_column: converted})
    multiplier = float(config.get("gap_threshold_multiplier", DEFAULT_GAP_MULTIPLIER))
    configured_frequency = normalize_frequency(config.get("frequency"))
    group_drafts: list[dict[str, Any]] = []
    modal_intervals: list[pd.Timedelta] = []
    inferred_codes: list[str] = []

    for group_value, group in _group_frames(working, entity_column):
        dates_original = group[date_column]
        negative = dates_original.diff().lt(pd.Timedelta(0)).fillna(False)
        sort_violations = int(negative.sum())
        valid = dates_original.dropna()
        duplicate_count = int(valid.duplicated(keep="first").sum())
        unique_dates = pd.Series(valid.drop_duplicates().sort_values().tolist(), dtype="datetime64[ns]")
        intervals = unique_dates.diff().dropna()
        positive_intervals = intervals[intervals > pd.Timedelta(0)]
        modal = None
        if not positive_intervals.empty:
            modes = positive_intervals.mode()
            modal = modes.iloc[0] if not modes.empty else positive_intervals.median()
            modal_intervals.append(modal)
        inferred = None
        if len(unique_dates) >= 3:
            try:
                inferred = pd.infer_freq(pd.DatetimeIndex(unique_dates))
            except (TypeError, ValueError):
                inferred = None
        if inferred:
            inferred_codes.append(inferred)
        group_drafts.append({
            "group_value": group_value,
            "group": _group_label(entity_column, group_value),
            "observations": int(len(group)),
            "inferred_frequency": inferred,
            "modal": modal,
            "unique_dates": unique_dates,
            "intervals": intervals,
            "duplicate_count": duplicate_count,
            "sort_violations": sort_violations,
        })

    detected_frequency = inferred_codes[0] if inferred_codes and len(set(inferred_codes)) == 1 else None
    fallback_modal = pd.Series(modal_intervals).median() if modal_intervals else None
    target_frequency = configured_frequency or detected_frequency or _interval_to_frequency(fallback_modal)
    groups: list[dict[str, Any]] = []

    for draft in group_drafts:
        modal = draft["modal"]
        intervals = draft["intervals"]
        gap_count = 0
        missing_period_count = 0
        examples = []
        if modal is not None and not intervals.empty:
            if configured_frequency:
                # Явная частота -- эталон сессии, а не описание уже
                # наблюдаемого ряда. Иначе стабильный ряд с шагом 2D
                # ошибочно прошёл бы правило frequency=D: его собственная
                # мода тоже равна 2D. Число ожидаемых шагов работает и с
                # календарными частотами MS/QS/YS, где Timedelta непостоянен.
                configured_gap_positions = []
                dates = draft["unique_dates"]
                for position in intervals.index:
                    previous = pd.Timestamp(dates.iloc[position - 1])
                    current = pd.Timestamp(dates.iloc[position])
                    missing = _missing_between(previous, current, configured_frequency, modal)
                    if missing + 1 > multiplier:
                        configured_gap_positions.append(position)
                gap_positions = intervals.loc[configured_gap_positions]
            else:
                gap_positions = intervals[intervals > modal * multiplier]
            gap_count = int(len(gap_positions))
            dates = draft["unique_dates"]
            for position in gap_positions.index[:5]:
                previous = pd.Timestamp(dates.iloc[position - 1])
                current = pd.Timestamp(dates.iloc[position])
                missing = _missing_between(previous, current, target_frequency, modal)
                missing_period_count += missing
                examples.append({
                    "previous_date": previous.isoformat(),
                    "current_date": current.isoformat(),
                    "missing_periods": missing,
                })
            if len(gap_positions) > 5:
                for position in gap_positions.index[5:]:
                    missing_period_count += _missing_between(
                        pd.Timestamp(dates.iloc[position - 1]),
                        pd.Timestamp(dates.iloc[position]),
                        target_frequency,
                        modal,
                    )
        groups.append({
            "group": draft["group"],
            "observations": draft["observations"],
            "inferred_frequency": draft["inferred_frequency"],
            "modal_interval": str(modal) if modal is not None else None,
            "gap_count": gap_count,
            "missing_period_count": missing_period_count,
            "duplicate_count": draft["duplicate_count"],
            "sort_violations": draft["sort_violations"],
            "gap_examples": examples,
        })

    sort_violations = sum(item["sort_violations"] for item in groups)
    duplicate_count = sum(item["duplicate_count"] for item in groups)
    gap_count = sum(item["gap_count"] for item in groups)
    missing_period_count = sum(item["missing_period_count"] for item in groups)
    return {
        "applicable": True,
        "applicability_message": None,
        "date_column": date_column,
        "entity_column": entity_column,
        "target_frequency": target_frequency,
        "detected_frequency": detected_frequency,
        "gap_threshold_multiplier": multiplier,
        "is_sorted": sort_violations == 0,
        "sort_violations": sort_violations,
        "invalid_date_count": invalid_date_count,
        "duplicate_count": duplicate_count,
        "gap_count": gap_count,
        "missing_period_count": missing_period_count,
        "total_violations": invalid_date_count + sort_violations + duplicate_count + gap_count,
        "groups": groups,
        "supported_actions": list(SUPPORTED_ACTIONS),
    }


def regularity_violation_mask(df: pd.DataFrame, rules: dict[str, Any] | None = None) -> pd.Series:
    """Помечает исходные строки, на которых обнаружена причина нарушения."""
    profile = profile_regularity(df, rules)
    mask = pd.Series(False, index=df.index, dtype=bool)
    if not profile["date_column"] or profile["date_column"] not in df.columns:
        return mask
    date_column = profile["date_column"]
    entity_column = profile["entity_column"]
    converted = smart_to_datetime(df[date_column])
    working = df.copy(deep=False).assign(**{date_column: converted})
    mask |= df[date_column].notna() & converted.isna()
    multiplier = profile["gap_threshold_multiplier"]
    for _value, group in _group_frames(working, entity_column):
        dates = group[date_column]
        mask.loc[group.index[dates.diff().lt(pd.Timedelta(0)).fillna(False)]] = True
        mask.loc[group.index[dates.notna() & dates.duplicated(keep="first")]] = True
        sorted_dates = dates.dropna().drop_duplicates().sort_values()
        intervals = sorted_dates.diff().dropna()
        positive = intervals[intervals > pd.Timedelta(0)]
        if positive.empty:
            continue
        modes = positive.mode()
        modal = modes.iloc[0] if not modes.empty else positive.median()
        mask.loc[intervals[intervals > modal * multiplier].index] = True
    return mask


# ── Визуализации Обзора остановки «Регулярность» (модуль «Предобработка»,
#    TsAnalysisPreprocessing.tsx) -- переиспользуют ту же группировку и
#    те же интервалы, что profile_regularity уже вычисляет внутри себя,
#    но profile_regularity не публикует сырые интервалы наружу (только
#    агрегаты + до 5 примеров разрывов). Эти две функции -- не новая
#    логика обнаружения, а другой СРЕЗ уже посчитанных данных. ──


def _select_group(df: pd.DataFrame, date_column: str, entity_column: str | None, group: str | None):
    """Возвращает (label, sub-DataFrame) для конкретной группы -- либо
    указанной по имени, либо (по умолчанию) с наибольшим числом строк,
    как самую репрезентативную для гистограммы/таймлайна."""
    if entity_column is None:
        return _group_label(None, None), df
    best_label, best_frame, best_size = None, None, -1
    for value, frame in _group_frames(df, entity_column):
        label = _group_label(entity_column, value)
        if group is not None and label != group:
            continue
        if len(frame) > best_size:
            best_label, best_frame, best_size = label, frame, len(frame)
    if best_frame is None:
        return None, None
    return best_label, best_frame


def regularity_intervals(
    df: pd.DataFrame, rules: dict[str, Any] | None = None, group: str | None = None, max_bins: int = 30
) -> dict[str, Any]:
    """Гистограмма интервалов (в секундах) между соседними уникальными
    датами внутри одной группы -- визуализирует ровно ту же величину,
    на которой основано обнаружение разрывов (modal × gap_threshold_multiplier).
    Панельные датасеты: по умолчанию берётся самая длинная по наблюдениям
    группа (см. _select_group); можно указать конкретную через group=.
    """
    profile = profile_regularity(df, rules)
    empty = {"group": group or "", "bins": [], "modal_seconds": None, "threshold_seconds": None}
    if not profile["applicable"]:
        return empty
    date_column = profile["date_column"]
    entity_column = profile["entity_column"]
    assert date_column is not None
    converted = smart_to_datetime(df[date_column])
    working = df.copy(deep=False).assign(**{date_column: converted})
    label, frame = _select_group(working, date_column, entity_column, group)
    if frame is None:
        return empty
    dates = frame[date_column].dropna().drop_duplicates().sort_values()
    intervals = dates.diff().dropna()
    positive = intervals[intervals > pd.Timedelta(0)]
    if positive.empty:
        return {**empty, "group": label}
    seconds = positive.dt.total_seconds()
    modes = positive.mode()
    modal = modes.iloc[0] if not modes.empty else positive.median()
    threshold_seconds = float(modal.total_seconds()) * float(profile["gap_threshold_multiplier"])

    n_bins = min(max_bins, seconds.nunique()) or 1
    counts, edges = np.histogram(seconds.to_numpy(), bins=n_bins)
    bins = [
        {"x0": float(edges[i]), "x1": float(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]
    return {
        "group": label,
        "bins": bins,
        "modal_seconds": float(modal.total_seconds()),
        "threshold_seconds": threshold_seconds,
    }


def regularity_timeline(
    df: pd.DataFrame, rules: dict[str, Any] | None = None, max_events: int = 500
) -> dict[str, Any]:
    """События нарушений (разрыв/дубль/нарушение сортировки) с датами --
    для таймлайн-графика Обзора: где именно во времени сосредоточены
    проблемы (единый кластер -- один сбойный период; разброс по всему
    ряду -- системная проблема источника данных)."""
    profile = profile_regularity(df, rules)
    empty = {
        "date_column": None, "entity_column": None, "min_date": None, "max_date": None,
        "events": [], "truncated": False,
    }
    if not profile["applicable"]:
        return empty
    date_column = profile["date_column"]
    entity_column = profile["entity_column"]
    assert date_column is not None
    converted = smart_to_datetime(df[date_column])
    working = df.copy(deep=False).assign(**{date_column: converted})
    multiplier = profile["gap_threshold_multiplier"]

    events: list[dict[str, Any]] = []
    all_dates: list[pd.Timestamp] = []
    for value, group in _group_frames(working, entity_column):
        label = _group_label(entity_column, value)
        dates_original = group[date_column]
        valid_dates = dates_original.dropna()
        all_dates.extend(valid_dates.tolist())

        negative = dates_original.diff().lt(pd.Timedelta(0)).fillna(False)
        for idx in dates_original.index[negative]:
            events.append({"date": dates_original.loc[idx].isoformat(), "kind": "sort_violation", "group": label})

        duplicated = valid_dates.duplicated(keep="first")
        for idx in valid_dates.index[duplicated]:
            events.append({"date": valid_dates.loc[idx].isoformat(), "kind": "duplicate", "group": label})

        unique_dates = valid_dates.drop_duplicates().sort_values()
        intervals = unique_dates.diff().dropna()
        positive = intervals[intervals > pd.Timedelta(0)]
        if not positive.empty:
            modes = positive.mode()
            modal = modes.iloc[0] if not modes.empty else positive.median()
            gap_positions = intervals[intervals > modal * multiplier]
            for position in gap_positions.index:
                events.append({"date": unique_dates.loc[position].isoformat(), "kind": "gap", "group": label})

    events.sort(key=lambda item: item["date"])
    truncated = len(events) > max_events
    return {
        "date_column": date_column,
        "entity_column": entity_column,
        "min_date": min(all_dates).isoformat() if all_dates else None,
        "max_date": max(all_dates).isoformat() if all_dates else None,
        "events": events[:max_events],
        "truncated": truncated,
    }

