"""Безопасный preview/apply исправлений ссылочной целостности."""
from __future__ import annotations

from typing import Any

import pandas as pd

from validation.referential import profile_referential, referential_invalid_mask


STRATEGIES = {"mode", "replace_null", "drop_rows", "replace_default", "flag"}


def preview_referential_corrections(
    df: pd.DataFrame,
    rules: dict,
    rule_indices: list[int],
    strategy: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    """Применяет одну стратегию к глубокой копии по активным FK-правилам."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    if not rule_indices:
        raise ValueError("Не выбрано ни одного правила для исправления")
    if len(rule_indices) != len(set(rule_indices)):
        raise ValueError("Одно правило не может повторяться в операции")

    profiles = {item["rule_index"]: item for item in profile_referential(df, rules)}
    unknown = [index for index in rule_indices if index not in profiles]
    if unknown:
        raise ValueError(f"Правило ссылочной целостности {unknown[0] + 1} не найдено")
    non_applicable = [index for index in rule_indices if not profiles[index]["applicable"]]
    if non_applicable:
        item = profiles[non_applicable[0]]
        raise ValueError(
            f"Правило '{item['rule_name']}' неприменимо: {item['applicability_message']}"
        )

    selected_columns = [profiles[index]["child_column"] for index in rule_indices]
    if len(selected_columns) != len(set(selected_columns)):
        raise ValueError("Нельзя одновременно исправлять несколько связей одной дочерней колонки")

    result_df = df.copy(deep=True)
    masks = {
        index: referential_invalid_mask(
            result_df[profiles[index]["child_column"]], profiles[index]["allowed_values"]
        )
        for index in rule_indices
    }
    rows_removed = 0
    flag_columns: dict[int, str | None] = {index: None for index in rule_indices}
    replacement_values: dict[int, Any] = {index: None for index in rule_indices}

    if strategy == "drop_rows":
        combined_mask = pd.Series(False, index=result_df.index)
        for mask in masks.values():
            combined_mask |= mask
        rows_removed = int(combined_mask.sum())
        result_df = result_df.loc[~combined_mask].reset_index(drop=True)
    else:
        for index in rule_indices:
            item = profiles[index]
            column = item["child_column"]
            mask = masks[index]
            invalid_count = int(mask.sum())
            if strategy == "mode":
                valid_values = result_df.loc[
                    result_df[column].notna()
                    & result_df[column].isin(item["allowed_values"]),
                    column,
                ]
                if invalid_count and valid_values.empty:
                    raise ValueError(
                        f"Для колонки '{column}' нет допустимых значений для расчёта моды"
                    )
                if invalid_count:
                    replacement = valid_values.value_counts().index[0]
                    result_df.loc[mask, column] = replacement
                    replacement_values[index] = replacement
            elif strategy == "replace_null":
                result_df.loc[mask, column] = pd.NA
            elif strategy == "replace_default":
                if not item["default_valid"]:
                    raise ValueError(
                        f"Для правила '{item['rule_name']}' значение по умолчанию отсутствует или не входит в справочник"
                    )
                result_df.loc[mask, column] = item["default_value"]
                replacement_values[index] = item["default_value"]
            else:
                flag_column = f"{column}_ref_valid"
                if flag_column in result_df.columns:
                    raise ValueError(f"Колонка '{flag_column}' уже существует")
                result_df[flag_column] = ~mask
                flag_columns[index] = flag_column

    results: list[dict[str, Any]] = []
    for index in rule_indices:
        source = profiles[index]
        column = source["child_column"]
        invalid_count = int(masks[index].sum())
        still_invalid = (
            invalid_count
            if strategy == "flag"
            else int(referential_invalid_mask(
                result_df[column], source["allowed_values"]
            ).sum())
        )
        results.append({
            "rule_index": index,
            "rule_name": source["rule_name"],
            "child_column": column,
            "invalid_count": invalid_count,
            "changed_count": 0 if strategy == "flag" else invalid_count,
            "still_invalid": still_invalid,
            "replacement_value": replacement_values[index],
            "flag_column": flag_columns[index],
        })

    return result_df, results, rows_removed
