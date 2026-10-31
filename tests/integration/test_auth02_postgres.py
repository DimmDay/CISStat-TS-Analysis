"""AUTH-02 real PostgreSQL contract; no SQLite/fake connection assertions."""

import os
from pathlib import Path
import sys
import subprocess
import unittest
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(
    DSN, "Set CISSTAT_AUTH_TEST_DSN; mandatory runner rejects a missing DSN"
)
class PostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from apps.api.authentication.storage import PostgresAccessStore

        self.pg = psycopg
        self.sql = sql
        self.schema = "auth02_" + uuid4().hex
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema))
            )
        self.addCleanup(self.cleanup)
        self.store = PostgresAccessStore(DSN, schema=self.schema)
        self.assertTrue(self.store.migrate())

    def cleanup(self):
        with self.pg.connect(DSN, autocommit=True) as conn:
            conn.execute(
                self.sql.SQL("DROP SCHEMA {} CASCADE").format(
                    self.sql.Identifier(self.schema)
                )
            )

    def seed(self, kind="mono", seats=1):
        with self.store.transaction() as tx:
            owner = tx.identities.create()
            account = tx.accounts.create(
                owner.subject_id, account_type=kind, seats=seats
            )
        return owner, account

    def test_roundtrip_same_email_not_identity_merge(self):
        with self.store.transaction() as tx:
            a = tx.identities.create()
            b = tx.identities.create()
            tx.identities.link_external(
                a.subject_id,
                "https://issuer",
                "opaque-A",
                email="same@example.test",
                email_verified=True,
            )
            tx.identities.link_external(
                b.subject_id,
                "https://issuer",
                "opaque-B",
                email="same@example.test",
                email_verified=True,
            )
        with self.store.transaction(readonly=True) as tx:
            self.assertEqual(tx.identities.get(a.subject_id), a)
            self.assertEqual(
                tx.identities.by_external("https://issuer", "opaque-B").subject_id,
                b.subject_id,
            )
            self.assertEqual(len(tx.identities.external_identities(a.subject_id)), 1)
            self.assertIsNone(tx.identities.by_external("https://ISSUER", "opaque-A"))

    def test_issuer_sub_unique_and_conflict_rolls_back_whole_transaction(self):
        from apps.api.authentication.errors import RepositoryConflict

        with self.store.transaction() as tx:
            a = tx.identities.create()
            b = tx.identities.create()
            tx.identities.link_external(a.subject_id, "issuer", "sub")
        with self.assertRaises(RepositoryConflict):
            with self.store.transaction() as tx:
                extra = tx.identities.create()
                tx.identities.link_external(b.subject_id, "issuer", "sub")
        with self.store.transaction() as tx:
            self.assertIsNone(tx.identities.get(extra.subject_id))
            self.assertEqual(
                tx.identities.by_external("issuer", "sub").subject_id, a.subject_id
            )

    def test_cross_repository_rollback_and_no_inner_commit(self):
        with self.assertRaisesRegex(RuntimeError, "injected"):
            with self.store.transaction() as tx:
                identity = tx.identities.create()
                account = tx.accounts.create(identity.subject_id)
                raise RuntimeError("injected after identity/account/member")
        with self.store.transaction() as tx:
            self.assertIsNone(tx.identities.get(identity.subject_id))
            self.assertIsNone(tx.accounts.get(account.account_id))

    def test_unique_subject_membership_and_foreign_keys_on_server(self):
        from apps.api.authentication.errors import RepositoryConflict

        owner, account = self.seed("multi", 2)
        statements = [
            (
                "INSERT INTO auth_identities(subject_id) VALUES (%s)",
                (owner.subject_id,),
            ),
            (
                "INSERT INTO auth_memberships(account_id,subject_id,account_role) VALUES (%s,%s,'member')",
                (account.account_id, owner.subject_id),
            ),
            (
                "INSERT INTO auth_memberships(account_id,subject_id,account_role) VALUES (%s,%s,'member')",
                (account.account_id, uuid4()),
            ),
        ]
        for query, args in statements:
            with self.assertRaises(RepositoryConflict):
                with self.store.transaction() as tx:
                    tx.connection.execute(query, args)

    def test_mono_exactly_one_owner_and_no_empty_account_commit(self):
        from apps.api.authentication.errors import RepositoryConflict

        owner, account = self.seed()
        with self.store.transaction() as tx:
            other = tx.identities.create()
        for query, args in [
            ("DELETE FROM auth_memberships WHERE account_id=%s", (account.account_id,)),
            (
                "UPDATE auth_memberships SET account_role='member' WHERE account_id=%s",
                (account.account_id,),
            ),
            (
                "INSERT INTO auth_memberships(account_id,subject_id,account_role) VALUES (%s,%s,'member')",
                (account.account_id, other.subject_id),
            ),
            (
                "INSERT INTO auth_accounts(account_id,tenant_id) VALUES (%s,%s)",
                (uuid4(), uuid4()),
            ),
        ]:
            with self.assertRaises(RepositoryConflict):
                with self.store.transaction() as tx:
                    tx.connection.execute(query, args)

    def test_member_and_owner_not_platform_admin(self):
        owner, account = self.seed()
        self.assertEqual(owner.platform_role, "external_user")
        with self.store.transaction() as tx:
            self.assertEqual(
                tx.accounts.memberships(account.account_id)[0].account_role, "owner"
            )
            self.assertEqual(
                tx.identities.get(owner.subject_id).platform_role, "external_user"
            )

    def test_closed_status_cannot_bypass_last_owner_invariant(self):
        from apps.api.authentication.errors import RepositoryConflict

        owner, account = self.seed()
        with self.assertRaises(RepositoryConflict):
            with self.store.transaction() as tx:
                closed = tx.accounts.update(
                    account.account_id,
                    expected_version=account.entitlement_version,
                    status="closed",
                )
                tx.accounts.update_member(
                    account.account_id,
                    owner.subject_id,
                    expected_version=closed.entitlement_version,
                    status="revoked",
                )

    def test_immutable_ids_and_tenant_binding(self):
        from apps.api.authentication.errors import RepositoryConflict

        owner, account = self.seed()
        for query, args in [
            (
                "UPDATE auth_identities SET subject_id=%s WHERE subject_id=%s",
                (uuid4(), owner.subject_id),
            ),
            (
                "UPDATE auth_accounts SET tenant_id=%s,entitlement_version=entitlement_version+1 WHERE account_id=%s",
                (uuid4(), account.account_id),
            ),
            (
                "UPDATE auth_memberships SET subject_id=%s WHERE account_id=%s",
                (uuid4(), account.account_id),
            ),
        ]:
            with self.assertRaises(RepositoryConflict):
                with self.store.transaction() as tx:
                    tx.connection.execute(query, args)

    def test_mono_multi_keeps_ids_and_cas_rejects_stale_writer(self):
        from apps.api.authentication.errors import VersionConflict

        owner, account = self.seed()
        with self.store.transaction() as tx:
            multi = tx.accounts.update(
                account.account_id,
                expected_version=account.entitlement_version,
                account_type="multi",
                seats=2,
            )
            other = tx.identities.create()
            tx.accounts.add_member(
                account.account_id,
                other.subject_id,
                expected_version=multi.entitlement_version,
            )
        with self.assertRaises(VersionConflict):
            with self.store.transaction() as tx:
                tx.accounts.update(
                    account.account_id,
                    expected_version=account.entitlement_version,
                    plan="professional",
                )
        with self.store.transaction() as tx:
            actual = tx.accounts.get(account.account_id)
            self.assertEqual(actual.tenant_id, account.tenant_id)
            self.assertEqual(actual.account_type, "multi")
            self.assertEqual(actual.plan, "demo")
            self.assertGreater(actual.entitlement_version, multi.entitlement_version)

    def test_concurrent_last_seat_cannot_overbook(self):
        from apps.api.authentication.errors import RepositoryConflict

        _, account = self.seed("multi", 2)
        with self.store.transaction() as tx:
            people = [tx.identities.create().subject_id for _ in range(2)]
        start = Barrier(2)

        def add(subject):
            start.wait(timeout=10)
            try:
                with self.store.transaction() as tx:
                    tx.connection.execute(
                        "INSERT INTO auth_memberships(account_id,subject_id,account_role) VALUES (%s,%s,'member')",
                        (account.account_id, subject),
                    )
                return True
            except RepositoryConflict:
                return False

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(add, people))
        self.assertEqual(sorted(results), [False, True])
        with self.store.transaction() as tx:
            self.assertEqual(len(tx.accounts.memberships(account.account_id)), 2)

    def test_concurrent_last_owners_cannot_both_demote(self):
        from apps.api.authentication.errors import RepositoryConflict

        owner, account = self.seed("multi", 2)
        with self.store.transaction() as tx:
            other = tx.identities.create()
            tx.accounts.add_member(
                account.account_id,
                other.subject_id,
                expected_version=account.entitlement_version,
                account_role="owner",
            )
        start = Barrier(2)

        def demote(subject):
            start.wait(timeout=10)
            try:
                with self.store.transaction() as tx:
                    tx.connection.execute(
                        "UPDATE auth_memberships SET account_role='member' WHERE account_id=%s AND subject_id=%s",
                        (account.account_id, subject),
                    )
                return True
            except RepositoryConflict:
                return False

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(demote, [owner.subject_id, other.subject_id]))
        self.assertEqual(sorted(results), [False, True])

    def test_identity_revoke_version_and_account_suspend_survive_new_repository(self):
        from apps.api.authentication.storage import PostgresAccessStore

        owner, account = self.seed()
        with self.store.transaction() as tx:
            tx.identities.set_status(
                owner.subject_id, "suspended", expected_version=owner.subject_version
            )
            tx.accounts.update(
                account.account_id,
                expected_version=account.entitlement_version,
                status="suspended",
            )
        other_store = PostgresAccessStore(DSN, schema=self.schema)
        self.assertTrue(other_store.readiness()["ok"])
        with other_store.transaction() as tx:
            self.assertEqual(tx.identities.get(owner.subject_id).status, "suspended")
            self.assertEqual(tx.identities.get(owner.subject_id).subject_version, 2)
            self.assertEqual(tx.accounts.get(account.account_id).status, "suspended")

    def test_migration_idempotence_checksum_and_transactional_ddl_rollback(self):
        from apps.api.authentication.migrations import apply_migration

        self.assertFalse(self.store.migrate())
        isolated = "auth02_rollback_" + uuid4().hex
        with self.pg.connect(DSN, autocommit=True) as conn:
            conn.execute(
                self.sql.SQL("CREATE SCHEMA {}").format(self.sql.Identifier(isolated))
            )
        try:
            with self.pg.connect(DSN) as conn:
                try:
                    with conn.transaction():
                        conn.execute(
                            self.sql.SQL(
                                "SET LOCAL search_path TO {}, pg_catalog"
                            ).format(self.sql.Identifier(isolated))
                        )
                        apply_migration(conn)
                        raise RuntimeError("rollback DDL")
                except RuntimeError:
                    pass
                self.assertIsNone(
                    conn.execute(
                        "SELECT to_regclass(%s)", (isolated + ".auth_identities",)
                    ).fetchone()[0]
                )
        finally:
            with self.pg.connect(DSN, autocommit=True) as conn:
                conn.execute(
                    self.sql.SQL("DROP SCHEMA {} CASCADE").format(
                        self.sql.Identifier(isolated)
                    )
                )

    def test_downgrade_empty_only_and_reapply(self):
        from apps.api.authentication.errors import RepositoryConflict

        rollback = (ROOT / "scripts/auth02/rollback_0019.sql").read_text(
            encoding="utf-8"
        )
        with self.store.transaction() as tx:
            tx.connection.execute(rollback)
        self.assertTrue(self.store.migrate())
        self.seed()
        with self.assertRaises(RepositoryConflict):
            with self.store.transaction() as tx:
                tx.connection.execute(rollback)

    def test_checksum_mismatch_fails_without_silent_reapply(self):
        from apps.api.authentication.errors import AuthSchemaNotReady

        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_schema_versions SET checksum='corrupted'"
            )
        self.assertFalse(self.store.readiness()["ok"])
        with self.assertRaises(AuthSchemaNotReady):
            self.store.migrate()

    def test_external_binding_cannot_be_reassigned(self):
        from apps.api.authentication.errors import RepositoryConflict

        with self.store.transaction() as tx:
            a = tx.identities.create()
            b = tx.identities.create()
            tx.identities.link_external(a.subject_id, "issuer", "sub")
        with self.assertRaises(RepositoryConflict):
            with self.store.transaction() as tx:
                tx.connection.execute(
                    "UPDATE auth_external_identities SET subject_id=%s WHERE issuer='issuer'",
                    (b.subject_id,),
                )

    def test_new_python_process_observes_committed_records(self):
        owner, account = self.seed()
        code = """import os
from apps.api.authentication.storage import PostgresAccessStore
store=PostgresAccessStore(os.environ['CISSTAT_AUTH_TEST_DSN'],schema=os.environ['AUTH02_TEST_SCHEMA'])
with store.transaction(readonly=True) as tx:
 assert str(tx.identities.by_external('restart-issuer','restart-sub').subject_id)==os.environ['AUTH02_TEST_OWNER']
 assert str(tx.accounts.for_subject(os.environ['AUTH02_TEST_OWNER'])[0].tenant_id)==os.environ['AUTH02_TEST_TENANT']
print('fresh Python process: persisted identity/account/tenant OK')
"""
        with self.store.transaction() as tx:
            tx.identities.link_external(
                owner.subject_id, "restart-issuer", "restart-sub"
            )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env={
                **os.environ,
                "AUTH02_TEST_SCHEMA": self.schema,
                "AUTH02_TEST_OWNER": str(owner.subject_id),
                "AUTH02_TEST_TENANT": str(account.tenant_id),
            },
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_existing_scientific_migrations_remain_usable_and_untouched(self):
        with self.store.transaction() as tx:
            for path in sorted((ROOT / "apps/api/migrations").glob("*.sql")):
                if int(path.name[:4]) > 18:
                    continue
                tx.connection.execute(path.read_text(encoding="utf-8"), prepare=False)
            tx.connection.execute(
                """INSERT INTO research_runs(run_id,session_id,dataset_fingerprint,dataset_name,
                target_column,created_at,last_active_at,status) VALUES
                ('auth02-legacy','legacy-session','digest','fixture','y',now(),now(),'active')"""
            )
        self.assertFalse(self.store.migrate())
        with self.store.transaction() as tx:
            self.assertEqual(
                tx.connection.execute(
                    "SELECT session_id FROM research_runs WHERE run_id='auth02-legacy'"
                ).fetchone()["session_id"],
                "legacy-session",
            )


if __name__ == "__main__":
    unittest.main()
