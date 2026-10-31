"""AUTH-01 functional policy contract. No authentication/object/budget decision.

Only a trusted coordinator may supply normalized workload/saved operation context.
HTTP handlers/workers adopt it in AUTH-11/13; a functional allow is not admission.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.api.plans import Capabilities, REGISTRY_VERSION

CapabilityId = Literal["can_run_baseline_models", "can_tune_models", "can_train_custom_models",
                       "can_use_api", "can_upload_own_data", "can_save_history"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StageDefinition(ContractModel):
    namespace: Literal["scientific", "application", "service"]
    stage_id: str


class OperationDefinition(ContractModel):
    operation_id: str
    stage_namespace: Literal["scientific", "application", "service"]
    stage: str
    capability: CapabilityId | None = None
    selector: Literal["none", "model", "scientific_stage"] = "none"
    authority: Literal["functional", "external", "unavailable"] = "functional"


class EntryBinding(ContractModel):
    operation_id: str
    programmatic_api: bool = False


class AccessRegistry(ContractModel):
    registry_version: Literal["authz-registry/1"] = REGISTRY_VERSION
    stages: tuple[StageDefinition, ...]
    baseline_model_ids: tuple[str, ...]
    operations: dict[str, OperationDefinition]
    bindings: dict[str, EntryBinding]

    @model_validator(mode="after")
    def references(self):
        stages = {(s.namespace, s.stage_id) for s in self.stages}
        if len(stages) != len(self.stages):
            raise ValueError("Duplicate stage")
        if not self.baseline_model_ids or len(set(self.baseline_model_ids)) != len(self.baseline_model_ids):
            raise ValueError("Empty/duplicate baseline allowlist")
        for key, operation in self.operations.items():
            if key != operation.operation_id:
                raise ValueError("Operation key/id mismatch: " + key)
            if (operation.stage_namespace, operation.stage) not in stages:
                raise ValueError("Unknown stage: " + key)
        for key, binding in self.bindings.items():
            if binding.operation_id not in self.operations:
                raise ValueError("Unknown operation binding: " + key)
        return self


def load_registry(text: str) -> AccessRegistry:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate registry JSON key: " + key)
            result[key] = value
        return result
    return AccessRegistry.model_validate(json.loads(text, object_pairs_hook=unique_keys))


REGISTRY = load_registry(Path(__file__).with_name("access_registry.v1.json").read_text(encoding="utf-8"))


def validate_inventory(report: dict) -> None:
    """CI exact coverage of application API templates and the four task aliases."""
    expected = {e["id"] for e in report["entries"] if e["kind"] in {"api", "task_alias"}}
    if expected != set(REGISTRY.bindings):
        raise ValueError("AUTH-00 / AUTH-01 binding drift: " + repr(sorted(expected ^ set(REGISTRY.bindings))))


class ModelWorkload(ContractModel):
    model_ids: tuple[str, ...] = Field(min_length=1)
    rows: int = Field(gt=0, strict=True)
    folds: int = Field(gt=0, strict=True)
    horizon: int = Field(gt=0, strict=True)
    seasonal_period: int = Field(gt=0, strict=True)
    custom_parameters: bool = Field(strict=True)

    @model_validator(mode="after")
    def unique_models(self):
        if len(set(self.model_ids)) != len(self.model_ids) or any(not m for m in self.model_ids):
            raise ValueError("Empty/duplicate model id")
        return self


class FunctionalDecision(ContractModel):
    allowed: bool
    code: str
    registry_version: Literal["authz-registry/1"] = REGISTRY_VERSION
    operation_id: str


def stage_allowed(caps: Capabilities, namespace: str, stage: str) -> bool:
    if not any(s.namespace == namespace and s.stage_id == stage for s in REGISTRY.stages):
        return False
    # Only application stage IDs participate in the product deny-list.
    return namespace != "application" or stage not in caps.restricted_stage_ids


def evaluate_operation(
    caps: Capabilities, operation_id: str, *, registry_version: str = REGISTRY_VERSION,
    workload: ModelWorkload | None = None, stage: str | None = None,
) -> FunctionalDecision:
    """Functional permission only; never infer a plan/role from user input.

    The caller validates model readiness and supplies the ACTUAL persisted fit
    context, including diagnostics/forecast selectors. Do not pass a browser's
    claim that an advanced result was a baseline. No CU/rate reservation here.
    """
    def result(code: str) -> FunctionalDecision:
        return FunctionalDecision(allowed=code == "functional_allowed", code=code, operation_id=operation_id)
    if registry_version != REGISTRY_VERSION or caps.registry_version != REGISTRY_VERSION:
        return result("registry_version_mismatch")
    operation = REGISTRY.operations.get(operation_id)
    if operation is None:
        return result("unknown_operation")
    if operation.authority == "unavailable":
        return result("operation_unavailable")
    if operation.authority == "external":
        return result("external_policy_required")
    if not stage_allowed(caps, operation.stage_namespace, operation.stage):
        return result("stage_restricted")
    if operation.selector == "scientific_stage":
        if stage is None or not stage_allowed(caps, "scientific", stage):
            return result("unknown_stage")
    if operation.capability is not None and not getattr(caps, operation.capability):
        return result("capability_not_included")
    if operation.selector == "model":
        if workload is None:
            return result("model_context_required")
        if caps.max_dataset_rows is not None and workload.rows > caps.max_dataset_rows:
            return result("dataset_limit_exceeded")
        baseline = not workload.custom_parameters and set(workload.model_ids) <= set(REGISTRY.baseline_model_ids)
        if not baseline:
            return result("functional_allowed" if caps.can_train_custom_models else "capability_not_included")
        if not caps.can_run_baseline_models:
            return result("capability_not_included")
        limits = caps.baseline_limits
        if (workload.rows > limits.max_rows or workload.folds > limits.max_folds
            or workload.horizon > limits.max_horizon or workload.seasonal_period > limits.max_seasonal_period
            or len(workload.model_ids) > limits.max_models):
            return result("baseline_limit_exceeded")
    return result("functional_allowed")


def evaluate_entry(caps: Capabilities, entry_id: str, **context) -> FunctionalDecision:
    """entry_id is an exact source inventory template, never a prefix matcher."""
    binding = REGISTRY.bindings.get(entry_id)
    if binding is None:
        return FunctionalDecision(allowed=False, code="unknown_entry", operation_id=entry_id)
    if binding.programmatic_api and not caps.can_use_api:
        return FunctionalDecision(allowed=False, code="api_not_included", operation_id=binding.operation_id)
    return evaluate_operation(caps, binding.operation_id, **context)


def contract_openapi() -> dict:
    """Standalone OpenAPI DTO document; application startup/science unnecessary.

    install_openapi_contract exposes the same schemas in the application's
    /openapi.json, without adding an endpoint or an auth/me placeholder.
    """
    from pydantic.json_schema import models_json_schema

    _, schema = models_json_schema(
        [(m, "serialization") for m in (Capabilities, AccessRegistry, ModelWorkload, FunctionalDecision)],
        ref_template="#/components/schemas/{model}",
    )
    return {"openapi":"3.1.0", "info":{"title":"CISStat access contract", "version":REGISTRY_VERSION},
            "paths":{}, "components":{"schemas":schema["$defs"]},
            "x-cisstat-access-registry":REGISTRY.model_dump(mode="json")}


def install_openapi_contract(app) -> None:
    """Add versioned components lazily to FastAPI's existing schema generator."""
    original = app.openapi
    def comparable(value):
        # FastAPI drops null defaults while serializing its OpenAPI DTOs.
        if isinstance(value, dict):
            return {k:comparable(v) for k,v in value.items() if not (k == "default" and v is None)}
        if isinstance(value, list):
            return [comparable(v) for v in value]
        return value
    def openapi():
        schema = original()
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, definition in contract_openapi()["components"]["schemas"].items():
            if name in schemas and comparable(schemas[name]) != comparable(definition):
                raise ValueError("OpenAPI access contract name collision: " + name)
            schemas[name] = definition
        schema["x-cisstat-access-registry"] = REGISTRY.model_dump(mode="json")
        for path, methods in schema.get("paths", {}).items():
            for method, operation in methods.items():
                binding = REGISTRY.bindings.get(f"api:{method.upper()}:{path}")
                if binding is not None:
                    operation["x-cisstat-operation-id"] = binding.operation_id
        return schema
    app.openapi = openapi
