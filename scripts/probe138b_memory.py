# scripts/probe138b_memory.py
"""Task 138b-followup -- пробник времени/памяти нейро-бэктеста (диагностика HTTP 502 на Render).

Гипотезы 502 на free-инстансе Render (512 MB, ~0.1 CPU):
  (a) OOM: импорт torch+neuralforecast + fit в процессе API превышает 512 MB;
  (b) proxy-таймаут: один fit (max_steps=300) на слабом CPU дольше ~100 c.

Фазы запускаются В СВЕЖИХ subprocess'ах (см. driver ниже), чтобы ru_maxrss
каждой фазы был независим.  Стек фазы "fit" воспроизводит базовую
загрузку процесса API (fastapi/uvicorn/pydantic/pandas/numpy) ДО
нейро-импорта, как в проде.

Запуск: python scripts/probe138b_memory.py {baseline|nf_import|fit|fit_1thread}
"""
from __future__ import annotations

import json
import os
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / 1024.0, 1)  # Linux: KiB -> MiB


def main() -> None:
    phase = sys.argv[1] if len(sys.argv) > 1 else "baseline"

    # --- Базовая загрузка процесса API (есть в проде ДО нейро-работы) ---
    import numpy  # noqa: F401
    import pandas  # noqa: F401
    import pydantic  # noqa: F401
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401

    if phase == "baseline":
        print(json.dumps({"phase": phase, "peak_rss_mb": _rss_mb()}))
        return

    if phase == "nf_import":
        t0 = time.monotonic()
        import neuralforecast  # noqa: F401
        import torch

        dt = time.monotonic() - t0
        print(json.dumps({
            "phase": phase, "peak_rss_mb": _rss_mb(),
            "import_seconds": round(dt, 1),
            "torch_threads_default": torch.get_num_threads(),
        }))
        return

    if phase in {"fit", "fit_1thread", "fit_guarded", "fit_env_budget"}:
        if phase == "fit_1thread":
            import torch

            torch.set_num_threads(1)
            torch.set_num_interop_threads(1)

        if phase == "fit_guarded":
            # Симуляция free-инстанса Render (512 MB): guard обязан дать
            # честный NeuralRuntimeCapacityError ДО импорта torch (~9 c).
            import apps.api.neural_resources as nr

            nr.read_instance_memory_mb = lambda: 512
            from apps.api.model_impls.lstm import _lstm_fit_predict

            t0 = time.monotonic()
            try:
                _lstm_fit_predict([float(v) for v in range(1, 41)], 2, random_state=42)
            except Exception as exc:  # noqa: BLE001 -- печатаем честный отказ
                dt = time.monotonic() - t0
                print(json.dumps({
                    "phase": phase, "peak_rss_mb": _rss_mb(),
                    "seconds": round(dt, 1),
                    "error_type": type(exc).__name__,
                    "error_head": str(exc)[:120],
                }))
                return
            raise SystemExit("ОШИБКА: fit прошёл на 512MB-инстансе -- гейт мёртв")

        if phase == "fit_env_budget":
            os.environ["CISSTAT_NEURAL_MAX_STEPS"] = "120"

        # Аппарат: 240 наблюдений, ratio 0.8 -> 192 train / 48 test,
        # сезонный месячный профиль (как дефолтный бэктест UI).
        series = [
            100.0 + 0.3 * step + 5.0 * (2 ** (0.5 * (step % 12) / 12)) * __import__("math").sin(2 * 3.141592653589793 * step / 12)
            for step in range(240)
        ]
        n_train = int(len(series) * 0.8)
        y_train, y_test = series[:n_train], series[n_train:]

        t0 = time.monotonic()
        from apps.api.model_impls.lstm import _lstm_fit_predict

        payload = _lstm_fit_predict(y_train, len(y_test), random_state=42)
        dt = time.monotonic() - t0
        forecast = payload["forecast"]
        print(json.dumps({
            "phase": phase, "peak_rss_mb": _rss_mb(),
            "fit_seconds": round(dt, 1),
            "n_forecast": len(forecast),
            "max_steps": payload["params"].get("max_steps"),
        }))
        return

    raise SystemExit(f"unknown phase: {phase}")


if __name__ == "__main__":
    main()
