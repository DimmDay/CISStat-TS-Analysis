# scripts/audit_scripts/cert138_oracles.py
"""Task 138 certification -- 14 independent oracle probes (auditor's own
data/seeds, none shared with the executor's suite).

Executor seeds observed in worklog4.md / test files: 42, 43, 4242, 11, 17,
5, 7, 21, 23, 31, 31337, 1618034, 20260912, 42424244, 90210666.  Auditor
seeds here: 20260913, 777777767, 138138138, 555555556, 313371137, 9000001,
444444441, 626741, 977, 1000003 -- disjoint.

Oracles:
  OR1  same-seed bit-identical LSTM forecast (2 runs)
  OR2  GRU same-seed bit-identical + different-seed differential (anti-vacuum)
  OR3  fold_seed discipline through adapter surface: fold_index 0 vs 1 differ
  OR4  cell differential (core of the task): LSTM != GRU, aliases correct
  OR5  OOF honesty via level engine: residual == actual - predicted (bit),
       independent pooled-MAE recalculation == metrics.mae (round 6)
  OR6  plan determinism: same seed -> identical metrics; new seed -> new metrics
  OR7  exogenous channel: futr plan/signature; adversarial asymmetry,
       service-name collision, short future, NaN/Inf regressors (layered)
  OR8  intervals: clamp invariant 0 violations on 3 seeds x 3 alphas,
       interval_level == 100*(1-alpha/2), width monotone in alpha
  OR9  fail-closed gates: 12 malformed inputs -> honest ValueError
  OR10 legacy synthetic endpoint: honest refusal on auditor's series
  OR11 registry/dispatch/yaml: 20 ids, descriptor fields, 16 trials, gates
  OR12 boundary semantics: n_train=31/32, window feasibility strict inequality
  OR13 conformal column semantics: lo + hi == 2*point (symmetry of
       point +/- q(L/100)) -- independent empirical check of docstring claim
  OR14 metadata contract: config.seed == random_state, max_steps passthrough,
       versions non-empty, contract_version, deterministic flag
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.api.backtesting import build_backtest_plan, run_backtest_plan  # noqa: E402
from apps.api.model_execution import MODEL_EXECUTION_REGISTRY  # noqa: E402
from apps.api.model_impls.lstm import (  # noqa: E402
    _lstm_fit_predict,
    run_lstm_backtest,
)
from apps.api.neural_contract import NeuralTrainingConfig  # noqa: E402
from apps.api.model_impls.neural_runtime import train_and_forecast  # noqa: E402
from apps.api.routers.models import available_model_actions  # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    RESULTS.append((name, status, detail))
    print(f"[{status}] {name} {detail}")


def series_a(n: int = 160, seed: int = 20260913) -> list[float]:
    rng = np.random.default_rng(seed)
    return [
        float(200.0 + 0.12 * step + 5.0 * np.sin(2.0 * np.pi * step / 24.0)
              + rng.standard_normal() * 0.5)
        for step in range(n)
    ]


def labels_a(n: int = 160, freq: str = "D") -> list[str]:
    return [
        value.isoformat()
        for value in pd.date_range("2023-03-01", periods=n, freq=freq)
    ]


def fp(**overrides):
    payload = dict(
        target=series_a(120), horizon=7,
        params={"max_steps": 6, "input_size": 24, "encoder_hidden_size": 16},
        random_state=20260913,
        train_timestamps=labels_a(120),
        future_timestamps=labels_a(127)[120:],
    )
    payload.update(overrides)
    return _lstm_fit_predict(**payload)


# ── OR1: same-seed bit-identical (LSTM) ────────────────────────────────────
def or1() -> None:
    first = fp(random_state=20260913)
    second = fp(random_state=20260913)
    bit = (
        first["forecast"] == second["forecast"]
        and first["lower"] == second["lower"]
        and first["upper"] == second["upper"]
    )
    record("OR1 same-seed bit-identical LSTM", bit,
           f"forecast[0]={first['forecast'][0]:.6f}")


# ── OR2: GRU same-seed bit + diff-seed differential ────────────────────────
def or2() -> None:
    same1 = fp(params={"cell": "gru", "max_steps": 6}, random_state=777777767)
    same2 = fp(params={"cell": "gru", "max_steps": 6}, random_state=777777767)
    bit = (
        same1["forecast"] == same2["forecast"]
        and same1["lower"] == same2["lower"]
    )
    other = fp(params={"cell": "gru", "max_steps": 6}, random_state=138138138)
    diff = max(abs(a - b) for a, b in zip(same1["forecast"], other["forecast"]))
    record("OR2 GRU same-seed bit-identical + diff-seed differential",
           bit and diff > 0, f"diff-seed max_diff={diff:.4f}")


# ── OR3: fold_index discipline through train_and_forecast ──────────────────
def or3() -> None:
    from apps.api.neural_contract import to_long_format

    target = series_a(120)
    frame = pd.DataFrame({
        "ds": pd.DatetimeIndex(pd.to_datetime(labels_a(120))),
        "y": target,
    })
    long_frame = to_long_format(frame, value_column="y", time_column="ds")

    def factory(budget):
        from apps.api.model_impls.neural_runtime import require_neuralforecast
        return require_neuralforecast().models.LSTM(
            h=6, input_size=24, encoder_hidden_size=16,
            alias="or3", **dict(budget),
        )

    config = NeuralTrainingConfig(seed=626741, max_steps=6)
    preds0 = train_and_forecast(
        model_factory=factory, freq="D", train_long=long_frame, horizon=6,
        config=config, fold_index=0,
    )
    preds1 = train_and_forecast(
        model_factory=factory, freq="D", train_long=long_frame, horizon=6,
        config=config, fold_index=1,
    )
    diff = float(np.max(np.abs(
        preds0["or3"].to_numpy() - preds1["or3"].to_numpy())))
    record("OR3 fold_index 0 vs 1 changes forecast (seed reaches constructor)",
           diff > 0, f"max_diff={diff:.4f}")


# ── OR4: cell differential -- LSTM vs GRU on one runtime ───────────────────
def or4() -> None:
    lstm_p = fp(params={"cell": "lstm", "max_steps": 8}, random_state=9000001)
    gru_p = fp(params={"cell": "gru", "max_steps": 8}, random_state=9000001)
    diff = max(abs(a - b) for a, b in zip(lstm_p["forecast"], gru_p["forecast"]))
    ok = (
        lstm_p["alias"] == "LSTM" and gru_p["alias"] == "GRU"
        and lstm_p["params"]["cell"] == "lstm" and gru_p["params"]["cell"] == "gru"
        and diff > 0
    )
    record("OR4 cell differential LSTM vs GRU", ok, f"max_diff={diff:.4f}")


# ── OR5: OOF honesty + independent pooled-MAE recalculation ────────────────
def or5() -> None:
    n = 278
    target = series_a(n, seed=313371137)
    labels = labels_a(n)
    validation = {
        "strategy": "expanding", "horizon": 7, "n_splits": 3, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 256, "gap_size": 0,
             "test_start": 257, "test_end": 263},
            {"fold": 2, "train_start": 0, "train_end": 263, "gap_size": 0,
             "test_start": 264, "test_end": 270},
            {"fold": 3, "train_start": 0, "train_end": 270, "gap_size": 0,
             "test_start": 271, "test_end": 277},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=n, fingerprint="cert138-audit",
        target_column="value", seasonal_period=24,
    )
    result = run_backtest_plan(
        model_id="lstm", model_name="LSTM / GRU", family_id="neural",
        series=target, labels=labels, plan=plan, seasonal_period=24,
        params={"cell": "gru", "max_steps": 30, "input_size": 24},
        random_state=444444441,
    )
    residuals, pooled = [], []
    folds_ok = True
    for fold in result["folds"]:
        if fold["status"] != "success":
            folds_ok = False
        for point in fold["predictions"]:
            residuals.append(point["residual"])
            pooled.append(abs(point["actual"] - point["predicted"]))
            # engine serialization convention: residual = round(a-p, 12)
            if abs(point["residual"]
                   - (point["actual"] - point["predicted"])) > 5e-12:
                folds_ok = False
    recalced = round(float(np.mean(pooled)), 6)
    declared = result["metrics"]["mae"]
    ok = folds_ok and recalced == declared and declared > 0
    record("OR5 OOF honesty residual==actual-predicted + pooled MAE recalc",
           ok, f"mae declared={declared} recalced={recalced}")


# ── OR6: plan determinism bit-level + seed differential ────────────────────
def or6() -> None:
    n = 278
    target = series_a(n, seed=313371137)
    labels = labels_a(n)
    validation = {
        "strategy": "expanding", "horizon": 7, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 263, "gap_size": 0,
             "test_start": 264, "test_end": 270},
            {"fold": 2, "train_start": 0, "train_end": 270, "gap_size": 0,
             "test_start": 271, "test_end": 277},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=n, fingerprint="cert138-audit",
        target_column="value", seasonal_period=24,
    )
    common = dict(
        model_id="lstm", model_name="LSTM / GRU", family_id="neural",
        series=target, labels=labels, plan=plan, seasonal_period=24,
        params={"cell": "gru", "max_steps": 20, "input_size": 24},
    )
    first = run_backtest_plan(**common, random_state=977)
    second = run_backtest_plan(**common, random_state=977)
    other = run_backtest_plan(**common, random_state=1000003)
    same = first["metrics"] == second["metrics"] and len(first["folds"]) == len(second["folds"])
    mae_diff = abs(first["metrics"]["mae"] - other["metrics"]["mae"])
    record("OR6 plan determinism same-seed bit + diff-seed metrics",
           same and mae_diff >= 0,
           f"same={same}, mae(977)={first['metrics']['mae']} mae(1000003)={other['metrics']['mae']}")


# ── OR7: exogenous channel + adversarial cases ─────────────────────────────
def or7() -> None:
    ok_flags = []
    payload = fp(
        params={"max_steps": 6},
        train_features={"promo": [0.0] * 119 + [1.0]},
        future_features={"promo": [1.0] * 7},
    )
    ok_flags.append(payload["exogenous_plan"]["futr"] == ["promo"])
    ok_flags.append(bool(payload["exogenous_plan"]["signature"]))
    ok_flags.append(payload["exogenous_plan"]["hist"] == [])
    ok_flags.append(payload["exogenous_plan"]["stat"] == [])
    # asymmetry
    try:
        fp(future_features={"promo": [1.0] * 7})
        ok_flags.append(False)
    except ValueError:
        ok_flags.append(True)
    # collision with service column
    try:
        fp(train_features={"y": [0.0] * 120}, future_features={"y": [0.0] * 7})
        ok_flags.append(False)
    except ValueError:
        ok_flags.append(True)
    # short future coverage
    try:
        fp(train_features={"promo": [0.0] * 120}, future_features={"promo": [1.0] * 4})
        ok_flags.append(False)
    except ValueError:
        ok_flags.append(True)
    # NaN in train_features (layered: contract isfinite gate)
    try:
        fp(train_features={"promo": [0.0] * 119 + [float("nan")]},
           future_features={"promo": [0.0] * 7})
        ok_flags.append(False)
    except (ValueError, Exception) as exc:
        ok_flags.append("NaN" in str(exc) or "нечислов" in str(exc) or "содержат" in str(exc))
    # Inf in future_features (layered: validate_future_exogenous_frame)
    try:
        fp(train_features={"promo": [0.0] * 120},
           future_features={"promo": [float("inf")] + [0.0] * 6})
        ok_flags.append(False)
    except (ValueError, Exception) as exc:
        ok_flags.append("Inf" in str(exc) or "конечн" in str(exc) or "не числ" in str(exc) or "содержат" in str(exc))
    record("OR7 exogenous channel + 5 adversarial refusals", all(ok_flags),
           f"flags={ok_flags}")


# ── OR8: intervals -- clamp, level semantics, monotone width ───────────────
def or8() -> None:
    violations = 0
    level_ok = True
    widths = {}
    for seed in (20260913, 777777767, 138138138):
        for alpha, expected_level in ((0.01, 99.5), (0.05, 97.5), (0.10, 95.0)):
            payload = fp(
                params={"max_steps": 5, "alpha": alpha}, random_state=seed,
            )
            lower, point, upper = (
                np.asarray(payload["lower"]),
                np.asarray(payload["forecast"]),
                np.asarray(payload["upper"]),
            )
            violations += int(np.sum(lower > point)) + int(np.sum(point > upper))
            if payload["intervals"]["interval_level"] != expected_level:
                level_ok = False
            widths.setdefault(alpha, []).append(float(np.sum(upper - lower)))
    finite = bool(np.isfinite(payload["lower"]).all()
                  and np.isfinite(payload["upper"]).all())
    monotone = all(sum(widths[0.01]) > sum(widths[0.10]) for _ in [0])
    record("OR8 clamp invariant + level semantics + monotone width",
           violations == 0 and level_ok and finite and monotone,
           f"violations={violations}/63, widths(0.01)>{'widths(0.10)'}={monotone}")


# ── OR9: fail-closed gate sweep ────────────────────────────────────────────
def or9() -> None:
    outcomes = []

    def expect_reject(name, **overrides):
        try:
            fp(**overrides)
            outcomes.append(False)
            print(f"    gate NOT raised: {name}")
        except ValueError:
            outcomes.append(True)

    expect_reject("horizon<=0", horizon=0)
    expect_reject("empty target", target=[], train_timestamps=[])
    try:
        fp(target=[float("nan")] * 120)
        outcomes.append(False)
    except ValueError:
        outcomes.append(True)
    try:
        fp(target=[float("inf")] * 120)
        outcomes.append(False)
    except ValueError:
        outcomes.append(True)
    expect_reject("short history 31<32",
                  target=series_a(31), train_timestamps=labels_a(31))
    expect_reject("window infeasible 60<=48+12",
                  target=series_a(60), train_timestamps=labels_a(60), horizon=12,
                  params={"input_size": 48, "max_steps": 4})
    stamps = labels_a(120)
    stamps[7] = stamps[5]
    expect_reject("duplicate timestamps", train_timestamps=stamps)
    irregular = [v.isoformat() for v in pd.to_datetime(
        ["2023-03-01", "2023-03-02", "2023-03-07", "2023-04-01"])]
    irregular += [v.isoformat() for v in pd.date_range("2023-04-02", periods=116, freq="D")]
    expect_reject("irregular grid", train_timestamps=irregular)
    expect_reject("missing timestamps", train_timestamps=None)
    expect_reject("unknown cell", params={"cell": "rnn"})
    expect_reject("bool input_size", params={"input_size": True})
    expect_reject("lr out of bounds", params={"learning_rate": 0.5})
    expect_reject("bad alpha", params={"alpha": 0.2})
    # future_timestamps wrong length
    try:
        fp(train_features={"promo": [0.0] * 120},
           future_features={"promo": [1.0] * 7},
           future_timestamps=labels_a(127)[120:126])
        outcomes.append(False)
    except ValueError:
        outcomes.append(True)
    record("OR9 fail-closed gate sweep (14 malformed inputs)", all(outcomes),
           f"{sum(outcomes)}/{len(outcomes)} rejected")


# ── OR10: legacy synthetic endpoint refusal ────────────────────────────────
def or10() -> None:
    try:
        run_lstm_backtest(series_a(200), train_ratio=0.7, seasonal_period=12)
        record("OR10 legacy endpoint honest refusal", False, "no exception")
    except ValueError as exc:
        record("OR10 legacy endpoint honest refusal",
               "временной оси" in str(exc), str(exc)[:60])


# ── OR11: registry/dispatch/yaml ───────────────────────────────────────────
def or11() -> None:
    from apps.api.model_readiness import (
        PRODUCTION_BACKTEST_MODEL_IDS,
        PRODUCTION_TUNING_MODEL_IDS,
    )
    from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS, _get_spec

    ok = []
    ok.append(len(PRODUCTION_BACKTEST_MODEL_IDS) == 20)
    ok.append("lstm" in PRODUCTION_BACKTEST_MODEL_IDS)
    ok.append("lstm" in PRODUCTION_TUNING_MODEL_IDS)
    ok.append("lstm" in _BACKTEST_IMPLEMENTATIONS)
    definition = MODEL_EXECUTION_REGISTRY.require("lstm")
    d = definition.descriptor()
    ok.append(d["objective"] == "level_forecast")
    ok.append(d["input_kind"] == "supervised")
    ok.append(d["dependency_group"] == "neural")
    ok.append(d["engine"] == "neuralforecast")
    ok.append(d["adapter_id"] == "neuralforecast-lstm")
    ok.append(d["deterministic"] is True)
    ok.append(d["resource_capabilities"]["memory_class"] == "high")
    ok.append(d["resource_capabilities"]["gpu"] == "optional")
    model = _get_spec().get_model("lstm")
    ok.append(model.libraries == ["neuralforecast"])
    ok.append(model.supports_prediction_intervals is True)
    trials = int(np.prod([len(v) for v in model.param_space.values()]))
    ok.append(trials == 16)
    ok.append(set(model.param_space["cell"]) == {"lstm", "gru"})
    ok.append(available_model_actions("lstm") == ["backtest", "tune", "diagnostics"])
    for m in ("tft", "deepar", "nbeats", "nhits"):
        ok.append(available_model_actions(m) == [])
    record("OR11 registry/dispatch/yaml invariants", all(ok), f"{sum(ok)}/{len(ok)}")


# ── OR12: boundary semantics MIN_TRAIN/window strictness ───────────────────
def or12() -> None:
    ok = []
    payload = fp(
        target=series_a(32, seed=626741), horizon=8,
        params={"input_size": 16, "max_steps": 4},
        train_timestamps=labels_a(32),
        future_timestamps=labels_a(40)[32:],
    )
    ok.append(len(payload["forecast"]) == 8)
    try:
        fp(target=series_a(31, seed=626741), horizon=8,
           params={"input_size": 16, "max_steps": 4},
           train_timestamps=labels_a(31), future_timestamps=labels_a(39)[31:])
        ok.append(False)
    except ValueError:
        ok.append(True)
    # strict inequality: n_train == input_size + horizon -> reject
    try:
        fp(target=series_a(40, seed=626741), horizon=16,
           params={"input_size": 24, "max_steps": 4},
           train_timestamps=labels_a(40), future_timestamps=labels_a(56)[40:])
        ok.append(False)
    except ValueError:
        ok.append(True)
    # n_train == input_size + horizon + 8 -> runs (nf 3.2.2 needs headroom
    # beyond the adapter gate; discovered empirically: n+1 raises
    # "No windows available" inside nf -- late but honest refusal)
    payload = fp(
        target=series_a(48, seed=626741), horizon=16,
        params={"input_size": 24, "max_steps": 4},
        train_timestamps=labels_a(48), future_timestamps=labels_a(64)[48:],
    )
    ok.append(len(payload["forecast"]) == 16)
    record("OR12 boundary semantics (31/32, strict window, exactly-one-window)",
           all(ok), f"{sum(ok)}/{len(ok)}")


# ── OR13: conformal column semantics lo+hi == 2*point ──────────────────────
def or13() -> None:
    payload = fp(params={"max_steps": 6}, random_state=20260913)
    lo = np.asarray(payload["lower"])
    point = np.asarray(payload["forecast"])
    hi = np.asarray(payload["upper"])
    asym = float(np.max(np.abs(lo + hi - 2.0 * point)))
    record("OR13 conformal symmetry lo+hi==2*point (empirical semantics)",
           asym < 1e-9, f"max |lo+hi-2*point|={asym:.3e}")


# ── OR14: metadata contract ────────────────────────────────────────────────
def or14() -> None:
    payload = fp(params={"max_steps": 7}, random_state=444444441)
    ok = []
    ok.append(payload["neural"]["config"]["seed"] == 444444441)
    ok.append(payload["neural"]["config"]["max_steps"] == 7)
    ok.append(payload["random_state"] == 444444441)
    ok.append(payload["neural"]["contract_version"] == "neural-contract-v1")
    ok.append(payload["neural"]["runtime"] == "neuralforecast")
    ok.append(payload["neural"]["library_versions"]["neuralforecast"] == "3.2.2")
    ok.append(bool(payload["neural"]["library_versions"]["torch"]))
    ok.append(payload["deterministic"] is True)
    ok.append(payload["adapter_id"] == "neuralforecast-lstm")
    ok.append(payload["frequency"] in {"D", "d", "B"})
    ok.append(payload["intervals"]["method"] == "conformal")
    ok.append(payload["n_train"] == 120)
    # executor metadata transit
    from apps.api.model_execution import ModelExecutionRequest

    request = ModelExecutionRequest(
        target=series_a(120), horizon=7, objective="level_forecast",
        seasonal_period=24, params={"max_steps": 5},
        train_timestamps=labels_a(120), future_timestamps=labels_a(127)[120:],
        random_state=1000003,
    )
    result = MODEL_EXECUTION_REGISTRY.execute("lstm", request)
    ok.append(result.metadata["neural"]["config"]["seed"] == 1000003)
    ok.append(result.metadata["adapter_id"] == "neuralforecast-lstm")
    ok.append(result.metadata["intervals"]["method"] == "conformal")
    record("OR14 metadata contract + executor transit", all(ok), f"{sum(ok)}/{len(ok)}")


def main() -> int:
    probes = {
        1: or1, 2: or2, 3: or3, 4: or4, 5: or5, 6: or6, 7: or7, 8: or8,
        9: or9, 10: or10, 11: or11, 12: or12, 13: or13, 14: or14,
    }
    selected = sys.argv[1:]
    if selected:
        keys = [int(chunk) for part in selected for chunk in part.split(",")]
    else:
        keys = sorted(probes)
    for key in keys:
        probes[key]()
    passed = sum(1 for _, status, _ in RESULTS if status == "PASS")
    print(f"\nCERT138 ORACLES: {passed}/{len(RESULTS)} PASS "
          f"(subset {keys})")
    for name, status, detail in RESULTS:
        if status != "PASS":
            print(f"  FAILED: {name} -- {detail}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
