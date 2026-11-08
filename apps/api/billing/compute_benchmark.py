"""Seeded real PELT/tuning workloads and train/holdout calibration, never fake timings."""

import math, time
from decimal import Decimal, localcontext
from collections import defaultdict
from .compute_units import Workload, Coefficient, quote_work
from .compute_profile import Profile, machine, kernel_digest
from .contract import digest_payload


def validation(n, folds, horizon):
    first = n - folds * horizon
    return {
        "strategy": "expanding",
        "horizon": horizon,
        "n_splits": folds,
        "gap": 0,
        "folds": [
            {
                "fold": i + 1,
                "train_start": 0,
                "train_end": first + i * horizon - 1,
                "gap_size": 0,
                "test_start": first + i * horizon,
                "test_end": first + (i + 1) * horizon - 1,
            }
            for i in range(folds)
        ],
    }


def case_inputs(case):
    import numpy as np
    import pandas as pd

    n = case["rows"]
    rng = np.random.default_rng(case["seed"])
    index = np.arange(n)
    y = 100 + 0.02 * index + 4 * np.sin(2 * np.pi * index / 12) + rng.normal(0, 0.5, n)
    if case.get("scenario") == "breaks":
        y += 6 * ((index // max(8, n // 12)) % 2)
    if case["key"] == "pelt":
        from app.eda.structural_breaks import analyze_structural_breaks

        args = {
            "series": pd.Series(y),
            "min_segment": 5 if case.get("scenario") == "breaks" else 20,
            "penalty_multiplier": 2.0,
        }
        from .compute_runtime import pelt_work

        return analyze_structural_breaks, args, pelt_work(args)
    model = case["key"].split(":", 1)[1]
    from src.catalog.modeling_spec_loader import ModelingSpec
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
    from apps.api.backtesting import build_backtest_plan
    from apps.api import modeling_tuning as tuning
    from .compute_profile import ROOT

    spec = ModelingSpec.from_yaml(ROOT / "rules/modeling.yaml")
    model_spec = spec.get_model(model)
    if model_spec is None or not model_spec.param_space:
        raise ValueError("unsupported tunable model")
    descriptor = MODEL_EXECUTION_REGISTRY.describe(model)
    labels = [v.isoformat() for v in pd.date_range("2010-01-01", periods=n, freq="MS")]
    period = 12
    horizon = case["horizon"]
    folds = case["folds"]
    objective = "level_forecast"
    contract = None
    kwargs = {"series": y.tolist(), "labels": labels}
    target_fn = tuning.execute_tuning_plan_with_artifacts
    columns = 1
    if model in ("var", "vecm", "deepar"):
        from apps.api.multivariate_contract import (
            build_endogenous_system,
            multivariate_cohort_contract,
        )

        columns = 5 if model == "deepar" else 3
        common = 100 + np.cumsum(rng.normal(0, 1, n))
        data = {
            "value": common.tolist(),
            **{
                "related" + str(j): (
                    common * (1 + j * 0.1) + rng.normal(0, 0.2, n)
                ).tolist()
                for j in range(1, columns)
            },
        }
        system = build_endogenous_system(data, timestamps=labels)
        fingerprints = {name: "auth14:" + name for name in data}
        contract = multivariate_cohort_contract(
            system, series_fingerprints=fingerprints
        )
        objective = "multivariate"
        period = 1
        kwargs = {"system": system}
        target_fn = tuning.execute_vector_tuning_plan_with_artifacts
        if model == "deepar":
            from apps.api.neural_contract import (
                NeuralTrainingConfig,
                build_exogenous_plan,
                interval_levels_for_alpha,
                neural_cohort_contract,
            )

            contract = neural_cohort_contract(
                fingerprint="auth14",
                n_series=columns,
                min_series=5,
                exogenous=build_exogenous_plan(
                    pd.DataFrame({"unique_id": [], "ds": [], "y": []})
                ),
                interval=interval_levels_for_alpha(0.05),
                loss="mqloss",
                config=NeuralTrainingConfig(seed=case["seed"], max_steps=300),
            )
            target_fn = tuning.execute_panel_tuning_plan_with_artifacts
            objective = "level_forecast"
            period = 12
    elif model in ("garch", "egarch"):
        from apps.api.volatility_contract import (
            build_volatility_target,
            volatility_cohort_contract,
        )

        prices = (100 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, n + 1)))).tolist()
        target = build_volatility_target(
            prices, method="log", timestamps=[str(i) for i in range(n + 1)]
        )
        objective = "volatility"
        period = 1
        contract = volatility_cohort_contract(
            target_column="value",
            fingerprint="auth14",
            returns_method="log",
            n_returns=target.n_returns,
            seasonal_period=1,
        )
        kwargs = {"target": target}
        target_fn = tuning.execute_volatility_tuning_plan_with_artifacts
    plan = build_backtest_plan(
        validation(n, folds, horizon),
        n_observations=n,
        fingerprint="auth14",
        target_column="value",
        seasonal_period=period,
        objective=objective,
        cohort_contract_override=contract,
    )
    kwargs.update(
        model_id=model,
        model_name=model_spec.name,
        family_id=descriptor["family_id"],
        param_space=model_spec.param_space,
        plan=plan,
        seasonal_period=period,
        max_trials=case["trials"],
        metric="qlike" if objective == "volatility" else "mae",
        random_state=case["seed"],
    )
    from .compute_runtime import tuning_work

    work = tuning_work(kwargs)
    if work.columns != columns:
        raise ValueError("normalized dimensions disagree")
    return target_fn, kwargs, work


def execute_case(case):
    # Runs in a sanitized child; imported kernels are the production implementations.
    target, kwargs, work = case_inputs(case)
    from apps.api.backtesting import BacktestExecutionError
    from .compute_meter import CURRENT

    try:
        result = target(**kwargs)
    except BacktestExecutionError:
        if case["key"] == "pelt" or CURRENT.get() is None or CURRENT.get().units < 1:
            raise
        return {
            "work": work.model_dump(mode="json"),
            "result": {
                "successful_trials": 0,
                "selected_trials": work.trials,
                "folds": work.folds,
                "outcome": "numerical_trial_failure",
            },
        }
    if case["key"] == "pelt":
        if not result["applicable"]:
            raise ValueError("PELT benchmark not applicable")
        summary = {
            "n_breaks": len(result["candidates"]),
            "jump": max(1, math.ceil(work.rows / 250)),
            "grid_points": work.grid_points,
        }
    else:
        summary = {
            "successful_trials": result.response.n_trials,
            "selected_trials": work.trials,
            "folds": work.folds,
        }
        if result.response.n_trials < 1:
            raise ValueError("no successful tuning trial")
    return {"work": work.model_dump(mode="json"), "result": summary}


def measure(case, *, timeout=120, memory_mb=1024):
    from apps.api.workers.process import run_bounded, WorkStopped, WorkFailed

    target, kwargs, work = case_inputs(case)
    # Data/plan construction outside measured child CPU is intentionally reported.
    started = time.monotonic_ns()
    try:
        result, proof = run_bounded(
            execute_case,
            (case,),
            timeout=timeout,
            memory_mb=memory_mb,
            work_key=work.key,
            work_limit=work.units,
        )
        if not proof.usage or proof.usage["units"] < 1:
            raise ValueError("no real fits measured")
        return {
            "case": case,
            "status": "ok",
            "work": result["work"],
            "result": result["result"],
            "usage": proof.usage,
            "metrics": {
                **proof.metrics,
                "parent_wall_ns": time.monotonic_ns() - started,
            },
        }
    except (WorkStopped, WorkFailed, ValueError) as exc:
        return {
            "case": case,
            "status": "failed",
            "code": getattr(exc, "code", type(exc).__name__),
        }


def calibrate(report):
    if report["schema_version"] != "auth14.benchmark/1":
        raise ValueError("unknown benchmark schema")
    if report["environment"] != machine() or report["kernels"] != kernel_digest():
        raise ValueError("benchmark environment changed during or since measurement")
    rows = report["samples"]
    if not rows or any(s["status"] != "ok" for s in rows):
        raise ValueError("incomplete benchmark cannot be activated")
    grouped = defaultdict(list)
    for sample in rows:
        work = Workload.model_validate(sample["work"])
        usage = sample["usage"]
        if (
            usage["key"] != work.key
            or type(usage["units"]) is not int
            or not 1 <= usage["units"] <= work.units
        ):
            raise ValueError("invalid actual work measurement")
        if any(
            type(sample["metrics"].get(k)) is not int or sample["metrics"][k] <= 0
            for k in ("cpu_ns", "parent_wall_ns", "rss_peak_bytes")
        ):
            raise ValueError("missing finite resource measurements")
        grouped[sample["case"]["key"]].append(sample)
    if set(grouped) != set(report["requested_keys"]):
        raise ValueError("missing operation measurements")
    coefficients = []
    checks = []
    for key, samples in sorted(grouped.items()):
        train = [s for s in samples if not s["case"]["holdout"]]
        hold = [s for s in samples if s["case"]["holdout"]]
        if len({s["work"]["rows"] for s in train}) < 3 or not hold:
            raise ValueError("three training sizes and independent holdout required")
        if {s["case"]["seed"] for s in train} & {s["case"]["seed"] for s in hold}:
            raise ValueError("holdout seed leaked into calibration")
        if key != "pelt" and not any(
            s["result"].get("successful_trials", 0) > 0 for s in samples
        ):
            raise ValueError("no successful production trial for operation")
        xs = [math.log(Workload.model_validate(s["work"]).volume) for s in train]
        ys = [
            math.log(s["metrics"]["cpu_ns"] / 1000 / s["usage"]["units"]) for s in train
        ]
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        variance = sum((x - mean_x) ** 2 for x in xs)
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / variance
        exponent = Decimal(str(max(0, min(3, math.ceil(slope * 4) / 4))))
        with localcontext() as ctx:
            ctx.prec = 60
            base = (
                max(
                    Decimal(s["metrics"]["cpu_ns"])
                    / 1000
                    / Decimal(s["usage"]["units"])
                    / (Decimal(Workload.model_validate(s["work"]).volume) ** exponent)
                    for s in train
                )
                * 2
            )
            base = base.quantize(Decimal("0.000000000000000001"))
        peak = max(s["metrics"].get("rss_peak_bytes") or 0 for s in samples)
        if peak <= 0:
            raise ValueError("mandatory peak memory measurement unavailable")
        max_work = lambda name: max(s["work"][name] for s in samples)
        # Bounds are measured envelope × explicit 2x CPU / 3x wall / 1.5x RSS margins.
        c = Coefficient(
            key=key,
            base_micro_cu=base,
            exponent=exponent,
            min_rows=min(s["work"]["rows"] for s in samples),
            max_rows=max_work("rows"),
            max_columns=max_work("columns"),
            max_units=max_work("units"),
            max_horizon=max_work("horizon"),
            max_period=max_work("seasonal_period"),
            max_folds=max_work("folds"),
            max_trials=max_work("trials"),
            wall_ms=min(
                report["timeout_seconds"] * 1000,
                math.ceil(
                    max(s["metrics"]["parent_wall_ns"] for s in samples) / 1e6 * 3
                ),
            ),
            memory_mb=min(report["memory_mb"], math.ceil(peak / 1048576 * 1.5)),
        )
        for sample in samples:
            q = quote_work(
                Workload.model_validate(sample["work"]), c, profile_hash="0" * 64
            )
            measured = math.ceil(sample["metrics"]["cpu_ns"] / 1000)
            estimated = q.unit_micro_cu * sample["usage"]["units"]
            if measured > estimated:
                raise ValueError(
                    "holdout cost exceeds calibrated envelope; expand measurements"
                )
            checks.append(
                {
                    "key": key,
                    "holdout": sample["case"]["holdout"],
                    "measured_cpu_microseconds": measured,
                    "quoted_attempted_micro_cu": estimated,
                }
            )
        coefficients.append(c)
    capacity = report["load_test"]
    if len(capacity["samples"]) != capacity["concurrency"] or any(
        s["status"] != "ok" for s in capacity["samples"]
    ):
        raise ValueError("capacity load test failed")
    for sample in capacity["samples"]:
        coefficient = next(c for c in coefficients if c.key == sample["case"]["key"])
        if sample["metrics"]["parent_wall_ns"] > coefficient.wall_ms * 1000000:
            raise ValueError("tested capacity exceeds runtime wall bound")
    memory_limit = report["environment"]["memory_limit_bytes"]
    memory_reserved = (
        max(s["metrics"]["rss_peak_bytes"] for s in [*rows, *capacity["samples"]])
        * capacity["concurrency"]
        * 1.5
        + report["reserve_memory_mb"] * 1048576
    )
    if not memory_limit or memory_reserved > memory_limit:
        raise ValueError("insufficient measured memory headroom")
    profile = Profile(
        environment=report["environment"],
        kernels=report["kernels"],
        evidence_digest=digest_payload(report),
        coefficients=tuple(coefficients),
        max_concurrency=capacity["concurrency"],
    )
    return profile, checks
