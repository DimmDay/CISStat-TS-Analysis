"""AUTH-CERT concurrency suite: races never double-spend or double-admit.

AC12/AC13/AC14/AC26 and §10 "Одновременные invite/seat/CU admission ...
не создают двойной расход или бесплатный результат". Races run on real
threads (HTTP and PostgreSQL levels); correctness is asserted from database
state, never from timings.
"""

import concurrent.futures
import os
import unittest
from uuid import uuid4

from tests.integration import authcert_harness as H
from tests.integration.authcert_harness import Deployment, STANDALONE

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires CISSTAT_AUTH_TEST_DSN")
class CertConcurrencyTests(unittest.TestCase):
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

    # ------------------------------------------------- AC12 code race (HTTP)

    def test_ac12_admission_code_parallel_enter_single_redemption(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client,
                alias="cert-race12-" + H.suffix(),
                require_admission=True,
                max_grants=4,
            )
            code = self.dep.admission_codes(admin_client, campaign, 1)[0]
            alias, secret = campaign["alias"], campaign["secret"]

        def enter(_):
            with self.dep.http() as client:
                response = Deployment.post(
                    client,
                    "/v1/auth/demo/enter",
                    json={
                        "login": alias,
                        "password": secret,
                        "admission_code": code,
                    },
                )
                return response.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(enter, range(4)))
        self.assertEqual(sorted(outcomes), [200, 401, 401, 401])
        redeemed = [
            r
            for r in self.dep.rows("auth_demo_admissions")
            if r["redeemed_at"] is not None
        ]
        self.assertEqual(len(redeemed), 1)
        with self.dep.store.transaction(readonly=True) as tx:
            grants = tx.connection.execute(
                "SELECT count(*) AS n FROM auth_demo_grants"
            ).fetchone()["n"]
        self.assertEqual(grants, 1)

    # ------------------------------------------- AC14 idempotent retry (HTTP)

    def test_ac14_idempotent_retry_same_result_conflict_on_payload(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client, alias="cert-idem14-" + H.suffix()
            )
            alias, secret = campaign["alias"], campaign["secret"]
        with self.dep.http() as participant:
            Deployment.enter(participant, alias, secret)
            Deployment.upload(participant)
            headers = {
                "Origin": STANDALONE,
                "X-CSRF-Token": Deployment.csrf(participant),
                "Idempotency-Key": "cert-idem-14",
            }
            first = participant.post(
                "/v1/session/date-column",
                json={"column": "date", "confirmed": True},
                headers=headers,
            )
            self.assertEqual(first.status_code, 200, first.text)
            replay = participant.post(
                "/v1/session/date-column",
                json={"column": "date", "confirmed": True},
                headers=headers,
            )
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(first.json(), replay.json())
            conflict = participant.post(
                "/v1/session/date-column",
                json={"column": "another", "confirmed": True},
                headers=headers,
            )
            self.assertEqual(conflict.status_code, 409, conflict.text)

    # ---------------------------------- AC13 last units race (wallet, PG)

    def test_ac13_last_units_race_exactly_one_winner(self):
        import psycopg

        from apps.api.billing.wallet import (
            WalletError,
            allocate_for_reservation,
        )

        account = self.dep.personal_user("cert-cu13-" + H.suffix(), plan="professional")[1]
        self.dep.issue_purchased(account.account_id, 100_000)
        rid = uuid4()
        now = self.dep.now

        def reserve(tag):
            try:
                with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
                    allocate_for_reservation(
                        conn, account.account_id, rid, 80_000, now
                    )
                    conn.commit()
                return "ok"
            except Exception as exc:
                detail = getattr(exc, "detail", None)
                return detail.get("code") if detail else type(exc).__name__

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, ("a", "b")))
        self.assertEqual(sorted(outcomes), ["cu_insufficient", "ok"])
        available = [
            r["available"]
            for r in self.dep.rows("auth_wallet_lots")
            if r["account_id"] == account.account_id
        ][0]
        self.assertEqual(available, 20_000)

    # ------------------------------- §10 settle race never doubles charge

    def test_s10_concurrent_settle_never_doubles_charge(self):
        import psycopg

        from apps.api.billing.wallet import (
            allocate_for_reservation,
            settle_reservation,
        )

        account = self.dep.personal_user("cert-spend10-" + H.suffix(), plan="professional")[1]
        self.dep.issue_purchased(account.account_id, 50_000)
        rid = uuid4()
        now = self.dep.now
        with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
            allocate_for_reservation(conn, account.account_id, rid, 20_000, now)
            conn.commit()

        def settle(_):
            with psycopg.connect(self.dep.dsn, row_factory=psycopg.rows.dict_row) as conn:
                settle_reservation(conn, account.account_id, rid, 12_345, now)
                conn.commit()
            return "ok"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(settle, range(2)))
        self.assertEqual(outcomes.count("ok"), 2)  # second pass is a no-op
        lot = [
            r
            for r in self.dep.rows("auth_wallet_lots")
            if r["account_id"] == account.account_id
        ][0]
        self.assertEqual(lot["spent"], 12_345)
        self.assertEqual(lot["available"], 37_655)

    # ------------------------------------ AC26 invitation replay (service)

    def test_ac26_invitation_replay_creates_no_second_membership(self):
        from apps.api.accounts.team import TeamService
        from apps.api.accounts.team_contract import Accept, Invite
        from apps.api.authentication.sessions import SessionService

        owner_login = "cert-seat26-owner-" + H.suffix()
        owner_identity, account = self.dep.personal_user(owner_login)
        guest_login = "cert-seat26-guest-" + H.suffix()
        guest_identity, _ = self.dep.personal_user(guest_login)
        sessions = SessionService(self.dep.store)
        owner = sessions.login(
            owner_login, H.PASS, account.account_id, origin=STANDALONE
        )
        team = TeamService(self.dep.store)
        with self.dep.store.transaction(readonly=True) as tx:
            version = tx.connection.execute(
                "SELECT entitlement_version AS version FROM auth_accounts WHERE account_id=%s",
                (account.account_id,),
            ).fetchone()["version"]
        issued = team.invite(
            owner.token,
            STANDALONE,
            account.account_id,
            Invite(
                target_subject_id=guest_identity.subject_id,
                expected_version=version,
                reason="cert invite",
                idempotency_key="cert-invite-26",
            ),
        )
        token = issued["invitation_token"]
        # The guest logs into their own account (identity owns exactly one).
        guest = sessions.login(
            guest_login, H.PASS, None, origin=STANDALONE
        )
        accept = team.accept(
            guest.token,
            STANDALONE,
            Accept(
                invitation_token=token,
                idempotency_key="cert-accept-26",
                reason="cert accept",
            ),
        )
        self.assertTrue(accept)
        with self.assertRaises(Exception) as replayed:
            team.accept(
                guest.token,
                STANDALONE,
                Accept(
                    invitation_token=token,
                    idempotency_key="cert-accept-26-b",
                    reason="replay attempt",
                ),
            )
        with self.dep.store.transaction(readonly=True) as tx:
            members = tx.connection.execute(
                "SELECT count(*) AS n FROM auth_account_members WHERE account_id=%s",
                (account.account_id,),
            ).fetchone()["n"]
        self.assertEqual(members, 2)  # owner + exactly one accepted guest
