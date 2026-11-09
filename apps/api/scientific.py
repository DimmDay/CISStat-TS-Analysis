"""AUTH-11: one HTTP scientific admission path over current AUTH-03/08/09 authority."""

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from apps.api.access_registry import (
    REGISTRY,
    ModelWorkload,
    evaluate_entry,
    evaluate_operation,
)
from apps.api.auth import get_current_principal
from apps.api.authentication.context import (
    _request_id,
    auth_error,
    resolve_request_context,
)
from apps.api.plans import AuthenticatedPrincipal
from apps.api.scientific_workload import actual_rows, model_workloads

ACTIVE_ADMISSION = ContextVar("cisstat_scientific_admission", default=None)
ADMIN_OPERATIONS = frozenset(
    {"observability.get_admin_overview", "observability.get_case_bank_candidates"}
)
# These existing state/report operations carry research data although their stage is service.
RESEARCH_OPERATIONS = frozenset(
    op
    for op in REGISTRY.operations
    if op.startswith("platform.")
    and op not in {"platform.health", "platform.health_ops"}
) | {"session.stage.select"}
REPLACEMENTS = frozenset(
    {"upload.file.load", "upload.db.load", "upload.demo_dataset.load"}
)


@dataclass(frozen=True)
class ScientificAdmission:
    context: object
    caps: object
    operation_id: str
    entry_id: str
    session: object = None


def scientific_mode():
    from apps.api.identity import MODE_SCOPED, get_identity_mode
    from apps.api.storage_diagnostics import get_storage_mode

    try:
        protected = (
            get_storage_mode() == "required" or get_identity_mode() == MODE_SCOPED
        )
        mode = os.environ.get("CISSTAT_SCIENTIFIC_GUARD_MODE", "").strip().lower() or (
            "enforce" if protected else "legacy_dev"
        )
        if mode not in {"enforce", "legacy_dev"} or (protected and mode != "enforce"):
            auth_error(503, "auth_authority_unavailable")
        return mode
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 -- fail closed without configuration/driver disclosure
        auth_error(503, "auth_authority_unavailable")


def guarded_operation(operation_id):
    operation = REGISTRY.operations.get(operation_id)
    return operation is not None and (
        operation.stage_namespace in {"scientific", "application"}
        or operation_id in RESEARCH_OPERATIONS
    )


def entry_for_request(request):
    matches = []
    for entry, binding in REGISTRY.bindings.items():
        if not entry.startswith("api:"):
            continue
        _, method, template = entry.split(":", 2)
        if method != request.method:
            continue
        pattern = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", re.escape(template))
        if re.fullmatch(pattern, request.url.path):
            matches.append((entry, binding))
    if len(matches) != 1:
        auth_error(403, "unknown_entry", _request_id(request))
    return matches[0]


def _error(code, admission):
    status = (
        402
        if code
        in {
            "capability_not_included",
            "baseline_limit_exceeded",
            "dataset_limit_exceeded",
            "api_not_included",
        }
        else 403
    )
    if code == "model_context_required":
        status = 409
    if code == "operation_unavailable":
        status = 501
    context = admission.context
    try:
        from apps.api.security_audit import record_standard

        record_standard(
            "authz_denied",
            "denied",
            actor_subject=context.subject_id,
            actor_via=context.auth_method,
            tenant_id=context.tenant_id,
            resource_kind="scientific_operation",
            resource_id=admission.operation_id,
            policy_basis="AUTH-11 operation admission",
            details={"reason_code": code},
        )
    except Exception:  # noqa: BLE001, S110 -- standard deny audit cannot change a denial
        pass
    auth_error(status, code, context.request_id)


def _decide(admission, workload=None, *, operation_id=None, stage=None):
    if operation_id is None:
        decision = evaluate_entry(
            admission.caps, admission.entry_id, workload=workload, stage=stage
        )
    else:
        decision = evaluate_operation(
            admission.caps, operation_id, workload=workload, stage=stage
        )
    if not decision.allowed:
        _error(decision.code, admission)


def _owned_session(request, context):
    from apps.api.identity import authorize_run_access
    from apps.api.research_runs import get_research_run_store
    from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store

    pointer = request.cookies.get(SESSION_COOKIE_NAME)
    subject = context.as_subject()
    session = None
    if pointer:
        session = get_session_store().get(pointer)
        if session is not None:
            if session.owner_account_id is not None:
                if not authorize_run_access(session, subject, action="read").allowed:
                    auth_error(404, "scientific_object_not_found", context.request_id)
            elif session.dataset is not None or session.run_id:
                auth_error(404, "scientific_object_not_found", context.request_id)
            else:
                session = None
    run_id = request.path_params.get("run_id") or (
        getattr(session, "run_id", None) if session else None
    )
    if run_id:
        run = get_research_run_store().get_run(run_id)
        if run is None or not authorize_run_access(run, subject, action="read").allowed:
            auth_error(404, "scientific_object_not_found", context.request_id)
        if session is None or session.run_id != run_id:
            session = (
                get_session_store().get(run.session_id) if run.session_id else None
            )
            if (
                session is not None
                and not authorize_run_access(session, subject, action="read").allowed
            ):
                auth_error(404, "scientific_object_not_found", context.request_id)
    return session


def preflight(request):
    if getattr(request.state, "_auth11_preflight_done", False):
        return getattr(request.state, "_auth11_admission", None)
    mode = scientific_mode()
    # Preserve local unbound fixtures; personal/durable credentials never opt out.
    headers = request.headers
    has_personal = "__Host-cisstat_auth" in request.cookies
    has_durable = any(
        value.startswith("csk_") for value in headers.getlist("x-api-key")
    )
    if mode == "legacy_dev" and not has_personal and not has_durable:
        request.state._auth11_preflight_done = True
        request.state._auth11_admission = None
        return None
    entry, binding = entry_for_request(request)
    if binding.operation_id in ADMIN_OPERATIONS:
        return None  # Existing ADMIN+MFA dependency remains authoritative.
    if not guarded_operation(binding.operation_id):
        auth_error(403, "unknown_entry", _request_id(request))
    context = resolve_request_context(request)
    if context.auth_method not in {"auth_session", "api_key"} or not context.account_id:
        auth_error(401, "authentication_required", context.request_id)
    if binding.programmatic_api:
        if context.auth_method != "api_key":
            auth_error(401, "api_key_required", context.request_id)
    elif context.auth_method != "auth_session":
        auth_error(403, "scientific_credential_not_allowed", context.request_id)
    caps = context.account_capabilities
    if caps is None:
        auth_error(503, "auth_authority_unavailable", context.request_id)
    try:
        session = _owned_session(request, context)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 -- fail closed without configuration/driver disclosure
        auth_error(503, "auth_authority_unavailable", context.request_id)
    admission = ScientificAdmission(context, caps, binding.operation_id, entry, session)
    operation = REGISTRY.operations[binding.operation_id]
    # Object ownership precedes commercial/stage barriers. A model-selector
    # decision needs actual workload; all other policies can reject before body parsing.
    if operation.selector != "model":
        stage = request.path_params.get("stage")
        if binding.operation_id == "upload.capture_dataset_passport":
            stage = {
                "start": "upload",
                "validation": "validation",
                "exit": "preprocessing",
                "modeling_entry": "modeling",
            }.get(stage)
        _decide(admission, stage=stage)
    else:
        preliminary = evaluate_entry(caps, entry)
        if not preliminary.allowed and preliminary.code != "model_context_required":
            _error(preliminary.code, admission)
    if binding.operation_id == "validation.rules.update_rules":
        # Legacy process-global mutable templates have no account-owned storage.
        # Use the existing session-scoped /dataset/validation-rules instead.
        _error("operation_unavailable", admission)
    if (
        binding.operation_id in {"upload.file.load", "upload.db.load"}
        and not caps.can_upload_own_data
    ):
        _error("capability_not_included", admission)
    if (
        binding.operation_id
        not in REPLACEMENTS
        | {
            "upload.db.probe",
            "validation.rules.get_rules_templates",
            "validation.rules.load_rules_template",
        }
        and (
            operation.stage_namespace != "service"
            or binding.operation_id == "platform.get_session_dataset"
        )
        and caps.max_dataset_rows is not None
        and actual_rows(session) > caps.max_dataset_rows
    ):
        _error("dataset_limit_exceeded", admission)
    if request.path_params.get("run_id") and not caps.can_save_history:
        pointer = request.cookies.get("cisstat_session_id")
        if (
            binding.operation_id == "platform.restore_run"
            or session is None
            or session.session_id != pointer
        ):
            _error("capability_not_included", admission)
    request.state._auth11_admission = admission
    request.state._auth11_preflight_done = True
    return admission


def admit_payload(request, payload):
    admission = preflight(request)
    if admission is None:
        return None
    operation = REGISTRY.operations[admission.operation_id]
    if admission.caps.max_dataset_rows is not None and isinstance(payload, dict):
        series = payload.get("series")
        if isinstance(series, list) and len(series) > admission.caps.max_dataset_rows:
            _error("dataset_limit_exceeded", admission)
    try:
        with execution_scope(admission):
            values = model_workloads(
                admission.operation_id, request, payload, admission.session
            )
    except (ValueError, TypeError, ValidationError):
        auth_error(422, "invalid_scientific_request", admission.context.request_id)
    # Non-model routes still check actual saved scientific results exposed by
    # current-state/report/application endpoints after a downgrade.
    for workload in values:
        policy = None if operation.selector == "model" else "modeling.get_model_card"
        _decide(admission, workload, operation_id=policy)
    if operation.selector == "model" and not values:
        # An empty collection/missing object contains no fit to grant. The
        # handler preserves its own 404/readiness contract, never executes a fit
        # without another engine-level fence.
        if admission.operation_id in {
            "modeling.backtest",
            "modeling.panel_backtest",
            "modeling.bootstrap_modeling_baselines",
        }:
            _error("model_context_required", admission)
        if (
            not admission.caps.can_run_baseline_models
            and not admission.caps.can_train_custom_models
        ):
            _error("capability_not_included", admission)
    if (
        admission.operation_id == "platform.restore_run"
        and not admission.caps.can_save_history
    ):
        _error("capability_not_included", admission)
    return admission


@contextmanager
def execution_scope(admission):
    token = ACTIVE_ADMISSION.set(admission)
    try:
        yield admission
    finally:
        ACTIVE_ADMISSION.reset(token)


async def scientific_guard(request: Request):
    payload = {}
    media_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if (
        media_type == "application/json"
        or media_type.startswith("application/")
        and media_type.endswith("+json")
        or not media_type
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
    ):
        try:
            payload = await request.json() if await request.body() else {}
        except ValueError:
            auth_error(422, "invalid_scientific_request", _request_id(request))
    admission = await run_in_threadpool(admit_payload, request, payload)
    with execution_scope(admission):
        yield admission


class ScientificRoute(APIRoute):
    """Reject missing/foreign authority before FastAPI reads JSON/multipart."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def guarded(request):
            admission = None
            try:
                admission = await run_in_threadpool(preflight, request)
                from apps.api.authentication.demo_lifecycle import govern
                response = await govern(request, admission, original)
                if admission is not None:
                    response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError:
                if admission is None:
                    raise
                auth_error(
                    422, "invalid_scientific_request", admission.context.request_id
                )
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
                raise

        return guarded


def authorize_execution(
    *,
    model_id,
    rows,
    folds=1,
    horizon=1,
    seasonal_period=1,
    custom_parameters=False,
    operation_id=None,
    parameters=None,
):
    """Last HTTP execution fence over ACTUAL kernel inputs, not browser claims."""
    admission = ACTIVE_ADMISSION.get()
    if admission is None:
        return
    caps = admission.caps
    if caps.max_dataset_rows is not None and rows > caps.max_dataset_rows:
        _error("dataset_limit_exceeded", admission)
    # A tuning admission authorizes its trials, not an unrelated direct fit.
    if admission.operation_id.startswith("modeling.tune"):
        if not caps.can_tune_models:
            _error("capability_not_included", admission)
        return
    from apps.api.scientific_workload import effective_period

    seasonal_period = effective_period(seasonal_period, parameters)
    try:
        workload = ModelWorkload(
            model_ids=(model_id,),
            rows=max(1, rows),
            folds=folds,
            horizon=horizon,
            seasonal_period=seasonal_period,
            custom_parameters=custom_parameters,
        )
    except (ValueError, TypeError):
        _error("model_context_required", admission)
    _decide(admission, workload, operation_id=operation_id or "modeling.backtest")


def enforce_dataframe(request, frame):
    admission = getattr(getattr(request, "state", None), "_auth11_admission", None)
    if (
        admission is not None
        and admission.caps.max_dataset_rows is not None
        and len(frame) > admission.caps.max_dataset_rows
    ):
        _error("dataset_limit_exceeded", admission)


def bounded_db_rows(request, requested):
    admission = getattr(request.state, "_auth11_admission", None)
    cap = admission.caps.max_dataset_rows if admission else None
    return (
        min(requested, cap)
        if cap is not None and requested is not None
        else cap
        if cap is not None
        else requested
    )


def legacy_model_capability(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    # v1 compatibility is only for local legacy fixtures. Real requests have
    # already passed operation-based admission (baseline != can_train_models).
    if (
        getattr(request.state, "_auth11_admission", None) is None
        and not principal.capabilities.can_train_models
    ):
        raise HTTPException(
            403, "Текущий план не включает возможность 'can_train_models'"
        )


def filter_candidates(request, response):
    admission = getattr(getattr(request, "state", None), "_auth11_admission", None)
    if admission is None:
        return response
    from apps.api.schemas import ModelStageCapability

    caps = admission.caps
    for candidate in response.catalog:
        actions = list(candidate.available_actions)
        if (
            not caps.can_train_custom_models
            and candidate.model_id not in REGISTRY.baseline_model_ids
        ):
            actions = []
        if not caps.can_tune_models:
            actions = [a for a in actions if a != "tune"]
        if actions != candidate.available_actions:
            candidate.available_actions = actions
            for stage, capability in candidate.stage_capabilities.items():
                if capability.action and capability.action not in actions:
                    candidate.stage_capabilities[stage] = ModelStageCapability(
                        status="blocked",
                        required=capability.required,
                        action=capability.action,
                        reason="Возможность не включена в текущий тариф Account",
                    )
    by_id = {c.model_id: c for c in response.catalog}
    response.candidates = [by_id[c.model_id] for c in response.candidates]
    response.statistics.runnable_candidates = sum(
        "backtest" in c.available_actions for c in response.candidates
    )
    response.statistics.blocked_candidates = sum(
        c.platform_status == "ready" and not c.available_actions
        for c in response.catalog
    )
    return response


def baseline_cohort(request, model_ids):
    admission = getattr(request.state, "_auth11_admission", None)
    if admission is None or admission.caps.can_train_custom_models:
        return model_ids
    return [m for m in model_ids if m in REGISTRY.baseline_model_ids][
        : admission.caps.baseline_limits.max_models
    ]


def authorize_dataframe(frame):
    """Guard actual replacement/expanded frames before AnalysisSession mutation."""
    admission = ACTIVE_ADMISSION.get()
    if (
        admission is not None
        and frame is not None
        and admission.caps.max_dataset_rows is not None
        and len(frame) > admission.caps.max_dataset_rows
    ):
        _error("dataset_limit_exceeded", admission)


def bounded_default(name, value):
    """Only bound SERVER defaults; explicit analyst validation choices are preserved."""
    admission = ACTIVE_ADMISSION.get()
    if admission is None or admission.caps.can_train_custom_models:
        return value
    field = {"folds": "max_folds", "horizon": "max_horizon", "models": "max_models"}[
        name
    ]
    return min(value, getattr(admission.caps.baseline_limits, field))
