# scripts/audit_scripts/cert137_recert_oracles.py
"""Recertification of Task 137 -- oracle probes on the REWORKED code.

Исполнитель доработал Task 137 по вердикту сертификации (блокирующая
находка seed-прокидки + НАХОДКИ 3-5).  Ресертификационные пробы на НОВЫХ
сидах аудитора (20260912/42424244/1618034/90210666 -- ни один не совпадает
с сидами сертификационной записи), проверяющие:

- RO1: дифференциальные пробы сидов (бывш. OR14b/c) -- ОБЯЗАНЫ зеленеть
  после фикса; same-seed остаётся бит-в-бит;
- RO2: stub-прокидка random_seed в конструктор (fold-производность);
- RO3: Inf-гейт keep-колонок (НАХОДКА-4) + легитимный категориальный путь;
- RO4: root-confinement чекпойнт-pointer (НАХОДКА-5): cross-root и чужой
  job -- отказ, легитимный pointer и normpath-эквивалент -- проход;
- RO5: restore_resume_state(root=...) -- тот же корень проходит, чужой
  корень -- честный отказ;
- RO6: прод-инварианты (реестр 19/24, нейро-пять вне v2).

Запуск: python scripts/audit_scripts/cert137_recert_oracles.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

from apps.api.neural_contract import (
    NEURAL_CONTRACT_VERSION,
    NeuralCheckpointStore,
    NeuralContractError,
    NeuralTrainingConfig,
    fold_seed,
    restore_resume_state,
    to_long_format,
)

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def expect_error(fn, *args, **kwargs) -> tuple[bool, str]:
    try:
        fn(*args, **kwargs)
    except NeuralContractError as exc:
        return True, str(exc)[:110]
    except Exception as exc:  # noqa: BLE001
        return False, f"неожиданный {type(exc).__name__}: {exc}"[:110]
    return False, "NeuralContractError не поднят"


# ── RO1: дифференциальные пробы сидов (реальные тренировки) ──────────────

def _nhits_factory(h: int = 4, input_size: int = 16):
    def factory(budget):
        from apps.api.model_impls.neural_runtime import require_neuralforecast
        models = require_neuralforecast().models
        return models.NHITS(h=h, input_size=input_size, **budget)
    return factory


def _my_long(n: int = 96, seed: int = 20260912) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "unique_id": ["recert_0"] * n,
        "ds": pd.date_range("2025-01-01", periods=n, freq="D"),
        "y": 8 + 0.05 * np.arange(n) + rng.standard_normal(n) * 0.2,
    })


def ro1_seed_differentials() -> None:
    from apps.api.model_impls.neural_runtime import train_and_forecast
    cfg = NeuralTrainingConfig(seed=42424244, max_steps=3)
    preds_a = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_my_long(),
        horizon=5, config=cfg, fold_index=0,
    )
    preds_b = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_my_long(),
        horizon=5, config=cfg, fold_index=0,
    )
    max_diff = float(np.abs(
        preds_a["NHITS"].to_numpy() - preds_b["NHITS"].to_numpy()
    ).max())
    record("RO1a same-seed детерминизм: бит-в-бит (max_diff == 0.0)",
           max_diff == 0.0, f"max_diff={max_diff!r}")

    preds_c = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_my_long(),
        horizon=5, config=cfg, fold_index=1,
    )
    diff_fc = float(np.abs(
        preds_a["NHITS"].to_numpy() - preds_c["NHITS"].to_numpy()
    ).max())
    record("RO1b другой fold_index -> другой fold_seed -> другой прогноз",
           diff_fc > 0.0, f"max_diff={diff_fc!r}")

    cfg2 = NeuralTrainingConfig(seed=1618034, max_steps=3)
    preds_d = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_my_long(),
        horizon=5, config=cfg2,
    )
    diff_seed = float(np.abs(
        preds_a["NHITS"].to_numpy() - preds_d["NHITS"].to_numpy()
    ).max())
    record("RO1c другой seed (1618034) -> другой прогноз",
           diff_seed > 0.0, f"max_diff={diff_seed!r}")


# ── RO2: stub-прокидка random_seed в конструктор ─────────────────────────

def ro2_seed_propagation_stub() -> None:
    from apps.api.model_impls.neural_runtime import train_and_forecast

    captured: list[dict] = []

    class _Stop(Exception):
        pass

    def factory(budget):
        captured.append(dict(budget))
        raise _Stop()

    for seed, fold in ((90210666, 0), (90210666, 3), (20260912, 0)):
        try:
            train_and_forecast(
                model_factory=factory, freq="D", train_long=_my_long(),
                horizon=4, config=NeuralTrainingConfig(seed=seed, max_steps=3),
                fold_index=fold,
            )
        except _Stop:
            pass
    expected = [
        fold_seed(90210666, fold_index=0),
        fold_seed(90210666, fold_index=3),
        fold_seed(20260912, fold_index=0),
    ]
    got = [entry.get("random_seed") for entry in captured]
    record("RO2a random_seed в budget == fold_seed(config.seed, fold_index)",
           got == expected, f"got={got}; expected={expected}")
    record("RO2b random_seed fold-производен (3 значения различны)",
           len(set(got)) == 3, f"unique={len(set(got))}/3")


# ── RO3: Inf-гейт keep-колонок ────────────────────────────────────────────

def _frame_with(column: str, values: list) -> pd.DataFrame:
    n = len(values)
    return pd.DataFrame({
        "ts": pd.date_range("2025-01-01", periods=n, freq="D"),
        "value": np.linspace(1.0, 2.0, n),
        column: values,
    })


def ro3_keep_column_inf_gate() -> None:
    frame = _frame_with("temp", [1.0, 2.0, np.inf, 4.0, 5.0, 6.0])
    ok, detail = expect_error(
        to_long_format, frame, value_column="value", time_column="ts",
        keep_columns=("temp",),
    )
    record("RO3a числовая keep-колонка с Inf -> отказ (НАХОДКА-4 закрыта)",
           ok, detail)

    frame_obj = _frame_with("temp", [1.0, 2.0, float("inf"), 4.0, 5.0, 6.0])
    frame_obj["temp"] = frame_obj["temp"].astype(object)
    ok2, detail2 = expect_error(
        to_long_format, frame_obj, value_column="value", time_column="ts",
        keep_columns=("temp",),
    )
    record("RO3b объектная колонка с Inf-флоатом (коэрцибельна) -> отказ",
           ok2, detail2)

    clean = _frame_with("temp", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    try:
        long = to_long_format(clean, value_column="value", time_column="ts",
                              keep_columns=("temp",))
        ok3 = list(long.columns) == ["unique_id", "ds", "y", "temp"]
        detail3 = f"columns={list(long.columns)}"
    except NeuralContractError as exc:
        ok3, detail3 = False, str(exc)[:110]
    record("RO3c чистая числовая keep-колонка проходит", ok3, detail3)

    cats = _frame_with("region", ["eu", "us", "ap", "eu", "us", "ap"])
    try:
        long = to_long_format(cats, value_column="value", time_column="ts",
                              keep_columns=("region",))
        ok4 = "region" in long.columns
        detail4 = f"values={sorted(set(long['region']))}"
    except NeuralContractError as exc:
        ok4, detail4 = False, str(exc)[:110]
    record("RO3d категориальная keep-колонка проходит (не числовой гейт)",
           ok4, detail4)


# ── RO4/RO5: root-confinement чекпойнтов и restore ───────────────────────

def ro4_checkpoint_confinement() -> None:
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as td_b:
        store = NeuralCheckpointStore(root=Path(td) / "ck")
        foreign = NeuralCheckpointStore(root=Path(td_b) / "ck")
        payload = b"recert-ckpt-bytes"
        ptr = store.save_checkpoint("job-rc1", payload, metadata={"step": 5})

        loaded, manifest = store.load_checkpoint("job-rc1", ptr)
        record("RO4a легитимный roundtrip (тот же store) проходит",
               loaded == payload and manifest["sha256"] == ptr["sha256"])

        ok, detail = expect_error(foreign.load_checkpoint, "job-rc1", ptr)
        record("RO4b cross-root чтение отклонено (было: читалось молча)",
               ok, detail)

        other = store.save_checkpoint("job-rc2", b"other-bytes")
        ok, detail = expect_error(store.load_checkpoint, "job-rc1", other)
        record("RO4c путь чужого job_id внутри корня отклонен (1:1 job<->ckpt)",
               ok, detail)

        escape = dict(ptr, path=str(Path(td) / "ck" / ".." / "escape.ckpt"))
        ok, detail = expect_error(store.load_checkpoint, "job-rc1", escape)
        record("RO4d path с '..' вне корня отклонен", ok, detail)

        # normpath-эквивалент легитимного пути (избыточные сегменты) -- проход
        redundant = dict(ptr, path=str(Path(td) / "ck" / "." / "job-rc1.ckpt"))
        try:
            loaded2, _ = store.load_checkpoint("job-rc1", redundant)
            ok2 = loaded2 == payload
            detail2 = "нормализованный путь принят"
        except NeuralContractError as exc:
            ok2, detail2 = False, str(exc)[:110]
        record("RO4e избыточные '.'-сегменты нормализуются (не ложный отказ)",
               ok2, detail2)

        state = restore_resume_state("job-rc1", ptr, root=Path(td) / "ck")
        record("RO5a restore с тем же корнем: metadata из pointer",
               state.metadata.get("step") == 5
               and state.contract_version == NEURAL_CONTRACT_VERSION)

        ok, detail = expect_error(restore_resume_state, "job-rc1", ptr)
        record("RO5b restore с ЧУЖИМ (дефолтным) корнем -- честный отказ",
               ok, detail)

        gone = store.checkpoint_path("job-gone")
        ghost = dict(ptr, path=str(gone), checkpoint_id="job-gone",
                     sha256="a" * 64)
        ok, detail = expect_error(
            restore_resume_state, "job-gone", ghost, root=Path(td) / "ck",
        )
        record("RO5c отсутствующий файл на легитимном пути -- отказ 'не найден'",
               ok and ("отсутств" in detail or "найден" in detail), detail)


# ── RO6: прод-инварианты ──────────────────────────────────────────────────

def ro6_production_invariants() -> None:
    from apps.api.model_readiness import (
        PRODUCTION_BACKTEST_MODEL_IDS,
        available_model_actions,
    )
    n_prod = len(PRODUCTION_BACKTEST_MODEL_IDS)
    record("RO6a PRODUCTION_BACKTEST_MODEL_IDS == 19 (count-гейты не тронуты)",
           n_prod == 19, f"n={n_prod}")
    record("RO6b нейро-пять отсутствуют в production-реестре",
           not {"lstm", "gru", "nbeats", "nhits", "tft", "deepar"}
           & set(PRODUCTION_BACKTEST_MODEL_IDS))
    record("RO6c catalog_only честен: available_model_actions('lstm') == []",
           available_model_actions("lstm") == [])


def main() -> None:
    print("=" * 78)
    print("CERT137 RECERT ORACLES -- на доработанном дереве, новые сиды аудитора")
    print("=" * 78)
    ro2_seed_propagation_stub()
    ro3_keep_column_inf_gate()
    ro4_checkpoint_confinement()
    ro6_production_invariants()
    ro1_seed_differentials()
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    print("-" * 78)
    print(f"TOTAL: {n_pass}/{len(RESULTS)} PASS")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL {name}: {detail}")
    sys.exit(0 if n_pass == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
