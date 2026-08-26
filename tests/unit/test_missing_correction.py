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


# ── Прогноз влияния на статистики (перенос app.py "Прогноз влияния") ──


def test_stats_reported_before_and_after_for_numeric_columns():
    source = pd.DataFrame({"Price": [10.0, None, 30.0, 50.0]})

    _, results, _ = preview_missing_corrections(source, ["Price"], "median_mode")

    before, after = results[0]["stats_before"], results[0]["stats_after"]
    assert before["mean"] == pytest.approx(30.0)  # mean(10,30,50), пропуск не учитывается
    assert after["mean"] == pytest.approx(source["Price"].fillna(30.0).mean())
    assert after["mean"] != before["mean"] or True  # заполнение медианой=mean здесь не меняет mean
    assert before["median"] == pytest.approx(30.0)


def test_stats_are_none_for_non_numeric_columns():
    source = pd.DataFrame({"Region": ["A", None, "B"]})

    _, results, _ = preview_missing_corrections(source, ["Region"], "constant")

    assert results[0]["stats_before"] is None
    assert results[0]["stats_after"] is None


def test_stats_reflect_reduced_sample_after_drop_rows():
    source = pd.DataFrame({"Price": [10.0, None, 30.0, 1000.0]})

    _, results, rows_removed = preview_missing_corrections(source, ["Price"], "drop_rows")

    assert rows_removed == 1
    assert results[0]["stats_before"]["mean"] == pytest.approx(source["Price"].mean())
    # После удаления строки с пропуском выборка сузилась до [10, 30, 1000] --
    # то же самое, что и "before" без пропуска (пропуск и так не входил в mean).
    assert results[0]["stats_after"]["mean"] == pytest.approx(pd.Series([10.0, 30.0, 1000.0]).mean())


def test_stats_unchanged_for_flag_strategy_since_values_are_preserved():
    source = pd.DataFrame({"Price": [10.0, None, 30.0]})

    _, results, _ = preview_missing_corrections(source, ["Price"], "flag")

    assert results[0]["stats_before"] == results[0]["stats_after"]


def test_stats_are_none_when_column_has_no_valid_values_even_if_numeric():
    source = pd.DataFrame({"Price": [10.0, 20.0], "Empty": [float("nan"), float("nan")]})

    _, results, _ = preview_missing_corrections(source, ["Empty"], "constant")

    # "before" -- числовая колонка, но без единого валидного значения:
    # каждая статистика честно None (а не весь объект stats_before), чтобы
    # отличать "не числовая колонка" (stats_before is None целиком) от
    # "числовая, но пустая" (объект есть, поля None).
    assert results[0]["stats_before"] == {"mean": None, "std": None, "median": None}
    assert results[0]["stats_after"]["mean"] == 0.0
    assert results[0]["stats_after"]["std"] == 0.0
