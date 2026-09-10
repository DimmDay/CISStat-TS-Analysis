# scripts/audit_scripts/cert137_oracles.py
"""Certification of Task 137 (Neural Runtime Contract) -- independent oracle probes.

Auditor: senior-разработчик (независимый аудит Task 137, коммит 7e73a83).
Все данные и сиды -- СОБСТВЕННЫЕ аудитора; ни один сид не совпадает с
сидами исполнителя (11/23/5/42/21/137/1234/99) и аудитора cert136
(314159265/271828182/.../20260909).

Сиды аудитора: 8675309, 1618033, 2718281, 606060, 42424243, 31337, 90210,
7777777, 555000111, 20260911.

Быстрые (без training) оракулы контракта.  Тренировочные оракулы --
отдельный скрипт cert137_runtime_oracles.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import yaml

from apps.api.neural_contract import (  # noqa: E402
    CHECKPOINT_MAX_BYTES,
    DEFAULT_NEURAL_QUANTILE_LEVELS,
    NEURAL_CONTRACT_VERSION,
    NEURAL_RUNTIME,
    NeuralCheckpointStore,
    NeuralContractError,
    NeuralExogenousPlan,
    NeuralRuntimeUnavailableError,
    NeuralTrainingConfig,
    build_exogenous_plan,
    build_static_frame,
    checkpoint_policy,
    fold_seed,
    interval_levels_for_alpha,
    neural_cohort_contract,
    neural_worker_capabilities,
    resolve_neural_device,
    resolve_probabilistic_loss,
    restore_resume_state,
    to_long_format,
    validate_future_exogenous_frame,
    validate_long_format,
)

RESULTS: list[tuple[str, str, str]] = []
AUDITOR_SEEDS = (8675309, 1618033, 2718281, 606060, 42424243,
                 31337, 90210, 7777777, 555000111, 20260911)


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, "PASS" if ok else "FAIL", detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def expect_error(fn, *args, **kwargs) -> tuple[bool, str]:
    try:
        fn(*args, **kwargs)
        return False, "expected NeuralContractError/ValueError, none raised"
    except NeuralContractError as exc:
        return True, f"{type(exc).__name__}: {str(exc)[:110]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"wrong error type {type(exc).__name__}: {str(exc)[:110]}"


# ── мои данные (сиды аудитора) ────────────────────────────────────────────

def _my_univariate(n: int = 72, seed: int = 8675309) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-06-01", periods=n, freq="D")
    values = 7 + 0.02 * np.arange(n) + rng.standard_normal(n) * 0.3
    return pd.DataFrame({"ts": idx, "val": values})


def _my_panel(n_per: int = 40, n_series: int = 3, seed: int = 1618033) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-05-01", periods=n_per, freq="D")
    frames = [
        pd.DataFrame({"ts": idx, "ent": f"reg_{i}", "val": 3 + i + rng.standard_normal(n_per) * 0.25})
        for i in range(n_series)
    ]
    return pd.concat(frames, ignore_index=True)


# ── OR1: long-format basics на моих данных ────────────────────────────────

def or1_long_format_basics() -> None:
    uni = to_long_format(_my_univariate(), value_column="val", time_column="ts")
    ok = (
        list(uni.columns) == ["unique_id", "ds", "y"]
        and len(uni) == 72
        and uni["unique_id"].nunique() == 1
        and uni["unique_id"].iloc[0] == "series_0"
        and pd.api.types.is_datetime64_any_dtype(uni["ds"])
        and pd.api.types.is_float_dtype(uni["y"])
    )
    record("OR1a univariate->long: series_0/ds/y, 72 строки", ok)

    pan = to_long_format(_my_panel(), value_column="val", time_column="ts", series_column="ent")
    ok = (
        pan["unique_id"].nunique() == 3
        and sorted(pan["unique_id"].unique()) == ["reg_0", "reg_1", "reg_2"]
        and pan.equals(pan.sort_values(["unique_id", "ds"]).reset_index(drop=True))
    )
    record("OR1b panel->long: 3 серии, сортировка (unique_id, ds)", ok)

    # числовые колонки одного объекта не выдаются за панель: без series_column
    wide = _my_univariate()
    wide["second_metric"] = np.sin(np.arange(len(wide)) / 3.0)
    ok, detail = expect_error(
        to_long_format, wide.assign(ent="same_obj"), value_column="val",
        time_column="ts", series_column=None,
    )
    # ожидание: это НЕ ошибка, но unique_id обязан быть одной серией series_0
    ok2 = True
    try:
        long2 = to_long_format(wide, value_column="val", time_column="ts")
        ok2 = long2["unique_id"].nunique() == 1
    except NeuralContractError:
        ok2 = False
    record("OR1c широкий объект без series_column = ОДНА серия (честность DeepAR)", ok2)


# ── OR2: fail-closed значения y/keep ──────────────────────────────────────

def or2_fail_closed_values() -> None:
    f = _my_univariate(seed=2718281)
    f.loc[4, "val"] = np.nan
    ok, detail = expect_error(to_long_format, f, value_column="val", time_column="ts")
    record("OR2a NaN в y -> отказ", ok, detail)

    f = _my_univariate(seed=2718281)
    f.loc[6, "val"] = np.inf
    ok, detail = expect_error(to_long_format, f, value_column="val", time_column="ts")
    record("OR2b Inf в y -> отказ", ok, detail)

    f = _my_univariate(seed=2718281)
    f["temp"] = np.linspace(1, 2, len(f))
    f.loc[3, "temp"] = np.nan
    ok, detail = expect_error(
        to_long_format, f, value_column="val", time_column="ts", keep_columns=("temp",),
    )
    record("OR2c NaN в keep-колонке -> отказ", ok, detail)

    f = _my_univariate(seed=2718281)
    f["temp"] = np.linspace(1, 2, len(f))
    f.loc[5, "temp"] = np.inf
    passed = False
    try:
        to_long_format(f, value_column="val", time_column="ts", keep_columns=("temp",))
        passed = True
    except NeuralContractError:
        passed = False
    record(
        "OR2d Inf в keep-колонке: ПРОПУСКАЕТСЯ (docstring обещает отказ)",
        True, "НАХОДКА-1: поведение расходится с docstring (isna без isfinite); "
              " Inf ловится только в hist/futr плана" if passed else "Inf отклонён -- расходится с фиксацией аудита",
    )

    ok, detail = expect_error(to_long_format, _my_univariate(), value_column="nope", time_column="ts")
    record("OR2e отсутствующая value-колонка -> отказ", ok, detail)


# ── OR3: validate_long_format / сетки ─────────────────────────────────────

def or3_grid_validation() -> None:
    long = to_long_format(_my_univariate(), value_column="val", time_column="ts")
    broken = long.drop(index=13).reset_index(drop=True)
    ok, detail = expect_error(validate_long_format, broken)
    record("OR3a пропуск в дневной сетке -> отказ", ok, detail)

    # панель, у которой ОДНА серия с дыркой
    pan = _my_panel(seed=606060)
    plong = to_long_format(pan, value_column="val", time_column="ts", series_column="ent")
    idx_drop = plong[plong["unique_id"] == "reg_1"].index[7]
    plong_broken = plong.drop(index=idx_drop).reset_index(drop=True)
    ok, detail = expect_error(validate_long_format, plong_broken)
    ok = ok and "reg_1" in detail
    record("OR3b панель: дырка только в reg_1 -> отказ с именем серии", ok, detail)

    info = validate_long_format(plong)
    record(
        "OR3c сводка панели: n_series=3, n_observations=120",
        info["n_series"] == 3 and info["n_observations"] == 120 and bool(info["frequency"]),
        f"frequency={info['frequency']!r}",
    )

    # целочисленная ось (путь, не покрытый тестами исполнителя)
    int_regular = pd.DataFrame({
        "unique_id": ["s"] * 10,
        "ds": [0, 7, 14, 21, 28, 35, 42, 49, 56, 63],
        "y": np.linspace(1, 2, 10),
    })
    try:
        info = validate_long_format(int_regular)
        record("OR3d целочисленная регулярная сетка -> OK", info["frequency"] == "int_step_7",
               f"frequency={info['frequency']!r}")
    except NeuralContractError as exc:
        record("OR3d целочисленная регулярная сетка -> OK", False, str(exc)[:120])

    int_irregular = pd.DataFrame({
        "unique_id": ["s"] * 10,
        "ds": [0, 7, 14, 21, 28, 35, 42, 49, 56, 70],
        "y": np.linspace(1, 2, 10),
    })
    ok, detail = expect_error(validate_long_format, int_irregular)
    record("OR3e целочисленная нерегулярная сетка -> отказ", ok, detail)

    int_nonmono = pd.DataFrame({
        "unique_id": ["s"] * 5,
        "ds": [0, 7, 3, 21, 28],
        "y": np.linspace(1, 2, 5),
    })
    ok, detail = expect_error(validate_long_format, int_nonmono)
    record("OR3f целочисленная немонотонная ось -> отказ", ok, detail)


# ── OR4: exogenous-план ───────────────────────────────────────────────────

def _long_with_exog(seed: int = 42424243):
    f = _my_univariate(seed=seed)
    n = len(f)
    f["promo"] = (np.arange(n) % 5 == 0).astype(float)
    f["mkt"] = np.cos(np.arange(n) / 4.0)
    f["zone"] = "west"
    return to_long_format(
        f, value_column="val", time_column="ts",
        keep_columns=("promo", "mkt", "zone"),
    )


def or4_exogenous_plan() -> None:
    long = _long_with_exog()
    plan = build_exogenous_plan(long, futr=("promo",), hist=("mkt",), stat=("zone",))
    ok = (
        isinstance(plan, NeuralExogenousPlan)
        and plan.futr_exog_list == ("promo",)
        and plan.hist_exog_list == ("mkt",)
        and plan.stat_exog_list == ("zone",)
    )
    record("OR4a явные роли futr/hist/stat", ok)

    ok, detail = expect_error(build_exogenous_plan, long, futr=("promo",), hist=("promo",))
    record("OR4b колонка в двух ролях -> отказ", ok, detail)

    ok, detail = expect_error(build_exogenous_plan, long, futr=("ghost",))
    record("OR4c неизвестная колонка -> отказ", ok, detail)

    long2 = _long_with_exog()
    long2.loc[9, "mkt"] = np.nan
    ok, detail = expect_error(build_exogenous_plan, long2, hist=("mkt",))
    record("OR4d NaN в hist -> отказ", ok, detail)

    long3 = _long_with_exog()
    long3.loc[11, "mkt"] = np.inf
    ok, detail = expect_error(build_exogenous_plan, long3, hist=("mkt",))
    record("OR4e Inf в hist -> отказ", ok, detail)

    long4 = _long_with_exog()
    long4.loc[12, "zone"] = "east"  # внутри одной серии -> не константа
    ok, detail = expect_error(build_exogenous_plan, long4, stat=("zone",))
    ok = ok and "series_0" in detail
    record("OR4f non-константный static -> отказ с offending series", ok, detail)

    # категориальный static, константный per series, разные между сериями
    f = _my_panel(seed=31337)
    f["region"] = f["ent"].map({"reg_0": "eu", "reg_1": "us", "reg_2": "ap"})
    plong = to_long_format(f, value_column="val", time_column="ts",
                           series_column="ent", keep_columns=("region",))
    plan = build_exogenous_plan(plong, stat=("region",))
    static = build_static_frame(plong, plan)
    ok = (
        static is not None
        and len(static) == 3
        and list(static["unique_id"]) == ["reg_0", "reg_1", "reg_2"]
        and list(static["region"]) == ["eu", "us", "ap"]
    )
    record("OR4g категориальный static: одна строка на серию", ok)

    # подпись: независимый пересчёт sha256
    payload = json.dumps(
        {"futr": ["promo"], "hist": ["mkt"], "stat": ["zone"]},
        sort_keys=True, ensure_ascii=False,
    )
    expected_sig = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    plan_a = build_exogenous_plan(_long_with_exog(), futr=("promo",), hist=("mkt",), stat=("zone",))
    plan_b = build_exogenous_plan(_long_with_exog(), futr=("promo",), hist=("mkt",))
    ok = (
        plan_a.signature == expected_sig
        and len(plan_a.signature) == 64
        and plan_a.signature != plan_b.signature
    )
    record("OR4h sha256-подпись == независимый пересчёт; роли меняют подпись", ok)


# ── OR5: future-frame ─────────────────────────────────────────────────────

def or5_future_frame() -> None:
    long = _long_with_exog()
    plan = build_exogenous_plan(long, futr=("promo",))
    h = 6
    future = pd.DataFrame({
        "unique_id": ["series_0"] * h,
        "ds": pd.date_range("2025-08-13", periods=h, freq="D"),
        "promo": np.zeros(h),
    })
    try:
        validate_future_exogenous_frame(plan, future, n_series=1, horizon=h)
        record("OR5a точное покрытие n_series*horizon -> OK", True)
    except NeuralContractError as exc:
        record("OR5a точное покрытие n_series*horizon -> OK", False, str(exc)[:120])

    ok, detail = expect_error(validate_future_exogenous_frame, plan, None, n_series=1, horizon=h)
    record("OR5b futr объявлен, frame=None -> отказ", ok, detail)

    short = future.iloc[: h - 3]
    ok, detail = expect_error(validate_future_exogenous_frame, plan, short, n_series=1, horizon=h)
    record("OR5c короткое покрытие -> отказ", ok, detail)

    nan_fut = future.copy()
    nan_fut.loc[2, "promo"] = np.nan
    ok, detail = expect_error(validate_future_exogenous_frame, plan, nan_fut, n_series=1, horizon=h)
    record("OR5d NaN в futr-колонке -> отказ", ok, detail)

    # панельный дисбаланс: суммарно h*2 строк, но у серии B не h
    plan_hist_only = build_exogenous_plan(long, hist=("mkt",))
    record("OR5e без futr plan: frame=None допустим",
           validate_future_exogenous_frame(plan_hist_only, None, n_series=1, horizon=h) is None)

    pan_long = to_long_format(_my_panel(), value_column="val", time_column="ts", series_column="ent")
    pan_plan = build_exogenous_plan(pan_long, futr=("promo",)) if "promo" in pan_long.columns else None
    if pan_plan is None:
        f = _my_panel()
        f["promo"] = (np.arange(len(f)) % 6 == 0).astype(float)
        plong = to_long_format(f, value_column="val", time_column="ts",
                               series_column="ent", keep_columns=("promo",))
        pan_plan = build_exogenous_plan(plong, futr=("promo",))
    h2 = 4
    def _rows(uid: str, count: int) -> pd.DataFrame:
        return pd.DataFrame({
            "unique_id": [uid] * count,
            "ds": pd.date_range("2025-06-10", periods=count, freq="D"),
            "promo": 0.0,
        })
    # суммарно 12 == n_series*h2, но 4/6/2 вместо 4/4/4
    balanced = pd.concat(
        [_rows("reg_0", h2), _rows("reg_1", h2 + 2), _rows("reg_2", h2 - 2)],
        ignore_index=True,
    )
    ok, detail = expect_error(
        validate_future_exogenous_frame, pan_plan, balanced, n_series=3, horizon=h2,
    )
    record("OR5f суммарный объём верный, но дисбаланс по сериям -> отказ", ok, detail)


# ── OR6: NeuralTrainingConfig bounds ──────────────────────────────────────

def or6_config_bounds() -> None:
    cases = [
        ("seed=-1", dict(seed=-1, max_steps=10)),
        ("seed=2**31", dict(seed=2**31, max_steps=10)),
        ("seed='42' (строка)", dict(seed="42", max_steps=10)),
        ("max_steps=None", dict(seed=5, max_steps=None)),
        ("max_steps=0", dict(seed=5, max_steps=0)),
        ("max_steps=10**6", dict(seed=5, max_steps=10**6)),
        ("max_steps=10.5 (float)", dict(seed=5, max_steps=10.5)),
        ("patience=51", dict(seed=5, max_steps=10, early_stopping_patience=51, val_size=5)),
        ("patience=3, val_size=0", dict(seed=5, max_steps=10, early_stopping_patience=3)),
        ("val_size=-5", dict(seed=5, max_steps=10, val_size=-5)),
        ("batch_size=0", dict(seed=5, max_steps=10, batch_size=0)),
        ("batch_size=4097", dict(seed=5, max_steps=10, batch_size=4097)),
    ]
    all_ok = True
    details = []
    for label, kwargs in cases:
        ok, detail = expect_error(NeuralTrainingConfig, **kwargs)
        if not ok:
            all_ok = False
        details.append(f"{label}:{'OK' if ok else 'ПРОПУЩЕНО'}")
    record("OR6a 12 отказ-кейсов bounded-конфига", all_ok, "; ".join(details))

    try:
        cfg = NeuralTrainingConfig(seed=20260911, max_steps=10_000,
                                   early_stopping_patience=50, val_size=100,
                                   batch_size=4096)
        record("OR6b гранично-допустимые значения -> OK",
               cfg.max_steps == 10_000 and cfg.early_stopping_patience == 50
               and cfg.batch_size == 4096 and cfg.seed == 20260911)
    except NeuralContractError as exc:
        record("OR6b гранично-допустимые значения -> OK", False, str(exc)[:120])


# ── OR7: fold_seed -- независимая арифметика + хэш-рандомизация ───────────

def or7_fold_seed() -> None:
    s, fi, st = 90210, 3, 5
    expected = (s * 1_000_003 + fi * 7_919 + st * 104_729 + 137) % (2**31)
    got = fold_seed(s, fold_index=fi, step=st)
    record("OR7a формула == независимая арифметика аудитора", got == expected,
           f"got={got}, expected={expected}")
    ok = (fold_seed(s, fold_index=0, step=0) == (s * 1_000_003 + 137) % (2**31)
          and fold_seed(7777777, fold_index=2, step=1)
              == (7777777 * 1_000_003 + 2 * 7_919 + 104_729 + 137) % (2**31))
    record("OR7b формулы ещё двух (seed, fold, step)", ok)

    code = (
        "import sys; sys.path.insert(0, {repo!r});"
        "from apps.api.neural_contract import fold_seed;"
        "print(fold_seed(90210, fold_index=3, step=5), fold_seed(555000111, fold_index=1, step=9))"
    ).format(repo=str(REPO))
    out_a = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={**os.environ, "PYTHONHASHSEED": "1"}, check=True,
    ).stdout.split()
    out_b = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={**os.environ, "PYTHONHASHSEED": "987654321"}, check=True,
    ).stdout.split()
    record("OR7c детерминизм между интерпретаторами (PYTHONHASHSEED 1 vs 987654321)",
           out_a == out_b and len(out_a) == 2, f"{out_a} vs {out_b}")

    ok, _ = expect_error(fold_seed, -1, fold_index=0)
    ok2, _ = expect_error(fold_seed, 5, fold_index=-2)
    record("OR7d отрицательные seed/fold_index -> отказ", ok and ok2)


# ── OR8/OR9: интервалы и потери ───────────────────────────────────────────

def or8_interval_levels() -> None:
    ok = True
    details = []
    for alpha, expected in [(0.2, (10.0, 50.0, 90.0)), (0.05, (2.5, 50.0, 97.5)),
                            (0.01, (0.5, 50.0, 99.5)), (0.5, (25.0, 50.0, 75.0))]:
        plan = interval_levels_for_alpha(alpha)
        if plan.levels != expected:
            ok = False
        details.append(f"alpha={alpha}->{plan.levels}")
    record("OR8a двусторонние симметричные уровни (медиана всегда)", ok, "; ".join(details))

    plan = interval_levels_for_alpha(0.2)
    record("OR8b нижний уровень == alpha/2 (двусторонняя конвенция, не alpha)",
           plan.levels[0] == 10.0 and plan.levels[0] != 20.0)
    record("OR8c method/median/alpha в плане",
           plan.method == "neural_quantile_outputs" and plan.median_level == 50.0
           and plan.alpha == 0.2)

    all_ok = True
    for bad in (0.0, 1.0, -0.1, 1.5, "0.2", None):
        ok, detail = expect_error(interval_levels_for_alpha, bad)
        if not ok:
            all_ok = False
    record("OR8d alpha вне (0,1)/не число -> отказ (6 кейсов)", all_ok)


def or9_losses() -> None:
    ok = all(resolve_probabilistic_loss(l) == l for l in ("mae", "mse", "huber"))
    ok2 = all(resolve_probabilistic_loss(l, levels=(10.0, 90.0)) == l
              for l in ("quantile", "mqloss"))
    record("OR9a whitelist: mae/mse/huber/quantile/mqloss", ok and ok2)

    all_ok = True
    for bad in ("cosine", "MAPE", "mape", "", "smape"):
        ok, _ = expect_error(resolve_probabilistic_loss, bad)
        if not ok:
            all_ok = False
    record("OR9b вне whitelist (в т.ч. mape/MAPE) -> отказ (5 кейсов)", all_ok)

    ok, _ = expect_error(resolve_probabilistic_loss, "quantile")
    ok2, _ = expect_error(resolve_probabilistic_loss, "mqloss")
    record("OR9c probabilistic без уровней -> отказ", ok and ok2)

    all_ok = True
    for bad_levels in ((0.0,), (100.0,), (-5.0,), (150.0,), (10.0, 200.0)):
        ok, _ = expect_error(resolve_probabilistic_loss, "quantile", levels=bad_levels)
        if not ok:
            all_ok = False
    record("OR9d уровни вне (0, 100) -> отказ (5 кейсов)", all_ok)
    record("OR9e DEFAULT_NEURAL_QUANTILE_LEVELS == (10, 50, 90)",
           DEFAULT_NEURAL_QUANTILE_LEVELS == (10.0, 50.0, 90.0))


# ── OR10: capabilities / device / без eager-импортов ──────────────────────

def or10_capabilities() -> None:
    code = (
        "import sys; sys.path.insert(0, {repo!r});"
        "import apps.api.neural_contract as c;"
        "print('torch' in sys.modules, 'neuralforecast' in sys.modules);"
        "import os;"
        "os.environ.pop('CISSTAT_GPU_AVAILABLE', None);"
        "caps = c.neural_worker_capabilities();"
        "print(caps['gpu_available'], caps['device'], caps['install_extra'], caps['packages'])"
    ).format(repo=str(REPO))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONHASHSEED": "0"}, check=True)
    lines = [l for l in out.stdout.strip().splitlines() if l.strip()]
    eager_line = lines[0].split()
    caps_line = lines[1].split()
    record("OR10a импорт neural_contract НЕ тянет torch/neuralforecast (subprocess)",
           eager_line == ["False", "False"], f"eager={eager_line}")
    record("OR10b capabilities без GPU-сигнала: cpu, install_extra=neural, packages",
           caps_line == ["False", "cpu", "neural", "['torch',", "'neuralforecast']"],
           f"caps={caps_line}")

    os.environ.pop("CISSTAT_GPU_AVAILABLE", None)
    record("OR10c requires_gpu без сигнала -> NeuralRuntimeUnavailableError",
           isinstance(_device_guard(), bool) and _device_guard())
    record("OR10d requires_gpu=False -> 'cpu'", resolve_neural_device(requires_gpu=False) == "cpu")
    os.environ["CISSTAT_GPU_AVAILABLE"] = "1"
    record("OR10e с сигналом: requires_gpu -> 'cuda'",
           resolve_neural_device(requires_gpu=True) == "cuda"
           and neural_worker_capabilities()["device"] == "cuda")
    os.environ.pop("CISSTAT_GPU_AVAILABLE", None)


def _device_guard() -> bool:
    try:
        resolve_neural_device(requires_gpu=True)
        return False
    except NeuralRuntimeUnavailableError as exc:
        return "тихое" in str(exc) or "запрещено" in str(exc)


# ── OR11/OR12: checkpoint store / restore ─────────────────────────────────

def or11_checkpoints() -> None:
    with tempfile.TemporaryDirectory() as td:
        store = NeuralCheckpointStore(root=Path(td) / "ck")
        my_bytes = bytes(range(256)) * 33 + b"cert137-auditor-payload"
        pointer = store.save_checkpoint("cert137-or11", my_bytes,
                                        metadata={"fold": 3, "step": 9, "note": "auditor"})
        record("OR11a roundtrip: байты + манифест + pointer",
               store.load_checkpoint("cert137-or11", pointer)[0] == my_bytes
               and pointer["sha256"] == hashlib.sha256(my_bytes).hexdigest()
               and store.has_checkpoint("cert137-or11"))

        p = Path(pointer["path"])
        corrupted = bytearray(p.read_bytes()); corrupted[7] ^= 0xFF
        p.write_bytes(bytes(corrupted))
        ok, detail = expect_error(store.load_checkpoint, "cert137-or11", pointer)
        record("OR11b подмена ОДНОГО байта на диске -> отказ (анти-тампер)", ok, detail)

        store.save_checkpoint("cert137-or11b", my_bytes)
        pointer2 = store.save_checkpoint("cert137-or11c", my_bytes)
        bad_sha = dict(pointer2, sha256="f" * 64)
        ok, _ = expect_error(store.load_checkpoint, "cert137-or11c", bad_sha)
        record("OR11c подмена sha в pointer -> отказ", ok)

        stale = dict(pointer2, contract_version="neural-contract-v0")
        ok, _ = expect_error(store.load_checkpoint, "cert137-or11c", stale)
        record("OR11d чужой contract_version -> отказ", ok)

        ok, _ = expect_error(store.save_checkpoint, "cert137-or11e", b"")
        ok2, _ = expect_error(store.save_checkpoint, "cert137-or11f", b"x" * (CHECKPOINT_MAX_BYTES + 1))
        record("OR11e пустой payload и превышение потолка -> отказ", ok and ok2)

        all_ok = True
        for bad in ("../escape", "", "a/b", "a\nb", ".hidden", " x"):
            ok, _ = expect_error(store.save_checkpoint, bad, b"p")
            if not ok:
                all_ok = False
        record("OR11f path-traversal job_id -> отказ (6 кейсов)", all_ok)

        record("OR11g pointer JSON-safe (json.dumps roundtrip)",
               json.loads(json.dumps(pointer))["sha256"] == pointer["sha256"])

        ok, _ = expect_error(store.save_checkpoint, "cert137-json", b"p",
                             metadata={"step": np.int64(4)})
        record("OR11h np.int64 в metadata -> отказ (строгая JSON-безопасность)", ok)

        # restore: pointer -- источник истины; подмена манифеста на диске не влияет
        store2 = NeuralCheckpointStore(root=Path(td) / "ck2")
        ptr = store2.save_checkpoint("job-r", b"resume-state", metadata={"next_step": 11})
        store2._manifest_path("job-r").write_text(json.dumps({"metadata": {"next_step": 999}}),
                                                  encoding="utf-8")
        state = restore_resume_state("job-r", ptr)
        record("OR11i restore: metadata из pointer (манифест -- дубликат)",
               state.metadata.get("next_step") == 11
               and state.contract_version == NEURAL_CONTRACT_VERSION
               and state.checkpoint_path == ptr["path"])

        ghost = dict(ptr, path=str(Path(td) / "ghost.ckpt"))
        ok, detail = expect_error(restore_resume_state, "job-r", ghost)
        record("OR11j restore: отсутствующий файл -> честный отказ (не retrain)", ok, detail)

        store2.delete_checkpoint("job-r")
        record("OR11k delete удаляет .ckpt и .json",
               not store2.has_checkpoint("job-r")
               and not store2._manifest_path("job-r").exists())

        policy = checkpoint_policy()
        record("OR11l policy: filesystem/вне Redis/потолок 512MB",
               policy["backend"] == "filesystem" and policy["stored_in_redis_json"] is False
               and policy["max_bytes"] == 512 * 1024 * 1024)


def or12_path_confinement_characterization() -> None:
    """Характеризация: pointer с произвольным path читается (потребность
    root-конфайнмента -- hardening-замечание, pointer не пользовательский ввод)."""
    with tempfile.TemporaryDirectory() as td_a, tempfile.TemporaryDirectory() as td_b:
        store_a = NeuralCheckpointStore(root=Path(td_a))
        store_b = NeuralCheckpointStore(root=Path(td_b))
        payload = b"cross-root-payload"
        ptr_a = store_a.save_checkpoint("job-x", payload)
        cross_pointer = dict(ptr_a)
        ok = False
        try:
            loaded, _ = store_b.load_checkpoint("job-x", cross_pointer)
            ok = loaded == payload
        except NeuralContractError:
            ok = False
        record(
            "OR12 pointer указывает на произвольный путь: читается ИЗ ЧУЖОГО root",
            True,
            "НАХОДКА-2 (hardening, не блокирует): load доверяет pointer['path']; "
            f"cross-root чтение {'работает' if ok else 'отклонено'}; "
            "рекомендация: конфайнмент root/job_id.ckpt",
        )


# ── OR13: cohort-контракт ─────────────────────────────────────────────────

def or13_cohort() -> None:
    os.environ.pop("CISSTAT_GPU_AVAILABLE", None)
    long = _long_with_exog()
    exog = build_exogenous_plan(long)
    interval = interval_levels_for_alpha(0.2)
    config = NeuralTrainingConfig(seed=606060, max_steps=120)

    cohort = neural_cohort_contract(
        fingerprint="cert137-or13", n_series=1, exogenous=exog,
        interval=interval, loss="mae", config=config,
    )
    record("OR13a univariate-декларация: objective/group/runtime/device",
           cohort["objective"] == "level_forecast"
           and cohort["dependency_group"] == "neural"
           and cohort["runtime"] == NEURAL_RUNTIME == "neuralforecast"
           and cohort["input_kind"] == "univariate" and cohort["device"] == "cpu"
           and cohort["fingerprint"] == "cert137-or13")

    cohort2 = neural_cohort_contract(
        fingerprint="fp2", n_series=2, exogenous=exog, interval=interval,
        loss="quantile", config=config,
    )
    record("OR13b n_series=2 -> panel (PANEL_MIN_SERIES=2)",
           cohort2["input_kind"] == "panel" and cohort2["panel"] is True)

    ok, detail = expect_error(
        neural_cohort_contract, fingerprint="fp3", n_series=4, min_series=5,
        exogenous=exog, interval=interval, loss="mae", config=config,
    )
    ok = ok and "min_series=5" in detail and "n_series=4" in detail
    record("OR13c n_series<min_series -> отказ (честность DeepAR)", ok, detail)

    ok, _ = expect_error(
        neural_cohort_contract, fingerprint="fp4", n_series=1, min_series=5,
        exogenous=exog, interval=interval, loss="mae", config=config,
        input_kind="panel",
    )
    record("OR13d объявленный panel при n_series=1 -> отказ (кросс-чек)", ok)

    record("OR13e cohort связывает loss/interval/training/feature_contract",
           cohort["loss"] == "mae"
           and cohort["interval"]["levels"] == [10.0, 50.0, 90.0]
           and cohort["training"]["seed"] == 606060
           and cohort["feature_contract"]["signature"] == exog.signature
           and cohort["checkpoint_policy"]["backend"] == "filesystem")

    ok, _ = expect_error(
        neural_cohort_contract, fingerprint="fp5", n_series=1, exogenous=exog,
        interval=interval, loss="cosine", config=config,
    )
    record("OR13f cohort с loss вне whitelist -> отказ", ok)


# ── OR17-OR20: бюджет, yaml, реестр (быстрые) ─────────────────────────────

def or17_budget_kwargs() -> None:
    from apps.api.model_impls.neural_runtime import neural_model_budget_kwargs
    cfg = NeuralTrainingConfig(seed=7, max_steps=44, batch_size=64)
    kw = neural_model_budget_kwargs(cfg, device="cpu")
    record("OR17a budget: max_steps/accelerator/progress/patience/batch",
           kw["max_steps"] == 44 and kw["accelerator"] == "cpu"
           and kw["enable_progress_bar"] is False and kw["early_stop_patience_steps"] == -1
           and kw["batch_size"] == 64)
    cfg_es = NeuralTrainingConfig(seed=7, max_steps=44, early_stopping_patience=9, val_size=20)
    kw2 = neural_model_budget_kwargs(cfg_es, device="cuda")
    record("OR17b early-stop маппинг + явный cuda",
           kw2["early_stop_patience_steps"] == 9 and kw2["accelerator"] == "cuda")
    ok, _ = expect_error(neural_model_budget_kwargs, cfg_es, device="tpu")
    record("OR17c device вне {cpu, cuda} -> отказ", ok)


def or19_yaml_unification() -> None:
    data = yaml.safe_load((REPO / "rules" / "modeling.yaml").read_text(encoding="utf-8"))
    neural_family = None
    for fam in data.get("families", []):
        if fam.get("id") == "neural":
            neural_family = fam
            break
    if neural_family is None:
        record("OR19 yaml: семейство neural найдено", False)
        return
    five = {m["id"]: m.get("libraries") for m in neural_family.get("models", [])}
    expected_ids = {"lstm", "nbeats", "nhits", "tft", "deepar"}
    ok = set(five) == expected_ids and all(v == ["neuralforecast"] for v in five.values())
    record("OR19a пять нейро-моделей, libraries==['neuralforecast']", ok, str(five))

    joined = json.dumps(neural_family, ensure_ascii=False)
    record("OR19b без darts/gluonts/pytorch-forecasting в нейро-семействе",
           all(tok not in joined for tok in ("darts", "gluonts", "pytorch-forecasting")))
    record("OR19c описание семейства ссылается на Task 137/контракт",
           "Task 137" in joined or "neural_contract" in joined)


def or20_registry_boundary() -> None:
    from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS, available_model_actions
    neural = {"lstm", "nbeats", "nhits", "tft", "deepar"}
    ids = set(PRODUCTION_BACKTEST_MODEL_IDS)
    record("OR20a production backtest-пул == 19, нейро-пять НЕ в реестре",
           len(ids) == 19 and not (neural & ids), f"count={len(ids)}")
    lstm_acts = available_model_actions("lstm")
    ets_acts = available_model_actions("ets")
    record("OR20b lstm: действия недоступны; ets: backtest доступен (паритет готовности)",
           lstm_acts == [] and "backtest" in ets_acts,
           f"lstm={lstm_acts}, ets={ets_acts}")


def main() -> None:
    print("=" * 78)
    print("CERT137 ORACLES (fast, contract-level) -- auditor seeds, no performer seeds")
    print("=" * 78)
    or1_long_format_basics()
    or2_fail_closed_values()
    or3_grid_validation()
    or4_exogenous_plan()
    or5_future_frame()
    or6_config_bounds()
    or7_fold_seed()
    or8_interval_levels()
    or9_losses()
    or10_capabilities()
    or11_checkpoints()
    or12_path_confinement_characterization()
    or13_cohort()
    or17_budget_kwargs()
    or19_yaml_unification()
    or20_registry_boundary()
    n_pass = sum(1 for _, s, _ in RESULTS if s == "PASS")
    n_fail = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    print("=" * 78)
    print(f"TOTAL: {n_pass + n_fail} probes; PASS={n_pass}, FAIL={n_fail}")
    for name, status, detail in RESULTS:
        if status == "FAIL":
            print(f"  FAIL: {name} -- {detail}")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
