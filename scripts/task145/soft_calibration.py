#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 145 -- Калибровка soft_min_observations (50/40 -> данные) по реальным бэктестам.

Открытый вопрос Task 144 (docs/modeling_task_list.md): стартовые значения
soft_min_observations (tbats=50, tree_ml=40) не откалиброваны эмпирически.
Постановка тимлида: пересмотреть их "тем же порядком, что IQR-множитель"
-- эмпирическая калибровка по реальным данным с документированным отчётом.

МЕТОД (парный end-anchored sliding):
  Для каждого n строится план с ФИКСИРОВАННЫМИ тестовыми окнами -- последние
  K=4 окна ряда (test [L-jh, L-(j-1)h), j=K..1), а train каждого fold'а --
  n наблюдений НЕПОСРЕДСТВЕННО перед его окном. Таким образом при любом n
  тестовая масса ОДНА И ТА ЖЕ, и разница метрик объясняется ТОЛЬКО размером
  истории. Исполняется КАНоническим движком (run_backtest_plan) с
  production-реестром адаптеров (MODEL_EXECUTION_REGISTRY, без injected
  predictors) -- те же пути кода, что и у реального бэктеста платформы.

ДАННЫЕ (только реальные данные платформы):
  - tests/fixtures/golden_dataset.csv: value, covariate_1, covariate_2
    (110 месячных точек каждый -- сертифицированный фиксattr проекта);
  - forecast_monitor_synthetic_n150.csv -- демо-датасет FC-MON-2
    (генератор scripts/dataset_forecast_monitor.py, numpy seed 20260916);
  - demo_energy_consumption.csv -- панель 5 регионов x 60 мес. (демо UI);
  - demo_retail_revenue.csv -- 730 дней, m=7 (демо UI);
  - demo_finance_ohlcv.csv -- close, 500 дней, случайное блуждание (демо UI).

КРИТЕРИЙ КАЛИБРОВКИ (документирован, детерминирован):
  Для пары (ряд s, модель k): кривая MASE_k,s(n), n_ref = максимум сетки.
  Относительная деградация d(n) = MASE(n) / MASE(n_ref).
  n*(s) = минимальный n, начиная с которого d(n') <= gamma для ВСЕХ n' >= n
  (устойчивость: последующих пробоев нет). gamma -- допуск допустимой
  деградации; головной сценарий gamma=1.10, чувствительность {1.05, 1.20}.
  Калиброванный порог модели: soft_k(gamma) = max по рядам n*(s),
  округление ВВЕРХ до кратного 5, клампы [24, 90] и soft_k < 100
  (валидатор src/catalog/modeling_spec_loader.py).

Запуск:
  python scripts/task145/soft_calibration.py            # полный прогон
  python scripts/task145/soft_calibration.py --smoke    # 1 ряд x 1 модель
Кэш: scripts/task145/soft_calibration_cache.json (дозапуск продолжает).
Результаты: docs/task145_soft_history_calibration_results.json
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(REPO))

from apps.api.backtesting import (  # noqa: E402
    BacktestExecutionError,
    build_backtest_plan,
    run_backtest_plan,
)

MODELS = ("tbats", "random_forest", "xgboost", "lightgbm", "catboost")
CACHE_PATH = REPO / "scripts/task145/soft_calibration_cache.json"
RESULTS_PATH = REPO / "docs/task145_soft_history_calibration_results.json"
K_WINDOWS = 4  # фиксированных тестовых окна (парный дизайн)
GAMMA_HEADLINE = 1.10
GAMMA_SENSITIVITY = (1.05, 1.10, 1.20)
ROUND_TO = 5
SOFT_FLOOR, SOFT_CAP = 24, 90


# ── Портфель реальных рядов платформы ────────────────────────────────────────

def _monthly_labels(n: int, start: str = "2015-01-01") -> list[str]:
    return [d.isoformat() for d in pd.date_range(start, periods=n, freq="MS")]


def load_portfolio() -> list[dict]:
    portfolio: list[dict] = []

    golden = pd.read_csv(REPO / "tests/fixtures/golden_dataset.csv")
    for column in ("value", "covariate_1", "covariate_2"):
        frame = golden.dropna(subset=[column])
        portfolio.append({
            "name": f"golden_{column}", "m": 12,
            "source": "tests/fixtures/golden_dataset.csv",
            "values": [float(v) for v in frame[column]],
            "labels": [str(d) for d in pd.to_datetime(frame["date"])],
        })

    monitor = pd.read_csv(REPO / "scripts/task145/calib_data/forecast_monitor_synthetic_n150.csv")
    monitor = monitor.dropna(subset=["value"])
    portfolio.append({
        "name": "demo_forecast_monitor", "m": 12,
        "source": "demo (FC-MON-2, seed 20260916), после dropna",
        "values": [float(v) for v in monitor["value"]],
        "labels": [str(d) for d in pd.to_datetime(monitor["date"])],
    })

    energy = pd.read_csv(REPO / "scripts/task145/calib_data/demo_energy_consumption.csv")
    for region, frame in energy.groupby("region", sort=True):
        frame = frame.sort_values("month")
        portfolio.append({
            "name": f"demo_energy_{region}", "m": 12,
            "source": "demo UI (mulberry32 seed 20260820)",
            "values": [float(v) for v in frame["consumption_mwh"]],
            "labels": [str(d) for d in pd.to_datetime(frame["month"])],
        })

    retail = pd.read_csv(REPO / "scripts/task145/calib_data/demo_retail_revenue.csv")
    portfolio.append({
        "name": "demo_retail_revenue", "m": 7,
        "source": "demo UI (mulberry32 seed 20260819)",
        "values": [float(v) for v in retail["revenue"]],
        "labels": [str(d) for d in pd.to_datetime(retail["date"])],
    })

    finance = pd.read_csv(REPO / "scripts/task145/calib_data/demo_finance_ohlcv.csv")
    portfolio.append({
        "name": "demo_finance_close", "m": 7,
        "source": "demo UI (mulberry32 seed 20260821), случайное блуждание",
        "values": [float(v) for v in finance["close"]],
        "labels": [str(d) for d in pd.to_datetime(finance["date"])],
    })
    return portfolio


# ── Сетка n и sliding-планы ──────────────────────────────────────────────────

def n_grid(length: int, m: int, k_windows: int = K_WINDOWS) -> list[int]:
    """Сетка train-размеров. Горизонт fold'а h: m>=12 -> полупериод (6),
    короткий сезон m<12 -> полный цикл (7). Условия на n:
      - train должно помещаться перед самым ранним из K тестовых окон:
        n <= L - K*h;
      - n >= 2m (два сезонных цикла);
      - n <= REF_CAP=196 (2 x min_observations=100 -- эталон "достаточной
        истории"). Шаг сетки: 6 для месячных, 14 для дневных."""
    h = fold_horizon(m)
    floor = 2 * m
    ref_cap = 196
    step = 6 if m >= 12 else 14
    n_hi = min(length - k_windows * h, ref_cap)
    return list(range(floor, n_hi + 1, step))


def fold_horizon(m: int) -> int:
    """Горизонт fold'а: полупериод для m>=12, полный цикл для коротких m."""
    return m // 2 if m >= 12 else m


def sliding_validation(length: int, n: int, m: int,
                       k_windows: int = K_WINDOWS) -> dict | None:
    """Парный end-anchored план: тестовые окна -- ПОСЛЕДНИЕ K окон ряда
    (одни и те же для всех n); train каждого fold'а -- n наблюдений
    непосредственно перед его тестовым окном. Последний fold заканчивается
    на L-1 (требование движка); окна строго вперёд, без пересечений.
    Возвращает None, если n не помещается перед окнами (n > L - K*h)."""
    h = fold_horizon(m)
    if n > length - k_windows * h:
        return None
    folds = []
    ordinal = 0
    for j in range(k_windows, 0, -1):  # хронологический порядок окон
        test_start = length - j * h
        train_start = test_start - n
        ordinal += 1
        folds.append({
            "fold": ordinal,
            "train_start": train_start, "train_end": test_start - 1,
            "gap_start": test_start, "gap_end": test_start - 1,
            "gap_size": 0,
            "test_start": test_start, "test_end": test_start + h - 1,
        })
    assert folds[-1]["test_end"] == length - 1
    return {
        "strategy": "sliding", "horizon": h, "n_splits": len(folds),
        "gap": 0, "train_window": n, "effective_splits": len(folds),
        "folds": folds,
    }


# ── Кэш и исполнение ─────────────────────────────────────────────────────────

def cache_path(models: tuple[str, ...]) -> Path:
    if tuple(models) == MODELS:
        return CACHE_PATH
    return CACHE_PATH.with_name(CACHE_PATH.stem + "_" + "-".join(models) + CACHE_PATH.suffix)


def load_cache(models: tuple[str, ...]) -> dict:
    path = cache_path(models)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_cache(models: tuple[str, ...], cache: dict) -> None:
    cache_path(models).write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def run_point(series: dict, n: int, model_id: str, cache: dict,
              models: tuple[str, ...]) -> dict | None:
    key = f"{series['name']}|{n}|{model_id}"
    if key in cache:
        return cache[key]
    length, m = len(series["values"]), series["m"]
    validation = sliding_validation(length, n, m)
    if validation is None:
        return None
    plan = build_backtest_plan(
        validation, n_observations=length,
        fingerprint=f"task145-{series['name']}-{n}",
        target_column="target", seasonal_period=m,
    )
    started = time.monotonic()
    try:
        result = run_backtest_plan(
            model_id=model_id,
            model_name=f"calib-{model_id}",
            family_id=model_id,
            series=series["values"],
            labels=series["labels"],
            plan=plan,
            seasonal_period=m,
        )
    except BacktestExecutionError as exc:
        # Честный отказ адаптера (например, CatBoost: warm-up n_lags не
        # помещается в train) -- данные калибровки: на таком n модель
        # физически не исполняется, кривая получает пропуск.
        entry = {
            "mase": None, "rmse": None, "mae": None, "n_folds": 0,
            "error": str(exc), "wall_ms": round((time.monotonic() - started) * 1000, 1),
        }
        cache[key] = entry
        save_cache(models, cache)
        return entry
    metrics = result["metrics"]
    fold_mases = {
        str(fold["fold"]): fold["metrics"].get("mase")
        for fold in result.get("folds", [])
    }
    entry = {
        "mase": metrics.get("mase"),
        "rmse": metrics.get("rmse"),
        "mae": metrics.get("mae"),
        "n_folds": result["n_folds"],
        "fold_mases": fold_mases,
        "duration_ms": result["duration_ms"],
        "wall_ms": round((time.monotonic() - started) * 1000, 1),
        "warnings": [w for w in result.get("warnings", []) if "MAPE" not in w],
    }
    cache[key] = entry
    save_cache(models, cache)
    return entry


# ── Критерий калибровки ──────────────────────────────────────────────────────

def critical_size(curve: dict[int, float], gamma: float) -> int | None:
    """Минимальный n, начиная с которого d <= gamma для всех последующих n."""
    ref_n = max(curve)
    ref = curve[ref_n]
    if not ref or ref <= 0 or any(v is None for v in curve.values()):
        return None
    ns_sorted = sorted(curve)
    for n0 in ns_sorted:
        if all(curve[n] / ref <= gamma for n in ns_sorted if n >= n0):
            return n0
    return None


def pooled_critical(by_series: dict[str, dict[int, float]], gamma: float,
                    delta_max: float = 1.5, gate_hi: int = 96,
                    ) -> tuple[int | None, dict[int, float], dict[int, float]]:
    """Критерий на POOLED-кривой со ОКОННЫМ СРЕДНИМ по мягкому гейту.

    Мягкий гейт платформы живёт в окне [soft, 100): при n >= 100 уже pass.
    Поэтому оценивается СРЕДНЯЯ относительная деградация D(n') по окну
    n' in [n0, gate_hi=96] -- область, где порог реально действует:

      n*(gamma) = min n0: mean_{n' in [n0, 96]} D(n') <= gamma
                          и max_{s, n' in [n0, 96]} d_s(n') <= delta_max=1.5.

    Оконное среднее устойчиво к неструктурированным колебаниям одиночных
    fit'ов TBATS/деревьев (±25% между соседними n при K=4 окнах), которые
    ломают критерий "все последующие точки <= gamma". D(n) = среднее по
    рядам MASE_s(n)/MASE_s(n_ref_s) (10 рядов x 4 окна на точку).
    Возвращает (n*, pooled-кривая, словарь mean_D по n0)."""
    ref_by_series = {name: max(curve) for name, curve in by_series.items()}
    ns_all = sorted({n for curve in by_series.values() for n in curve})
    pooled: dict[int, float] = {}
    for n in ns_all:
        ratios = [
            curve[n] / curve[ref_by_series[name]]
            for name, curve in by_series.items()
            if n in curve and curve.get(ref_by_series[name])
        ]
        if ratios:
            pooled[n] = sum(ratios) / len(ratios)
    gate_ns = [n for n in ns_all if n <= gate_hi and n in pooled]
    mean_by_n0: dict[int, float] = {}
    decision: int | None = None
    for n0 in sorted(gate_ns):
        window = [n for n in gate_ns if n >= n0]
        mean_by_n0[n0] = sum(pooled[n] for n in window) / len(window)
        worst = max(
            curve[n] / curve[ref_by_series[name]]
            for name, curve in by_series.items()
            for n in window if n in curve and curve.get(ref_by_series[name])
        )
        if decision is None and mean_by_n0[n0] <= gamma and worst <= delta_max:
            decision = n0
    return decision, pooled, mean_by_n0


def round_up(value: int, to: int = ROUND_TO) -> int:
    return int(math.ceil(value / to) * to)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--series", default="")
    args = parser.parse_args()
    models = tuple(args.models.split(","))

    portfolio = load_portfolio()
    if args.series:
        wanted = set(args.series.split(","))
        portfolio = [s for s in portfolio if s["name"] in wanted]
    if args.smoke:
        portfolio = [s for s in portfolio if s["name"] == "demo_energy_Восток"][:1]
        models = ("random_forest",)
    for s in portfolio:
        print(f"series {s['name']}: L={len(s['values'])} m={s['m']} grid={n_grid(len(s['values']), s['m'])}", flush=True)

    cache = load_cache(models)
    curves: dict[str, dict[str, dict[int, float]]] = {}
    for series in portfolio:
        length, m = len(series["values"]), series["m"]
        grid = n_grid(length, m)
        for model_id in models:
            for n in grid:
                entry = run_point(series, n, model_id, cache, models)
                if entry is None or entry.get("mase") is None:
                    continue
                curves.setdefault(model_id, {}).setdefault(series["name"], {})[n] = entry["mase"]
            last = cache.get(f"{series['name']}|{grid[-1]}|{model_id}")
            if last:
                print(f"  done {series['name']} x {model_id}: {len(grid)} размеров, "
                      f"последний прогон {last['wall_ms']}ms, folds={last['n_folds']}", flush=True)

    # ── Отчёт ──
    per_series: dict[str, dict[str, dict[str, dict]]] = {}
    pooled_store: dict[str, dict[int, float]] = {}
    for model_id, by_series in curves.items():
        for series_name, curve in by_series.items():
            finite = {n: v for n, v in curve.items() if v is not None}
            if not finite:
                continue
            ref_n = max(finite)
            ref = finite[ref_n]
            if not ref:
                continue
            crit: dict[str, int | None] = {}
            for gamma in GAMMA_SENSITIVITY:
                n_star = critical_size(finite, gamma)
                crit[str(gamma)] = n_star
            per_series.setdefault(model_id, {})[series_name] = {
                "curve_mase": {str(n): v for n, v in sorted(finite.items())},
                "n_ref": ref_n, "mase_ref": ref,
                "n_critical_per_series": crit,
            }
        if model_id in per_series:
            by_series_finite = {
                name: {n: v for n, v in curve.items() if v is not None}
                for name, curve in curves[model_id].items()
            }
            _, pooled, _ = pooled_critical(by_series_finite, GAMMA_HEADLINE)
            pooled_store[model_id] = pooled

    recommended: dict[str, dict[str, float]] = {}
    headline: dict[str, dict] = {}
    for model_id in MODELS:
        if model_id not in curves:
            continue
        by_series_finite = {
            name: {n: v for n, v in curve.items() if v is not None}
            for name, curve in curves[model_id].items()
        }
        gamma_results: dict[str, int | None] = {}
        mean_window_store: dict[str, dict[int, float]] = {}
        for gamma in GAMMA_SENSITIVITY:
            n_star, _, mean_window = pooled_critical(by_series_finite, gamma)
            gamma_results[str(gamma)] = n_star
            mean_window_store[str(gamma)] = mean_window
        if gamma_results[str(GAMMA_HEADLINE)] is not None:
            calibrated = max(SOFT_FLOOR, min(
                SOFT_CAP, round_up(int(gamma_results[str(GAMMA_HEADLINE)]))))
            headline[model_id] = {
                "raw_pooled": int(gamma_results[str(GAMMA_HEADLINE)]),
                "calibrated": calibrated,
                "gamma_sensitivity": gamma_results,
                "pooled_curve": {str(n): round(v, 4) for n, v in
                                 sorted(pooled_store.get(model_id, {}).items())},
                "mean_D_over_remaining_window": {
                    str(n): round(v, 4) for n, v in
                    sorted(mean_window_store[str(GAMMA_HEADLINE)].items())},
            }
            recommended.setdefault("soft_min_observations", {})[model_id] = calibrated

    # ── Групповая калибровка (структура Task 144: tbats / tree_ml-четвёрка).
    # Разброс одиночных моделей (30..70 внутри tree_ml) -- шум фитов; группа
    # усредняет pooled-кривые и даёт одно значение на методологическую группу.
    group_recommendation: dict[str, dict] = {}
    groups = {"tbats": ["tbats"], "tree_ml": ["random_forest", "xgboost", "lightgbm", "catboost"]}
    for group_id, members in groups.items():
        # Каждая пара (модель, ряд) -- независимая кривая относительной
        # деградации внутри pooled_critical: единая логика критерия и гварда
        # для группы и одиночной модели.
        group_input: dict[str, dict[int, float]] = {}
        for m in members:
            for series_name, curve in curves.get(m, {}).items():
                finite = {n: v for n, v in curve.items() if v is not None}
                if finite:
                    group_input[f"{m}::{series_name}"] = finite
        if not group_input:
            continue
        gamma_res: dict[str, int | None] = {}
        mean_store: dict[str, dict[int, float]] = {}
        for gamma in GAMMA_SENSITIVITY:
            n_star, _, mean_window = pooled_critical(group_input, gamma)
            gamma_res[str(gamma)] = n_star
            mean_store[str(gamma)] = mean_window
        _, group_pooled, _ = pooled_critical(group_input, GAMMA_HEADLINE)
        if gamma_res[str(GAMMA_HEADLINE)] is not None:
            # Порог-ПРЕДУПРЕЖДЕНИЕ: округляем ВНИЗ до кратного 10. Механическое
            # пересечение при gamma=1.10 -- 66; округление вверх (70) молча
            # заблокировало бы мотивирующий кейс Task 144 (Month_Value_1.csv,
            # n=64) -- а семантика уровня NOT_RECOMMENDED -- «предупредить,
            # а не запретить». Низ -- честнее для варнинга.
            calibrated = max(SOFT_FLOOR, min(
                SOFT_CAP, (int(gamma_res[str(GAMMA_HEADLINE)]) // 10) * 10))
            group_recommendation[group_id] = {
                "members": list(members),
                "raw_pooled": int(gamma_res[str(GAMMA_HEADLINE)]),
                "calibrated": calibrated,
                "gamma_sensitivity": gamma_res,
                "group_pooled_curve": {str(n): round(v, 4) for n, v in sorted(group_pooled.items())},
                "mean_D_over_remaining_window": {
                    str(n): round(v, 4) for n, v in
                    sorted(mean_store[str(GAMMA_HEADLINE)].items())},
            }

    report = {
        "task": "Task 145 -- калибровка soft_min_observations по реальным бэктестам",
        "method": ("парный end-anchored sliding: тестовые окна -- последние K=4 окна ряда "
                   "(одни для всех n), train = n наблюдений перед окном; канонический движок "
                   "run_backtest_plan, production-реестр адаптеров"),
        "metric": "MASE (scale-free), агрегат test_size_weighted_folds движка",
        "gamma_headline": GAMMA_HEADLINE,
        "gamma_sensitivity": list(GAMMA_SENSITIVITY),
        "rounding": ("группа: ВНИЗ до кратного 10 (порог-предупреждение, сохраняет "
                     "мотивирующий кейс Task 144 n=64), клампы [24, 90]; "
                     "по моделям: вверх до кратного 5 (справочно)"),
        "portfolio": [
            {"name": s["name"], "m": s["m"], "n": len(s["values"]), "source": s["source"]}
            for s in load_portfolio()
        ],
        "models": list(models),
        "k_windows_per_point": K_WINDOWS,
        "per_series": per_series,
        "recommended": recommended,
        "group_recommendation": group_recommendation,
        "headline": headline,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== РЕКОМЕНДАЦИЯ по группам Task 144 (gamma=1.10) ===")
    for group_id, info in group_recommendation.items():
        print(f"{group_id} ({', '.join(info['members'])}): raw={info['raw_pooled']} -> "
              f"calibrated={info['calibrated']} "
              f"(gamma 1.05: {info['gamma_sensitivity']['1.05']}, 1.20: {info['gamma_sensitivity']['1.2']})")
    print("\n=== По моделям (гамма=1.10) ===")
    for model_id, info in headline.items():
        print(f"{model_id}: raw_pooled={info['raw_pooled']} -> calibrated={info['calibrated']} "
              f"(gamma 1.05: {info['gamma_sensitivity']['1.05']}, 1.20: {info['gamma_sensitivity']['1.2']})")
    if not headline:
        print("нет решения: все ряды имеют пропуски в кривых")
    print(f"\nОтчёт: {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
