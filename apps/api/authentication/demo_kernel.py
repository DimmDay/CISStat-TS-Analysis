"""Forum baseline kernels reuse AUTH-13 supervision, slots, fencing and receipts."""

import functools
import inspect
from datetime import UTC, datetime, timedelta
from uuid import uuid4


def bounded_demo_kernel(fn):
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        from apps.api.billing.compute_meter import IN_CHILD
        from apps.api.scientific import ACTIVE_ADMISSION
        from apps.api.workers.execution import ACTIVE, Execution

        if (
            IN_CHILD.get()
            and fn.__name__ == "compute_forecast"
            and kwargs.get("registry") is None
        ):
            from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

            kwargs["registry"] = MODEL_EXECUTION_REGISTRY
        admission = ACTIVE_ADMISSION.get()
        if (
            IN_CHILD.get()
            or admission is None
            or not admission.context.demo_grant_id
            or ACTIVE.get() is not None
        ):
            return fn(*args, **kwargs)
        from .demo_lifecycle import REQUEST

        request = REQUEST.get()
        if request is None:
            from .context import auth_error

            auth_error(503, "compute_route_required")
        arguments = signature.bind(*args, **kwargs)
        arguments.apply_defaults()
        v = arguments.arguments
        from apps.api.access_registry import ModelWorkload

        plan = v.get("plan")
        series = v.get("series", v.get("history_values", ()))
        workload = ModelWorkload(
            model_ids=(v["model_id"],),
            rows=len(series),
            folds=len(plan.folds) if plan else 1,
            horizon=plan.horizon + plan.gap
            if plan
            else v.get(
                "horizon",
                max(1, len(series) - int(len(series) * v.get("train_ratio", 0.8))),
            ),
            seasonal_period=v["seasonal_period"],
            custom_parameters=False,
        )
        from apps.api.billing.contract import Admission, Cost
        from apps.api.workers.bridge import authority

        auth = authority(request)
        op = "demo-kernel:" + uuid4().hex
        session = admission.session
        run = session.run_id if session and session.run_id else "stateless:" + op
        deadline = min(
            datetime.now(UTC) + timedelta(seconds=60),
            admission.context.plan_expires_at,
            request.state._auth16_deadline,
        )
        row = auth.admit(
            admission.context,
            Admission(
                entry_id=admission.entry_id,
                resource_kind="run" if session else "stateless",
                resource_id=run,
                idempotency_key=op,
                payload={
                    "request": str(request.state._auth16_call),
                    "kernel": fn.__name__,
                },
                cost=Cost(micro_cu=0, version="demo-baseline/1"),
                deadline=deadline,
                workload=workload,
            ),
            kind="modeling",
            external_id=op,
            run_id=run,
            session_id=session.session_id if session else None,
            context_id=session.current_context_id() if session else None,
            descriptor={
                "family": "inline",
                "resource_kind": "run" if session else "stateless",
                "workload": workload.model_dump(mode="json"),
            },
        )
        execution = Execution(
            auth,
            auth.claim(row["worker_id"], lease_seconds=65),
            timeout=60,
            memory_mb=1024,
        )
        token = ACTIVE.set(execution)
        try:
            if fn.__name__ == "compute_forecast":
                from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

                if v["registry"] is not MODEL_EXECUTION_REGISTRY:
                    from .context import auth_error

                    auth_error(403, "operation_not_allowed")
                kwargs = {**kwargs, "registry": None}
            value = execution.run(wrapped, *args, **kwargs)
            execution.publish(lambda c: None, descriptor={"kernel": fn.__name__})
            return value
        finally:
            execution.abort()
            ACTIVE.reset(token)

    wrapped.__signature__ = signature
    return wrapped
