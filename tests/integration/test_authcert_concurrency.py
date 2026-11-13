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
                # Entry contract: prepare issues the resume cookie the
                # enter endpoint requires (resume_digest refuses bare
                # enter with 401).
                Deployment.post(client, "/v1/auth/demo/prepare")
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
        # One winner; the losers are refused on the consumed code (409
        # admission_consumed — the same replay contract as the serial case).
        self.assertEqual(sorted(outcomes), [200, 409, 409, 409])
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
        login = "cert-cu13-" + H.suffix()
        account = self.dep.personal_user(login, plan="professional")[1]
        self.dep.issue_purchased(account.account_id, 100_000)
        # Native AUTH-12/21 trusted path: the coordinator reserve itself
        # pins the wallet; concurrent reserves race for the last units.
        ctx = self.dep.api_reservation_ctx(login, account)

        def reserve(tag):
            try:
                self.dep.reserve_start(ctx, cu=80_000, key="cert-ac13-" + tag)
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
        login = "cert-spend10-" + H.suffix()
        account = self.dep.personal_user(login, plan="professional")[1]
        self.dep.issue_purchased(account.account_id, 50_000)
        # Trusted path: reserve→start pins the hold; the settle race runs
        # on the coordinator's version CAS (the same expected_version).
        ctx = self.dep.api_reservation_ctx(login, account)
        receipt = self.dep.reserve_start(ctx, cu=20_000, key="cert-s10-reserve")
        from apps.api.billing.coordinator import ReservationCoordinator

        coordinator = ReservationCoordinator(self.dep.store)
        with self.dep.store.transaction(readonly=True) as tx:
            version = tx.connection.execute(
                "SELECT version FROM auth_reservations WHERE reservation_id=%s",
                (receipt.reservation_id,),
            ).fetchone()["version"]

        def settle(_):
            try:
                coordinator.settle(
                    receipt.reservation_id,
                    expected_version=version,
                    actual_cu=12_345,
                )
                return "ok"
            except Exception as exc:
                detail = getattr(exc, "detail", None)
                return detail.get("code") if detail else type(exc).__name__

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(settle, range(2)))
        self.assertEqual(outcomes.count("ok"), 2)  # second pass is an idempotent replay
        lot = [
            r
            for r in self.dep.rows("auth_wallet_lots")
            if r["account_id"] == account.account_id
        ][0]
        self.assertEqual(lot["spent"], 12_345)
        # Conservation is exact: a doubled settle would break the sum.
        self.assertEqual(
            lot["available"]
            + lot["reserved"]
            + lot["spent"]
            + lot["expired"]
            + lot["refunded"],
            50_000,
        )

    # ------------------------------------ AC26 invitation replay (service)

    def test_ac26_invitation_replay_creates_no_second_membership(self):
        from apps.api.accounts.team import TeamService
        from apps.api.accounts.team_contract import Accept, Invite
        from apps.api.authentication.sessions import SessionService

        owner_login = "cert-seat26-owner-" + H.suffix()
        # Team operations need a MULTI account (native AUTH-17 provisioning).
        owner_identity, account = self.dep.multi_user(owner_login, seats=2)
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
        # The replayed accept is IDEMPOTENT for the same guest (the token
        # is consumed, the membership exists) — and never mints a second one.
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
                "SELECT count(*) AS n FROM auth_memberships WHERE account_id=%s AND status='active'",
                (account.account_id,),
            ).fetchone()["n"]
        self.assertEqual(members, 2)  # owner + exactly one accepted guest
