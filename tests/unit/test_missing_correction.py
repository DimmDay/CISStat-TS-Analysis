from __future__ import annotations

import pandas as pd
import pytest

from apps.api.missing_correction import preview_missing_corrections


def test_median_mode_preview_does_not_mutate_source():
    source = pd.DataFrame({"Price": [10.0, None, 30.0, None]})

    corrected, results, rows_removed = preview_missing_corrections(
        source, ["Price"], "median_mode"
    )

    assert source["Price"].isnull().sum() == 2  # исходный DataFrame не тронут
    assert corrected["Price"].tolist() == [10.0, 20.0, 30.0, 20.0]
    assert results[0]["missing_count"] == 2
    assert results[0]["changed_count"] == 2
    assert results[0]["still_missing"] == 0
    assert rows_removed == 0


def test_mean_mode_preview_fills_categorical_with_mode():
    source = pd.DataFrame({"Region": ["A", "A", None, "B"]})

    corrected, results, _ = preview_missing_corrections(source, ["Region"], "mean_mode")

    assert corrected["Region"].tolist() == ["A", "A", "A", "B"]
    assert results[0]["still_missing"] == 0


def test_constant_preview_fills_zero_for_numeric_and_unknown_for_categorical():
    source = pd.DataFrame({"Price": [1.0, None], "Region": ["A", None]})

    corrected, results, _ = preview_missing_corrections(
        source, ["Price", "Region"], "constant"
    )

    assert corrected["Price"].tolist() == [1.0, 0.0]
    assert corrected["Region"].tolist() == ["A", "Unknown"]


def test_interpolate_preview_uses_linear_interpolation():
    source = pd.DataFrame({"Price": [10.0, None, 30.0]})

    corrected, results, _ = preview_missing_corrections(source, ["Price"], "interpolate")

    assert corrected["Price"].tolist() == [10.0, 20.0, 30.0]
    assert results[0]["still_missing"] == 0


def test_interpolate_rejects_non_numeric_column():
    source = pd.DataFrame({"Region": ["A", None, "B"]})

    with pytest.raises(ValueError, match="Интерполяция доступна только для числовых"):
        preview_missing_corrections(source, ["Region"], "interpolate")


def test_drop_rows_uses_union_of_selected_columns_only():
    source = pd.DataFrame({
        "Price": [1.0, None, 3.0],
        "Region": ["A", "B", None],
        "Unrelated": [None, "x", "y"],  # содержит пропуск, но не выбрана
    })

    corrected, results, rows_removed = preview_missing_corrections(
        source, ["Price", "Region"], "drop_rows"
    )

    assert rows_removed == 2  # строки 1 и 2 (Price или Region пусты)
    assert corrected["Price"].tolist() == [1.0]
    assert corrected["Region"].tolist() == ["A"]
    assert pd.isna(corrected["Unrelated"].iloc[0])  # непроверяемая колонка не участвовала в удалении


def test_flag_preserves_missing_values_and_adds_indicator_column():
    source = pd.DataFrame({"Price": [1.0, None]})

    corrected, results, _ = preview_missing_corrections(source, ["Price"], "flag")

    assert corrected["Price"].isnull().tolist() == [False, True]
    assert corrected["Price_missing_flag"].tolist() == [0, 1]
    assert results[0]["flag_column"] == "Price_missing_flag"
    assert results[0]["still_missing"] == 1
    assert results[0]["changed_count"] == 0


def test_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="Неподдерживаемая стратегия"):
        preview_missing_corrections(pd.DataFrame({"A": [1, None]}), ["A"], "bogus")


def test_rejects_empty_column_selection():
    with pytest.raises(ValueError, match="Не выбрано ни одной колонки"):
        preview_missing_corrections(pd.DataFrame({"A": [1, None]}), [], "constant")


def test_rejects_column_missing_from_dataframe():
    with pytest.raises(ValueError, match="отсутствует в датасете"):
        preview_missing_corrections(pd.DataFrame({"A": [1, None]}), ["B"], "constant")


def test_median_mode_raises_when_no_valid_values_available():
    source = pd.DataFrame({"Price": [float("nan"), float("nan")]})  # dtype float64, полностью пуст
    with pytest.raises(ValueError, match="нет корректных значений"):
        preview_missing_corrections(source, ["Price"], "median_mode")
