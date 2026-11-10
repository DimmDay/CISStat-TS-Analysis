"""Durable opaque AuthSessions. Authority failures never select a memory store."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import json
import re
import secrets
from uuid import UUID, uuid4

from .context import VerifiedCredential, auth_error, AuthHTTPException
from .storage import PostgresAccessStore

ABSOLUTE = timedelta(hours=8)
IDLE = timedelta(minutes=15)
TOKEN = re.compile(r"s1_[A-Za-z0-9_-]{43}\Z")
LOGIN_STATE = re.compile(r"[ok][12]_[A-Za-z0-9_-]{43}\Z")


def token_digest(token):
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        auth_error(401, "invalid_credential")
    return hashlib.sha256(("cisstat.authsession/1\0" + token).encode()).hexdigest()


def state_digest(token):
    """AUTH-19 one-time entry state/selection token digest (hash-only storage)."""
    if not isinstance(token, str) or not LOGIN_STATE.fullmatch(token):
        auth_error(401, "invalid_credential")
    return hashlib.sha256(("cisstat.login_state/1\0" + token).encode()).hexdigest()


def boundary(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AuthHTTPException:
            raise
        except Exception:
            auth_error(503, "auth_authority_unavailable")

    return call


def public_session(row):
    return {
        k: (
            str(row[k])
            if isinstance(row[k], UUID)
            else row[k].isoformat()
            if isinstance(row[k], datetime)
            else row[k]
        )
        for k in (
            "session_id",
            "family_id",
            "account_id",
            "issued_at",
            "last_seen_at",
            "idle_expires_at",
            "absolute_expires_at",
            "revoked_at",
        )
    }


@dataclass(frozen=True)
class IssuedSession:
    token: str = field(repr=False)
    session: dict


@dataclass(frozen=True)
class AccountChoices:
    # Password-verified projection only, not a credential.
    accounts: tuple


ACCOUNT_LABELS = {"mono": "Личный", "multi": "Командный"}
ACCOUNT_PLANS = {
    "internal": "Внутренний",
    "demo": "Демо",
    "starter": "Стартовый",
    "professional": "Профессиональный",
    "enterprise": "Корпоративный",
}


def available_accounts(tx, subject_id, now):
    """('single', account_id) | ('multiple', AccountChoices) | ('none', None).

    Shared by password login (AUTH-04) and external entry (AUTH-19):
    only active memberships of active, non-expired accounts are offered.
    """
    from apps.api.accounts.entitlements import account_is_active

    active = [
        a
        for a in tx.accounts.for_subject(subject_id)
        if account_is_active(a, now=now)
    ]
    if len(active) > 1:
        return "multiple", AccountChoices(
            tuple(
                {
                    "account_id": str(a.account_id),
                    "label": f"{ACCOUNT_LABELS[a.account_type]} аккаунт {i + 1} — {ACCOUNT_PLANS[a.plan]}",
                }
                for i, a in enumerate(active)
            )
        )
    return "single", (active[0].account_id if active else None)


class SessionService:
    def __init__(self, store=None, clock=None):
        from .credentials import PasswordCodec

        self.store = store
        self.clock = clock
        self.codec = PasswordCodec()

    @contextmanager
    def _tx(self, readonly=False):
        store = self.store if self.store is not None else PostgresAccessStore.from_env()
        from .mfa_migrations import check_schema

        with store.transaction(readonly=readonly) as tx:
            check_schema(tx.connection)
            yield tx

    def _now(self, conn):
        now = (
            self.clock()
            if self.clock
            else conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        )
        if now.tzinfo is None:
            raise ValueError("aware auth clock required")
        return now.astimezone(timezone.utc)

    def _identity(self, c, subject):
        # Same lock order for verify/issue/password/global revoke. Role/status
        # writers AUTH-02 also lock/update this row, fencing reactivation races.
        return c.execute(
            "SELECT * FROM auth_identities WHERE subject_id=%s FOR UPDATE", (subject,)
        ).fetchone()

    def _epoch(self, c, subject):
        c.execute(
            "INSERT INTO auth_subject_security(subject_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (subject,),
        )
        return c.execute(
            "SELECT session_epoch FROM auth_subject_security WHERE subject_id=%s",
            (subject,),
        ).fetchone()["session_epoch"]

    def _audit(
        self,
        c,
        action,
        subject,
        resource,
        operation,
        *,
        actor_via="auth_session",
        resource_kind=None,
    ):
        from apps.api.security_audit import build_audit_record

        record = build_audit_record(
            action,
            "allowed",
            actor_subject=str(subject),
            actor_via=actor_via,
            resource_kind=resource_kind
            or ("auth_session" if action == "auth_session_changed" else "credential"),
            resource_id=str(resource),
            policy_basis="AUTH-05 MFA command"
            if action == "auth_mfa_changed"
            else "AUTH-04 durable command",
            details={"operation": operation},
        )
        c.execute(
            "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
            (record["audit_id"], json.dumps(record)),
        )

    def _invalidate_all(self, c, subject, now):
        c.execute(
            "UPDATE auth_subject_security SET session_epoch=session_epoch+1 WHERE subject_id=%s",
            (subject,),
        )
        c.execute(
            "UPDATE auth_sessions SET revoked_at=%s WHERE subject_id=%s AND revoked_at IS NULL",
            (now, subject),
        )

    def _rate(self, login, peer):
        # Fixed windows; at most 1000 admitted hash attempts/minute, including
        # unknown usernames. Prune bounded rows before adding per-source keys.
        with self._tx() as tx:
            c = tx.connection
            now = self._now(c)
            c.execute(
                "DELETE FROM auth_login_limits WHERE bucket IN (SELECT bucket FROM auth_login_limits WHERE resets_at<=%s LIMIT 100)",
                (now,),
            )
            buckets = [
                ("global", 1000),
                ("login:" + hashlib.sha256(login.encode()).hexdigest(), 10),
                ("peer:" + hashlib.sha256(peer.encode()).hexdigest(), 100),
            ]
            for bucket, limit in buckets:
                row = c.execute(
                    """INSERT INTO auth_login_limits(bucket,attempts,resets_at) VALUES (%s,1,%s)
                    ON CONFLICT(bucket) DO UPDATE SET attempts=CASE WHEN auth_login_limits.resets_at<=%s THEN 1 ELSE auth_login_limits.attempts+1 END,
                    resets_at=CASE WHEN auth_login_limits.resets_at<=%s THEN EXCLUDED.resets_at ELSE auth_login_limits.resets_at END
                    RETURNING attempts""",
                    (bucket, now + timedelta(minutes=1), now, now),
                ).fetchone()
                if row["attempts"] > limit:
                    auth_error(429, "too_many_attempts")

    def _limit(self, key, limit, *, window=600):
        """AUTH-19 durable fixed-window limiter for external entry surfaces."""
        with self._tx() as tx:
            c = tx.connection
            now = self._now(c)
            c.execute(
                "DELETE FROM auth_login_limits WHERE bucket IN (SELECT bucket FROM auth_login_limits WHERE resets_at<=%s LIMIT 100)",
                (now,),
            )
            row = c.execute(
                """INSERT INTO auth_login_limits(bucket,attempts,resets_at) VALUES (%s,1,%s)
                ON CONFLICT(bucket) DO UPDATE SET attempts=CASE WHEN auth_login_limits.resets_at<=%s THEN 1 ELSE auth_login_limits.attempts+1 END,
                resets_at=CASE WHEN auth_login_limits.resets_at<=%s THEN EXCLUDED.resets_at ELSE auth_login_limits.resets_at END
                RETURNING attempts""",
                (key, now + timedelta(seconds=window), now, now),
            ).fetchone()
            if row["attempts"] > limit:
                auth_error(429, "too_many_attempts")

    @boundary
    def set_password(
        self, subject_id, login, password, *, expected_version=None, scopes=()
    ):
        """Trusted provisioning seam, never a public first-user/bootstrap API."""
        from apps.api.identity import ALL_SCOPES

        if not set(scopes) <= ALL_SCOPES:
            raise ValueError("unknown scope")
        from .credentials import normalize_login

        login = normalize_login(login)
        encoded = self.codec.hash(password)
        with self._tx() as tx:
            c = tx.connection
            identity = self._identity(c, subject_id)
            if not identity or identity["kind"] != "person":
                auth_error(401, "invalid_credential")
            self._epoch(c, subject_id)
            now = self._now(c)
            old = c.execute(
                "SELECT * FROM auth_password_credentials WHERE subject_id=%s FOR UPDATE",
                (subject_id,),
            ).fetchone()
            if old:
                if expected_version != old["version"]:
                    auth_error(409, "auth_version_conflict")
                row = c.execute(
                    """UPDATE auth_password_credentials SET password_hash=%s,status='active',scopes=%s::jsonb,updated_at=%s
                    WHERE credential_id=%s RETURNING *""",
                    (encoded, json.dumps(sorted(scopes)), now, old["credential_id"]),
                ).fetchone()
            else:
                row = c.execute(
                    """INSERT INTO auth_password_credentials(credential_id,subject_id,login,password_hash,scopes)
                    VALUES (%s,%s,%s,%s,%s::jsonb) RETURNING *""",
                    (uuid4(), subject_id, login, encoded, json.dumps(sorted(scopes))),
                ).fetchone()
            self._invalidate_all(c, subject_id, now)
            self._audit(
                c,
                "auth_password_changed",
                subject_id,
                row["credential_id"],
                "provisioned",
            )
            return {
                "credential_id": str(row["credential_id"]),
                "version": row["version"],
            }

    @boundary
    def login(
        self,
        login,
        password,
        account_id=None,
        *,
        old_token=None,
        origin,
        peer="unknown",
    ):
        from .credentials import normalize_login

        login = normalize_login(login)
        self._rate(login, peer)
        with self._tx(readonly=True) as tx:
            candidate = tx.connection.execute(
                "SELECT * FROM auth_password_credentials WHERE login=%s", (login,)
            ).fetchone()
        encoded = (
            candidate["password_hash"]
            if candidate and candidate["status"] == "active"
            else None
        )
        if not self.codec.verify(encoded, password):
            from apps.api.security_audit import record_standard

            record_standard(
                "authn_denied",
                "denied",
                actor_via="password",
                policy_basis="AUTH-04 password",
                details={"reason_code": "invalid_credential"},
            )
            auth_error(401, "invalid_credential")
        rehash = self.codec.hash(password) if self.codec.needs_rehash(encoded) else None
        with self._tx() as tx:
            c = tx.connection
            u = self._identity(c, candidate["subject_id"])
            current = c.execute(
                "SELECT * FROM auth_password_credentials WHERE credential_id=%s FOR UPDATE",
                (candidate["credential_id"],),
            ).fetchone()
            if (
                not u
                or u["status"] != "active"
                or u["kind"] != "person"
                or not current
                or current["status"] != "active"
                or current["version"] != candidate["version"]
            ):
                auth_error(401, "invalid_credential")
            if account_id is None:
                selection_now = self._now(c)
                kind, value = available_accounts(tx, u["subject_id"], selection_now)
                if kind == "multiple":
                    return value
                account_id = value
            a = tx.accounts.get(account_id) if account_id else None
            members = tx.accounts.memberships(account_id) if a else ()
            if (
                not a
                or a.status != "active"
                or not any(
                    m.subject_id == u["subject_id"] and m.status == "active"
                    for m in members
                )
            ):
                auth_error(403, "account_access_denied")
            from apps.api.accounts.entitlements import account_is_active
            if not account_is_active(a, now=self._now(c)):
                auth_error(403, "account_expired")
            epoch = self._epoch(c, u["subject_id"])
            now = self._now(c)
            if rehash:
                current = c.execute(
                    "UPDATE auth_password_credentials SET password_hash=%s,updated_at=%s WHERE credential_id=%s RETURNING *",
                    (rehash, now, current["credential_id"]),
                ).fetchone()
                self._invalidate_all(c, u["subject_id"], now)
                epoch = self._epoch(c, u["subject_id"])
                self._audit(
                    c,
                    "auth_password_changed",
                    u["subject_id"],
                    current["credential_id"],
                    "rehash",
                )
            if isinstance(old_token, str) and TOKEN.fullmatch(old_token):
                old = c.execute(
                    "UPDATE auth_sessions SET revoked_at=%s WHERE token_hash=%s AND revoked_at IS NULL RETURNING session_id,subject_id",
                    (now, token_digest(old_token)),
                ).fetchone()
                if old:
                    self._audit(
                        c,
                        "auth_session_changed",
                        old["subject_id"],
                        old["session_id"],
                        "login_replaced",
                    )
            from .mfa import MfaService

            mfa = MfaService(self.store, clock=self.clock)
            challenge = mfa.login_challenge(
                c, u, current, a.account_id, origin, now, epoch
            )
            if challenge is not None:
                return challenge
            return self._issue(c, u, current, a.account_id, origin, now, epoch)

    def _issue(self, c, u, current, account_id, origin, now, epoch, *, auth_time=None, absolute_expires_at=None, family_id=None):
        token = "s1_" + secrets.token_urlsafe(32)
        row = c.execute(
            """INSERT INTO auth_sessions(session_id,family_id,token_hash,subject_id,account_id,credential_id,
            credential_version,subject_version,session_epoch,scopes,origin,auth_time,issued_at,last_seen_at,idle_expires_at,absolute_expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                uuid4(),
                family_id or uuid4(),
                token_digest(token),
                u["subject_id"],
                account_id,
                current["credential_id"],
                current["version"],
                u["subject_version"],
                epoch,
                json.dumps(current["scopes"]),
                origin,
                auth_time or now,
                now,
                now,
                min(now + IDLE, absolute_expires_at or now + ABSOLUTE),
                absolute_expires_at or now + ABSOLUTE,
            ),
        ).fetchone()
        self._audit(
            c, "auth_session_changed", u["subject_id"], row["session_id"], "created"
        )
        return IssuedSession(token, public_session(row))

    def _issue_external(
        self, c, u, account_id, origin, now, epoch, *, method, auth_time=None, operation=None
    ):
        """AUTH-19 session for a verified external identity: no password
        credential row, no scopes. Fencing stays on identity status/version,
        session epoch and account membership."""
        token = "s1_" + secrets.token_urlsafe(32)
        row = c.execute(
            """INSERT INTO auth_sessions(session_id,family_id,token_hash,subject_id,account_id,credential_id,
            credential_version,subject_version,session_epoch,scopes,origin,auth_time,issued_at,last_seen_at,idle_expires_at,absolute_expires_at)
            VALUES (%s,%s,%s,%s,%s,NULL,NULL,%s,%s,'[]'::jsonb,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                uuid4(),
                uuid4(),
                token_digest(token),
                u["subject_id"],
                account_id,
                u["subject_version"],
                epoch,
                origin,
                min(auth_time, now) if auth_time else now,
                now,
                now,
                now + IDLE,
                now + ABSOLUTE,
            ),
        ).fetchone()
        self._audit(
            c,
            "auth_session_changed",
            u["subject_id"],
            row["session_id"],
            operation or (method + "_login"),
        )
        return IssuedSession(token, public_session(row))

    def _load(self, c, digest, *, touch):
        hint = c.execute(
            "SELECT subject_id FROM auth_sessions WHERE token_hash=%s", (digest,)
        ).fetchone()
        if not hint:
            auth_error(401, "invalid_credential")
        u = self._identity(c, hint["subject_id"])
        row = c.execute(
            "SELECT * FROM auth_sessions WHERE token_hash=%s FOR UPDATE", (digest,)
        ).fetchone()
        now = self._now(c)
        if row["credential_id"] is None:
            # AUTH-19 external session: no password credential to fence with.
            # Identity status/version/epoch/membership checks below still apply.
            cred = {"status": "active", "version": None}
        else:
            cred = c.execute(
                "SELECT version,status FROM auth_password_credentials WHERE credential_id=%s",
                (row["credential_id"],),
            ).fetchone()
        if row.get("demo_grant_id"):
            from .demo import grant_for_account
            grant = grant_for_account(c, row["account_id"], now)
            if not grant or grant["grant_id"] != row["demo_grant_id"] or grant["subject_id"] != row["subject_id"]:
                auth_error(401, "invalid_credential")
            if row["origin"] not in grant["policy"]["allowed_origins"]:
                auth_error(403, "campaign_inactive")
            # Rotation explicitly revokes sessions; resume keeps the same grant.
            cred = {"status": "active", "version": grant["credential_version"]}
        epoch = c.execute(
            "SELECT session_epoch FROM auth_subject_security WHERE subject_id=%s",
            (row["subject_id"],),
        ).fetchone()
        if (
            not u
            or u["status"] != "active"
            or row["revoked_at"] is not None
            or now >= row["absolute_expires_at"]
            or now >= row["idle_expires_at"]
            or not cred
            or cred["status"] != "active"
            or cred["version"] != row["credential_version"]
            or u["subject_version"] != row["subject_version"]
            or not epoch
            or epoch["session_epoch"] != row["session_epoch"]
        ):
            auth_error(401, "invalid_credential")
        account = c.execute(
            """SELECT a.* FROM auth_accounts a JOIN auth_memberships m USING(account_id)
            WHERE a.account_id=%s AND m.subject_id=%s AND a.status='active' AND m.status='active' """,
            (row["account_id"], row["subject_id"]),
        ).fetchone()
        if not account:
            auth_error(401, "invalid_credential")
        from apps.api.accounts.entitlements import account_is_active
        if not account_is_active(account, now=now):
            auth_error(403, "account_expired")
        from .mfa import session_mfa

        session_mfa(c, row, required=u["platform_role"] == "admin")
        if touch:
            # Never extend absolute lifetime; row lock prevents post-revoke touch.
            row = c.execute(
                "UPDATE auth_sessions SET last_seen_at=%s,idle_expires_at=%s WHERE session_id=%s RETURNING *",
                (now, min(now + IDLE, row["absolute_expires_at"]), row["session_id"]),
            ).fetchone()
        return row

    @boundary
    def verify(self, token, *, touch=True, origin=None):
        digest = token_digest(token)
        with self._tx() as tx:
            row = self._load(tx.connection, digest, touch=touch)
            if origin is not None and row["origin"] != origin:
                auth_error(401, "invalid_credential")
            from .mfa import session_mfa

            return VerifiedCredential(
                subject_id=str(row["subject_id"]),
                credential_id=str(row["credential_id"] or row["session_id"]),
                account_id=str(row["account_id"]),
                auth_method="auth_session",
                auth_session_id=str(row["session_id"]),
                scopes=frozenset(row["scopes"]),
                auth_time=row["auth_time"],
                mfa_verified_at=session_mfa(tx.connection, row),
            )

    @boundary
    def list_sessions(self, token):
        digest = token_digest(token)
        with self._tx() as tx:
            row = self._load(tx.connection, digest, touch=True)
            rows = tx.connection.execute(
                "SELECT * FROM auth_sessions WHERE subject_id=%s ORDER BY issued_at DESC,session_id LIMIT 100",
                (row["subject_id"],),
            ).fetchall()
            return [public_session(r) for r in rows]

    @boundary
    def logout(self, token):
        if token is None:
            return
        digest = token_digest(token)
        with self._tx() as tx:
            c = tx.connection
            hint = c.execute(
                "SELECT subject_id FROM auth_sessions WHERE token_hash=%s", (digest,)
            ).fetchone()
            if not hint:
                return
            self._identity(c, hint["subject_id"])
            row = c.execute(
                "UPDATE auth_sessions SET revoked_at=%s WHERE token_hash=%s AND revoked_at IS NULL RETURNING *",
                (self._now(c), digest),
            ).fetchone()
            if row:
                self._audit(
                    c,
                    "auth_session_changed",
                    row["subject_id"],
                    row["session_id"],
                    "logout",
                )

    @boundary
    def revoke(self, token, session_id=None, *, all_sessions=False, family_id=None):
        digest = token_digest(token)
        with self._tx() as tx:
            c = tx.connection
            row = self._load(c, digest, touch=False)
            now = self._now(c)
            if all_sessions:
                self._invalidate_all(c, row["subject_id"], now)
                resource = row["subject_id"]
                operation = "self_revoke_all"
            elif family_id:
                count = c.execute(
                    "UPDATE auth_sessions SET revoked_at=%s WHERE subject_id=%s AND family_id=%s AND revoked_at IS NULL RETURNING session_id",
                    (now, row["subject_id"], UUID(str(family_id))),
                ).fetchall()
                if not count:
                    auth_error(404, "session_not_found")
                resource = family_id
                operation = "family_revoked"
            else:
                target = c.execute(
                    "SELECT * FROM auth_sessions WHERE session_id=%s AND subject_id=%s FOR UPDATE",
                    (UUID(str(session_id)), row["subject_id"]),
                ).fetchone()
                if not target:
                    auth_error(404, "session_not_found")
                c.execute(
                    "UPDATE auth_sessions SET revoked_at=%s WHERE session_id=%s AND revoked_at IS NULL",
                    (now, target["session_id"]),
                )
                resource = target["session_id"]
                operation = "self_revoke"
            self._audit(
                c, "auth_session_changed", row["subject_id"], resource, operation
            )

    @boundary
    def change_password(
        self, token, current_password, new_password, *, proof=None, origin=None
    ):
        evidence = self.verify(token, touch=False)
        with self._tx(readonly=True) as tx:
            old = tx.connection.execute(
                "SELECT * FROM auth_password_credentials WHERE credential_id=%s",
                (evidence.credential_id,),
            ).fetchone()
        if old is None:
            auth_error(403, "capability_not_included")
        if not self.codec.verify(old["password_hash"], current_password):
            auth_error(401, "invalid_credential")
        encoded = self.codec.hash(new_password)
        with self._tx() as tx:
            c = tx.connection
            row = self._load(c, token_digest(token), touch=False)
            cred = c.execute(
                "SELECT * FROM auth_password_credentials WHERE credential_id=%s FOR UPDATE",
                (row["credential_id"],),
            ).fetchone()
            if cred["version"] != old["version"]:
                auth_error(409, "auth_version_conflict")
            from .mfa import MfaService, session_mfa

            if session_mfa(c, row) is not None:
                MfaService(self.store, clock=self.clock).consume_step_up(
                    c, token, proof, "password.change", origin or row["origin"]
                )
            now = self._now(c)
            c.execute(
                "UPDATE auth_password_credentials SET password_hash=%s,updated_at=%s WHERE credential_id=%s",
                (encoded, now, row["credential_id"]),
            )
            self._invalidate_all(c, row["subject_id"], now)
            self._audit(
                c,
                "auth_password_changed",
                row["subject_id"],
                row["credential_id"],
                "self_change",
            )

    @boundary
    def revoke_password(self, subject_id, *, expected_version):
        with self._tx() as tx:
            c = tx.connection
            self._identity(c, subject_id)
            self._epoch(c, subject_id)
            cred = c.execute(
                "SELECT * FROM auth_password_credentials WHERE subject_id=%s FOR UPDATE",
                (subject_id,),
            ).fetchone()
            if not cred or cred["version"] != expected_version:
                auth_error(409, "auth_version_conflict")
            c.execute(
                "UPDATE auth_password_credentials SET status='revoked' WHERE subject_id=%s",
                (subject_id,),
            )
            self._invalidate_all(c, subject_id, self._now(c))
            self._audit(
                c, "auth_password_changed", subject_id, cred["credential_id"], "revoked"
            )

    @boundary
    def select_login(self, selection, account_id, origin, *, old_token=None):
        """AUTH-19 one-time account selection after external verification.

        The selection token is subject-bound, origin-bound and single-use;
        the account binding is re-checked here, never trusted from the token.
        """
        digest = state_digest(selection)
        with self._tx() as tx:
            c = tx.connection
            now = self._now(c)
            hint = c.execute(
                "SELECT subject_id FROM auth_login_states WHERE state_hash=%s",
                (digest,),
            ).fetchone()
            if not hint:
                auth_error(401, "invalid_credential")
            u = self._identity(c, hint["subject_id"])
            row = c.execute(
                """UPDATE auth_login_states SET consumed_at=%s
                WHERE state_hash=%s AND purpose IN ('oidc_select','email_select')
                AND consumed_at IS NULL AND expires_at>%s AND issued_at<=%s AND origin=%s
                RETURNING purpose""",
                (now, digest, now, now, origin),
            ).fetchone()
            if not row or not u or u["status"] != "active" or u["kind"] != "person":
                auth_error(401, "invalid_credential")
            a = tx.accounts.get(account_id) if account_id else None
            members = tx.accounts.memberships(account_id) if a else ()
            if (
                not a
                or a.status != "active"
                or not any(
                    m.subject_id == u["subject_id"] and m.status == "active"
                    for m in members
                )
            ):
                auth_error(403, "account_access_denied")
            from apps.api.accounts.entitlements import account_is_active

            if not account_is_active(a, now=now):
                auth_error(403, "account_expired")
            epoch = self._epoch(c, u["subject_id"])
            self._retire_old(c, old_token, now)
            method = "oidc" if row["purpose"] == "oidc_select" else "email"
            return self._issue_external(
                c,
                u,
                a.account_id,
                origin,
                now,
                epoch,
                method=method,
                operation=method + "_select",
            )

    def _retire_old(self, c, old_token, now):
        """Revoke the caller's previous browser session on a new login."""
        if isinstance(old_token, str) and TOKEN.fullmatch(old_token):
            old = c.execute(
                "UPDATE auth_sessions SET revoked_at=%s WHERE token_hash=%s AND revoked_at IS NULL RETURNING session_id,subject_id",
                (now, token_digest(old_token)),
            ).fetchone()
            if old:
                self._audit(
                    c,
                    "auth_session_changed",
                    old["subject_id"],
                    old["session_id"],
                    "login_replaced",
                )

    def _insert_select_state(self, c, purpose, origin, now, subject_id):
        """AUTH-19 one-time subject-bound selection token (TTL 5 minutes)."""
        token = "k1_" + secrets.token_urlsafe(32)
        c.execute(
            """INSERT INTO auth_login_states(state_id,purpose,state_hash,nonce,pkce_verifier,subject_id,origin,issued_at,expires_at)
            VALUES (%s,%s,%s,NULL,NULL,%s,%s,%s,%s)""",
            (
                uuid4(),
                purpose,
                state_digest(token),
                subject_id,
                origin,
                now,
                now + timedelta(minutes=5),
            ),
        )
        return token

    @boundary
    def readiness(self):
        from .mfa_migrations import check_schema

        with self._tx(readonly=True) as tx:
            check_schema(tx.connection)
            pending = tx.connection.execute(
                "SELECT count(*) AS n FROM auth_audit_outbox WHERE delivered_at IS NULL"
            ).fetchone()["n"]
        return {
            "ok": True,
            "backend": "postgres",
            "schema_version": "0021_auth05_mfa",
            "audit_pending": pending,
        }


def service_for_request(request):
    state = getattr(getattr(request, "scope", {}).get("app"), "state", None)
    provided = getattr(state, "auth_session_service", None)
    if provided is not None:
        return provided
    return SessionService(store=getattr(state, "auth_access_store", None))


class SessionCredentialVerifier:
    def __init__(self, request):
        self.request = request

    def api_key(self, key):
        from .api_keys import key_mode, secret_digest, service_for_request
        from .api_key_policy import admit_request
        from .legacy import LegacyCredentialVerifier

        if key_mode() == "durable" or key.startswith("csk_"):
            secret_digest(key)  # Reject malformed credentials before opening authority.
            evidence = service_for_request(self.request).verify(key)
            if not getattr(self.request.state, "_auth10_principal_lookup", False):
                admit_request(self.request, evidence)
            return evidence
        return LegacyCredentialVerifier().api_key(key)

    def session(self, request):
        from .csrf import auth_cookie, check_csrf

        token = auth_cookie(request)
        if token is None:
            return None
        token_digest(token)
        if request.headers.get("sec-fetch-site") not in (
            None,
            "same-origin",
            "same-site",
            "none",
        ):
            auth_error(403, "csrf_invalid")
        # Unsafe cookie-auth operations get a local CSRF foundation now, not
        # an unprotected window until the common proxy/UI task AUTH-06.
        method = getattr(request, "method", "GET")
        if method not in ("GET", "HEAD", "OPTIONS"):
            check_csrf(request)
        path = getattr(getattr(request, "url", None), "path", "")
        if method == "GET" and path.endswith("/restore"):
            auth_error(403, "csrf_invalid")
        origin = request.headers.get("origin")
        if origin:
            from .csrf import trusted_origin

            trusted_origin(request)
        return service_for_request(request).verify(token, origin=origin)
