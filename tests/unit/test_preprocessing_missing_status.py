from __future__ import annotations

from apps.api.routers.session import _preprocessing_missing_status


def test_disabled_mode_is_always_skipped_regardless_of_data():
    assert _preprocessing_missing_status("disabled", total_columns=5, total_missing=10) == ("skipped", "disabled")
    assert _preprocessing_missing_status("disabled", total_columns=0, total_missing=0) == ("skipped", "disabled")


def test_zero_columns_is_not_required_for_auto_and_enabled():
    assert _preprocessing_missing_status("auto", total_columns=0, total_missing=0) == ("skipped", "not_required")
    # enabled не может заставить появиться колонки -- тот же нейтральный статус, не "needs_rule".
    assert _preprocessing_missing_status("enabled", total_columns=0, total_missing=0) == ("skipped", "not_required")


def test_auto_and_enabled_report_real_data_when_columns_exist():
    assert _preprocessing_missing_status("auto", total_columns=3, total_missing=0) == ("done", None)
    assert _preprocessing_missing_status("auto", total_columns=3, total_missing=2) == ("warning", None)
    assert _preprocessing_missing_status("enabled", total_columns=3, total_missing=0) == ("done", None)
    assert _preprocessing_missing_status("enabled", total_columns=3, total_missing=2) == ("warning", None)
