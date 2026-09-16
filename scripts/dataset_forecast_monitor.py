#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Синтетический датасет для мониторинга модуля «Прогнозирование» без нейро-моделей.

ВЕРСИЯ 2 (2026-09-16, FC-MON-2): по запросу тимлида добавлены НЕСКОЛЬКО
ВЫБРОСОВ (4: три спайка + один глубокий провал) и НЕСКОЛЬКО ПРОПУСКОВ (3)
-- «настоящесть» данных; датасет размещён ПЕРВЫМ в демо-карточках
вкладки «Загрузка» (пакет packages/ui/lib/demoDatasets.ts, генератор
generateForecastMonitor -- зеркал этого скрипта).

ПОСТАНОВКА (тимлид): нужен синтетический датасет, который в модуле
«Моделирование» фильтром «Применение» ЧЕСТНО не пропускается в отбор
«Для текущего ряда» для нейросетевых моделей (в частности, LSTM).
Причина -- ограничение render.com free tier по памяти (512 MB): импорт
torch+neuralforecast занимает ~606 MB (Task 138c), нейро-бэктест на
free-инстансе честно отвечает 503. Миграция на корпоративный сервер
отменит ограничение; до того мониторинг «Прогнозирования» должен идти
на не-нейронных моделях.

МЕХАНИЗМ БЛОКИРОВКИ -- реальные правила applicability-движка
rules/modeling.yaml (не обходные пути):

  F04 (forbidden -> NOT_APPLICABLE): n_observations < model.min_observations.
      У ВСЕХ 5 нейро-моделей каталога (lstm/tft/nbeats/nhits/deepar)
      min_observations = 200. Датасет на 150 наблюдений даёт каждому из
      них NOT_APPLICABLE с сообщением «Недостаточно данных: 150 < 200».
      LSTM специфичен: requires_gpu=false, поэтому D06 (DL без GPU) его
      НЕ ловит; D02 (n<300) даёт только мягкий NOT_RECOMMENDED. F04 --
      единственный жёсткий честный блок для LSTM, и он же накрывает всю
      пятёрку единым правилом.
  F02: garch/egarch (domain=financial) на данных domain=other -- NOT_APPLICABLE
      (заодно исключает тяжёлые volatility-импорты).
  D03: tree_ml без feature engineering -- NOT_RECOMMENDED (вне пула).
  D05: tbats при n<200 -- NOT_RECOMMENDED (вне пула, заодно скорость).
  F01: var/vecm/deepar при n_series=1 -- NOT_APPLICABLE. ВАЖНО (проверено
      верификацией): правила исполняются предопределёнными handlers в
      modeling_spec_loader._evaluate_rule (YAML-условия декларативны);
      F01-handler имеет fallback model.min_series > 1, поэтому F01
      срабатывает и при requires_multiple_series = None (ни одна модель
      не задаёт его явно). deepar получает F01 раньше F04 (порядок
      правил в списке forbidden) -- исход тот же: NOT_APPLICABLE.
      Расхождение текста YAML-условия и handler-логики зафиксировано в
      worklog6.md как кандидат-находка уровня документации.

ПАРАМЕТРЫ РЯДА (детерминированные, numpy default_rng(20260916)):
  150 месячных наблюдений 2013-01..2025-06 (freq=MS, is_regular=true);
  value = 120 + 0.55*t (тренд) + 18*sin(2*pi*(t+2)/12) (сезон M=12)
          + N(0, 3.2); значения положительные; колонки date,value.
  ВЫБРОСЫ (4, за IQR-заборами финального ряда, запас >= 9):
      t=25 +110, t=70 +105, t=105 +95 (спайки вверх),
      t=130 -135 (глубокий провал, остаётся > 0);
  ПРОПУСКИ (3): t=45, 87, 122 (пустая ячейка value, дата сохранена).
  После dropna паспорт видит n=147: < 200 -- F04 блокирует всю пятёрку
  нейро; >= 100 -- сохраняет каталог (arima/arima_auto/prophet/tbats/
  tree_ml min_obs<=100); outlier_ratio = 4/147 ~ 0.027 < 0.05.

  ПОСЛЕДСТВИЯ ПРОПУСКОВ (честное поведение платформы, отражено в
  верификации):
    * build_eda_model_matrix на сыром df возвращает applicable=False
      («цель содержит пропуски -- завершите предобработку»);
    * prepare_passport_series дропает NaN-строки -> индекс ряда получает
      разрывы дат -> паспорт честно «Нерегулярная», сезонность до
      Предобработки не подтверждается (merged seasonal_periods=[]);
    * ПРИ ЭТОМ пул «Для текущего ряда» ПОЛНЫЙ (10 не-нейронных, проверено
      движком), а бэктест получает чистые 147 точек (NaN не доходят до
      моделей), гейтов регулярности на /backtest нет -- быстрый
      мониторинг «Прогнозирования» работает и без Предобработки.
    * Датасет честно ведёт пользователя через Предобработку (устранение
      пропусков -> регулярность и сезонность восстанавливаются), что и
      требуется от «настоящего» демо-набора.

ВЕРИФИКАЦИЯ -- ТОЛЬКО реальный код платформы (верификация, не доверие;
никакой пере-имплементации логики):
  app.data.detectors.detect_and_convert_datetime / detect_column_frequency
  -> app.core.passport.prepare_passport_series / calculate_ts_passport
  -> apps.api.modeling_workflow.honest_system_profile /
     volatility_clustering_profile (та же сборка DataProfile, что в
     build_modeling_context)
  -> src.catalog.modeling_spec_loader.ModelingSpec (rules/modeling.yaml):
     resolve_all_applicability + get_candidate_pool.

Запуск из корня репозитория:
  python3 scripts/dataset_forecast_monitor.py [--out PATH]

Выход: CSV датасета + отчёт верификации (PASS/FAIL assert-цепочка).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from app.data.detectors import (
    detect_and_convert_datetime,
    detect_column_frequency,
)
from app.core.passport import calculate_ts_passport, prepare_passport_series
from apps.api.modeling_workflow import (
    honest_system_profile,
    volatility_clustering_profile,
)
from apps.api.eda_model_matrix import build_eda_model_matrix
from src.catalog.modeling_spec_loader import DataProfile, ModelingSpec
from apps.api.model_readiness import available_model_actions

# ── Параметры генерации (детерминизм) ─────────────────────────────────────
SEED = 20260916
N_OBS = 150                      # окно [100, 200): F04 нейро, >=100 каталог
START = "2013-01-01"
FREQ_CODE = "MS"                 # month-start; pd.infer_freq -> "MS"
BASE = 120.0                     # уровень ряда
TREND = 0.55                     # наклон тренда в месяц
SEASON_AMP = 18.0                # амплитуда годовой сезонности
SEASON_PHASE = 2                 # сдвиг фазы (пик ~ март)
NOISE_SIGMA = 3.2
# FC-MON-2: выбросы (индекс, дельта к локальной базовой линии) и пропуски.
# Дельты подобраны пробой (probe_outlier_design): за IQR-заборами
# ФИНАЛЬНОГО ряда с запасом >= 9; провал остаётся > 0. Зеркало --
# константы FORECAST_MONITOR_* в packages/ui/lib/demoDatasets.ts.
OUTLIERS: list[tuple[int, float]] = [
    (25, 110.0),   # спайк в начале
    (70, 105.0),   # спайк в первой трети (сезонная фаза ~0)
    (105, 95.0),   # спайк в середине
    (130, -135.0), # глубокий провал (остаётся > 0)
]
MISSING_T: list[int] = [45, 87, 122]
N_EFFECTIVE = N_OBS - len(MISSING_T)   # 147 -- n паспорта/профиля (dropna)
OUTLIER_RATIO_EXPECTED = round(len(OUTLIERS) / N_EFFECTIVE, 8)
NEURAL_IDS = {"lstm", "tft", "nbeats", "nhits", "deepar"}
EXPECTED_POOL = {
    "naive", "seasonal_naive", "drift", "mean",
    "ets", "ets_damped", "theta", "arima", "arima_auto", "prophet",
}
EXPECTED_BLOCKED = {
    "garch": "F02", "egarch": "F02",
    # var/vecm/deepar: F01 (n_series == 1 при min_series > 1 -- fallback
    # F01-handler'а; deepar получает F01 раньше F04 по порядку правил).
    "var": "F01", "vecm": "F01",
    # deepar проверяется отдельно: rule_id in {F01, F04} (порядок правил).
}


def generate_series() -> pd.DataFrame:
    """Детерминированный ряд: тренд + сезон M=12 + шум + выбросы + пропуски."""
    rng = np.random.default_rng(SEED)
    t = np.arange(N_OBS, dtype=float)
    value = (
        BASE
        + TREND * t
        + SEASON_AMP * np.sin(2.0 * np.pi * (t + SEASON_PHASE) / 12.0)
        + rng.normal(0.0, NOISE_SIGMA, N_OBS)
    )
    for idx, delta in OUTLIERS:
        value[idx] += delta
    dates = pd.date_range(START, periods=N_OBS, freq=FREQ_CODE)
    df = pd.DataFrame(
        {"date": dates.strftime("%Y-%m-%d"), "value": np.round(value, 2)}
    )
    # Пропуски ПОСЛЕ округления: пустая ячейка value при сохранной дате.
    df.loc[MISSING_T, "value"] = np.nan
    return df


def build_profile_from_platform(df: pd.DataFrame) -> tuple[DataProfile, dict]:
    """Профиль данных -- ТОЛЬКО реальным кодом платформы.

    Та же цепочка, что прод-путь Upload -> Passport -> Modeling context:
    датасет -> datetime-детекторы -> канонический ряд -> паспорт ->
    поля профиля по правилам build_modeling_context.
    """
    df_work, detected_cols, ts_active, date_col = detect_and_convert_datetime(df)
    freq_info = detect_column_frequency(df_work[date_col])
    series = prepare_passport_series(df_work, "value", date_col)
    passport = calculate_ts_passport(series)
    values = pd.Series(series.to_numpy(dtype=float))

    system = honest_system_profile(
        df_work, date_column=date_col, target_column="value"
    )
    # Мердж сезонных периодов В ТОЧНОМ порядке build_modeling_context:
    # spectral-выбор сессии (пусто до остановки «Спектр») -> матрица EDA
    # -> паспорт (спектр сырого ряда). ВЕРСИЯ 2: из-за пропусков матрица
    # честно not applicable (periods=[]), поэтому merged = паспортный
    # спектр; после Предобработки матрица снова подтвердит сезон.
    matrix = build_eda_model_matrix(
        df_work, "value", task="forecast", horizon=12,
        validation_strategy="expanding", n_splits=5, gap=0, train_window=60,
    )
    matrix_periods = list(matrix.get("profile", {}).get("seasonal_periods", []))
    passport_periods = [int(p) for p in
                        (passport.get("seasonal_periods", {}) or {}).get("periods", [])]
    seasonal_periods = [int(p) for p in
                        dict.fromkeys(matrix_periods + passport_periods)
                        if int(p) > 1]
    profile = DataProfile(
        n_observations=len(series),
        n_series=int(system.get("n_series", 1)),
        n_exogenous=0,
        is_regular=bool((passport.get("freq", {}) or {}).get("is_regular")),
        frequency=_frequency_alias((passport.get("freq", {}) or {}).get("value")),
        has_seasonality=bool((passport.get("seasonality", {}) or {}).get("is_seasonal")),
        seasonal_periods=seasonal_periods,
        is_stationary_or_diffable=bool(
            (passport.get("stationarity", {}) or {}).get("is_stationary")
        ),
        is_cointegrated=bool(system.get("is_cointegrated", False)),
        has_negative_values=bool((values < 0).any()),
        has_volatility_clustering=volatility_clustering_profile(values)["reject_null"],
        domain="other",
        missing_ratio=0.0,
        outlier_ratio=_iqr_outlier_ratio(values),
        has_holidays=False,
        gpu_available=False,
        feature_engineering_applied=False,
    )
    return profile, {
        "ts_active": ts_active, "date_col": date_col,
        "detected_cols": detected_cols, "freq_info": freq_info,
        "passport": passport, "system": system, "matrix": matrix,
    }


def _frequency_alias(value) -> str:
    """Копия логики apps/api/modeling_workflow._frequency_alias (2 строки,
    импорт модуля тянет FastAPI-зависимости eda_* -- здесь не нужны)."""
    raw = str(value or "").upper()
    if raw.startswith(("B", "C", "D")):
        return "D"
    if raw.startswith("W"):
        return "W"
    if raw.startswith(("M", "BM", "SM")):
        return "M"
    if raw.startswith(("Q", "BQ")):
        return "Q"
    if raw.startswith(("Y", "A")):
        return "Y"
    return raw or "other"


def _iqr_outlier_ratio(values: pd.Series) -> float:
    q1, q3 = np.quantile(values.to_numpy(dtype=float), [0.25, 0.75])
    iqr = q3 - q1
    if iqr <= np.finfo(float).eps:
        return 0.0
    count = int(((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).sum())
    return round(count / len(values), 8)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(Path("/home/z/my-project/download")
                    / f"forecast_monitor_synthetic_n{N_OBS}.csv"),
    )
    args = parser.parse_args()

    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {label}" + (f" -- {detail}" if detail else ""))
        if not ok:
            failures.append(f"{label}: {detail}")

    # ── 1. Генерация CSV ──────────────────────────────────────────────
    print("== 1. Генерация CSV ==")
    df = generate_series()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"  CSV: {out_path} ({out_path.stat().st_size} bytes)")

    # ── 2. Структурная верификация CSV ────────────────────────────────
    print("== 2. Структура CSV (детекторы платформы) ==")
    df_rt = pd.read_csv(out_path)
    check("shape == (150, 2)", df_rt.shape == (N_OBS, 2), str(df_rt.shape))
    check(f"ровно {len(MISSING_T)} пропуска, только в value",
          int(df_rt["value"].isna().sum()) == len(MISSING_T)
          and int(df_rt["date"].isna().sum()) == 0,
          f"value={int(df_rt['value'].isna().sum())}, "
          f"date={int(df_rt['date'].isna().sum())}")
    check("значения положительные (включая провал-выброс)",
          float(df_rt["value"].min()) > 0,
          f"min={df_rt['value'].min()}")
    dates = pd.to_datetime(df_rt["date"])
    inferred = pd.infer_freq(pd.DatetimeIndex(dates))
    check("регулярный месячный шаг (pd.infer_freq) -- даты при пропусках сохранены",
          inferred == "MS",
          f"inferred={inferred}; календарные месяцы имеют шаг 28–31 день,"
          f" поэтому сравнение в днях неприменимо")

    df_work, detected_cols, ts_active, date_col = detect_and_convert_datetime(df_rt)
    check("date-колонка распознана", ts_active and date_col == "date",
          f"date_col={date_col}, detected={detected_cols}")
    freq_info = detect_column_frequency(df_work[date_col])
    check("частота MS (месячная)", freq_info["code"] == "MS",
          f"{freq_info['selected']} (code={freq_info['code']})")

    # ── 3. Паспорт ряда (реальный calculate_ts_passport) ──────────────
    print("== 3. Паспорт ряда (после dropna пропусков) ==")
    series = prepare_passport_series(df_work, "value", date_col)
    check(f"n паспорта = {N_EFFECTIVE} (150 - {len(MISSING_T)} пропуска)",
          len(series) == N_EFFECTIVE, f"n={len(series)}")
    passport = calculate_ts_passport(series)
    freq_p = passport.get("freq", {}) or {}
    season_p = passport.get("seasonality", {}) or {}
    stat_p = passport.get("stationarity", {}) or {}
    spec_p = passport.get("seasonal_periods", {}) or {}
    check("is_regular = False -- ЧЕСТНО: даты пропусков выпали из индекса ряда",
          bool(freq_p.get("is_regular")) is False, str(freq_p))
    check("has_seasonality = False -- ЧЕСТНО: сезон на сетке с разрывами не подтверждается",
          bool(season_p.get("is_seasonal")) is False)
    check("is_stationary = False (тренд -- ожидаемо)",
          bool(stat_p.get("is_stationary")) is False)
    passport_periods = [int(p) for p in (spec_p.get("periods") or [])]
    print(f"  i  сезонные периоды паспорта: {passport_periods} "
          f"(спектр трендового ряда с выбросами -- информационно, не гейт)")

    # ── 4. Профиль данных (сборка как в build_modeling_context) ───────
    print("== 4. Профиль данных Modeling ==")
    profile, ctx = build_profile_from_platform(df_rt)
    values = pd.Series(series.to_numpy(dtype=float))
    system = honest_system_profile(df_work, date_column=date_col, target_column="value")
    check(f"n_observations = {N_EFFECTIVE} (dropna)",
          profile.n_observations == N_EFFECTIVE,
          f"n={profile.n_observations}")
    check("n_series = 1 (date + одна числовая)", profile.n_series == 1,
          str(system))
    check("frequency честно отражает нерегулярность (до Предобработки)",
          profile.frequency != "M",
          f"frequency={profile.frequency}")
    check("is_regular = False (до Предобработки)", profile.is_regular is False)
    check("has_seasonality = False (до Предобработки)",
          profile.has_seasonality is False)
    # Честное поведение платформы при пропусках (FC-MON-2): матрица EDA
    # на сыром df not applicable (пропуски -- зона Предобработки),
    # merged seasonal_periods = только паспортный спектр.
    matrix = ctx["matrix"]
    check("матрица EDA честно not applicable (пропуски)",
          matrix.get("applicable") is False
          and "пропуск" in str(matrix.get("reason", "")),
          f"applicable={matrix.get('applicable')}, "
          f"reason={matrix.get('reason')}")
    check("merged seasonal_periods = паспортным (матрица не подтвердила из-за пропусков)",
          profile.seasonal_periods == passport_periods,
          f"merged={profile.seasonal_periods}, паспорт={passport_periods}")
    check("has_negative_values = False", profile.has_negative_values is False)
    check("gpu_available = False", profile.gpu_available is False)
    check("feature_engineering_applied = False",
          profile.feature_engineering_applied is False)
    check(f"outlier_ratio = {OUTLIER_RATIO_EXPECTED} ({len(OUTLIERS)}/{N_EFFECTIVE}), < 0.05",
          profile.outlier_ratio == OUTLIER_RATIO_EXPECTED
          and profile.outlier_ratio < 0.05,
          str(profile.outlier_ratio))
    print(f"  i  профиль: seasonal_periods={profile.seasonal_periods} "
          f"(мердж: сессия(пусто) + матрица(пропуски->[]) + паспорт; "
          f"бэктест до Предобработки берёт [0]), "
          f"is_stationary_or_diffable={profile.is_stationary_or_diffable}, "
          f"volatility_clustering="
          f"{volatility_clustering_profile(values)['reject_null']} "
          f"(влияет только на P04 -- financial, не наш случай)")

    # ── 5. Применимость (реальный движок rules/modeling.yaml) ─────────
    print("== 5. Движок применимости (ModelingSpec) ==")
    spec = ModelingSpec.from_yaml(str(REPO_ROOT / "rules" / "modeling.yaml"))
    results = spec.resolve_all_applicability(profile)
    pool = spec.get_candidate_pool(profile)  # min_level по умолчанию

    print(f"  {'модель':<14} {'уровень':<26} {'правило':<8} в_пуле")
    pool_ids = {r.model_id for r in pool}
    for family in spec.families:
        for model in family.models:
            r = results[model.id]
            in_pool = "да" if model.id in pool_ids else "-"
            print(f"  {model.id:<14} {r.level:<26} {str(r.rule_id or '-'):<8} {in_pool}")

    print("== 6. ЦЕЛЕВЫЕ ассерты задачи ==")
    for model_id in sorted(NEURAL_IDS):
        r = results[model_id]
        # deepar: F01 срабатывает раньше F04 (порядок правил в forbidden),
        # т.к. min_series=5 > 1 -> fallback F01-handler'а. Исход тот же.
        expected_rules = {"F01", "F04"} if model_id == "deepar" else {"F04"}
        check(f"{model_id}: NOT_APPLICABLE ({'/'.join(sorted(expected_rules))})",
              r.level == "NOT_APPLICABLE" and r.rule_id in expected_rules,
              f"{r.level}/{r.rule_id}")
    for model_id, rule in EXPECTED_BLOCKED.items():
        r = results[model_id]
        check(f"{model_id}: NOT_APPLICABLE по {rule}",
              r.level == "NOT_APPLICABLE" and r.rule_id == rule,
              f"{r.level}/{r.rule_id}")
    neural_in_pool = sorted(pool_ids & NEURAL_IDS)
    check("в пуле «Для текущего ряда» нет нейро-моделей",
          not neural_in_pool, f"нейро в пуле: {neural_in_pool}")
    missing = sorted(EXPECTED_POOL - pool_ids)
    check("мониторинговое ядро в пуле (baselines+ETS+Theta+ARIMA+Prophet)",
          not missing, f"отсутствуют: {missing}")
    # Условная регистрация реестра (честный реестр↔dispatch-гейт): в ЛОКАЛЬНОМ
    # окружении без опциональных зависимостей prophet/tbats/нейро-группы
    # реестр содержит 15 backtest-моделей; в прод-образе (apps/api/Dockerfile:
    # requirements.txt с prophet==1.4.0 + requirements-neural.txt) все 24.
    # Поэтому: локально жёстко требуем backtest-действие у моделей без
    # опциональных зависимостей; prophet проверяем только на уровень пула.
    _OPTIONAL_DEP_MODELS = {"prophet", "tbats"} | NEURAL_IDS
    not_ready = [r.model_id for r in pool
                 if r.model_id not in _OPTIONAL_DEP_MODELS
                 and "backtest" not in (available_model_actions(r.model_id) or [])]
    check("кандидаты пула без опциональных зависимостей -- backtest в реестре",
          not not_ready, f"не готовы: {not_ready}")
    prophet_registered = "backtest" in (available_model_actions("prophet") or [])
    print(f"  i  prophet: backtest-действие реестра "
          f"{'зарегистрировано' if prophet_registered else 'не зарегистрировано ЛОКАЛЬНО (нет пакета prophet)'}; "
          f"в прод-образе Dockerfile ставит prophet==1.4.0 -- на Render")
    print(f"     мониторинг с prophet доступен (Task 124, сертифицирован).")

    lstm_msg = results["lstm"].message
    print(f"  i  сообщение LSTM: {lstm_msg}")
    check("сообщение LSTM содержит честный порог (147 < 200)",
          str(N_EFFECTIVE) in lstm_msg and "200" in lstm_msg, lstm_msg)

    # ── Итог ──────────────────────────────────────────────────────────
    print("=" * 68)
    if failures:
        print(f"ИТОГ: FAIL ({len(failures)} провалов)")
        for f in failures:
            print(f"  - {f}")
        return 1
    n_runnable = sum(r.level in {"RECOMMENDED", "CONDITIONALLY_APPLICABLE"}
                     for r in results.values())
    print(f"ИТОГ: PASS -- датасет годен для мониторинга «Прогнозирования».")
    print(f"  LSTM и нейро-пятёрка: NOT_APPLICABLE -- lstm/nbeats/nhits/tft по F04"
          f" ({N_EFFECTIVE} < 200), deepar по F01 (n_series=1 < min_series=5).")
    print(f"  Реализм (FC-MON-2): {len(OUTLIERS)} выброса + {len(MISSING_T)} пропуска; "
          f"до Предобработки паспорт честно «Нерегулярная», матрица EDA "
          f"not applicable -- при этом пул и бэктест полностью рабочие.")
    print(f"  Пул «Для текущего ряда»: {len(pool)} моделей "
          f"(из {n_runnable} не-NOT_APPLICABLE в каталоге).")
    print(f"  Покрытие ci_method: empirical_oof_quantile (baselines), "
          f"analytic (arima/theta), parametric_simulation (ets), "
          f"native_adapter (prophet).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
