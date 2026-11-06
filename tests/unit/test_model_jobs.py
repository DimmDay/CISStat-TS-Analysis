from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.api.model_jobs import (
    MODEL_JOB_CONTRACT_VERSION,
    ModelJobContractError,
    dependency_group_manifest,
    gpu_runtime_available,
    job_signature,
    resource_policy_for,
)

_MODEL_JOBS_PATH = (
    Path(__file__).resolve().parents[2] / "apps" / "api" / "model_jobs.py"
)
_MISSING = object()


def _import_model_jobs_without_resource():
    """Импортировать СВЕЖИЙ экземпляр model_jobs с недоступным resource.

    sys.modules["resource"] = None заставляет ``import resource``
    поднимать ImportError -- ровно то, что происходит на Windows, где
    модуля нет вовсе (ModuleNotFoundError -- подкласс ImportError).
    Глобальный apps.api.model_jobs не трогаем: экземпляр живёт под
    временным именем и удаляется из sys.modules после проверки.
    """
    spec = importlib.util.spec_from_file_location(
        "model_jobs_windows_parity", _MODEL_JOBS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    saved = sys.modules.get("resource", _MISSING)
    sys.modules["resource"] = None
    try:
        spec.loader.exec_module(module)
    finally:
        if saved is _MISSING:
            sys.modules.pop("resource", None)
        else:
            sys.modules["resource"] = saved
    sys.modules.pop("model_jobs_windows_parity", None)
    return module


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


# --- Windows-паритет (AUTH-07-HOTFIX2, 2026-11-06) -------------------------
# CI auth07.yml первым начал импортировать apps.api.main на windows-2025:
# top-level `import resource` в model_jobs.py падал ModuleNotFoundError
# ещё на collection тестов, локальные же гейты (Linux) были зелёными.
# Контракт: модуль job-контрактов обязан импортироваться на любой ОС.


def test_model_jobs_imports_without_unix_resource_module() -> None:
    module = _import_model_jobs_without_resource()

    assert module.resource is None
    assert module.MODEL_JOB_CONTRACT_VERSION == MODEL_JOB_CONTRACT_VERSION


def test_process_memory_mb_degrades_to_zero_without_resource_module() -> None:
    module = _import_model_jobs_without_resource()

    # Честная деградация: без resource пик RSS неизмерим, бюджетная
    # проверка памяти в modeling_session превращается в no-op (0.0 ниже
    # любого лимита), а не в падение импорта всего приложения.
    assert module.process_memory_mb() == 0.0


def test_contract_surface_survives_windows_import(monkeypatch) -> None:
    monkeypatch.delenv("CISSTAT_GPU_AVAILABLE", raising=False)
    module = _import_model_jobs_without_resource()

    assert set(module.dependency_group_manifest()) == {
        "classical", "ml", "volatility", "neural",
    }
    assert module.gpu_runtime_available() is False
    policy = module.resource_policy_for(
        {"memory_class": "low", "gpu": "unsupported", "cpu": "required"},
    )
    assert policy["memory_limit_mb"] == 512


@pytest.mark.skipif(sys.platform == "win32", reason="проверка только для Unix")
def test_process_memory_mb_reports_peak_rss_on_unix() -> None:
    # Обратная сторона контракта: на платформах С resource функция
    # обязана измерять реальный пик RSS, а не возвращать заглушку.
    from apps.api import model_jobs as live

    assert live.resource is not None
    assert live.process_memory_mb() > 0.0
