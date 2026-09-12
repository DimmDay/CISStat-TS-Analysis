# scripts/task140a_fix_probe.py
"""Эмпирический проб Task 140a -- гейт окна +2 и оживление ручек
hidden_size/mlp_layers в nhits.py + F3' (horizon=1 и стеки) ПОД фикс-срез.

Поверхность ожиданий снимается пробом ДО написания тестов (прецедент
Tasks 139/140/141/139a): правка без контрольного замера на реальном
runtime запрещена.

Секции:

  1. F1' (находка сертификации Task 140, аналог F1 Task 139): формула
     минимальной длины ряда conformal-конфигурации 3.2.2
     (PredictionIntervals в fit) для NHITS -- прямые вызовы библиотеки
     (БЕЗ адаптерного гейта) на 5 конфигах (input_size, horizon):
     ожидание -- фит отказывает при n == input+h и n == input+h+1
     (сырые Exception библиотеки) и обучается при n == input+h+2.

  2. F2' (находка сертификации Task 140): мёртвые ручки hidden_size/
     mlp_layers ЧЕРЕЗ АДАПТЕР (текущий код до правки) -- значения
     bounded-валидации честны, но до конструктора не доходят:
     max|diff| = 0.0 по всему диапазону (literal-dup класс).

  3. F2' -- проверка НОВОГО pair-маппинга библиотекой:
     mlp_units = [[hidden, hidden] for _ in range(mlp_layers)]
     (та же конвенция пар [in, out], что сертифицирована для NBEATS
     Task 139a) на поверхности NHITS: весь диапазон hidden [8, 128] x
     layers [1, 4] исполним, попарно различим (на репрезентативной
     сетке); семантика потребления mlp_units снята по весам блоков
     (весь список -- скрытые слои КАЖДОГО блока).

  4. F3' (кандидат-нахождка Task 139a, N-BEATS): horizon=1 несовместим
     со стеками trend/seasonality (interpretable) -- сырой Exception
     библиотеки при ЛЮБОЙ длине ряда; generic (identity) при h=1
     исполним?  Плюс: NHITS (identity x 3) при h=1 исполним?
     Эмпирия для решения о гейте пары (стек, horizon).

Запуск: OMP_NUM_THREADS=1 CISSTAT_NEURAL_MAX_STEPS=6 python3 \
  scripts/task140a_fix_probe.py
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
import torch

os.environ.setdefault("CISSTAT_NEURAL_MAX_STEPS", "6")  # скоростной бюджет

from apps.api.model_impls import nbeats as nbeats_module  # noqa: E402
from apps.api.model_impls import nhits as nhits_module  # noqa: E402


def auditor_series(n: int = 130, seed: int = 140) -> list[float]:
    """Собственный ряд аудитора: синус + тренд + шум (seed=140)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    values = (50.0 + 0.12 * t + 4.0 * np.sin(2.0 * np.pi * t / 12.0)
              + rng.normal(0.0, 0.3, n))
    return values.astype(float).tolist()


def _direct_library_fit(model_kind: str, n: int, input_size: int, horizon: int,
                        extra_kwargs: dict | None = None) -> str:
    """Прямой вызов NeuralForecast (БЕЗ адаптерного гейта): 'OK' при
    успешном fit+predict в conformal-конфигурации, иначе 'ВИД: сообщение'."""
    from neuralforecast import NeuralForecast
    from neuralforecast.losses.pytorch import MAE
    from neuralforecast.utils import PredictionIntervals

    nf_models = nhits_module._require_models()
    cls = nf_models.NHITS if model_kind == "NHITS" else nf_models.NBEATS
    model = cls(
        h=horizon,
        input_size=input_size,
        alias=model_kind,
        loss=MAE(),
        max_steps=3,
        accelerator="cpu",
        enable_progress_bar=False,
        early_stop_patience_steps=-1,
        random_seed=140,
        **(extra_kwargs or {}),
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
    if model_kind not in preds.columns:
        return f"ОШИБКА: колонки {list(preds.columns)}"
    return f"OK len={len(preds)}"


def section_f1_formula_stability() -> bool:
    print("== Секция 1: F1' -- формула n_min = input+horizon+2 для NHITS (5 конфигов) ==")
    configs = ((8, 2), (16, 4), (24, 3), (28, 2), (48, 6))
    stable = True
    for input_size, horizon in configs:
        outcomes = []
        for extra in (0, 1, 2):
            n = input_size + horizon + extra
            try:
                outcome = _direct_library_fit("NHITS", n, input_size, horizon)
            except Exception as exc:  # noqa: BLE001 -- характеристика отказа
                kind = type(exc).__name__
                first = str(exc).splitlines()[0][:72]
                outcome = f"{kind}: {first}"
            outcomes.append((n, outcome))
        ok_n = outcomes[-1][1].startswith("OK")
        raw_band = all(
            not outcomes[index][1].startswith("OK") for index in (0, 1)
        )
        verdict = "ФОРМУЛУ ПОДТВЕРЖДАЕТ" if (ok_n and raw_band) else "ОТКЛОНЕНИЕ"
        if not (ok_n and raw_band):
            stable = False
        print(f"  input={input_size:3d} horizon={horizon}:")
        for n, outcome in outcomes:
            print(f"    n={n:3d}: {outcome}")
        print(f"    -> {verdict}")
    print(f"  ИТОГ F1': формула {'СТАБИЛЬНА' if stable else 'НЕ стабильна'}")
    return stable


def section_f2_dead_knobs_through_adapter() -> None:
    print("== Секция 2: F2' -- мёртвые ручки через адаптер (текущий код) ==")
    series = auditor_series(90)
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
        print(f"  {handle} {values}: max|diff| попарно = {diffs}")


def _block_widths(model) -> list[tuple[int, int]]:
    """Фактические ширины Linear-слоёв первого блока (по весам)."""
    widths = [
        (linear.weight.shape[0], linear.weight.shape[1])
        for _, linear in model.blocks[0].named_modules()
        if isinstance(linear, torch.nn.Linear)
    ]
    return widths


def section_f2_new_pair_mapping() -> bool:
    print("== Секция 3: F2' -- pair-маппинг mlp_units на NHITS (прямые фиты) ==")
    # 3a) Семантика потребления mlp_units: весовая фактура первого блока.
    nf_models = nhits_module._require_models()
    probe_kwargs = {
        "h": 2, "input_size": 16, "alias": "NHITS", "max_steps": 3,
        "accelerator": "cpu", "enable_progress_bar": False,
        "early_stop_patience_steps": -1, "random_seed": 140,
    }
    default_model = nf_models.NHITS(**probe_kwargs)
    mapped_model = nf_models.NHITS(
        **probe_kwargs, mlp_units=[[24, 24], [40, 40]],
    )
    print(f"  дефолт:  widths(block0) = {_block_widths(default_model)}")
    print(f"  [[24,24],[40,40]]: widths(block0) = {_block_widths(mapped_model)}")

    # 3b) Исполнимость и различимость pair-маппинга через адаптерную
    #     структуру (прямые фиты библиотеки с conformal-конфигурацией).
    series = auditor_series(90)
    feasible = True
    grid = ((8, 1), (32, 2), (128, 4), (64, 3))
    for hidden, layers in grid:
        try:
            payload = _direct_library_fit(
                "NHITS", len(series), 24, 4,
                extra_kwargs={
                    "n_pool_kernel_size": [2, 2, 1],
                    "n_freq_downsample": [4, 2, 1],
                    "mlp_units": [[hidden, hidden] for _ in range(layers)],
                },
            )
            print(f"  hidden={hidden:3d} layers={layers}: {payload}")
            if not payload.startswith("OK"):
                feasible = False
        except Exception as exc:  # noqa: BLE001 -- характеристика отказа
            feasible = False
            kind = type(exc).__name__
            first = str(exc).splitlines()[0][:72]
            print(f"  hidden={hidden:3d} layers={layers}: {kind}: {first}")

    # 3c) Попарная различимость ПРОГНОЗОВ pair-маппинга (реальный fit/predict
    #     через NeuralForecast с одним seed на репрезентативной сетке).
    print("  различимость прогнозов (fit+predict, seed=140):")
    forecasts: dict[tuple[int, int], np.ndarray] = {}
    for hidden, layers in grid:
        try:
            from neuralforecast import NeuralForecast
            from neuralforecast.losses.pytorch import MAE
            from neuralforecast.utils import PredictionIntervals
            nf_models3 = nhits_module._require_models()
            model = nf_models3.NHITS(
                h=4, input_size=24, alias="NHITS",
                n_pool_kernel_size=[2, 2, 1], n_freq_downsample=[4, 2, 1],
                mlp_units=[[hidden, hidden] for _ in range(layers)],
                loss=MAE(), max_steps=6, accelerator="cpu",
                enable_progress_bar=False, early_stop_patience_steps=-1,
                random_seed=140,
            )
            y = np.asarray(series, dtype=float)
            frame = pd.DataFrame({
                "unique_id": "probe", "ds": np.arange(len(y), dtype=int),
                "y": y,
            })
            nf = NeuralForecast(models=[model], freq=1)
            nf.fit(df=frame, prediction_intervals=PredictionIntervals())
            preds = nf.predict()
            forecasts[(hidden, layers)] = preds["NHITS"].to_numpy(dtype=float)
        except Exception as exc:  # noqa: BLE001 -- характеристика отказа
            kind = type(exc).__name__
            first = str(exc).splitlines()[0][:60]
            print(f"    ({hidden},{layers}): {kind}: {first}")
            feasible = False
    distinguishable = True
    combos = sorted(forecasts)
    for i, low in enumerate(combos):
        for high in combos[i + 1:]:
            diff = float(np.abs(forecasts[low] - forecasts[high]).max())
            if diff == 0.0:
                distinguishable = False
                print(f"    {low} vs {high}: max|diff| = 0.0 (СЛИЛИСЬ)")
    if distinguishable:
        print(f"    все {len(combos)} комбинаций попарно различимы (max|diff| > 0)")
    verdict = feasible and distinguishable
    print(f"  ИТОГ F2': pair-маппинг "
          f"{'ИСПОЛНИМ И РАЗЛИЧИМ' if verdict else 'НЕ ОК'}")
    return verdict


def section_f3_horizon_one() -> bool:
    print("== Секция 4: F3' -- horizon=1 и стеки (NBEATS interpretable/generic, NHITS) ==")
    n = 60
    outcomes: dict[str, str] = {}

    probes = (
        ("NBEATS interpretable h=1", "NBEATS", 1, {
            "stack_types": ["trend", "seasonality"], "n_blocks": [1, 1],
            "mlp_units": [[32, 32], [32, 32]],
        }),
        ("NBEATS interpretable h=2", "NBEATS", 2, {
            "stack_types": ["trend", "seasonality"], "n_blocks": [1, 1],
            "mlp_units": [[32, 32], [32, 32]],
        }),
        ("NBEATS generic h=1", "NBEATS", 1, {
            "stack_types": ["identity", "identity"], "n_blocks": [1, 1],
            "mlp_units": [[32, 32], [32, 32]], "basis": "polynomial",
        }),
        ("NBEATS generic h=2", "NBEATS", 2, {
            "stack_types": ["identity", "identity"], "n_blocks": [1, 1],
            "mlp_units": [[32, 32], [32, 32]], "basis": "polynomial",
        }),
        ("NHITS h=1", "NHITS", 1, {
            "n_pool_kernel_size": [2, 2, 1], "n_freq_downsample": [4, 2, 1],
            "mlp_units": [[32, 32], [32, 32]],
        }),
    )
    for label, kind, horizon, extra in probes:
        try:
            outcome = _direct_library_fit(kind, n, 24, horizon, extra_kwargs=extra)
        except Exception as exc:  # noqa: BLE001 -- характеристика отказа
            outcome = f"{type(exc).__name__}: {str(exc).splitlines()[0][:72]}"
        outcomes[label] = outcome
        print(f"  {label}: {outcome}")

    interpretable_h1_raw = not outcomes["NBEATS interpretable h=1"].startswith("OK")
    interpretable_h2_ok = outcomes["NBEATS interpretable h=2"].startswith("OK")
    generic_h1_ok = outcomes["NBEATS generic h=1"].startswith("OK")
    nhits_h1_ok = outcomes["NHITS h=1"].startswith("OK")
    verdict = interpretable_h1_raw and interpretable_h2_ok and generic_h1_ok and nhits_h1_ok
    print(f"  ИТОГ F3': interpretable h=1 сырой отказ={interpretable_h1_raw}, "
          f"h=2 OK={interpretable_h2_ok}, generic h=1 OK={generic_h1_ok}, "
          f"NHITS h=1 OK={nhits_h1_ok} -> "
          f"{'гейт только для interpretable' if (interpretable_h1_raw and generic_h1_ok and nhits_h1_ok) else 'СМОТРИ ЭМПИРИКУ'}")
    return verdict


def main() -> int:
    ok1 = section_f1_formula_stability()
    section_f2_dead_knobs_through_adapter()
    ok3 = section_f2_new_pair_mapping()
    ok4 = section_f3_horizon_one()
    print(f"PROBE {'OK' if (ok1 and ok3 and ok4) else 'WITH FINDINGS'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
