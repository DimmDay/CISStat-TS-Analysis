"""AUTH-20 facts-only /health/ops projection of the audit/ops authority.

Peek semantics: no factory initialization beyond the cheap store object;
every probe is bounded and any failure degrades to a safe placeholder.
No DSN, token, cookie or ledger row content is ever exposed.
"""

from .lockdown import LOCKDOWN_ENV, engaged
from .ops_sweeper import INTERVAL_ENV


def _external_entry_flags():
    from .email_challenges import email_configured
    from .oidc import oidc_configured

    return {"oidc": bool(oidc_configured()), "email_trial": bool(email_configured())}


def build_auth_ops_health(*, audit_sweeper=None, store=None):
    import os

    payload = {
        "state": "ok",
        "lockdown": engaged(),
        "lockdown_env": LOCKDOWN_ENV,
        "audit_sweeper": dict(audit_sweeper or {}),
        "audit_sweeper_interval_env": INTERVAL_ENV,
        "external_entry": _external_entry_flags(),
        "audit_outbox_pending": None,
        "ledger": None,
        "schema_version": None,
    }
    try:
        from .auth20_migrations import VERSION
        from .storage import PostgresAccessStore

        if store is None:
            store = PostgresAccessStore.from_env()
        with store.transaction(readonly=True) as tx:
            c = tx.connection
            from .auth20_migrations import check_schema

            check_schema(c)
            payload["schema_version"] = VERSION
            payload["audit_outbox_pending"] = c.execute(
                "SELECT count(*) AS n FROM auth_audit_outbox WHERE delivered_at IS NULL"
            ).fetchone()["n"]
            payload["ledger"] = {
                "total": c.execute("SELECT count(*) AS n FROM auth_ops_ledger").fetchone()["n"],
                "last_24h": c.execute(
                    "SELECT count(*) AS n FROM auth_ops_ledger WHERE occurred_at > now() - interval '24 hours'"
                ).fetchone()["n"],
            }
    except Exception as exc:  # noqa: BLE001 — диагностика не роняет health
        from apps.api.storage_diagnostics import safe_health_error

        payload["state"] = "degraded"
        payload["detail"] = safe_health_error(exc)
    return payload
