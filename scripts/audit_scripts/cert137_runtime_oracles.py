# scripts/audit_scripts/cert137_runtime_oracles.py
"""Certification of Task 137 -- runtime oracles with REAL NeuralForecast training.

Сиды аудитора (1618033, 42424243, 31337) -- ни один не совпадает с сидами
исполнителя и cert136.  Покрывает шаги probe-скрипта исполнителя, которые
в его committed-версии недостижимы (QuantileLoss, DeepAR-панель), плюс
бит-в-бит детерминизм и conformal-выходы на СВОИХ данных.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apps.api.neural_contract import NeuralTrainingConfig  # noqa: E402
from apps.api.model_impls.neural_runtime import (  # noqa: E402
    neural_model_budget_kwargs,
    seed_neural_runtime,
    train_and_forecast,
)

RESULTS: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, "PASS" if ok else "FAIL", detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def _my_long(n: int = 110, seed: int = 1618033) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "unique_id": ["aud_series"] * n,
        "ds": pd.date_range("2025-01-05", periods=n, freq="D"),
        "y": 4 + 0.04 * np.arange(n) + rng.standard_normal(n) * 0.2,
    })


def _nhits_factory(h: int = 4, input_size: int = 16):
    import neuralforecast.models as M
    return lambda budget: M.NHITS(h=h, input_size=input_size, **budget)


def or14_determinism() -> None:
    cfg = NeuralTrainingConfig(seed=1618033, max_steps=3)
    preds_a = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_my_long(),
        horizon=5, config=cfg,
    )
    preds_b = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_my_long(),
        horizon=5, config=cfg,
    )
    max_diff = float(np.abs(
        preds_a["NHITS"].to_numpy() - preds_b["NHITS"].to_numpy()
    ).max())
    record("OR14a детерминизм (мой seed 1618033): тот же seed -> бит-в-бит",
           max_diff == 0.0, f"max_diff={max_diff!r}")

    preds_c = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_my_long(),
        horizon=5, config=cfg, fold_index=1,
    )
    diff_fc = float(np.abs(
        preds_a["NHITS"].to_numpy() - preds_c["NHITS"].to_numpy()
    ).max())
    record("OR14b другой fold_index -> другой fold_seed -> другой прогноз",
           diff_fc > 0.0, f"max_diff={diff_fc!r}")

    cfg2 = NeuralTrainingConfig(seed=31337, max_steps=3)
    preds_d = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_my_long(),
        horizon=5, config=cfg2,
    )
    diff_seed = float(np.abs(
        preds_a["NHITS"].to_numpy() - preds_d["NHITS"].to_numpy()
    ).max())
    record("OR14c другой seed (31337) -> другой прогноз", diff_seed > 0.0,
           f"max_diff={diff_seed!r}")


def or15_conformal() -> None:
    cfg = NeuralTrainingConfig(seed=42424243, max_steps=3)
    preds = train_and_forecast(
        model_factory=_nhits_factory(h=6), freq="D", train_long=_my_long(),
        horizon=6, config=cfg, levels=(10.0, 90.0),
    )
    lo_col = [c for c in preds.columns if c.endswith("-lo-10.0")]
    hi_col = [c for c in preds.columns if c.endswith("-hi-90.0")]
    ok = (
        len(preds) == 6
        and "NHITS" in preds.columns
        and bool(lo_col) and bool(hi_col)
        and (preds[lo_col[0]] <= preds[hi_col[0]]).all()
    )
    record("OR15a conformal-структура: колонки lo-10/hi-90, lo-10 <= hi-90 "
           "(контрактное обещание)", ok,
           f"columns={list(preds.columns)}; ПРИМЕЧАНИЕ: lo<=point<=hi на "
           "недообученной модели (max_steps=3) контрактом НЕ обещается -- "
           "conformal-калибровка осмысленна на сходимой модели")

    point = train_and_forecast(
        model_factory=_nhits_factory(h=6), freq="D", train_long=_my_long(),
        horizon=6, config=cfg,
    )
    record("OR15b без levels -- нет интервальных колонок",
           not any(("-lo-" in c or "-hi-" in c) for c in point.columns))


def or16_probe_facts() -> None:
    # (a) max_epochs fail-closed (шаг, подтверждённый и в записи исполнителя)
    import neuralforecast.models as M
    try:
        M.NHITS(h=4, input_size=16, max_epochs=2, accelerator="cpu",
                enable_progress_bar=False)
        record("OR16a max_epochs -> fail-closed отказ", False, "конструктор не отказал")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        record("OR16a max_epochs -> fail-closed отказ",
               "max_epochs is deprecated" in msg and "max_steps" in msg,
               f"{type(exc).__name__}: {str(exc)[:90]}")

    # (b) заявление «BaseModel молча ставит accelerator='gpu'»:
    # на CPU-боксе accelerator остаётся None (auto); по исходнику _base_model
    # строки 403-406 'gpu' ставится ТОЛЬКО при torch.cuda.is_available().
    m = M.NHITS(h=4, input_size=16, max_steps=1, enable_progress_bar=False)
    import inspect
    src = inspect.getsource(type(m).__mro__[1].__init__ if False else m.__class__)
    # честная проверка исходника BaseModel.__init__ на условность
    from neuralforecast.common import _base_model as bm
    base_src = inspect.getsource(bm.BaseModel.__init__)
    conditional_gpu = ("if torch.cuda.is_available():" in base_src
                       and 'trainer_kwargs["accelerator"] = "gpu"' in base_src)
    record("OR16b устройство НЕ прижато моделью (None на CPU; 'gpu' только при CUDA)",
           m.trainer_kwargs.get("accelerator") is None and conditional_gpu,
           f"accelerator={m.trainer_kwargs.get('accelerator')!r}; "
           "ЗАМЕЧАНИЕ к работе: заявление 'молча ставит gpu' верно только "
           "на GPU-машинах; контрактная защита (явный accelerator) корректна")

    # (c) probabilistic-поверхность 3.2.2: MQLoss работает, QuantileLoss сломан
    from neuralforecast import NeuralForecast
    from neuralforecast.losses.pytorch import MQLoss, QuantileLoss
    try:
        QuantileLoss(level=[10.0, 90.0])
        ql_level_rejected = False
    except TypeError:
        ql_level_rejected = True
    record("OR16c-факт QuantileLoss(level=...) отклоняется конструктором 3.2.2 "
           "(committed probe-шаг исполнителя несовместим с 3.2.2)", ql_level_rejected)

    seed_neural_runtime(2718281)
    model = M.NHITS(
        h=4, input_size=16, max_steps=2, enable_progress_bar=False,
        accelerator="cpu", loss=MQLoss(level=[10.0, 90.0]),
    )
    nf = NeuralForecast(models=[model], freq="D")
    nf.fit(_my_long())
    p = nf.predict()
    qcols = [c for c in p.columns if "-lo-10.0" in c or "-hi-90.0" in c or "-median" in c]
    record("OR16c MQLoss(level=[10,90]) -- РАБОЧИЙ probabilistic-путь 3.2.2",
           len(qcols) >= 3, f"qcols={qcols}; рекомендация срезам 138-142: "
           "QuantileLoss сломан (q-список падает в fit, q-тензор даёт мусорную колонку)")

    # (d) DeepAR панель (3 серии, мой сид 42424243)
    rng = np.random.default_rng(42424243)
    frames = []
    for i in range(3):
        frames.append(pd.DataFrame({
            "unique_id": [f"aud_{i}"] * 96,
            "ds": pd.date_range("2025-02-01", periods=96, freq="D"),
            "y": 6 + i * 1.5 + rng.standard_normal(96) * 0.3,
        }))
    panel = pd.concat(frames, ignore_index=True)
    seed_neural_runtime(42424243)
    deepar = M.DeepAR(h=4, input_size=16, max_steps=2,
                      enable_progress_bar=False, accelerator="cpu")
    nf2 = NeuralForecast(models=[deepar], freq="D")
    nf2.fit(panel)
    p2 = nf2.predict()
    record("OR16d DeepAR панель 3x96: fit/predict OK",
           len(p2) == 12 and p2["unique_id"].nunique() == 3,
           f"rows={len(p2)}, series={p2['unique_id'].nunique()}")


def or17_five_models_construct() -> None:
    import neuralforecast.models as M
    config = NeuralTrainingConfig(seed=20260911, max_steps=1)
    budget = neural_model_budget_kwargs(config, device="cpu")
    ok = True
    names = []
    for cls_name in ("LSTM", "NBEATS", "NHITS", "TFT", "DeepAR"):
        model = getattr(M, cls_name)(h=4, input_size=16, **budget)
        names.append(f"{cls_name}:{model.h}")
        ok = ok and model.h == 4
    record("OR17e пять каталог-моделей конструируются на едином бюджете", ok,
           " ".join(names))


def main() -> None:
    print("=" * 78)
    print("CERT137 RUNTIME ORACLES (real training) -- auditor seeds only")
    print("=" * 78)
    or14_determinism()
    or15_conformal()
    or16_probe_facts()
    or17_five_models_construct()
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
