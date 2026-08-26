"""Единый профиль достаточности наблюдений для engine/API/UI.

Достаточность описывает применимость классов методов, а не «плохие строки».
Поэтому профиль считает только пары с корректной датой и числовым значением
целевого ряда, отдельно внутри каждой сущности панельного датасета.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.data.detectors import (
    score_all_columns_as_date,
    score_all_columns_as_entity_group,
    smart_to_datetime,
)


DEFAULT_THRESHOLDS = {
    "min_obs_trend": 10,
    "min_obs_seasonality": 24,
    "min_obs_arima": 50,
    "min_obs_fft": 64,
    "min_obs_ml": 100,
    "min_seasons": 2,
}

CHECK_DEFINITIONS = (
    ("trend", "Тренд и базовые модели", "min_obs_trend", "наблюдений", "Тренд, линейная регрессия"),
    ("seasonality", "Сезонная структура", "min_obs_seasonality", "наблюдений", "STL, сезонные модели"),
    ("arima", "ARIMA / ETS", "min_obs_arima", "наблюдений", "ARIMA, SARIMA, ETS"),
    ("fft", "Спектральный анализ", "min_obs_fft", "наблюдений", "FFT, периодограмма"),
    ("ml", "ML-модели", "min_obs_ml", "наблюдений", "XGBoost, Prophet, нейросетевые модели"),
    ("seasons", "Сезонные циклы", "min_seasons", "циклов", "SARIMA, Holt-Winters"),
)

SUPPORTED_ACTIONS = ("restrict_models", "flag_groups", "drop_groups")
_DATE_NAME_TOKENS = ("date", "дата", "year", "год", "time", "время", "period", "период")


def _config(rules: dict[str, Any] | None) -> dict[str, Any]:
    raw = (rules or {}).get("sufficiency", {})
    return raw if isinstance(raw, dict) else {}


def _regularity_config(rules: dict[str, Any] | None) -> dict[str, Any]:
    raw = (rules or {}).get("regularity", {})
    return raw if isinstance(raw, dict) else {}


def _empty_profile(message: str, **columns: Any) -> dict[str, Any]:
    return {
        "applicable": False,
        "applicability_message": message,
        "date_column": columns.get("date_column"),
        "entity_column": columns.get("entity_column"),
        "target_column": columns.get("target_column"),
        "frequency": None,
        "seasonal_period": None,
        "groups_total": 0,
        "sufficient_groups": 0,
        "insufficient_groups": 0,
        "total_failed_checks": 0,
        "groups": [],
        "thresholds": [],
        "supported_actions": list(SUPPORTED_ACTIONS),
    }


def _detect_columns(
    df: pd.DataFrame,
    rules: dict[str, Any] | None,
    target_column: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    config = _config(rules)
    regularity = _regularity_config(rules)
    date_column = config.get("date_column") or config.get("date_col") or regularity.get("date_column") or regularity.get("date_col")
    if date_column:
        date_column = str(date_column)
        if date_column not in df.columns:
            return date_column, None, None, f"Временная колонка '{date_column}' отсутствует в датасете"
    else:
        candidates = score_all_columns_as_date(df)
        best = candidates[0] if candidates and candidates[0]["score"] > 0 else None
        date_column = str(best["name"]) if best else None
        if date_column is None:
            return None, None, None, "Не определена временная колонка"

    entity_column = config.get("entity_column") or config.get("entity_col") or regularity.get("entity_column") or regularity.get("entity_col")
    if entity_column:
        entity_column = str(entity_column)
        if entity_column not in df.columns:
            return date_column, entity_column, None, f"Группирующая колонка '{entity_column}' отсутствует в датасете"
        if entity_column == date_column:
            return date_column, entity_column, None, "Временная и группирующая колонки должны различаться"
    else:
        candidates = score_all_columns_as_entity_group(df, date_col=date_column)
        best = next((item for item in candidates if item["score"] > 0), None)
        entity_column = str(best["name"]) if best else None

    selected_target = target_column or config.get("target_column") or config.get("value_column")
    if selected_target:
        selected_target = str(selected_target)
        if selected_target not in df.columns:
            return date_column, entity_column, selected_target, f"Целевая колонка '{selected_target}' отсутствует в датасете"
    else:
        numeric = [str(column) for column in df.select_dtypes(include="number").columns]
        candidates = [
            column for column in numeric
            if column != date_column and not any(token in column.lower() for token in _DATE_NAME_TOKENS)
        ]
        selected_target = candidates[0] if candidates else next((column for column in numeric if column != date_column), None)
        if selected_target is None:
            return date_column, entity_column, None, "Не определена числовая целевая колонка"
    if selected_target in {date_column, entity_column}:
        return date_column, entity_column, selected_target, "Целевая колонка должна отличаться от временной и группирующей"
    return date_column, entity_column, selected_target, None


def _frequency_code(dates: pd.Series, configured: Any = None) -> str | None:
    if configured is not None and str(configured).strip():
        try:
            return pd.tseries.frequencies.to_offset(str(configured).strip()).freqstr
        except (TypeError, ValueError):
            return str(configured).strip()
    unique = pd.DatetimeIndex(dates.dropna().drop_duplicates().sort_values())
    if len(unique) >= 3:
        try:
            inferred = pd.infer_freq(unique)
            if inferred:
                return inferred
        except (TypeError, ValueError):
            pass
    if len(unique) < 2:
        return None
    days = pd.Series(unique).diff().dropna().median() / pd.Timedelta(days=1)
    if 0.9 <= days <= 1.1:
        return "D"
    if 6.5 <= days <= 7.5:
        return "W"
    if 27 <= days <= 32:
        return "MS"
    if 89 <= days <= 93:
        return "QS"
    if 364 <= days <= 367:
        return "YS"
    return None


def _default_seasonal_period(frequency: str | None) -> int:
    code = (frequency or "").upper()
    if code.startswith("H"):
        return 24
    if code.startswith("B"):
        return 5
    if code.startswith("D"):
        return 7
    if code.startswith("W"):
        return 52
    if code.startswith(("M", "BM")):
        return 12
    if code.startswith("Q"):
        return 4
    return 1


def _group_frames(df: pd.DataFrame, entity_column: str | None):
    if entity_column is None:
        yield None, df
        return
    yield from df.groupby(entity_column, dropna=False, sort=False)


def profile_sufficiency(
    df: pd.DataFrame,
    rules: dict[str, Any] | None = None,
    *,
    target_column: str | None = None,
) -> dict[str, Any]:
    """Строит единый профиль применимости методов по длине валидного ряда."""
    config = _config(rules)
    date_column, entity_column, selected_target, error = _detect_columns(df, rules, target_column)
    if error:
        return _empty_profile(
            error, date_column=date_column, entity_column=entity_column, target_column=selected_target,
        )
    assert date_column is not None and selected_target is not None

    converted_dates = smart_to_datetime(df[date_column])
    numeric_target = pd.to_numeric(df[selected_target], errors="coerce")
    if int(converted_dates.notna().sum()) < 2:
        return _empty_profile(
            "Недостаточно корректных временных меток для оценки длины ряда",
            date_column=date_column, entity_column=entity_column, target_column=selected_target,
        )

    thresholds = {
        key: int(config.get(key, default)) for key, default in DEFAULT_THRESHOLDS.items()
    }
    configured_frequency = config.get("frequency") or _regularity_config(rules).get("frequency")
    frequency = _frequency_code(converted_dates, configured_frequency)
    seasonal_period = int(config.get("seasonal_period", _default_seasonal_period(frequency)))
    threshold_rows = [
        {"id": check_id, "label": label, "threshold": thresholds[key], "unit": unit, "models": models}
        for check_id, label, key, unit, models in CHECK_DEFINITIONS
    ]

    working = df.copy(deep=False).assign(
        __sufficiency_date=converted_dates,
        __sufficiency_target=numeric_target,
    )
    groups: list[dict[str, Any]] = []
    for group_value, group in _group_frames(working, entity_column):
        valid_mask = group["__sufficiency_date"].notna() & group["__sufficiency_target"].notna()
        valid = group.loc[valid_mask]
        unique_timestamps = int(valid["__sufficiency_date"].nunique())
        # Повторы одной временной метки не увеличивают независимую длину
        # ряда: дубли устраняются отдельной остановкой регулярности.
        valid_observations = unique_timestamps
        seasonal_cycles = unique_timestamps // seasonal_period if seasonal_period > 0 else 0
        checks = []
        for check_id, label, key, unit, models in CHECK_DEFINITIONS:
            actual = seasonal_cycles if key == "min_seasons" else valid_observations
            threshold = thresholds[key]
            checks.append({
                "id": check_id,
                "label": label,
                "actual": actual,
                "threshold": threshold,
                "unit": unit,
                "passed": actual >= threshold,
                "deficit": max(threshold - actual, 0),
                "models": models,
            })
        failed = [item for item in checks if not item["passed"]]
        groups.append({
            "group": "Весь датасет" if entity_column is None else str(group_value),
            "rows_total": int(len(group)),
            "valid_observations": valid_observations,
            "invalid_target_count": int((group["__sufficiency_date"].notna() & group["__sufficiency_target"].isna()).sum()),
            "invalid_date_count": int(group["__sufficiency_date"].isna().sum()),
            "unique_timestamps": unique_timestamps,
            "frequency": _frequency_code(valid["__sufficiency_date"], configured_frequency) or frequency,
            "seasonal_period": seasonal_period,
            "seasonal_cycles": seasonal_cycles,
            "failed_checks": len(failed),
            "passed_checks": len(checks) - len(failed),
            "checks": checks,
            "available_capabilities": [item["models"] for item in checks if item["passed"]],
            "unavailable_capabilities": [item["models"] for item in failed],
        })

    insufficient_groups = sum(item["failed_checks"] > 0 for item in groups)
    return {
        "applicable": True,
        "applicability_message": None,
        "date_column": date_column,
        "entity_column": entity_column,
        "target_column": selected_target,
        "frequency": frequency,
        "seasonal_period": seasonal_period,
        "groups_total": len(groups),
        "sufficient_groups": len(groups) - insufficient_groups,
        "insufficient_groups": insufficient_groups,
        "total_failed_checks": sum(item["failed_checks"] for item in groups),
        "groups": groups,
        "thresholds": threshold_rows,
        "supported_actions": list(SUPPORTED_ACTIONS),
    }


def legacy_sufficiency_result(profile: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Адаптер старого Streamlit-контракта поверх нового профиля."""
    if not profile["applicable"]:
        return ([{
            "Тип": "Нет временной колонки",
            "Статус": "⚠️ Анализ невозможен",
            "Рекомендация": profile["applicability_message"],
        }], {})
    results = []
    recommendations = {}
    for group in profile["groups"]:
        failed = [item for item in group["checks"] if not item["passed"]]
        details = [
            f"❌ {item['label']}: {item['actual']} {item['unit']} < {item['threshold']} (доступно: {item['models']})"
            for item in failed
        ]
        recs = [f"• Для {item['label']} нужно ещё {item['deficit']} {item['unit']}" for item in failed]
        results.append({
            "Тип": "Панельная группа" if profile["entity_column"] else "Общий ряд",
            "Группа": group["group"],
            "Всего наблюдений": group["valid_observations"],
            "Частота": group["frequency"] or "unknown",
            "Полных сезонов": group["seasonal_cycles"],
            "Нарушений": group["failed_checks"],
            "Детали": details,
            "Рекомендации": "\n".join(recs) if recs else "Нарушений не выявлено",
            "Статус": "⚠️ Недостаточно" if failed else "✅ Достаточность обеспечена",
        })
        recommendations[group["group"]] = {
            "n_total": group["valid_observations"],
            "frequency": group["frequency"] or "unknown",
            "n_seasons": group["seasonal_cycles"],
            "available_models": group["available_capabilities"],
            "unavailable_models": group["unavailable_capabilities"],
        }
    return results, recommendations
