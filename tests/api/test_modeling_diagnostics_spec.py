"""Regression tests for the formal diagnostics contract in modeling.yaml.

PHASE 2 contract:
- Ljung-Box: residual autocorrelation.
- Jarque-Bera: residual normality.
- ARCH-LM: conditional heteroscedasticity.
- Durbin-Watson: residual serial correlation.

The YAML specification must describe exactly the diagnostics implemented by
apps.api.routers.diagnostics. This prevents the formal contract from drifting
away from the production endpoint.
"""
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "rules" / "modeling.yaml"

EXPECTED_DIAGNOSTICS = {
    "ljung_box": {
        "name": "Автокорреляция остатков (Ljung-Box)",
        "applicable_if": "n_observations > lags",
        "requires_p_value": True,
    },
    "jarque_bera": {
        "name": "Нормальность остатков (Jarque-Bera)",
        "applicable_if": "n_observations >= 8",
        "requires_p_value": True,
    },
    "arch_lm": {
        "name": "Условная гетероскедастичность (ARCH-LM)",
        "applicable_if": "n_observations > arch_lags + 1 and residual variance > 0",
        "requires_p_value": True,
    },
    "durbin_watson": {
        "name": "Статистика Дарбина-Уотсона (Durbin-Watson)",
        "applicable_if": "finite residuals with at least 2 observations",
        "requires_p_value": False,
    },
}


def _diagnostics_spec() -> list[dict]:
    document = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    stages = document["pipeline"]["stages"]
    stage = next(item for item in stages if item["id"] == "diagnostics")
    return stage["checks"]


def test_diagnostics_stage_exists_and_has_exact_phase_2_tests() -> None:
    checks = _diagnostics_spec()
    actual_ids = [item["id"] for item in checks]
    assert actual_ids == list(EXPECTED_DIAGNOSTICS)
    assert len(actual_ids) == len(set(actual_ids))


def test_diagnostics_spec_matches_runtime_contract() -> None:
    checks = {item["id"]: item for item in _diagnostics_spec()}

    for test_id, expected in EXPECTED_DIAGNOSTICS.items():
        check = checks[test_id]
        assert check["name"] == expected["name"]
        assert expected["applicable_if"] in check["applicable_if"]
        assert check["alpha"] == 0.05
        assert check["severity_if_failed"] in {"warning", "error"}
        assert check["requires_p_value"] is expected["requires_p_value"]


def test_ljung_box_has_configurable_lags() -> None:
    checks = {item["id"]: item for item in _diagnostics_spec()}
    assert checks["ljung_box"]["lags"] == 10


def test_arch_lm_has_configurable_lags() -> None:
    checks = {item["id"]: item for item in _diagnostics_spec()}
    assert checks["arch_lm"]["lags"] == 10


def test_spec_does_not_contain_removed_non_phase_2_checks() -> None:
    checks = {item["id"] for item in _diagnostics_spec()}
    assert "residual_stationarity" not in checks
    assert "prediction_interval_coverage" not in checks
    assert "residual_normality" not in checks
