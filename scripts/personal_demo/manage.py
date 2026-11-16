"""Operator-only SMTP diagnostics and pause of new trial issuance. No secrets in output."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("status", "smtp-test", "pause", "resume"))
    p.add_argument("--to")
    a = p.parse_args()
    try:
        from apps.api.authentication.email_challenges import email_configured
        from apps.api.authentication.personal_demo import POOL_ID, metadata

        if a.command == "status":
            print(
                json.dumps(
                    {
                        "email_configured": email_configured(),
                        "personal_demo": metadata(),
                    }
                )
            )
            return 0
        if not sys.stdin.isatty():
            p.error("interactive operator terminal required")
        if a.command == "smtp-test":
            if not a.to:
                p.error("--to your own test mailbox required")
            from apps.api.authentication.providers.email_delivery import (
                SmtpEmailDelivery,
            )

            delivery = SmtpEmailDelivery.from_env()
            if not delivery:
                raise ValueError()
            delivery.send(
                a.to,
                "CISStat DataTime Lab — SMTP test",
                "SMTP transport test. No login link or account was created.",
            )
            print('{"ok":true,"sent":true}')
            return 0
        from apps.api.authentication.personal_demo_migrations import check_schema
        from apps.api.authentication.storage import PostgresAccessStore
        from apps.api.billing.coordinator import audit

        if input("Type personal-demo to change new registrations: ") != "personal-demo":
            return 2
        with PostgresAccessStore.from_env().transaction() as tx:
            c = tx.connection
            check_schema(c)
            c.execute(
                "UPDATE auth_personal_demo_pool SET status=%s WHERE pool_id=%s",
                ("paused" if a.command == "pause" else "active", POOL_ID),
            )
            audit(
                c,
                "auth_budget_changed",
                POOL_ID,
                details={"command": "personal_demo_" + a.command},
            )
        print('{"ok":true}')
        return 0
    except Exception:  # noqa: BLE001 -- never print SMTP response/driver/configuration values
        print('{"ok":false,"code":"personal_demo_operator_failed"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
