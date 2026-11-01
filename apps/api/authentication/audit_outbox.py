"""Durable AUTH-04 intent -> existing security_audit sink, idempotent audit_id.

No independent auth security journal; no external sink call inside a mutation.
"""

from .sessions import boundary
from .storage import PostgresAccessStore
from .context import auth_error


@boundary
def publish_pending(*, store=None, sink=None, limit=100):
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("bounded audit batch required")
    if sink is None:
        from apps.api.security_audit import get_audit_sink, PostgresAuditSink

        sink = get_audit_sink()
        # Default dev memory is never presented as durable outbox delivery.
        if not isinstance(sink, PostgresAuditSink):
            auth_error(503, "auth_authority_unavailable")
    store = store if store is not None else PostgresAccessStore.from_env()
    count = 0
    with store.transaction() as tx:
        rows = tx.connection.execute(
            """SELECT audit_id,payload FROM auth_audit_outbox WHERE delivered_at IS NULL
            ORDER BY created_at,audit_id LIMIT %s FOR UPDATE SKIP LOCKED""",
            (limit,),
        ).fetchall()
        for row in rows:
            # Crash after append/before mark is safe: existing PostgresAuditSink
            # INSERT ... ON CONFLICT(audit_id) DO NOTHING is the consumer fence.
            if not sink.append(row["payload"]):
                auth_error(503, "auth_authority_unavailable")
            tx.connection.execute(
                "UPDATE auth_audit_outbox SET delivered_at=clock_timestamp() WHERE audit_id=%s",
                (row["audit_id"],),
            )
            count += 1
    return count
