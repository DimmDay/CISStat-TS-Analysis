"""AUTH-20 native PostgreSQL: revocation ledger, marks export/restore
reconciliation, quarantine, lockdown, mandatory-audit delivery.

Real SQL transactions against a disposable PostgreSQL. Backup restore is
emulated faithfully: schema drop + fresh migrations + snapshot rows replayed
with session_replication_role=replica (the physical pg_restore contract).
No real network, no production VM is claimed.
"""

import json
import os
from datetime import timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from fastapi import HTTPException

from apps.api.authentication.auth20_migrations import CHECKSUM, VERSION, apply_migration, check_schema
from apps.api.authentication.ops_service import AuthOpsService
from apps.api.authentication.storage import PostgresAccessStore
from tests.integration import test_auth04_sessions as previous

PASS = previous.PASS
ORIGIN = previous.ORIGIN
DSN = previous.DSN

@unittest.skipUnless(
    os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required"
)
class Auth20SQLTests(previous.SessionSQLTests):
    """Extends the AUTH-04 native fixture; fresh schema per test."""

    def setUp(self):
        super().setUp()
        with self.store.transaction() as tx:
            apply_migration(tx.connection)
        self.ops = AuthOpsService(store=self.store)

    # -- helpers -------------------------------------------------------

    def person(self, login):
        with self.store.transaction() as tx:
            person = tx.identities.create()
            account = tx.accounts.create(person.subject_id, plan="starter")
        self.service.set_password(person.subject_id, login, PASS)
        issued = self.service.login(
            login, PASS, account.account_id, origin=ORIGIN
        )
        return person, account, issued.token

    def error(self, work, status, code=None):
        with self.assertRaises(HTTPException) as result:
            work()
        self.assertEqual(result.exception.status_code, status)
        if code:
            self.assertEqual(result.exception.detail["code"], code)

    def rows(self, table):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute("SELECT * FROM " + table).fetchall()

    def ledger(self, table=None):
        with self.store.transaction(readonly=True) as tx:
            if table:
                return tx.connection.execute(
                    "SELECT * FROM auth_ops_ledger WHERE table_name=%s ORDER BY entry_id",
                    (table,),
                ).fetchall()
            return tx.connection.execute(
                "SELECT * FROM auth_ops_ledger ORDER BY entry_id"
            ).fetchall()

    def api_key(self, subject_id, account_id, token):
        """Minimal durable API key (AUTH-10 row shape)."""
        key_id = uuid4()
        digest = "a" * 64
        with self.store.transaction() as tx:
            tx.connection.execute(
                """INSERT INTO auth_api_keys(key_id,family_id,token_hash,subject_id,account_id,
                subject_version,label,scopes,version,created_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,1,'reconcile',ARRAY['api.read']::text[],1,now(),now()+interval '30 days')""",
                (key_id, uuid4(), digest, subject_id, account_id),
            )
        return key_id

    def account_scope(self):
        with self.store.transaction() as tx:
            tx.connection.execute(
                """INSERT INTO auth_budget_scopes(scope_id,kind,parent_id,account_id,starts_at,ends_at)
                VALUES (%s,'account',NULL,%s,%s,NULL)
                ON CONFLICT (scope_id) DO NOTHING""",
                (self.account.account_id, self.account.account_id, self.now),
            )

    def campaign(self, *, alias=None):
        self.account_scope()
        campaign_id = uuid4()
        admission_id = uuid4()
        now = self.now
        with self.store.transaction() as tx:
            c = tx.connection
            sponsor = uuid4()
            c.execute(
                """INSERT INTO auth_budget_scopes(scope_id,kind,parent_id,account_id,starts_at,ends_at)
                VALUES (%s,'sponsor',NULL,NULL,%s,%s)""",
                (sponsor, now, now + timedelta(days=1)),
            )
            c.execute(
                """INSERT INTO auth_budget_scopes(scope_id,kind,parent_id,account_id,starts_at,ends_at)
                VALUES (%s,'campaign',%s,NULL,%s,%s)""",
                (campaign_id, sponsor, now, now + timedelta(days=1)),
            )
            c.execute(
                """INSERT INTO auth_demo_campaigns(campaign_id,alias,policy,password_hash,
                issued_grants,created_at,status,activated_at,sponsor_id)
                VALUES (%s,%s,%s,'$argon2id$'||repeat('x',64),0,%s,'active',%s,%s)""",
                (
                    campaign_id,
                    alias or ("ops-" + uuid4().hex[:8]),
                    json.dumps(
                        {
                            "starts_at": now.isoformat(),
                            "ends_at": (now + timedelta(days=1)).isoformat(),
                            "allowed_origins": [ORIGIN],
                            "grant_hours": 24,
                            "participant_cu": 100,
                            "participant_concurrency": 1,
                            "participant_analyses": 5,
                            "admission_codes": 1,
                        }
                    ),
                    now,
                    now,
                    sponsor,
                ),
            )
            c.execute(
                """INSERT INTO auth_demo_admissions(admission_id,campaign_id,code_hash,expires_at,created_at)
                VALUES (%s,%s,%s,%s,%s)""",
                (admission_id, campaign_id, uuid4().hex + uuid4().hex[:32], now + timedelta(days=1), now),
            )
        return campaign_id, admission_id

    def issue_grant(self, campaign_id):
        """A grant issued on the fixture owner account (the common flow)."""
        grant_id = uuid4()
        now = self.now
        with self.store.transaction() as tx:
            c = tx.connection
            c.execute(
                """INSERT INTO auth_budget_scopes(scope_id,kind,parent_id,account_id,starts_at,ends_at)
                VALUES (%s,'grant',%s,%s,%s,%s)""",
                (grant_id, self.account.account_id, self.account.account_id, now, now + timedelta(days=1)),
            )
            c.execute(
                """INSERT INTO auth_demo_grants(grant_id,campaign_id,subject_id,account_id,resume_hash,
                issued_at,expires_at,policy_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,1)""",
                (
                    grant_id,
                    campaign_id,
                    self.owner.subject_id,
                    self.account.account_id,
                    "b" * 64 if "b" * 64 not in [
                        r["resume_hash"] for r in c.execute("SELECT resume_hash FROM auth_demo_grants").fetchall()
                    ] else uuid4().hex + uuid4().hex[:32],
                    now,
                    now + timedelta(days=1),
                ),
            )
            c.execute(
                "UPDATE auth_demo_campaigns SET issued_grants=issued_grants+1 WHERE campaign_id=%s",
                (campaign_id,),
            )
        return grant_id

    def reservation_fixture(self, held=10):
        reservation_id = uuid4()
        with self.store.transaction() as tx:
            tx.connection.execute(
                """INSERT INTO auth_reservations(reservation_id,account_id,subject_id,tenant_id,
                canonical_operation,key_digest,payload_digest,admission,quote_version,held_cu,state,
                version,created_at,deadline)
                VALUES (%s,%s,%s,%s,'models.train',%s,%s,%s,'q1',%s,'running',1,%s,%s)""",
                (
                    reservation_id,
                    self.account.account_id,
                    self.owner.subject_id,
                    uuid4(),
                    "d" * 64,
                    "e" * 64,
                    json.dumps({"entry": "models.train"}),
                    held,
                    self.now,
                    self.now + timedelta(minutes=10),
                ),
            )
        return reservation_id

    def worker_service_fixture(self):
        service_id = uuid4()
        with self.store.transaction() as tx:
            tx.connection.execute(
                """INSERT INTO auth_worker_services(service_id,key_hash,kinds,created_at,expires_at)
                VALUES (%s,%s,ARRAY['modeling']::text[],%s,%s)""",
                (service_id, "f" * 64, self.now, self.now + timedelta(days=1)),
            )
        return service_id

    # -- restore emulation ----------------------------------------------

    def snapshot(self):
        """Capture every base table and sequence value in the test schema."""
        captured = {"tables": {}, "sequences": {}}
        with self.pg.connect(DSN, autocommit=True, row_factory=dict_row) as conn:
            conn.execute(
                sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(self.schema))
            )
            tables = [
                r["table_name"]
                for r in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name",
                    (self.schema,),
                ).fetchall()
            ]
            for table in tables:
                captured["tables"][table] = conn.execute(
                    "SELECT * FROM " + table
                ).fetchall()
            for seq in conn.execute(
                "SELECT sequencename,last_value FROM pg_sequences WHERE schemaname=%s",
                (self.schema,),
            ).fetchall():
                captured["sequences"][seq["sequencename"]] = seq["last_value"]
        return captured

    def restore(self, captured):
        """Faithful physical-restore emulation: drop schema, fresh migrations,
        replay ALL rows with triggers disabled (session_replication_role=replica,
        the pg_restore contract), then restore sequence state."""
        with self.pg.connect(DSN, autocommit=True, row_factory=dict_row) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
            conn.execute(
                sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(self.schema))
            )
            apply_migration(conn)
            conn.execute("SET session_replication_role = replica")
            from psycopg.types.json import Json

            # Fresh migrations already seeded 0019..0032 rows; the physical
            # restore replaces their content wholesale (pg_restore contract).
            captured_names = [n for n, r in captured["tables"].items() if r]
            if captured_names:
                conn.execute(
                    "TRUNCATE {} CASCADE".format(
                        ",".join(sql.Identifier(n).as_string(conn) for n in captured_names)
                    )
                )

            for table, rows in captured["tables"].items():
                if not rows:
                    continue
                columns = list(rows[0].keys())
                types = {
                    r["column_name"]: r["data_type"]
                    for r in conn.execute(
                        "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
                        (self.schema, table),
                    ).fetchall()
                }

                def _adapt(value, col, table=table, types=types):
                    if types.get(col) == "jsonb" and isinstance(value, (dict, list)):
                        return Json(value)
                    return value

                query = "INSERT INTO {} ({}) VALUES ({})".format(
                    sql.Identifier(table).as_string(conn),
                    ",".join(sql.Identifier(c).as_string(conn) for c in columns),
                    ",".join("%s" for _ in columns),
                )
                with conn.cursor() as cur:
                    cur.executemany(
                        query,
                        [
                            tuple(_adapt(row[c], c) for c in columns)
                            for row in rows
                        ],
                    )
            for name, value in captured["sequences"].items():
                conn.execute(
                    "SELECT setval(%s, %s, %s)",
                    (f"{self.schema}.{name}", value, True),
                )
            conn.execute("RESET session_replication_role")



    # -- migration -------------------------------------------------------

    def test_migration_apply_check_repeat_and_earlier_checksums(self):
        from apps.api.authentication.auth19_migrations import CHECKSUM as C31
        from apps.api.authentication.auth19_migrations import VERSION as V31
        from apps.api.billing.subscription_migrations import CHECKSUM as C30

        with self.store.transaction(readonly=True) as tx:
            check_schema(tx.connection)
            rows = {
                r["version"]: r["checksum"]
                for r in tx.connection.execute(
                    "SELECT version,checksum FROM auth_schema_versions"
                ).fetchall()
            }
        self.assertEqual(rows.get(V31), C31)
        self.assertEqual(rows.get("0030_auth18_provider"), C30)
        self.assertEqual(rows.get(VERSION), CHECKSUM)
        with self.store.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
        triggers = [
            "auth20_ledger_guard", "auth20_capture_password", "auth20_capture_sessions",
            "auth20_capture_api_keys", "auth20_capture_worker_services",
            "auth20_capture_demo_grants", "auth20_capture_demo_admissions",
            "auth20_capture_reservations", "auth20_capture_billing_orders",
        ]
        with self.store.transaction(readonly=True) as tx:
            found = {
                r["tgname"]
                for r in tx.connection.execute(
                    "SELECT tgname FROM pg_trigger WHERE tgname LIKE 'auth20%'"
                ).fetchall()
            }
        self.assertTrue(set(triggers) <= found)

    # -- ledger capture ----------------------------------------------------

    def test_ledger_captures_terminal_transitions_only(self):
        person_b, account_b, token_b = self.person("ops-bob")
        cred = [
            r
            for r in self.rows("auth_password_credentials")
            if r["subject_id"] == person_b.subject_id
        ][0]
        self.service.revoke_password(person_b.subject_id, expected_version=cred["version"])
        self.assertEqual(len(self.ledger("auth_password_credentials")), 1)

        # session revocation capture (password session of the fixture owner)
        owner_token = self.login().token
        self.service.revoke(owner_token, all_sessions=True)
        session_rows = self.ledger("auth_sessions")
        self.assertGreaterEqual(len(session_rows), 1)

        # non-terminal updates capture nothing
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_password_credentials SET version=version+1,updated_at=now() WHERE subject_id=%s",
                (person_b.subject_id,),
            )
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_sessions SET last_seen_at=now() WHERE revoked_at IS NULL"
            )
        self.assertEqual(len(self.ledger("auth_password_credentials")), 1)
        self.assertEqual(len(self.ledger("auth_sessions")), len(session_rows))

        # api key / worker service revocation capture
        key_id = self.api_key(person_b.subject_id, account_b.account_id, "ignored")
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_api_keys SET revoked_at=now(),version=version+1 WHERE key_id=%s",
                (key_id,),
            )
        service_id = self.worker_service_fixture()
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_worker_services SET revoked_at=now() WHERE service_id=%s",
                (service_id,),
            )
        self.assertEqual(len(self.ledger("auth_api_keys")), 1)
        self.assertEqual(len(self.ledger("auth_worker_services")), 1)

        # demo grant revoke + admission consume capture
        campaign_id, admission_id = self.campaign()
        grant_id = self.issue_grant(campaign_id)
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_demo_grants SET status='revoked' WHERE grant_id=%s",
                (grant_id,),
            )
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_demo_admissions SET redeemed_at=now(),redeemed_grant_id=%s WHERE admission_id=%s",
                (grant_id, admission_id),
            )
        self.assertEqual(len(self.ledger("auth_demo_grants")), 1)
        self.assertEqual(len(self.ledger("auth_demo_admissions")), 1)
        image = self.ledger("auth_demo_grants")[0]["row_image"]
        self.assertEqual(image["status"], "revoked")

        # reservation settle capture
        reservation_id = self.reservation_fixture()
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_reservations SET state='settled',actual_cu=5,version=version+1 WHERE reservation_id=%s",
                (reservation_id,),
            )
        ledger_reservation = self.ledger("auth_reservations")
        self.assertEqual(len(ledger_reservation), 1)
        self.assertEqual(ledger_reservation[0]["event"], "settled")
        self.assertEqual(ledger_reservation[0]["row_image"]["actual_cu"], 5)

        # ledger is append-only for UPDATE
        with self.store.transaction() as tx:
            with self.assertRaises(psycopg.errors.CheckViolation):
                tx.connection.execute(
                    "UPDATE auth_ops_ledger SET event='revoked' WHERE entry_id=%s",
                    (self.ledger()[0]["entry_id"],),
                )

    # -- marks export ------------------------------------------------------

    def test_marks_export_writes_atomic_file_and_audit_intent(self):
        campaign_id, admission_id = self.campaign()
        grant_id = self.issue_grant(campaign_id)
        path = f"/tmp/auth20-marks-{uuid4().hex}.json"
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        result = self.ops.export_marks(path)
        self.assertTrue(os.path.exists(path))
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        document = json.loads(Path(path).read_text())
        self.assertEqual(document["format"], "cisstat-auth20-marks/1")
        self.assertEqual(document["counts"], {})
        self.assertTrue(document["complete"])
        pending = [
            r
            for r in self.rows("auth_audit_outbox")
            if r["payload"]["action"] == "auth_ops_changed"
        ]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["payload"]["details"]["kind"], "marks_export")
        self.assertFalse(any(r["delivered_at"] for r in pending))
        self.assertEqual(result["entries"], 0)

    # -- restore reconciliation ----------------------------------------------

    def test_restore_reconciliation_reapplies_every_terminal_state(self):
        person, account, token = self.person("ops-alice")
        key_id = self.api_key(person.subject_id, account.account_id, "ignored")
        service_id = self.worker_service_fixture()
        campaign_id, admission_id = self.campaign()
        grant_id = self.issue_grant(campaign_id)
        reservation_id = self.reservation_fixture(held=20)
        cred = [
            r
            for r in self.rows("auth_password_credentials")
            if r["subject_id"] == person.subject_id
        ][0]

        captured = self.snapshot()

        # terminal transitions after the snapshot
        self.service.revoke(token, all_sessions=True)
        self.service.revoke_password(person.subject_id, expected_version=cred["version"])
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_api_keys SET revoked_at=now(),version=version+1 WHERE key_id=%s",
                (key_id,),
            )
            tx.connection.execute(
                "UPDATE auth_worker_services SET revoked_at=now() WHERE service_id=%s",
                (service_id,),
            )
            tx.connection.execute(
                "UPDATE auth_demo_grants SET status='revoked' WHERE grant_id=%s",
                (grant_id,),
            )
            tx.connection.execute(
                "UPDATE auth_demo_admissions SET redeemed_at=now(),redeemed_grant_id=%s WHERE admission_id=%s",
                (grant_id, admission_id),
            )
            tx.connection.execute(
                "UPDATE auth_reservations SET state='settled',actual_cu=15,version=version+1 WHERE reservation_id=%s",
                (reservation_id,),
            )
        path = f"/tmp/auth20-marks-{uuid4().hex}.json"
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        marks_result = self.ops.export_marks(path)
        self.assertGreaterEqual(marks_result["entries"], 6)
        marks = json.loads(Path(path).read_text())

        # physical restore emulation: everything rolls back
        self.restore(captured)
        self.ops = AuthOpsService(store=self.store)
        with self.store.transaction(readonly=True) as tx:
            cred_row = tx.connection.execute(
                "SELECT status FROM auth_password_credentials WHERE credential_id=%s",
                (cred["credential_id"],),
            ).fetchone()
            res_row = tx.connection.execute(
                "SELECT state,actual_cu FROM auth_reservations WHERE reservation_id=%s",
                (reservation_id,),
            ).fetchone()
            adm_row = tx.connection.execute(
                "SELECT redeemed_at FROM auth_demo_admissions WHERE admission_id=%s",
                (admission_id,),
            ).fetchone()
        self.assertEqual(cred_row["status"], "active")
        self.assertEqual(res_row["state"], "running")
        self.assertIsNone(res_row["actual_cu"])
        self.assertIsNone(adm_row["redeemed_at"])
        # resurrection is real: the credential logs in again
        self.service.login(
            "ops-alice", PASS, account.account_id, origin=ORIGIN
        )

        summary = self.ops.reconcile_marks(marks, reason="restore-check")
        self.assertGreaterEqual(summary["applied"], 6)
        self.assertEqual(summary["unrepairable"], [])
        with self.store.transaction(readonly=True) as tx:
            c = tx.connection
            self.assertEqual(
                c.execute(
                    "SELECT status FROM auth_password_credentials WHERE credential_id=%s",
                    (cred["credential_id"],),
                ).fetchone()["status"],
                "revoked",
            )
            self.assertEqual(
                c.execute(
                    "SELECT revoked_at IS NOT NULL AS gone FROM auth_sessions WHERE session_id IN (SELECT session_id FROM auth_sessions WHERE subject_id=%s)",
                    (person.subject_id,),
                ).fetchall()[0]["gone"],
                True,
            )
            self.assertEqual(
                c.execute(
                    "SELECT revoked_at IS NOT NULL AS gone FROM auth_api_keys WHERE key_id=%s",
                    (key_id,),
                ).fetchone()["gone"],
                True,
            )
            self.assertEqual(
                c.execute(
                    "SELECT revoked_at IS NOT NULL AS gone FROM auth_worker_services WHERE service_id=%s",
                (service_id,)).fetchone()["gone"],
                True,
            )
            self.assertEqual(
                c.execute(
                    "SELECT status FROM auth_demo_grants WHERE grant_id=%s",
                    (grant_id,),
                ).fetchone()["status"],
                "revoked",
            )
            self.assertIsNotNone(
                c.execute(
                    "SELECT redeemed_at FROM auth_demo_admissions WHERE admission_id=%s",
                    (admission_id,),
                ).fetchone()["redeemed_at"]
            )
            res_row = c.execute(
                "SELECT state,actual_cu FROM auth_reservations WHERE reservation_id=%s",
                (reservation_id,),
            ).fetchone()
        self.assertEqual(res_row["state"], "settled")
        self.assertEqual(res_row["actual_cu"], 15)
        # re-issued sessions died too; the old password no longer logs in
        self.error(
            lambda: self.service.login(
                "ops-alice", PASS, account.account_id, origin=ORIGIN
            ),
            401,
        )

        # idempotent second run: everything already terminal
        again = self.ops.reconcile_marks(marks, reason="replay")
        self.assertEqual(again["applied"], 0)
        self.assertEqual(again["skipped"], summary["applied"])

    def test_tombstone_grant_replayed_from_row_image(self):
        self.account_scope()
        campaign_id, admission_id = self.campaign()
        captured = self.snapshot()
        # grant issued AFTER the snapshot, then revoked
        grant_id = self.issue_grant(campaign_id)
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_demo_grants SET status='revoked' WHERE grant_id=%s",
                (grant_id,),
            )
        path = f"/tmp/auth20-marks-{uuid4().hex}.json"
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        marks = json.loads(Path(self.ops.export_marks(path)["path"]).read_text())
        self.restore(captured)
        self.ops = AuthOpsService(store=self.store)
        with self.store.transaction(readonly=True) as tx:
            self.assertIsNone(
                tx.connection.execute(
                    "SELECT 1 FROM auth_demo_grants WHERE grant_id=%s", (grant_id,)
                ).fetchone()
            )
        summary = self.ops.reconcile_marks(marks, reason="tombstone")
        self.assertEqual(summary["applied"], 1)
        with self.store.transaction(readonly=True) as tx:
            row = tx.connection.execute(
                "SELECT status,campaign_id,subject_id FROM auth_demo_grants WHERE grant_id=%s",
                (grant_id,),
            ).fetchone()
            issued = tx.connection.execute(
                "SELECT issued_grants FROM auth_demo_campaigns WHERE campaign_id=%s",
                (campaign_id,),
            ).fetchone()
        self.assertEqual(row["status"], "revoked")
        self.assertEqual(row["campaign_id"], campaign_id)
        self.assertEqual(issued["issued_grants"], 1)

    def test_unrepairable_consumed_reports_finding(self):
        campaign_id, admission_id = self.campaign()
        captured = self.snapshot()
        grant_id = self.issue_grant(campaign_id)
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_demo_admissions SET redeemed_at=now(),redeemed_grant_id=%s WHERE admission_id=%s",
                (grant_id, admission_id),
            )
        path = f"/tmp/auth20-marks-{uuid4().hex}.json"
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        marks = json.loads(Path(self.ops.export_marks(path)["path"]).read_text())
        self.restore(captured)
        self.ops = AuthOpsService(store=self.store)
        summary = self.ops.reconcile_marks(marks, reason="lost-grant")
        self.assertEqual(summary["applied"], 0)
        self.assertEqual(
            [f["reason"] for f in summary["unrepairable"]], ["consumed_grant_absent"]
        )

    # -- quarantine ----------------------------------------------------------

    def test_quarantine_closes_sessions_and_pauses_campaigns(self):
        person_b, account_b, token_b = self.person("ops-carol")
        campaign_id, admission_id = self.campaign()
        summary = self.ops.quarantine(reason="doubt-before-reconcile")
        self.assertGreaterEqual(summary["sessions_revoked"], 1)
        self.assertEqual(summary["campaigns_paused"], 1)
        with self.store.transaction(readonly=True) as tx:
            active = tx.connection.execute(
                "SELECT count(*) AS n FROM auth_sessions WHERE revoked_at IS NULL"
            ).fetchone()["n"]
            paused = tx.connection.execute(
                "SELECT status FROM auth_demo_campaigns WHERE campaign_id=%s",
                (campaign_id,),
            ).fetchone()["status"]
        self.assertEqual(active, 0)
        self.assertEqual(paused, "paused")
        # entries re-open after quarantine (it is not a lockdown)
        fresh = self.service.login(
            "ops-carol", PASS, account_b.account_id, origin=ORIGIN
        )
        self.assertTrue(fresh.token)
        audits = [
            r
            for r in self.rows("auth_audit_outbox")
            if r["payload"]["action"] == "auth_ops_changed"
            and r["payload"]["details"]["kind"] == "quarantine"
        ]
        self.assertGreaterEqual(len(audits), 2)

    # -- lockdown ------------------------------------------------------------

    def test_lockdown_denies_entries_but_not_live_sessions(self):
        from apps.api.authentication.demo import DemoService
        from apps.api.authentication.email_challenges import EmailChallengeService
        from apps.api.authentication.oidc import OidcService

        person, account, token = self.person("ops-dave")
        email = EmailChallengeService(store=self.store, clock=lambda: self.now)
        oidc = OidcService(store=self.store, clock=lambda: self.now)
        demo = DemoService(store=self.store, clock=lambda: self.now)
        with patch.dict(os.environ, {"CISSTAT_AUTH_LOCKDOWN": "1"}):
            self.error(
                lambda: self.service.login(
                    "ops-dave", PASS, account.account_id, origin=ORIGIN
                ),
                503,
                "auth_lockdown",
            )
            self.error(
                lambda: email.start(
                    "trial@example.ru", "trial_login", ORIGIN, "203.0.113.77"
                ),
                503,
                "auth_lockdown",
            )
            self.error(
                lambda: oidc.start("login", ORIGIN, "203.0.113.77"),
                503,
                "auth_lockdown",
            )
            self.error(
                lambda: demo.enter("ops-campaign", "pw", "r1", ORIGIN, "203.0.113.77"),
                503,
                "auth_lockdown",
            )
            # live session still verifies (entry gate only)
            evidence = self.service.verify(token, origin=ORIGIN)
            self.assertEqual(str(evidence.subject_id), str(person.subject_id))
        # lockdown off: entries work again
        issued = self.service.login(
            "ops-dave", PASS, account.account_id, origin=ORIGIN
        )
        self.assertTrue(issued.token)

    # -- mandatory audit delivery ---------------------------------------------

    def test_audit_delivery_idempotent_and_memory_refusal(self):
        from apps.api.security_audit import PostgresAuditSink

        self.person("ops-eve")
        pending = [r for r in self.rows("auth_audit_outbox") if r["delivered_at"] is None]
        self.assertGreaterEqual(len(pending), 1)
        sink = PostgresAuditSink(DSN)
        delivered = self.ops.drain_audit(limit=100, sink=sink)
        self.assertGreaterEqual(delivered, 1)
        self.assertEqual(self.ops.drain_audit(limit=100, sink=sink), 0)
        with self.store.transaction(readonly=True) as tx:
            left = tx.connection.execute(
                "SELECT count(*) AS n FROM auth_audit_outbox WHERE delivered_at IS NULL"
            ).fetchone()["n"]
        self.assertEqual(left, 0)
        # durable sink keeps the audit_id fence: re-append deduplicates
        records = sink.list_recent(limit=200)
        ids = {r["audit_id"] for r in records if r["action"] == "auth_session_changed"}
        self.assertTrue(ids)

    # -- retention ------------------------------------------------------------

    def test_prune_respects_retention_floor(self):
        from datetime import datetime, timezone

        # an old capture beyond retention and a fresh capture within it
        stale_id = uuid4()
        with self.store.transaction() as tx:
            tx.connection.execute(
                """INSERT INTO auth_ops_ledger(table_name,row_id,event,row_image,occurred_at)
                VALUES ('auth_demo_grants',%s,'revoked',jsonb_build_object('status','revoked'),now()-interval '400 days')""",
                (stale_id,),
            )
        campaign_id, admission_id = self.campaign()
        grant_id = self.issue_grant(campaign_id)
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_demo_grants SET status='revoked' WHERE grant_id=%s",
                (grant_id,),
            )
        self.assertEqual(len(self.ledger("auth_demo_grants")), 2)
        result = self.ops.prune_ledger(retention_days="180")
        self.assertEqual(result["pruned"], 1)
        self.assertEqual(self.ops.prune_ledger(retention_days="180")["pruned"], 0)
        self.assertEqual(len(self.ledger("auth_demo_grants")), 1)
        self.assertEqual(self.ledger("auth_demo_grants")[0]["row_id"], grant_id)

    # -- health facts -----------------------------------------------------------

    def test_health_auth_ops_facts(self):
        from apps.api.authentication.ops_health import build_auth_ops_health

        block = build_auth_ops_health(audit_sweeper={"enabled": False}, store=self.store)
        self.assertEqual(block["state"], "ok")
        self.assertEqual(block["schema_version"], VERSION)
        self.assertFalse(block["lockdown"])
        self.assertIn("audit_outbox_pending", block)
        self.assertIn("ledger", block)
        self.assertIn("external_entry", block)
        degraded = build_auth_ops_health(audit_sweeper={})
        self.assertEqual(degraded["state"], "degraded")
        self.assertIn("detail", degraded)
        with patch.dict(os.environ, {"CISSTAT_AUTH_LOCKDOWN": "1"}):
            block = build_auth_ops_health(audit_sweeper={}, store=self.store)
            self.assertTrue(block["lockdown"])


if __name__ == "__main__":
    unittest.main()
