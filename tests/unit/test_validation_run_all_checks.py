# tests/unit/test_validation_run_all_checks.py
"""
Тесты для validate_dataframe(df, rules)["checks"] -- пер-чек агрегация
10 проверок вкладки «Валидация» (см. validation/engine.py::_run_all_checks),
подключено 2026-08-14 (ранее эти 9 функций существовали, но ни одна
API-точка их не вызывала).

Отдельный тест-файл (не смешан с tests/test_validation.py /
tests/unit/test_validation_checks.py) -- покрывает именно контракт
{status, count, items}, а не сами sub-check функции по отдельности
(они уже покрыты своими файлами).
"""
from __future__ import annotations

import pandas as pd
import pytest

from validation.engine import validate_dataframe, auto_generate_rules


EXPECTED_CHECK_IDS = {
    "data_types", "formats", "ranges", "consistency", "uniqueness",
    "inclusion", "referential", "text_quality", "regularity", "sufficiency",
}


def test_checks_key_has_all_10_ids_matching_frontend_check_type():
    """Ключи result['checks'] должны 1:1 совпадать с id в CHECKS
    (TsAnalysisValidation.tsx) -- иначе фронт получит "дыры" в списке."""
    df = pd.DataFrame({"value": [1, 2, 3]})
    result = validate_dataframe(df, {})
    assert set(result["checks"].keys()) == EXPECTED_CHECK_IDS


def test_each_check_has_status_count_items_shape():
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=10, freq="D").astype(str),
        "price": range(10),
    })
    rules = auto_generate_rules(df)
    result = validate_dataframe(df, rules)
    for check_id, check in result["checks"].items():
        assert check["status"] in ("done", "warning", "pending"), check_id
        assert "count" in check
        assert "items" in check
        assert isinstance(check["items"], list)
        for item in check["items"]:
            assert "label" in item and "count" in item


def test_pending_checks_have_none_count_and_empty_items():
    """referential без rules['referential'] -- честно 'pending', не 'done'
    (у нас физически нет справочника для сверки, это не 0 нарушений)."""
    df = pd.DataFrame({"value": [1, 2, 3]})
    result = validate_dataframe(df, {})
    assert result["checks"]["referential"] == {"status": "pending", "count": None, "items": []}


def test_ranges_violation_detected_via_auto_generated_rules():
    df = pd.DataFrame({
        "price": [10.0, 20.0, -5.0, 30.0],  # -5 должно нарушить авто-диапазон [0, max*1.5]
    })
    rules = auto_generate_rules(df)
    result = validate_dataframe(df, rules)
    ranges = result["checks"]["ranges"]
    assert ranges["status"] == "warning"
    assert ranges["count"] == 1
    assert ranges["items"] == [{"label": "price", "count": 1}]


def test_uniqueness_detects_full_row_duplicates():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)  # дублируем строку 0 (a=1,b=x) -- 2 и 3 строки других
    result = validate_dataframe(df, {})
    uniq = result["checks"]["uniqueness"]
    assert uniq["status"] == "warning"
    assert uniq["count"] == 2  # обе копии дубля считаются (duplicated(keep=False))


def test_regularity_pending_without_date_column():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    result = validate_dataframe(df, {})
    assert result["checks"]["regularity"] == {"status": "pending", "count": None, "items": []}


def test_regularity_detects_gap():
    dates = pd.date_range("2020-01-01", periods=5, freq="D").tolist()
    dates[3] = dates[3] + pd.Timedelta(days=10)  # разрыв
    df = pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in dates], "value": range(5)})
    result = validate_dataframe(df, {})
    reg = result["checks"]["regularity"]
    assert reg["status"] == "warning"
    assert reg["count"] >= 1


def test_sufficiency_pending_without_date_column():
    df = pd.DataFrame({"a": [1, 2, 3]})
    result = validate_dataframe(df, {})
    assert result["checks"]["sufficiency"] == {"status": "pending", "count": None, "items": []}


def test_data_types_reflects_schema_errors_count():
    """data_types.count должен совпадать с суммой schema_errors (не
    задваивать и не терять числа -- прямое зеркало уже существующего
    result['schema_errors'])."""
    df = pd.DataFrame({"value": [1, 2, 3]})
    result = validate_dataframe(df, {})
    dt = result["checks"]["data_types"]
    assert dt["count"] == sum(result["schema_errors"].values())


class TestTextQualityEmptyStringRegressio:
    """Регресс-тест на баг: unicode_artifacts содержал '' первым
    элементом -- str.contains('', regex=False) истинно для ЛЮБОЙ строки,
    из-за чего validate_text_quality помечал 100% строк любой текстовой
    колонки как "мусор" (найдено 2026-08-14 при первом реальном
    подключении функции к API)."""

    def test_clean_text_column_has_zero_violations(self):
        df = pd.DataFrame({
            "label": ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург"],
        })
        result = validate_dataframe(df, {})
        tq = result["checks"]["text_quality"]
        assert tq["status"] == "done", f"ложные срабатывания: {tq['items']}"
        assert tq["count"] == 0

    def test_only_actually_garbled_row_is_flagged(self):
        df = pd.DataFrame({"label": ["clean one", "clean two", "clean\x00three", "clean four"]})
        result = validate_dataframe(df, {})
        tq = result["checks"]["text_quality"]
        assert tq["status"] == "warning"
        assert tq["count"] == 1  # ровно одна строка с control-символом, не все 4


class TestSufficiencyIsoDateStringRegression:
    """Регресс-тест на баг: validate_sufficiency падал с ValueError
    ('cannot convert float NaN to integer'), если date_col хранится как
    ISO-строка ('2020-01-01'), а не datetime64 -- частый случай, т.к.
    валидация вызывается ДО стадии «Предобработка» (найдено 2026-08-14
    при первом реальном подключении к API, через GET /dataset/validate)."""

    def test_iso_date_strings_do_not_crash(self):
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=20, freq="D").astype(str),
            "country": ["RU"] * 10 + ["US"] * 10,
            "price": range(20),
        })
        result = validate_dataframe(df, {})  # не должно бросить исключение
        suff = result["checks"]["sufficiency"]
        assert suff.get("error") is None, f"sufficiency упала: {suff.get('error')}"
        assert suff["status"] == "warning"  # 10 наблюдений на группу < всех порогов
        assert suff["count"] == 10  # 2 группы (RU, US) × 5 непройденных порогов каждая
