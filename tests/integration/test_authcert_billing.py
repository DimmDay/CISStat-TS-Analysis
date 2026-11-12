"""AUTH-CERT billing suite: cross-stage wallet invariants (spec §12.5).

Financial composition oracles no single task owned: seat churn never mints
credit, refund hold blocks spend, expiry sweep is honest, MEMBER privacy
through the real HTTP surface, integer exactness at scale. Money moves only
through trusted provisioning (no provider/network in this environment).
"""

import os
import unittest
from uuid import uuid4

from tests.integration import authcert_harness as H
from tests.integration.authcert_harness import Deployment, STANDALONE

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires CISSTAT_AUTH_TEST_DSN")
class CertBillingTests(unittest.TestCase):
    dep = None
    admin = None

    @classmethod
    def setUpClass(cls):
        cls.dep = Deployment()
        with cls.dep.http() as client:
            body, rec = cls.dep.admin_client(client)
        cls.admin = rec

    @classmethod
    def tearDownClass(cls):
        cls.dep.stop()

    def admin_login(self, client):
        return self.dep.admin_relogin(
            client, self.admin["login"], self.admin["seed"]
        )

    def lots(self, account_id):
        return [
            r
            for r in self.dep.rows("auth_wallet_lots")
            if r["account_id"] == account_id
        ]

    # --------------------------------------- §12.5 seat churn keeps ledger

    def test_seat_churn_never_creates_credit_and_privacy_holds(self):
        from apps.api.accounts.team import TeamService
        from apps.api.accounts.team_contract import Accept, Invite
        from apps.api.authentication.sessions import SessionService

        owner_login = "cert-bill-owner-" + H.suffix()
        owner_identity, account = self.dep.personal_user(owner_login)
        wallet, lot = self.dep.issue_purchased(account.account_id, 10_000_000)
        before = self.lots(account.account_id)
        guest_login = "cert-bill-guest-" + H.suffix()
        guest_identity, guest_account = self.dep.personal_user(guest_login)
        sessions = SessionService(self.dep.store)
        owner = sessions.login(
            owner_login, H.PASS, account.account_id, origin=STANDALONE
        )
        guest = sessions.login(guest_login, H.PASS, None, origin=STANDALONE)
        team = TeamService(self.dep.store)
        with self.dep.store.transaction(readonly=True) as tx:
            version = tx.connection.execute(
                "SELECT version FROM auth_accounts WHERE account_id=%s",
                (account.account_id,),
            ).fetchone()["version"]
        issued = team.invite(
            owner.token,
            STANDALONE,
            account.account_id,
            Invite(
                target_subject_id=guest_identity.subject_id,
                expected_version=version,
                reason="cert billing seat",
                idempotency_key="cert-bill-seat",
            ),
        )
        team.accept(
            guest.token,
            STANDALONE,
            Accept(
                invitation_token=issued["invitation_token"],
                idempotency_key="cert-bill-accept",
                reason="cert billing accept",
            ),
        )
        # Seat churn minted no credit: the ledger is byte-identical.
        self.assertEqual(self.lots(account.account_id), before)
        # MEMBER privacy through the real HTTP surface: the guest sees a
        # usage projection, never sources/ledger/money.
        with self.dep.http() as owner_client, self.dep.http() as guest_client:
            Deployment.login(owner_client, owner_login)
            Deployment.login(guest_client, guest_login)
            path = f"/v1/billing/{account.account_id}/wallet"
            owner_view = owner_client.get(path, headers={"Origin": STANDALONE})
            self.assertEqual(owner_view.status_code, 200, owner_view.text)
            guest_view = guest_client.get(path, headers={"Origin": STANDALONE})
            self.assertEqual(guest_view.status_code, 200, guest_view.text)
            import json as json_module

            guest_body = json_module.dumps(guest_view.json()).lower()
            self.assertNotIn("purchased", guest_body)
            self.assertNotIn("promotional", guest_body)
            ledger = guest_client.get(
                path + "/ledger", headers={"Origin": STANDALONE}
            )
            self.assertEqual(ledger.status_code, 403)
            owner_ledger = owner_client.get(
                path + "/ledger", headers={"Origin": STANDALONE}
            )
            self.assertEqual(owner_ledger.status_code == 200, True, owner_ledger.text)

    # --------------------- whole-lot refund hold blocks spend; release paths

    def test_refund_hold_blocks_spend_and_release_paths_are_exclusive(self):
        import psycopg

        from apps.api.billing.wallet import (
            allocate_for_reservation,
            refund_hold_in_tx,
            refund_release_in_tx,
        )

        account = self.dep.personal_user("cert-bill-refund-" + H.suffix(), plan="professional")[1]
        self.dep.issue_purchased(account.account_id, 500_000)

        def locked_row(conn):
            return conn.execute(
                "SELECT * FROM auth_wallet_lots WHERE account_id=%s FOR UPDATE",
                (account.account_id,),
            ).fetchone()

        # Self-service hold on the whole lot: spend cannot touch held CU.
        with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
            refund_hold_in_tx(conn, locked_row(conn), reason="cert hold")
            conn.commit()
        rid = uuid4()
        with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
            with self.assertRaises(Exception) as refused:
                allocate_for_reservation(
                    conn, account.account_id, rid, 400_000, self.dep.now
                )
            detail = getattr(refused.exception, "detail", None)
            code = detail.get("code") if detail else None
            self.assertIn(code, ("cu_insufficient", "wallet_locked"))
            conn.rollback()
        # Honest provider failure releases the hold back to available.
        with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
            refund_release_in_tx(
                conn, locked_row(conn), "refund_failed", reason="cert failed"
            )
            conn.commit()
        row = self.lots(account.account_id)[0]
        self.assertEqual(row["available"], 500_000)
        self.assertEqual(row["refund_pending"], 0)
        # The spend that was refused during the hold now succeeds.
        with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
            allocate_for_reservation(
                conn, account.account_id, rid, 400_000, self.dep.now
            )
            conn.commit()
        row = self.lots(account.account_id)[0]
        self.assertEqual(row["reserved"], 400_000)
        self.assertEqual(row["available"], 100_000)

    # ------------------------------------- integer exactness at scale (E1)

    def test_integer_split_exactness_at_giant_scale(self):
        import psycopg

        from apps.api.billing.wallet import (
            allocate_for_reservation,
            settle_reservation,
        )

        account = self.dep.personal_user("cert-bill-big-" + H.suffix(), plan="professional")[1]
        units = 10 ** 12  # catalog ceiling: 1e12 micro-CU
        self.dep.issue_purchased(account.account_id, units)
        rid = uuid4()
        with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
            allocate_for_reservation(conn, account.account_id, rid, 999_999_999_999, self.dep.now)
            conn.commit()
        with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
            settle_reservation(conn, account.account_id, rid, 777_777_777_777, self.dep.now)
            conn.commit()
        row = self.lots(account.account_id)[0]
        self.assertEqual(row["issued"], units)
        self.assertEqual(row["spent"], 777_777_777_777)
        self.assertEqual(row["available"], units - 777_777_777_777)

    # ---------------------------------------- expired included never revives

    def test_expiry_sweep_honest_and_no_revival(self):
        """Balanced included-lot inserts follow the 0033 invariant (the same
        restore-artifact shape AUTH-25 fixtures use); the sweep is the real
        trusted command."""
        import psycopg
        from datetime import timedelta
        from uuid import uuid4 as new_uuid

        from apps.api.billing.wallet import WalletService

        account = self.dep.personal_user("cert-bill-exp-" + H.suffix(), plan="professional")[1]
        wallet = self.dep.wallet(account.account_id)
        self.dep.issue_purchased(account.account_id, 100_000)

        def insert_included(expires_at, units):
            lot_id = new_uuid()
            with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
                conn.execute(
                    "INSERT INTO auth_wallet_lots(lot_id,wallet_id,account_id,source,"
                    "issued,available,expires_at,version,created_at) "
                    "VALUES (%s,%s,%s,'included',%s,%s,%s,1,%s)",
                    (
                        lot_id,
                        conn.execute(
                            "SELECT wallet_id FROM auth_wallets WHERE account_id=%s",
                            (account.account_id,),
                        ).fetchone()["wallet_id"],
                        account.account_id,
                        units,
                        units,
                        expires_at,
                        self.dep.now,
                    ),
                )
                conn.commit()

        insert_included(self.dep.now - timedelta(minutes=1), 250_000)
        wallet.sweep_expiry(reason="cert sweep", now=self.dep.now)
        rows = {r["source"]: r for r in self.lots(account.account_id)}
        self.assertEqual(rows["included"]["expired"], 250_000)
        self.assertEqual(rows["included"]["available"], 0)
        self.assertEqual(rows["purchased"]["available"], 100_000)
        # A new cycle's included is fresh credit; the expired lot never revives.
        insert_included(self.dep.now + timedelta(hours=1), 300_000)
        rows = {r["source"]: r for r in self.lots(account.account_id)}
        self.assertEqual(rows["included"]["expired"], 250_000)
        self.assertEqual(rows["included"]["available"], 300_000)
