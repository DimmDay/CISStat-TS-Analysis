# scripts/audit_scripts/cert138_mutations.py
"""Task 138 certification -- mutation probes.

Precedent cert136/cert137: each mutation is applied in memory on disk,
checked against a TARGETED pytest subset (expect RED), reverted from a
pre-saved copy, and the revert is verified byte-identical.  Mutations that
survive are characterized separately.

20 mutations target apps/api/model_impls/lstm.py,
apps/api/model_impls/neural_runtime.py, apps/api/model_execution.py and
apps/api/routers/models.py.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable

FILES = [
    "apps/api/model_impls/lstm.py",
    "apps/api/model_impls/neural_runtime.py",
    "apps/api/model_execution.py",
    "apps/api/routers/models.py",
]

BACKUPS: dict[str, Path] = {}


def make_backups() -> None:
    for rel in FILES:
        src = ROOT / rel
        dst = Path(str(src) + ".cert138_bak")
        shutil.copyfile(src, dst)
        BACKUPS[rel] = dst


def restore_all() -> None:
    for rel, dst in BACKUPS.items():
        shutil.copyfile(dst, ROOT / rel)


def verify_clean() -> bool:
    ok = True
    for rel, dst in BACKUPS.items():
        current = (ROOT / rel).read_bytes()
        backup = dst.read_bytes()
        if current != backup:
            ok = False
            print(f"    DIRTY after restore: {rel}")
        dst.unlink()
    return ok


def run_pytest(targets: str) -> tuple[bool, str]:
    cmd = [PY, "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"]
    cmd += targets.split()
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = result.stdout + result.stderr
    green = "no tests ran" not in out and "error" not in out.lower().split("===")[0][:2000]
    passed_line = [line for line in out.splitlines() if " passed" in line]
    passed = bool(passed_line) and "failed" not in passed_line[-1] and "error" not in passed_line[-1]
    return (result.returncode == 0 and green and passed), out


class Mutation:
    def __init__(self, mid: str, rel: str, old: str, new: str, targets: str,
                 note: str = ""):
        self.mid = mid
        self.rel = rel
        self.old = old
        self.new = new
        self.targets = targets
        self.note = note


LSTM = "apps/api/model_impls/lstm.py"
RUNTIME = "apps/api/model_impls/neural_runtime.py"
EXEC = "apps/api/model_execution.py"
ROUTERS = "apps/api/routers/models.py"

MUTATIONS = [
    Mutation(
        "M1 LSTM_MIN_TRAIN 32->5", LSTM,
        "LSTM_MIN_TRAIN = 32",
        "LSTM_MIN_TRAIN = 5",
        "tests/unit/test_lstm_adapter.py::test_fail_closed_on_short_history",
        "absolute floor of recurrent training",
    ),
    Mutation(
        "M2 window feasibility gate removed", LSTM,
        "    if n_train <= input_size + int(horizon):\n        raise ValueError(",
        "    if False and n_train <= input_size + int(horizon):\n        raise ValueError(",
        "tests/unit/test_lstm_adapter.py::test_fail_closed_when_window_infeasible_for_history",
        "silent window shrink forbidden",
    ),
    Mutation(
        "M3 regular-grid validation bypassed", LSTM,
        "    try:\n        grid = validate_regular_grid(\n            [value.isoformat() for value in timestamps]\n        )\n    except MultivariateContractError as exc:\n        raise ValueError(f\"LSTM: {exc}\") from exc\n    return str(grid[\"frequency\"])",
        "    return 'D'",
        "tests/unit/test_lstm_adapter.py::test_fail_closed_on_irregular_grid tests/unit/test_lstm_adapter.py::test_fail_closed_on_duplicate_timestamps",
        "single source of truth of regular grid (Task 131)",
    ),
    Mutation(
        "M4 hidden integer axis instead of refusal", LSTM,
        "    if timestamps is None or len(timestamps) == 0:\n        raise ValueError(",
        "    if timestamps is None or len(timestamps) == 0:\n        from app.data.detectors import smart_to_datetime as _s\n        _fake = pd.Series(range(120))\n        return [pd.Timestamp(v) for v in pd.to_datetime(pd.Timestamp('2000-01-01')) + pd.to_timedelta(_fake, unit='D')]\n        raise ValueError(",
        "tests/unit/test_lstm_adapter.py::test_fail_closed_on_missing_train_timestamps",
        "row-order labels must not be coerced into dates",
    ),
    Mutation(
        "M5 cell whitelist widened (rnn accepted)", LSTM,
        'CELL_OPTIONS = {"lstm", "gru"}',
        'CELL_OPTIONS = {"lstm", "gru", "rnn"}',
        "tests/unit/test_lstm_adapter.py::test_fail_closed_on_unknown_cell",
        "core of task: cell in {lstm, gru} only",
    ),
    Mutation(
        "M6 bool coercion allowed for int handles", LSTM,
        "        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):",
        "        if not isinstance(value, (int, np.integer)):",
        "tests/unit/test_lstm_adapter.py::test_fail_closed_on_bool_instead_of_int",
        "bool is a subclass of int: True->1 hidden coercion",
    ),
    Mutation(
        "M7 alpha whitelist removed", LSTM,
        "    if alpha_value not in ALPHA_OPTIONS:\n        raise ValueError(\n            f\"LSTM param 'alpha'={alpha_value} вне допустимого набора \"\n            f\"{sorted(ALPHA_OPTIONS)}\"\n        )",
        "    if False:\n        raise ValueError('alpha rejected')",
        "tests/unit/test_lstm_adapter.py::test_fail_closed_on_non_whitelist_alpha",
        "alpha whitelist {0.01, 0.05, 0.10}",
    ),
    Mutation(
        "M8 exogenous symmetry gate removed", LSTM,
        "    if train_names != future_names:\n        only_train = sorted(train_names - future_names)\n        only_future = sorted(future_names - train_names)\n        raise ValueError(",
        "    if False:\n        raise ValueError(",
        "tests/unit/test_lstm_adapter.py::test_fail_closed_on_future_features_without_train_counterpart tests/unit/test_lstm_adapter.py::test_fail_closed_on_train_features_without_future_counterpart",
        "granted channel must be symmetric train<->future",
    ),
    Mutation(
        "M9 service-column collision gate removed", LSTM,
        "    collision = sorted(train_names & _SERVICE_COLUMNS)\n    if collision:\n        raise ValueError(",
        "    collision = sorted(train_names & _SERVICE_COLUMNS)\n    if False:\n        raise ValueError(",
        "tests/unit/test_lstm_adapter.py::test_fail_closed_on_feature_name_collision_with_service_columns",
        "regressor named y/ds/unique_id would silently overwrite target",
    ),
    Mutation(
        "M10 clamp invariant check removed", LSTM,
        "    if not (\n        (lower <= forecast).all() and (forecast <= upper).all()\n    ):\n        raise NeuralContractError(",
        "    if False:\n        raise NeuralContractError(",
        "tests/unit/test_lstm_adapter.py::test_forecast_length_and_finiteness",
        "lower <= point <= upper guard (no clamp substitution)",
    ),
    Mutation(
        "M11 seed injection into constructor removed", RUNTIME,
        "    budget[\"random_seed\"] = int(seed)",
        "    pass",
        "tests/unit/test_lstm_adapter.py::test_different_seed_changes_forecast tests/unit/test_lstm_integration_paths.py::test_lstm_execution_different_seed_changes_forecast",
        "blocker regression of Task 137 resertification",
    ),
    Mutation(
        "M12 interval level levels[-1] -> levels[0]", LSTM,
        "    interval_level = interval_plan.levels[-1]",
        "    interval_level = interval_plan.levels[0]",
        "tests/unit/test_lstm_adapter.py::test_alpha_drives_interval_width_symmetrically",
        "both bounds on 1-alpha/2 level (conformal semantics)",
    ),
    Mutation(
        "M13 futr_df silently dropped", LSTM,
        "        futr_df = pd.DataFrame({",
        "        futr_df = None\n        if False:\n            futr_df = pd.DataFrame({",
        "tests/unit/test_lstm_adapter.py::test_exogenous_path_produces_forecast_with_plan_signature",
        "future regressors must reach predict()",
    ),
    Mutation(
        "M14 registry deterministic=True -> False", EXEC,
        "        deterministic=True,\n        dependency_group=\"neural\",",
        "        deterministic=False,\n        dependency_group=\"neural\",",
        "tests/unit/test_lstm_integration_paths.py::test_lstm_definition_declares_neural_level_contract",
        "same-seed bit-identical contract declared to the platform",
    ),
    Mutation(
        "M15 lstm removed from dispatch", ROUTERS,
        '    "lstm": run_lstm_backtest,\n}',
        "}",
        "tests/unit/test_lstm_integration_paths.py::test_lstm_in_production_backtest_ids_and_dispatch",
        "dispatch<->readiness gate on import",
    ),
    Mutation(
        "M16 adapter_id renamed", LSTM,
        'LSTM_ADAPTER_ID = "neuralforecast-lstm"',
        'LSTM_ADAPTER_ID = "neuralforecast-lstm-x"',
        "tests/unit/test_lstm_adapter.py::test_metadata_carries_neural_contract_block tests/unit/test_lstm_integration_paths.py::test_lstm_definition_declares_neural_level_contract",
        "self-identification of the adapter",
    ),
    Mutation(
        "M17 legacy endpoint returns synthetic demo", LSTM,
        "def run_lstm_backtest(\n    series: Sequence[float],\n    train_ratio: float,\n    seasonal_period: int,\n) -> None:",
        "def run_lstm_backtest(\n    series: Sequence[float],\n    train_ratio: float,\n    seasonal_period: int,\n) -> None:\n    return {'forecast': [0.0], 'lower': [0.0], 'upper': [0.0], 'demo': True}",
        "tests/unit/test_lstm_adapter.py::test_legacy_endpoint_honest_refusal_on_bare_series",
        "no Naive-fallback on bare series",
    ),
    Mutation(
        "M18 max_steps budget overridden to 1 (honest rewrite)", LSTM,
        "            futr_exog_list=list(plan.futr_exog_list),\n            alias=alias,\n            **dict(budget),\n        )",
        "            futr_exog_list=list(plan.futr_exog_list),\n            alias=alias,\n            **{**dict(budget), 'max_steps': 1},\n        )",
        "tests/unit/test_lstm_adapter.py::test_metadata_carries_neural_contract_block",
        "budget handle must actually reach the constructor (no literal-dup artifact)",
    ),
    Mutation(
        "M19 PredictionIntervals removed (conformal off)", RUNTIME,
        "    if levels:\n        from neuralforecast.utils import PredictionIntervals\n        fit_kwargs[\"prediction_intervals\"] = PredictionIntervals()",
        "    if False:\n        pass",
        "tests/unit/test_lstm_adapter.py::test_forecast_length_and_finiteness",
        "certified conformal path of Task 137",
    ),
    Mutation(
        "M20 future frame validation skipped", LSTM,
        "        validate_future_exogenous_frame(\n            plan, futr_df, n_series=1, horizon=int(horizon),\n        )",
        "        pass",
        "tests/unit/test_lstm_adapter.py::test_fail_closed_on_future_frame_missing_horizon_coverage",
        "futr must cover n_series*horizon without NaN",
    ),
]


def apply_and_check(m: Mutation) -> dict:
    path = ROOT / m.rel
    original = path.read_text(encoding="utf-8")
    if m.old not in original:
        return {"mid": m.mid, "status": "NOT-APPLIED", "detail": "anchor not found"}
    mutated = original.replace(m.old, m.new, 1)
    path.write_text(mutated, encoding="utf-8")
    try:
        green, out = run_pytest(m.targets)
        status = "SURVIVED" if green else "KILLED"
        detail = (out.splitlines()[-1] if out.splitlines() else "")[:160]
    finally:
        path.write_text(original, encoding="utf-8")
    return {"mid": m.mid, "status": status, "detail": detail}


def main() -> int:
    selected = sys.argv[1:]
    if selected:
        keys = set()
        for part in selected:
            for chunk in part.split(","):
                chunk = chunk.strip()
                if chunk:
                    keys.add(int(chunk))
        chosen = [m for i, m in enumerate(MUTATIONS, 1) if i in keys]
    else:
        chosen = MUTATIONS
    make_backups()
    outcomes: list[dict] = []
    try:
        for m in chosen:
            print(f"-> {m.mid} ({m.note})", flush=True)
            outcome = apply_and_check(m)
            print(f"   {outcome['status']}: {outcome['detail']}", flush=True)
            outcomes.append(outcome)
    finally:
        restore_all()
    killed = sum(1 for o in outcomes if o["status"] == "KILLED")
    survived = [o for o in outcomes if o["status"] == "SURVIVED"]
    failed = [o for o in outcomes if o["status"] == "NOT-APPLIED"]
    print(f"\nCERT138 MUTATIONS: KILLED={killed} SURVIVED={len(survived)} "
          f"NOT-APPLIED={len(failed)}")
    for o in survived:
        print(f"  SURVIVED: {o['mid']} -- {o['detail']}")
    for o in failed:
        print(f"  NOT-APPLIED: {o['mid']} -- {o['detail']}")
    print("CLEAN:", verify_clean())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
