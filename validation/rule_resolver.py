"""Разрешение правил вкладки «Валидация».

Приоритет источников фиксирован: правила сессии > выбранный YAML-шаблон >
системные правила. Системный слой содержит только воспроизводимые проверки;
он не объявляет фактические категории датасета допустимым справочником и не
строит произвольные min/max из наблюдаемого диапазона.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from validation.engine import auto_generate_rules, load_rules


RuleSource = Literal["system", "template", "session", "not_applicable"]

CHECK_IDS = (
    "data_types", "formats", "ranges", "consistency", "uniqueness",
    "inclusion", "referential", "text_quality", "regularity", "sufficiency",
)

TEMPLATE_PATHS = {
    "default": "default_rules.yaml",
    "fao_prices": "fao_prices.yaml",
    "macro": "macro.yaml",
}

CHECK_SECTIONS = {
    "data_types": "schema",
    "formats": "formats",
    "ranges": "ranges",
    "consistency": "consistency",
    "uniqueness": "uniqueness",
    "inclusion": "inclusion",
    "referential": "referential",
    "text_quality": "text_quality",
    "regularity": "regularity",
    "sufficiency": "sufficiency",
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _load_template(template_id: str) -> dict[str, Any]:
    if template_id in ("system", "custom", ""):
        return {}
    filename = TEMPLATE_PATHS.get(template_id)
    if filename is None:
        raise ValueError(f"Неизвестный шаблон правил: {template_id}")
    repository_root = Path(__file__).resolve().parents[1]
    return load_rules(str(repository_root / "rules" / filename))


def _has_rule(config: dict[str, Any], section: str) -> bool:
    value = config.get(section)
    if section == "schema":
        return bool(isinstance(value, dict) and value.get("columns"))
    return bool(value)


def _system_applicability(df: pd.DataFrame, rules: dict[str, Any]) -> dict[str, bool]:
    date_columns = [
        column for column in df.columns
        if pd.api.types.is_datetime64_any_dtype(df[column])
        or any(token in str(column).lower() for token in ("date", "дата", "year", "год", "time", "время"))
    ]
    has_numeric = bool(df.select_dtypes(include="number").columns.tolist())
    return {
        "data_types": _has_rule(rules, "schema"),
        "formats": _has_rule(rules, "formats"),
        "ranges": _has_rule(rules, "ranges"),
        "consistency": _has_rule(rules, "consistency"),
        "uniqueness": True,
        "inclusion": False,
        "referential": False,
        "text_quality": bool(df.select_dtypes(include=["object", "string"]).columns.tolist()),
        "regularity": bool(date_columns),
        "sufficiency": bool(date_columns and has_numeric),
    }


def resolve_validation_rules(
    df: pd.DataFrame,
    *,
    template_id: str = "system",
    session_overrides: dict[str, Any] | None = None,
    type_schema: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, RuleSource]]:
    """Возвращает итоговые правила и источник эталона для каждой проверки."""
    system_rules = auto_generate_rules(df)
    template_rules = _load_template(template_id)
    overrides = deepcopy(session_overrides or {})

    if type_schema:
        overrides = _deep_merge(overrides, {
            "schema": {
                "columns": {
                    column: {"type": target_type, "nullable": True, "coerce": True}
                    for column, target_type in type_schema.items()
                    if column in df.columns
                }
            }
        })

    resolved = _deep_merge(_deep_merge(system_rules, template_rules), overrides)
    applicability = _system_applicability(df, system_rules)
    sources: dict[str, RuleSource] = {}
    for check_id in CHECK_IDS:
        section = CHECK_SECTIONS[check_id]
        if _has_rule(overrides, section):
            sources[check_id] = "session"
        elif _has_rule(template_rules, section):
            sources[check_id] = "template"
        elif applicability[check_id]:
            sources[check_id] = "system"
        else:
            sources[check_id] = "not_applicable"

    return resolved, sources
