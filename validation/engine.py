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

from validation.uniqueness import check_uniqueness
from validation.inclusion import check_inclusion

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


def _run_all_checks(df: pd.DataFrame, rules: dict, schema_errors: dict) -> dict:
    """Запускает все 9 sub-check функций + агрегирует pandera schema_errors
    (data_types) в единый словарь {check_id: {status, count, items}},
    ключи check_id -- те же 10 id, что в CHECKS (TsAnalysisValidation.tsx):
    data_types, formats, ranges, consistency, uniqueness, inclusion,
    referential, text_quality, regularity, sufficiency.

    status: "done" (0 нарушений) | "warning" (>0 нарушений) |
            "pending" (проверка неприменима -- нет данных для неё:
            например referential без справочника или нет date-колонки).
    items: [{label, count}] -- для графика детализации на фронте
    (BacktestComparisonChart -- прецедент того же паттерна в Моделировании).

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
            checks[check_id] = {"status": "pending", "count": None, "items": [], "error": str(ex)}

    # ── data_types (pandera-схема, уже посчитана выше в validate_dataframe) ──
    def _data_types():
        count = sum(schema_errors.values()) if schema_errors else 0
        items = [{"label": str(k), "count": int(v)} for k, v in schema_errors.items()]
        return {"status": _status(count), "count": count, "items": items}
    _safe("data_types", _data_types)

    # ── formats ──
    def _formats():
        raw = validate_formats(df, rules)
        items = [{"label": r["Колонка"], "count": r["Нарушений"]} for r in raw if r["Нарушений"] > 0]
        count = sum(i["count"] for i in items) if raw else None
        return {"status": _status(count), "count": count, "items": items}
    _safe("formats", _formats)

    # ── ranges ──
    def _ranges():
        raw, _masks, _bounds = validate_ranges(df, rules)
        items = [{"label": r["Колонка"], "count": r["Нарушений"]} for r in raw]
        count = sum(i["count"] for i in items)
        return {"status": _status(count), "count": count, "items": items}
    _safe("ranges", _ranges)

    # ── consistency ──
    def _consistency():
        raw = validate_consistency(df, rules)
        items = [{"label": r["Правило"], "count": r.get("Нарушений", 0)} for r in raw if "Нарушений" in r]
        count = sum(i["count"] for i in items) if items else None
        return {"status": _status(count), "count": count, "items": items}
    _safe("consistency", _consistency)

    # ── uniqueness ──
    def _uniqueness():
        date_col = None
        for c in df.columns:
            if any(kw in c.lower() for kw in ["date", "дата", "year", "год"]):
                date_col = c
                break
        raw = check_uniqueness(df, date_col=date_col)
        count = raw["duplicate_count"]
        items = [{"label": "Дублирующиеся строки", "count": count}] if count > 0 else []
        return {"status": _status(count), "count": count, "items": items}
    _safe("uniqueness", _uniqueness)

    # ── inclusion ──
    def _inclusion():
        inclusion_rules = rules.get("inclusion", {})
        if not inclusion_rules:
            return {"status": "pending", "count": None, "items": []}
        raw, _masks = check_inclusion(df, inclusion_rules)
        items = [{"label": r["Колонка"], "count": r["Нарушений"]} for r in raw]
        count = sum(i["count"] for i in items)
        return {"status": _status(count), "count": count, "items": items}
    _safe("inclusion", _inclusion)

    # ── referential (auto_generate_rules НЕ умеет генерировать FK-справочники
    # -- без явного шаблона правил всегда "pending", это ЧЕСТНО отражает
    # реальность: у нас нет родительской таблицы для сверки) ──
    def _referential():
        ref_rules = rules.get("referential", [])
        if not ref_rules:
            return {"status": "pending", "count": None, "items": []}
        raw, _masks = validate_referential(df, rules)
        items = [{"label": r["Колонка"], "count": r["Нарушений"]} for r in raw]
        count = sum(i["count"] for i in items)
        return {"status": _status(count), "count": count, "items": items}
    _safe("referential", _referential)

    # ── text_quality ──
    def _text_quality():
        raw, _masks = validate_text_quality(df, rules)
        items = [{"label": r["Колонка"], "count": r["Нарушений"]} for r in raw]
        count = sum(i["count"] for i in items)
        return {"status": _status(count), "count": count, "items": items}
    _safe("text_quality", _text_quality)

    # ── regularity ──
    def _regularity():
        raw, _masks, _freq_info, sort_info = validate_regular_step(df, rules)
        if sort_info.get("date_col") is None:
            return {"status": "pending", "count": None, "items": []}
        if not sort_info.get("is_sorted", True):
            n = sort_info.get("sort_violations", 0)
            return {
                "status": _status(n),
                "count": n,
                "items": [{"label": "Нарушение хронологии", "count": n}],
            }
        items = [{"label": r.get("Группа", "?"), "count": r.get("Пропусков", 0)} for r in raw]
        count = sum(i["count"] for i in items)
        return {"status": _status(count), "count": count, "items": items}
    _safe("regularity", _regularity)

    # ── sufficiency ──
    def _sufficiency():
        raw, _recs = validate_sufficiency(df, rules)
        if raw and raw[0].get("Тип") == "Нет временной колонки":
            return {"status": "pending", "count": None, "items": []}
        items = [{"label": r.get("Группа", "?"), "count": r.get("Нарушений", 0)} for r in raw]
        count = sum(i["count"] for i in items)
        return {"status": _status(count), "count": count, "items": items}
    _safe("sufficiency", _sufficiency)

    return checks


def validate_dataframe(df: pd.DataFrame, rules: dict) -> dict:
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
    result["checks"] = _run_all_checks(df, rules, result["schema_errors"])

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


def validate_formats(df, rules):
    """Проверяет колонки датафрейма на соответствие регулярным выражениям."""
    results = []
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

        if col_name in df.columns:
            non_null_data = df[col_name].dropna()
            if len(non_null_data) == 0:
                continue

            matches = non_null_data.astype(str).str.fullmatch(pattern)
            valid_count = matches.sum()
            total_count = len(non_null_data)
            match_pct = (valid_count / total_count) * 100 if total_count > 0 else 0
            invalid_count = int(total_count - valid_count)

            if match_pct >= threshold:
                status = "✅ Норма"
            else:
                status = "⚠️ Отклонение"

            results.append({
                "Колонка": col_name,
                "Шаблон": pattern[:30] + "..." if len(pattern) > 30 else pattern,
                "Всего записей": total_count,
                "Нарушений": invalid_count,
                "% match": f"{match_pct:.1f}%",
                "Статус": status
            })

    return results


def validate_consistency(df, rules):
    """
    Проверяет согласованность данных (хронология внутри групп).
    
    🔧 ИСПРАВЛЕНИЕ: Показывает ОБЕ строки нарушения (2016 и 2015),
    а не только ту, где diff() < 0.
    """
    results = []
    consistency_rules = rules.get("consistency", [])

    # Автогенерация правила, если пусто
    if not consistency_rules:
        year_cols = [c for c in df.columns if 'year' in c.lower() or 'год' in c.lower()]
        date_cols = df.select_dtypes(include=['datetime64']).columns.tolist()
        if year_cols:
            consistency_rules.append({
                "name": "Хронологический порядок лет",
                "type": "chronology",
                "description": "Проверка хронологического порядка лет внутри групп",
                "columns": [year_cols[0]],
                "severity": "error"
            })
        elif date_cols:
            consistency_rules.append({
                "name": "Хронологический порядок дат",
                "type": "chronology",
                "description": "Проверка хронологического порядка дат внутри групп",
                "columns": [date_cols[0]],
                "severity": "error"
            })

    for rule in consistency_rules:
        try:
            rule_type = rule.get("type", "unknown")
            rule_name = rule.get("name", "Unnamed")
            columns = rule.get("columns", [])
            violations = 0
            violation_mask = pd.Series(False, index=df.index)

            if rule_type == "chronology" and columns and columns[0] in df.columns:
                time_col = columns[0]
                
                # Ищем группирующую колонку
                group_col = None
                for c in df.columns:
                    if c != time_col and df[c].dtype in ['object', 'string', 'category']:
                        n_unique = df[c].nunique()
                        if 1 < n_unique < min(100, len(df) * 0.5):
                            group_col = c
                            break

                if group_col:
                    # Панельные данные: проверяем внутри каждой группы
                    for group_name, group_df in df.groupby(group_col):
                        group_sorted = group_df.sort_index()
                        time_values = group_sorted[time_col]
                        
                        # Находим нарушения: где текущий год < предыдущего
                        time_diff = time_values.diff()
                        if pd.api.types.is_datetime64_any_dtype(time_values):
                            group_violations_mask = time_diff < pd.Timedelta(seconds=0)
                        else:
                            group_violations_mask = time_diff < 0
                        
                        violations += group_violations_mask.sum()
                        
                        # 🔧 ИСПРАВЛЕНИЕ: Показываем ОБЕ строки нарушения
                        # Строка где diff() < 0 (2015)
                        violation_mask.loc[group_sorted[group_violations_mask].index] = True
                        
                        # И предыдущая строка (2016) — тоже нарушение!
                        violation_indices = group_sorted[group_violations_mask].index
                        for idx in violation_indices:
                            prev_idx = group_sorted.index[group_sorted.index.get_loc(idx) - 1]
                            violation_mask.loc[prev_idx] = True
                else:
                    # Обычный ряд
                    time_diff = df[time_col].diff()
                    if pd.api.types.is_datetime64_any_dtype(df[time_col]):
                        violation_mask = time_diff < pd.Timedelta(seconds=0)
                    else:
                        violation_mask = time_diff < 0
                    
                    # Добавляем предыдущие строки
                    violation_indices = df[violation_mask].index
                    for idx in violation_indices:
                        loc = df.index.get_loc(idx)
                        if loc > 0:
                            prev_idx = df.index[loc - 1]
                            violation_mask.loc[prev_idx] = True
                    
                    violations = violation_mask.sum() // 2  # Делим на 2, т.к. каждая пара считается дважды

            results.append({
                "Правило": rule_name,
                "Тип": rule_type,
                "Нарушений": int(violations),
                "Статус": "⚠️ Нарушено" if violations > 0 else "✅ Соблюдено",
                "mask": violation_mask
            })
        except Exception as e:
            results.append({
                "Правило": rule.get("name", "unknown"),
                "Статус": f"❌ Ошибка: {e}",
                "mask": pd.Series(False, index=df.index)
            })

    return results


def validate_ranges(df, rules):
    """Проверяет числовые колонки на соответствие допустимым диапазонам."""
    results = []
    violation_masks = {}
    rule_bounds = {}
    range_rules = rules.get("ranges", [])
    num_cols = df.select_dtypes(include=['number']).columns.tolist()

    for col in num_cols:
        col_lower = col.lower()
        matched_rule = None

        for rule in range_rules:
            keywords = rule.get("keywords", [])
            if any(kw in col_lower for kw in keywords):
                matched_rule = rule
                break

        if matched_rule:
            min_val = matched_rule.get("min")
            max_val = matched_rule.get("max")
            rule_bounds[col] = (min_val, max_val)

            mask = pd.Series(False, index=df.index)
            if min_val is not None:
                mask |= (df[col] < min_val)
            if max_val is not None:
                mask |= (df[col] > max_val)

            if mask.any():
                violation_masks[col] = mask
                violations = mask.sum()
                results.append({
                    "Колонка": col,
                    "Правило": f"{min_val if min_val is not None else '-∞'} < x < {max_val if max_val is not None else '∞'}",
                    "Нарушений": int(violations),
                    "% брака": f"{(violations / len(df) * 100):.2f}%",
                    "Min факт": df[col].min(),
                    "Max факт": df[col].max()
                })

    return results, violation_masks, rule_bounds


def auto_generate_rules(df: pd.DataFrame) -> dict:
    """Автоматически генерирует базовые правила валидации."""
    rules = {
        "ranges": [],
        "inclusion": {},
        "consistency": [],
        "formats": {}
    }

    if df.empty:
        return rules

    for col in df.select_dtypes(include='number').columns:
        col_lower = col.lower()
        min_val = float(df[col].min()) if pd.notna(df[col].min()) else 0
        max_val = float(df[col].max()) if pd.notna(df[col].max()) else 1000

        if any(kw in col_lower for kw in ['price', 'цена', 'стоимость']):
            rules["ranges"].append({
                "name": f"{col} — положительная цена",
                "keywords": [col],
                "min": 0,
                "max": max_val * 3
            })
        elif any(kw in col_lower for kw in ['year', 'год']):
            rules["ranges"].append({
                "name": f"{col} — разумный год",
                "keywords": [col],
                "min": 1900,
                "max": 2100
            })
        elif any(kw in col_lower for kw in ['percent', '%', 'доля']):
            rules["ranges"].append({
                "name": f"{col} — процент (0-100)",
                "keywords": [col],
                "min": 0,
                "max": 100
            })
        else:
            rules["ranges"].append({
                "name": f"{col} — авто-диапазон",
                "keywords": [col],
                "min": min_val - abs(min_val) * 0.1 if min_val < 0 else 0,
                "max": max_val * 1.5
            })

    for col in df.select_dtypes(include=['object', 'string']).columns:
        if 1 < df[col].nunique() < 50:
            rules["inclusion"][col] = df[col].dropna().unique().tolist()

    date_cols = [c for c in df.columns if 'year' in c.lower() or 'date' in c.lower() or 'дата' in c.lower()]
    if date_cols:
        rules["consistency"].append({
            "name": "Хронологический порядок",
            "type": "chronology",
            "description": "Проверка возрастания времени",
            "columns": [date_cols[0]]
        })

    return rules


def validate_referential(df, rules):
    """Проверяет ссылочную целостность."""
    results = []
    violation_masks = {}
    ref_rules = rules.get("referential", [])

    for rule in ref_rules:
        child_col = rule.get("child_column")
        parent_values = rule.get("allowed_values", [])
        default_val = rule.get("default_value", "Unknown")
        rule_name = rule.get("name", "Unnamed")

        if child_col and child_col in df.columns and parent_values:
            mask = ~df[child_col].isin(parent_values) & df[child_col].notna()
            violations = mask.sum()

            if violations > 0:
                violation_masks[rule_name] = mask
                results.append({
                    "Правило": rule_name,
                    "Колонка": child_col,
                    "Нарушений": int(violations),
                    "% брака": f"{(violations / len(df)) * 100:.2f}%",
                    "allowed_values": parent_values,
                    "default_value": default_val,
                    "Статус": "⚠️ Нарушено"
                })

    return results, violation_masks


def validate_text_quality(df, rules):
    """Проверяет качество текстовых колонок."""
    results = []
    violation_masks = {}
    text_rules = rules.get("text_quality", [])
    text_cols = df.select_dtypes(include=['object', 'string']).columns.tolist()

    for col in text_cols:
        violations = 0
        violation_types = []
        mask = pd.Series(False, index=df.index)

        try:
            garbage_mask = df[col].astype(str).str.contains(
                r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]',
                na=False,
                regex=True
            )
        except Exception:
            garbage_mask = pd.Series(False, index=df.index)

        # БАГ (найден 2026-08-14 при первом реальном подключении этой
        # функции к API -- до этого validate_text_quality нигде не
        # вызывалась продакшен-кодом кроме app.py, поэтому не проявлялась):
        # unicode_artifacts содержал '' (пустую строку) первым элементом.
        # str.contains('', regex=False) истинно для ЛЮБОЙ строки (пустая
        # подстрока входит в любую строку) -- каждая текстовая колонка
        # целиком помечалась как "мусор". Реальные мусорные маркеры --
        # только replacement character/BOM/mojibake-последовательность.
        unicode_artifacts = ['\ufffd', '\ufeff', 'ï¿½']
        for artifact in unicode_artifacts:
            try:
                garbage_mask |= df[col].astype(str).str.contains(artifact, na=False, regex=False)
            except Exception:
                pass

        garbage_count = garbage_mask.sum()
        if garbage_count > 0:
            violations += garbage_count
            mask |= garbage_mask
            violation_types.append(f"мусор: {garbage_count}")

        short_mask = df[col].astype(str).str.strip() == ''
        short_count = short_mask.sum()
        if short_count > 0:
            violations += short_count
            mask |= short_mask
            violation_types.append(f"пустые: {short_count}")

        long_mask = df[col].astype(str).str.len() > 500
        long_count = long_mask.sum()
        if long_count > 0:
            violations += long_count
            mask |= long_mask
            violation_types.append(f"длинные: {long_count}")

        if violations > 0:
            violation_masks[col] = mask
            results.append({
                "Колонка": col,
                "Тип": ", ".join(violation_types),
                "Нарушений": int(violations),
                "% брака": f"{(violations / len(df)) * 100:.2f}%",
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