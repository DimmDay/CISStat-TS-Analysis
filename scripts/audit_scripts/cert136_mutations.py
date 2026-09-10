"""Task 136 certification -- mutation probes (auditor side).

Protocol per mutation: apply textual patch -> run targeted pytest subset ->
record KILLED (tests went RED) or SURVIVED (stayed GREEN) -> revert via
git checkout -> verify working tree byte-clean.

Categories:
  M1-M6, M8, M10, M11, M14, M16 -- anti-tamper of Task 136 promises
      (convergence budget, o>=1 mandate, persistence, diagnostics key,
       leverage direction, rescale, significance level, min history,
       determinism flag, adapter_id, dispatch gate)
  M7, M9, M12, M13 -- suspected test-coverage gaps (prediction: survive)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTEST = ROOT / ".venv-cert136" / "bin" / "python"

ADAPTER = "apps/api/model_impls/egarch.py"
ENGINE = "apps/api/backtesting.py"
REGISTRY = "apps/api/model_execution.py"
DISPATCH = "apps/api/routers/models.py"

ADAPTER_SUITE = ["tests/unit/test_egarch_adapter.py"]

MUTATIONS: list[dict] = [
    dict(
        mid="M1", file=ADAPTER,
        old="EGARCH_MAXITER = 1000", new="EGARCH_MAXITER = 100",
        pytest=["tests/unit/test_egarch_adapter.py::TestEgarchFailClosed"
                "::test_explicit_optimizer_budget_converges_pathological_slice"],
        promise="explicit SLSQP convergence budget",
    ),
    dict(
        mid="M2", file=ADAPTER,
        old='    "o": (1, 3),', new='    "o": (0, 3),',
        pytest=["tests/unit/test_egarch_adapter.py::TestEgarchParams"
                "::test_o_must_be_strictly_positive_asymmetry_mandate",
                "tests/unit/test_egarch_adapter.py::TestEgarchParams"
                "::test_p_o_q_outside_bounds_fail_closed"],
        promise="o>=1 asymmetry mandate",
    ),
    dict(
        mid="M3", file=ADAPTER,
        old='    beta_keys = [key for key in fit_params if key.startswith("beta[")]',
        new='    beta_keys = [key for key in fit_params if key.startswith(\n'
            '        "beta[") or key.startswith("alpha[")]',
        pytest=["tests/unit/test_egarch_adapter.py::TestEgarchFitPredict"
                "::test_metadata_carries_mle_and_diagnostics_state"],
        promise="persistence := sum(beta) (log-variance AR)",
    ),
    dict(
        mid="M4", file=ENGINE,
        old="                model_id: volatility_model_block,",
        new='                "garch": volatility_model_block,',
        pytest=["tests/api/test_egarch_session.py::"
                "test_egarch_runs_volatility_session_backtest"],
        promise="diagnostics block key == model_id",
    ),
    dict(
        mid="M5", file=ADAPTER,
        old='        direction = "negative"',
        new='        direction = "positive"',
        pytest=["tests/unit/test_egarch_adapter.py::TestEgarchAsymmetry"
                "::test_leverage_recovered_negative_on_simulated_series"],
        promise="leverage_direction from fitted gamma sign",
    ),
    dict(
        mid="M6", file=ADAPTER,
        old="            rescale=False,  # БЕЗ скрытого масштабирования входа",
        new="            rescale=True,",
        pytest=["tests/unit/test_egarch_adapter.py::TestEgarchFitPredict"
                "::test_rescale_false_no_hidden_transform"],
        promise="rescale=False (no hidden input scaling)",
    ),
    dict(
        mid="M7", file=ADAPTER,
        old="INTERVAL_SIMULATIONS = 4000", new="INTERVAL_SIMULATIONS = 10",
        pytest=ADAPTER_SUITE,
        promise="simulation path count 4000 (suspected survivor)",
    ),
    dict(
        mid="M8", file=ADAPTER,
        old="ASYMMETRY_SIGNIFICANCE_LEVEL = 0.05",
        new="ASYMMETRY_SIGNIFICANCE_LEVEL = 0.5",
        pytest=["tests/unit/test_egarch_adapter.py::TestEgarchAsymmetry"
                "::test_asymmetry_block_declares_gamma_metadata"],
        promise="asymmetry significance level pinned at 0.05",
    ),
    dict(
        mid="M9", file=ADAPTER,
        old="    quantiles = (alpha_level / 2.0, 1.0 - alpha_level / 2.0)",
        new="    quantiles = (alpha_level, 1.0 - alpha_level)",
        pytest=ADAPTER_SUITE,
        promise="two-sided central intervals at alpha/2 (suspected survivor)",
    ),
    dict(
        mid="M10", file=ADAPTER,
        old="EGARCH_MIN_TRAIN = 20", new="EGARCH_MIN_TRAIN = 5",
        pytest=["tests/unit/test_egarch_adapter.py::"
                "test_min_train_aligns_with_contract_minimum"],
        promise="min history == MIN_RETURNS_OBSERVATIONS (20)",
    ),
    dict(
        mid="M11", file=REGISTRY,
        old='        objective="volatility",\n'
            '        input_kind="univariate",\n'
            '        supports_prediction_intervals=True,\n'
            '        deterministic=True,\n'
            '        dependency_group="volatility",\n'
            '        resource_capabilities=_CLASSICAL_RESOURCES,\n'
            '    ),\n])\n',
        new='        objective="volatility",\n'
            '        input_kind="univariate",\n'
            '        supports_prediction_intervals=True,\n'
            '        deterministic=False,\n'
            '        dependency_group="volatility",\n'
            '        resource_capabilities=_CLASSICAL_RESOURCES,\n'
            '    ),\n])\n',
        pytest=["tests/unit/test_egarch_integration_paths.py::"
                "test_egarch_definition_declares_volatility_contract"],
        promise="registry determinism=True declaration",
    ),
    dict(
        mid="M12", file=ADAPTER,
        old="    lower = np.minimum(lower, variance_forecast)\n"
            "    upper = np.maximum(upper, variance_forecast)\n",
        new="",
        pytest=ADAPTER_SUITE,
        promise="interval clamp lower<=point<=upper (suspected survivor)",
    ),
    dict(
        mid="M13", file=ADAPTER,
        old='    if not np.isfinite(vector).all():\n'
            '        raise ValueError(\n'
            '            "EGARCH: returns содержат NaN/Inf -- импутация запрещена "\n'
            '            "(fail-closed)"\n'
            '        )\n',
        new="",
        pytest=["tests/unit/test_egarch_adapter.py::TestEgarchFailClosed"
                "::test_nonfinite_input_fail_closed"],
        promise="NaN/Inf input fail-closed (suspected survivor)",
    ),
    dict(
        mid="M14", file=REGISTRY,
        old='            "adapter_id": payload["adapter_id"],\n'
            '            "params": payload["params"],\n'
            '            "persistence": payload["persistence"],\n'
            '            "is_covariance_stationary": payload['
            '"is_covariance_stationary"],\n'
            '            "convergence_flag": payload["convergence_flag"],\n'
            '            "nobs": payload["nobs"],\n'
            '            "loglikelihood": payload["loglikelihood"],\n'
            '            "aic": payload["aic"],\n'
            '            "bic": payload["bic"],\n'
            '            "std_residuals": payload["std_residuals"].tolist(),\n'
            '            "conditional_volatility": payload['
            '"conditional_volatility"].tolist(),\n'
            '            "asymmetry": payload["asymmetry"],\n'
            '            "mean_model": payload["mean_model"],\n'
            '            "dist": payload["dist"],\n'
            '            "intervals": payload["intervals"],\n'
            '            "deterministic": payload["deterministic"],\n'
            '        },\n'
            '    )\n\n\n'
            'def _xgboost_executor',
        new='            "params": payload["params"],\n'
            '            "persistence": payload["persistence"],\n'
            '            "is_covariance_stationary": payload['
            '"is_covariance_stationary"],\n'
            '            "convergence_flag": payload["convergence_flag"],\n'
            '            "nobs": payload["nobs"],\n'
            '            "loglikelihood": payload["loglikelihood"],\n'
            '            "aic": payload["aic"],\n'
            '            "bic": payload["bic"],\n'
            '            "std_residuals": payload["std_residuals"].tolist(),\n'
            '            "conditional_volatility": payload['
            '"conditional_volatility"].tolist(),\n'
            '            "asymmetry": payload["asymmetry"],\n'
            '            "mean_model": payload["mean_model"],\n'
            '            "dist": payload["dist"],\n'
            '            "intervals": payload["intervals"],\n'
            '            "deterministic": payload["deterministic"],\n'
            '        },\n'
            '    )\n\n\n'
            'def _xgboost_executor',
        pytest=["tests/api/test_egarch_session.py::"
                "test_egarch_runs_volatility_session_backtest"],
        promise="adapter_id self-identification in executor metadata",
    ),
    dict(
        mid="M16", file=DISPATCH,
        old='    "egarch": run_egarch_backtest,\n}',
        new='}',
        pytest=["tests/unit/test_egarch_integration_paths.py::"
                "test_egarch_in_production_backtest_ids_and_dispatch"],
        promise="dispatch<->registry module-level gate",
    ),
]

EXPECTED_SURVIVORS = {"M7", "M9", "M12", "M13"}


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=900,
    )


def main() -> int:
    failures: list[str] = []
    rows: list[str] = []
    for mutation in MUTATIONS:
        mid = mutation["mid"]
        target = ROOT / mutation["file"]
        original = target.read_text(encoding="utf-8")
        old, new = mutation["old"], mutation["new"]
        if old not in original:
            rows.append(f"{mid}: PATCH-ANCHOR NOT FOUND ({mutation['file']})")
            failures.append(mid)
            continue
        try:
            target.write_text(original.replace(old, new, 1), encoding="utf-8")
            result = run([str(PYTEST), "-m", "pytest", *mutation["pytest"],
                          "-q", "--no-header", "-p", "no:cacheprovider"])
            killed = result.returncode != 0
            status = "KILLED" if killed else "SURVIVED"
            detail = ""
            if killed:
                for line in reversed((result.stdout or "").splitlines()):
                    if "failed" in line or "error" in line:
                        detail = line.strip()[:110]
                        break
            rows.append(f"{mid}: {status} {detail} -- {mutation['promise']}")
            if not killed and mid not in EXPECTED_SURVIVORS:
                failures.append(mid)
        finally:
            target.write_text(original, encoding="utf-8")
            check = run(["git", "-C", str(ROOT), "diff", "--quiet",
                         mutation["file"]])
            if check.returncode != 0:
                rows.append(f"{mid}: REVERT CHECK FAILED for "
                            f"{mutation['file']}")
                failures.append(mid)
    print()
    for row in rows:
        print(row)
    survivors = [m["mid"] for m in MUTATIONS
                 if any(r.startswith(m["mid"] + ": SURVIVED") for r in rows)]
    print()
    print(f"Mutation summary: {len(rows)} probes; "
          f"killed={len(rows) - len(survivors)}, survived={survivors}; "
          f"unexpected outcomes: {failures or 'none'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
