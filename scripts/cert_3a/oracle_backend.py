# -*- coding: utf-8 -*-
"""PANEL-MODELS-3a-CERT: независимые оракулы на СВОИХ данных.

Корпус «Уральские цеха» (U1 4x8, U2 6x12, U3 5x12/5x9) с РУЧНОЙ арифметикой:
target = base + 2*d (d -- индекс дня), exog = 10*base + d. Все ожидания
вычислены вручную и зафиксированы константами. Дизъюнктен с корпусами
поставки (test_panel_preprocessing/test_panel_contract) и прошлых сертификатов.

Запуск из корня репозитория: python3 scripts/cert_3a/oracle_backend.py
Канон ошибки: любая неудача -- FAIL с описанием; скрипт печатает таблицу и
exit-код 0/1.
"""
from __future__ import annotations

import copy
import json
import sys

import numpy as np
import pandas as pd

from app.preprocessing.panel import (
    BALANCED,
    CAPACITY_REFUSE_ENTITIES,
    CAPACITY_WARN_ENTITIES,
    UNBALANCED,
    PanelContractError,
    PanelFrame,
    PanelPassport,
    between_transform,
    build_panel_frame,
    build_panel_passport,
    entity_dummies,
    panel_fingerprint,
    panel_lag,
    pesaran_cd,
    within_transform,
)
from apps.api.modeling_workflow import build_panel_modeling_context
from apps.api.session_store import (
    AnalysisSession,
    DatasetInfo,
    PASSPORT_CHECKPOINT_STAGES,
    PASSPORT_STAGES,
    session_from_dict,
    session_to_dict,
)

RESULTS: list[tuple[str, str, str]] = []  # (oracle, status, detail)


def check(oracle: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    RESULTS.append((oracle, status, detail))
    if not condition:
        print(f"FAIL {oracle}: {detail}")


def expect_error(oracle: str, fn, *fragments: str) -> None:
    try:
        fn()
    except PanelContractError as error:
        message = str(error)
        missing = [fragment for fragment in fragments if fragment not in message]
        check(oracle, not missing, f"сообщение без фрагментов {missing}: {message!r}")
        return
    except Exception as error:  # noqa: BLE001
        check(oracle, False, f"неожиданный класс {type(error).__name__}: {error}")
        return
    check(oracle, False, "PanelContractError не поднят")


# ── Корпуса (ручная арифметика) ─────────────────────────────────────────────

BASES = {"Ц1": 100, "Ц2": 200, "Ц3": 300, "Ц4": 400}  # Уральские цеха
START = pd.Timestamp("2024-03-01")


def ural(n_dates: int = 8, entities=("Ц1", "Ц2", "Ц3", "Ц4"), shift_last_by: int = 0) -> pd.DataFrame:
    rows = []
    for index, entity in enumerate(entities):
        offset = shift_last_by if (shift_last_by and entity == entities[-1]) else 0
        for day in range(n_dates):
            rows.append({
                "entity": entity,
                "date": START + pd.Timedelta(days=day + offset),
                "target": float(BASES[entity] + 2 * day),
                "exog": float(10 * BASES[entity] + day),
            })
    return pd.DataFrame(rows)


def balanced(n_entities: int, n_dates: int, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_entities):
        for day in range(n_dates):
            rows.append({
                "entity": f"з{i}",
                "date": pd.Timestamp("2024-04-01") + pd.Timedelta(days=day),
                "target": float(rng.normal(5 + i, 1)),
                "exog": float(rng.normal(0, 1)),
            })
    return pd.DataFrame(rows)


PARAMS_FULL = dict(date_column="date", entity_column="entity",
                   value_columns=["target", "exog"], target_column="target")

# ── O01: честная фактура сбалансированной панели (ручные числа) ────────────
frame_u1 = build_panel_frame(ural(8), **PARAMS_FULL)
check("O01a", frame_u1.n_entities == 4 and frame_u1.balance == BALANCED, str(frame_u1.balance))
check("O01b", frame_u1.n_dates_common == 8 and len(frame_u1.dates_common) == 8, str(frame_u1.n_dates_common))
check("O01c", frame_u1.t_per_entity == {"min": 8, "median": 8.0, "max": 8}, str(frame_u1.t_per_entity))
check("O01d", frame_u1.n_valid == 32, str(frame_u1.n_valid))
check("O01e", list(frame_u1.dates_common)[0] == START and list(frame_u1.dates_common)[-1] == START + pd.Timedelta(days=7), "dates_common endpoints")
check("O01f", frame_u1.value_columns == ("target", "exog") and frame_u1.target_column == "target", "composition")
shuffled_u1 = ural(8).sample(frac=1, random_state=13).reset_index(drop=True)
frame_shuffled = build_panel_frame(shuffled_u1, **PARAMS_FULL)
pairs_shuffled = list(frame_shuffled.frame[["entity", "date"]].itertuples(index=False, name=None))
check("O01g", pairs_shuffled == sorted(pairs_shuffled), "frame -- отсортированная копия на перемешанном входе")

# ── O02: несбалансированность (Ц4 сдвинут на 2 дня, внутри регулярна) ──────
frame_u1s = build_panel_frame(ural(8, shift_last_by=2), **PARAMS_FULL)
expected_common = [START + pd.Timedelta(days=d) for d in range(2, 8)]
check("O02a", frame_u1s.balance == UNBALANCED, frame_u1s.balance)
check("O02b", frame_u1s.n_dates_common == 6, str(frame_u1s.n_dates_common))
check("O02c", list(frame_u1s.dates_common) == expected_common, "пересечение сеток вручную: 03-03..03-08")
check("O02d", frame_u1s.t_per_entity == {"min": 8, "median": 8.0, "max": 8}, str(frame_u1s.t_per_entity))
check("O02e", frame_u1s.n_valid == 32, str(frame_u1s.n_valid))

# ── O03: дубликаты (entity, date) с примером сущностей ─────────────────────
dup = pd.concat([ural(8), ural(8).iloc[[0]]], ignore_index=True)
expect_error("O03", lambda: build_panel_frame(dup, **PARAMS_FULL), "дубликат", "Ц1")

# ── O04-O06: fail-closed даты/сущности/числа ────────────────────────────────
bad_date = ural(8).astype({"date": object})
bad_date.loc[0, "date"] = "не-дата"
expect_error("O04", lambda: build_panel_frame(bad_date, **PARAMS_FULL), "дат")
nan_entity = ural(8)
nan_entity["entity"] = nan_entity["entity"].astype(object)
nan_entity.loc[3, "entity"] = None
expect_error("O05", lambda: build_panel_frame(nan_entity, **PARAMS_FULL), "сущност")
non_numeric = ural(8).astype({"exog": object})
non_numeric["exog"] = ["a", "b"] * 16
expect_error("O06", lambda: build_panel_frame(non_numeric, **PARAMS_FULL), "числов")

# ── O07: гэп внутри сущности vs регулярная короткая сетка всех ─────────────
gapped = ural(8)
gapped = gapped[~((gapped["entity"] == "Ц2") & (gapped["date"] == START + pd.Timedelta(days=3)))]
expect_error("O07a", lambda: build_panel_frame(gapped, **PARAMS_FULL), "регулярн")
shorter = ural(8)
shorter = shorter[shorter["date"] != START]  # у ВСЕХ нет первого дня -- регулярная сетка 7 дат
frame_short = build_panel_frame(shorter, **PARAMS_FULL)
check("O07b", frame_short.t_per_entity == {"min": 7, "median": 7.0, "max": 7}
      and frame_short.balance == BALANCED and frame_short.n_valid == 28,
      f"регулярная короткая сетка легитимна: {frame_short.t_per_entity}")

# ── O08: состав колонок ─────────────────────────────────────────────────────
expect_error("O08a", lambda: build_panel_frame(ural(8), date_column="date", entity_column="date",
                                               value_columns=["target"], target_column="target"), "различ")
expect_error("O08b", lambda: build_panel_frame(ural(8), date_column="date", entity_column="entity",
                                               value_columns=["target"], target_column="exog"), "должна входить")
expect_error("O08c", lambda: build_panel_frame(ural(8), date_column="date", entity_column="entity",
                                               value_columns=["target", "target"], target_column="target"), "различ")
expect_error("O08d", lambda: build_panel_frame(ural(8), date_column="date", entity_column="entity",
                                               value_columns=["target", "date"], target_column="target"), "сущностной")
expect_error("O08e", lambda: build_panel_frame(ural(8).drop(columns=["exog"]), **PARAMS_FULL), "exog")

# ── O09: исходный df не мутируется (глубокое сравнение) ────────────────────
source = ural(8)
snapshot = copy.deepcopy(source)
build_panel_frame(source, **PARAMS_FULL)
check("O09", source.equals(snapshot), "df эквивалентен глубокой копии до вызова")

# ── O10: иммутабельность и JSON-безопасность ────────────────────────────────
try:
    frame_u1.n_entities = 99
    check("O10a", False, "FrozenInstanceError не поднят")
except Exception as error:  # noqa: BLE001
    check("O10a", type(error).__name__ == "FrozenInstanceError", type(error).__name__)
payload = frame_u1.to_dict()
try:
    json.dumps(payload, ensure_ascii=False, allow_nan=False)
    check("O10b", payload["contract_version"] == "panel-contract-v1", "json ok")
except ValueError as error:
    check("O10b", False, f"json: {error}")

# ── O11: tz-aware даты -> naive UTC (ручная конвертация +05:00) ─────────────
tz_rows = []
for day in range(8):
    for entity, base in BASES.items():
        tz_rows.append({
            "entity": entity,
            "date": pd.Timestamp("2024-03-01", tz="Asia/Yekaterinburg") + pd.Timedelta(days=day),
            "target": float(base + 2 * day),
            "exog": float(10 * base + day),
        })
frame_tz = build_panel_frame(pd.DataFrame(tz_rows), **PARAMS_FULL)
expected_naive = pd.Timestamp("2024-02-29") + pd.Timedelta(hours=19)  # 00:00+05 -> 19:00 UTC предыдущего дня
check("O11a", frame_tz.n_valid == 32 and frame_tz.balance == BALANCED, "tz-панель прошла контракт")
first_date = frame_tz.frame["date"].min()
check("O11b", first_date == expected_naive, f"первая дата {first_date} != {expected_naive}")

# ── O12: within/between ручная арифметика (среднее Ц1 = 107, Ц4 = 407) ──────
within = within_transform(ural(8), entity_column="entity", columns=["target", "exog"])
between = between_transform(ural(8), entity_column="entity", columns=["target", "exog"])
row0 = within[(within["entity"] == "Ц1")].sort_values("date").iloc[0]
check("O12a", abs(row0["target"] - (-7.0)) < 1e-12, f"within Ц1 d0 = {row0['target']} (ручное -7)")
b4 = between[between["entity"] == "Ц4"]["target"]
check("O12b", bool((b4 == 407.0).all()), f"between Ц4 = 407 (получено {b4.unique()})")
total = within[["target", "exog"]] + between[["target", "exog"]]
check("O12c", np.allclose(total.to_numpy(dtype=float), ural(8)[["target", "exog"]].to_numpy(dtype=float)), "within+between==исходный")
means = within.groupby("entity")["target"].mean()
check("O12d", bool(np.allclose(means.to_numpy(dtype=float), 0.0, atol=1e-12)), "нулевое среднее within")
check("O12e", not within.equals(ural(8)), "within возвращает изменённую копию, источник не тронут")
check("O12f", ural(8)["target"].sum() == sum(BASES[e] * 8 + 2 * 28 for e in BASES), "санити корпуса (ручная сумма)")

# ── O13: panel_lag без утечек на своих данных ──────────────────────────────
lagged = panel_lag(ural(8), entity_column="entity", column="target", lags=(1, 2))
check("O13a", lagged["target_lag1"].isna().sum() == 4 and lagged["target_lag2"].isna().sum() == 8,
      f"NaN по первым 1/2 датам каждой сущности: {lagged['target_lag1'].isna().sum()}/{lagged['target_lag2'].isna().sum()}")
c2 = lagged[lagged["entity"] == "Ц2"].sort_values("date")
check("O13b", c2["target_lag1"].iloc[1] == 200.0 and c2["target_lag2"].iloc[2] == 200.0,
      f"Ц2(d1).lag1==200, Ц2(d2).lag2==200: {c2['target_lag1'].iloc[1]},{c2['target_lag2'].iloc[2]}")
# Плоский shift на сортировке (date, entity) УТЕКАЕТ -- панельный лаг обязан дать NaN:
interleaved = ural(8).sort_values(["date", "entity"]).reset_index(drop=True)
flat = interleaved["target"].shift(1)
panel = panel_lag(interleaved, entity_column="entity", column="target", lags=(1,))
first_non_base = panel[panel["entity"] != "Ц1"].index.min()
check("O13c", flat.loc[first_non_base] == 100.0 and pd.isna(panel.loc[first_non_base, "target_lag1"]),
      "плоский shift утёкает (100.0), panel_lag даёт NaN")
expect_error("O13d", lambda: panel_lag(ural(8), entity_column="entity", column="target", lags=(0,)), "положительными")
expect_error("O13e", lambda: panel_lag(ural(8), entity_column="entity", column="нет_колонки", lags=(1,)), "нет_колонки")

# ── O14: entity_dummies ─────────────────────────────────────────────────────
dummies_first = entity_dummies(ural(8), entity_column="entity", drop_first=True)
check("O14a", dummies_first.shape == (32, 3) and list(dummies_first.columns) == ["Ц2", "Ц3", "Ц4"],
      f"{dummies_first.shape}, {list(dummies_first.columns)}")
check("O14b", (dummies_first[ural(8)["entity"] == "Ц1"].to_numpy() == 0).all(), "базовая сущность нулевая")
dummies_full = entity_dummies(ural(8), entity_column="entity", drop_first=False)
check("O14c", dummies_full.shape == (32, 4) and list(dummies_full.columns) == ["Ц1", "Ц2", "Ц3", "Ц4"], "полная матрица")
check("O14d", (dummies_full.sum(axis=0).to_numpy() == [8, 8, 8, 8]).all(), "по 8 единиц на сущность")

# ── O15: fingerprint-инварианты ─────────────────────────────────────────────
df_u1 = ural(8)
fp_base = panel_fingerprint(df_u1, **PARAMS_FULL)
check("O15a", len(fp_base) == 64 and fp_base == panel_fingerprint(df_u1.sample(frac=1, random_state=5).reset_index(drop=True), **PARAMS_FULL),
      "порядок строк не влияет")
changed = df_u1.copy()
changed.loc[10, "target"] = changed.loc[10, "target"] + 0.5
check("O15b", fp_base != panel_fingerprint(changed, **PARAMS_FULL), "смена значения меняет fingerprint")
check("O15c", fp_base != panel_fingerprint(df_u1.iloc[1:], **PARAMS_FULL), "удаление строки меняет fingerprint")
renamed = df_u1.rename(columns={"exog": "exog_v2"})
check("O15d", fp_base == panel_fingerprint(renamed, date_column="date", entity_column="entity",
                                           value_columns=["target", "exog_v2"], target_column="target"),
      "переименование value-колонки (то же содержание/позиция) не меняет fingerprint")
swapped = panel_fingerprint(df_u1, date_column="date", entity_column="entity",
                            value_columns=["exog", "target"], target_column="target")
check("O15e", swapped != fp_base, "смена ПОРЯДКА value_columns меняет fingerprint (состав сверяется отдельно)")
frame_norm = build_panel_frame(df_u1, **PARAMS_FULL)
check("O15f", fp_base == panel_fingerprint(frame_norm.frame, **PARAMS_FULL), "fingerprint нормализованной копии == исходному")
tz_fp = panel_fingerprint(pd.DataFrame(tz_rows), **PARAMS_FULL)
check("O15g", tz_fp != fp_base, "tz-aware содержимое честно отличается (UTC-сдвиг меняет даты)")
expect_error("O15h", lambda: panel_fingerprint(pd.DataFrame(), **PARAMS_FULL), "Fingerprint")
expect_error("O15i", lambda: panel_fingerprint(df_u1.drop(columns=["target"]), **PARAMS_FULL), "target")

# ── O16: Pesaran CD -- точная ручная арифметика ─────────────────────────────
z = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
cd_rows = []
for entity, sign in (("р1", 1.0), ("р2", 1.0), ("р3", -1.0)):
    for t in range(5):
        cd_rows.append({"entity": entity, "date": pd.Timestamp("2024-05-01") + pd.Timedelta(days=t),
                        "value": sign * z[t]})
cd_result = pesaran_cd(pd.DataFrame(cd_rows), date_column="date", entity_column="entity", column="value")
expected_stat = float(np.sqrt(2 * 5 / (3 * 2)) * (1.0 + (-1.0) + (-1.0)))  # sqrt(5/3) * (-1)
check("O16a", cd_result["available"] is True and abs(cd_result["statistic"] - expected_stat) < 1e-9,
      f"CD={cd_result['statistic']}, ручное {expected_stat}")
check("O16b", cd_result["n_pairs"] == 3 and cd_result["n_pairs_skipped"] == 0
      and cd_result["t_common"] == 5 and cd_result["n_entities"] == 3, str(cd_result))
check("O16c", 0.0 <= cd_result["p_value"] <= 1.0 and cd_result["p_value"] > 0.05,
      f"p={cd_result['p_value']} (сумма rho=-1 не значима -- ручная проверка)")

# ── O17: CD skip-логика (inf-выбросы режут пары) ────────────────────────────
skip_rows = []
for day in range(6):
    skip_rows.append({"entity": "a", "date": pd.Timestamp("2024-06-01") + pd.Timedelta(days=day), "value": float(day) + 1})
    value_b = (float(day) + 1) if day >= 4 else float("inf")  # у b только 2 конечные точки
    skip_rows.append({"entity": "b", "date": pd.Timestamp("2024-06-01") + pd.Timedelta(days=day), "value": value_b})
    skip_rows.append({"entity": "c", "date": pd.Timestamp("2024-06-01") + pd.Timedelta(days=day), "value": float(day) * 2})
skip_result = pesaran_cd(pd.DataFrame(skip_rows), date_column="date", entity_column="entity", column="value")
check("O17a", skip_result["available"] is True and skip_result["n_pairs"] == 1 and skip_result["n_pairs_skipped"] == 2,
      str({k: skip_result[k] for k in ("n_pairs", "n_pairs_skipped", "available")}))
# нулевая дисперсия -- пара пропускается
const_rows = [{"entity": "x", "date": pd.Timestamp("2024-07-01") + pd.Timedelta(days=t), "value": 5.0} for t in range(4)]
const_rows += [{"entity": "y", "date": pd.Timestamp("2024-07-01") + pd.Timedelta(days=t), "value": float(t)} for t in range(4)]
const_result = pesaran_cd(pd.DataFrame(const_rows), date_column="date", entity_column="entity", column="value")
check("O17b", const_result["available"] is False and const_result["n_pairs_skipped"] == 1, str(const_result.get("reason")))

# ── O18: CD unavailable-ветки ───────────────────────────────────────────────
single = pesaran_cd(pd.DataFrame([row for row in cd_rows if row["entity"] == "р1"]),
                    date_column="date", entity_column="entity", column="value")
check("O18a", single["available"] is False and "2 сущности" in single["reason"], single["reason"])
two_dates = pesaran_cd(pd.DataFrame(cd_rows[:2] + cd_rows[5:7]), date_column="date", entity_column="entity", column="value")
check("O18b", two_dates["available"] is False and "коротка" in two_dates["reason"], two_dates["reason"])
broken = pesaran_cd(pd.DataFrame([{"entity": "a", "date": "мусор", "value": 1}]), date_column="date", entity_column="entity", column="value")
check("O18c", broken["available"] is False and broken["reason"], "мусорная дата -> available=False, не крэш")

# ── O19: гейты паспорта на СВОИХ корпусах ───────────────────────────────────
passport_u2 = build_panel_passport(balanced(6, 12), **PARAMS_FULL)
fe = passport_u2.models["fixed_effects"]
re_ = passport_u2.models["random_effects"]
pv = passport_u2.models["panel_var"]
check("O19a", fe["applicable"] is True and re_["applicable"] is True and fe["gates"] == {"n_entities": 6, "t_min": 12, "n_exog": 1},
      str(fe))
check("O19b", pv["applicable"] is True and pv["warning"] is not None and "VAR(1)" in pv["warning"],
      f"T_common=12: VAR(1) применим, VAR(2) warning: {pv['warning']}")
passport_u2_18 = build_panel_passport(balanced(6, 18, seed=1), **PARAMS_FULL)
check("O19c", passport_u2_18.models["panel_var"]["warning"] is None, "T_common=18 >= 3*2*3: warning нет")
passport_u2_17 = build_panel_passport(balanced(6, 17, seed=2), **PARAMS_FULL)
pv17 = passport_u2_17.models["panel_var"]
check("O19d", pv17["applicable"] is True and pv17["warning"] is not None, "T_common=17: pass + warning")
passport_5x12 = build_panel_passport(balanced(5, 12, seed=3), **PARAMS_FULL)
check("O19e", passport_5x12.models["fixed_effects"]["applicable"] is True
      and passport_5x12.models["panel_var"]["applicable"] is True, "границы 5 сущностей/T=12 -- ровно на гейте")
passport_5x11 = build_panel_passport(balanced(5, 11, seed=4), **PARAMS_FULL)
pv11 = passport_5x11.models["panel_var"]
check("O19f", pv11["applicable"] is False and any("T_common=11" in r for r in pv11["reasons"]), str(pv11["reasons"]))
passport_5x9 = build_panel_passport(balanced(5, 9, seed=5), **PARAMS_FULL)
fe9 = passport_5x9.models["fixed_effects"]
check("O19g", fe9["applicable"] is False and any("минимальная длина" in r and "9" in r for r in fe9["reasons"])
      and not any("Недостаточно сущностей" in r for r in fe9["reasons"]),
      "5x9: только гейт длины, сущностей достаточно")
passport_u1 = build_panel_passport(ural(8), **PARAMS_FULL)
fe_u1 = passport_u1.models["fixed_effects"]
check("O19h", fe_u1["applicable"] is False and any("Недостаточно сущностей" in r for r in fe_u1["reasons"])
      and any("минимальная длина" in r for r in fe_u1["reasons"]), "4x8: обе причины различимы")
no_exog = build_panel_passport(balanced(6, 12, seed=6), date_column="date", entity_column="entity",
                               value_columns=["target"], target_column="target")
check("O19i", no_exog.models["fixed_effects"]["applicable"] is False
      and any("экзоген" in r and "PANEL-GMM-4" in r for r in no_exog.models["fixed_effects"]["reasons"])
      and no_exog.models["panel_var"]["applicable"] is False, "нет экзогенных: FE честная причина + PVAR n_vars<2")
check("O19j", no_exog.models["gmm"]["applicable"] is False and "PANEL-GMM-4" in " ".join(no_exog.models["gmm"]["reasons"]),
      "GMM честный отказ")
unbal_rows = []
for i in range(5):
    for t in range(14):
        unbal_rows.append({"entity": f"з{i}", "date": pd.Timestamp("2024-04-01") + pd.Timedelta(days=t),
                           "target": float(i + t), "exog": float(t)})
for t in range(14):  # з5: сдвинутое окно, внутри строго регулярно
    unbal_rows.append({"entity": "з5", "date": pd.Timestamp("2024-04-03") + pd.Timedelta(days=t),
                       "target": float(t), "exog": -float(t)})
passport_unbal = build_panel_passport(pd.DataFrame(unbal_rows), **PARAMS_FULL)
pv_unbal = passport_unbal.models["panel_var"]
check("O19k", pv_unbal["applicable"] is False and len(pv_unbal["reasons"]) == 1
      and "сбалансированн" in pv_unbal["reasons"][0].lower(),
      f"несбалансированность -- единственная причина PVAR: {pv_unbal['reasons']}")

# ── O20: advisory CD не блокирует паспорт (сильная зависимость) ─────────────
rng = np.random.default_rng(77)
factor = rng.normal(0, 1, size=12)
dep_rows = []
for i in range(6):
    for t in range(12):
        dep_rows.append({"entity": f"з{i}", "date": pd.Timestamp("2024-04-01") + pd.Timedelta(days=t),
                         "target": float(3.0 * factor[t] + rng.normal(0, 0.05)), "exog": float(t)})
dep_passport = build_panel_passport(pd.DataFrame(dep_rows), **PARAMS_FULL)
check("O20a", dep_passport.cross_sectional_dependence["available"] is True
      and abs(dep_passport.cross_sectional_dependence["statistic"]) > 2.0, str(dep_passport.cross_sectional_dependence.get("statistic")))
check("O20b", dep_passport.models["fixed_effects"]["applicable"] is True, "advisory не блокирует гейты")

# ── O21: капы производительности (_capacity_facts через паспорт 201) ────────
passport_201 = build_panel_passport(balanced(201, 10, seed=8), **PARAMS_FULL)
check("O21a", passport_201.capacity["refused"] is False and passport_201.capacity["warning"] is not None
      and passport_201.capacity["n_entities"] == 201, "201 сущностей: warning, не отказ")
check("O21b", passport_201.models["fixed_effects"]["applicable"] is True, "201: FE остаётся применимым")
# границы капов: 2000 -- ещё не отказ (строгий >), 2001 -- отказ. Полный паспорт на 2000+
# сущностей с CD (2M пар) -- минуты, этот путь покрыт repo-тестом; здесь -- _capacity_facts.
from app.preprocessing.panel import _capacity_facts  # noqa: E402
cap2000 = _capacity_facts(2000)
cap2001 = _capacity_facts(2001)
check("O21c", cap2000["refused"] is False and cap2000["warning"] is not None and "2000" in cap2000["warning"],
      "2000 сущностей: warning, ещё не отказ (кап строгий >)")
check("O21d", cap2001["refused"] is True and "2000" in cap2001["warning"] and "512MB" in cap2001["warning"], str(cap2001["warning"]))

# ── O22: профиль достаточности и nan_profile (ручные числа) ─────────────────
check("O22a", passport_u2.sufficiency["applicable"] is True and passport_u2.sufficiency["groups_total"] == 6,
      str(passport_u2.sufficiency.get("groups_total")))
nan_ural = ural(8)
nan_ural.loc[(nan_ural["entity"] == "Ц2") & (nan_ural["date"] == START + pd.Timedelta(days=2)), "target"] = np.nan
nan_ural.loc[(nan_ural["entity"] == "Ц3") & (nan_ural["date"] == START + pd.Timedelta(days=3)), "exog"] = np.nan
frame_nan = build_panel_frame(nan_ural, **PARAMS_FULL)
check("O22b", frame_nan.n_valid == 31, f"n_valid=32-1={frame_nan.n_valid}")
check("O22c", frame_nan.nan_profile["Ц2"]["target_missing"] == 1 and frame_nan.nan_profile["Ц2"]["rows"] == 8, str(frame_nan.nan_profile["Ц2"]))
check("O22d", frame_nan.nan_profile["Ц3"]["exog_missing"] == 1 and frame_nan.nan_profile["Ц3"]["target_missing"] == 0, str(frame_nan.nan_profile["Ц3"]))
check("O22e", frame_nan.nan_profile["Ц1"] == {"rows": 8, "target_missing": 0, "exog_missing": 0}, str(frame_nan.nan_profile["Ц1"]))
# смешанная колонка: часть значений не числа -> NaN, НЕ ошибка (честная семантика coerce)
mixed = ural(8).astype({"exog": object})
mixed.loc[mixed["entity"] == "Ц4", "exog"] = ["п", "н"] * 4
frame_mixed = build_panel_frame(mixed, **PARAMS_FULL)
check("O22f", frame_mixed.n_valid == 32 and frame_mixed.nan_profile["Ц4"]["exog_missing"] == 8,
      "смешанная колонка -> NaN по сущности, контракт не рвётся")
inf_ural = ural(8)
inf_ural.loc[(inf_ural["entity"] == "Ц3") & (inf_ural["date"] == START + pd.Timedelta(days=4)), "target"] = np.inf
frame_inf = build_panel_frame(inf_ural, **PARAMS_FULL)
check("O22g", frame_inf.n_valid == 31 and frame_inf.nan_profile["Ц3"]["target_missing"] == 1,
      f"inf-target честно исключён из n_valid ({frame_inf.n_valid}) и учтён в профиле")

# ── O23: PanelPassport иммутабельность/JSON/фактура ─────────────────────────
try:
    passport_u2.balance = BALANCED
    check("O23a", False, "FrozenInstanceError не поднят")
except Exception as error:  # noqa: BLE001
    check("O23a", type(error).__name__ == "FrozenInstanceError", type(error).__name__)
dump = passport_u2.to_dict()
try:
    json.dumps(dump, ensure_ascii=False, allow_nan=False)
    check("O23b", dump["contract_version"] == "panel-passport-v1" and dump["columns"]["target_column"] == "target", "json ok")
except ValueError as error:
    check("O23b", False, f"json: {error}")
check("O23c", dump["columns"] == {"date_column": "date", "entity_column": "entity",
                                  "value_columns": ["target", "exog"], "target_column": "target"}, "блок columns дублирует состав")
check("O23d", passport_u2_18.n_entities == 6 and passport_u2_18.n_dates_common == 18
      and passport_u2_18.t_per_entity == {"min": 18, "median": 18.0, "max": 18}, "фактура паспорта == фактуре frame")
iso = dep_passport.created_at
check("O23e", "T" in iso and ("+" in iso or "Z" in iso or iso.endswith("00")), f"created_at ISO-UTC: {iso}")

# ── O24: вселенная panel_entry (session_store) ──────────────────────────────
def make_session(df: pd.DataFrame) -> AnalysisSession:
    session = AnalysisSession(session_id="cert-ural")
    session.set_dataset(DatasetInfo(dataset_id="ds-cert", name="ural", rows=len(df),
                                    columns=len(df.columns), size_label="1 KB", dataset_fingerprint="fp-cert"), df)
    session.target_column = "target"
    session.date_column = "date"
    return session


def confirm(session: AnalysisSession, df: pd.DataFrame):
    passport = build_panel_passport(df, **PARAMS_FULL)
    fingerprint = panel_fingerprint(df, **PARAMS_FULL)
    snapshot = session.append_panel_passport_snapshot(passport=passport.to_dict(), fingerprint=fingerprint)
    checkpoint = session.append_panel_entry_checkpoint(snapshot, previous_snapshot_id=snapshot.snapshot_id, created_snapshot=True)
    return snapshot, checkpoint


df_u2 = balanced(6, 12)
session = make_session(df_u2)
try:
    session.target_column = None
    session.append_panel_passport_snapshot(passport={"x": 1}, fingerprint="fp")
    check("O24a", False, "требование target не сработало")
except ValueError as error:
    check("O24a", isinstance(error, ValueError) and "target" in str(error), str(error))
session.target_column = "target"
snapshot1, checkpoint1 = confirm(session, df_u2)
confirm(session, df_u2)
check("O24b", len(session.panel_passport_history) == 2 and len(session.panel_entry_checkpoints) == 2
      and session.latest_panel_entry_checkpoint() is session.panel_entry_checkpoints[-1], "append-only история")
check("O24c", session.latest_passport_checkpoint("modeling_entry") is None and session.passport_history == []
      and session.passport_checkpoints == [], "однорядная вселенная не тронута (R4)")
check("O24d", checkpoint1.stage == "panel_entry" and checkpoint1.fingerprint == snapshot1.fingerprint
      and snapshot1.passport["contract_version"] == "panel-passport-v1", "содержимое checkpoint")
foreign = make_session(df_u2)
foreign_snapshot, _ = confirm(foreign, df_u2)
try:
    session.append_panel_entry_checkpoint(foreign_snapshot, previous_snapshot_id=None, created_snapshot=False)
    check("O24e", False, "чужой снимок принят")
except ValueError as error:
    check("O24e", isinstance(error, ValueError) and "снимок" in str(error), str(error))
session.reset_passports()
check("O24f", session.panel_passport_history == [] and session.panel_entry_checkpoints == []
      and session.latest_panel_entry_checkpoint() is None, "reset_passports чистит панельную вселенную")
session2 = make_session(df_u2)
_, _ = confirm(session2, df_u2)
session2.set_target_column("exog")  # смена цели -- reset_passports
check("O24g", session2.panel_passport_history == [] and session2.panel_entry_checkpoints == [], "set_target_column инвалидирует панель")
session3 = make_session(df_u2)
snapshot3, checkpoint3 = confirm(session3, df_u2)
restored = session_from_dict(session_to_dict(session3))
check("O24h", restored.latest_panel_entry_checkpoint() == checkpoint3
      and restored.panel_passport_history[0].passport == snapshot3.passport, "Redis roundtrip")
legacy = session_from_dict({"session_id": "legacy-cert"})
check("O24i", legacy.panel_passport_history == [] and legacy.panel_entry_checkpoints == [], "backcompat старых документов")
session9 = make_session(df_u2)
confirm(session9, df_u2)
session9.set_dataset(DatasetInfo(dataset_id="ds-new", name="new", rows=10, columns=4,
                                 size_label="1 KB", dataset_fingerprint="fp-new"), df_u2.iloc[:0])
check("O24k", session9.panel_passport_history == [] and session9.panel_entry_checkpoints == [],
      "set_dataset чистит панельную вселенную (новый датасет)")
check("O24j", PASSPORT_STAGES == ("start", "validation", "exit", "modeling_entry")
      and PASSPORT_CHECKPOINT_STAGES == ("modeling_entry",), "однорядные константы не тронуты")

# ── O25: гейт build_panel_modeling_context ──────────────────────────────────
session4 = make_session(df_u2)
try:
    build_panel_modeling_context(session4, **PARAMS_FULL)
    check("O25a", False, "гейт без checkpoint пропустил")
except ValueError as error:
    check("O25a", isinstance(error, ValueError) and "panel_entry" in str(error) and "modeling_entry" not in str(error), str(error))
confirm(session4, df_u2)
context = build_panel_modeling_context(session4, **PARAMS_FULL)
check("O25b", context["fingerprint"] == panel_fingerprint(df_u2, **PARAMS_FULL)
      and context["checkpoint"]["stage"] == "panel_entry"
      and context["passport"]["n_entities"] == 6, "свежий checkpoint проходит")
changed = df_u2.copy()
changed.loc[0, "target"] = changed.loc[0, "target"] + 123.0
session4.set_dataframe(changed, reason="cert-mutation")
try:
    build_panel_modeling_context(session4, **PARAMS_FULL)
    check("O25c", False, "истечение не сработало")
except ValueError as error:
    check("O25c", isinstance(error, ValueError) and "устарел" in str(error), str(error))
session5 = make_session(df_u2)
confirm(session5, df_u2)
try:
    build_panel_modeling_context(session5, date_column="date", entity_column="entity",
                                 value_columns=["target"], target_column="target")
    check("O25d", False, "смена состава колонок прошла")
except ValueError as error:
    check("O25d", isinstance(error, ValueError) and "Состав колонок" in str(error), str(error))
try:
    build_panel_modeling_context(session5, date_column="date", entity_column="entity",
                                 value_columns=["exog", "target"], target_column="target")
    check("O25e", False, "перестановка value_columns прошла как совпадение")
except ValueError as error:
    check("O25e", isinstance(error, ValueError) and "Состав колонок" in str(error), "порядок состава честно сверяется")
broken_df = df_u2.drop(columns=["exog"])
session5.set_dataframe(broken_df, reason="cert-drop")
try:
    build_panel_modeling_context(session5, **PARAMS_FULL)
    check("O25f", False, "PanelContractError не обёрнут")
except ValueError as error:
    check("O25f", isinstance(error, ValueError) and "Панель не проходит контракт" in str(error), str(error))
shuffled = df_u2.sample(frac=1, random_state=11).reset_index(drop=True)
session6 = make_session(df_u2)
confirm(session6, df_u2)
session6.set_dataframe(shuffled, reason="cert-shuffle")
expected_fp = panel_fingerprint(df_u2, **PARAMS_FULL)
ctx_g = build_panel_modeling_context(session6, **PARAMS_FULL)
check("O25g", ctx_g["fingerprint"] == expected_fp, "перестановка строк НЕ истекает checkpoint (порядок-инвариантность)")
import apps.api.modeling_workflow as mw  # noqa: E402
from app.core import passport as passport_module  # noqa: E402


def _boom(*args, **kwargs):
    raise AssertionError("панельный контур вызвал prepare_passport_series")


original_prepare = passport_module.prepare_passport_series
original_mw_prepare = mw.prepare_passport_series
passport_module.prepare_passport_series = _boom
mw.prepare_passport_series = _boom
try:
    ctx_h = build_panel_modeling_context(session6, **PARAMS_FULL)
    check("O25h", ctx_h["passport"]["n_entities"] == 6, "R4: prepare_passport_series не вызывается")
except AssertionError as error:
    check("O25h", False, str(error))
finally:
    passport_module.prepare_passport_series = original_prepare
    mw.prepare_passport_series = original_mw_prepare

# ── O26: числовые id сущностей ──────────────────────────────────────────────
numeric_rows = []
for i in (1, 2, 3):
    for day in range(6):
        numeric_rows.append({"entity": i, "date": pd.Timestamp("2024-08-01") + pd.Timedelta(days=day),
                             "target": float(10 * i + day), "exog": float(day)})
frame_numeric = build_panel_frame(pd.DataFrame(numeric_rows), **PARAMS_FULL)
check("O26a", frame_numeric.n_entities == 3 and set(frame_numeric.nan_profile) == {"1", "2", "3"},
      f"числовые сущности -> строковые ключи nan_profile: {set(frame_numeric.nan_profile)}")
dummies_num = entity_dummies(pd.DataFrame(numeric_rows), entity_column="entity", drop_first=False)
check("O26b", list(dummies_num.columns) == ["1", "2", "3"], f"строковые dummy-колонки: {list(dummies_num.columns)}")

# ── Итог ────────────────────────────────────────────────────────────────────
total = len(RESULTS)
passed = sum(1 for _, status, _ in RESULTS if status == "PASS")
print("\n===== ORACLE PROTOCOL =====")
for oracle, status, detail in RESULTS:
    if status == "FAIL":
        print(f"FAIL {oracle}: {detail}")
print(f"TOTAL={total} PASS={passed} FAIL={total - passed}")
sys.exit(0 if passed == total else 1)
