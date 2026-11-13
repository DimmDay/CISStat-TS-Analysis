"""AUTH-CERT failures suite: unavailable authority, audit faults, restore.

AC19/AC20/AC27 and §10 "ENV removal / key rotation / backup restore сохраняют
доказанное владение и не воскрешают отзыв". Faults affect only disposable
test stores; the live HTTP surface must answer honestly (503 without
anonymous fallback, fail-closed refusal, no resurrection after restart).
"""

import os
import unittest
from unittest import mock

from tests.integration import authcert_harness as H
from tests.integration.authcert_harness import Deployment, PASS, STANDALONE

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires CISSTAT_AUTH_TEST_DSN")
class CertFailureTests(unittest.TestCase):
    dep = None
    admin = None

    @classmethod
    def setUpClass(cls):
        cls.dep = Deployment()
        with cls.dep.http() as client:
            body, rec = cls.dep.admin_client(client)
        cls.admin = {"seed": rec["seed"], "login": rec["login"], "password": PASS}

    @classmethod
    def tearDownClass(cls):
        cls.dep.stop()

    def admin_login(self, client):
        return self.dep.admin_relogin(
            client, self.admin["login"], self.admin["seed"]
        )

    # ---------------------------------------------------------------- AC19

    def test_ac19_unavailable_authority_503_no_anonymous_fallback(self):
        from apps.api.authentication.storage import PostgresAccessStore

        login = "cert-ac19-" + H.suffix()
        self.dep.personal_user(login)
        with self.dep.http() as client:
            Deployment.login(client, login)
            broken = PostgresAccessStore(
                "postgresql://postgres:@/missing_cert_db?host=/nonexistent-sock"
            )
            import apps.api.main as main_module

            real = main_module.app.state.auth_access_store
            main_module.app.state.auth_access_store = broken
            try:
                # An authenticated request during the outage answers 503.
                refused = client.get(
                    "/v1/auth/me", headers={"Origin": STANDALONE}
                )
                self.assertEqual(refused.status_code, 503)
                self.assertEqual(
                    refused.json()["detail"]["code"],
                    "auth_authority_unavailable",
                )
                # Anonymous callers get no fallback success either.
                client.cookies.clear()
                anonymous = client.get(
                    "/v1/auth/me", headers={"Origin": STANDALONE}
                )
                self.assertEqual(anonymous.status_code, 401)
            finally:
                main_module.app.state.auth_access_store = real
            recovered = client.get(
                "/v1/auth/csrf",
                headers={"Origin": STANDALONE, "X-CSRF-Request": "1"},
            )
            self.assertEqual(recovered.status_code, 200)

    # ---------------------------------------------------------------- AC20

    def test_ac20_audit_fault_leaves_no_unaccounted_change(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            from apps.api.authentication import demo as demo_module

            before = len(self.dep.rows("auth_demo_campaigns"))
            with mock.patch.object(
                demo_module, "audit", side_effect=RuntimeError("audit down")
            ):
                refused = Deployment.post(
                    admin_client,
                    "/v1/admin/demo-campaigns",
                    json={
                        "alias": "cert-fault-" + H.suffix(),
                        "policy": self._policy(),
                        "reason": "audit fault attempt",
                    },
                )
            self.assertEqual(refused.status_code, 503, refused.text)
            after = len(self.dep.rows("auth_demo_campaigns"))
            self.assertEqual(after, before)
            # Retry after the fault is consistent: the same command succeeds.
            ok = Deployment.post(
                admin_client,
                "/v1/admin/demo-campaigns",
                json={
                    "alias": "cert-fault-" + H.suffix(),
                    "policy": self._policy(),
                    "reason": "audit recovered",
                },
            )
            self.assertEqual(ok.status_code, 200, ok.text)

    def _policy(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        return {
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "grant_minutes": 60,
            "max_grants": 10,
            "campaign_cu": 1000000,
            "participant_cu": 100000,
            "campaign_concurrency": 2,
            "participant_concurrency": 1,
            "campaign_analyses": 10,
            "participant_analyses": 2,
            "max_rows": 5000,
            "allow_upload": True,
            "allowed_origins": [H.STANDALONE, H.EMBEDDED],
        }

    # ---------------------------------------------------------------- AC27

    def test_ac27_restart_does_not_resurrect_revocations(self):
        login = "cert-ac27-" + H.suffix()
        self.dep.personal_user(login)
        with self.dep.http() as client:
            Deployment.login(client, login)
            Deployment.post(client, "/v1/auth/logout")
        # "Restart": a fresh HTTP context reopens every durable store.
        with self.dep.http() as client:
            # The logged-out session stays revoked; the token is dead.
            client.cookies.set(
                "__Host-cisstat_auth", "x" * 60, domain="datasetup.ru"
            )
            self.assertEqual(
                client.get("/v1/auth/me", headers={"Origin": STANDALONE}).status_code,
                401,
            )
        # A consumed admission code stays consumed across the restart.
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client,
                alias="cert-ac27c-" + H.suffix(),
                require_admission=True,
                max_grants=2,
            )
            code = self.dep.admission_codes(admin_client, campaign, 1)[0]
            alias, secret = campaign["alias"], campaign["secret"]
        with self.dep.http() as winner:
            Deployment.enter(winner, alias, secret, code=code)
        with self.dep.http() as challenger:
            Deployment.post(challenger, "/v1/auth/demo/prepare")
            replay = Deployment.post(
                challenger,
                "/v1/auth/demo/enter",
                json={
                    "login": alias,
                    "password": secret,
                    "admission_code": code,
                },
            )
            self.assertEqual(replay.status_code, 409, replay.text)
            self.assertEqual(
                replay.json()["detail"]["code"], "admission_consumed"
            )
        redeemed = [
            r
            for r in self.dep.rows("auth_demo_admissions")
            if r["redeemed_at"] is not None
        ]
        self.assertEqual(len(redeemed), 1)

    # ------------------------------------------- §10 rotation and lockdown

    def test_s10_credential_rotation_kills_old_secret(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client, alias="cert-rot-" + H.suffix()
            )
            alias, secret, cid = (
                campaign["alias"],
                campaign["secret"],
                campaign["campaign_id"],
            )
            version = campaign["policy_version"]
        rotated = None
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            rotated = Deployment.post(
                admin_client,
                f"/v1/admin/demo-campaigns/{cid}/rotate-credential",
                json={
                    "expected_version": version,
                    "reason": "cert rotation",
                },
            )
            self.assertEqual(rotated.status_code == 200, True, rotated.text)
            new_secret = rotated.json()["secret"]
        with self.dep.http() as participant:
            Deployment.post(participant, "/v1/auth/demo/prepare")
            old = Deployment.post(
                participant,
                "/v1/auth/demo/enter",
                json={"login": alias, "password": secret},
            )
            self.assertEqual(old.status_code, 401)
            fresh = Deployment.post(
                participant,
                "/v1/auth/demo/enter",
                json={"login": alias, "password": new_secret},
            )
            self.assertEqual(fresh.status_code == 200, True, fresh.text)

    def test_s10_lockdown_and_csrf_key_removal_fail_closed(self):
        with self.dep.http() as client:
            import apps.api.main as main_module

            # Lockdown closes the password entry before any DB work while
            # existing sessions keep verifying (no logout inside the patch:
            # logout would revoke the session under test).
            self.admin_login(client)
            with mock.patch.dict(
                os.environ, {"CISSTAT_AUTH_LOCKDOWN": "1"}
            ):
                blocked = Deployment.post(
                    client,
                    "/v1/auth/login",
                    json={
                        "login": self.admin["login"],
                        "password": self.admin["password"],
                    },
                )
                self.assertEqual(blocked.status_code, 503)
                self.assertEqual(
                    blocked.json()["detail"]["code"], "auth_lockdown"
                )
                me = client.get("/v1/auth/me", headers={"Origin": STANDALONE})
                self.assertEqual(me.status_code, 200)
            # Removing the CSRF signing key fails closed with a safe code.
            with mock.patch.dict(
                os.environ,
                {"CISSTAT_AUTH_CSRF_KEY": ""},
            ):
                csrf = client.get(
                    "/v1/auth/csrf",
                    headers={"Origin": STANDALONE, "X-CSRF-Request": "1"},
                )
                self.assertEqual(csrf.status_code, 503)
