# scripts/audit_scripts/cert140_f1f2_probe.py
"""Эмпирический проб аудитора (сертификация Task 140, мои данные).

Цель -- первичная фактура двух кандидатов в находки ДО финализации
оракулов cert140_oracles.py:

  F1' (аналог НАХОДКИ-1 сертификации Task 139): гейт неосуществимого
  окна nhits.py -- `nobs < input_size + horizon` БЕЗ +2; конформный
  контур 3.2.2 (PredictionIntervals) требует n >= input+horizon+2 --
  полоса [input+h, input+h+1] проходит адаптерный гейт и падает сырым
  Exception библиотеки (вне таксономии ValueError адаптера).

  F2' (новая, класс literal-dup/metadata-lie): hidden_size и mlp_layers
  -- МЁРТВЫЕ ручки: validate_nhits_params их bounded-валидацией
  подтверждает и params/metadata эхом возвращают, но в конструктор
  NHITS они не передаются НИКАК (mlp_units не строится -- у NHITS 3.2.2
  нет параметра hidden_size; дефолт mlp_units=3*[[512,512]] остаётся
  навсегда).  yaml::nhits param_space содержит hidden_size -- ось
  тюнинга без эффекта.

Данные аудита: собственный генератор (синус + тренд + шум, seed=140),
НЕ фикстуры исполнителя (прецедент cert139_oracles.py).

Запуск: OMP_NUM_THREADS=1 CISSTAT_NEURAL_MAX_STEPS=6 python3 \
  scripts/audit_scripts/cert140_f1f2_probe.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np

os.environ.setdefault("CISSTAT_NEURAL_MAX_STEPS", "6")  # скоростной бюджет

from apps.api.model_impls import nbeats as nbeats_module  # noqa: E402
from apps.api.model_impls import nhits as nhits_module  # noqa: E402


def my_series(n: int = 90, seed: int = 140) -> list[float]:
    """Собственный ряд аудитора: синус + тренд + шум (seed=140)."""
    rng = np.random.default_rng(seed)
    step = np.arange(n, dtype=float)
    values = 50.0 + 0.12 * step + 4.0 * np.sin(2.0 * np.pi * step / 12.0)
    values += rng.standard_normal(n) * 0.3
    return values.astype(float).tolist()


def main() -> int:
    series = my_series()
    print("== F1'-проба: boundary-полоса гейта окна (input=28, horizon=3) ==")
    for nobs in (30, 31, 32, 33):
        attempt = series[:nobs]
        try:
            payload = nhits_module._nhits_fit_predict(
                attempt, 3, params={"input_size": 28}, random_state=140,
            )
            print(f"n={nobs}: FIT OK (len={len(payload['forecast'])})")
        except Exception as exc:  # noqa: BLE001 -- характеристика, не прогон
            kind = type(exc).__name__
            first = str(exc).splitlines()[0][:100]
            print(f"n={nobs}: {kind}: {first}")

    print("== F2'-проба: мёртвые ручки hidden_size / mlp_layers ==")
    base = nhits_module._nhits_fit_predict(
        series, 4, params={"hidden_size": 8}, random_state=140,
    )
    for handle, values in (
        ("hidden_size", (8, 32, 128)),
        ("mlp_layers", (1, 2, 4)),
    ):
        forecasts = []
        for value in values:
            payload = nhits_module._nhits_fit_predict(
                series, 4, params={handle: value}, random_state=140,
            )
            forecasts.append(np.asarray(payload["forecast"], dtype=float))
        diffs = [
            float(np.abs(a - b).max())
            for a, b in zip(forecasts[:-1], forecasts[1:])
        ]
        print(f"{handle} {values}: max|diff| попарно = {diffs}")

    print("== F2'-контраст: nbeats hidden_size жив? ==")
    nb_lo = nbeats_module._nbeats_fit_predict(
        series, 4, params={"hidden_size": 8}, random_state=140,
    )
    nb_hi = nbeats_module._nbeats_fit_predict(
        series, 4, params={"hidden_size": 128}, random_state=140,
    )
    diff = float(np.abs(
        np.asarray(nb_lo["forecast"]) - np.asarray(nb_hi["forecast"]),
    ).max())
    print(f"nbeats hidden_size 8 vs 128: max|diff| = {diff}")

    print("== interpolation_config жив? ==")
    hier = nhits_module._nhits_fit_predict(
        series, 4, params={"interpolation_config": "hierarchical"},
        random_state=140,
    )
    light = nhits_module._nhits_fit_predict(
        series, 4, params={"interpolation_config": "light"}, random_state=140,
    )
    diff = float(np.abs(
        np.asarray(hier["forecast"]) - np.asarray(light["forecast"]),
    ).max())
    print(f"hierarchical vs light: max|diff| = {diff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
