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


# tests/unit/test_validation_regularity.py (дополнение)

from app.validation.regularity import apply_regularity_strategy

def test_apply_regularity_interpolate_single_series():
    """Тест стратегии Interpolate для обычного ряда."""
    # Убираем np.nan на 04, чтобы интерполяция шла строго между 02 и 04
    dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-04", "2020-01-05"])
    df = pd.DataFrame({"date": dates, "value": [1.0, 2.0, 4.0, 5.0]})
    
    # Пропуск 3-го числа. Interpolate должен заполнить его средним между 02 (2.0) и 04 (4.0)
    result = apply_regularity_strategy(df, strategy="Interpolate", freq="D", date_col="date")
    
    assert len(result) == 5  # Добавился один день (2020-01-03)
    # Линейная интерполяция между 2.0 и 4.0 на 03 даст ровно 3.0
    assert result.loc[result["date"] == pd.to_datetime("2020-01-03"), "value"].values[0] == 3.0

def test_apply_regularity_fictitious_panel_data():
    """Тест стратегии 'фиктивные' для Panel Data."""
    dates_a = pd.to_datetime(["2020-01-01", "2020-01-03"])
    dates_b = pd.to_datetime(["2020-01-02", "2020-01-03"])
    
    df = pd.DataFrame({
        "country": ["A", "A", "B", "B"],
        "date": list(dates_a) + list(dates_b),
        "value": [10, 30, 20, 30],
        "cat_col": ["X", "X", "Y", "Y"]
    })
    
    result = apply_regularity_strategy(
        df, strategy="фиктивные", freq="D", date_col="date", entity_col="country"
    )
    
    # Функция строит диапазон от min до max ВНУТРИ каждой группы.
    # У страны A (01, 03) добавится 02 -> 3 записи.
    # У страны B (02, 03) диапазон и так полный -> 2 записи.
    assert len(result) == 5  # Было 4, стало 5
    
    # Проверяем, что у страны A на 02-е число подставились нули и ffill для категории
    a_missing = result[(result["country"] == "A") & (result["date"] == pd.to_datetime("2020-01-02"))]
    assert len(a_missing) == 1
    assert a_missing["value"].values[0] == 0
    assert a_missing["cat_col"].values[0] == "X"

def test_apply_regularity_flag_strategy():
    """Тест стратегии 'флагом' (должна добавить колонку _has_gap)."""
    dates = pd.date_range("2020-01-01", periods=5, freq="D").delete([2]) # gap
    df = pd.DataFrame({"date": dates, "value": range(4)})
    
    result = apply_regularity_strategy(df, strategy="флагом", freq="D", date_col="date")
    
    assert "_has_gap" in result.columns
    assert result["_has_gap"].sum() > 0

def test_apply_regularity_graceful_degradation():
    """Тест Правила 16: функция не должна падать при некорректной частоте."""
    dates = pd.to_datetime(["2020-01-01", "2020-01-02"])
    df = pd.DataFrame({"date": dates, "value": [1, 2]})
    
    # Передаем невалидную частоту
    result = apply_regularity_strategy(df, strategy="Interpolate", freq="INVALID_FREQ", date_col="date")
    
    # Функция должна отработать без падения и вернуть DataFrame
    assert isinstance(result, pd.DataFrame)
    assert len(result) > 0