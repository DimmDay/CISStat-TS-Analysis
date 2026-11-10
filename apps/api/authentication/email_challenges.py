"""AUTH-19 personal email entry secrets: keyed digests, bounded OTP, uniform answers.

The magic-link token and the OTP are keyed HMAC-SHA256 values
(CISSTAT_AUTH_EMAIL_KEY, >=32 bytes). A missing/short key closes the whole
email contour (503) instead of silently falling back to an unkeyed hash.
Identity resolution and sessions live in EmailChallengeService; this module
holds only the pure contract surface testable without PostgreSQL.
"""

import hashlib
import hmac
import os
import re
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from .context import auth_error
from .providers.email_delivery import DeliveryUnavailable
from .sessions import (
    SessionService,
    available_accounts,
    boundary,
)

EMAIL_ISSUER = "cisstat.email/1"
TTL = timedelta(minutes=15)
MAX_ATTEMPTS = 5
CODE_LENGTH = 8

EMAIL_TOKEN = re.compile(r"e1_[A-Za-z0-9_-]{43}\Z")
CODE = re.compile(r"[0-9]{8}\Z")
_LOCAL = re.compile(r"[a-z0-9][a-z0-9._+\-]{0,63}\Z")
_DOMAIN = re.compile(r"[a-z0-9][a-z0-9.\-]{1,251}\Z")


def email_key_configured():
    return len(os.environ.get("CISSTAT_AUTH_EMAIL_KEY", "")) >= 32


def _key():
    value = os.environ.get("CISSTAT_AUTH_EMAIL_KEY", "").encode()
    if len(value) < 32:
        auth_error(503, "email_unavailable")
    return value


def normalize_email(value):
    if not isinstance(value, str):
        auth_error(422, "invalid_request")
    email = value.strip().lower()
    if len(email) < 6 or len(email) > 320 or email.count("@") != 1:
        auth_error(422, "invalid_request")
    local, _, domain = email.partition("@")
    if not _LOCAL.fullmatch(local) or not _DOMAIN.fullmatch(domain) or "." not in domain:
        auth_error(422, "invalid_request")
    return email


def email_token_digest(token):
    if not isinstance(token, str) or not EMAIL_TOKEN.fullmatch(token):
        auth_error(401, "invalid_credential")
    return hmac.new(
        _key(), ("cisstat.email_token/1\0" + token).encode(), hashlib.sha256
    ).hexdigest()


def email_code_digest(email, code):
    if not isinstance(code, str) or not CODE.fullmatch(code):
        auth_error(401, "invalid_credential")
    return hmac.new(
        _key(), ("cisstat.email_code/1\0" + email + "\0" + code).encode(), hashlib.sha256
    ).hexdigest()


def generate_code():
    return str(secrets.randbelow(10**CODE_LENGTH)).zfill(CODE_LENGTH)


def generate_token():
    return "e1_" + secrets.token_urlsafe(32)


def email_configured():
    return email_key_configured() and bool(os.environ.get("CISSTAT_AUTH_SMTP_HOST"))


def trial_plan_expiry(now):
    """Optional operator policy for new personal trial accounts."""
    raw = os.environ.get("CISSTAT_AUTH_TRIAL_PLAN_DAYS", "")
    if not raw:
        return None
    days = int(raw)
    if not 1 <= days <= 3650:
        raise ValueError("invalid trial plan days")
    return now + timedelta(days=days)


class EmailChallengeService(SessionService):
    """Personal trial login and authenticated email binding.

    The start answer never discloses whether the address already belongs to a
    personal identity. Consume is a POST command; a mail scanner fetching the
    link performs a GET and consumes nothing. Delivery failure keeps the
    challenge unusable, so an email outage cannot open entry.
    """

    def _delivery(self):
        from .providers.email_delivery import SmtpEmailDelivery

        if not email_configured():
            auth_error(503, "email_unavailable")
        delivery = SmtpEmailDelivery.from_env()
        if delivery is None:
            auth_error(503, "email_unavailable")
        return delivery

    def _subject_line(self, purpose):
        return (
            "Подтверждение входа в CISStat TS Analysis"
            if purpose == "trial_login"
            else "Подтверждение email в CISStat TS Analysis"
        )

    def _letter(self, purpose, origin, code, token):
        link = origin + "/login?email_challenge=" + token
        if purpose == "trial_login":
            return (
                "Код подтверждения входа: " + code + "\n\n"
                "Или перейдите по ссылке и нажмите «Подтвердить вход»:\n" + link
                + "\n\nКод и ссылка действительны 15 минут и работают один раз."
            )
        return (
            "Код подтверждения email: " + code + "\n\n"
            "Или перейдите по ссылке и подтвердите привязку:\n" + link
            + "\n\nКод и ссылка действительны 15 минут и работают один раз."
        )

    def _audit_identity(self, c, subject, operation, target_hash):
        from apps.api.security_audit import build_audit_record
        import json as _json

        record = build_audit_record(
            "auth_identity_changed",
            "allowed",
            actor_subject=str(subject),
            actor_via="auth_session" if subject else "email_challenge",
            resource_kind="identity",
            resource_id=str(subject),
            policy_basis="AUTH-19 verified email binding",
            details={"operation": operation, "email_hash": target_hash[:16]},
        )
        c.execute(
            "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
            (record["audit_id"], _json.dumps(record)),
        )

    @boundary
    def start(self, email, purpose, origin, peer, *, session_token=None):
        self._delivery()
        email = normalize_email(email)
        subject = None
        if purpose == "email_bind":
            if not session_token:
                auth_error(401, "authentication_required")
            evidence = self.verify(session_token, origin=origin)
            subject = UUID(evidence.subject_id)
        elif purpose != "trial_login":
            auth_error(422, "invalid_request")
        email_hash = hashlib.sha256(email.encode()).hexdigest()
        self._limit("email:" + email_hash, 3)
        self._limit("email-peer:" + hashlib.sha256(peer.encode()).hexdigest(), 20)
        self._limit("email-global", 500)
        token, code = generate_token(), generate_code()
        with self._tx() as tx:
            c = tx.connection
            from .auth19_migrations import check_schema

            check_schema(c)
            now = self._now(c)
            if purpose == "email_bind":
                existing = tx.identities.by_external(EMAIL_ISSUER, email)
                if existing and existing.subject_id != subject:
                    auth_error(409, "email_already_bound")
            c.execute(
                """INSERT INTO auth_email_challenges(challenge_id,purpose,email,token_hash,code_hash,
                subject_id,origin,issued_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    uuid4(),
                    purpose,
                    email,
                    email_token_digest(token),
                    email_code_digest(email, code),
                    subject,
                    origin,
                    now,
                    now + TTL,
                ),
            )
        try:
            self._delivery().send(
                email, self._subject_line(purpose), self._letter(purpose, origin, code, token)
            )
        except DeliveryUnavailable:
            with self._tx() as tx:
                tx.connection.execute(
                    "UPDATE auth_email_challenges SET delivered_at=%s,delivery_code='failed' WHERE token_hash=%s",
                    (self._now(tx.connection), email_token_digest(token)),
                )
            auth_error(503, "email_delivery_unavailable")
        with self._tx() as tx:
            tx.connection.execute(
                "UPDATE auth_email_challenges SET delivered_at=%s,delivery_code='sent' WHERE token_hash=%s",
                (self._now(tx.connection), email_token_digest(token)),
            )
        return {"status": "email_sent"}

    def _challenge_row(self, c, digest, origin):
        row = c.execute(
            "SELECT * FROM auth_email_challenges WHERE token_hash=%s", (digest,)
        ).fetchone()
        if not row:
            auth_error(401, "invalid_credential")
        return row

    def _check(self, c, row, now, purposes, origin, *, skip_attempts=False):
        if (
            row["purpose"] not in purposes
            or row["consumed_at"] is not None
            or now >= row["expires_at"]
            or now < row["issued_at"]
            or (not skip_attempts and row["attempts"] >= MAX_ATTEMPTS)
            or row["origin"] != origin
            or row["delivery_code"] != "sent"
        ):
            auth_error(401, "invalid_credential")

    def _consume_row(self, c, row, now):
        updated = c.execute(
            "UPDATE auth_email_challenges SET consumed_at=%s WHERE challenge_id=%s AND consumed_at IS NULL RETURNING challenge_id",
            (now, row["challenge_id"]),
        ).fetchone()
        if not updated:
            auth_error(401, "invalid_credential")

    @boundary
    def consume(
        self,
        token=None,
        code=None,
        email=None,
        *,
        origin,
        old_token=None,
        session_token=None,
    ):
        from .auth19_migrations import check_schema

        if token:
            digest = email_token_digest(token)
            with self._tx() as tx:
                c = tx.connection
                check_schema(c)
                row = self._challenge_row(c, digest, origin)
            purpose = row["purpose"]
        elif code and email:
            email = normalize_email(email)
            self._limit("email-code:" + hashlib.sha256(email.encode()).hexdigest(), 20)
            with self._tx() as tx:
                c = tx.connection
                check_schema(c)
                # The newest unconsumed delivered challenge for the mailbox.
                # A wrong OTP cannot be matched by hash, so the challenge is
                # located by email and the attempt budget is spent on it.
                row = c.execute(
                    """SELECT * FROM auth_email_challenges
                    WHERE email=%s AND consumed_at IS NULL AND delivery_code='sent'
                    ORDER BY issued_at DESC,challenge_id DESC LIMIT 1 FOR UPDATE""",
                    (email,),
                ).fetchone()
                if not row:
                    auth_error(401, "invalid_credential")
            purpose = row["purpose"]
        else:
            auth_error(422, "invalid_request")
        if code:
            # The attempt is committed BEFORE the OTP is judged so that a
            # wrong code cannot roll back its budget (AUTH-05 pattern).
            with self._tx() as tx:
                c = tx.connection
                row = c.execute(
                    "SELECT * FROM auth_email_challenges WHERE challenge_id=%s FOR UPDATE",
                    (row["challenge_id"],),
                ).fetchone()
                now = self._now(c)
                self._check(c, row, now, (purpose,), origin)
                c.execute(
                    "UPDATE auth_email_challenges SET attempts=attempts+1 WHERE challenge_id=%s",
                    (row["challenge_id"],),
                )
        with self._tx() as tx:
            c = tx.connection
            row = c.execute(
                "SELECT * FROM auth_email_challenges WHERE challenge_id=%s FOR UPDATE",
                (row["challenge_id"],),
            ).fetchone()
            now = self._now(c)
            # The attempt budget was already validated before this attempt was
            # counted; the 5th attempt may still succeed.
            self._check(c, row, now, (purpose,), origin, skip_attempts=code is not None)
            if code and row["code_hash"] != email_code_digest(email, code):
                auth_error(401, "invalid_credential")
            if purpose == "email_bind":
                if not session_token:
                    auth_error(401, "authentication_required")
                evidence = self.verify(session_token, touch=False, origin=origin)
                if evidence.subject_id != str(row["subject_id"]):
                    auth_error(401, "invalid_credential")
                existing = tx.identities.by_external(EMAIL_ISSUER, row["email"])
                if existing and existing.subject_id != row["subject_id"]:
                    auth_error(409, "email_already_bound")
                self._consume_row(c, row, now)
                if not existing:
                    tx.identities.link_external(
                        row["subject_id"],
                        EMAIL_ISSUER,
                        row["email"],
                        email=row["email"],
                        email_verified=True,
                    )
                    self._audit_identity(c, row["subject_id"], "email_bound", hashlib.sha256(row["email"].encode()).hexdigest())
                return {"status": "email_bound"}
            self._consume_row(c, row, now)
            return self._trial(c, tx, row, origin, now, old_token)

    def _trial(self, c, tx, row, origin, now, old_token):
        u = tx.identities.by_external(EMAIL_ISSUER, row["email"])
        created = False
        if not u:
            u = tx.identities.create()
            tx.identities.link_external(
                u.subject_id, EMAIL_ISSUER, row["email"], email=row["email"], email_verified=True
            )
            tx.accounts.create(
                u.subject_id,
                plan="starter",
                plan_expires_at=trial_plan_expiry(now),
            )
            created = True
        subject_id = u.subject_id
        identity = self._identity(c, subject_id)
        if not identity or identity["status"] != "active" or identity["kind"] != "person":
            auth_error(401, "invalid_credential")
        if created:
            self._audit_identity(
                c, subject_id, "trial_identity_created", hashlib.sha256(row["email"].encode()).hexdigest()
            )
        kind, value = available_accounts(tx, subject_id, now)
        if kind == "none" or (kind == "single" and value is None):
            auth_error(403, "account_access_denied")
        if kind == "multiple":
            token = self._insert_select_state(
                c, "email_select", origin, now, subject_id
            )
            return {
                "status": "account_required",
                "accounts": value.accounts,
                "selection_token": token,
            }
        epoch = self._epoch(c, subject_id)
        self._retire_old(c, old_token, now)
        return self._issue_external(c, identity, value, origin, now, epoch, method="email")


def service_for_request(request):
    state = getattr(getattr(request, "scope", {}).get("app"), "state", None)
    provided = getattr(state, "auth_email_service", None)
    if provided is not None:
        return provided
    return EmailChallengeService(store=getattr(state, "auth_access_store", None))
