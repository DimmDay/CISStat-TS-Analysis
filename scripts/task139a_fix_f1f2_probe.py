# scripts/task139a_fix_f1f2_probe.py
"""Эмпирический проб Task 139a -- применение исправлений находок F1/F2
сертификации Task 139 (N-BEATS) ПОД фикс-срез.

Поверхность ожиданий снимается пробом ДО написания тестов (прецедент
Task 139/140/141): правка без контрольного замера на реальном runtime
запрещена.

Секции:

  1. F1 (НАХОДКА-1 сертификации Task 139): минимальная длина ряда
     conformal-конфигурации 3.2.2 (PredictionIntervals в fit) --
     прямые вызовы библиотеки (БЕЗ адаптерного гейта) на 5 конфигах
     (input_size, horizon): ожидание -- фит отказывает при
     n == input+h и n == input+h+1 (сырые Exception библиотеки) и
     обучается при n == input+h+2.  Стабильность формулы
     n_min = input_size + horizon + 2.

  2. F2 (НАХОДКА-2): дефекты СТАРОГО маппинга
     mlp_units = [[hidden]*mlp_layers for _ in range(2)] через адаптер
     (текущий код до правки): layers=1 -- RAW IndexError конструктора
     NBEATSBlock (библиотека читает пары [in, out] inner-списка),
     layers=3/4 -- МОЛЧА эквивалентны 2 (max|diff| = 0.0).

  3. F2 -- проверка НОВОГО pair-маппинга
     mlp_units = [[hidden, hidden] for _ in range(mlp_layers)]
     (симуляция правки monkeypatch'ем _stack_kwargs ДО неё):
     весь диапазон [1, 4] исполним, попарно различим; дефолт
     mlp_layers=2 -- бит-паритет со старым маппингом
     (сертифицированный путь бит-неизменен).

Запуск: OMP_NUM_THREADS=1 CISSTAT_NEURAL_MAX_STEPS=6 python3 \
  scripts/task139a_fix_f1f2_probe.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

os.environ.setdefault("CISSTAT_NEURAL_MAX_STEPS", "6")  # скоростной бюджет

from apps.api.model_impls import nbeats as nbeats_module  # noqa: E402


def auditor_series(n: int = 130, seed: int = 2026) -> list[float]:
    """Собственный ряд аудитора: синус + тренд + шум (seed=2026)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    values = (5.0 + 1.7 * np.sin(2.0 * np.pi * t / 12.0) + 0.03 * t
              + rng.normal(0.0, 0.15, n))
    return values.astype(float).tolist()


def _direct_library_fit(n: int, input_size: int, horizon: int) -> str:
    """Прямой вызов NeuralForecast (БЕЗ адаптерного гейта): 'OK' при
    успешном fit+predict в conformal-конфигурации, иначе 'ВИД: сообщение'."""
    from neuralforecast import NeuralForecast
    from neuralforecast.losses.pytorch import MAE
    from neuralforecast.utils import PredictionIntervals

    nf_module = nbeats_module._require_models()
    model = nf_module.NBEATS(
        h=horizon,
        input_size=input_size,
        alias="NBEATS",
        stack_types=["trend", "seasonality"],
        n_blocks=[1, 1],
        mlp_units=[[32, 32] for _ in range(2)],
        loss=MAE(),
        max_steps=3,
        accelerator="cpu",
        enable_progress_bar=False,
        early_stop_patience_steps=-1,
        random_seed=2026,
    )
    y = np.asarray(auditor_series(n), dtype=float)
    frame = pd.DataFrame({
        "unique_id": "probe",
        "ds": np.arange(n, dtype=int),
        "y": y,
    })
    nf = NeuralForecast(models=[model], freq=1)
    nf.fit(df=frame, prediction_intervals=PredictionIntervals())
    preds = nf.predict(level=[95.0])
    if "NBEATS" not in preds.columns:
        return f"ОШИБКА: колонки {list(preds.columns)}"
    return f"OK len={len(preds)}"


def section_f1_formula_stability() -> None:
    print("== Секция 1: F1 -- формула n_min = input+horizon+2 (5 конфигов) ==")
    configs = ((8, 2), (16, 4), (24, 3), (28, 2), (48, 6))
    stable = True
    for input_size, horizon in configs:
        outcomes = []
        for extra in (0, 1, 2):
            n = input_size + horizon + extra
            try:
                outcome = _direct_library_fit(n, input_size, horizon)
            except Exception as exc:  # noqa: BLE001 -- характеристика отказа
                kind = type(exc).__name__
                first = str(exc).splitlines()[0][:72]
                outcome = f"{kind}: {first}"
            outcomes.append((n, outcome))
        ok_n = outcomes[-1][1].startswith("OK")
        raw_band = all(
            not outcomes[index][1].startswith("OK") for index in (0, 1)
        )
        verdict = "ФОРМУЛА ПОДТВЕРЖДАЁТ" if (ok_n and raw_band) else "ОТКЛОНЕНИЕ"
        if not (ok_n and raw_band):
            stable = False
        print(f"  input={input_size:3d} horizon={horizon}:")
        for n, outcome in outcomes:
            print(f"    n={n:3d}: {outcome}")
        print(f"    -> {verdict}")
    print(f"  ИТОГ F1: формула {'СТАБИЛЬНА' if stable else 'НЕ стабильна'}")


def _forecast(layers: int) -> np.ndarray:
    payload = nbeats_module._nbeats_fit_predict(
        auditor_series(90)[:90], 4,
        params={"mlp_layers": layers}, random_state=2026,
    )
    return np.asarray(payload["forecast"], dtype=float)


def _forecast_with_stack_kwargs(layers: int, stack_kwargs_builder) -> np.ndarray:
    original = nbeats_module._stack_kwargs
    nbeats_module._stack_kwargs = stack_kwargs_builder
    try:
        return _forecast(layers)
    finally:
        nbeats_module._stack_kwargs = original


def _new_pair_mapping(stack_config: str, hidden: int, mlp_layers: int) -> dict:
    """НОВЫЙ pair-маппинг (кандидат исправления F2)."""
    mlp_units = [[hidden, hidden] for _ in range(mlp_layers)]
    if stack_config == "interpretable":
        return {
            "stack_types": ["trend", "seasonality"],
            "n_blocks": [1, 1],
            "mlp_units": mlp_units,
        }
    return {
        "stack_types": ["identity", "identity"],
        "n_blocks": [1, 1],
        "mlp_units": mlp_units,
        "basis": "polynomial",
    }


def section_f2_old_defects() -> None:
    print("== Секция 2: F2 -- дефекты СТАРОГО маппинга (текущий код) ==")
    try:
        _forecast(1)
        print("  layers=1: ФИТ OK (дефект исчез?)")
    except Exception as exc:  # noqa: BLE001 -- характеристика отказа
        kind = type(exc).__name__
        first = str(exc).splitlines()[0][:72]
        print(f"  layers=1: {kind}: {first}")
    base = _forecast(2)
    for layers in (3, 4):
        same = _forecast(layers)
        diff = float(np.abs(base - same).max())
        print(f"  layers={layers} vs 2: max|diff| = {diff} "
              f"({'МОЛЧА эквивалентны 2' if diff == 0.0 else 'различимы'})")


def section_f2_new_mapping() -> None:
    print("== Секция 3: F2 -- НОВЫЙ pair-маппинг (симуляция правки) ==")
    # Структурный паритет дефолта: new(2) == old(2) литерально.
    old_two = [[32] * 2 for _ in range(2)]
    new_two = [[32, 32] for _ in range(2)]
    print(f"  структуры при layers=2: old={old_two} new={new_two} "
          f"равны: {old_two == new_two}")
    forecasts = {}
    for layers in (1, 2, 3, 4):
        forecasts[layers] = _forecast_with_stack_kwargs(
            layers, _new_pair_mapping,
        )
        print(f"  layers={layers}: ФИТ OK (новый маппинг)")
    print("  попарная различимость нового маппинга:")
    distinguishable = True
    for i, low in enumerate((1, 2, 3)):
        for high in (2, 3, 4)[i:]:
            diff = float(np.abs(forecasts[low] - forecasts[high]).max())
            mark = "различимы" if diff > 0.0 else "СЛИЛИСЬ"
            if diff == 0.0:
                distinguishable = False
            print(f"    {low} vs {high}: max|diff| = {diff} ({mark})")
    # Бит-паритет сертифицированного дефолта: layers=2, old vs new.
    old_forecast = _forecast_with_stack_kwargs(
        2,
        lambda stack, hidden, layers: {
            "stack_types": ["trend", "seasonality"],
            "n_blocks": [1, 1],
            "mlp_units": [[hidden] * layers for _ in range(2)],
        },
    )
    parity = float(np.abs(old_forecast - forecasts[2]).max())
    print(f"  бит-паритет дефолта (layers=2, old vs new): max|diff| = {parity}")
    verdict = (
        distinguishable and parity == 0.0
    )
    print(f"  ИТОГ F2: новый маппинг "
          f"{'ИСПОЛНИМ И РАЗЛИЧИМ, дефолт бит-неизменен' if verdict else 'НЕ ОК'}")


def main() -> int:
    section_f1_formula_stability()
    section_f2_old_defects()
    section_f2_new_mapping()
    print("PROBE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
