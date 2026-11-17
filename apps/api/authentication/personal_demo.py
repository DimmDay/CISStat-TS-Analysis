"""Verified-email personal trial provisioner. One transaction, bounded launch pool."""

import hashlib
import os
from datetime import timedelta
from uuid import UUID

from apps.api.authentication.context import auth_error
from apps.api.authentication.storage import PostgresAccessStore
from apps.api.billing.coordinator import audit
from apps.api.billing.policy import BudgetPolicy
from apps.api.billing.wallet import WalletService
from apps.api.plans import PLAN_DEFINITIONS, PlanName
from apps.api.workers.connection import bind_connection

from .personal_demo_migrations import check_schema

POOL_ID = UUID("00000000-0000-4000-8000-000000000036")
PROFILE = {
    "days": 14,
    "micro_cu": 100000000,
    "analyses": 10,
    "concurrency": 1,
    "max_rows": 50000,
}


def enabled():
    return os.environ.get("CISSTAT_PERSONAL_DEMO_ENABLED") == "1"


def profile(row=None):
    return {
        **PROFILE,
        **({k: row[k] for k in ("days", "micro_cu", "analyses")} if row else {}),
        "max_rows": PLAN_DEFINITIONS[PlanName.STARTER].max_dataset_rows,
    }


def _pool(c, lock=False):
    return c.execute(
        "SELECT * FROM auth_personal_demo_pool WHERE pool_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (POOL_ID,),
    ).fetchone()


def metadata(store=None):
    from .email_challenges import email_configured

    result = {"available": False, "limits": profile()}
    if not enabled() or not email_configured():
        return result
    try:
        store = store or PostgresAccessStore.from_env()
        with store.transaction(readonly=True) as tx:
            c = tx.connection
            check_schema(c)
            row = _pool(c)
            now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
            if row:
                result["limits"] = profile(row)
                count = c.execute(
                    "SELECT count(*) AS n FROM auth_personal_trials WHERE pool_id=%s",
                    (POOL_ID,),
                ).fetchone()["n"]
                result["available"] = (
                    row["status"] == "active"
                    and now < row["signup_ends_at"]
                    and count < row["max_trials"]
                )
    except Exception:  # noqa: BLE001 -- public availability is bounded; no driver details
        return result
    return result


def enroll(c, store, subject, account, email, now):
    """Only invoked after email proof inside consume transaction. No body actor/amount claims."""
    check_schema(c)
    old = c.execute(
        "SELECT * FROM auth_personal_trials WHERE subject_id=%s", (subject,)
    ).fetchone()
    if old:
        return False
    a = c.execute(
        "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE", (account,)
    ).fetchone()
    if (
        not a
        or a["plan"] != "starter"
        or a["account_type"] != "mono"
        or a["status"] != "active"
        or a["plan_expires_at"]
        and a["plan_expires_at"] <= now
    ):
        return False
    memberships = c.execute(
        "SELECT * FROM auth_memberships WHERE subject_id=%s AND status='active'",
        (subject,),
    ).fetchall()
    if (
        len(memberships) != 1
        or memberships[0]["account_id"] != account
        or memberships[0]["account_role"] != "owner"
    ):
        return False
    # Existing funded/managed/purchased accounts are never re-provisioned or reset.
    for table in ("auth_budget_scopes", "auth_wallets", "auth_reservations"):
        if c.execute(
            "SELECT 1 FROM " + table + " WHERE account_id=%s LIMIT 1", (account,)
        ).fetchone():
            return False
    pool = _pool(c, True)
    count = c.execute(
        "SELECT count(*) AS n FROM auth_personal_trials WHERE pool_id=%s", (POOL_ID,)
    ).fetchone()["n"]
    if (
        not pool
        or pool["status"] != "active"
        or now >= pool["signup_ends_at"]
        or count >= pool["max_trials"]
    ):
        auth_error(403, "personal_demo_unavailable")
    expires = (
        min(now + timedelta(days=pool["days"]), a["plan_expires_at"])
        if a["plan_expires_at"]
        else now + timedelta(days=pool["days"])
    )
    c.execute(
        "UPDATE auth_accounts SET plan_expires_at=%s,entitlement_version=entitlement_version+1,updated_at=%s WHERE account_id=%s",
        (expires, now, account),
    )
    reason = "Verified email personal trial; one-time pilot allocation"
    # Production EmailChallengeService has no injected store. Resolve the
    # environment authority before binding this transaction for policy/wallet.
    store = store if store is not None else PostgresAccessStore.from_env()
    policy = BudgetPolicy(store)
    with bind_connection(c, store):
        policy.create_scope(
            "account",
            account_id=account,
            parent_id=pool["sponsor_id"],
            starts_at=now,
            reason=reason,
        )
        grant = policy.create_scope(
            "grant",
            account_id=account,
            parent_id=account,
            starts_at=now,
            ends_at=expires,
            reason=reason,
        )
        for sid in (account, grant["scope_id"]):
            for metric, limit in [("cu", pool["micro_cu"]), ("concurrency", 1)]:
                policy.set_budget(sid, metric, limit_units=limit, reason=reason)
        policy.set_budget(
            grant["scope_id"], "analysis", limit_units=pool["analyses"], reason=reason
        )
        period = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while period < expires:
            policy.set_budget(
                grant["scope_id"],
                "api",
                limit_units=PLAN_DEFINITIONS[PlanName.STARTER].max_api_calls_per_month,
                period=period.strftime("%Y-%m"),
                reason=reason,
            )
            period = (period.replace(day=28) + timedelta(days=4)).replace(day=1)
        wallet = WalletService(store)
        wallet.create_wallet(account, reason=reason)
        issued = wallet.issue_promotional(
            account,
            pool["micro_cu"],
            origin_ref="personal-demo:" + str(subject),
            expires_at=expires,
            reason=reason,
        )
    c.execute(
        "INSERT INTO auth_personal_trials VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            subject,
            account,
            hashlib.sha256(email.encode()).hexdigest(),
            POOL_ID,
            UUID(str(issued["lot_id"])),
            now,
            expires,
        ),
    )
    from .demo_admin_notifications import enqueue
    enqueue(c, subject, email, now, expires, profile(pool))
    audit(
        c,
        "auth_budget_changed",
        account,
        actor=str(subject),
        details={
            "command": "personal_demo_enrolled",
            "pool_id": str(POOL_ID),
            "micro_cu": pool["micro_cu"],
            "analyses": pool["analyses"],
        },
    )
    return True


async def govern_upload(request, admission, handler):
    """Keep trial first-run claim and durable upload in the same SQL transaction."""
    if admission is None or admission.operation_id not in {
        "upload.file.load",
        "upload.db.load",
        "upload.demo_dataset.load",
    }:
        return await handler(request)
    store = (
        getattr(request.app.state, "auth_access_store", None)
        or PostgresAccessStore.from_env()
    )
    with store.transaction() as tx:
        c = tx.connection
        exists = c.execute(
            "SELECT to_regclass('auth_personal_trials') AS name"
        ).fetchone()["name"]
        if not exists:
            if enabled():
                auth_error(503, "auth_authority_unavailable")
            trial = None
        else:
            check_schema(c)
            trial = c.execute(
                "SELECT 1 FROM auth_personal_trials WHERE account_id=%s",
                (admission.context.account_id,),
            ).fetchone()
        if trial:
            from .demo_lifecycle import REQUEST

            token = REQUEST.set(request)
            try:
                with bind_connection(c, store):
                    return await handler(request)
            finally:
                REQUEST.reset(token)
    return await handler(request)


def prepare_analysis(request):
    """Server-owned run id; called by every dataset creation alias before publication."""
    if getattr(request.state, "_personal_demo_run_id", None):
        return request.state._personal_demo_run_id
    from uuid import uuid4

    from apps.api.billing.contract import Admission, Cost
    from apps.api.billing.coordinator import ReservationCoordinator
    from apps.api.workers.connection import access_connection

    from .sessions import SessionService

    store = (
        getattr(request.app.state, "auth_access_store", None)
        or PostgresAccessStore.from_env()
    )
    c = access_connection(store)
    if c is None:
        auth_error(503, "auth_authority_unavailable")
    current = request.state._auth11_admission
    ctx = current.context
    now = SessionService(store)._now(c)
    run = "RUN-" + uuid4().hex.upper()
    coordinator = ReservationCoordinator(store)
    receipt = coordinator.reserve(
        ctx,
        Admission(
            entry_id=current.entry_id,
            resource_kind="run",
            resource_id=run,
            analysis_run_id=run,
            idempotency_key="personal:" + run,
            payload={"run": run},
            cost=Cost(micro_cu=0, version="personal-analysis/1"),
            deadline=min(now + timedelta(seconds=60), ctx.plan_expires_at),
            slots=0,
        ),
    )
    coordinator.release(receipt.reservation_id, expected_version=receipt.version)
    request.state._personal_demo_run_id = run
    return run
