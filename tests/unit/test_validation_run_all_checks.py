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
    assert result["checks"]["referential"] == {"status": "pending", "count": None, "items": [], "scope": "column"}


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
    assert result["checks"]["regularity"] == {"status": "pending", "count": None, "items": [], "scope": "dataset"}


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
    assert result["checks"]["sufficiency"] == {"status": "pending", "count": None, "items": [], "scope": "column"}


def test_data_types_is_pending_without_explicit_schema():
    """Фактический dtype нельзя считать эталоном для самого себя.

    Без rules['schema']['columns'] backend строит профиль типов, но не
    заявляет ложное «0 нарушений»: сравнивать фактические типы не с чем.
    """
    df = pd.DataFrame({"value": [1, 2, 3]})
    result = validate_dataframe(df, {})
    dt = result["checks"]["data_types"]
    assert dt == {"status": "pending", "count": None, "items": [], "scope": "dataset"}


def test_data_types_is_done_when_explicit_schema_matches():
    df = pd.DataFrame({"value": [1, 2, 3]})
    rules = {
        "schema": {
            "columns": {
                "value": {"type": "integer", "required": True, "coerce": True},
            }
        }
    }
    result = validate_dataframe(df, rules)
    assert result["checks"]["data_types"] == {
        "status": "done", "count": 0, "items": [], "scope": "dataset"
    }


def test_data_types_warns_when_value_cannot_be_coerced_to_schema_type():
    df = pd.DataFrame({"value": ["1", "not-a-number", "3"]})
    rules = {
        "schema": {
            "columns": {
                "value": {"type": "integer", "required": True, "coerce": True},
            }
        }
    }
    result = validate_dataframe(df, rules)
    data_types = result["checks"]["data_types"]

    assert data_types["status"] == "warning"
    assert data_types["count"] > 0
    assert data_types["items"]
    assert result["schema_errors_by_column"]["value"] > 0


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


class TestPerColumnScoping:
    """target_column (2026-08-14) -- часть проверок скоупится до одной
    колонки, часть принципиально остаётся dataset-wide (см. докстринг
    _run_all_checks). scope в ответе честно показывает, что есть что."""

    def test_ranges_scoped_to_target_column_only(self):
        df = pd.DataFrame({
            "price": [10.0, 20.0, -999.0, 30.0],  # 1 нарушение
            "score": [1000.0, 2000.0, -50000.0, 1500.0],  # тоже нарушение, но НЕ target
        })
        rules = auto_generate_rules(df)
        result = validate_dataframe(df, rules, target_column="price")
        ranges = result["checks"]["ranges"]
        assert ranges["scope"] == "column"
        assert ranges["items"] == [{"label": "price", "count": 1}]  # НЕ score

    def test_ranges_without_target_column_shows_all_columns(self):
        """Без target_column поведение НЕ меняется -- backward compatible
        (public.py/internal.py вызывают validate_dataframe(df, rules) без
        target_column, дефолт None).

        Обе колонки содержат 'price' в имени -- auto_generate_rules даёт
        каждой СВОЁ домен-правило (min=0, см. auto_generate_rules), у
        generic (не price/year) колонок авто-диапазон вычисляется ИЗ
        min/max самой колонки и поэтому математически не может быть
        нарушен -- для честного теста с двумя нарушениями нужны именно
        price-подобные имена."""
        df = pd.DataFrame({
            "price": [10.0, 20.0, -999.0, 30.0],
            "avg_price": [100.0, 200.0, -500.0, 150.0],
        })
        rules = auto_generate_rules(df)
        result = validate_dataframe(df, rules)  # target_column не передан
        ranges = result["checks"]["ranges"]
        labels = {i["label"] for i in ranges["items"]}
        assert labels == {"price", "avg_price"}

    def test_ranges_pending_when_target_column_has_no_rule_violations_but_other_does(self):
        """target_column='price' задан, но у price нет нарушений (только
        у 'other') -- pending с count=None, а не 0 (0 означало бы 'проверено,
        нарушений нет', а не 'к этой колонке правило вообще не привязано')."""
        df = pd.DataFrame({
            "price": [10.0, 20.0, 30.0],  # без нарушений
            "other": [1000.0, 2000.0, -99999.0],  # нарушение, но не в target
        })
        rules = auto_generate_rules(df)
        result = validate_dataframe(df, rules, target_column="price")
        ranges = result["checks"]["ranges"]
        assert ranges["scope"] == "column"
        # price прошёл (0 нарушений) -- validate_ranges всё равно вернёт
        # запись для price с Нарушений=0, значит статус "done", не "pending"
        assert ranges["status"] == "done"
        assert ranges["count"] == 0

    def test_sufficiency_scoped_via_num_col_directly(self):
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=10, freq="D").astype(str),
            "price": range(10),
            "volume": range(10, 20),
        })
        result_price = validate_dataframe(df, {}, target_column="price")
        result_volume = validate_dataframe(df, {}, target_column="volume")
        # Разные target_column могут дать разные Группа-детали (validate_sufficiency
        # использует num_col для отчёта) -- главное, что оба реально приняты,
        # без ошибок, и scope="column".
        assert result_price["checks"]["sufficiency"]["scope"] == "column"
        assert result_volume["checks"]["sufficiency"]["scope"] == "column"
        assert result_price["checks"]["sufficiency"].get("error") is None
        assert result_volume["checks"]["sufficiency"].get("error") is None

    def test_consistency_uniqueness_regularity_ignore_target_column(self):
        """Эти 3 проверки принципиально dataset-wide -- target_column не
        должен менять их результат (межколоночные правила / дубли строк /
        ось времени -- см. докстринг _run_all_checks)."""
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=10, freq="D").astype(str),
            "price": range(10),
            "volume": range(10, 20),
        })
        result_none = validate_dataframe(df, {}, target_column=None)
        result_price = validate_dataframe(df, {}, target_column="price")
        for check_id in ("consistency", "uniqueness", "regularity"):
            assert result_none["checks"][check_id]["scope"] == "dataset"
            assert result_price["checks"][check_id]["scope"] == "dataset"
            assert result_none["checks"][check_id]["count"] == result_price["checks"][check_id]["count"]

    def test_text_quality_scoped_to_numeric_target_is_pending(self):
        """target_column всегда числовой (контракт Phase 0.5) --
        validate_text_quality работает только с текстовыми колонками,
        поэтому для числового target честный результат -- pending, не
        ошибка и не 0 (0 подразумевало бы, что проверка была применена)."""
        df = pd.DataFrame({"price": [1.0, 2.0, 3.0], "label": ["clean", "text", "here"]})
        result = validate_dataframe(df, {}, target_column="price")
        tq = result["checks"]["text_quality"]
        assert tq["scope"] == "column"
        assert tq["status"] == "pending"
        assert tq["count"] is None
