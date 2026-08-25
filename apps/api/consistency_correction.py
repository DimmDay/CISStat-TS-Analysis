"""Транзакционный preview/apply для логики и хронологии."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from validation.engine import evaluate_consistency_rules


STRATEGIES = {"sort_chronology", "drop_rows", "replace_null", "flag"}


def _flag_name(rule_name: str, rule_index: int) -> str:
    slug = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "_", rule_name).strip("_").lower()
    return f"{slug or f'rule_{rule_index + 1}'}_consistency_valid"


def _group_aware_order(
    df: pd.DataFrame,
    *,
    time_column: str,
    group_column: str | None,
) -> list[Any]:
    if group_column:
        order: list[Any] = []
        for _, group in df.groupby(group_column, sort=False, dropna=False):
            order.extend(group.sort_values(time_column, kind="stable", na_position="last").index.tolist())
        return order
    return df.sort_values(time_column, kind="stable", na_position="last").index.tolist()


def preview_consistency_corrections(
    df: pd.DataFrame,
    rules: dict,
    rule_indices: list[int],
    strategy: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    """Выполняет стратегию на глубокой копии; исходный DataFrame не меняется."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    if not rule_indices:
        raise ValueError("Не выбрано ни одного правила для исправления")
    if len(rule_indices) != len(set(rule_indices)):
        raise ValueError("Одно правило не может повторяться в операции")

    evaluations = {item["rule_index"]: item for item in evaluate_consistency_rules(df, rules)}
    missing = [index for index in rule_indices if index not in evaluations]
    if missing:
        raise ValueError(f"Правило с индексом {missing[0]} отсутствует")
    selected = [evaluations[index] for index in rule_indices]
    not_applicable = [item for item in selected if not item["applicable"]]
    if not_applicable:
        raise ValueError(
            f"Правило '{not_applicable[0]['rule_name']}' неприменимо: "
            f"{not_applicable[0]['applicability_message']}"
        )
    if strategy == "sort_chronology" and any(
        item["rule_type"] != "chronology" for item in selected
    ):
        raise ValueError("Сортировка применима только к правилам хронологии")

    result_df = df.copy(deep=True)
    rows_removed = 0
    changed_by_rule: dict[int, int] = {index: 0 for index in rule_indices}
    flags_by_rule: dict[int, str | None] = {index: None for index in rule_indices}

    if strategy == "drop_rows":
        combined = pd.Series(False, index=result_df.index)
        for item in selected:
            combined |= item["mask"]
            changed_by_rule[item["rule_index"]] = item["affected_rows"]
        rows_removed = int(combined.sum())
        result_df = result_df.loc[~combined].reset_index(drop=True)
    elif strategy == "sort_chronology":
        for item in selected:
            order = _group_aware_order(
                result_df,
                time_column=item["time_column"],
                group_column=item["group_column"],
            )
            previous_positions = {index: position for position, index in enumerate(result_df.index)}
            changed_by_rule[item["rule_index"]] = sum(
                previous_positions.get(index) != position for position, index in enumerate(order)
            )
            result_df = result_df.loc[order]
        result_df = result_df.reset_index(drop=True)
    elif strategy == "replace_null":
        for item in selected:
            changed = 0
            for column in item["correction_columns"]:
                mask = item["mask"]
                changed += int((mask & result_df[column].notna()).sum())
                result_df.loc[mask, column] = pd.NA
            changed_by_rule[item["rule_index"]] = changed
    else:
        for item in selected:
            flag_column = _flag_name(item["rule_name"], item["rule_index"])
            if flag_column in result_df.columns:
                raise ValueError(f"Колонка '{flag_column}' уже существует")
            result_df[flag_column] = ~item["mask"]
            flags_by_rule[item["rule_index"]] = flag_column

    next_evaluations = {
        item["rule_index"]: item for item in evaluate_consistency_rules(result_df, rules)
    }
    results = []
    for item in selected:
        next_item = next_evaluations.get(item["rule_index"])
        still_invalid = (
            int(item["invalid_count"] or 0)
            if strategy == "flag"
            else int(next_item["invalid_count"] or 0) if next_item and next_item["applicable"] else 0
        )
        results.append({
            "rule_index": item["rule_index"],
            "rule_name": item["rule_name"],
            "invalid_count": int(item["invalid_count"] or 0),
            "affected_rows": item["affected_rows"],
            "changed_count": changed_by_rule[item["rule_index"]],
            "still_invalid": still_invalid,
            "flag_column": flags_by_rule[item["rule_index"]],
        })

    return result_df, results, rows_removed
