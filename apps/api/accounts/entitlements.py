"""AUTH-08 Account policy. No role, browser clock or cached cookie plan."""

from collections.abc import Mapping
from datetime import UTC, datetime

from apps.api.plans import INTERNAL_CAPABILITIES, PLAN_DEFINITIONS, PlanName


def account_is_active(account, *, now=None):
    """Half-open lifetime; missing/malformed persisted attributes fail closed."""
    now = now if now is not None else datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("aware account clock required")
    if account is None:
        return False
    status = account["status"] if isinstance(account, Mapping) else account.status
    if status != "active":
        return False
    deadline = (
        account["plan_expires_at"]
        if isinstance(account, Mapping)
        else account.plan_expires_at
    )
    if deadline is not None and deadline.tzinfo is None:
        raise ValueError("aware account expiry required")
    return deadline is None or now < deadline


def account_capabilities(account, *, now=None):
    if not account_is_active(account, now=now):
        raise ValueError("inactive account")
    caps = (
        INTERNAL_CAPABILITIES
        if account.plan == "internal"
        else PLAN_DEFINITIONS[PlanName(account.plan)]
    )
    # No shared mutable policy objects between requests or consumers.
    return caps.model_copy(deep=True)
