# validation/engine.py
"""
Ядро валидации датасетов.
Поддерживает: типы данных, диапазоны, домены, уникальность, бизнес-правила.
Не исправляет данные автоматически — только фиксирует ошибки.
"""

import pandas as pd
import numpy as np
import pandera as pa
from pandera import Check, Column, DataFrameSchema
from pandera.errors import SchemaErrors
from datetime import datetime, date
from pathlib import Path
import yaml
import re
import warnings
import os

from validation.inclusion import (
    coerce_inclusion_rule_to_series,
    inclusion_invalid_mask,
    normalize_inclusion_rule,
)
from validation.referential import profile_referential, referential_invalid_mask
from validation.regularity import profile_regularity
from validation.text_quality import profile_text_quality

warnings.filterwarnings("ignore", category=UserWarning)

# ── Валидация вкладки «Валидация» (10 проверок из TsAnalysisValidation.tsx)
# ── Синхронизация с тимлидом 2026-08-14: validate_dataframe расширена,
# ── чтобы сама вызывать все 9 sub-check функций (formats/ranges/consistency/
# ── uniqueness/inclusion/referential/text_quality/regularity/sufficiency) +
# ── pandera-схему (data_types) -- вместо ранее НЕподключенного состояния,
# ── где эти функции существовали, но /rules/validate их не вызывал.
#
# CheckStatus ("done"|"warning"|"pending") -- см. packages/ui/components/
# StatusIcon.tsx, НЕ менять набор значений без синхронизации с фронтом.


def load_rules(config_path: str = "rules/default_rules.yaml") -> dict:
    """Загружает правила валидации из YAML-конфига"""
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_check_expression(expr: str, column_series: pd.Series) -> pd.Series:
    """
    Парсит простые выражения валидации: ">= 0", "<= today", "in [A,B,C]"
    Возвращает булеву маску: True = валидно, False = ошибка
    """
    expr = expr.strip()

    # Сравнение с числом: >= 0, < 100, == 5
    match_num = re.match(r'^([<>=!]+)\s*(-?\d+\.?\d*)$', expr)
    if match_num:
        op, val = match_num.groups()
        val = float(val) if '.' in val else int(val)
        if op == '>=': return column_series >= val
        if op == '<=': return column_series <= val
        if op == '>': return column_series > val
        if op == '<': return column_series < val
        if op == '==': return column_series == val
        if op == '!=': return column_series != val

    # Сравнение с датой: <= today, >= 2020-01-01
    match_date = re.match(r'^([<>=!]+)\s*(today|\d{4}-\d{2}-\d{2})$', expr)
    if match_date:
        op, val = match_date.groups()
        if val == "today":
            val = pd.Timestamp.today()
        else:
            val = pd.Timestamp(val)
        if op == '>=': return column_series >= val
        if op == '<=': return column_series <= val
        if op == '>': return column_series > val
        if op == '<': return column_series < val

    # Проверка на вхождение в список: in [A,B,C]
    match_in = re.match(r'^in\s*\[([^\]]+)\]$', expr)
    if match_in:
        values = [v.strip().strip("'\"") for v in match_in.group(1).split(',')]
        return column_series.isin(values)

    # Regex для строк: matches ^[A-Z]{2}\d{4}$
    match_regex = re.match(r'^matches\s+(.+)$', expr)
    if match_regex:
        pattern = match_regex.group(1)
        return column_series.astype(str).str.match(pattern, na=False)

    # По умолчанию — всё валидно
    return pd.Series([True] * len(column_series), index=column_series.index)


def build_pandera_schema(rules: dict) -> DataFrameSchema:
    """Преобразует YAML-правила в схему Pandera для валидации"""
    columns = {}
    schema_config = rules.get("schema", {})

    for col_name, col_rules in schema_config.get("columns", {}).items():
        checks = []

        # Тип данных
        dtype_map = {
            "integer": pa.Int64, "int": pa.Int64,
            "float": pa.Float64, "double": pa.Float64,
            "string": pa.String, "str": pa.String,
            "bool": pa.Bool, "boolean": pa.Bool,
            "datetime64[ns]": pa.DateTime, "datetime": pa.DateTime,
            "date": pa.DateTime
        }
        dtype = dtype_map.get(col_rules.get("type", "").lower())

        # Nullable
        nullable = col_rules.get("nullable", True)
        if not nullable:
            checks.append(Check.notna())

        # Диапазоны для чисел
        if "min" in col_rules and "max" in col_rules:
            checks.append(Check.in_range(col_rules["min"], col_rules["max"]))
        elif "min" in col_rules:
            checks.append(Check.greater_than_or_equal_to(col_rules["min"]))
        elif "max" in col_rules:
            checks.append(Check.less_than_or_equal_to(col_rules["max"]))

        # Допустимые значения (домен)
        if "allowed_values" in col_rules:
            checks.append(Check.isin(col_rules["allowed_values"]))

        # Уникальность
        if col_rules.get("unique"):
            checks.append(Check.unique())

        # Regex для строк
        if "pattern" in col_rules:
            checks.append(Check.str_matches(col_rules["pattern"]))

        columns[col_name] = Column(
            dtype,
            *checks,
            nullable=nullable,
            required=col_rules.get("required", False),
            coerce=col_rules.get("coerce", True)
        )

    return DataFrameSchema(
        columns,
        required=schema_config.get("required_columns", []),
        strict=False,
        coerce=True
    )


def _run_all_checks(df: pd.DataFrame, rules: dict, schema_errors: dict, target_column: str | None = None) -> dict:
    """Запускает все 9 sub-check функций + агрегирует pandera schema_errors
    (data_types) в единый словарь {check_id: {status, count, items, scope}},
    ключи check_id -- те же 10 id, что в CHECKS (TsAnalysisValidation.tsx):
    data_types, formats, ranges, consistency, uniqueness, inclusion,
    referential, text_quality, regularity, sufficiency.

    status: "done" (0 нарушений) | "warning" (>0 нарушений) |
            "pending" (проверка неприменима -- нет данных для неё:
            например referential без справочника или нет date-колонки).
    items: [{label, count}] -- для графика детализации на фронте
    (BacktestComparisonChart -- прецедент того же паттерна в Моделировании).

    target_column (2026-08-14, per-column скоуп): если задан, часть
    проверок фильтруется до ЭТОЙ колонки -- ranges/formats/inclusion/
    referential/text_quality (per-column по своей природе, items уже
    имеют label=имя колонки) и sufficiency (validate_sufficiency
    принимает num_col напрямую). Остальные (data_types, consistency,
    uniqueness, regularity) ПРИНЦИПИАЛЬНО не скоупятся до одной колонки
    -- это либо строковый уровень (дубли строк), либо межколоночные
    правила (close>=open), либо ось времени (не значение), либо schema
    errors без надёжной привязки к одной колонке -- остаются
    dataset-wide вне зависимости от target_column, что отражено в
    scope="dataset" (честно показать на фронте, а не молча не менять
    поведение при выборе колонки).

    scope в ответе: "column" -- проверка учитывает target_column (если
    он задан), "dataset" -- всегда весь датасет, target_column не влияет.

    Не бросает исключений наружу -- одна упавшая sub-check-функция не
    должна ронять всю страницу «Валидация» (try/except на каждую,
    статус "pending" + count=None при ошибке, ошибка не проглатывается
    молча -- пишется в 'error' поле для отладки).
    """
    checks: dict = {}

    def _status(count: int | None) -> str:
        if count is None:
            return "pending"
        return "done" if count == 0 else "warning"

    def _safe(check_id: str, fn):
        try:
            checks[check_id] = fn()
        except Exception as ex:  # noqa: BLE001 -- см. докстринг: изоляция сбоя одной проверки
            checks[check_id] = {"status": "pending", "count": None, "items": [], "scope": "dataset", "error": str(ex)}

    # ── data_types (pandera-схема) -- dataset-wide, см. докстринг ──
    def _data_types():
        # Ожидаемая схема приходит из resolver: пользовательская схема,
        # шаблон либо безопасный системный вывод по dtype/приводимости.
        schema_columns = rules.get("schema", {}).get("columns", {})
        if not schema_columns:
            return {"status": "pending", "count": None, "items": [], "scope": "dataset"}
        count = sum(schema_errors.values()) if schema_errors else 0
        items = [{"label": str(k), "count": int(v)} for k, v in schema_errors.items()]
        return {"status": _status(count), "count": count, "items": items, "scope": "dataset"}
    _safe("data_types", _data_types)

    # ── formats (per-column) ──
    def _formats():
        raw = validate_formats(df, rules)  # validate_formats эмитит запись
        # ДАЖЕ для колонок без нарушений (Нарушений=0) -- в отличие от
        # ranges/inclusion/referential/text_quality (см. докстринг модуля).
        # Поэтому raw как есть -- надёжный сигнал применимости "правило
        # matched эту колонку", даже с 0 нарушений.
        if target_column is not None:
            matched = next((r for r in raw if r["Колонка"] == target_column), None)
            if matched is None:
                return {"status": "pending", "count": None, "items": [], "scope": "column"}
            count = matched["Нарушений"]
            items = [{"label": target_column, "count": count}] if count > 0 else []
            return {"status": _status(count), "count": count, "items": items, "scope": "column"}
        items = [{"label": r["Колонка"], "count": r["Нарушений"]} for r in raw if r["Нарушений"] > 0]
        count = sum(i["count"] for i in items) if raw else None
        return {"status": _status(count), "count": count, "items": items, "scope": "column"}
    _safe("formats", _formats)

    # ── ranges (per-column) ──
    def _ranges():
        raw, _masks, bounds = validate_ranges(df, rules)
        # bounds (не raw!) -- надёжный сигнал применимости: validate_ranges
        # заполняет rule_bounds[col] для КАЖДОЙ matched колонки, но
        # добавляет запись в raw ТОЛЬКО если есть нарушения (см. докстринг
        # модуля) -- по одному raw нельзя отличить "правило есть, 0
        # нарушений" от "правила нет вообще".
        if target_column is not None:
            if target_column not in bounds:
                return {"status": "pending", "count": None, "items": [], "scope": "column"}
            count = sum(r["Нарушений"] for r in raw if r["Колонка"] == target_column)
            items = [{"label": target_column, "count": count}] if count > 0 else []
            return {"status": _status(count), "count": count, "items": items, "scope": "column"}
        if not bounds:
            return {"status": "pending", "count": None, "items": [], "scope": "column"}
        items = [{"label": r["Колонка"], "count": r["Нарушений"]} for r in raw]
        count = sum(i["count"] for i in items)
        return {"status": _status(count), "count": count, "items": items, "scope": "column"}
    _safe("ranges", _ranges)

    # ── consistency (межколоночные правила) -- dataset-wide, см. докстринг ──
    def _consistency():
        raw = validate_consistency(df, rules)
        items = [{"label": r["Правило"], "count": r.get("Нарушений", 0)} for r in raw if "Нарушений" in r]
        count = sum(i["count"] for i in items) if items else None
        return {"status": _status(count), "count": count, "items": items, "scope": "dataset"}
    _safe("consistency", _consistency)

    # ── uniqueness (строковый уровень) -- dataset-wide, см. докстринг ──
    def _uniqueness():
        profile = profile_uniqueness(df, rules)
        if not profile["applicable"]:
            return {"status": "pending", "count": None, "items": [], "scope": "dataset"}
        count = int(profile["duplicate_rows"] or 0)
        label = (
            f"Дубли по ключу {' + '.join(profile['key_columns'])}"
            if profile["mode"] != "full_row"
            else "Полные дубликаты строк"
        )
        items = [{"label": label, "count": count}] if count > 0 else []
        return {"status": _status(count), "count": count, "items": items, "scope": "dataset"}
    _safe("uniqueness", _uniqueness)

    # ── inclusion (per-column) ──
    def _inclusion():
        profiles = profile_inclusion(df, rules)
        if target_column is not None:
            profiles = [item for item in profiles if item["column"] == target_column]
        if not profiles:
            return {"status": "pending", "count": None, "items": [], "scope": "column"}
        items = [
            {"label": item["column"], "count": item["invalid_count"]}
            for item in profiles if item["invalid_count"] > 0
        ]
        count = sum(item["invalid_count"] for item in profiles)
        return {"status": _status(count), "count": count, "items": items, "scope": "column"}
    _safe("inclusion", _inclusion)

    # ── referential (per-column, auto_generate_rules НЕ умеет генерировать
    # FK-справочники -- без явного шаблона правил всегда "pending", это
    # ЧЕСТНО отражает реальность: у нас нет родительской таблицы для сверки) ──
    def _referential():
        profiles = [item for item in profile_referential(df, rules) if item["applicable"]]
        if target_column is not None:
            profiles = [item for item in profiles if item["child_column"] == target_column]
        if not profiles:
            return {"status": "pending", "count": None, "items": [], "scope": "column"}
        items = [
            {"label": item["rule_name"], "count": item["invalid_count"]}
            for item in profiles if item["invalid_count"] > 0
        ]
        count = sum(int(item["invalid_count"] or 0) for item in profiles)
        return {"status": _status(count), "count": count, "items": items, "scope": "column"}
    _safe("referential", _referential)

    # ── text_quality (per-column, только текстовые колонки -- target_column
    # по контракту Phase 0.5 всегда числовой, поэтому со скоупом почти
    # всегда честно "pending", это ожидаемо, не баг) ──
    def _text_quality():
        text_columns = df.select_dtypes(include=["object", "string"]).columns
        if target_column is not None and target_column not in text_columns:
            # validate_text_quality сканирует только текстовые колонки --
            # применимость определяем по dtype НАПРЯМУЮ, а не по наличию
            # записи в raw (validate_text_quality тоже не эмитит запись
            # для чистой колонки -- по raw нельзя отличить "не текстовая"
            # от "текстовая, но без мусора").
            return {"status": "pending", "count": None, "items": [], "scope": "column"}
        if target_column is None and len(text_columns) == 0:
            return {"status": "pending", "count": None, "items": [], "scope": "column"}
        profile = profile_text_quality(df, rules)
        if target_column is not None:
            item = next((entry for entry in profile if entry["column"] == target_column), None)
            count = int(item["invalid_count"]) if item is not None else 0
            items = [{"label": target_column, "count": count}] if count > 0 else []
            return {"status": _status(count), "count": count, "items": items, "scope": "column"}
        items = [
            {"label": item["column"], "count": item["invalid_count"]}
            for item in profile if item["invalid_count"] > 0
        ]
        count = sum(i["count"] for i in items)
        return {"status": _status(count), "count": count, "items": items, "scope": "column"}
    _safe("text_quality", _text_quality)

    # ── regularity (ось времени, не значение) -- dataset-wide, см. докстринг ──
    def _regularity():
        profile = profile_regularity(df, rules)
        if not profile["applicable"]:
            return {"status": "pending", "count": None, "items": [], "scope": "dataset"}
        items = []
        for label, key in (
            ("Некорректные временные метки", "invalid_date_count"),
            ("Нарушения сортировки", "sort_violations"),
            ("Дубли временных меток", "duplicate_count"),
        ):
            if profile[key] > 0:
                items.append({"label": label, "count": int(profile[key])})
        items.extend(
            {"label": f"Разрывы: {group['group']}", "count": int(group["gap_count"])}
            for group in profile["groups"] if group["gap_count"] > 0
        )
        count = int(profile["total_violations"])
        return {"status": _status(count), "count": count, "items": items, "scope": "dataset"}
    _safe("regularity", _regularity)

    # ── sufficiency (per-column -- validate_sufficiency принимает num_col
    # НАПРЯМУЮ, самый прямой случай скоупинга из всех 10) ──
    def _sufficiency():
        raw, _recs = validate_sufficiency(df, rules, num_col=target_column)
        if raw and raw[0].get("Тип") == "Нет временной колонки":
            return {"status": "pending", "count": None, "items": [], "scope": "column"}
        items = [{"label": r.get("Группа", "?"), "count": r.get("Нарушений", 0)} for r in raw]
        count = sum(i["count"] for i in items)
        return {"status": _status(count), "count": count, "items": items, "scope": "column"}
    _safe("sufficiency", _sufficiency)

    return checks


def validate_dataframe(df: pd.DataFrame, rules: dict, target_column: str | None = None) -> dict:
    """
    Запускает полную валидацию датасета.
    Returns:
        dict с ключами:
        - is_valid: bool
        - errors: list[dict]
        - warnings: list[dict]
        - schema_errors: dict
        - validated_df: pd.DataFrame
        - summary: dict
    """
    result = {
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "schema_errors": {},
        "schema_errors_by_column": {},
        "validated_df": df.copy(),
        "summary": {},
        "checks": {},
    }

    if df.empty:
        result["errors"].append({"message": "Датасет пустой", "severity": "error"})
        result["is_valid"] = False
        return result

    # 1. Валидация схемы через Pandera
    try:
        schema = build_pandera_schema(rules)
        validated = schema.validate(df, lazy=True)
        result["validated_df"] = validated
    except SchemaErrors as e:
        result["is_valid"] = False
        if e.failure_cases is not None and not e.failure_cases.empty:
            result["schema_errors"] = e.failure_cases.groupby("check").size().to_dict()
            column_cases = e.failure_cases.dropna(subset=["column"])
            result["schema_errors_by_column"] = {
                str(column): int(count)
                for column, count in column_cases.groupby("column").size().items()
            }
            for _, row in e.failure_cases.head(100).iterrows():
                result["errors"].append({
                    "type": "schema",
                    "row": int(row["index"]) if pd.notna(row.get("index")) else None,
                    "column": row.get("column"),
                    "value": str(row.get("value")) if pd.notna(row.get("value")) else "NaN",
                    "check": row.get("check"),
                    "severity": "error"
                })
    except Exception as ex:
        result["errors"].append({"type": "schema_build", "message": str(ex), "severity": "error"})
        result["is_valid"] = False

    # 2. Проверка кастомных бизнес-правил
    for rule in rules.get("rules", []):
        try:
            col = rule.get("column")
            check_expr = rule.get("check")
            severity = rule.get("severity", "warning")
            rule_name = rule.get("name", "unnamed_rule")

            if col and col in df.columns and check_expr:
                series = df[col]
                mask = _parse_check_expression(check_expr, series)
                nullable = rules.get("schema", {}).get("columns", {}).get(col, {}).get("nullable", True)
                if nullable:
                    invalid_mask = ~mask & series.notna()
                else:
                    invalid_mask = ~mask

                if invalid_mask.any():
                    entry = {
                        "type": "business_rule",
                        "rule": rule_name,
                        "column": col,
                        "invalid_count": int(invalid_mask.sum()),
                        "sample_invalid_values": df.loc[invalid_mask, col].head(5).tolist(),
                        "severity": severity
                    }
                    if severity == "error":
                        result["errors"].append(entry)
                        result["is_valid"] = False
                    else:
                        result["warnings"].append(entry)
        except Exception as ex:
            result["errors"].append({
                "type": "rule_execution",
                "rule": rule.get("name"),
                "error": str(ex),
                "severity": "error"
            })
            result["is_valid"] = False

    # 3. Сводная статистика
    result["summary"] = {
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "total_errors": len(result["errors"]),
        "total_warnings": len(result["warnings"]),
        "schema_error_types": result["schema_errors"],
        "validation_timestamp": datetime.now().isoformat()
    }

    # 4. Пер-чек агрегация для вкладки «Валидация» (10 карточек слева,
    # см. _run_all_checks) -- добавлено 2026-08-14, аддитивно к уже
    # существующему контракту result (errors/warnings/summary не менялись,
    # /rules/validate в public.py/internal.py их не читают и не сломаются).
    result["checks"] = _run_all_checks(df, rules, result["schema_errors"], target_column=target_column)

    return result


# === ПРОВЕРКА ФОРМАТОВ (REGEX) ===
DEFAULT_FORMAT_PATTERNS = {
    "email": {
        "pattern": r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
        "description": "Email",
        "threshold": 95
    },
    "phone_ru": {
        "pattern": r"^(\+7|7|8)?[\s\-]?\(?[489][0-9]{2}\)?[\s\-]?[0-9]{3}[\s\-]?[0-9]{2}[\s\-]?[0-9]{2}$",
        "description": "Телефон РФ",
        "threshold": 90
    },
    "date_iso": {
        "pattern": r"^\d{4}-\d{2}-\d{2}$",
        "description": "Дата (YYYY-MM-DD)",
        "threshold": 98
    },
    "currency_code": {
        "pattern": r"^[A-Z]{3}$",
        "description": "Код валюты (ISO)",
        "threshold": 100
    }
}


def format_invalid_mask(series: pd.Series, pattern: str) -> pd.Series:
    """Единая маска regex-нарушений; пропуски не считаются нарушениями."""
    re.compile(pattern)
    return series.notna() & ~series.astype("string").str.fullmatch(pattern, na=False)


def profile_formats(df: pd.DataFrame, rules: dict) -> list[dict]:
    """Полный профиль применимых правил для проверки и мастера исправлений."""
    profiles = []
    formats_config = rules.get("formats", DEFAULT_FORMAT_PATTERNS)

    for col_name, cfg in formats_config.items():
        if isinstance(cfg, dict):
            pattern = cfg.get("pattern")
            threshold = cfg.get("threshold", 95)
        else:
            pattern = cfg
            threshold = 95

        if not pattern:
            continue

        if col_name not in df.columns:
            continue

        series = df[col_name]
        invalid_mask = format_invalid_mask(series, pattern)
        total_count = int(series.notna().sum())
        invalid_count = int(invalid_mask.sum())
        valid_count = total_count - invalid_count
        match_pct = (valid_count / total_count) * 100 if total_count else None
        profiles.append({
            "column": col_name,
            "pattern": pattern,
            "threshold": float(threshold),
            "total_count": total_count,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "match_pct": round(match_pct, 2) if match_pct is not None else None,
            "invalid_examples": [
                str(value) for value in series[invalid_mask].drop_duplicates().head(5).tolist()
            ],
        })

    return profiles


def validate_formats(df, rules):
    """Проверяет колонки датафрейма на соответствие регулярным выражениям."""
    results = []
    for item in profile_formats(df, rules):
        # Сохраняем прежний контракт: пустая колонка не делала проверку применимой.
        if item["total_count"] == 0:
            continue
        match_pct = item["match_pct"] or 0
        results.append({
            "Колонка": item["column"],
            "Шаблон": item["pattern"][:30] + "..." if len(item["pattern"]) > 30 else item["pattern"],
            "Всего записей": item["total_count"],
            "Нарушений": item["invalid_count"],
            "% match": f"{match_pct:.1f}%",
            "Статус": "✅ Норма" if match_pct >= item["threshold"] else "⚠️ Отклонение",
        })

    return results


def _inclusion_value_label(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return str(value)


def profile_inclusion(df: pd.DataFrame, rules: dict) -> list[dict]:
    """Profile explicit allowed-value domains without inferring a reference.

    Inclusion is a domain rule: deriving the allowed set from the same dataset
    would make every observed value valid by construction.  Consequently only
    non-empty rules for columns that actually exist are applicable.
    """
    profiles = []
    defaults = rules.get("inclusion_defaults", {})
    for column, config in rules.get("inclusion", {}).items():
        if column not in df.columns:
            continue
        allowed_values, default_value = normalize_inclusion_rule(
            config, defaults.get(column)
        )
        if not allowed_values:
            continue

        series = df[column]
        allowed_values, default_value = coerce_inclusion_rule_to_series(
            series, allowed_values, default_value
        )
        invalid_mask = inclusion_invalid_mask(series, allowed_values)
        total_count = int(series.notna().sum())
        invalid_count = int(invalid_mask.sum())
        valid_count = total_count - invalid_count
        invalid_pct = (invalid_count / total_count) * 100 if total_count else None
        invalid_values = [
            {"value": _inclusion_value_label(value), "count": int(count)}
            for value, count in series[invalid_mask].value_counts(dropna=False).head(10).items()
        ]
        valid_observed = series[series.notna() & series.isin(allowed_values)]
        default_valid = default_value is not None and default_value in allowed_values
        supported_actions = ["replace_null", "drop_rows", "flag"]
        if not valid_observed.empty:
            supported_actions.insert(0, "mode")
        if default_valid:
            supported_actions.insert(-1, "replace_default")
        profiles.append({
            "column": str(column),
            "allowed_values": allowed_values,
            "allowed_count": len(allowed_values),
            "total_count": total_count,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "invalid_pct": round(invalid_pct, 2) if invalid_pct is not None else None,
            "invalid_values": invalid_values,
            "default_value": default_value,
            "default_valid": default_valid,
            "supported_actions": supported_actions,
        })
    return profiles


_CONSISTENCY_OPERATORS = {
    "<": lambda left, right: left < right,
    "<=": lambda left, right: left <= right,
    ">": lambda left, right: left > right,
    ">=": lambda left, right: left >= right,
    "==": lambda left, right: left == right,
    "!=": lambda left, right: left != right,
}


def _consistency_group_column(df: pd.DataFrame, time_column: str, rule: dict) -> str | None:
    explicit = rule.get("group_column")
    if explicit:
        return explicit if explicit in df.columns and explicit != time_column else None
    for column in df.select_dtypes(include=["object", "string", "category"]).columns:
        if column == time_column:
            continue
        unique = df[column].nunique(dropna=True)
        if 1 < unique <= min(100, max(2, len(df) * 0.5)):
            return str(column)
    return None


def _coerce_consistency_time(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, errors="coerce")


def _chronology_evaluation(df: pd.DataFrame, rule: dict) -> dict:
    columns = [str(column) for column in rule.get("columns", [])]
    if not columns or columns[0] not in df.columns:
        missing = columns[0] if columns else "временная колонка"
        return {"applicable": False, "message": f"Колонка '{missing}' отсутствует"}

    time_column = columns[0]
    explicit_group = rule.get("group_column")
    if explicit_group and explicit_group not in df.columns:
        return {"applicable": False, "message": f"Колонка '{explicit_group}' отсутствует"}
    group_column = _consistency_group_column(df, time_column, rule)
    violation_mask = pd.Series(False, index=df.index)
    checked_count = 0
    invalid_count = 0
    examples: list[str] = []

    groups = df.groupby(group_column, sort=False, dropna=False) if group_column else [(None, df)]
    for group_name, group_df in groups:
        values = _coerce_consistency_time(group_df[time_column])
        previous = values.shift(1)
        comparable = values.notna() & previous.notna()
        reversals = comparable & (values < previous)
        checked_count += int(comparable.sum())
        invalid_count += int(reversals.sum())
        for index in group_df.index[reversals]:
            position = group_df.index.get_loc(index)
            previous_index = group_df.index[position - 1]
            violation_mask.loc[[previous_index, index]] = True
            if len(examples) < 5:
                prefix = f"{group_column}={group_name}: " if group_column else ""
                examples.append(
                    f"{prefix}{group_df.loc[previous_index, time_column]} → {group_df.loc[index, time_column]}"
                )

    return {
        "applicable": True,
        "mask": violation_mask,
        "checked_count": checked_count,
        "invalid_count": invalid_count,
        "examples": examples,
        "columns": [time_column],
        "time_column": time_column,
        "group_column": group_column,
        "correction_columns": [time_column],
        "supported_actions": ["sort_chronology", "drop_rows", "replace_null", "flag"],
    }


def _comparison_evaluation(
    df: pd.DataFrame,
    *,
    columns: list[str],
    operator: str,
    rule_type: str,
) -> dict:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        return {"applicable": False, "message": f"Колонка '{missing[0]}' отсутствует"}
    if len(columns) != 2 or operator not in _CONSISTENCY_OPERATORS:
        return {"applicable": False, "message": "Правило сравнения задано некорректно"}

    left = df[columns[0]]
    right = df[columns[1]]
    comparable = left.notna() & right.notna()
    try:
        valid = _CONSISTENCY_OPERATORS[operator](left, right)
    except (TypeError, ValueError):
        return {"applicable": False, "message": "Типы колонок нельзя сравнить"}
    invalid = comparable & ~valid.fillna(False)
    return {
        "applicable": True,
        "mask": invalid,
        "checked_count": int(comparable.sum()),
        "invalid_count": int(invalid.sum()),
        "examples": [
            f"{columns[0]}={row[columns[0]]}; {columns[1]}={row[columns[1]]}"
            for _, row in df.loc[invalid, columns].head(5).iterrows()
        ],
        "columns": columns,
        "time_column": None,
        "group_column": None,
        "correction_columns": [columns[0]],
        "supported_actions": ["drop_rows", "replace_null", "flag"],
        "rule_type": rule_type,
    }


def _single_column_evaluation(
    df: pd.DataFrame,
    *,
    column: str,
    valid_mask: pd.Series,
) -> dict:
    comparable = df[column].notna()
    invalid = comparable & ~valid_mask.fillna(False)
    return {
        "applicable": True,
        "mask": invalid,
        "checked_count": int(comparable.sum()),
        "invalid_count": int(invalid.sum()),
        "examples": [f"{column}={value}" for value in df.loc[invalid, column].head(5).tolist()],
        "columns": [column],
        "time_column": None,
        "group_column": None,
        "correction_columns": [column],
        "supported_actions": ["drop_rows", "replace_null", "flag"],
    }


def _condition_evaluation(df: pd.DataFrame, rule: dict) -> dict | None:
    """Безопасно поддерживает только явное сравнение колонок без eval()."""
    condition = str(rule.get("condition", "")).strip()
    match = re.fullmatch(r"([A-Za-z_][\w.]*)\s*(<=|>=|==|!=|<|>)\s*([A-Za-z_][\w.]*)", condition)
    if not match:
        return None
    left, operator, right = match.groups()
    result = _comparison_evaluation(
        df, columns=[left, right], operator=operator, rule_type="comparison"
    )
    result["condition"] = condition
    return result


def _evaluate_consistency_rule(df: pd.DataFrame, rule: dict) -> dict:
    rule_type = str(rule.get("type", "condition" if rule.get("condition") else "unknown"))
    columns = [str(column) for column in rule.get("columns", [])]

    if rule_type == "chronology":
        return _chronology_evaluation(df, rule)
    if rule_type == "comparison":
        return _comparison_evaluation(
            df,
            columns=columns,
            operator=str(rule.get("operator", "")),
            rule_type=rule_type,
        )
    if rule_type in {"negative_price", "positive_prices"}:
        if not columns or columns[0] not in df.columns:
            missing = columns[0] if columns else "целевая колонка"
            return {"applicable": False, "message": f"Колонка '{missing}' отсутствует"}
        numeric = pd.to_numeric(df[columns[0]], errors="coerce")
        valid = numeric >= 0 if rule_type == "negative_price" else numeric > 0
        return _single_column_evaluation(df, column=columns[0], valid_mask=valid)
    if rule_type == "profit_revenue":
        if len(columns) != 2:
            return {"applicable": False, "message": "Нужны колонки выручки и прибыли"}
        return _comparison_evaluation(
            df, columns=[columns[1], columns[0]], operator="<=", rule_type=rule_type
        )
    if rule_type == "energy_subsystem":
        if len(columns) != 2:
            return {"applicable": False, "message": "Нужны колонки общего и подсистемного потребления"}
        return _comparison_evaluation(
            df, columns=[columns[1], columns[0]], operator="<=", rule_type=rule_type
        )
    if rule_type == "steps_distance":
        if len(columns) != 2 or any(column not in df.columns for column in columns):
            return {"applicable": False, "message": "Нужны колонки шагов и расстояния"}
        comparable = df[columns].notna().all(axis=1)
        invalid = comparable & (df[columns[0]] == 0) & (df[columns[1]] > 0)
    elif rule_type == "speed_fuel":
        if len(columns) != 2 or any(column not in df.columns for column in columns):
            return {"applicable": False, "message": "Нужны колонки скорости и расхода топлива"}
        comparable = df[columns].notna().all(axis=1)
        invalid = comparable & (df[columns[0]] == 0) & (df[columns[1]] > 1)
    elif rule_type == "temp_precip":
        if len(columns) != 2 or any(column not in df.columns for column in columns):
            return {"applicable": False, "message": "Нужны колонки температуры и типа осадков"}
        comparable = df[columns].notna().all(axis=1)
        precipitation = df[columns[1]].astype(str).str.lower()
        snow = precipitation.str.contains(r"снег|snow", regex=True)
        rain = precipitation.str.contains(r"дожд|rain", regex=True)
        invalid = comparable & ((snow & (df[columns[0]] > 0)) | (rain & (df[columns[0]] < 0)))
    else:
        condition_result = _condition_evaluation(df, rule)
        if condition_result is not None:
            return condition_result
        return {"applicable": False, "message": f"Тип правила '{rule_type}' не поддерживается"}

    return {
        "applicable": True,
        "mask": invalid,
        "checked_count": int(comparable.sum()),
        "invalid_count": int(invalid.sum()),
        "examples": [
            "; ".join(f"{column}={row[column]}" for column in columns)
            for _, row in df.loc[invalid, columns].head(5).iterrows()
        ],
        "columns": columns,
        "time_column": None,
        "group_column": None,
        "correction_columns": [columns[-1]],
        "supported_actions": ["drop_rows", "replace_null", "flag"],
    }


def evaluate_consistency_rules(df: pd.DataFrame, rules: dict) -> list[dict]:
    """Единый источник масок для общей проверки, обзора и исправлений."""
    configured = list(rules.get("consistency", []) or [])
    if not configured:
        configured = list(auto_generate_rules(df).get("consistency", []))

    evaluations: list[dict] = []
    for index, rule in enumerate(configured):
        try:
            raw = _evaluate_consistency_rule(df, rule)
        except Exception as ex:  # изолируем ошибку одного предметного правила
            raw = {"applicable": False, "message": f"Ошибка правила: {ex}"}
        applicable = bool(raw.get("applicable"))
        invalid_count = int(raw.get("invalid_count", 0)) if applicable else None
        checked_count = int(raw.get("checked_count", 0)) if applicable else 0
        mask = raw.get("mask", pd.Series(False, index=df.index))
        evaluations.append({
            "rule_index": index,
            "rule_name": str(rule.get("name", f"Правило {index + 1}")),
            "rule_type": str(rule.get("type", "condition" if rule.get("condition") else "unknown")),
            "description": rule.get("description"),
            "columns": raw.get("columns", [str(column) for column in rule.get("columns", [])]),
            "time_column": raw.get("time_column"),
            "group_column": raw.get("group_column"),
            "applicable": applicable,
            "applicability_message": None if applicable else raw.get("message", "Правило неприменимо"),
            "checked_count": checked_count,
            "valid_count": checked_count - invalid_count if applicable else 0,
            "invalid_count": invalid_count,
            "affected_rows": int(mask.sum()) if applicable else 0,
            "invalid_examples": raw.get("examples", []),
            "supported_actions": raw.get("supported_actions", []),
            "correction_columns": raw.get("correction_columns", []),
            "mask": mask,
        })
    return evaluations


def profile_consistency(df: pd.DataFrame, rules: dict) -> list[dict]:
    """Полный профиль настроенных правил, включая pass и неприменимость."""
    return [
        {key: value for key, value in item.items() if key not in {"mask", "correction_columns"}}
        for item in evaluate_consistency_rules(df, rules)
    ]


def validate_consistency(df, rules):
    """Legacy-контракт поверх единого профилировщика согласованности."""
    results = []
    for item in evaluate_consistency_rules(df, rules):
        if not item["applicable"]:
            continue
        violations = int(item["invalid_count"] or 0)
        results.append({
            "Правило": item["rule_name"],
            "Тип": item["rule_type"],
            "Колонки": item["columns"],
            "Нарушений": violations,
            "Затронуто строк": item["affected_rows"],
            "Статус": "⚠️ Нарушено" if violations > 0 else "✅ Соблюдено",
            "mask": item["mask"],
        })
    return results


_UNIQUENESS_TIME_TOKENS = ("date", "дата", "year", "год", "time", "время", "period", "период")
_UNIQUENESS_ENTITY_TOKENS = ("country", "стра", "region", "регион", "entity", "group", "организац")


def _uniqueness_key(df: pd.DataFrame, rules: dict) -> tuple[bool, str, list[str], str | None]:
    """Разрешает явный, системный или полнострочный ключ без частичного fallback."""
    configured = rules.get("uniqueness", {}).get("composite_key", [])
    if configured:
        columns = [str(column) for column in configured]
        missing = [column for column in columns if column not in df.columns]
        if missing:
            return False, "composite_key", columns, f"Колонки ключа отсутствуют: {', '.join(missing)}"
        return True, "composite_key", columns, None

    time_columns = [
        str(column) for column in df.columns
        if pd.api.types.is_datetime64_any_dtype(df[column])
        or any(token in str(column).lower() for token in _UNIQUENESS_TIME_TOKENS)
    ]
    entity_columns = [
        str(column) for column in df.select_dtypes(include=["object", "string", "category"]).columns
        if df[column].nunique(dropna=True) > 0
        and any(token in str(column).lower() for token in _UNIQUENESS_ENTITY_TOKENS)
    ]
    if time_columns:
        return True, "inferred_key", entity_columns[:1] + time_columns[:1], None
    return True, "full_row", [str(column) for column in df.columns], None


def uniqueness_duplicate_mask(df: pd.DataFrame, rules: dict, *, keep=False) -> pd.Series:
    """Единая маска дубликатов для общей проверки, обзора и исправлений."""
    applicable, _mode, columns, message = _uniqueness_key(df, rules)
    if not applicable:
        raise ValueError(message or "Правило уникальности неприменимо")
    if not columns:
        return pd.Series(False, index=df.index, dtype=bool)
    return df.duplicated(subset=columns, keep=keep)


def _uniqueness_display_value(value) -> str:
    if value is None or pd.isna(value):
        return "∅"
    return str(value.item() if isinstance(value, np.generic) else value)


def profile_uniqueness(df: pd.DataFrame, rules: dict) -> dict:
    """Профиль ключа и групп дублей с раздельными бизнес-метриками."""
    applicable, mode, key_columns, message = _uniqueness_key(df, rules)
    supported = ["keep_first", "keep_last", "drop_all", "flag"]
    if mode != "full_row":
        supported.insert(3, "aggregate")
    base = {
        "applicable": applicable,
        "applicability_message": message,
        "mode": mode,
        "key_columns": key_columns,
        "total_rows": len(df),
        "valid_rows": 0,
        "duplicate_rows": None,
        "duplicate_groups": None,
        "redundant_rows": None,
        "duplicate_pct": None,
        "groups": [],
        "supported_actions": supported,
    }
    if not applicable:
        return base

    duplicate_mask = uniqueness_duplicate_mask(df, rules, keep=False)
    duplicate_rows = int(duplicate_mask.sum())
    groups: list[dict] = []
    if duplicate_rows:
        grouped = df.loc[duplicate_mask].groupby(key_columns, sort=False, dropna=False)
        for key, group in grouped:
            values = key if isinstance(key, tuple) else (key,)
            groups.append({
                "key_values": {
                    column: _uniqueness_display_value(value)
                    for column, value in zip(key_columns, values)
                },
                "occurrences": len(group),
                "redundant_rows": len(group) - 1,
                "row_numbers": [int(df.index.get_loc(index)) + 1 for index in group.index],
            })
    redundant_rows = sum(group["redundant_rows"] for group in groups)
    base.update({
        "valid_rows": len(df) - duplicate_rows,
        "duplicate_rows": duplicate_rows,
        "duplicate_groups": len(groups),
        "redundant_rows": redundant_rows,
        "duplicate_pct": round((duplicate_rows / len(df)) * 100, 2) if len(df) else 0.0,
        "groups": groups[:100],
    })
    return base


def range_invalid_mask(series: pd.Series, min_value, max_value) -> pd.Series:
    """Единая маска нарушений диапазона; пропуски проверяются отдельно."""
    mask = pd.Series(False, index=series.index)
    if min_value is not None:
        mask |= series.notna() & (series < min_value)
    if max_value is not None:
        mask |= series.notna() & (series > max_value)
    return mask


def _range_rule_for_column(column: str, range_rules: list[dict]):
    column_lower = str(column).lower()
    for rule in range_rules:
        keywords = rule.get("keywords", [])
        if any(str(keyword).lower() in column_lower for keyword in keywords):
            return rule
    return None


def _python_number(value):
    if value is None or pd.isna(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


def profile_ranges(df: pd.DataFrame, rules: dict) -> list[dict]:
    """Полный профиль всех применимых min/max-правил, включая 0 нарушений."""
    profiles = []
    range_rules = rules.get("ranges", [])
    for column in df.select_dtypes(include=["number"]).columns:
        rule = _range_rule_for_column(str(column), range_rules)
        if not rule:
            continue
        min_value = rule.get("min")
        max_value = rule.get("max")
        if min_value is None and max_value is None:
            continue

        series = df[column]
        invalid_mask = range_invalid_mask(series, min_value, max_value)
        total_count = int(series.notna().sum())
        invalid_count = int(invalid_mask.sum())
        valid_count = total_count - invalid_count
        invalid_pct = (invalid_count / total_count) * 100 if total_count else None
        finite = series.dropna()
        profiles.append({
            "column": str(column),
            "rule_name": (
                rule.get("name")
                or rule.get("description")
                or f"{column} — допустимый диапазон"
            ),
            "min_allowed": min_value,
            "max_allowed": max_value,
            "actual_min": _python_number(finite.min()) if not finite.empty else None,
            "actual_max": _python_number(finite.max()) if not finite.empty else None,
            "total_count": total_count,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "invalid_pct": round(invalid_pct, 2) if invalid_pct is not None else None,
            "invalid_examples": [
                _python_number(value)
                for value in series[invalid_mask].drop_duplicates().head(5).tolist()
            ],
        })
    return profiles


def validate_ranges(df, rules):
    """Проверяет числовые колонки на соответствие допустимым диапазонам."""
    results = []
    violation_masks = {}
    rule_bounds = {}

    for item in profile_ranges(df, rules):
        column = item["column"]
        min_value = item["min_allowed"]
        max_value = item["max_allowed"]
        rule_bounds[column] = (min_value, max_value)
        if item["invalid_count"] > 0:
            violation_masks[column] = range_invalid_mask(df[column], min_value, max_value)
            results.append({
                "Колонка": column,
                "Правило": (
                    f"{min_value if min_value is not None else '-∞'} ≤ x ≤ "
                    f"{max_value if max_value is not None else '∞'}"
                ),
                "Нарушений": item["invalid_count"],
                "% брака": f"{item['invalid_pct']:.2f}%",
                "Min факт": item["actual_min"],
                "Max факт": item["actual_max"],
            })

    return results, violation_masks, rule_bounds


def infer_system_type_schema(df: pd.DataFrame) -> dict:
    """Строит стартовую схему по dtype, приводимости значений и имени.

    Для object-колонок учитывается приводимость отдельных значений.
    Поэтому смешанная Price=[10, 20, "ошибка"] остаётся ожидаемо числовой
    и выявляет ошибку, а не объявляется строковой целиком.
    """
    numeric_name_tokens = (
        "price", "цена", "cost", "value", "amount", "сумм", "volume",
        "объем", "quantity", "count", "rate", "percent", "pct", "share",
    )
    date_name_tokens = ("date", "дата", "time", "время", "timestamp")
    year_name_tokens = ("year", "год")
    columns: dict[str, dict] = {}
    for column in df.columns:
        series = df[column]
        name = str(column).lower()
        expected = "string"

        if pd.api.types.is_bool_dtype(series):
            expected = "boolean"
        elif pd.api.types.is_integer_dtype(series):
            expected = "integer"
        elif pd.api.types.is_float_dtype(series):
            expected = "float"
        elif pd.api.types.is_datetime64_any_dtype(series):
            expected = "datetime"
        else:
            values = series.dropna()
            text_values = values.astype(str).str.strip()
            numeric = pd.to_numeric(text_values, errors="coerce")
            numeric_ratio = float(numeric.notna().mean()) if len(values) else 0.0
            if any(token in name for token in year_name_tokens) and numeric_ratio >= 0.5:
                expected = "integer"
            elif any(token in name for token in numeric_name_tokens) and numeric_ratio >= 0.5:
                finite = numeric.dropna()
                expected = "integer" if len(finite) and np.allclose(finite % 1, 0) else "float"
            elif numeric_ratio >= 0.9:
                finite = numeric.dropna()
                expected = "integer" if len(finite) and np.allclose(finite % 1, 0) else "float"
            elif any(token in name for token in date_name_tokens):
                parsed = pd.to_datetime(text_values, errors="coerce")
                if len(values) and float(parsed.notna().mean()) >= 0.8:
                    expected = "datetime"

        columns[str(column)] = {
            "type": expected,
            "nullable": True,
            "coerce": True,
        }
    return {"columns": columns}


def _system_format_rules(df: pd.DataFrame) -> dict:
    rules: dict[str, dict] = {}
    for column in df.select_dtypes(include=["object", "string"]).columns:
        name = str(column).lower()
        if "email" in name or "e-mail" in name:
            rules[str(column)] = {"pattern": DEFAULT_FORMAT_PATTERNS["email"]["pattern"], "threshold": 95}
        elif any(token in name for token in ("phone", "телефон", "mobile")):
            rules[str(column)] = {"pattern": DEFAULT_FORMAT_PATTERNS["phone_ru"]["pattern"], "threshold": 90}
        elif any(token in name for token in ("date", "дата")):
            rules[str(column)] = {"pattern": DEFAULT_FORMAT_PATTERNS["date_iso"]["pattern"], "threshold": 98}
        elif any(token in name for token in ("currency", "валюта", "currency_code")):
            rules[str(column)] = {"pattern": r"^[A-Za-z]{3}$", "threshold": 100}
    return rules


def auto_generate_rules(df: pd.DataFrame) -> dict:
    """Генерирует системные правила без круговых доменов и диапазонов."""
    rules = {
        "schema": {"columns": {}},
        "ranges": [],
        "inclusion": {},
        "consistency": [],
        "formats": {},
        "uniqueness": {},
    }

    if df.empty:
        return rules

    rules["schema"] = infer_system_type_schema(df)
    rules["formats"] = _system_format_rules(df)

    for col in df.select_dtypes(include='number').columns:
        col_lower = col.lower()
        if any(kw in col_lower for kw in ['price', 'цена', 'стоимость']):
            rules["ranges"].append({
                "name": f"{col} — положительная цена",
                "keywords": [str(col)],
                "min": 0,
                "max": None
            })
        elif any(kw in col_lower for kw in ['year', 'год']):
            rules["ranges"].append({
                "name": f"{col} — разумный год",
                "keywords": [str(col)],
                "min": 1900,
                "max": 2100
            })
        elif any(kw in col_lower for kw in ['percent', '%', 'доля']):
            rules["ranges"].append({
                "name": f"{col} — процент (0-100)",
                "keywords": [str(col)],
                "min": 0,
                "max": 100
            })
        # Неизвестной числовой семантике диапазон не назначается из
        # фактических min/max: это гарантировало бы ложное прохождение.

    date_cols = [
        c for c in df.columns
        if pd.api.types.is_datetime64_any_dtype(df[c])
        or any(token in str(c).lower() for token in (
            'year', 'год', 'date', 'дата', 'time', 'время', 'timestamp', 'period', 'период'
        ))
    ]
    if date_cols:
        rules["consistency"].append({
            "name": "Хронологический порядок",
            "type": "chronology",
            "description": "Проверка возрастания времени",
            "columns": [date_cols[0]]
        })

    return rules


def validate_referential(df, rules):
    """Legacy-контракт поверх единого профиля ссылочной целостности."""
    results = []
    violation_masks = {}
    for item in profile_referential(df, rules):
        if not item["applicable"] or not item["invalid_count"]:
            continue
        child_col = item["child_column"]
        mask = referential_invalid_mask(df[child_col], item["allowed_values"])
        violation_masks[item["rule_name"]] = mask
        results.append({
            "Правило": item["rule_name"],
            "Колонка": child_col,
            "Нарушений": item["invalid_count"],
            "% брака": f"{item['invalid_pct']:.2f}%",
            "allowed_values": item["allowed_values"],
            "default_value": item["default_value"],
            "Статус": "⚠️ Нарушено",
        })

    return results, violation_masks


def validate_text_quality(df, rules):
    """Legacy-контракт поверх единого профиля ``validation.text_quality``."""
    results = []
    violation_masks = {}
    from validation.text_quality import text_quality_masks

    issue_labels = {
        "garbage": "мусор",
        "empty": "пустые",
        "too_short": "короткие",
        "too_long": "длинные",
        "whitespace": "пробелы",
        "pattern": "шаблон",
    }
    for item in profile_text_quality(df, rules):
        violations = int(item["invalid_count"])
        if violations > 0:
            col = item["column"]
            mask = text_quality_masks(df[col], rules, column=col)["combined"]
            violation_masks[col] = mask
            violation_types = [
                f"{issue_labels[name]}: {count}"
                for name, count in item["issue_counts"].items() if count > 0
            ]
            results.append({
                "Колонка": col,
                "Тип": ", ".join(violation_types),
                "Нарушений": violations,
                "% брака": f"{item['invalid_pct']:.2f}%" if item["invalid_pct"] is not None else "N/A",
                "Статус": "️ Нарушено"
            })

    return results, violation_masks


def validate_regular_step(df, rules, date_col=None):
    """Проверка равномерности временного шага с учётом панельных данных."""
    # Защита от пустых/маленьких данных
    if df.empty or len(df) < 3:
        return [], {}, {}, {'is_sorted': True, 'sort_violations': 0, 'group_col': None, 'date_col': date_col}

    if not date_col:
        for c in df.columns:
            if any(kw in c.lower() for kw in ['date', 'дата', 'year', 'год', 'time', 'время']):
                date_col = c
                break
    
    if not date_col or date_col not in df.columns:
        return [], {}, {}, {'is_sorted': True, 'sort_violations': 0, 'group_col': None, 'date_col': None}

    results = []
    violation_masks = {}
    freq_info = {}
    
    # Поиск группирующей колонки
    group_col = None
    for c in df.columns:
        if c != date_col and df[c].dtype in ['object', 'string', 'category']:
            n_unique = df[c].nunique()
            if 1 < n_unique < 100:
                group_col = c
                break

    df_temp = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_temp[date_col]):
        df_temp[date_col] = pd.to_datetime(df_temp[date_col], errors='coerce')

    # Проверка сортировки
    is_sorted = True
    sort_violations = 0
    
    if group_col:
        for _, group_df in df_temp.groupby(group_col):
            if not group_df[date_col].is_monotonic_increasing:
                is_sorted = False
                sort_violations += int((group_df[date_col].diff() < pd.Timedelta(seconds=0)).sum())
    else:
        if not df_temp[date_col].is_monotonic_increasing:
            is_sorted = False
            sort_violations = int((df_temp[date_col].diff() < pd.Timedelta(seconds=0)).sum())

    # Ранний возврат, если не отсортировано
    if not is_sorted:
        return [], {}, {}, {'is_sorted': False, 'sort_violations': sort_violations, 'group_col': group_col, 'date_col': date_col}

    # Проверка регулярности (только если отсортировано)
    if group_col:
        for group_name, group_df in df_temp.groupby(group_col):
            group_sorted = group_df.sort_values(date_col)
            intervals = group_sorted[date_col].diff()
            modal = intervals.mode().iloc[0] if len(intervals.mode()) > 0 else intervals.median()
            gaps = int((intervals > modal * 1.5).sum())
            inferred = pd.infer_freq(group_sorted[date_col].drop_duplicates().sort_values())
            
            results.append({'Тип': 'Панельные данные', 'Группа': f"{group_col}={group_name}", 'Всего наблюдений': len(group_df), 'Частота': inferred, 'Пропусков': gaps, 'Статус': '✅' if gaps == 0 else '⚠️'})
            if gaps > 0:
                violation_masks[f"{group_col}_{group_name}"] = group_sorted.index.isin(group_sorted[intervals > modal * 1.5].index)
            freq_info['inferred_freq'] = inferred
    else:
        df_sorted = df_temp.sort_values(date_col)
        intervals = df_sorted[date_col].diff()
        modal = intervals.mode().iloc[0] if len(intervals.mode()) > 0 else intervals.median()
        gaps = int((intervals > modal * 1.5).sum())
        inferred = pd.infer_freq(df_sorted[date_col].drop_duplicates().sort_values())
        
        results.append({'Тип': 'Временной ряд', 'Группа': 'Весь датасет', 'Всего наблюдений': len(df), 'Частота': inferred, 'Пропусков': gaps, 'Статус': '✅' if gaps == 0 else '⚠️'})
        if gaps > 0:
            violation_masks['all'] = df_sorted.index.isin(df_sorted[intervals > modal * 1.5].index)
        freq_info['inferred_freq'] = inferred

    # ВОЗВРАЩАЕМ РОВНО 4 ЗНАЧЕНИЯ
    sort_info = {'is_sorted': True, 'sort_violations': 0, 'group_col': group_col, 'date_col': date_col}
    return results, violation_masks, freq_info, sort_info


def validate_sufficiency(df, rules, date_col=None, group_col=None, num_col=None):
    """Проверяет достаточность числа наблюдений для применения TS-моделей."""
    results = []
    recommendations = {}

    # Автоопределение колонок
    if date_col is None:
        date_candidates = [c for c in df.columns if 'year' in c.lower() or 'date' in c.lower() or 'дата' in c.lower()]
        if not date_candidates:
            results.append({
                'Тип': 'Нет временной колонки',
                'Статус': '⚠️ Анализ невозможен',
                'Рекомендация': 'Для проверки достаточности необходима колонка с датами/годами'
            })
            return results, recommendations
        date_col = date_candidates[0]

    if group_col is None:
        for c in df.columns:
            if c != date_col and df[c].dtype == 'object' and df[c].nunique() < 100:
                if 'country' in c.lower() or 'стран' in c.lower() or 'region' in c.lower():
                    group_col = c
                    break

    if num_col is None:
        num_cols = df.select_dtypes(include='number').columns.tolist()
        if num_cols:
            num_col = num_cols[0]

    # Пороговые значения
    sufficiency_rules = rules.get("sufficiency", {})
    thresholds = {
        'min_obs_trend': sufficiency_rules.get('min_obs_trend', 10),
        'min_obs_seasonality': sufficiency_rules.get('min_obs_seasonality', 24),
        'min_obs_arima': sufficiency_rules.get('min_obs_arima', 50),
        'min_obs_ml': sufficiency_rules.get('min_obs_ml', 100),
        'min_obs_fft': sufficiency_rules.get('min_obs_fft', 64),
        'min_seasons': sufficiency_rules.get('min_seasons', 2),
    }

    def detect_frequency(dates_series):
        """Определяет частоту временного ряда"""
        if pd.api.types.is_datetime64_any_dtype(dates_series):
            inferred = pd.infer_freq(dates_series.sort_values())
            if inferred:
                if 'D' in inferred:
                    return 'daily', 365
                elif 'M' in inferred or 'MS' in inferred:
                    return 'monthly', 12
                elif 'Q' in inferred:
                    return 'quarterly', 4
                elif 'Y' in inferred or 'A' in inferred:
                    return 'yearly', 1
        else:
            try:
                years = pd.to_datetime(dates_series.astype(str), format='%Y', errors='coerce')
                years = years.dropna()
                if len(years) > 1:
                    intervals = years.diff().dropna()
                    avg_interval = intervals.mean()
                    if avg_interval.days > 300:
                        return 'yearly', 1
                    elif avg_interval.days > 25:
                        return 'monthly', 12
            except:
                pass
        return 'unknown', 1

    def check_group_sufficiency(group_df, group_name=""):
        group_results = []
        n_total = len(group_df)
        if n_total == 0:
            return group_results

        freq_name, periods_per_year = detect_frequency(group_df[date_col])

        if pd.api.types.is_datetime64_any_dtype(group_df[date_col]):
            n_years = (group_df[date_col].max() - group_df[date_col].min()).days / 365.25
        else:
            # БАГ (найдено 2026-08-14, первое реальное подключение к API):
            # date_col часто хранится как ISO-строка ("2020-01-01"), ещё
            # не приведённая к datetime64 (валидация вызывается ДО стадии
            # «Предобработка»). Старый код сразу пытался pd.to_numeric --
            # на ISO-строке это молча даёт NaN для ВСЕХ значений (не
            # исключение), затем years.max()-years.min() на пустой Series
            # тоже молча даёт NaN (не исключение) -- except ниже никогда
            # не срабатывал, и NaN долетал до int(n_years) => ValueError,
            # роняя всю проверку "sufficiency" (перехватывалось _safe() в
            # _run_all_checks, но пользователь просто не видел результат).
            # Фикс: сначала пробуем как дату, потом как голый год.
            parsed_dates = pd.to_datetime(group_df[date_col], errors='coerce').dropna()
            if len(parsed_dates) >= 2:
                n_years = (parsed_dates.max() - parsed_dates.min()).days / 365.25
            else:
                years = pd.to_numeric(group_df[date_col], errors='coerce').dropna()
                if len(years) >= 2:
                    n_years = float(years.max() - years.min())
                else:
                    n_years = n_total / periods_per_year if periods_per_year > 0 else 0

        n_seasons = int(n_years) if periods_per_year == 1 else int(n_years)

        checks = [
            {
                'name': 'Минимум для тренда',
                'threshold': thresholds['min_obs_trend'],
                'actual': n_total,
                'passed': n_total >= thresholds['min_obs_trend'],
                'models': 'Базовый тренд, линейная регрессия'
            },
            {
                'name': 'Минимум для ARIMA',
                'threshold': thresholds['min_obs_arima'],
                'actual': n_total,
                'passed': n_total >= thresholds['min_obs_arima'],
                'models': 'ARIMA, SARIMA, Exponential Smoothing'
            },
            {
                'name': 'Минимум для сезонности',
                'threshold': thresholds['min_obs_seasonality'],
                'actual': n_total,
                'passed': n_total >= thresholds['min_obs_seasonality'],
                'models': 'STL-декомпозиция, сезонные модели'
            },
            {
                'name': 'Минимум для спектрального анализа (FFT)',
                'threshold': thresholds['min_obs_fft'],
                'actual': n_total,
                'passed': n_total >= thresholds['min_obs_fft'],
                'models': 'FFT, Wavelet-анализ, периодограмма'
            },
            {
                'name': 'Минимум для ML-моделей',
                'threshold': thresholds['min_obs_ml'],
                'actual': n_total,
                'passed': n_total >= thresholds['min_obs_ml'],
                'models': 'LSTM, XGBoost, Prophet (рекомендуется)'
            },
            {
                'name': 'Достаточность сезонов для SARIMA',
                'threshold': thresholds['min_seasons'],
                'actual': n_seasons,
                'passed': n_seasons >= thresholds['min_seasons'],
                'models': 'SARIMA, Holt-Winters (требуют ≥2 полных сезона)',
                'unit': 'сезонов'
            }
        ]

        failed_checks = [c for c in checks if not c['passed']]

        if failed_checks:
            entry = {
                'Тип': 'Панельная группа' if group_name else 'Общий ряд',
                'Группа': group_name if group_name else 'Весь датасет',
                'Всего наблюдений': n_total,
                'Частота': freq_name,
                'Периодов в году': periods_per_year,
                'Полных сезонов (лет)': n_seasons,
                'Нарушений': len(failed_checks),
                'Детали': [
                    f"❌ {c['name']}: {c['actual']} {c.get('unit', 'набл.')} < {c['threshold']} (доступно: {c['models']})"
                    for c in failed_checks
                ],
                'Рекомендации': _generate_recommendations(failed_checks, n_total, freq_name),
                'Статус': '⚠️ Недостаточно'
            }
            group_results.append(entry)
        else:
            group_results.append({
                'Тип': 'Панельная группа' if group_name else 'Общий ряд',
                'Группа': group_name if group_name else 'Весь датасет',
                'Всего наблюдений': n_total,
                'Частота': freq_name,
                'Полных сезонов': n_seasons,
                'Нарушений': 0,
                'Статус': '✅ Достаточность обеспечена'
            })

        recommendations[group_name if group_name else 'all'] = {
            'n_total': n_total,
            'frequency': freq_name,
            'n_seasons': n_seasons,
            'available_models': [c['models'] for c in checks if c['passed']],
            'unavailable_models': [c['models'] for c in failed_checks]
        }

        return group_results

    # Проверка для панельных или обычных данных
    if group_col and group_col in df.columns:
        for group_name, group_df in df.groupby(group_col):
            results.extend(check_group_sufficiency(group_df, group_name))
    else:
        results.extend(check_group_sufficiency(df, ""))

    return results, recommendations


def _generate_recommendations(failed_checks, n_total, freq_name):
    """Генерирует рекомендации на основе выявленных недостатков"""
    recs = []
    for check in failed_checks:
        deficit = check['threshold'] - check['actual']
        if 'сезон' in check.get('unit', ''):
            recs.append(f"• Для {check['name']} нужно ещё {deficit} полных сезонов")
        else:
            recs.append(f"• Для {check['name']} нужно ещё {deficit} наблюдений")

    if n_total < 50:
        recs.append("💡 Рассмотрите сбор дополнительных данных или агрегацию по более крупным периодам")
    if n_total < 100 and freq_name == 'yearly':
        recs.append("💡 Для годовых данных с n<100 рекомендуется использовать простые модели (ARIMA, ETS)")

    return "\n".join(recs) if recs else "Нарушений не выявлено"


def generate_validation_passport(df_before, val_results, df_after=None,
                                  dataset_name="Неизвестный датасет"):
    """
    Генерирует Паспорт валидации временного ряда.
    Returns:
        tuple: (df_passport, dq_score, metadata_dict)
    """
    from datetime import datetime

    passport = []
    n_total = len(df_before)

    # 1. Типы данных
    val = val_results.get("val", {})
    n_type_errors = len([e for e in val.get("errors", []) if e.get("type") == "schema"])
    passport.append({
        "Вид проверки": "1. Типы данных",
        "Измерение DQ": "Validity",
        "Метрика": "n_type_errors / n_total",
        "Алгоритм": "pandera.DataFrameSchema + df.dtypes → select_dtypes()",
        "Значение ДО": f"{n_type_errors} ошибок",
        "Значение ПОСЛЕ": "—",
        "Δ": "—",
        "Влияние на TS": "Некорректный тип ломает DatetimeIndex → ARIMA/Prophet",
        "Статус": "" if n_type_errors > 0 else "✅"
    })

    # 2. Форматы (Regex)
    pattern_results = val_results.get("pattern_results", [])
    n_format_issues = len([r for r in pattern_results if "Отклонение" in r.get("Статус", "")])
    passport.append({
        "Вид проверки": "2. Форматы (Regex)",
        "Измерение DQ": "Validity",
        "Метрика": "% match = valid/total",
        "Алгоритм": "Series.str.fullmatch(pattern) vs threshold",
        "Значение ДО": f"{n_format_issues} колонок с отклонениями",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Невалидные форматы → ошибки парсинга дат",
        "Статус": "❌" if n_format_issues > 0 else "✅"
    })

    # 3. Диапазоны значений
    range_results = val_results.get("range_results", [])
    n_range_violations = sum(r.get("Нарушений", 0) for r in range_results)
    passport.append({
        "Вид проверки": "3. Диапазоны значений",
        "Измерение DQ": "Accuracy",
        "Метрика": "n_out_of_range / n_total",
        "Алгоритм": "df[col] < min | df[col] > max по правилам YAML",
        "Значение ДО": f"{n_range_violations} нарушений",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Выбросы искажают mean/std, ломают STL",
        "Статус": "❌" if n_range_violations > 0 else "✅"
    })

    # 4. Согласованность
    consistency_results = val_results.get("consistency", [])
    n_consistency_violations = sum(r.get("Нарушений", 0) for r in consistency_results)
    passport.append({
        "Вид проверки": "4. Согласованность",
        "Измерение DQ": "Consistency",
        "Метрика": "n_violations / valid",
        "Алгоритм": "Векторизованные маски df[A] OP df[B] + diff() внутри групп",
        "Значение ДО": f"{n_consistency_violations} нарушений",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Искажает лаги, ломает cumsum и VAR/VECM",
        "Статус": "❌" if n_consistency_violations > 0 else "✅"
    })

    # 5. Уникальность (с учётом панельных данных)
    categorical_cols = df_before.select_dtypes(include=['object', 'string', 'category']).columns.tolist()
    date_cols = [c for c in df_before.columns if 'date' in c.lower() or 'дата' in c.lower() or
                 'year' in c.lower() or 'год' in c.lower() or
                 pd.api.types.is_datetime64_any_dtype(df_before[c])]

    panel_candidates = []
    for col in categorical_cols:
        if col not in date_cols:
            unique_ratio = df_before[col].nunique() / len(df_before)
            if unique_ratio < 0.5 and df_before[col].nunique() > 1:
                panel_candidates.append(col)

    is_panel_data = len(panel_candidates) > 0 and len(date_cols) > 0

    if is_panel_data:
        check_cols = panel_candidates + date_cols[:1]
        duplicates = df_before.duplicated(subset=check_cols, keep=False).sum()
        uniqueness_status = "✅" if duplicates == 0 else "❌"
        uniqueness_value = f"{duplicates} дубликатов по комбинации {check_cols}"
        uniqueness_impact = f"Дубли комбинации {check_cols} ломают DatetimeIndex, resample(), STL"
    else:
        duplicates = df_before.duplicated(keep=False).sum()
        uniqueness_status = "✅" if duplicates == 0 else "❌"
        uniqueness_value = f"{duplicates} дубликатов"
        uniqueness_impact = "Дубли дат ломают DatetimeIndex, resample(), STL"

    passport.append({
        "Вид проверки": "5. Уникальность",
        "Измерение DQ": "Uniqueness",
        "Метрика": "% dup = duplicated/total",
        "Алгоритм": "df.duplicated(keep=False) / subset",
        "Значение ДО": uniqueness_value,
        "Значение ПОСЛЕ": "—",
        "Δ": "—",
        "Влияние на TS": uniqueness_impact,
        "Статус": uniqueness_status
    })

    # 6. Справочники (Inclusion)
    inclusion_results = val_results.get("inclusion", [])
    n_inclusion_violations = sum(r.get("Нарушений", 0) for r in inclusion_results)
    passport.append({
        "Вид проверки": "6. Справочники (Inclusion)",
        "Измерение DQ": "Validity",
        "Метрика": "% invalid = not_in_set/total",
        "Алгоритм": "Series.isin(allowed_values)",
        "Значение ДО": f"{n_inclusion_violations} нарушений",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Неизвестные категории ломают groupby, pivot",
        "Статус": "❌" if n_inclusion_violations > 0 else "✅"
    })

    # 7. Ссылочная целостность
    ref_results = val_results.get("referential", [])
    n_ref_violations = sum(r.get("Нарушений", 0) for r in ref_results)
    passport.append({
        "Вид проверки": "7. Ссылочная целостность",
        "Измерение DQ": "Consistency",
        "Метрика": "% orphans = violations/valid",
        "Алгоритм": "~df[child].isin(parent_values) & notna()",
        "Значение ДО": f"{n_ref_violations} 'сиротских' записей",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Разрыв связей искажает агрегацию",
        "Статус": "❌" if n_ref_violations > 0 else "✅"
    })

    # 8. Хронологический порядок
    timeliness_results = val_results.get("timeliness", [])
    n_time_reversals = sum(r.get("Нарушений", 0) for r in timeliness_results)
    passport.append({
        "Вид проверки": "8. Хронологический порядок",
        "Измерение DQ": "Timeliness",
        "Метрика": "n_time_reversals / n_total",
        "Алгоритм": "groupby(country).sort_values(date).diff() < 0",
        "Значение ДО": f"{n_time_reversals} нарушений порядка",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Нарушение порядка → некорректные лаги",
        "Статус": "❌" if n_time_reversals > 0 else "✅"
    })

    # 9. Равномерность шага
    regularity_results = val_results.get("regularity", [])
    n_gaps = sum(r.get("Пропусков", r.get("Всего пропусков", 0)) for r in regularity_results)
    freq_info = val_results.get("regularity_freq_info", {})
    inferred_freq = freq_info.get("inferred_freq", "—") if freq_info else "—"
    passport.append({
        "Вид проверки": "9. Равномерность шага",
        "Измерение DQ": "Timeliness",
        "Метрика": "n_gaps; inferred_freq",
        "Алгоритм": "pd.infer_freq() + diff() > 1.5×mode",
        "Значение ДО": f"{n_gaps} пропусков; freq={inferred_freq}",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Ломает ARIMA/SARIMA (требуют регулярный индекс)",
        "Статус": "❌" if n_gaps > 0 else "✅"
    })

    # 10. Достаточность наблюдений
    sufficiency_results = val_results.get("sufficiency", [])
    n_insufficient = len([r for r in sufficiency_results if r.get("Нарушений", 0) > 0])
    passport.append({
        "Вид проверки": "10. Достаточность числа наблюдений",
        "Измерение DQ": "Completeness",
        "Метрика": "n_total vs пороги (trend≥10, ARIMA≥50, ML≥100)",
        "Алгоритм": "Сравнение с порогами + расчёт полных сезонов",
        "Значение ДО": f"{n_insufficient} групп с недостаточным объёмом",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Недостаток → переобучение, нестабильные параметры",
        "Статус": "❌" if n_insufficient > 0 else "✅"
    })

    # 11. Пропуски
    miss = val_results.get("miss", {})
    total_missing = 0
    if isinstance(miss, dict):
        if "summary" in miss:
            total_missing = miss["summary"].get("total_missing", 0)
        else:
            total_missing = sum(v.get("missing_count", 0) if isinstance(v, dict) else 0
                               for v in miss.values())

    missing_pct = (total_missing / (n_total * len(df_before.columns)) * 100) if n_total > 0 else 0
    passport.append({
        "Вид проверки": "11. Полнота данных (Missing)",
        "Измерение DQ": "Completeness",
        "Метрика": "% missing = NaN / (n_rows × n_cols)",
        "Алгоритм": "df.isna().sum()",
        "Значение ДО": f"{total_missing} пропусков ({missing_pct:.1f}%)",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Пропуски искажают автокорреляцию",
        "Статус": "" if total_missing > 0 else "✅"
    })

    # 12. Выбросы
    outl = val_results.get("outl", {})
    n_outliers = 0
    if isinstance(outl, dict):
        if "summary" in outl:
            n_outliers = outl["summary"].get("total_outliers", 0)
        else:
            n_outliers = sum(v.get("outliers_count", 0) if isinstance(v, dict) else 0
                            for v in outl.values())

    passport.append({
        "Вид проверки": "12. Выбросы (Outliers)",
        "Измерение DQ": "Accuracy",
        "Метрика": "n_outliers (IQR / Z-score)",
        "Алгоритм": "Q1-1.5×IQR, Q3+1.5×IQR + Z-score > 3",
        "Значение ДО": f"{n_outliers} выбросов",
        "Значение ПОСЛЕ": "—", "Δ": "—",
        "Влияние на TS": "Выбросы искажают mean/std, параметрические тесты",
        "Статус": "❌" if n_outliers > 0 else "✅"
    })

    # Итог: размер датасета
    if df_after is not None and len(df_after) > 0:
        passport.append({
            "Вид проверки": "Итог: размер датасета",
            "Измерение DQ": "—",
            "Метрика": "n_rows, n_cols",
            "Алгоритм": "df.shape",
            "Значение ДО": f"{n_total} × {len(df_before.columns)}",
            "Значение ПОСЛЕ": f"{len(df_after)} × {len(df_after.columns)}",
            "Δ": f"{len(df_after) - n_total:+} строк",
            "Влияние на TS": "—",
            "Статус": "ℹ️"
        })

    # COMPOSITE DQ SCORE
    checks_total = len(passport)
    checks_passed = len([p for p in passport if p["Статус"] == "✅"])
    dq_score = (checks_passed / checks_total * 100) if checks_total > 0 else 0

    passport.append({
        "Вид проверки": "COMPOSITE DQ SCORE",
        "Измерение DQ": "Aggregate",
        "Метрика": "DQ Score = passed/total × 100",
        "Алгоритм": "Взвешенная сумма по 6 измерениям DAMA",
        "Значение ДО": f"{checks_passed}/{checks_total} проверок пройдено",
        "Значение ПОСЛЕ": f"{dq_score:.1f}%",
        "Δ": "—",
        "Влияние на TS": f"При DQ≥80% — все модели; <50% — только базовые",
        "Статус": "✅" if dq_score >= 80 else ("⚠️" if dq_score >= 50 else "❌")
    })

    df_passport = pd.DataFrame(passport)

    metadata = {
        "document_title": "ПАСПОРТ ВАЛИДАЦИИ ВРЕМЕННОГО РЯДА",
        "dataset_name": dataset_name,
        "n_rows": n_total,
        "n_cols": len(df_before.columns),
        "platform": "CISStat TS Analysis",
        "platform_tagline": "Сгенерировано и валидировано платформой CISStat TS Analysis",
        "verification": "Верифицировано Статкомитетом СНГ",
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "dq_score": dq_score,
        "checks_passed": checks_passed,
        "checks_total": checks_total
    }

    return df_passport, dq_score, metadata


def get_model_recommendations(dq_score, val_results):
    """Формирует структурированные рекомендации по применимости моделей."""
    sufficiency = val_results.get("sufficiency", [])
    regularity = val_results.get("regularity", [])
    n_gaps = sum(r.get("Пропусков", r.get("Всего пропусков", 0)) for r in regularity)
    n_insufficient = len([r for r in sufficiency if r.get("Нарушений", 0) > 0])

    if dq_score >= 80 and n_gaps == 0 and n_insufficient == 0:
        tier = "high"
    elif dq_score >= 50:
        tier = "medium"
    else:
        tier = "low"

    models = {
        "high": {
            "available": [
                "ARIMA / SARIMA",
                "Exponential Smoothing (ETS, Holt-Winters)",
                "Prophet (Facebook)",
                "VAR / VECM (для многомерных рядов)",
                "FFT / Спектральный анализ",
                "XGBoost / LightGBM (с лагами)",
                "LSTM (нейросеть)",
                "N-BEATS, Temporal Fusion Transformer"
            ],
            "limited": [],
            "unavailable": []
        },
        "medium": {
            "available": [
                "ARIMA (с осторожностью)",
                "Exponential Smoothing (ETS)",
                "Holt-Winters (при наличии ≥2 сезонов)",
                "Линейный тренд + сезонная декомпозиция"
            ],
            "limited": [
                "Prophet (требует ≥50 наблюдений)",
                "SARIMA (нужны полные сезоны)"
            ],
            "unavailable": [
                "LSTM (недостаточно данных для обучения)",
                "N-BEATS, Transformer-модели",
                "FFT (требует ≥64 точки)"
            ]
        },
        "low": {
            "available": [
                "Скользящее среднее (Moving Average)",
                "Наивный прогноз (Last Value)",
                "Линейная регрессия по тренду"
            ],
            "limited": [
                "ARIMA (высокий риск переобучения)",
                "Holt-Winters (нестабильные оценки)"
            ],
            "unavailable": [
                "SARIMA, Prophet, LSTM, XGBoost",
                "Спектральный анализ",
                "VAR/VECM"
            ]
        }
    }

    rec = models.get(tier, models["low"]).copy()

    if tier == "high":
        explanation = (
            f"DQ Score = {dq_score:.1f}% — данные высокого качества. "
            "Рекомендуется начать с SARIMA или Prophet, затем сравнить с LSTM/XGBoost."
        )
        primary = "SARIMA / Prophet"
    elif tier == "medium":
        explanation = (
            f"DQ Score = {dq_score:.1f}% — данные среднего качества. "
            f"Выявлено {n_gaps} пропусков и {n_insufficient} групп с недостаточным объёмом. "
            "Рекомендуется предобработка (интерполяция, агрегация), затем ARIMA или ETS."
        )
        primary = "ARIMA / Exponential Smoothing"
    else:
        explanation = (
            f"DQ Score = {dq_score:.1f}% — данные низкого качества. "
            "Моделирование возможно только базовыми методами после устранения критических нарушений."
        )
        primary = "Скользящее среднее / Наивный прогноз"

    rec["explanation"] = explanation
    rec["primary_recommendation"] = primary
    rec["tier"] = tier
    rec["dq_score"] = dq_score

    return rec
