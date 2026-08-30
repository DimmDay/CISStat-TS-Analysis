from __future__ import annotations

import pandas as pd
import pytest

from validation.regularity import regularity_intervals, regularity_timeline


def test_intervals_reports_modal_and_threshold_in_seconds():
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    df = pd.DataFrame({"date": dates, "value": range(12)})

    result = regularity_intervals(df)

    assert result["modal_seconds"] is not None
    assert result["threshold_seconds"] == pytest.approx(result["modal_seconds"] * 1.5)
    assert sum(b["count"] for b in result["bins"]) == 11  # 12 точек -> 11 интервалов


def test_intervals_not_applicable_returns_empty_result():
    df = pd.DataFrame({"a": [1, 2, 3]})
    result = regularity_intervals(df)
    assert result["bins"] == []
    assert result["modal_seconds"] is None


def test_intervals_selects_largest_group_by_default_for_panel_data():
    dates_a = pd.date_range("2020-01-01", periods=3, freq="MS")
    dates_b = pd.date_range("2020-01-01", periods=8, freq="MS")
    df = pd.concat([
        pd.DataFrame({"date": dates_a, "entity": "A"}),
        pd.DataFrame({"date": dates_b, "entity": "B"}),
    ], ignore_index=True)

    result = regularity_intervals(df)
    assert result["group"] == "B"  # B крупнее (8 набл. против 3)


def test_intervals_respects_explicit_group_selection():
    dates_a = pd.date_range("2020-01-01", periods=3, freq="MS")
    dates_b = pd.date_range("2020-01-01", periods=8, freq="MS")
    df = pd.concat([
        pd.DataFrame({"date": dates_a, "entity": "A"}),
        pd.DataFrame({"date": dates_b, "entity": "B"}),
    ], ignore_index=True)

    result = regularity_intervals(df, group="A")
    assert result["group"] == "A"


def test_timeline_flags_gap_duplicate_and_sort_violation_events():
    dates = pd.date_range("2020-01-01", periods=6, freq="MS").tolist()
    # Разрыв: пропущен один месяц между позициями 2 и 3
    with_gap = dates[:3] + dates[4:]
    # Добавляем дубль и нарушение сортировки
    rows = with_gap + [with_gap[0], dates[0]]
    df = pd.DataFrame({"date": rows})

    result = regularity_timeline(df)
    kinds = {event["kind"] for event in result["events"]}
    assert "gap" in kinds
    assert "duplicate" in kinds
    assert result["date_column"] == "date"
    assert result["min_date"] is not None and result["max_date"] is not None


def test_timeline_not_applicable_returns_empty_result():
    df = pd.DataFrame({"a": [1, 2, 3]})
    result = regularity_timeline(df)
    assert result["events"] == []
    assert result["date_column"] is None


def test_timeline_truncates_when_events_exceed_max():
    # Полностью хаотичный ряд -- почти каждая точка станет "разрывом"
    dates = pd.date_range("2020-01-01", periods=50, freq="D").tolist()
    scattered = [dates[0]] + [dates[i] for i in range(1, 50, 7)]  # редкие, неровные шаги
    df = pd.DataFrame({"date": scattered})

    result = regularity_timeline(df, max_events=2)
    assert len(result["events"]) <= 2
