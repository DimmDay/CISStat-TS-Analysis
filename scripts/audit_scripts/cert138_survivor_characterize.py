# scripts/audit_scripts/cert138_survivor_characterize.py
"""Task 138 certification -- survivor characterization (subprocess probes).

Lesson learned: in-process probes re-import the module ONCE at startup, so
mutating the file on disk does NOT change behavior of an already-imported
module.  Every probe here therefore runs in a FRESH python subprocess
(`--probe NAME`), guaranteeing the mutated file is actually executed.

Survivors (full neural suite 51 passed under each mutation -- already
established): M6 bool coercion, M10 clamp invariant, M18 max_steps override,
M20 future frame validation skip.

Verdict classes:
  EQUIVALENT   -- another independent layer keeps fail-closed outcome.
  DEFENSIVE    -- live gate unreachable by happy-path tests (fault-injected
                  here); recommend an injection unit test.
  COVERAGE GAP -- real behavioral change no test/oracle catches.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

LSTM = ROOT / "apps/api/model_impls/lstm.py"
BAK = Path(str(LSTM) + ".surv_bak")
PY = sys.executable


def backup() -> None:
    shutil.copyfile(LSTM, BAK)


def restore() -> None:
    shutil.copyfile(BAK, LSTM)


def clean_check() -> bool:
    ok = LSTM.read_bytes() == BAK.read_bytes()
    BAK.unlink()
    return ok


def swap(old: str, new: str) -> bool:
    text = LSTM.read_text(encoding="utf-8")
    if old not in text:
        return False
    LSTM.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


# ── probes (run in fresh subprocess) ───────────────────────────────────────

def series_a(n: int, seed: int = 20260913) -> list[float]:
    rng = np.random.default_rng(seed)
    return [
        float(200.0 + 0.12 * step + 5.0 * np.sin(2.0 * np.pi * step / 24.0)
              + rng.standard_normal() * 0.5)
        for step in range(n)
    ]


def labels_a(n: int) -> list[str]:
    return [v.isoformat() for v in pd.date_range("2023-03-01", periods=n, freq="D")]


def fp(**overrides):
    payload = dict(
        target=series_a(120), horizon=7,
        params={"max_steps": 6, "input_size": 24, "encoder_hidden_size": 16},
        random_state=20260913,
        train_timestamps=labels_a(120),
        future_timestamps=labels_a(127)[120:],
    )
    payload.update(overrides)
    from apps.api.model_impls.lstm import _lstm_fit_predict
    return _lstm_fit_predict(**payload)


def probe_bool() -> None:
    from apps.api.model_impls.lstm import validate_lstm_params
    for handle in ("input_size", "max_steps", "encoder_n_layers"):
        try:
            normalized = validate_lstm_params({handle: True})
            print(f"BOOL {handle}=True -> ACCEPTED as {normalized[handle]!r}")
        except ValueError as exc:
            print(f"BOOL {handle}=True -> ValueError: {str(exc)[:60]}")


def probe_clamp() -> None:
    import apps.api.model_impls.lstm as lstm_mod

    real = lstm_mod.train_and_forecast

    def broken(*args, **kwargs):
        predictions = real(*args, **kwargs)
        point_cols = [c for c in predictions.columns if c in ("LSTM", "GRU")]
        lo_col = [c for c in predictions.columns if "-lo-" in c][0]
        predictions.iloc[0, predictions.columns.get_loc(lo_col)] = (
            predictions.iloc[0][point_cols[0]] + 10.0  # lower > point
        )
        return predictions

    lstm_mod.train_and_forecast = broken
    try:
        payload = fp(params={"max_steps": 6})
        mx = float(np.max(np.asarray(payload["lower"])
                          - np.asarray(payload["forecast"])))
        print(f"CLAMP NO-RAISE payload returned, max(lower-point)={mx:.4f}")
    except Exception as exc:
        print(f"CLAMP RAISED {type(exc).__name__}: {str(exc)[:80]}")
    finally:
        lstm_mod.train_and_forecast = real


def probe_budget() -> None:
    captured: dict = {}
    from apps.api.model_impls.neural_runtime import require_neuralforecast

    nf_module = require_neuralforecast()
    real_cls = nf_module.models.LSTM

    class Spy(real_cls):  # noqa: N801 -- probe-local subclass
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    nf_module.models.LSTM = Spy
    try:
        payload = fp(params={"max_steps": 7})
        meta = payload["neural"]["config"]["max_steps"]
        got = captured.get("max_steps")
        print(f"BUDGET metadata={meta} constructor_received={got!r} "
              f"wiring_ok={got == 7}")
    except Exception as exc:
        print(f"BUDGET probe error {type(exc).__name__}: {str(exc)[:80]}")
    finally:
        nf_module.models.LSTM = real_cls


def probe_future() -> None:
    for tag, values in (
        ("SHORT", [1.0] * 4),
        ("NAN", [1.0, 0.0, 0.0, 0.0, 0.0, float("nan"), 0.0]),
        ("INF", [float("inf")] + [0.0] * 6),
    ):
        try:
            payload = fp(
                train_features={"promo": [0.0] * 120},
                future_features={"promo": values},
            )
            finite = bool(np.isfinite(payload["forecast"]).all())
            print(f"FUTURE {tag} NO-RAISE forecast_finite={finite} "
                  f"forecast[0]={payload['forecast'][0]:.4f}")
        except Exception as exc:
            print(f"FUTURE {tag} RAISED {type(exc).__name__}: {str(exc)[:80]}")


PROBES = {"bool": probe_bool, "clamp": probe_clamp,
          "budget": probe_budget, "future": probe_future}

# ── mutation definitions (anchors identical to cert138_mutations.py) ───────

MUT = {
    "M6": ("        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):",
           "        if not isinstance(value, (int, np.integer)):"),
    "M10": ("    if not (\n        (lower <= forecast).all() and (forecast <= upper).all()\n    ):\n        raise NeuralContractError(",
            "    if False:\n        raise NeuralContractError("),
    "M18": ("            futr_exog_list=list(plan.futr_exog_list),\n            alias=alias,\n            **dict(budget),",
            "            futr_exog_list=list(plan.futr_exog_list),\n            alias=alias,\n            **{**dict(budget), 'max_steps': 1},"),
    "M20": ("        validate_future_exogenous_frame(\n            plan, futr_df, n_series=1, horizon=int(horizon),\n        )",
            "        pass"),
}

PLAN = [("M6", "bool"), ("M10", "clamp"), ("M18", "budget"), ("M20", "future")]


def run_probe(name: str) -> str:
    res = subprocess.run([PY, __file__, "--probe", name], cwd=ROOT,
                         capture_output=True, text=True)
    lines = [line for line in (res.stdout + res.stderr).splitlines()
             if line.startswith(("BOOL", "CLAMP", "BUDGET", "FUTURE"))]
    return "\n".join(lines) if lines else f"(no probe output, rc={res.returncode})"


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--probe":
        PROBES[sys.argv[2]]()
        return 0

    for mid, probe_name in PLAN:
        old, new = MUT[mid]
        print(f"\n== {mid} ==")
        print("-- PRISTINE (fresh subprocess) --")
        print(run_probe(probe_name))
        backup()
        try:
            if not swap(old, new):
                print("  ANCHOR NOT FOUND")
                continue
            print("-- MUTATED (fresh subprocess) --")
            print(run_probe(probe_name))
        finally:
            restore()
        print(f"CLEAN: {clean_check()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
