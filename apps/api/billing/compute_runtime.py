"""PELT/tuning adapters over AUTH-13; actual kernels supply every work dimension."""

import functools, inspect, typing
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid5, NAMESPACE_URL
from apps.api.authentication.context import auth_error
from .contract import Admission, Cost, digest_payload
from .compute_units import Workload, Quote, charge_units
from .compute_profile import load_profile
from .compute_meter import IN_CHILD
from .compute_cache import CachedResponse

ROUTE = ContextVar("cisstat_compute_route", default=None)


def profile_or_error():
    try:
        return load_profile()
    except Exception:
        auth_error(503, "compute_profile_unavailable")


def tuning_work(arguments, *, single=False):
    model = arguments["model_id"]
    plan = arguments.get("plan")
    if plan is None:
        from apps.api.routers.models import _build_grid, _truncate_grid, MAX_TRIALS

        spec = arguments["spec"].get_model(model)
        if spec is None or not spec.param_space:
            return None
        selected, _ = _truncate_grid(
            _build_grid(spec.param_space),
            min(arguments.get("max_trials") or MAX_TRIALS, MAX_TRIALS),
            arguments["random_state"],
        )
        folds = arguments["cv_config"].n_splits
        horizon = arguments["cv_config"].test_size + arguments["cv_config"].gap
        rows = len(arguments["series"])
        period = 1
        columns = 1
    else:
        from apps.api.modeling_tuning import prepare_tuning_grid

        selected = (
            [arguments.get("params", {})]
            if single
            else prepare_tuning_grid(
                arguments["param_space"],
                max_trials=arguments.get("max_trials"),
                metric=arguments["metric"],
                random_state=arguments.get("random_state", 42),
            ).selected
        )
        folds = len(plan.folds)
        horizon = plan.horizon + plan.gap
        rows = plan.n_observations
        period = int(arguments.get("seasonal_period", 1))
        system = arguments.get("system")
        columns = max(1, len(getattr(system, "series", {}) or {})) + max(
            len(getattr(plan, "feature_columns", ()) or ()),
            len(getattr(getattr(plan, "feature_plan", None), "features", ()) or ()),
        )
    return Workload(
        key="tuning:" + model,
        rows=rows,
        columns=columns,
        units=len(selected) * folds,
        folds=folds,
        trials=len(selected),
        horizon=horizon,
        seasonal_period=max(1, period),
    )


def pelt_work(arguments):
    from app.eda.structural_breaks import (
        MAX_PELT_GRID_POINTS,
        SENSITIVITY_MULTIPLIERS,
        MIN_STRUCTURAL_OBSERVATIONS,
    )
    import math

    rows = len(arguments["series"])
    if rows < MIN_STRUCTURAL_OBSERVATIONS:
        return None
    import pandas as pd
    import numpy as np

    if (
        pd.to_numeric(arguments["series"], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .isna()
        .any()
    ):
        return None
    jump = max(1, math.ceil(rows / MAX_PELT_GRID_POINTS))
    return Workload(
        key="pelt",
        rows=rows,
        columns=3,
        grid_points=math.ceil(rows / jump),
        units=10 + len(SENSITIVITY_MULTIPLIERS) + 2,
    )


def make_quote(work):
    profile = profile_or_error()
    if profile is None:
        return None
    try:
        return profile.quote(work)
    except ValueError:
        auth_error(402, "compute_work_not_calibrated")


def saved_charge(descriptor, proof):
    raw = descriptor.get("compute_quote")
    if not raw:
        return 0
    quote = Quote.model_validate(raw)
    usage = proof.get("usage")
    if proof.get("outcome") == "not_started":
        return 0
    if not isinstance(usage, dict) or usage.get("key") != quote.workload.key:
        auth_error(409, "worker_uncertain")
    try:
        return charge_units(quote, usage["units"])
    except (KeyError, ValueError):
        auth_error(409, "worker_uncertain")


def compute_route(fn):
    # Resolving postponed annotations keeps FastAPI/OpenAPI signatures intact.
    signature = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    signature = signature.replace(
        parameters=[
            p.replace(annotation=hints.get(n, p.annotation))
            for n, p in signature.parameters.items()
        ],
        return_annotation=hints.get("return", signature.return_annotation),
    )

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        from apps.api.scientific import ACTIVE_ADMISSION
        from apps.api.workers.execution import ACTIVE

        if ACTIVE_ADMISSION.get() is None:
            return fn(*args, **kwargs)
        bound = signature.bind(*args, **kwargs).arguments
        controller = {
            "request": bound.get("request"),
            "work": None,
            "active_token": None,
        }
        token = ROUTE.set(controller)
        try:
            result = fn(*args, **kwargs)
            work = controller["work"]
            if work is not None and not work.published:
                from fastapi.encoders import jsonable_encoder

                work.publish(
                    lambda c: None, descriptor={"response": jsonable_encoder(result)}
                )
            return result
        except CachedResponse as replay:
            return replay.value
        finally:
            if controller["active_token"] is not None:
                ACTIVE.reset(controller["active_token"])
            if controller["work"] is not None:
                controller["work"].abort()
            ROUTE.reset(token)

    wrapped.__signature__ = signature
    return wrapped


def compute_kernel(kind, *, single=False):
    def decorate(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            from apps.api.scientific import ACTIVE_ADMISSION
            from apps.api.workers.execution import ACTIVE, Execution

            if IN_CHILD.get() or ACTIVE_ADMISSION.get() is None:
                return fn(*args, **kwargs)
            arguments = signature.bind(*args, **kwargs)
            arguments.apply_defaults()
            work = (
                pelt_work(arguments.arguments)
                if kind == "pelt"
                else tuning_work(arguments.arguments, single=single)
            )
            if work is None:
                return fn(*args, **kwargs)
            active = ACTIVE.get()
            if active is not None:
                return active.run(wrapped, *args, **kwargs)
            controller = ROUTE.get()
            if controller is None:
                auth_error(503, "compute_route_required")
            admission = ACTIVE_ADMISSION.get()
            session = admission.session
            from apps.api.workers.bridge import authority

            auth = authority(controller["request"])
            request = controller["request"]
            input_hash = digest_payload(_safe_inputs(arguments.arguments))
            client_key = (
                request.headers.get("Idempotency-Key") if request is not None else None
            )
            if client_key is not None and not 1 <= len(client_key) <= 128:
                auth_error(422, "invalid_scientific_request")
            if not client_key and request is not None and request.method == "GET":
                from .compute_profile import kernel_digest

                client_key = digest_payload(
                    {
                        "inputs": input_hash,
                        "kernels": kernel_digest(),
                        "credential": admission.context.credential_id,
                        "context": session.current_context_id() if session else None,
                    }
                )
            operation = (
                str(
                    uuid5(
                        NAMESPACE_URL,
                        ":".join(
                            (
                                admission.context.account_id,
                                admission.context.subject_id,
                                admission.entry_id,
                                session.run_id if session else "stateless",
                                client_key,
                            )
                        ),
                    )
                )
                if client_key
                else str(uuid4())
            )
            existing = auth.find("modeling", operation) if client_key else None
            if existing:
                if existing["descriptor"].get("input_hash") != input_hash:
                    auth_error(409, "idempotency_conflict")
                from .compute_cache import read

                return read(auth, admission.context, existing)
            quote = make_quote(work)
            limits = runtime_limits(work, quote)
            description = {
                "family": "inline",
                "input_hash": input_hash,
                "resource_kind": "run" if session and session.run_id else "stateless",
                "compute_work": work.model_dump(mode="json"),
                "compute_quote": quote.model_dump(mode="json") if quote else None,
                "data_digest": session.data_digest if session else None,
            }
            resource = (
                session.run_id
                if session and session.run_id
                else "stateless:" + operation
            )
            deadline = datetime.now(UTC) + timedelta(milliseconds=limits["wall_ms"])
            if admission.context.plan_expires_at:
                deadline = min(deadline, admission.context.plan_expires_at)
            req = Admission(
                entry_id=admission.entry_id,
                resource_kind=description["resource_kind"],
                resource_id=resource,
                idempotency_key="inline:" + operation,
                payload={
                    "work": description["compute_work"],
                    "inputs": digest_payload(_safe_inputs(arguments.arguments)),
                },
                cost=Cost(
                    micro_cu=quote.reserved_micro_cu if quote else 0,
                    version=quote.version if quote else "unpriced-auth13/1",
                ),
                deadline=deadline,
                slots=1,
            )
            row = auth.admit(
                admission.context,
                req,
                kind="modeling",
                external_id=operation,
                run_id=resource,
                session_id=session.session_id if session and session.run_id else None,
                context_id=session.current_context_id()
                if session and session.run_id
                else None,
                descriptor=description,
            )
            claim = auth.claim(
                row["worker_id"],
                lease_seconds=min(3600, max(1, (limits["wall_ms"] + 999) // 1000 + 5)),
            )
            execution = Execution(
                auth,
                claim,
                timeout=limits["wall_ms"] / 1000,
                memory_mb=limits["memory_mb"],
            )
            execution.inline = True
            execution.compute_descriptor = description
            controller["work"] = execution
            controller["active_token"] = ACTIVE.set(execution)
            result = execution.run(wrapped, *args, **kwargs)
            from .compute_cache import stage

            if not hasattr(result, "response"):
                reference = stage(result, kind)
                execution.proof = auth.attach_result(
                    execution.claim, execution.proof, reference
                )
                from apps.api.workers.spool import save

                save(execution.claim, execution.proof)
            return result

        return wrapped

    return decorate


def _safe_inputs(arguments):
    # Canonical across Python processes; pickle/set iteration is not an idempotency key.
    import dataclasses
    from collections.abc import Mapping
    from pydantic import BaseModel

    def plain(value):
        if isinstance(value, float):
            import math

            if not math.isfinite(value):
                return {"$nonfinite": str(value)}
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, BaseModel):
            return plain(value.model_dump(mode="json"))
        if dataclasses.is_dataclass(value):
            return {
                f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)
            }
        if isinstance(value, Mapping):
            return {str(k): plain(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [plain(x) for x in value]
        if type(value).__module__.startswith("pandas.") and hasattr(value, "index"):
            return {
                "values": plain(value.to_numpy().tolist()),
                "index": plain(value.index.tolist()),
                "columns": plain(value.columns.tolist())
                if hasattr(value, "columns")
                else None,
            }
        if hasattr(value, "item"):
            return plain(value.item())
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "tolist"):
            return plain(value.tolist())
        if callable(value):
            return value.__module__ + "." + value.__qualname__
        if hasattr(value, "__dict__"):
            return {
                "type": type(value).__module__ + "." + type(value).__qualname__,
                "state": plain(vars(value)),
            }
        from pathlib import Path

        if isinstance(value, Path):
            return str(value)
        raise ValueError("unsupported normalized input")

    return {"sha256": digest_payload(plain(arguments))}


def runtime_limits(work, quote):
    if work.key == "pelt":
        limits = {"wall_ms": 60000, "memory_mb": 1024}
    else:
        from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
        from apps.api.model_jobs import resource_policy_for

        descriptor = MODEL_EXECUTION_REGISTRY.describe(work.key.split(":", 1)[1])
        policy = resource_policy_for(descriptor["resource_capabilities"])
        limits = {
            "wall_ms": policy["total_timeout_seconds"] * 1000,
            "memory_mb": policy["memory_limit_mb"],
        }
    if quote:
        limits["wall_ms"] = min(limits["wall_ms"], quote.coefficient.wall_ms)
        limits["memory_mb"] = min(limits["memory_mb"], quote.coefficient.memory_mb)
    return limits
