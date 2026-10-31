#!/usr/bin/env python3
"""Seed/verify disposable records across an actual database process restart.

CISSTAT_AUTH_TEST_DSN only. The JSON contains IDs/versions, no DSN or secrets.
This helper never touches public auth tables; its schema name is server-generated.
"""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.authentication.storage import PostgresAccessStore


def main():
    import psycopg
    from psycopg import sql

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seed", "verify"])
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get("CISSTAT_AUTH_TEST_DSN")
    if not dsn:
        raise SystemExit("CISSTAT_AUTH_TEST_DSN required")
    if args.action == "seed":
        schema = "auth02_restart_" + uuid4().hex
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        store = PostgresAccessStore(dsn, schema=schema)
        store.migrate()
        with store.transaction() as tx:
            identity = tx.identities.create()
            tx.identities.link_external(
                identity.subject_id, "restart-probe", "external-sub"
            )
            account = tx.accounts.create(identity.subject_id)
            identity = tx.identities.set_status(
                identity.subject_id,
                "suspended",
                expected_version=identity.subject_version,
            )
        args.state.write_text(
            json.dumps(
                {
                    "schema": schema,
                    "subject": str(identity.subject_id),
                    "subject_version": identity.subject_version,
                    "account": str(account.account_id),
                    "tenant": str(account.tenant_id),
                    "entitlement_version": account.entitlement_version,
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        print("restart probe seeded")
        return
    state = json.loads(args.state.read_text(encoding="utf-8"))
    if not re.fullmatch(r"auth02_restart_[a-f0-9]{32}", state["schema"]):
        raise SystemExit("unexpected test schema")
    store = PostgresAccessStore(dsn, schema=state["schema"])
    for _ in range(50):
        if store.readiness()["ok"]:
            break
        time.sleep(0.2)
    else:
        raise SystemExit("test database not ready after restart")
    with store.transaction(readonly=True) as tx:
        identity = tx.identities.by_external("restart-probe", "external-sub")
        account = tx.accounts.get(state["account"])
        assert (
            str(identity.subject_id) == state["subject"]
            and identity.subject_version == state["subject_version"]
        )
        assert identity.status == "suspended"
        assert (
            str(account.tenant_id) == state["tenant"]
            and account.entitlement_version == state["entitlement_version"]
        )
        assert (
            tx.accounts.memberships(account.account_id)[0].subject_id
            == identity.subject_id
        )
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(state["schema"]))
        )
    print(
        "restart probe verified: identity/external/account/membership/versions durable"
    )


if __name__ == "__main__":
    main()
