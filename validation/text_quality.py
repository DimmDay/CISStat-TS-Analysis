"""Единая бизнес-логика проверки и исправления качества текста.

Функции этого модуля не зависят от Streamlit/FastAPI и используются
общей валидацией, обзором остановки и preview/apply мастером исправления.
"""
from __future__ import annotations

from typing import Any

import pandas as pd


DEFAULT_MIN_LENGTH = 1
DEFAULT_MAX_LENGTH = 500
DEFAULT_GARBAGE_CHARS = ("\ufffd", "\ufeff", "ï¿½")
SUPPORTED_ACTIONS = ("normalize", "replace_null", "drop_rows", "replace_unknown", "flag")
CONTROL_PATTERN = r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"


def _config(rules: dict[str, Any] | None) -> dict[str, Any]:
    raw = (rules or {}).get("text_quality", {})
    return raw if isinstance(raw, dict) else {}


def _decode_garbage_token(value: Any) -> str:
    token = str(value)
    if not token:
        return ""
    if token.startswith("\\x") and len(token) == 4:
        try:
            return chr(int(token[2:], 16))
        except ValueError:
            return token
    if token.startswith("\\u") and len(token) == 6:
        try:
            return chr(int(token[2:], 16))
        except ValueError:
            return token
    return token


def _garbage_tokens(config: dict[str, Any]) -> list[str]:
    configured = config.get("garbage_chars", [])
    values = configured if isinstance(configured, list) else []
    # Пустая строка принципиально исключается: Series.str.contains("")
    # истинно для каждого значения и ранее давала 100% ложных нарушений.
    return list(dict.fromkeys(
        token
        for token in (*DEFAULT_GARBAGE_CHARS, *(_decode_garbage_token(v) for v in values))
        if token
    ))


def text_quality_masks(
    series: pd.Series,
    rules: dict[str, Any] | None = None,
    *,
    column: str | None = None,
) -> dict[str, pd.Series]:
    """Возвращает маски отдельных причин и объединённую маску строк.

    Пропуски не являются нарушением целостности текста: их обрабатывает
    отдельная проверка полноты. Все остальные маски считаются только по
    непустым исходным значениям и имеют индекс исходной Series.
    """
    config = _config(rules)
    min_length = int(config.get("min_length", DEFAULT_MIN_LENGTH))
    max_length = int(config.get("max_length", DEFAULT_MAX_LENGTH))
    present = series.notna()
    text = series.astype("string")
    stripped = text.str.strip()
    stripped_lengths = stripped.str.len()
    raw_lengths = text.str.len()

    garbage = pd.Series(False, index=series.index, dtype=bool)
    garbage |= present & text.str.contains(CONTROL_PATTERN, na=False, regex=True)
    for token in _garbage_tokens(config):
        garbage |= present & text.str.contains(token, na=False, regex=False)

    empty = present & stripped.eq("").fillna(False)
    too_short = present & stripped_lengths.lt(min_length).fillna(False)
    too_long = present & raw_lengths.gt(max_length).fillna(False)
    whitespace = present & (
        text.ne(stripped).fillna(False)
        | text.str.contains(r"\s{2,}", na=False, regex=True)
    )

    pattern = pd.Series(False, index=series.index, dtype=bool)
    allowed_patterns = config.get("allowed_patterns", {})
    expected_pattern = (
        allowed_patterns.get(column)
        if isinstance(allowed_patterns, dict) and column is not None
        else None
    )
    if expected_pattern:
        pattern = present & ~text.str.fullmatch(str(expected_pattern), na=False)

    combined = garbage | empty | too_short | too_long | whitespace | pattern
    return {
        "garbage": garbage.astype(bool),
        "empty": empty.astype(bool),
        "too_short": too_short.astype(bool),
        "too_long": too_long.astype(bool),
        "whitespace": whitespace.astype(bool),
        "pattern": pattern.astype(bool),
        "combined": combined.astype(bool),
    }


def profile_text_quality(df: pd.DataFrame, rules: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Строит полный профиль всех текстовых колонок, включая чистые."""
    config = _config(rules)
    min_length = int(config.get("min_length", DEFAULT_MIN_LENGTH))
    max_length = int(config.get("max_length", DEFAULT_MAX_LENGTH))
    text_columns = df.select_dtypes(include=["object", "string"]).columns.tolist()
    profile: list[dict[str, Any]] = []

    for column in text_columns:
        masks = text_quality_masks(df[column], rules, column=column)
        present = df[column].notna()
        invalid_count = int(masks["combined"].sum())
        total_count = int(present.sum())
        examples = (
            df.loc[masks["combined"], column]
            .astype(str)
            .drop_duplicates()
            .head(5)
            .tolist()
        )
        profile.append({
            "column": str(column),
            "total_count": total_count,
            "valid_count": total_count - invalid_count,
            "invalid_count": invalid_count,
            "invalid_pct": round(invalid_count / total_count * 100, 2) if total_count else None,
            "min_length": min_length,
            "max_length": max_length,
            "issue_counts": {
                name: int(masks[name].sum())
                for name in ("garbage", "empty", "too_short", "too_long", "whitespace", "pattern")
            },
            "invalid_examples": examples,
            "supported_actions": list(SUPPORTED_ACTIONS),
        })
    return profile


def compute_text_violations(df_to_check: pd.DataFrame) -> list[dict[str, Any]]:
    """Backward-compatible контракт Streamlit поверх единого профиля."""
    violations: list[dict[str, Any]] = []
    for item in profile_text_quality(df_to_check):
        if not item["invalid_count"]:
            continue
        column = item["column"]
        masks = text_quality_masks(df_to_check[column], column=column)
        violations.append({
            "column": column,
            "count": item["invalid_count"],
            "mask": masks["combined"],
            "garbage_count": item["issue_counts"]["garbage"],
            "short_count": item["issue_counts"]["empty"],
            "long_count": item["issue_counts"]["too_long"],
            "sample_values": df_to_check.loc[masks["combined"], column].head(3).tolist(),
        })
    return violations


def _normalize_values(series: pd.Series) -> pd.Series:
    """Legacy-стратегия Streamlit: strip/lower/очистка/сжатие пробелов."""
    result = (
        series.astype("string")
        .str.replace(CONTROL_PATTERN, "", regex=True)
        .str.replace("\ufffd", "", regex=False)
        .str.replace("\ufeff", "", regex=False)
        .str.replace("ï¿½", "", regex=False)
        .str.strip()
        .str.lower()
        .str.replace(r"[^\w\s\-]", "", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    return result.mask(result.eq(""), pd.NA)


def apply_text_strategy(
    df_input: pd.DataFrame,
    text_violations: list[dict[str, Any]],
    strategy: str,
) -> pd.DataFrame:
    """Backward-compatible применение пяти стратегий Streamlit к копии."""
    result = df_input.copy(deep=True)
    if "Удалить" in strategy:
        combined = pd.Series(False, index=result.index, dtype=bool)
        for violation in text_violations:
            combined |= violation["mask"].reindex(result.index, fill_value=False)
        return result.loc[~combined].reset_index(drop=True)

    for violation in text_violations:
        column = violation["column"]
        if column not in result.columns:
            continue
        mask = violation["mask"].reindex(result.index, fill_value=False)
        if "Очистить" in strategy:
            result.loc[mask, column] = _normalize_values(result.loc[mask, column])
        elif "NaN" in strategy:
            result.loc[mask, column] = pd.NA
        elif "Неизвестно" in strategy:
            result.loc[mask, column] = "Неизвестно"
        elif "флагом" in strategy:
            result[f"{column}_text_valid"] = ~mask
    return result
