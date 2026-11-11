"""AUTH-19 OIDC login/link orchestration on durable AUTH-04 sessions.

Entry is deny-by-default: without CISSTAT_AUTH_OIDC_ISSUER/CLIENT_ID every
command returns a safe 503 and no network call is made. The IdP code/state is
consumed before any outbound token exchange; an unknown (issuer, subject)
binding is denied without registration or email-based merge.
"""

import os
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from .context import auth_error
from .providers.oidc import OidcConfig, OidcProvider, ProviderMismatch, ProviderUnavailable
from .sessions import (
    AccountChoices,
    IssuedSession,
    SessionService,
    available_accounts,
    boundary,
    state_digest,
)

STATE_TTL = timedelta(minutes=10)
SELECT_TTL = timedelta(minutes=5)


def oidc_configured():
    config = os.environ.get("CISSTAT_AUTH_OIDC_ISSUER", "") and os.environ.get(
        "CISSTAT_AUTH_OIDC_CLIENT_ID", ""
    )
    return bool(config)


class OidcService(SessionService):
    def _provider(self):
        try:
            config = OidcConfig.from_env()
        except ValueError:
            auth_error(503, "oidc_unavailable")
        if config is None:
            auth_error(503, "oidc_unavailable")
        return OidcProvider(config)

    @staticmethod
    def _provider_error(exc):
        # Safe upstream mapping: protocol forgery is a credential failure,
        # provider/config/transport problems are temporary unavailability.
        if isinstance(exc, ProviderMismatch):
            auth_error(401, "invalid_credential")
        auth_error(503, "auth_authority_unavailable")

    def _insert_state(self, c, purpose, origin, now, *, subject_id=None, nonce=None, verifier=None, ttl=STATE_TTL):
        token = "o1_" + secrets.token_urlsafe(32)
        row = c.execute(
            """INSERT INTO auth_login_states(state_id,purpose,state_hash,nonce,pkce_verifier,subject_id,origin,issued_at,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING state_id""",
            (
                uuid4(),
                purpose,
                state_digest(token),
                nonce,
                verifier,
                subject_id,
                origin,
                now,
                now + ttl,
            ),
        ).fetchone()
        return token, row["state_id"]

    @boundary
    def start(self, purpose, origin, peer, *, session_token=None):
        from .lockdown import assert_open

        assert_open()
        provider = self._provider()
        self._limit("oidc-peer:" + peer, 30)
        subject_id = None
        if purpose == "link":
            if not session_token:
                auth_error(401, "authentication_required")
            evidence = self.verify(session_token, origin=origin)
            subject_id = UUID(evidence.subject_id)
        elif purpose != "login":
            auth_error(422, "invalid_request")
        from .providers.oidc import pkce_pair

        try:
            discovery = provider.discovery()
            verifier, challenge = pkce_pair()
        except (ProviderMismatch, ProviderUnavailable) as exc:
            self._provider_error(exc)
        nonce = secrets.token_urlsafe(24)
        with self._tx() as tx:
            c = tx.connection
            from .auth19_migrations import check_schema

            check_schema(c)
            now = self._now(c)
            state, _ = self._insert_state(
                c,
                "oidc_link" if purpose == "link" else "oidc_login",
                origin,
                now,
                subject_id=subject_id,
                nonce=nonce,
                verifier=verifier,
            )
        try:
            url = provider.authorization_url(
                redirect_uri=origin + "/login",
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                discovery=discovery,
            )
        except (ProviderMismatch, ProviderUnavailable) as exc:
            self._provider_error(exc)
        return {"authorize_url": url, "state": state}

    @boundary
    def callback(self, code, state, origin, peer, *, old_token=None, session_token=None):
        provider = self._provider()
        digest = state_digest(state)
        with self._tx() as tx:
            c = tx.connection
            from .auth19_migrations import check_schema

            check_schema(c)
            now = self._now(c)
            row = c.execute(
                """UPDATE auth_login_states SET consumed_at=%s
                WHERE state_hash=%s AND purpose IN ('oidc_login','oidc_link')
                AND consumed_at IS NULL AND expires_at>%s AND issued_at<=%s AND origin=%s
                RETURNING purpose,nonce,pkce_verifier,subject_id""",
                (now, digest, now, now, origin),
            ).fetchone()
            if not row:
                auth_error(401, "invalid_credential")
        try:
            discovery = provider.discovery()
            tokens = provider.exchange(
                code=code,
                code_verifier=row["pkce_verifier"],
                redirect_uri=origin + "/login",
                discovery=discovery,
            )
            claims = provider.verify_id_token(
                tokens["id_token"], nonce=row["nonce"], discovery=discovery
            )
        except (ProviderMismatch, ProviderUnavailable) as exc:
            self._provider_error(exc)
        issuer = provider.config.issuer
        if row["purpose"] == "oidc_link":
            return self._link(
                row["subject_id"], issuer, claims, origin, session_token
            )
        return self._login(issuer, claims, origin, old_token)

    def _identity_by_binding(self, c, issuer, sub):
        return c.execute(
            """SELECT i.* FROM auth_identities i JOIN auth_external_identities e USING(subject_id)
            WHERE e.issuer=%s AND e.external_subject=%s""",
            (issuer, sub),
        ).fetchone()

    def _login(self, issuer, claims, origin, old_token):
        from apps.api.security_audit import record_standard

        with self._tx() as tx:
            c = tx.connection
            u = self._identity_by_binding(c, issuer, claims["sub"])
            if not u:
                record_standard(
                    "authn_denied",
                    "denied",
                    actor_via="oidc",
                    policy_basis="AUTH-19 external identity binding",
                    details={"reason_code": "invalid_credential"},
                )
                auth_error(401, "invalid_credential")
            u = self._identity(c, u["subject_id"])
            if not u or u["status"] != "active" or u["kind"] != "person":
                auth_error(401, "invalid_credential")
            if u["platform_role"] == "admin":
                # IdP-MFA evidence contract is a separate delivery; local
                # password+MFA admin login stays the supported path (R3).
                auth_error(403, "mfa_required")
            now = self._now(c)
            kind, value = available_accounts(tx, u["subject_id"], now)
            if kind == "none" or (kind == "single" and value is None):
                auth_error(403, "account_access_denied")
            if kind == "multiple":
                token = self._insert_select_state(
                    c, "oidc_select", origin, now, u["subject_id"]
                )
                return {
                    "status": "account_required",
                    "accounts": value.accounts,
                    "selection_token": token,
                }
            epoch = self._epoch(c, u["subject_id"])
            auth_time = claims.get("auth_time")
            if not isinstance(auth_time, (int, float)) or auth_time > now.timestamp() + 60:
                auth_time = None
            if auth_time:
                from datetime import datetime, timezone

                auth_time = datetime.fromtimestamp(auth_time, timezone.utc)
            self._retire_old(c, old_token, now)
            return self._issue_external(
                c, u, value, origin, now, epoch, method="oidc", auth_time=auth_time
            )

    def _link(self, subject_id, issuer, claims, origin, session_token):
        if not session_token:
            auth_error(401, "authentication_required")
        evidence = self.verify(session_token, touch=False, origin=origin)
        if evidence.subject_id != str(subject_id):
            auth_error(401, "invalid_credential")
        with self._tx() as tx:
            c = tx.connection
            u = self._identity(c, subject_id)
            if not u or u["status"] != "active" or u["kind"] != "person":
                auth_error(401, "invalid_credential")
            now = self._now(c)
            existing = self._identity_by_binding(c, issuer, claims["sub"])
            if existing and existing["subject_id"] != u["subject_id"]:
                auth_error(409, "oidc_already_linked")
            if not existing:
                tx.identities.link_external(
                    u["subject_id"],
                    issuer,
                    claims["sub"],
                    email=claims.get("email"),
                    email_verified=bool(claims.get("email_verified"))
                    and isinstance(claims.get("email"), str),
                )
                self._audit_identity(
                    c, u["subject_id"], "oidc_linked", issuer
                )
            return {"status": "linked"}

    def _audit_identity(self, c, subject, operation, provider):
        from apps.api.security_audit import build_audit_record
        import json as _json

        record = build_audit_record(
            "auth_identity_changed",
            "allowed",
            actor_subject=str(subject),
            actor_via="auth_session",
            resource_kind="identity",
            resource_id=str(subject),
            policy_basis="AUTH-19 external identity binding",
            details={"operation": operation, "provider": provider},
        )
        c.execute(
            "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
            (record["audit_id"], _json.dumps(record)),
        )


def service_for_request(request):
    state = getattr(getattr(request, "scope", {}).get("app"), "state", None)
    provided = getattr(state, "auth_oidc_service", None)
    if provided is not None:
        return provided
    return OidcService(store=getattr(state, "auth_access_store", None))
