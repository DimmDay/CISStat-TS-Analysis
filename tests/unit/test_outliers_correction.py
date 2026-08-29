from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.outliers_correction import (
    detect_mask_on_residual,
    preview_outlier_corrections,
)


def test_cap_clips_to_iqr_bounds_without_mutating_source():
    values = [10.0] * 20 + [1000.0]
    source = pd.DataFrame({"Price": values})

    corrected, results, rows_removed = preview_outlier_corrections(source, ["Price"], "cap", "iqr", 1.5)

    assert source["Price"].iloc[-1] == 1000.0  # исходный не тронут
    assert corrected["Price"].iloc[-1] < 1000.0
    assert results[0]["outlier_count"] == 1
    assert results[0]["still_outliers"] == 0
    assert rows_removed == 0


def test_median_replaces_outliers_with_median_of_non_outliers():
    values = [10.0] * 20 + [1000.0]
    source = pd.DataFrame({"Price": values})

    corrected, results, _ = preview_outlier_corrections(source, ["Price"], "median", "iqr", 1.5)

    assert corrected["Price"].iloc[-1] == 10.0
    assert results[0]["changed_count"] == 1


def test_drop_rows_uses_union_of_selected_columns_only():
    source = pd.DataFrame({
        "A": [10.0] * 20 + [1000.0],
        "B": list(range(1, 22)),
        "Unrelated": [9999.0] + [1.0] * 20,  # выброс в ДРУГОЙ строке (0), не в той же, что A (20)
    })

    corrected, results, rows_removed = preview_outlier_corrections(source, ["A"], "drop_rows", "iqr", 1.5)

    assert rows_removed == 1
    assert len(corrected) == 20
    assert 9999.0 in corrected["Unrelated"].to_numpy()  # непроверяемая колонка не участвовала


def test_flag_preserves_values_and_adds_indicator_column():
    values = [10.0] * 20 + [1000.0]
    source = pd.DataFrame({"Price": values})

    corrected, results, _ = preview_outlier_corrections(source, ["Price"], "flag", "iqr", 1.5)

    assert corrected["Price"].iloc[-1] == 1000.0
    assert corrected["Price_outlier_flag"].tolist()[-1] == 1
    assert results[0]["flag_column"] == "Price_outlier_flag"
    assert results[0]["changed_count"] == 0


# ── Прогноз влияния на статистики (перенос app.py + missing_correction.py) ──


def test_stats_before_and_after_reported_for_cap_strategy():
    values = [10.0] * 20 + [1000.0]
    source = pd.DataFrame({"Price": values})

    _, results, _ = preview_outlier_corrections(source, ["Price"], "cap", "iqr", 1.5)

    before, after = results[0]["stats_before"], results[0]["stats_after"]
    assert before["mean"] == pytest.approx(source["Price"].mean())
    assert after["mean"] < before["mean"]  # кэпирование должно снизить среднее


def test_stats_unchanged_for_flag_strategy_since_values_are_preserved():
    values = [10.0] * 20 + [1000.0]
    source = pd.DataFrame({"Price": values})

    _, results, _ = preview_outlier_corrections(source, ["Price"], "flag", "iqr", 1.5)

    assert results[0]["stats_before"] == results[0]["stats_after"]


def test_stats_reflect_reduced_sample_after_drop_rows():
    values = [10.0] * 20 + [1000.0]
    source = pd.DataFrame({"Price": values})

    _, results, rows_removed = preview_outlier_corrections(source, ["Price"], "drop_rows", "iqr", 1.5)

    assert rows_removed == 1
    assert results[0]["stats_after"]["mean"] == pytest.approx(10.0)  # выброс исключён из выборки


def test_rejects_non_numeric_column():
    source = pd.DataFrame({"Region": ["A", "B"] * 10})
    with pytest.raises(ValueError, match="не числовая"):
        preview_outlier_corrections(source, ["Region"], "median", "iqr", 1.5)


def test_rejects_unknown_strategy():
    source = pd.DataFrame({"Price": [1.0] * 15})
    with pytest.raises(ValueError, match="Неподдерживаемая стратегия"):
        preview_outlier_corrections(source, ["Price"], "bogus", "iqr", 1.5)


def test_rejects_empty_column_selection():
    source = pd.DataFrame({"Price": [1.0] * 15})
    with pytest.raises(ValueError, match="Не выбрано ни одной колонки"):
        preview_outlier_corrections(source, [], "median", "iqr", 1.5)


# ── Обнаружение на остатке STL-декомпозиции (опция мастера) ──


def _regular_series_with_one_shock(n=48):
    dates = pd.date_range("2020-01-01", periods=n, freq="MS")
    rng = np.random.default_rng(0)
    seasonal = 10 * np.sin(np.arange(n) * 2 * np.pi / 12)
    trend = np.linspace(0, 5, n)
    noise = rng.normal(0, 0.5, n)
    values = 100 + trend + seasonal + noise
    values[30] += 50  # аномалия относительно ожидаемого сезонного уровня
    return pd.DataFrame({"date": dates, "value": values})


def test_detect_mask_on_residual_flags_the_injected_shock():
    df = _regular_series_with_one_shock()
    mask = detect_mask_on_residual(df, column="value", date_column="date", method="iqr", param=1.5)
    assert mask.iloc[30]


def test_detect_mask_on_residual_raises_for_panel_data():
    # Несколько строк на одну дату -- декомпозиция неприменима (см.
    # _prepare_decomposable_series), должно дать понятную ошибку, а не 500.
    df = pd.DataFrame({
        "date": ["2020-01-01", "2020-01-01", "2020-02-01", "2020-02-01"],
        "value": [1.0, 2.0, 3.0, 4.0],
    })
    with pytest.raises(ValueError, match="Декомпозиция недоступна"):
        detect_mask_on_residual(df, column="value", date_column="date", method="iqr", param=1.5)


def test_detect_mask_on_residual_rejects_unknown_column():
    df = _regular_series_with_one_shock()
    with pytest.raises(ValueError, match="отсутствует в датасете"):
        detect_mask_on_residual(df, column="nope", date_column="date", method="iqr", param=1.5)


# ── Boxplot-сводка (перенос px.box из легаси) ──


def test_outlier_boxplot_groups_splits_by_mask():
    from apps.api.outliers_correction import outlier_boxplot_groups

    values = pd.Series([10.0] * 20 + [1000.0])
    mask = pd.Series([False] * 20 + [True])

    groups = outlier_boxplot_groups(values, mask)

    assert groups["outliers"]["count"] == 1
    assert groups["outliers"]["median"] == 1000.0
    assert groups["normal"]["count"] == 20
    assert groups["normal"]["median"] == 10.0


def test_outlier_boxplot_groups_none_when_group_is_empty():
    from apps.api.outliers_correction import outlier_boxplot_groups

    values = pd.Series([10.0] * 5)
    mask = pd.Series([False] * 5)

    groups = outlier_boxplot_groups(values, mask)

    assert groups["outliers"] is None
    assert groups["normal"]["count"] == 5
