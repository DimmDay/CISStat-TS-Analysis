"""Durable MFA state machine. Challenges/proofs never implement AuthSession."""

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import quote, urlencode
from uuid import UUID, uuid4

from .context import auth_error
from .mfa_crypto import seal, unseal, verify_totp
from .sessions import IssuedSession, SessionService, boundary, token_digest

TTL = timedelta(minutes=5)
CHALLENGE = re.compile(r"c1_[A-Za-z0-9_-]{43}\Z")
ACTIONS = frozenset({"mfa.replace", "recovery.rotate", "password.change"})


def challenge_digest(token):
    if not isinstance(token, str) or not CHALLENGE.fullmatch(token):
        auth_error(401, "invalid_credential")
    return hashlib.sha256(("cisstat.challenge/1\0" + token).encode()).hexdigest()


def _hash(value, domain):
    return hashlib.sha256((domain + "\0" + value).encode()).hexdigest()


def session_mfa(c, row, *, required=False):
    proof = c.execute(
        """SELECT p.verified_at, f.revoked_at, f.subject_id FROM auth_session_mfa p
        JOIN auth_mfa_factors f USING(factor_id) WHERE p.session_id=%s""",
        (row["session_id"],),
    ).fetchone()
    if proof and (
        proof["revoked_at"] is not None or proof["subject_id"] != row["subject_id"]
    ):
        auth_error(401, "invalid_credential")
    if required and not proof:
        auth_error(401, "invalid_credential")
    return proof["verified_at"] if proof else None


@dataclass(frozen=True)
class IssuedChallenge:
    token: str = field(repr=False)
    purpose: str
    expires_at: object


@dataclass(frozen=True)
class Enrollment:
    challenge: IssuedChallenge
    secret: str = field(repr=False)
    uri: str = field(repr=False)


@dataclass(frozen=True)
class Completion:
    session: IssuedSession | None = None
    proof: IssuedChallenge | None = None
    recovery_codes: tuple = field(default=(), repr=False)


class MfaService(SessionService):
    def _factor(self, c, subject):
        return c.execute(
            "SELECT * FROM auth_mfa_factors WHERE subject_id=%s AND revoked_at IS NULL FOR UPDATE",
            (subject,),
        ).fetchone()

    def _mint(
        self,
        c,
        u,
        cred,
        account_id,
        origin,
        now,
        epoch,
        purpose,
        *,
        factor_id=None,
        session_id=None,
        target="",
        auth_time=None,
        expires_at=None,
        key_id=None,
        secret_cipher=None,
    ):
        token = "c1_" + secrets.token_urlsafe(32)
        expiry = min(now + TTL, expires_at) if expires_at else now + TTL
        c.execute(
            """INSERT INTO auth_challenges(challenge_id,token_hash,subject_id,account_id,credential_id,
            credential_version,subject_version,session_epoch,purpose,target,session_id,factor_id,origin,
            auth_time,issued_at,expires_at,key_id,secret_cipher) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                uuid4(),
                challenge_digest(token),
                u["subject_id"],
                account_id,
                cred["credential_id"],
                cred["version"],
                u["subject_version"],
                epoch,
                purpose,
                target,
                session_id,
                factor_id or uuid4(),
                origin,
                auth_time or now,
                now,
                expiry,
                key_id,
                secret_cipher,
            ),
        )
        return IssuedChallenge(token, purpose, expiry)

    def login_challenge(self, c, u, cred, account_id, origin, now, epoch):
        factor = self._factor(c, u["subject_id"])
        if factor:
            return self._mint(
                c,
                u,
                cred,
                account_id,
                origin,
                now,
                epoch,
                "login",
                factor_id=factor["factor_id"],
            )
        previous = c.execute(
            "SELECT * FROM auth_mfa_factors WHERE subject_id=%s ORDER BY created_at DESC,factor_id LIMIT 1",
            (u["subject_id"],),
        ).fetchone()
        if previous:
            # Recovery never reopens password-only login or enrollment.
            return self._mint(
                c,
                u,
                cred,
                account_id,
                origin,
                now,
                epoch,
                "recovery",
                factor_id=previous["factor_id"],
            )
        if u["platform_role"] == "admin":
            allowed = c.execute(
                "SELECT enrollment_allowed FROM auth_subject_security WHERE subject_id=%s",
                (u["subject_id"],),
            ).fetchone()
            if not allowed or not allowed["enrollment_allowed"]:
                auth_error(403, "mfa_required")
            return self._mint(
                c, u, cred, account_id, origin, now, epoch, "enroll_start"
            )
        return None

    def _challenge(
        self, c, token, origin, purposes, *, session_token=None, target=None
    ):
        digest = challenge_digest(token)
        hint = c.execute(
            "SELECT subject_id FROM auth_challenges WHERE token_hash=%s", (digest,)
        ).fetchone()
        if not hint:
            auth_error(401, "invalid_credential")
        u = self._identity(c, hint["subject_id"])
        row = c.execute(
            "SELECT * FROM auth_challenges WHERE token_hash=%s FOR UPDATE", (digest,)
        ).fetchone()
        cred = c.execute(
            "SELECT * FROM auth_password_credentials WHERE credential_id=%s",
            (row["credential_id"],),
        ).fetchone()
        epoch = self._epoch(c, row["subject_id"])
        now = self._now(c)
        if (
            not u
            or u["status"] != "active"
            or u["kind"] != "person"
            or row["subject_version"] != u["subject_version"]
            or not cred
            or cred["status"] != "active"
            or cred["version"] != row["credential_version"]
            or epoch != row["session_epoch"]
            or row["purpose"] not in purposes
            or row["consumed_at"] is not None
            or now >= row["expires_at"]
            or now < row["issued_at"]
            or row["origin"] != origin
            or (target is not None and row["target"] != target)
        ):
            auth_error(401, "invalid_credential")
        member = c.execute(
            """SELECT a.status,a.plan_expires_at FROM auth_memberships m JOIN auth_accounts a USING(account_id)
            WHERE m.subject_id=%s AND m.account_id=%s AND m.status='active' AND a.status='active' """,
            (row["subject_id"], row["account_id"]),
        ).fetchone()
        if not member:
            auth_error(401, "invalid_credential")
        from apps.api.accounts.entitlements import account_is_active
        if not account_is_active(member, now=now):
            auth_error(403, "account_expired")
        if row["session_id"] is not None:
            if session_token is None:
                auth_error(401, "invalid_credential")
            session = self._load(c, token_digest(session_token), touch=False)
            if (
                session["session_id"] != row["session_id"]
                or session["origin"] != origin
            ):
                auth_error(401, "invalid_credential")
        return row, u, cred, now

    def _consume(self, c, row, now):
        c.execute(
            "UPDATE auth_challenges SET consumed_at=%s WHERE challenge_id=%s",
            (now, row["challenge_id"]),
        )

    def _attempt(self, token, origin, purposes, session_token=None):
        # Commit the attempt BEFORE evaluating a code. Raising for a bad OTP
        # inside the consuming transaction must not roll back its budget.
        with self._tx() as tx:
            row, _, _, _ = self._challenge(
                tx.connection, token, origin, purposes, session_token=session_token
            )
            subject = str(row["subject_id"])
        self._rate("mfa:" + subject, "mfa:" + subject)
        with self._tx() as tx:
            row, _, _, _ = self._challenge(
                tx.connection, token, origin, purposes, session_token=session_token
            )
            if row["attempts"] >= 5:
                auth_error(401, "invalid_credential")
            tx.connection.execute(
                "UPDATE auth_challenges SET attempts=attempts+1 WHERE challenge_id=%s",
                (row["challenge_id"],),
            )

    @boundary
    def begin_enrollment(self, token, *, origin):
        with self._tx() as tx:
            c = tx.connection
            row, u, cred, now = self._challenge(c, token, origin, {"enroll_start"})
            # The durable enroll_start is the authorization, not a reusable
            # password-only enrollment window after recovery/replacement.
            if self._factor(c, u["subject_id"]):
                auth_error(401, "invalid_credential")
            secret = secrets.token_bytes(20)
            binding = str(u["subject_id"]) + ":" + str(row["factor_id"])
            kid, cipher = seal(secret, binding)
            self._consume(c, row, now)
            challenge = self._mint(
                c,
                u,
                cred,
                row["account_id"],
                origin,
                now,
                row["session_epoch"],
                "enroll",
                factor_id=row["factor_id"],
                auth_time=row["auth_time"],
                expires_at=row["expires_at"],
                key_id=kid,
                secret_cipher=cipher,
            )
            encoded = base64.b32encode(secret).decode()
            uri = (
                "otpauth://totp/"
                + quote("CISStat:" + cred["login"], safe="")
                + "?"
                + urlencode(
                    {
                        "secret": encoded,
                        "issuer": "CISStat",
                        "algorithm": "SHA1",
                        "digits": 6,
                        "period": 30,
                    }
                )
            )
            self._audit(
                c,
                "auth_mfa_changed",
                u["subject_id"],
                row["factor_id"],
                "enrollment_started",
                actor_via="mfa_challenge",
            )
            return Enrollment(challenge, encoded, uri)

    def _codes(self, c, subject, factor_id, now):
        c.execute(
            "UPDATE auth_recovery_codes SET consumed_at=%s WHERE subject_id=%s AND consumed_at IS NULL",
            (now, subject),
        )
        codes = tuple("r1_" + secrets.token_urlsafe(24) for _ in range(10))
        for code in codes:
            c.execute(
                "INSERT INTO auth_recovery_codes(code_id,subject_id,factor_id,code_hash,created_at) VALUES (%s,%s,%s,%s,%s)",
                (uuid4(), subject, factor_id, _hash(code, "cisstat.recovery/1"), now),
                prepare=False,
            )
        return codes

    @boundary
    def complete(self, token, code, *, origin, session_token=None):
        self._attempt(token, origin, {"enroll", "login", "step_up"}, session_token)
        with self._tx() as tx:
            c = tx.connection
            row, u, cred, now = self._challenge(
                c,
                token,
                origin,
                {"enroll", "login", "step_up"},
                session_token=session_token,
            )
            enrollment = row["purpose"] == "enroll"
            factor = row if enrollment else self._factor(c, u["subject_id"])
            if not factor or factor["factor_id"] != row["factor_id"]:
                auth_error(401, "invalid_credential")
            seed = unseal(
                factor["key_id"],
                factor["secret_cipher"],
                str(u["subject_id"]) + ":" + str(row["factor_id"]),
            )
            step = verify_totp(
                seed, code, now, -1 if enrollment else factor["last_step"]
            )
            if step is None:
                auth_error(401, "invalid_credential")
            codes = ()
            if enrollment:
                if self._factor(c, u["subject_id"]):
                    auth_error(401, "invalid_credential")
                c.execute(
                    "INSERT INTO auth_mfa_factors(factor_id,subject_id,key_id,secret_cipher,last_step,created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        row["factor_id"],
                        u["subject_id"],
                        row["key_id"],
                        row["secret_cipher"],
                        step,
                        now,
                    ),
                )
                c.execute(
                    "UPDATE auth_subject_security SET enrollment_allowed=false WHERE subject_id=%s",
                    (u["subject_id"],),
                )
                self._invalidate_all(c, u["subject_id"], now)
                codes = self._codes(c, u["subject_id"], row["factor_id"], now)
                self._audit(
                    c,
                    "auth_mfa_changed",
                    u["subject_id"],
                    row["factor_id"],
                    "enrolled",
                    actor_via="mfa_challenge",
                )
            else:
                c.execute(
                    "UPDATE auth_mfa_factors SET last_step=%s WHERE factor_id=%s",
                    (step, factor["factor_id"]),
                )
            self._consume(c, row, now)
            if row["purpose"] == "step_up":
                proof = self._mint(
                    c,
                    u,
                    cred,
                    row["account_id"],
                    origin,
                    now,
                    row["session_epoch"],
                    "proof",
                    factor_id=row["factor_id"],
                    session_id=row["session_id"],
                    target=row["target"],
                    auth_time=row["auth_time"],
                )
                self._audit(
                    c,
                    "auth_mfa_changed",
                    u["subject_id"],
                    row["session_id"],
                    "step_up_verified",
                )
                return Completion(proof=proof)
            issued = self._issue(
                c,
                u,
                cred,
                row["account_id"],
                origin,
                now,
                self._epoch(c, u["subject_id"]),
                auth_time=row["auth_time"],
            )
            c.execute(
                "INSERT INTO auth_session_mfa(session_id,factor_id,verified_at) VALUES (%s,%s,%s)",
                (UUID(issued.session["session_id"]), row["factor_id"], now),
            )
            return Completion(session=issued, recovery_codes=codes)

    @boundary
    def recover(self, token, code, *, origin):
        self._attempt(token, origin, {"login", "recovery"})
        with self._tx() as tx:
            c = tx.connection
            row, u, cred, now = self._challenge(c, token, origin, {"login", "recovery"})
            factor = c.execute(
                "SELECT * FROM auth_mfa_factors WHERE factor_id=%s AND subject_id=%s FOR UPDATE",
                (row["factor_id"], u["subject_id"]),
            ).fetchone()
            recovery = c.execute(
                "SELECT * FROM auth_recovery_codes WHERE code_hash=%s AND subject_id=%s FOR UPDATE",
                (_hash(code, "cisstat.recovery/1"), u["subject_id"]),
            ).fetchone()
            if (
                not factor
                or factor["factor_id"] != row["factor_id"]
                or not recovery
                or recovery["factor_id"] != factor["factor_id"]
                or recovery["consumed_at"] is not None
            ):
                auth_error(401, "invalid_credential")
            self._consume(c, row, now)
            c.execute(
                "UPDATE auth_recovery_codes SET consumed_at=%s WHERE code_id=%s",
                (now, recovery["code_id"]),
            )
            self._reset_factor(c, u["subject_id"], now, invalidate_codes=False)
            self._audit(
                c,
                "auth_mfa_changed",
                u["subject_id"],
                row["factor_id"],
                "recovered_sessions_revoked",
                actor_via="mfa_challenge",
            )
            return self._mint(
                c,
                u,
                cred,
                row["account_id"],
                origin,
                now,
                self._epoch(c, u["subject_id"]),
                "enroll_start",
                auth_time=row["auth_time"],
                expires_at=row["expires_at"],
            )

    def _reset_factor(self, c, subject, now, *, invalidate_codes=True):
        c.execute(
            "UPDATE auth_mfa_factors SET revoked_at=%s WHERE subject_id=%s AND revoked_at IS NULL",
            (now, subject),
        )
        if invalidate_codes:
            c.execute(
                "UPDATE auth_recovery_codes SET consumed_at=%s WHERE subject_id=%s AND consumed_at IS NULL",
                (now, subject),
            )
        c.execute(
            "UPDATE auth_subject_security SET enrollment_allowed=false WHERE subject_id=%s",
            (subject,),
        )
        self._invalidate_all(c, subject, now)

    @boundary
    def start_step_up(self, token, password, action, *, origin):
        if action not in ACTIONS:
            auth_error(403, "mfa_required")
        evidence = self.verify(token, touch=False, origin=origin)
        self._rate("stepup:" + evidence.subject_id, "stepup:" + evidence.subject_id)
        with self._tx(readonly=True) as tx:
            old = tx.connection.execute(
                "SELECT * FROM auth_password_credentials WHERE credential_id=%s",
                (evidence.credential_id,),
            ).fetchone()
        if not self.codec.verify(old["password_hash"], password):
            auth_error(401, "invalid_credential")
        with self._tx() as tx:
            c = tx.connection
            session = self._load(c, token_digest(token), touch=False)
            u = self._identity(c, session["subject_id"])
            cred = c.execute(
                "SELECT * FROM auth_password_credentials WHERE credential_id=%s",
                (evidence.credential_id,),
            ).fetchone()
            if cred["version"] != old["version"]:
                auth_error(401, "invalid_credential")
            factor = self._factor(c, u["subject_id"])
            if not factor:
                auth_error(403, "mfa_required")
            return self._mint(
                c,
                u,
                cred,
                session["account_id"],
                origin,
                self._now(c),
                session["session_epoch"],
                "step_up",
                factor_id=factor["factor_id"],
                session_id=session["session_id"],
                target=action,
            )

    def consume_step_up(self, c, session_token, proof, action, origin):
        """Reusable transaction guard. Action and exact AuthSession are mandatory."""
        row, u, cred, now = self._challenge(
            c, proof, origin, {"proof"}, session_token=session_token, target=action
        )
        factor = self._factor(c, u["subject_id"])
        if not factor or factor["factor_id"] != row["factor_id"]:
            auth_error(401, "invalid_credential")
        self._consume(c, row, now)
        return row, u, cred, now

    @boundary
    def rotate_recovery(self, token, proof, *, origin):
        with self._tx() as tx:
            row, u, _, now = self.consume_step_up(
                tx.connection, token, proof, "recovery.rotate", origin
            )
            codes = self._codes(tx.connection, u["subject_id"], row["factor_id"], now)
            self._audit(
                tx.connection,
                "auth_mfa_changed",
                u["subject_id"],
                row["factor_id"],
                "recovery_rotated",
            )
            return codes

    @boundary
    def replace_factor(self, token, proof, *, origin):
        with self._tx() as tx:
            c = tx.connection
            row, u, cred, now = self.consume_step_up(
                c, token, proof, "mfa.replace", origin
            )
            self._reset_factor(c, u["subject_id"], now)
            self._audit(
                c,
                "auth_mfa_changed",
                u["subject_id"],
                row["factor_id"],
                "replacement_sessions_revoked",
            )
            return self._mint(
                c,
                u,
                cred,
                row["account_id"],
                origin,
                now,
                self._epoch(c, u["subject_id"]),
                "enroll_start",
                expires_at=row["expires_at"],
            )

    @boundary
    def prepare_bootstrap(self):
        """CLI ONLY. Singleton row is durable even after secret expiry/consume."""
        with self._tx() as tx:
            c = tx.connection
            c.execute("SELECT pg_advisory_xact_lock(2105001)")
            if (
                c.execute(
                    "SELECT 1 FROM auth_identities WHERE platform_role='admin' LIMIT 1"
                ).fetchone()
                or c.execute("SELECT 1 FROM auth_bootstrap").fetchone()
            ):
                auth_error(409, "auth_version_conflict")
            token = "b1_" + secrets.token_urlsafe(32)
            now = self._now(c)
            c.execute(
                "INSERT INTO auth_bootstrap(slot,token_hash,issued_at,expires_at) VALUES (1,%s,%s,%s)",
                (_hash(token, "cisstat.bootstrap/1"), now, now + timedelta(minutes=15)),
            )
            self._audit(
                c,
                "auth_mfa_changed",
                "operator:bootstrap",
                "bootstrap",
                "bootstrap_prepared",
                actor_via="operator_cli",
                resource_kind="bootstrap",
            )
            return token

    @boundary
    def bootstrap(self, secret, login, password):
        from .credentials import normalize_login

        login = normalize_login(login)
        encoded = self.codec.hash(password)
        with self._tx() as tx:
            c = tx.connection
            c.execute("SELECT pg_advisory_xact_lock(2105001)")
            row = c.execute(
                "SELECT * FROM auth_bootstrap WHERE slot=1 FOR UPDATE"
            ).fetchone()
            now = self._now(c)
            if (
                not row
                or row["consumed_at"] is not None
                or now >= row["expires_at"]
                or now < row["issued_at"]
                or not hmac.compare_digest(
                    row["token_hash"], _hash(secret, "cisstat.bootstrap/1")
                )
                or c.execute(
                    "SELECT 1 FROM auth_identities WHERE platform_role='admin' LIMIT 1"
                ).fetchone()
            ):
                auth_error(401, "invalid_credential")
            u = tx.identities.create(platform_role="admin")
            account = tx.accounts.create(u.subject_id, plan="internal")
            credential = uuid4()
            c.execute(
                "INSERT INTO auth_password_credentials(credential_id,subject_id,login,password_hash) VALUES (%s,%s,%s,%s)",
                (credential, u.subject_id, login, encoded),
            )
            self._epoch(c, u.subject_id)
            c.execute(
                "UPDATE auth_subject_security SET enrollment_allowed=true WHERE subject_id=%s",
                (u.subject_id,),
            )
            c.execute("UPDATE auth_bootstrap SET consumed_at=%s WHERE slot=1", (now,))
            self._audit(
                c,
                "auth_mfa_changed",
                "operator:bootstrap",
                u.subject_id,
                "bootstrap_admin_created",
                actor_via="operator_cli",
                resource_kind="identity",
            )
            return {
                "subject_id": str(u.subject_id),
                "account_id": str(account.account_id),
                "login": login,
            }


def mfa_for_request(request):
    state = request.app.state
    provided = getattr(state, "auth_mfa_service", None)
    return (
        provided
        if provided is not None
        else MfaService(getattr(state, "auth_access_store", None))
    )
