# tests/api/test_status_original_series.py
"""Task PROGR-24-ORIGIN-A (spec_status_original_series.md, задача A):
реестр происхождения колонок и каноническая область профилей качества.

Методологическое правило спеки: гейты качества данных (пропуски / выбросы /
регулярность / проверки «Валидации») применяются ОДИН РАЗ к каноническому
исходному ряду. Производные колонки (разности, сглаживание, декомпозиция,
флаги остановок) получают собственную downstream-обработку и НЕ возвращаются
в статусы более ранних остановок: остановка ниже по течению не может менять
статус остановки выше (пайплайн остаётся направленным графом).

Ключевые контракты задачи A:
  Р1 реестр derived_columns = {имя: {stage, source, created_at}} -- ЕДИНАЯ
     точка регистрации: хелпер сравнивает колонки до/после apply (не
     угадывает по суффиксу имени);
  Р2 регистрация во всех apply-эндпоинтах, добавляющих колонки
     (стационарность / генерация признаков / дисперсия / сглаживание /
     декомпозиция / флаг выбросов; симметрично -- флаг пропусков и
     валидационные флаги);
  Р3 canonical_columns(session) -- область профилей «Пропусков»,
     «Выбросов», «Регулярности» и проверок «Валидации»; статус считается
     ТОЛЬКО по исходным колонкам;
  Р4 профиль по производным колонкам -- отдельно, полем derived_summary,
     ВНЕ статуса и вне свёртки;
  Р5 совместимость: старые сессии без реестра считают все колонки
     исходными; set_dataset сбрасывает реестр; версия схемы растёт;
  Р6 петля «+4 выброса от самой флаг-колонки» (PROGR-22-REPRO) исчезает
     ПО ПОСТРОЕНИЮ: флаг-колонка остановки сама производная.

Следствие для ROGR-22-REPRO-G345 (спека §Реализация п.4): «окно лжи»
PROGR-23-FIX-G345 закрывается ПРИЧИНОЙ (карточка больше не видит
производные всплески), трассировка из PROGR-23 остаётся.
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.column_origin import (
    canonical_columns,
    derived_columns_in_frame,
    register_derived_columns,
    scope_columns,
)
from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    SESSION_SCHEMA_VERSION,
    AnalysisSession,
    get_session_store,
    reset_session_store_for_testing,
    session_from_dict,
    session_to_dict,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


# ── helpers ──────────────────────────────────────────────────────────


def _g345_frame() -> pd.DataFrame:
    """Детерминированный аналог forecast_monitor_synthetic_n150.csv
    (тренд + сезон M=12, 4 выброса, 3 пропуска) -- тот же кадр, на котором
    воспроизводился класс C5 (worklog9.md)."""
    t = np.arange(150, dtype=float)
    value = 120 + 0.55 * t + 18 * np.sin(2.0 * np.pi * (t + 2) / 12.0)
    value[25] += 110
    value[70] += 105
    value[105] += 95
    value[130] -= 135
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2013-01-01", periods=150, freq="MS").strftime("%Y-%m-%d"),
            "value": np.round(value, 2),
        }
    )
    frame.loc[[45, 87, 122], "value"] = np.nan
    return frame


def _upload(client_: TestClient, frame: pd.DataFrame) -> None:
    response = client_.post(
        "/v1/internal/upload",
        files={"file": ("frame.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _session() -> Any:
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id, "у тестового клиента нет cookie сессии"
    return get_session_store().get(session_id)


def _stationarity_apply(client_: TestClient, column: str = "value") -> dict[str, Any]:
    """Честный UI-поток до стационарности (кнопка «Применить» мастера
    disabled без preview -- верность UI-потоку, PROGR-22-REPRO-G345):
    остановка «Пропуски» интерполирует пропуски (гейт стационарности
    требует завершённой остановки), затем preview → apply. Если профиль
    не выбрал метод -- явный выбор аналитика first_difference."""
    missing = _missing_card(client_)
    cols = [x["column"] for x in missing["columns"] if x.get("missing_count")]
    if cols:
        response = client_.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": cols, "strategy": "interpolate", "apply": True},
        )
        assert response.status_code == 200, response.text
    profile = client_.get(
        f"/v1/session/dataset/preprocessing/stationarity-profile?column={column}"
    ).json()
    method = profile["profile"].get("selected_method") or "first_difference"
    response = client_.post(
        "/v1/session/dataset/preprocessing/stationarity-transformations",
        json={"column": column, "method": method, "apply": True, "confirm_non_causal": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _outlier_card(client_: TestClient) -> dict[str, Any]:
    response = client_.get("/v1/session/dataset/outlier-profile?method=iqr")
    assert response.status_code == 200, response.text
    return response.json()


def _missing_card(client_: TestClient) -> dict[str, Any]:
    response = client_.get("/v1/session/dataset/missing-profile")
    assert response.status_code == 200, response.text
    return response.json()


# ── Р1/Р2: реестр происхождения -- единая точка регистрации ──────────


class TestRegistryRegistration:
    def test_session_has_derived_columns_field_default_empty(self):
        session = AnalysisSession(session_id="s")
        assert session.derived_columns == {}, "старые/новые сессии без применений -- реестр пуст"

    def test_register_derived_columns_compares_before_after(self):
        """Хелпер НЕ угадывает по суффиксу: регистрируется разность
        списков колонок до/после apply, метаданные {stage, source,
        created_at} передаются вызывающим apply-эндпоинтом."""
        session = AnalysisSession(session_id="s")
        session.dataframe = pd.DataFrame({"a": [1], "b": [2]})
        added = register_derived_columns(
            session, before_columns=["a"], stage="stationarity", source="stationarity:first_difference:a"
        )
        assert added == ["b"]
        entry = session.derived_columns["b"]
        assert entry["stage"] == "stationarity"
        assert entry["source"] == "stationarity:first_difference:a"
        assert entry["created_at"], "штамп времени обязателен"

    def test_register_derived_columns_no_new_columns_is_noop(self):
        session = AnalysisSession(session_id="s")
        session.dataframe = pd.DataFrame({"a": [1]})
        added = register_derived_columns(
            session, before_columns=["a"], stage="outliers", source="outlier_flag"
        )
        assert added == []
        assert session.derived_columns == {}

    def test_stationarity_apply_registers_output_column(self):
        _upload(client, _g345_frame())
        summary = _stationarity_apply(client)
        registry = _session().derived_columns
        output = summary["output_column"]
        assert output in registry, "производная колонка стационарности зарегистрирована"
        assert registry[output]["stage"] == "stationarity"

    def test_outlier_flag_apply_registers_flag_column(self):
        """Р6: флаг-колонка самой остановки «Выбросы» сама производная --
        петля «+4 выброса от флаг-колонки» (PROGR-22-REPRO) исчезает
        по построению."""
        _upload(client, _g345_frame())
        response = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["value"], "strategy": "flag", "method": "iqr", "apply": True},
        )
        assert response.status_code == 200, response.text
        flag_column = response.json()["added_columns"][0]
        registry = _session().derived_columns
        assert registry[flag_column]["stage"] == "outliers"

    def test_missing_flag_apply_registers_flag_column(self):
        _upload(client, _g345_frame())
        response = client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": ["value"], "strategy": "flag", "apply": True},
        )
        assert response.status_code == 200, response.text
        flag_column = response.json()["added_columns"][0]
        registry = _session().derived_columns
        assert registry[flag_column]["stage"] == "missing"

    def test_preview_does_not_register(self):
        """Preview не мутирует сессию -- реестр растёт только на apply."""
        _upload(client, _g345_frame())
        response = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["value"], "strategy": "flag", "method": "iqr", "apply": False},
        )
        assert response.status_code == 200, response.text
        assert _session().derived_columns == {}

    def test_cap_strategy_without_new_columns_registers_nothing(self):
        _upload(client, _g345_frame())
        response = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["value"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
        )
        assert response.status_code == 200, response.text
        assert _session().derived_columns == {}, "кэп меняет значения, а не добавляет колонки"


# ── Р5: каноническая область, совместимость, сериализация ────────────


class TestCanonicalScopeAndCompat:
    def test_canonical_columns_excludes_registered_keeps_order(self):
        session = AnalysisSession(session_id="s")
        session.dataframe = pd.DataFrame({"date": [0], "value": [1], "value_d": [2]})
        session.derived_columns = {"value_d": {"stage": "stationarity", "source": "x", "created_at": "t"}}
        assert canonical_columns(session) == ["date", "value"]

    def test_canonical_columns_stale_registry_entry_is_harmless(self):
        """Реестр может содержать уже удалённую колонку: область
        пересекается с фактическими колонками датафрейма."""
        session = AnalysisSession(session_id="s")
        session.dataframe = pd.DataFrame({"a": [1]})
        session.derived_columns = {
            "ghost": {"stage": "smoothing", "source": "x", "created_at": "t"},
        }
        assert canonical_columns(session) == ["a"]
        assert derived_columns_in_frame(session) == []

    def test_scope_columns_utility(self):
        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        assert scope_columns(df, ["b"]) == ["a", "c"]
        assert scope_columns(df, []) == ["a", "b", "c"]
        assert scope_columns(df, ["a", "b", "c"]) == []

    def test_legacy_session_without_registry_all_columns_canonical(self):
        """Старые Redis-сессии без поля derived_columns: все колонки
        считаются исходными (обратная совместимость, спека §Реализация п.3)."""
        legacy = {
            "session_id": "legacy",
            "dataframe_json": pd.DataFrame({"a": [1]}).to_json(orient="split"),
            "stages": {},
        }
        session = session_from_dict(legacy)
        assert session.derived_columns == {}
        assert canonical_columns(session) == ["a"]

    def test_schema_version_grows(self):
        """Спека §Реализация п.3: версия схемы сессии растёт."""
        assert SESSION_SCHEMA_VERSION == 3

    def test_registry_survives_serialization_roundtrip(self):
        session = AnalysisSession(session_id="s")
        session.dataframe = pd.DataFrame({"a": [1], "a_d": [2]})
        session.derived_columns = {"a_d": {"stage": "smoothing", "source": "ema:a", "created_at": "t"}}
        restored = session_from_dict(session_to_dict(session))
        assert restored.derived_columns == session.derived_columns

    def test_corrupt_registry_entries_are_dropped_on_read(self):
        """Философия деградации Task 143: мусорная запись реестра не роняет
        сессию -- не-словарные значения отбрасываются при чтении."""
        doc = {
            "session_id": "s",
            "derived_columns": {"ok": {"stage": "smoothing"}, "bad": 42, "worse": None},
        }
        session = session_from_dict(doc)
        assert set(session.derived_columns) == {"ok"}

    def test_set_dataset_resets_registry(self):
        _upload(client, _g345_frame())
        _stationarity_apply(client)
        assert _session().derived_columns, "предусловие: реестр непустой"
        _upload(client, _g345_frame())
        assert _session().derived_columns == {}, "новый датасет = новый анализ"


# ── Р3/Р4: область профилей «Выбросов» + derived_summary ─────────────


class TestOutlierProfileScope:
    def test_card_counts_canonical_only_and_derived_summary_carries_spikes(self):
        """Ядро задачи A: производные всплески НЕ прибавляются к карточке
        (в карточной шкале только исходные 4, а не 8), но честно видны в
        derived_summary (вне статуса)."""
        _upload(client, _g345_frame())
        _stationarity_apply(client)

        card = _outlier_card(client)
        assert card["status"] == "warning", "предусловие: исходные 4 выбросы value на месте"
        assert card["total_outliers"] == 4, (
            "в карточной шкале только выбросы исходной колонки -- добавка от "
            "производной (ещё 4) исчезла"
        )
        card_columns = [item["column"] for item in card["columns"]]
        assert card_columns == ["value"], "в профиле карточки только исходные колонки"

        derived = card["derived_summary"]
        assert derived is not None, "при наличии производных колонок derived_summary есть"
        assert derived["total_outliers"] == 4, "всплески производной колонки честно посчитаны отдельно"
        assert derived["total_columns"] == 1
        assert [item["column"] for item in derived["columns"]][0] != "value"

    def test_card_done_when_original_clean_and_derived_spikes_stay_informational(self):
        """Полное ядро спеки: исходный ряд вычищен, производная колонка
        несёт всплески -> карточка ЗЕЛЁНАЯ (статус не возвращается назад),
        всплески -- только в информационном канале."""
        _upload(client, _g345_frame())
        client.post("/v1/session/date-column", json={"column": "date"})
        missing = _missing_card(client)
        cols = [x["column"] for x in missing["columns"] if x.get("missing_count")]
        client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": cols, "strategy": "interpolate", "apply": True},
        )
        card1 = _outlier_card(client)
        client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": card1["affected_columns"], "strategy": "cap",
                  "method": "iqr", "param": 1.5, "apply": True},
        )
        _stationarity_apply(client)

        card = _outlier_card(client)
        assert card["status"] == "done", (
            "исходный ряд чист -- остановка «Выбросы» зелёная независимо от "
            "производных всплесков"
        )
        assert card["total_outliers"] == 0
        assert card["derived_summary"]["total_outliers"] == 4, (
            "всплески производной колонки честны в информационном канале"
        )

    def test_no_derived_columns_derived_summary_is_absent(self):
        _upload(client, _g345_frame())
        card = _outlier_card(client)
        assert card["status"] == "warning", "предусловие: у исходной колонки есть выбросы"
        assert card["total_outliers"] == 4
        assert card.get("derived_summary") is None, (
            "без производных колонок информационного канала нет -- ответ "
            "обратной совместимости"
        )

    def test_c5_root_cause_closed_partial_fix_leaves_green_card(self):
        """Класс C5 G345 устраняется ПРИЧИНОЙ: частичная фиксация (исходная
        колонка исправлена, производная снята с чекбокса) оставляет ЗЕЛЁНУЮ
        карточку -- жёлтой её красили только выбросы производной колонки."""
        _upload(client, _g345_frame())
        client.post("/v1/session/date-column", json={"column": "date"})
        missing = _missing_card(client)
        cols = [x["column"] for x in missing["columns"] if x.get("missing_count")]
        client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": cols, "strategy": "interpolate", "apply": True},
        )
        card1 = _outlier_card(client)
        client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": card1["affected_columns"], "strategy": "cap",
                  "method": "iqr", "param": 1.5, "apply": True},
        )
        _stationarity_apply(client)

        apply2 = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["value"], "strategy": "cap", "method": "iqr",
                  "param": 1.5, "apply": True},
        ).json()
        assert apply2["status"] == "done", "карточная шкала после частичной фиксации -- done"
        assert apply2["total_outliers_after"] == 0
        assert apply2["derived_summary"]["total_outliers"] == 4, (
            "всплески производной колонки остались -- но в информационном "
            "канале, вне статуса"
        )

        card_final = _outlier_card(client)
        assert card_final["status"] == "done"
        assert card_final["total_outliers"] == 0

    def test_flag_column_loop_disappears_by_construction(self):
        """Р6: после flag-apply флаг-колонка исчезает из профиля карточки --
        её собственные «выбросы» (вырожденный IQR на 0/1) больше не
        добавляются к остановке (PROGR-22-REPRO: «+4 от самой флаг-колонки»)."""
        _upload(client, _g345_frame())
        before = _outlier_card(client)
        assert before["total_outliers"] == 4

        response = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["value"], "strategy": "flag", "method": "iqr", "apply": True},
        )
        assert response.status_code == 200, response.text
        flag_column = response.json()["added_columns"][0]

        after = _outlier_card(client)
        after_columns = [item["column"] for item in after["columns"]]
        assert flag_column not in after_columns, "флаг-колонка -- производная, в карточке её нет"
        assert after["total_numeric_columns"] == 1
        assert after["derived_summary"]["total_columns"] == 1

    def test_correction_response_card_scale_anticipates_preview_flags(self):
        """Preview flag-операции: карточная шкала ответа -- гипотеза ПОСЛЕ
        операции; добавляемые операцией флаг-колонки уже учтены как
        производные: счёт карточки (4 исходных) НЕ удваивается деградировавшим
        IQR флаг-колонки (до задачи A -- 8)."""
        _upload(client, _g345_frame())
        preview = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["value"], "strategy": "flag", "method": "iqr", "apply": False},
        ).json()
        assert preview["status"] == "warning", "флаги не меняют значения исходной колонки"
        assert preview["total_outliers_after"] == 4, (
            "флаг-колонка не попадает в карточную шкалу даже в гипотезе preview: "
            "4 исходных, а не 8"
        )
        assert preview["derived_summary"]["total_outliers"] == 4, (
            "деградировавший IQR флаг-колонки виден только в информационном канале"
        )

    def test_correction_response_status_matches_card_get(self):
        _upload(client, _g345_frame())
        _stationarity_apply(client)
        response = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": ["value"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True},
        ).json()
        card = _outlier_card(client)
        assert response["status"] == card["status"]
        assert response["total_outliers_after"] == card["total_outliers"]


# ── Р3/Р4: область профиля «Пропусков» ───────────────────────────────


class TestMissingProfileScope:
    def test_missing_card_counts_canonical_only(self):
        _upload(client, _g345_frame())
        _stationarity_apply(client)
        card = _missing_card(client)
        card_columns = [item["column"] for item in card["columns"]]
        assert card_columns == ["value"] or card_columns == ["date", "value"], (
            "в профиле пропусков только исходные колонки"
        )
        assert all("value_" not in c or c == "value" for c in card_columns)
        assert card["derived_summary"] is not None
        assert card["derived_summary"]["total_columns"] >= 1

    def test_missing_correction_response_profile_scoped(self):
        _upload(client, _g345_frame())
        _stationarity_apply(client)
        response = client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": ["value"], "strategy": "interpolate", "apply": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        profile_columns = [item["column"] for item in body["profile"]]
        assert all(item != "value_detrend" and not item.startswith("value_") or item == "value" for item in profile_columns)


# ── Р3: «Регулярность» -- каноническая область ───────────────────────


class TestRegularityProfileScope:
    def test_regularity_profile_applicable_and_stable_with_derived_columns(self):
        """Регулярность работает по временной оси; подстановка канонической
        области не ломает автодетекцию даты, а производные числовые колонки
        не участвуют."""
        _upload(client, _g345_frame())
        _stationarity_apply(client)
        response = client.get("/v1/session/dataset/preprocessing/regularity-profile")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["profile"]["applicable"] is True
        assert body["status"] in {"done", "warning"}

    def test_regularity_validation_side_scoped(self):
        _upload(client, _g345_frame())
        _stationarity_apply(client)
        response = client.get("/v1/session/dataset/regularity-profile")
        assert response.status_code == 200, response.text
        assert response.json()["profile"]["applicable"] is True


# ── Р3: проверки «Валидации» -- каноническая область ─────────────────


class TestValidationScope:
    def test_validate_runs_on_canonical_scope(self):
        _upload(client, _g345_frame())
        _stationarity_apply(client)
        response = client.get("/v1/session/dataset/validate")
        assert response.status_code == 200, response.text
        body = response.json()
        assert "checks" in body
        # производные колонки не участвуют в проверках: свежая производная
        # колонка не порождает новых ошибок data_types/ranges
        assert body["checks"]["data_types"]["status"] in {"done", "warning", "skipped"}

    def test_validate_explicit_derived_column_is_honest_422(self):
        """Прямой вызов с производной колонкой -- методологический guard:
        проверки качества к производным колонкам не применяются."""
        _upload(client, _g345_frame())
        summary = _stationarity_apply(client)
        derived = summary["output_column"]
        response = client.get("/v1/session/dataset/validate", params={"column": derived})
        assert response.status_code == 422
        assert "производн" in response.json()["detail"].lower()

    def test_validate_explicit_original_column_still_works(self):
        _upload(client, _g345_frame())
        _stationarity_apply(client)
        response = client.get("/v1/session/dataset/validate", params={"column": "value"})
        assert response.status_code == 200, response.text

    def test_sufficiency_with_derived_target_still_works(self):
        """Исключение (документировано): sufficiency -- проверка готовности
        к моделированию о ВЫБРАННОМ target (он может быть производным),
        а не гейт качества канонического ряда."""
        _upload(client, _g345_frame())
        summary = _stationarity_apply(client)
        derived = summary["output_column"]
        response = client.post("/v1/session/target-column", json={"column": derived})
        assert response.status_code == 200, response.text
        validate_response = client.get("/v1/session/dataset/validate")
        assert validate_response.status_code == 200, validate_response.text


# ── Полный поток G345: финал card == trace, причина закрыта ──────────


class TestFullG345Flow:
    def test_full_flow_card_trace_consistent_and_spike_channel_honest(self):
        """Полный поток G345 (загрузка -> пропуски -> выбросы №1 ->
        стационарность): после задачи A карточка НЕ желтеет от производных
        всплесков вовсе (причина устранена), Прогресс согласован с ней,
        информационный канал derived_summary несёт 4 всплеска."""
        _upload(client, _g345_frame())
        client.post("/v1/session/date-column", json={"column": "date"})
        missing = _missing_card(client)
        cols = [x["column"] for x in missing["columns"] if x.get("missing_count")]
        client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": cols, "strategy": "interpolate", "apply": True},
        )
        card1 = _outlier_card(client)
        client.post(
            "/v1/session/dataset/outlier-corrections",
            json={"columns": card1["affected_columns"], "strategy": "cap",
                  "method": "iqr", "param": 1.5, "apply": True},
        )
        _stationarity_apply(client)

        card2 = _outlier_card(client)
        assert card2["status"] == "done", (
            "причина закрыта: производные всплески не окрашивают остановку "
            "«Выбросы» исходного ряда"
        )
        assert card2["derived_summary"]["total_outliers"] == 4

        trace = client.get("/v1/progress/trace")
        assert trace.status_code == 200, trace.text
        nodes = {
            n["node_id"]: n
            for n in trace.json().get("nodes", [])
            if n.get("stage") == "preprocessing"
        }
        assert nodes["outliers"]["status"] == card2["status"], (
            "Прогресс согласован с карточкой -- расхождение G345 не "
            "воспроизводится на уровне причины"
        )
