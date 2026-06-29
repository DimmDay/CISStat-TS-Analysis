# tests/unit/test_validation_text.py
import pytest
import pandas as pd
from validation.text_quality import compute_text_violations, apply_text_strategy

# --- Тесты для compute_text_violations ---
def test_compute_text_violations_basic():
    # TODO: Заполнить на основе legacy-логики (строки ~7299-7485)
    df = pd.DataFrame({"text_col": ["Normal text", "Bad@Text!", "", None, "12345"]})
    # rules = {...} # Какие правила проверяются? (длина, спецсимволы, regex?)
    # violations = compute_text_violations(df, "text_col", rules)
    # assert violations == expected_legacy_result
    pass

# --- Тесты для apply_text_strategy ---
def test_apply_text_strategy_lowercase():
    # TODO: Заполнить на основе legacy-логики (строки ~7486-7557)
    df = pd.DataFrame({"text_col": ["TEXT", "Text", "text"]})
    # strategy = "lower"
    # cleaned_df = apply_text_strategy(df, "text_col", strategy)
    # assert cleaned_df["text_col"].tolist() == ["text", "text", "text"]
    pass