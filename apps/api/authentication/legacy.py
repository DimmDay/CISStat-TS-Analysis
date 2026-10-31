"""Transitional ENV credentials. No raw key is copied into a principal/context."""

import os
from uuid import UUID

from apps.api.plans import AuthenticatedPrincipal, PlanName, Role


def _uuid(value):
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def parse_key_registry():
    from apps.api.identity import (
        ALL_SCOPES,
        DEFAULT_TENANT_ID,
        is_valid_subject_id,
        is_valid_tenant_id,
        subject_pseudonym,
    )

    registry = {}
    duplicates = set()
    for entry in filter(None, os.environ.get("CISSTAT_API_KEYS", "").split(",")):
        parts = entry.split(":")
        if not 3 <= len(parts) <= 7:
            continue
        key, role, plan = parts[:3]
        if not key or key in duplicates:
            continue
        if key in registry:
            registry.pop(key)
            duplicates.add(key)
            continue
        subject = parts[3] if len(parts) > 3 and parts[3] else subject_pseudonym(key)
        tenant = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_TENANT_ID
        scopes = (
            tuple(s.strip() for s in parts[5].split("+") if s.strip())
            if len(parts) > 5
            else ()
        )
        account = parts[6] if len(parts) > 6 and parts[6] else None
        if (
            subject == key
            or not is_valid_subject_id(subject)
            or not is_valid_tenant_id(tenant)
            or not set(scopes) <= ALL_SCOPES
            or (account is not None and (not _uuid(subject) or not _uuid(account)))
        ):
            continue
        try:
            registry[key] = AuthenticatedPrincipal(
                principal_id=subject,
                subject_id=subject,
                tenant_id=tenant,
                role=Role(role),
                plan=PlanName(plan) if plan else None,
                scopes=scopes,
                account_id=account,
                credential_id="cred-"
                + subject_pseudonym("api-key-reference:" + key)[5:],
                auth_method="legacy_api_key",
            )
        except ValueError:
            continue
    return registry


class LegacyCredentialVerifier:
    """Deployment-owned compatibility adapter; not a personal session verifier."""

    def api_key(self, key):
        from .context import VerifiedCredential, auth_error

        registry = parse_key_registry()
        if not registry:
            auth_error(503, "auth_authority_unavailable")
        principal = registry.get(key)
        if principal is None:
            return None
        durable = _uuid(principal.subject_id)
        return VerifiedCredential(
            subject_id=principal.subject_id,
            account_id=principal.account_id,
            credential_id=principal.credential_id,
            auth_method="api_key" if durable else "legacy_api_key",
            scopes=frozenset(principal.scopes),
            legacy_principal=None if durable else principal,
        )

    def session(self, request):
        from .context import auth_error

        # AUTH-04 owns this cookie and the verifier implementation. Do not
        # reinterpret a presented AuthSession token as a research pointer.
        if "__Host-cisstat_auth" in request.cookies:
            auth_error(401, "invalid_credential")
        return None
