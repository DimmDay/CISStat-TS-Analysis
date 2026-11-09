"""AUTH-10 PostgreSQL key authority. No token recovery/cache or ENV fallback."""

import hashlib
import os
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from uuid import UUID, uuid4

from apps.api.accounts.entitlements import account_capabilities, account_is_active
from apps.api.accounts.models import Account

from .api_key_contract import API_SCOPES, IssueKeyBody, RotateKeyBody, VersionBody
from .api_key_migrations import VERSION, check_schema
from .context import VerifiedCredential, auth_error
from .sessions import SessionService, boundary, token_digest
from .storage import PostgresAccessStore

TOKEN = re.compile(r"csk_[A-Za-z0-9_-]{43}\Z")
PUBLIC = (
    "key_id",
    "family_id",
    "subject_id",
    "account_id",
    "label",
    "scopes",
    "version",
    "created_at",
    "expires_at",
    "revoked_at",
    "replaced_by",
)


def new_secret():
    return "csk_" + secrets.token_urlsafe(32)


def secret_digest(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        auth_error(401, "invalid_credential")
    return hashlib.sha256(("cisstat.api-key/1\0" + value).encode()).hexdigest()


def key_mode():
    from apps.api.identity import MODE_SCOPED, get_identity_mode
    from apps.api.storage_diagnostics import get_storage_mode

    protected = get_storage_mode() == "required" or get_identity_mode() == MODE_SCOPED
    value = os.environ.get("CISSTAT_API_KEY_MODE", "").strip().lower() or (
        "durable" if protected else "legacy_dev"
    )
    if value not in ("durable", "legacy_dev") or (protected and value != "durable"):
        auth_error(503, "auth_authority_unavailable")
    return value


def public_key(row):
    return {key: row[key] for key in PUBLIC}


@dataclass(frozen=True)
class IssuedKey:
    secret: str = field(repr=False)
    key: dict


class APIKeyService:
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
            raise ValueError("aware key clock required")
        return value.astimezone(UTC)

    @contextmanager
    def _tx(self):
        key_mode()
        with self.store.transaction() as tx:
            check_schema(tx.connection)
            yield tx.connection

    def _authority(
        self, c, subject, account, *, require_api, lock="UPDATE", active=True
    ):
        # Lock order agrees with SessionService identity first; Account lifecycle
        # never takes Identity locks. Membership trigger locks its Account.
        u = c.execute(
            "SELECT * FROM auth_identities WHERE subject_id=%s FOR " + lock, (subject,)
        ).fetchone()
        a = c.execute(
            "SELECT * FROM auth_accounts WHERE account_id=%s FOR " + lock, (account,)
        ).fetchone()
        m = c.execute(
            "SELECT * FROM auth_memberships WHERE subject_id=%s AND account_id=%s",
            (subject, account),
        ).fetchone()
        if u is None or a is None:
            auth_error(401, "invalid_credential")
        if active and (
            u["status"] != "active"
            or m is None
            or m["status"] != "active"
            or not account_is_active(a, now=self._now(c))
        ):
            auth_error(401, "invalid_credential")
        if (
            require_api
            and not account_capabilities(Account(**a), now=self._now(c)).can_use_api
        ):
            auth_error(403, "api_not_allowed")
        return u, a

    def _session(self, c, token, origin, *, fresh=False, require_api=False):
        hint = c.execute(
            "SELECT subject_id,account_id FROM auth_sessions WHERE token_hash=%s",
            (token_digest(token),),
        ).fetchone()
        if hint is None:
            auth_error(401, "invalid_credential")
        u, a = self._authority(
            c, hint["subject_id"], hint["account_id"], require_api=require_api
        )
        if u["kind"] != "person":
            auth_error(403, "api_key_management_denied")
        service = SessionService(self.store, clock=self.clock)
        row = service._load(c, token_digest(token), touch=False)
        if row.get("demo_grant_id"):
            auth_error(403, "api_key_management_denied")
        if origin is not None and row["origin"] != origin:
            auth_error(401, "invalid_credential")
        if fresh:
            from .mfa import session_mfa

            mfa = session_mfa(c, row, required=u["platform_role"] == "admin")
            at = max(v for v in (row["auth_time"], mfa) if v is not None)
            now = self._now(c)
            if not at <= now < at + timedelta(minutes=15):
                auth_error(403, "reauthentication_required")
        return u, a

    @staticmethod
    def _audit(c, operation, u, a, key, *, via="auth_session", reason=None):
        from apps.api.security_audit import build_audit_record
        from apps.api.telemetry import redact_text

        record = build_audit_record(
            "auth_api_key_changed",
            "allowed",
            actor_subject=str(u["subject_id"])
            if via == "auth_session"
            else "operator:local",
            actor_via=via,
            tenant_id=str(a["tenant_id"]),
            resource_kind="api_key",
            resource_id=str(key["key_id"]),
            resource_version=str(key["version"]),
            policy_basis="AUTH-10 durable key command",
            details={
                "operation": operation,
                "account_id": str(a["account_id"]),
                "subject_id": str(u["subject_id"]),
                "reason": redact_text(reason or "", limit=256),
            },
        )
        c.execute(
            "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
            (record["audit_id"], __import__("json").dumps(record)),
        )

    def _insert(self, c, u, a, label, scopes, expires, *, family=None):
        now = self._now(c)
        if not frozenset(scopes) <= API_SCOPES or not scopes:
            auth_error(403, "api_scope_denied")
        count = c.execute(
            "SELECT count(*) AS n FROM auth_api_keys WHERE subject_id=%s AND account_id=%s AND revoked_at IS NULL AND expires_at>%s",
            (u["subject_id"], a["account_id"], now),
        ).fetchone()["n"]
        if count >= 20:
            auth_error(409, "api_key_limit")
        value = new_secret()
        key_id = uuid4()
        row = c.execute(
            """INSERT INTO auth_api_keys(key_id,family_id,token_hash,subject_id,account_id,subject_version,
            label,scopes,created_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                key_id,
                family or key_id,
                secret_digest(value),
                u["subject_id"],
                a["account_id"],
                u["subject_version"],
                label,
                sorted(scopes),
                now,
                expires,
            ),
        ).fetchone()
        return IssuedKey(value, public_key(row))

    def _issue(self, c, u, a, body, *, via="auth_session", reason=None):
        body = IssueKeyBody.model_validate(body.model_dump())
        expires = self._now(c) + timedelta(days=body.expires_in_days)
        if a["plan_expires_at"] is not None:
            expires = min(expires, a["plan_expires_at"])
        result = self._insert(c, u, a, body.label, body.scopes, expires)
        self._audit(c, "issued", u, a, result.key, via=via, reason=reason)
        return result

    @boundary
    def issue(self, session_token, body, *, origin):
        with self._tx() as c:
            u, a = self._session(c, session_token, origin, fresh=True, require_api=True)
            return self._issue(c, u, a, body)

    @boundary
    def list(self, session_token, *, origin):
        with self._tx() as c:
            u, a = self._session(c, session_token, origin)
            rows = c.execute(
                """SELECT * FROM auth_api_keys WHERE subject_id=%s AND account_id=%s
                ORDER BY (revoked_at IS NULL AND expires_at>clock_timestamp()) DESC,created_at DESC,key_id DESC LIMIT 101""",
                (u["subject_id"], a["account_id"]),
            ).fetchall()
            return {
                "items": [public_key(row) for row in rows[:100]],
                "truncated": len(rows) > 100,
            }

    @staticmethod
    def _owned(c, key_id, u, a, expected):
        if type(expected) is not int or expected < 1:
            auth_error(422, "api_key_invalid_request")
        row = c.execute(
            "SELECT * FROM auth_api_keys WHERE key_id=%s AND subject_id=%s AND account_id=%s FOR UPDATE",
            (UUID(str(key_id)), u["subject_id"], a["account_id"]),
        ).fetchone()
        if row is None:
            auth_error(404, "api_key_not_found")
        if row["version"] != expected:
            auth_error(409, "api_key_conflict")
        return row

    def _rotate(self, c, u, a, key_id, body, *, via="auth_session", reason=None):
        old = self._owned(c, key_id, u, a, body.expected_version)
        now = self._now(c)
        if old["revoked_at"] is not None or now >= old["expires_at"]:
            auth_error(409, "api_key_inactive")
        scopes = body.scopes if body.scopes is not None else old["scopes"]
        if not set(scopes) <= set(old["scopes"]):
            auth_error(403, "api_scope_denied")
        replacement = uuid4()
        # Deferrable replacement FK permits retirement before insertion;
        # the partial unique family index never has two live credentials.
        c.execute(
            "UPDATE auth_api_keys SET revoked_at=%s,replaced_by=%s,version=version+1 WHERE key_id=%s",
            (now, replacement, old["key_id"]),
        )
        value = new_secret()
        row = c.execute(
            """INSERT INTO auth_api_keys(key_id,family_id,token_hash,subject_id,account_id,subject_version,
            label,scopes,created_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                replacement,
                old["family_id"],
                secret_digest(value),
                u["subject_id"],
                a["account_id"],
                u["subject_version"],
                old["label"],
                sorted(scopes),
                now,
                old["expires_at"],
            ),
        ).fetchone()
        self._audit(c, "rotated", u, a, row, via=via, reason=reason)
        return IssuedKey(value, public_key(row))

    @boundary
    def rotate(self, session_token, key_id, body, *, origin):
        body = RotateKeyBody.model_validate(body.model_dump())
        with self._tx() as c:
            u, a = self._session(c, session_token, origin, fresh=True, require_api=True)
            return self._rotate(c, u, a, key_id, body)

    def _revoke(self, c, u, a, key_id, expected, *, via="auth_session", reason=None):
        row = self._owned(c, key_id, u, a, expected)
        if row["revoked_at"] is not None:
            return public_key(row)
        row = c.execute(
            "UPDATE auth_api_keys SET revoked_at=%s,version=version+1 WHERE key_id=%s RETURNING *",
            (self._now(c), row["key_id"]),
        ).fetchone()
        self._audit(c, "revoked", u, a, row, via=via, reason=reason)
        return public_key(row)

    @boundary
    def revoke(self, session_token, key_id, body, *, origin):
        body = VersionBody.model_validate(body.model_dump())
        with self._tx() as c:
            u, a = self._session(c, session_token, origin)
            return self._revoke(c, u, a, key_id, body.expected_version)

    @boundary
    def verify(self, value):
        digest = secret_digest(value)
        with self._tx() as c:
            hint = c.execute(
                "SELECT * FROM auth_api_keys WHERE token_hash=%s", (digest,)
            ).fetchone()
            if (
                hint is None
                or hint["revoked_at"] is not None
                or self._now(c) >= hint["expires_at"]
            ):
                auth_error(401, "invalid_credential")
            u, a = self._authority(
                c,
                hint["subject_id"],
                hint["account_id"],
                require_api=True,
                lock="SHARE",
            )
            row = c.execute(
                "SELECT * FROM auth_api_keys WHERE key_id=%s FOR SHARE",
                (hint["key_id"],),
            ).fetchone()
            if (
                row["revoked_at"] is not None
                or self._now(c) >= row["expires_at"]
                or row["subject_version"] != u["subject_version"]
                or not set(row["scopes"]) <= API_SCOPES
            ):
                auth_error(401, "invalid_credential")
            return VerifiedCredential(
                subject_id=str(u["subject_id"]),
                account_id=str(a["account_id"]),
                credential_id=str(row["key_id"]),
                auth_method="api_key",
                scopes=frozenset(row["scopes"]),
            )

    @boundary
    def operator_issue(self, subject, account, body, *, reason):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise ValueError("bounded operator reason required")
        with self._tx() as c:
            u, a = self._authority(
                c, UUID(str(subject)), UUID(str(account)), require_api=True
            )
            if u["kind"] != "service":
                auth_error(403, "api_key_management_denied")
            return self._issue(c, u, a, body, via="operator_cli", reason=reason)

    @boundary
    def operator_rotate(self, subject, account, key_id, body, *, reason):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise ValueError("bounded operator reason required")
        body = RotateKeyBody.model_validate(body.model_dump())
        with self._tx() as c:
            u, a = self._authority(
                c, UUID(str(subject)), UUID(str(account)), require_api=True
            )
            if u["kind"] != "service":
                auth_error(403, "api_key_management_denied")
            return self._rotate(
                c, u, a, key_id, body, via="operator_cli", reason=reason
            )

    @boundary
    def operator_revoke(self, subject, account, key_id, expected_version, *, reason):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise ValueError("bounded operator reason required")
        with self._tx() as c:
            u, a = self._authority(
                c,
                UUID(str(subject)),
                UUID(str(account)),
                require_api=False,
                active=False,
            )
            return self._revoke(
                c, u, a, key_id, expected_version, via="operator_cli", reason=reason
            )

    @boundary
    def readiness(self):
        with self._tx() as c:
            c.execute("SELECT key_id FROM auth_api_keys LIMIT 0")
        return {
            "ok": True,
            "backend": "postgres",
            "schema_version": VERSION,
            "request_mode": key_mode(),
        }


def service_for_request(request):
    state = getattr(getattr(request, "scope", {}).get("app"), "state", None)
    provided = getattr(state, "auth_api_key_service", None)
    return (
        provided
        if provided is not None
        else APIKeyService(store=getattr(state, "auth_access_store", None))
    )
