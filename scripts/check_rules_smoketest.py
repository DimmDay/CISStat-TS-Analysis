"""Локальная проверка для CI-правил test_rules.yml.

Воспроизводит ровно тот one-liner, что запускается в .github/workflows/test_rules.yml,
но с корректным путём к файлу.
"""
import sys
from pathlib import Path

# Запуск из корня репозитория
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from validation.engine import load_rules, validate_dataframe
import pandas as pd

CSV_PATH = ROOT / "tests" / "fixtures" / "sample_bad_data.csv"
print(f"Loading CSV from: {CSV_PATH} (exists={CSV_PATH.exists()})")

df = pd.read_csv(CSV_PATH)
print(f"Loaded {len(df)} rows, columns: {list(df.columns)}")

rules = load_rules()
print(f"Loaded {len(rules)} rule sections")

res = validate_dataframe(df, rules)
print(f"is_valid = {res['is_valid']}")
print(f"errors   = {len(res['errors'])}")
print(f"warnings = {len(res['warnings'])}")
print(f"schema   = {res['schema_errors']}")
if res["errors"]:
    print("\nFirst 5 errors:")
    for e in res["errors"][:5]:
        print(f"  - {e}")

assert not res["is_valid"], "Ожидалось, что датасет НЕ валиден (is_valid=False)"
print("\nOK: assert not res['is_valid'] выполнен")
