# tests/unit/test_validation_regularity.py
import pytest
import pandas as pd
import numpy as np
from app.validation.regularity import compute_regularity_violations

def test_regularity_single_series_with_gap():
    """Тест для обычного ряда с пропуском (gap)."""
    dates = pd.date_range("2020-01-01", periods=10, freq="D")
    # Удаляем 2 дня, чтобы создать аномальный разрыв
    dates = dates.delete([3, 4]) 
    df = pd.DataFrame({"date": dates, "value": range(8)})
    
    result = compute_regularity_violations(df, date_col="date")
    
    assert result["gaps_count"] > 0, "Должен быть обнаружен хотя бы один gap"
    assert result["mask"].sum() > 0
    assert result["freq_info"].get("inferred_freq") == "B"
    assert "error" not in result

def test_regularity_panel_data_isolated_gap():
    """Тест для Panel Data: gap только в одной сущности (Country B)."""
    dates_a = pd.date_range("2020-01-01", periods=5, freq="D")
    dates_b = pd.date_range("2020-01-01", periods=5, freq="D").delete([2]) # gap in entity B
    
    df = pd.DataFrame({
        "country": ["A"]*5 + ["B"]*4,
        "date": list(dates_a) + list(dates_b),
        "value": range(9)
    })
    
    result = compute_regularity_violations(df, date_col="date", entity_col="country")
    
    # Должны быть найдены нарушения (gap в стране B)
    assert result["gaps_count"] > 0
    # Проверяем, что маска имеет ту же длину, что и исходный df
    assert len(result["mask"]) == len(df)
    
def test_regularity_graceful_degradation_on_bad_dates():
    """Тест Правила 16: функция не должна падать на мусорных датах."""
    df = pd.DataFrame({
        "date": ["2020-01-01", "not_a_date", "2020-01-03"],
        "value": [1, 2, 3]
    })
    
    result = compute_regularity_violations(df, date_col="date")
    
    # Функция должна отработать, возможно с ошибкой в словаре, но без Exception
    assert isinstance(result["mask"], pd.Series)