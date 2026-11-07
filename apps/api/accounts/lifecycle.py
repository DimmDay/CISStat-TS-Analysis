"""AUTH-08 trusted operator commands, NOT a public Account policy API.

Only a local operator entry point may call these writers. HTTP/session owner
self-service, invitations, seat purchases and OWNER transfers are AUTH-17/18.
All state, scoped invalidation and audit intent commit or roll back together.
"""

import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from apps.api.authentication.errors import RecordNotFound, RepositoryConflict
from apps.api.authentication.mfa_migrations import check_schema
from apps.api.authentication.storage import PostgresAccessStore

from .entitlements import account_is_active
from .models import Account


class AccountChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    plan: (
        Literal["demo", "starter", "professional", "enterprise", "internal"] | None
    ) = None
    status: Literal["active", "suspended", "closed"] | None = None
    account_type: Literal["multi"] | None = None
    plan_expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def explicit_patch(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None
            for key in self.model_fields_set - {"plan_expires_at"}
        ):
            raise ValueError("nonempty explicit account change required")
        return self


def enqueue_audit(connection, action, before, after, *, reason, member=None):
    """Existing catalogue/schema/outbox; no sink commit inside this transaction."""
    from apps.api.security_audit import build_audit_record

    details = {
        "reason": reason,
        "before_version": before.entitlement_version,
        "after_version": after.entitlement_version,
    }
    if member is not None:
        details["member_subject_id"] = str(member[0])
        details["membership_status"] = member[1]
    else:
        for key in ("plan", "status", "account_type", "plan_expires_at"):
            old, new = getattr(before, key), getattr(after, key)
            if old != new:
                details["before_" + key] = (
                    old.isoformat() if isinstance(old, datetime) else old
                )
                details["after_" + key] = (
                    new.isoformat() if isinstance(new, datetime) else new
                )
    record = build_audit_record(
        action,
        "allowed",
        actor_subject="operator:local",
        actor_via="operator_cli",
        tenant_id=str(after.tenant_id),
        resource_kind="account_membership" if member else "account",
        resource_id=str(after.account_id),
        resource_version=str(after.entitlement_version),
        policy_basis="AUTH-08 trusted operator command",
        details=details,
    )
    connection.execute(
        "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
        (record["audit_id"], json.dumps(record)),
    )


class AccountLifecycle:
    """Trusted in-process seam, same authority as auth05/bootstrap CLI.

    No actor/role/tenant assertion from browser input is accepted here. A future
    HTTP adapter must authenticate and authorize independently before calling a
    separately designed self-service command. Do not mount this class as-is.
    """

    def __init__(self, store=None, clock=None):
        self.store = store if store is not None else PostgresAccessStore.from_env()
        self.clock = clock

    def _now(self, c):
        value = (
            self.clock()
            if self.clock
            else c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        )
        if value.tzinfo is None:
            raise ValueError("aware account clock required")
        return value.astimezone(UTC)

    @staticmethod
    def _validate(account_id, expected_version, reason):
        account_id = UUID(str(account_id))
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("positive expected_version required")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise ValueError("reason of 1..256 characters required")
        return account_id

    @staticmethod
    def _invalidate(c, account_id, now, subject=None):
        # Account scoped: neither passwords nor sessions in sibling Accounts
        # are touched. Terminal guards from 0020/0021 prevent resurrection.
        params = (now, account_id, subject, subject)
        c.execute(
            """UPDATE auth_sessions SET revoked_at=%s WHERE account_id=%s
            AND (%s::uuid IS NULL OR subject_id=%s) AND revoked_at IS NULL""",
            params,
        )
        c.execute(
            """UPDATE auth_challenges SET consumed_at=%s WHERE account_id=%s
            AND (%s::uuid IS NULL OR subject_id=%s) AND consumed_at IS NULL""",
            params,
        )

    def change(self, account_id, *, expected_version, change, reason):
        account_id = self._validate(account_id, expected_version, reason)
        if not isinstance(change, AccountChange):
            raise TypeError("validated AccountChange required")
        # Revalidate even a model_construct() object at the trusted boundary.
        patch = change.model_dump(exclude_unset=True)
        change = AccountChange.model_validate(patch)
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            before = Account(**tx.accounts._lock(account_id, expected_version))
            now = self._now(c)
            if all(getattr(before, key) == value for key, value in patch.items()):
                return before
            if before.status == "closed":
                raise RepositoryConflict()
            after = tx.accounts.update(
                account_id, expected_version=expected_version, **patch
            )
            if not account_is_active(before, now=now) or not account_is_active(
                after, now=now
            ):
                self._invalidate(c, account_id, now)
            enqueue_audit(c, "auth_account_changed", before, after, reason=reason)
            return after

    def membership(self, account_id, subject_id, *, expected_version, status, reason):
        account_id = self._validate(account_id, expected_version, reason)
        subject_id = UUID(str(subject_id))
        if status not in ("active", "revoked"):
            raise ValueError("active or revoked status required")
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            before = Account(**tx.accounts._lock(account_id, expected_version))
            member = next(
                (
                    m
                    for m in tx.accounts.memberships(account_id, include_revoked=True)
                    if m.subject_id == subject_id
                ),
                None,
            )
            if member is None:
                raise RecordNotFound()
            if member.status == status:
                return before
            if before.status == "closed" or (
                status == "active" and not account_is_active(before, now=self._now(c))
            ):
                raise RepositoryConflict()
            tx.accounts.update_member(
                account_id, subject_id, expected_version=expected_version, status=status
            )
            # Fence both transitions. Older trusted repository writers could
            # revoke membership without marking the SID terminal; restoration
            # must not revive that historical credential either.
            self._invalidate(c, account_id, self._now(c), subject_id)
            after = tx.accounts.get(account_id)
            # Deferred AUTH-02 constraints still run at commit, including raw
            # SQL writers. Failure rolls back the outbox and invalidation too.
            enqueue_audit(
                c,
                "auth_membership_changed",
                before,
                after,
                reason=reason,
                member=(subject_id, status),
            )
            return after
