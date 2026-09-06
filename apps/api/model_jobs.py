"""Persistent, bounded execution contract for long-running model work.

The HTTP/session layer owns persistence and CAS.  This module keeps job
identity, dependency groups, resource budgets and public progress independent
from FastAPI so future classical, ML, volatility and neural adapters can share
the same protocol without storing fitted estimators in Redis.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
import resource
import sys
from typing import Any, Literal, Mapping, Sequence


MODEL_JOB_CONTRACT_VERSION = "model-job-v1"

ModelDependencyGroup = Literal["classical", "ml", "volatility", "neural"]
ModelJobOperation = Literal["tuning"]
ModelJobStatus = Literal["in_progress", "completed", "failed", "cancelled", "stale"]


class ModelJobContractError(ValueError):
    """A job request or persisted record violates the execution contract."""


_DEPENDENCY_GROUPS: dict[ModelDependencyGroup, dict[str, Any]] = {
    "classical": {
        "install_extra": "classical",
        "packages": ["numpy", "statsmodels", "scipy", "prophet"],
    },
    "ml": {
        "install_extra": "ml",
        "packages": ["scikit-learn", "xgboost", "lightgbm", "catboost"],
    },
    "volatility": {
        "install_extra": "volatility",
        "packages": ["arch"],
    },
    "neural": {
        "install_extra": "neural",
        "packages": ["torch", "neuralforecast"],
    },
}

_RESOURCE_POLICIES: dict[str, dict[str, int]] = {
    "low": {
        "memory_limit_mb": 512,
        "cpu_threads": 1,
        "step_timeout_seconds": 60,
        "total_timeout_seconds": 900,
    },
    "standard": {
        "memory_limit_mb": 1024,
        "cpu_threads": 2,
        "step_timeout_seconds": 120,
        "total_timeout_seconds": 1800,
    },
    "high": {
        "memory_limit_mb": 4096,
        "cpu_threads": 4,
        "step_timeout_seconds": 300,
        "total_timeout_seconds": 7200,
    },
}


def dependency_group_manifest() -> dict[str, dict[str, Any]]:
    """Return a JSON-safe copy of deploy-time optional dependency groups."""
    return {
        name: {
            "install_extra": value["install_extra"],
            "packages": list(value["packages"]),
        }
        for name, value in _DEPENDENCY_GROUPS.items()
    }


def resource_policy_for(capabilities: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve immutable server limits from registry resource capabilities."""
    memory_class = str(capabilities.get("memory_class") or "")
    if memory_class not in _RESOURCE_POLICIES:
        raise ModelJobContractError(f"Неподдерживаемый memory_class: {memory_class}")
    gpu = str(capabilities.get("gpu") or "")
    if gpu not in {"unsupported", "optional", "required"}:
        raise ModelJobContractError(f"Неподдерживаемый GPU capability: {gpu}")
    cpu = str(capabilities.get("cpu") or "")
    if cpu not in {"required", "optional"}:
        raise ModelJobContractError(f"Неподдерживаемый CPU capability: {cpu}")
    limits = _RESOURCE_POLICIES[memory_class]
    available_threads = max(1, int(os.cpu_count() or 1))
    return {
        "contract_version": MODEL_JOB_CONTRACT_VERSION,
        "memory_class": memory_class,
        "memory_limit_mb": limits["memory_limit_mb"],
        "cpu": cpu,
        "cpu_threads": min(limits["cpu_threads"], available_threads),
        "gpu": gpu,
        "step_timeout_seconds": limits["step_timeout_seconds"],
        "total_timeout_seconds": limits["total_timeout_seconds"],
    }


def gpu_runtime_available() -> bool:
    """Use an explicit deploy signal; probing CUDA must not import torch eagerly."""
    return os.getenv("CISSTAT_GPU_AVAILABLE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def job_signature(
    *, operation: str, model_id: str, cohort_id: str,
    work_plan: Sequence[Mapping[str, Any]], random_state: int,
    resource_policy: Mapping[str, Any],
) -> str:
    """Bind idempotency to data, work plan, deterministic seed and budgets."""
    payload = {
        "contract_version": MODEL_JOB_CONTRACT_VERSION,
        "operation": operation,
        "model_id": model_id,
        "cohort_id": cohort_id,
        "work_plan": [dict(item) for item in work_plan],
        "random_state": int(random_state),
        "resource_policy": dict(resource_policy),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def deadline_iso(*, total_timeout_seconds: int) -> str:
    return (utc_now() + timedelta(seconds=int(total_timeout_seconds))).isoformat()


def deadline_expired(job: Mapping[str, Any]) -> bool:
    raw = job.get("deadline_at")
    if not raw:
        return True
    try:
        deadline = datetime.fromisoformat(str(raw))
    except ValueError:
        return True
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return utc_now() >= deadline


def process_memory_mb() -> float:
    """Return peak RSS in MiB (macOS reports bytes, Linux reports KiB)."""
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak / (1024.0 * 1024.0) if sys.platform == "darwin" else peak / 1024.0


def progress_snapshot(job: Mapping[str, Any]) -> dict[str, Any]:
    completed = int(job.get("next_step", 0))
    total = int(job.get("total_steps", 0))
    folds_per_step = int(job.get("folds_per_step", 0))
    epochs_per_step = int(job.get("epochs_per_step", 0))
    percent = round((100.0 * completed / total) if total else 0.0, 2)
    return {
        "phase": str(job.get("progress_phase") or "steps"),
        "completed_steps": completed,
        "total_steps": total,
        "percent": percent,
        "trials": {
            "completed": completed if job.get("operation") == "tuning" else 0,
            "total": total if job.get("operation") == "tuning" else 0,
        },
        "folds": {
            "completed": min(total * folds_per_step, completed * folds_per_step),
            "total": total * folds_per_step,
        },
        "epochs": {
            "completed": min(total * epochs_per_step, completed * epochs_per_step),
            "total": total * epochs_per_step,
        },
    }


def public_job(job: Mapping[str, Any], *, idempotent_replay: bool = False) -> dict[str, Any]:
    """Expose progress/result without internal work plans or heavy artifacts."""
    return {
        "job_id": job["job_id"],
        "job_signature": job["job_signature"],
        "contract_version": job["contract_version"],
        "operation": job["operation"],
        "model_id": job["model_id"],
        "cohort_id": job["cohort_id"],
        "status": job["status"],
        "dependency_group": job["dependency_group"],
        "deterministic_seed": job["random_state"],
        "resource_policy": dict(job["resource_policy"]),
        "progress": progress_snapshot(job),
        "result": job.get("result"),
        "error": job.get("error"),
        "cancellation": job.get("cancellation"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "deadline_at": job.get("deadline_at"),
        "idempotent_replay": bool(idempotent_replay),
    }
