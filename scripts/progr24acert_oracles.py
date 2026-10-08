#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОРКУЛЫ НЕЗАВИСИМОЙ СЕРТИФИКАЦИИ задачи A (spec_status_original_series.md,
Task PROGR-24-ORIGIN-A) -- аудит PROGR-24-CERT.

Принципы сертификации (прецеденты PROGR-17/18/20/21-CERT):
  - данные СВОИ, не пересекающиеся с данными разработчика
    (детерминированный аналог forecast_monitor_synthetic_n150.csv)
    и с оракулами прошлых сертификаций;
  - оракулы НЕ копируют ассерты test_status_original_series.py, а
    перекрывают их другими углами атаки (суффикс-ловушки, NaN-гигиена
    производных warm-up, локальная рекомпозиция профиля, живой
    roundtrip через store, сброс реестра с колонкой-приманкой).

СВОЙ датасет -- дневной ряд розничных продаж retail_daily.csv, 364 точки
(52 недели), колонки: date / sales / price / sales_deseasonalized (ПРИМАНКА --
исходная колонка с "производноподобным" именем, загружена из файла;
реестр обязан считать её ИСХОДНОЙ -- спека: "колонки не угадываем по
суффиксу имени"). sales: недельная сезонность + тренд + 6 инжектированных
выбросов + 4 пропуска; price -- исходный предиктор.

Группы:
  A -- модуль apps/api/column_origin.py на своих сценариях (12);
  B -- живой API на своём датасете (18);
  C -- инварианты реестра/области/канала на полном многостадийном потоке (6).

Правила AGENTS.md: только измерение, без commit/push.
"""
from __future__ import annotations

import io
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Тихий протокол: шум FastAPI/multipart/psycopg не относится к предмету аудита.
logging.disable(logging.WARNING)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.preprocessing.missing import missing_summary, profile_missing  # noqa: E402
from app.preprocessing.outliers import outliers_summary, profile_outliers  # noqa: E402
from apps.api.column_origin import (  # noqa: E402
    canonical_columns,
    derived_columns_in_frame,
    operation_added_columns,
    register_derived_columns,
    scope_columns,
    scope_frame,
    split_profiles,
)
from apps.api.main import app  # noqa: E402
from apps.api.session_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    SESSION_SCHEMA_VERSION,
    AnalysisSession,
    get_session_store,
    reset_session_store_for_testing,
    session_from_dict,
    session_to_dict,
)

OUT = REPO / "scripts" / "progr24acert_oracles.txt"

_lines: list[str] = []
_checks: list[tuple[str, bool]] = []


def emit(text: str = "") -> None:
    print(text)
    _lines.append(text)


def check(label: str, ok: bool) -> bool:
    _checks.append((label, ok))
    emit(f"    [{'PASS' if ok else 'FAIL'}] {label}")
    return ok


# ── свой датасет ─────────────────────────────────────────────────────


def _decoy_deseasonalized(sales: np.ndarray) -> np.ndarray:
    """Приманка «sales_deseasonalized»: сезон, снятый ОФФЛАЙН при подготовке
    файла (окно 7, центрированное среднее) -- это ИСХОДНАЯ колонка (загружена
    из CSV); имя похоже на производное, но реестр обязан считать её ИСХОДНОЙ
    (спека: «колонки не угадываем по суффиксу имени»). Имя выбрано так,
    чтобы НЕ совпадать ни с одним генерируемым суффиксом эндпоинтов
    (detrended/diff1/diff2/sdiff*/logdiff/ema/sma/...)."""
    s = pd.Series(sales)
    deseason = s - s.rolling(7, center=True, min_periods=1).mean() + s.mean()
    return np.round(deseason.to_numpy(), 2)


def retail_frame(version: int = 1) -> pd.DataFrame:
    """Дневной ряд розничных продаж, 364 точки. version=2 -- другой ряд
    (другая фаза сезона/шум) с колонками-приманками sales_deseasonalized И
    sales_roll7_mean в самом файле."""
    rng = np.random.default_rng(20261008 if version == 1 else 731991)
    t = np.arange(364, dtype=float)
    dow = t % 7.0
    sales = 200.0 + 0.15 * t + 60.0 * np.exp(-0.5 * ((dow - 5) / 1.0) ** 2) \
        + 45.0 * np.exp(-0.5 * ((dow - 6) / 1.0) ** 2) + rng.normal(0, 8, len(t))
    if version == 2:
        sales = 340.0 - 0.10 * t + 40.0 * np.sin(2 * np.pi * dow / 7.0) + rng.normal(0, 11, len(t))
    sales = np.round(sales, 2)
    if version == 1:
        # 6 выбросов и 4 пропуска -- только в первой версии (тестовый поток B).
        for pos, delta in [(40, 220.0), (97, 190.0), (160, -170.0), (222, 160.0), (288, 140.0), (333, -150.0)]:
            sales[pos] += delta
        sales[[70, 151, 240, 310]] = np.nan
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=364, freq="D").strftime("%Y-%m-%d"),
            "sales": sales,
            "price": np.round(100.0 + 0.02 * t + 4.0 * np.sin(2 * np.pi * t / 91.0), 2),
        }
    )
    frame["sales_deseasonalized"] = _decoy_deseasonalized(sales)
    if version == 2:
        roll = frame["sales"].rolling(7).mean()
        frame["sales_roll7_mean"] = np.round(roll, 2)
    return frame


def upload(c: TestClient, frame: pd.DataFrame, name: str) -> None:
    r = c.post(
        "/v1/internal/upload",
        files={"file": (name, io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert r.status_code == 200, r.text


def sess(c: TestClient) -> AnalysisSession:
    sid = c.cookies.get(SESSION_COOKIE_NAME)
    assert sid, "нет cookie сессии"
    return get_session_store().get(sid)


def card(c: TestClient, url: str) -> dict:
    r = c.get(url)
    assert r.status_code == 200, r.text
    return r.json()


def trace_node(c: TestClient, node_id: str) -> dict | None:
    nodes = {
        n["node_id"]: n
        for n in c.get("/v1/progress/trace").json().get("nodes", [])
        if n.get("stage") == "preprocessing"
    }
    return nodes.get(node_id)


# ── Группа A: модуль column_origin на своих сценариях ────────────────


def group_a() -> None:
    emit("\n── A. Модуль column_origin.py -- свои сценарии ──")

    s = AnalysisSession(session_id="acert")
    s.dataframe = pd.DataFrame({"date": [0], "sales": [1], "price": [2]})
    s.dataframe = pd.DataFrame({"date": [0], "sales": [1], "price": [2], "sales_deseasonalized": [3], "f1": [4], "f2": [5]})
    added = register_derived_columns(
        s, before_columns=["date", "sales", "price", "sales_deseasonalized"],
        stage="feature_eng", source="acert:lags:sales",
    )
    ok = check("A1: единая точка -- разность списков до/после (приманка в before НЕ регистрируется), метаданные {stage, source, created_at}",
               added == ["f1", "f2"] and "sales_deseasonalized" not in s.derived_columns
               and all(set(s.derived_columns[n]) == {"stage", "source", "created_at"} for n in ["f1", "f2"]))

    ok &= check("A2: суффикс-приманка sales_deseasonalized остаётся канонической (не угадывается по имени)",
                "sales_deseasonalized" in canonical_columns(s) and "sales_deseasonalized" not in s.derived_columns)
    _checks[-1] = ("A2: суффикс-приманка sales_deseasonalized остаётся канонической (не угадывается по имени)", ok)

    first_ts = s.derived_columns["f1"]["created_at"]
    re_added = register_derived_columns(s, before_columns=["date", "sales", "price", "sales_deseasonalized"],
                                        stage="smoothing", source="acert:ema:f1")
    ok = check("A2b: повторное появление колонки перезаписывает метаданные (last-wins реестра, канон зафиксирован)",
               re_added == ["f1", "f2"] and s.derived_columns["f1"]["stage"] == "smoothing"
               and s.derived_columns["f1"]["created_at"] >= first_ts)

    s.dataframe = pd.DataFrame({"a": [1]})
    s.derived_columns = {"ghost": {"stage": "decomposition", "source": "x", "created_at": "t"}}
    ok = check("A4: ghost-запись удалённой колонки безвредна (canonical==[a], derived_in_frame==[])",
               canonical_columns(s) == ["a"] and derived_columns_in_frame(s) == [])

    df = pd.DataFrame({"a": range(5), "b": range(5)})
    empty = scope_frame(df, [])
    ok = check("A5: scope_frame([]) -> 0 колонок при сохранённых строках (честное «нечего проверять»)",
               empty.shape == (5, 0) and len(empty.index) == 5)

    after = pd.DataFrame({"a": range(5), "b": range(5), "new": range(5)})
    ok = check("A6: operation_added_columns -- добавленное операцией, до записи реестра",
               operation_added_columns(["a", "b"], after) == ["new"])

    df3 = pd.DataFrame({"can": [1, 2, np.nan], "der": [np.nan, 4.0, 5.0]})
    can_prof, der_prof = split_profiles(df3, ["der"], profile_missing)
    ok = check("A7: split_profiles -- области раздельны, обе непусты и согласованы с профилем полного df",
               [p["column"] for p in can_prof] == ["can"]
               and [p["column"] for p in der_prof] == ["der"]
               and can_prof[0]["missing_count"] == 1 and der_prof[0]["missing_count"] == 1)

    s2 = AnalysisSession(session_id="acert2")
    s2.dataframe = pd.DataFrame({"a": [1], "a_d": [2]})
    s2.derived_columns = {"a_d": {"stage": "variance_stab", "source": "log:a", "created_at": "t0"}}
    rt = session_from_dict(session_to_dict(s2))
    ok = check("A8: roundtrip session_to_dict -> session_from_dict сохраняет реестр байт-в-байт",
               rt.derived_columns == s2.derived_columns)

    doc = {
        "session_id": "acert3",
        "derived_columns": {
            "ok": {"stage": "smoothing"},
            7: {"stage": "x", "source": "y", "created_at": "z"},
            "bad": 42,
            "worse": None,
            "lst": ["a"],
        },
    }
    ok = check("A9: мусорные записи отброшены, не-строковый ключ приведён к str (деградация Task 143)",
               set(session_from_dict(doc).derived_columns) == {"ok", "7"})

    s3 = AnalysisSession(session_id="acert4")
    ok = check("A10: dataframe=None -> canonical==[] и derived_in_frame==[]; register возвращает []",
               canonical_columns(s3) == [] and derived_columns_in_frame(s3) == []
               and register_derived_columns(s3, before_columns=[], stage="x", source="y") == [])

    ok = check("A11: новая сессия -- реестр пуст; SESSION_SCHEMA_VERSION == 3 (спека п.3)",
               AnalysisSession(session_id="acert5").derived_columns == {} and SESSION_SCHEMA_VERSION == 3)

    s4 = AnalysisSession(session_id="acert6")
    s4.dataframe = pd.DataFrame({"a": [1], "a_ema": [2]})
    before_snapshot = ["a"]
    register_derived_columns(s4, before_columns=before_snapshot, stage="smoothing", source="ema:a")
    again = register_derived_columns(
        s4, before_columns=["a", "a_ema"], stage="smoothing", source="ema:a"
    )
    ok = check("A12: вход не мутируется; повторный вызов без новых колонок -- no-op []",
               before_snapshot == ["a"] and again == [] and set(s4.derived_columns) == {"a_ema"})


# ── Группа B: живой API на своём датасете ────────────────────────────


def group_b_c() -> None:
    emit("\n── B/C. Живой API -- свой дневной ряд розничных продаж ──")
    reset_session_store_for_testing()
    c = TestClient(app)
    upload(c, retail_frame(1), "retail_daily.csv")

    # B1: после загрузки derived_summary отсутствует; приманка канонична;
    # карточка совпадает с ЛОКАЛЬНОЙ рекомпозицией по канонической области.
    out_card = card(c, "/v1/session/dataset/outlier-profile?method=iqr")
    miss_card = card(c, "/v1/session/dataset/missing-profile")
    local_profiles = profile_outliers(
        scope_frame(retail_frame(1), ["sales", "price", "sales_deseasonalized"]), method="iqr"
    )
    local_out = outliers_summary(local_profiles, total_rows=364)
    local_miss = missing_summary(retail_frame(1))
    check("B1: загрузка -- derived_summary нет в обоих профилях (обратная совместимость ответа)",
          out_card.get("derived_summary") is None and miss_card.get("derived_summary") is None)
    check("B1: карточка выбросов == локальная рекомпозиция по канонической области (свой расчёт)",
          out_card["total_outliers"] == local_out["total_outliers"]
          and sorted(out_card["affected_columns"]) == sorted(x["column"] for x in local_profiles if x["outlier_count"] > 0)
          and sorted(x["column"] for x in out_card["columns"] if x["outlier_count"] > 0) == sorted(x["column"] for x in local_profiles if x["outlier_count"] > 0))
    check("B1: приманка sales_deseasonalized в карточке выбросов и пропусков как ИСХОДНАЯ колонка",
          any(x["column"] == "sales_deseasonalized" for x in out_card["columns"])
          and any(x["column"] == "sales_deseasonalized" for x in miss_card["columns"]))
    check("B1: карточка пропусков == локальная рекомпозиция (пропуски sales и приманки, price чист)",
          miss_card["total_missing"] == local_miss["total_missing"] == 8)

    # B5a: preview flag на СЫРОМ ряду: флаг-колонка материализуется на копии,
    # но карточная шкала НЕ удваивается (== живой карточке до операции), а
    # вырожденный IQR флаг-колонки (K единиц -> K «выбросов») честно виден
    # только в derived_summary.
    k_sales = next(x["outlier_count"] for x in out_card["columns"] if x["column"] == "sales")
    preview = c.post("/v1/session/dataset/outlier-corrections",
                     json={"columns": ["sales"], "strategy": "flag", "method": "iqr", "apply": False}).json()
    check("B5a: preview flag на сыром ряду -- карточная шкала == живой карточке (флаг НЕ удваивает счёт), вырожденный IQR флага только в derived_summary",
          preview["status"] == "warning"
          and preview["total_outliers_after"] == out_card["total_outliers"]
          and (preview.get("derived_summary") or {}).get("total_columns") == 1
          and (preview.get("derived_summary") or {}).get("total_outliers") == k_sales)

    c.post("/v1/session/date-column", json={"column": "date"})

    # B2: interpolate + cap -> исходный ряд чист.
    cols = [x["column"] for x in miss_card["columns"] if x.get("missing_count")]
    r = c.post("/v1/session/dataset/missing-corrections",
               json={"columns": cols, "strategy": "interpolate", "apply": True})
    assert r.status_code == 200, r.text
    card1 = card(c, "/v1/session/dataset/outlier-profile?method=iqr")
    r = c.post("/v1/session/dataset/outlier-corrections",
               json={"columns": card1["affected_columns"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True})
    assert r.status_code == 200, r.text
    card2 = card(c, "/v1/session/dataset/outlier-profile?method=iqr")
    check("B2: пропуски интерполированы, выбросы кэпированы -- карточка done(0)",
          card2["status"] == "done" and card2["total_outliers"] == 0)

    # B5b: preview flag на ЧИСТОМ ряду: маска пуста -> флаг-колонка не
    # материализуется (честный no-op), карточная шкала 0.
    preview2 = c.post("/v1/session/dataset/outlier-corrections",
                      json={"columns": ["sales"], "strategy": "flag", "method": "iqr", "apply": False}).json()
    check("B5b: preview flag на чистом ряду -- done/0, флаг-колонка не создаётся (маска пуста)",
          preview2["status"] == "done" and preview2["total_outliers_after"] == 0
          and preview2.get("derived_summary") is None and preview2["added_columns"] == [])

    # B3: стационарность -> всплески производной НЕ красят карточку.
    prof = c.get("/v1/session/dataset/preprocessing/stationarity-profile?column=sales").json()
    method = prof["profile"].get("selected_method") or "first_difference"
    r = c.post("/v1/session/dataset/preprocessing/stationarity-transformations",
               json={"column": "sales", "method": method, "apply": True, "confirm_non_causal": True})
    assert r.status_code == 200, r.text
    derived_name = r.json()["output_column"]
    card3 = card(c, "/v1/session/dataset/outlier-profile?method=iqr")
    ds = card3.get("derived_summary") or {}
    check("B3: ядро спеки на своём ряде -- карточка осталась done(0), всплески производной только в derived_summary",
          card3["status"] == "done" and card3["total_outliers"] == 0 and ds.get("total_outliers", 0) >= 1)
    check("B3: реестр: производная стационарности {stage=stationarity, source непуст, created_at ISO}",
          sess(c).derived_columns[derived_name]["stage"] == "stationarity"
          and bool(sess(c).derived_columns[derived_name]["source"])
          and datetime.fromisoformat(sess(c).derived_columns[derived_name]["created_at"]) is not None)
    node = trace_node(c, "outliers")
    check("B3: трасса согласована с карточкой (done, бейдж 0) -- причина, не трассировка",
          node is not None and node["status"] == "done" and node["summary_count"] == 0)

    # B6: генерация признаков с warm-up NaN -- NaN производных не красят «Пропуски».
    r = c.post("/v1/session/dataset/preprocessing/feature-generations",
               json={"column": "sales", "lags": [1], "rolling_windows": [7],
                     "rolling_statistics": ["mean"], "drop_warmup_rows": False, "apply": True})
    assert r.status_code == 200, r.text
    fg = r.json()
    fg_names = ((fg.get("metadata") or {}).get("feature_names")) or []
    miss2 = card(c, "/v1/session/dataset/missing-profile")
    ds2 = miss2.get("derived_summary") or {}
    check("B6: NaN-гигиена -- канонические пропуски 0 (карточка done), warm-up NaN лага/каузального rolling (1+7=8) только в derived_summary",
          miss2["status"] == "done" and miss2["total_missing"] == 0
          and ds2.get("total_missing") == 8
          and ds2.get("total_columns") == 1 + len(fg_names)
          and set(fg_names) <= set(sess(c).derived_columns))
    check("B6: stage=feature_eng в реестре для всех добавленных признаков",
          all(sess(c).derived_columns[n]["stage"] == "feature_eng" for n in fg_names) and len(fg_names) >= 2)

    # B7/B8: сглаживание, дисперсия, декомпозиция -- свои стадии в реестре.
    r = c.post("/v1/session/dataset/preprocessing/smoothing-transformations",
               json={"column": "sales", "method": "ema", "span": 14, "apply": True})
    assert r.status_code == 200, r.text
    smooth_name = ((r.json().get("metadata") or {}).get("output_column")) or r.json().get("output_column")
    r = c.post("/v1/session/dataset/preprocessing/variance-transformations",
               json={"column": "sales", "method": "log", "apply": True})
    assert r.status_code == 200, r.text
    var_name = ((r.json().get("metadata") or {}).get("output_column")) or r.json().get("output_column")
    r = c.post("/v1/session/dataset/preprocessing/decomposition-outputs",
               json={"column": "sales", "period": 7, "outputs": ["components"], "apply": True})
    assert r.status_code == 200, r.text
    dec_names = r.json().get("added_columns") or []
    reg = sess(c).derived_columns
    check("B7/B8: свои стадии -- smoothing/variance_stab/decomposition зарегистрированы единой точкой",
          reg.get(smooth_name, {}).get("stage") == "smoothing"
          and reg.get(var_name, {}).get("stage") == "variance_stab"
          and all(reg.get(n, {}).get("stage") == "decomposition" for n in dec_names) and len(dec_names) >= 1)

    # B4: мастер-профиль в ответе коррекции не предлагает производные заново.
    resp = c.post("/v1/session/dataset/outlier-corrections",
                  json={"columns": ["sales"], "strategy": "cap", "method": "iqr", "param": 1.5, "apply": True}).json()
    master_cols = [x["column"] for x in resp["profile"]]
    check("B4: профиль мастера в ответе коррекции -- только канонические колонки",
          set(master_cols) <= set(canonical_columns(sess(c))))

    # B9: валидация -- 200/422/200, sufficiency-исключение для производной цели.
    ok200 = c.get("/v1/session/dataset/validate").status_code
    r422 = c.get("/v1/session/dataset/validate", params={"column": derived_name})
    r422b = c.get("/v1/session/dataset/validate", params={"column": fg_names[0]})
    ok_orig = c.get("/v1/session/dataset/validate", params={"column": "sales"}).status_code
    r_target = c.post("/v1/session/target-column", json={"column": derived_name})
    ok_suff = c.get("/v1/session/dataset/validate").status_code
    check("B9: /validate по канонической области; явная производная (стационарности И feature_eng) -- 422; исходная -- 200",
          ok200 == 200 and r422.status_code == 422 and "производн" in r422.json()["detail"].lower()
          and r422b.status_code == 422 and ok_orig == 200)
    check("B9: sufficiency-исключение -- target=производная принят, /validate 200",
          r_target.status_code == 200 and ok_suff == 200)
    c.post("/v1/session/target-column", json={"column": "sales"})

    # B14: регулярность по канонической оси.
    regp = card(c, "/v1/session/dataset/preprocessing/regularity-profile")
    check("B14: «Регулярность» применима по канонической области после 5 производящих остановок",
          regp["profile"]["applicable"] is True)

    # B12: roundtrip через живой store (save -> get) -- реестр переживает хранилище.
    store = get_session_store()
    st = sess(c)
    store.save(st)
    again = store.get(st.session_id)
    check("B12: реестр переживает save/get хранилища без потерь",
          again is not None and again.derived_columns == st.derived_columns)

    # C1/C2/C3/C4/C5: инварианты на полном многостадийном потоке.
    ok_c1 = all(set(e) == {"stage", "source", "created_at"} and bool(e["source"]) for e in reg.values())
    ok_c1 &= all(e["stage"] in {"stationarity", "smoothing", "variance_stab", "decomposition", "feature_eng", "missing", "outliers", "validation", "regularity"} for e in reg.values())
    check("C1: каждая запись реестра -- ровно {stage, source, created_at}, stage из известного набора", ok_c1)
    df_now = sess(c).dataframe
    can, der = set(canonical_columns(sess(c))), set(derived_columns_in_frame(sess(c)))
    check("C2: разбиение без потерь: canonical ∪ derived_in_frame == все колонки, пересечение пусто",
          can | der == {str(x) for x in df_now.columns} and not (can & der))
    expected_profiles = profile_outliers(scope_frame(df_now, sorted(can)), method="iqr")
    expected = outliers_summary(expected_profiles, total_rows=len(df_now))
    live = card(c, "/v1/session/dataset/outlier-profile?method=iqr")
    check("C3: живая карточка == локальная рекомпозиция по canonical_columns ПОСЛЕ 5 остановок",
          live["total_outliers"] == expected["total_outliers"]
          and sorted(x["column"] for x in live["columns"] if x["outlier_count"] > 0)
              == sorted(x["column"] for x in expected_profiles if x["outlier_count"] > 0))
    check("C5: счётчики канала неотрицательны, created_at парсится как ISO-UTC",
          all(isinstance(ds.get(k), int) and ds.get(k, 0) >= 0 for k in ("total_outliers", "total_columns"))
          and all(datetime.fromisoformat(e["created_at"]).tzinfo is not None for e in reg.values()))

    # B11: set_dataset сбрасывает реестр; приманки нового файла -- исходные.
    upload(c, retail_frame(2), "retail_daily_v2.csv")
    reg_v2 = sess(c).derived_columns
    miss_v2 = card(c, "/v1/session/dataset/missing-profile")
    cols_v2 = [x["column"] for x in miss_v2["columns"]]
    check("B11: новый датасет -- реестр пуст; колонки-приманки v2 (sales_deseasonalized, sales_roll7_mean) ИСХОДНЫЕ",
          reg_v2 == {} and "sales_deseasonalized" in cols_v2 and "sales_roll7_mean" in cols_v2)
    check("C4: derived_summary отсутствует ровно когда derived_columns_in_frame пусто (бидирекционально, финал)",
          miss_v2.get("derived_summary") is None and derived_columns_in_frame(sess(c)) == [])

    # B15: защита исходной колонки от молчаливой перезаписи генерируемым именем.
    # Файл содержит колонку sales_detrended -- ТОЧНОЕ имя выхода linear_detrend;
    # apply обязан ответить 422 «уже существует», а не затереть исходную колонку.
    reset_session_store_for_testing()
    c4 = TestClient(app)
    probe_frame = retail_frame(2).copy()
    probe_frame["sales_detrended"] = np.round(probe_frame["sales"] * 0.5, 2)
    upload(c4, probe_frame, "retail_probe.csv")
    r_probe = c4.post("/v1/session/dataset/preprocessing/stationarity-transformations",
                      json={"column": "sales", "method": "linear_detrend", "apply": True,
                            "confirm_non_causal": True})
    check("B15: коллизия генерируемого имени с исходной колонкой -- честная 422, исходные данные и реестр нетронуты",
          r_probe.status_code == 422 and "уже существует" in r_probe.json()["detail"]
          and sess(c4).derived_columns == {} and "sales_detrended" in sess(c4).dataframe.columns)

    # B10: legacy-сессия без реестра.
    legacy = {
        "session_id": "acert-legacy",
        "dataframe_json": pd.DataFrame({"date": ["2024-01-01"], "sales": [1.0]}).to_json(orient="split"),
        "stages": {},
    }
    check("B10: старый документ без derived_columns -- все колонки исходные",
          canonical_columns(session_from_dict(legacy)) == ["date", "sales"])


def main() -> int:
    emit("=" * 100)
    emit("ОРКУЛЫ СЕРТИФИКАЦИИ PROGR-24-CERT -- задача A (spec_status_original_series.md)")
    emit("Данные аудита: retail_daily.csv (364 точки, дневной ряд, приманки-суффиксы), НЕ пересекается с данными разработчика")
    emit("=" * 100)
    group_a()
    group_b_c()
    emit("\n" + "=" * 100)
    total = len(_checks)
    failed = [label for label, ok in _checks if not ok]
    emit(f"ИТОГ ОРАКУЛОВ: {total - len(failed)}/{total} GREEN")
    for label, ok in _checks:
        emit(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    emit("=" * 100)
    emit("AGENTS.md: локальное измерение, commit/push НЕ выполнялись.")
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    emit(f"Протокол: {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
