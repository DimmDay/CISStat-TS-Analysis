"""Opaque worker credentials; no cookie/API key or client identity delegation shortcut."""

import hashlib
import secrets
import re
from datetime import timedelta
from uuid import uuid4
from apps.api.authentication.context import auth_error
from apps.api.billing.coordinator import audit
from apps.api.authentication.storage import PostgresAccessStore
from .migrations import check_schema

KEY = re.compile(r"cwk_[A-Za-z0-9_-]{43}\Z")
KINDS = frozenset({"modeling", "render", "delivery"})


def digest(key):
    if not isinstance(key, str) or not KEY.fullmatch(key):
        auth_error(503, "worker_service_unavailable")
    return hashlib.sha256(("cisstat.worker/1\0" + key).encode()).hexdigest()


def verify(c, key, kind, *, lock=False):
    row = c.execute(
        "SELECT * FROM auth_worker_services WHERE key_hash=%s"
        + (" FOR SHARE" if lock else ""),
        (digest(key),),
    ).fetchone()
    now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    if (
        not row
        or kind is not None
        and kind not in row["kinds"]
        or row["revoked_at"] is not None
        or now >= row["expires_at"]
    ):
        auth_error(503, "worker_service_unavailable")
    return row


class WorkerServices:
    def __init__(self, store=None):
        self.store = store if store is not None else PostgresAccessStore.from_env()

    def issue(self, *, kinds, reason, days=365):
        if (
            not kinds
            or not set(kinds) <= KINDS
            or type(days) is not int
            or not 1 <= days <= 365
        ):
            raise ValueError("bounded service authority required")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise ValueError("reason required")
        key = "cwk_" + secrets.token_urlsafe(32)
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
            sid = uuid4()
            c.execute(
                "INSERT INTO auth_worker_services(service_id,key_hash,kinds,created_at,expires_at) VALUES (%s,%s,%s,%s,%s)",
                (sid, digest(key), sorted(set(kinds)), now, now + timedelta(days=days)),
            )
            audit(
                c,
                "auth_worker_changed",
                sid,
                details={
                    "transition": "service_issued",
                    "kinds": sorted(kinds),
                    "reason": reason,
                },
            )
        return key

    def revoke(self, service_id, *, reason):
        if not reason or len(reason) > 256:
            raise ValueError("reason required")
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            row = c.execute(
                "SELECT * FROM auth_worker_services WHERE service_id=%s FOR UPDATE",
                (service_id,),
            ).fetchone()
            if not row:
                auth_error(404, "worker_not_found")
            if row["revoked_at"] is not None:
                return
            c.execute(
                "UPDATE auth_worker_services SET revoked_at=clock_timestamp() WHERE service_id=%s",
                (service_id,),
            )
            audit(
                c,
                "auth_worker_changed",
                service_id,
                details={"transition": "service_revoked", "reason": reason},
            )
