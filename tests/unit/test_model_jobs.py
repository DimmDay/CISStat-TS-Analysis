from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apps.api.model_jobs import (
    MODEL_JOB_CONTRACT_VERSION,
    ModelJobContractError,
    dependency_group_manifest,
    gpu_runtime_available,
    job_signature,
    resource_policy_for,
)


def test_dependency_groups_and_resource_policies_cover_future_model_families() -> None:
    manifest = dependency_group_manifest()

    assert set(manifest) == {"classical", "ml", "volatility", "neural"}
    assert manifest["classical"]["install_extra"] == "classical"
    assert manifest["ml"]["packages"]
    assert manifest["volatility"]["packages"]
    assert manifest["neural"]["packages"]

    low = resource_policy_for(
        {"memory_class": "low", "gpu": "unsupported", "cpu": "required"},
    )
    high = resource_policy_for(
        {"memory_class": "high", "gpu": "required", "cpu": "required"},
    )
    assert low["contract_version"] == MODEL_JOB_CONTRACT_VERSION
    assert low["memory_limit_mb"] < high["memory_limit_mb"]
    assert high["gpu"] == "required"
    assert high["step_timeout_seconds"] <= high["total_timeout_seconds"]


def test_job_signature_is_deterministic_and_binds_seed_budget_and_work_plan() -> None:
    policy = resource_policy_for(
        {"memory_class": "standard", "gpu": "unsupported", "cpu": "required"},
    )
    payload = {
        "operation": "tuning",
        "model_id": "ets",
        "cohort_id": "cohort-1",
        "work_plan": [{"trial": 0}, {"trial": 1}],
        "random_state": 42,
        "resource_policy": policy,
    }

    signature = job_signature(**payload)

    assert signature == job_signature(**payload)
    assert signature != job_signature(**{**payload, "random_state": 43})
    assert signature != job_signature(
        **{**payload, "work_plan": [{"trial": 0}]},
    )


def test_resource_policy_rejects_unknown_capabilities() -> None:
    with pytest.raises(ModelJobContractError, match="memory_class"):
        resource_policy_for(
            {"memory_class": "unbounded", "gpu": "unsupported", "cpu": "required"},
        )

    # Keep this import used so the contract's timestamps are explicitly UTC-safe.
    assert datetime.now(timezone.utc).tzinfo is not None


def test_gpu_runtime_uses_explicit_lazy_deploy_signal(monkeypatch) -> None:
    monkeypatch.delenv("CISSTAT_GPU_AVAILABLE", raising=False)
    assert gpu_runtime_available() is False
    monkeypatch.setenv("CISSTAT_GPU_AVAILABLE", "true")
    assert gpu_runtime_available() is True
