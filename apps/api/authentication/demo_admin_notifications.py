"""Admin-only durable notice after first verified trial grant. No login proof.

Claim/lease and fenced acknowledgement use short SQL transactions; SMTP runs
outside them and outside login. Delivery is at least once after an ambiguous
SMTP outcome/crash; a stable Message-ID identifies retries, not an exactly-once
promise. Normal logins and competing workers do not duplicate a notice.
"""
import os
from datetime import timedelta, timezone
from decimal import Decimal
from email.utils import parseaddr
from uuid import uuid4

from .storage import PostgresAccessStore
from .demo_admin_migrations import check_schema
from .providers.email_delivery import SmtpEmailDelivery

SUBJECT = "Новый пользователь подтвердил email и получил демо-доступ"
MOSCOW = timezone(timedelta(hours=3), "МСК")


def enabled():
    return os.environ.get("CISSTAT_DEMO_ADMIN_NOTIFICATIONS_ENABLED") == "1"


def recipient():
    from .email_challenges import normalize_email
    try:
        return normalize_email(os.environ.get("CISSTAT_DEMO_ADMIN_EMAIL", ""))
    except Exception:
        raise ValueError("admin recipient unavailable") from None


def enqueue(c, subject, email, issued_at, expires_at, limits):
    if not enabled():
        return
    check_schema(c)
    c.execute(
        """INSERT INTO auth_demo_admin_notifications
        (notification_id,user_email,issued_at,expires_at,micro_cu,analyses,concurrency,max_rows)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(notification_id) DO NOTHING""",
        (subject, email, issued_at, expires_at, limits["micro_cu"], limits["analyses"],
         limits["concurrency"], limits["max_rows"]),
    )


def letter(row):
    def date(value):
        return value.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M:%S МСК")
    cu = format(Decimal(row["micro_cu"]) / Decimal(1000000), "f")
    return (
        SUBJECT + ".\n\n"
        "Пользователь: " + row["user_email"] + "\n"
        "Email подтверждён, демо выдано: " + date(row["issued_at"]) + "\n"
        "Демо-доступ до: " + date(row["expires_at"]) + "\n\n"
        "Выданные лимиты:\n"
        f"• Вычислительный бюджет: {cu} CU\n"
        f"• Исследования: {row['analyses']}\n"
        f"• Одновременные вычисления: {row['concurrency']}\n"
        f"• Строк в датасете: до {row['max_rows']}\n"
        "\nЛичное пространство MONO. Уведомление о первой выдаче демо-доступа.\n"
    )


def claim(store, to_email):
    with store.transaction() as tx:
        c = tx.connection
        check_schema(c)
        row = c.execute(
            """SELECT notification_id FROM auth_demo_admin_notifications
            WHERE (status='pending' AND next_attempt_at<=clock_timestamp())
               OR (status='sending' AND lease_until<=clock_timestamp())
            ORDER BY issued_at,notification_id LIMIT 1 FOR UPDATE SKIP LOCKED"""
        ).fetchone()
        if not row:
            return None
        return c.execute(
            """UPDATE auth_demo_admin_notifications SET status='sending', attempts=attempts+1,
            claim_id=%s,lease_until=clock_timestamp()+interval '3 minutes',
            recipient=COALESCE(recipient,%s)
            WHERE notification_id=%s RETURNING *""",
            (uuid4(), to_email, row["notification_id"]),
        ).fetchone()


def complete(store, row, *, sent):
    delay = min(3600, 30 * 2 ** min(row["attempts"] - 1, 7))
    with store.transaction() as tx:
        return tx.connection.execute(
            """UPDATE auth_demo_admin_notifications SET status=%s,
            sent_at=CASE WHEN %s THEN clock_timestamp() ELSE NULL END,
            last_error_code=%s, next_attempt_at=clock_timestamp()+%s,
            claim_id=NULL,lease_until=NULL
            WHERE notification_id=%s AND status='sending' AND claim_id=%s RETURNING notification_id""",
            ("sent" if sent else "pending", sent, None if sent else "smtp_unavailable",
             timedelta(seconds=delay), row["notification_id"], row["claim_id"]),
        ).fetchone() is not None


def publish_pending(*, store=None, delivery=None):
    if not enabled():
        return {"enabled": False, "sent": 0}
    to_email = recipient()  # Invalid config never claims a row or affects login.
    store = store if store is not None else PostgresAccessStore.from_env()
    delivery = delivery if delivery is not None else SmtpEmailDelivery.from_env()
    if delivery is None:
        return {"enabled": True, "sent": 0, "error": "smtp_unconfigured"}
    row = claim(store, to_email)
    if row is None:
        return {"enabled": True, "sent": 0}
    try:
        domain = parseaddr(delivery.sender)[1].rsplit("@", 1)[1]
        delivery.send(row["recipient"], SUBJECT, letter(row),
                      message_id=f"<demo-admin.{row['notification_id']}@{domain}>")
    except Exception:  # Never log SMTP responses, addresses, credentials or bodies.
        complete(store, row, sent=False)
        return {"enabled": True, "sent": 0, "error": "smtp_unavailable"}
    marked = complete(store, row, sent=True)
    return {"enabled": True, "sent": int(marked)}


def status(*, store=None):
    store = store if store is not None else PostgresAccessStore.from_env()
    with store.transaction(readonly=True) as tx:
        check_schema(tx.connection)
        counts = tx.connection.execute(
            "SELECT status,count(*) AS n FROM auth_demo_admin_notifications GROUP BY status"
        ).fetchall()
        errors = tx.connection.execute(
            "SELECT count(*) AS n FROM auth_demo_admin_notifications WHERE status<>'sent' AND last_error_code IS NOT NULL"
        ).fetchone()["n"]
    try:
        recipient()
        configured = True
    except ValueError:
        configured = False
    from .ops_sweeper import interval_seconds
    return {"enabled": enabled(), "worker_interval_seconds": interval_seconds(), "recipient_configured": configured,
            "smtp_configured": SmtpEmailDelivery.from_env() is not None,
            "counts": {s: next((r["n"] for r in counts if r["status"] == s), 0)
                       for s in ("pending", "sending", "sent")}, "retrying": errors}
