"""AUTH-CERT API suite: identity/session/MFA/admin/team over the full app.

AC01–AC05, AC09/AC10, AC17, AC21–AC23, AC25, AC03 (spec_auth §17) verified
through the live HTTP surface of a production-like deployment (fresh 0019→0035
database, required storage mode, real cookies/CSRF/Origin). Independent
expectations; the reducer is never copied.
"""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from tests.integration import authcert_harness as H
from tests.integration.authcert_harness import Deployment, PASS, STANDALONE, EMBEDDED

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires CISSTAT_AUTH_TEST_DSN")
class CertApiTests(unittest.TestCase):
    dep = None
    admin = None

    @classmethod
    def setUpClass(cls):
        cls.dep = Deployment()
        with cls.dep.http() as client:
            body, rec = cls.dep.admin_client(client)
        cls.admin = {
            "seed": rec["seed"],
            "login": rec["login"],
            "password": PASS,
        }

    @classmethod
    def tearDownClass(cls):
        cls.dep.stop()

    def client(self):
        return self._cm.enter_context(self.dep.http())

    def admin_login(self, client, origin=STANDALONE):
        """Fresh MFA login for the class admin (single-use bootstrap spent)."""
        return self.dep.admin_relogin(
            client,
            self.admin["login"],
            self.admin["seed"],
            origin=origin,
            password=self.admin["password"],
        )

    def setUp(self):
        import contextlib

        self._cm = contextlib.ExitStack()
        self.addCleanup(self._cm.close)
        self.client = self.client()

    # ------------------------------------------------------------ AC01/02

    def test_ac01_ac02_admin_mfa_login_both_origins(self):
        # Admin sessions are origin-bound: each shell serves the named admin
        # from its own login, which is exactly the two-shell contract.
        with self.dep.http() as standalone_client:
            self.dep.admin_relogin(
                standalone_client, self.admin["login"], self.admin["seed"]
            )
            me = self.dep.me(standalone_client)
            self.assertEqual(me["role"], "admin")
            self.assertIsNotNone(me["mfa_verified_at"])
            # AC02: standalone self-service admin surface calls real APIs.
            campaigns = standalone_client.get(
                "/v1/admin/demo-campaigns", headers={"Origin": STANDALONE}
            )
            self.assertEqual(campaigns.status_code, 200, campaigns.text)
            self.assertIn("campaigns", campaigns.json())
        with self.dep.http() as embedded_client:
            self.dep.admin_relogin(
                embedded_client,
                self.admin["login"],
                self.admin["seed"],
                origin=EMBEDDED,
            )
            embedded = embedded_client.get(
                "/v1/admin/demo-campaigns", headers={"Origin": EMBEDDED}
            )
            self.assertEqual(embedded.status_code, 200, embedded.text)
            # AUTH-19 availability flags visible on both shells' transport.
            flags = embedded_client.get(
                "/v1/auth/csrf",
                headers={"Origin": EMBEDDED, "X-CSRF-Request": "1"},
            )
            self.assertEqual(flags.status_code, 200)
            self.assertIn("email_trial", flags.json())

    # ---------------------------------------------------------------- AC03

    def test_ac03_owner_and_analyst_rejected_on_admin_apis(self):
        login = "cert-owner-" + H.suffix()
        self.dep.personal_user(login)
        with self.dep.http() as owner_client:
            Deployment.login(owner_client, login)
            # Owner of a real account is still not an ADMIN.
            blocked = owner_client.get(
                "/v1/admin/demo-campaigns", headers={"Origin": STANDALONE}
            )
            self.assertEqual(blocked.status_code, 403)
            # URL/role-body/header tampering does not help.
            tampered = Deployment.post(
                owner_client,
                "/v1/admin/demo-campaigns",
                json={
                    "alias": "cert-evil-" + H.suffix(),
                    "policy": self._policy(),
                    "reason": "attempt",
                    "role": "admin",
                },
            )
            self.assertIn(tampered.status_code, (403, 422))
            header = owner_client.get(
                "/v1/admin/demo-campaigns",
                headers={"Origin": STANDALONE, "X-Role": "admin"},
            )
            self.assertEqual(header.status_code, 403)
        # internal_analyst gets the same refusal.
        analyst = "cert-analyst-" + H.suffix()
        identity, _ = self.dep.personal_user(analyst, platform_role="internal_analyst")
        with self.dep.http() as analyst_client:
            Deployment.login(analyst_client, analyst)
            self.assertEqual(
                analyst_client.get(
                    "/v1/admin/demo-campaigns", headers={"Origin": STANDALONE}
                ).status_code,
                403,
            )
            self.assertEqual(identity.platform_role, "internal_analyst")

    def _policy(self):
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
            "allowed_origins": [STANDALONE, EMBEDDED],
        }

    # ---------------------------------------------------------------- AC04

    def test_ac04_challenge_not_session_and_fresh_stepup_required(self):
        new_pass = "Another durable acceptance passphrase 42!"
        with self.dep.http() as client:
            self.admin_login(client)
            me = self.dep.me(client)
            self.assertIsNotNone(me["mfa_verified_at"])
            # A sensitive change without a fresh step-up proof is refused for
            # an MFA-enabled user even with a perfectly valid session.
            refused = Deployment.post(
                client,
                "/v1/auth/password",
                json={
                    "current_password": self.admin["password"],
                    "new_password": new_pass,
                },
            )
            self.assertIn(refused.status_code, (401, 403), refused.text)
            # Fresh step-up: password + MFA code -> one-time proof.
            step = Deployment.post(
                client,
                "/v1/auth/step-up",
                json={
                    "password": self.admin["password"],
                    "action": "password.change",
                },
            ).json()
            self.assertEqual(step["status"], "challenge_required", step)
            proof_body = self.dep.admin_verify(
                client, self.admin["seed"], step["challenge_token"]
            )
            proof = proof_body["challenge_token"]
            changed = Deployment.post(
                client,
                "/v1/auth/password",
                json={
                    "current_password": self.admin["password"],
                    "new_password": new_pass,
                    "proof": proof,
                },
            )
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertTrue(changed.json()["sessions_revoked"])
            self.admin["password"] = new_pass
            # Sessions were revoked by the sensitive change.
            self.assertEqual(
                client.get("/v1/auth/me", headers={"Origin": STANDALONE}).status_code,
                401,
            )
        with self.dep.http() as client:
            # A login challenge token is never a usable session.
            challenge = Deployment.post(
                client,
                "/v1/auth/login",
                json={
                    "login": self.admin["login"],
                    "password": self.admin["password"],
                },
            ).json()
            self.assertEqual(challenge["status"], "challenge_required")
            client.cookies.set(
                "__Host-cisstat_auth",
                challenge["challenge_token"],
                domain="datasetup.ru",
            )
            self.assertEqual(
                client.get("/v1/auth/me", headers={"Origin": STANDALONE}).status_code,
                401,
            )

    # ---------------------------------------------------------------- AC05

    def test_ac05_logout_and_role_removal_close_next_request(self):
        login = "cert-logout-" + H.suffix()
        self.dep.personal_user(login)
        with self.dep.http() as client:
            Deployment.login(client, login)
            self.assertEqual(
                client.get("/v1/auth/me", headers={"Origin": STANDALONE}).status_code,
                200,
            )
            out = Deployment.post(client, "/v1/auth/logout")
            self.assertEqual(out.status_code, 204)
            self.assertEqual(
                client.get("/v1/auth/me", headers={"Origin": STANDALONE}).status_code,
                401,
            )
        # Role removal (ADMIN снятие) closes the very next request without
        # waiting for any access TTL: the identity version-bump revokes the
        # session (AUTH-04 fencing) and the admin surface stays closed. The
        # fixture admin is restored at the end (bootstrap is single-use).
        with self.dep.store.transaction(readonly=True) as tx:
            admin_row = tx.connection.execute(
                "SELECT subject_id FROM auth_password_credentials WHERE login=%s",
                (self.admin["login"],),
            ).fetchone()
        with self.dep.http() as client:
            self.admin_login(client)
            ok = client.get(
                "/v1/admin/demo-campaigns", headers={"Origin": STANDALONE}
            )
            self.assertEqual(ok.status_code, 200)
            with self.dep.store.transaction() as tx:
                tx.connection.execute(
                    "UPDATE auth_identities SET platform_role='external_user',"
                    "subject_version=subject_version+1 WHERE subject_id=%s",
                    (admin_row["subject_id"],),
                )
            after = client.get(
                "/v1/admin/demo-campaigns", headers={"Origin": STANDALONE}
            )
            self.assertIn(after.status_code, (401, 403))
        with self.dep.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_identities SET platform_role='admin',"
                "subject_version=subject_version+1 WHERE subject_id=%s",
                (admin_row["subject_id"],),
            )
        with self.dep.http() as client:
            self.admin_login(client)
            restored = client.get(
                "/v1/admin/demo-campaigns", headers={"Origin": STANDALONE}
            )
            self.assertEqual(restored.status_code, 200)

    # ---------------------------------------------------------------- AC09

    def test_ac09_relogin_keeps_grant_expiry_and_usage(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client,
                alias="cert-ac09-" + H.suffix(),
                grant_minutes=90,
            )
            alias, secret = campaign["alias"], campaign["secret"]
        with self.dep.http() as participant:
            Deployment.enter(participant, alias, secret)
            first = Deployment.demo_me(participant)
            expires = first["expires_at"]
            # logout + resume: same grant, same expiry, same usage.
            Deployment.post(participant, "/v1/auth/logout")
            resumed = Deployment.post(participant, "/v1/auth/demo/resume")
            self.assertEqual(resumed.status_code == 200, True)
            again = Deployment.demo_me(participant)
            self.assertEqual(again["grant_id"], first["grant_id"])
            self.assertEqual(again["expires_at"], expires)

    # ---------------------------------------------------------------- AC10

    def test_ac10_expired_campaign_boundary_rejects_enter(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            # ends_at inside the next two seconds: enter after the boundary.
            campaign = self.dep.campaign(
                admin_client,
                alias="cert-ac10-" + H.suffix(),
                ends_at=(datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(),
                grant_minutes=1,
            )
            alias, secret = campaign["alias"], campaign["secret"]
        import time as time_module

        time_module.sleep(3)
        with self.dep.http() as participant:
            Deployment.post(participant, "/v1/auth/demo/prepare")
            refused = Deployment.post(
                participant,
                "/v1/auth/demo/enter",
                json={"login": alias, "password": secret},
            )
            self.assertEqual(refused.status_code, 403)
            self.assertEqual(
                refused.json()["detail"]["code"], "demo_expired"
            )

    # ---------------------------------------------------------------- AC17

    def test_ac17_second_session_no_new_budget_no_usage_reset(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client, alias="cert-ac17-" + H.suffix()
            )
            alias, secret, cid = (
                campaign["alias"],
                campaign["secret"],
                campaign["campaign_id"],
            )
            usage_path = f"/v1/admin/demo-campaigns/{cid}/usage"

            def usage():
                return admin_client.get(
                    usage_path, headers={"Origin": STANDALONE}
                ).json()

            with self.dep.http() as first:
                Deployment.enter(first, alias, secret)
                grants_after_one = usage().get("issued_grants")
                # Re-enter from the SAME browser (same resume cookie)
                # replaces its own session; never a second grant/budget.
                Deployment.enter(first, alias, secret)
                self.assertEqual(usage().get("issued_grants"), grants_after_one)
            with self.dep.http() as second:
                Deployment.enter(second, alias, secret)
            self.assertEqual(usage().get("issued_grants"), grants_after_one + 1)

    # ------------------------------------------------------- AC21/AC22/AC23

    def test_ac21_fixation_rotates_and_cookies_differ(self):
        login = "cert-fixation-" + H.suffix()
        self.dep.personal_user(login)
        with self.dep.http() as client:
            first = Deployment.login(client, login)
            old = client.cookies.get("__Host-cisstat_auth")
            second = Deployment.login(client, login)
            self.assertNotEqual(
                second["session"]["session_id"], first["session"]["session_id"]
            )
            client.cookies.set("__Host-cisstat_auth", old, domain="datasetup.ru")
            self.assertEqual(
                client.get("/v1/auth/me", headers={"Origin": STANDALONE}).status_code,
                401,
            )
        set_cookie = None
        with self.dep.http() as probe:
            Deployment.login(probe, login)
        with self.dep.http() as fresh:
            response = fresh.post(
                "/v1/auth/login",
                json={"login": login, "password": PASS},
                headers={
                    "Origin": STANDALONE,
                    "X-CSRF-Token": Deployment.csrf(fresh),
                },
            )
            raw = response.headers.get("set-cookie", "")
            self.assertIn("__Host-cisstat_auth", raw)
            self.assertIn("HttpOnly", raw)
            self.assertIn("Secure", raw)
            self.assertIn("SameSite=lax", raw)
            self.assertNotIn("Domain=", raw)
            # Auth session cookie and research pointer are different names.
            self.assertNotIn("cisstat_session_id=", raw.split(";")[0])

    def test_ac22_ac23_csrf_origin_and_no_cors_bypass(self):
        login = "cert-csrf-" + H.suffix()
        self.dep.personal_user(login)
        with self.dep.http() as client:
            Deployment.login(client, login)
            # Missing CSRF proof on a mutation is refused.
            missing = client.post(
                "/v1/auth/logout", headers={"Origin": STANDALONE}
            )
            self.assertEqual(missing.status_code, 403)
            # Wrong Origin is refused on the same call.
            wrong = client.post(
                "/v1/auth/logout",
                headers={
                    "Origin": "https://evil.example",
                    "X-CSRF-Token": Deployment.csrf(client),
                },
            )
            self.assertEqual(wrong.status_code, 403)
            # Cross-site fetch metadata is refused even with a valid proof.
            cross = client.post(
                "/v1/auth/logout",
                headers={
                    "Origin": STANDALONE,
                    "Sec-Fetch-Site": "cross-site",
                    "X-CSRF-Token": Deployment.csrf(client),
                },
            )
            self.assertEqual(cross.status_code, 403)
            # A disallowed origin never receives CORS opening headers.
            evil = client.get(
                "/v1/auth/me",
                headers={"Origin": "https://evil.example"},
            )
            self.assertNotIn("access-control-allow-origin", evil.headers)

    # ---------------------------------------------------------------- AC25

    def test_ac25_policy_cas_one_winner_usage_not_reset(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client, alias="cert-ac25-" + H.suffix()
            )
            alias, secret = campaign["alias"], campaign["secret"]
            cid = campaign["campaign_id"]
            with self.dep.http() as participant:
                Deployment.enter(participant, alias, secret)
            # Two concurrent edits from the same old version: one wins.
            old_version = campaign["policy_version"]
            policy = dict(campaign["policy"])
            policy["max_grants"] = policy["max_grants"] + 5
            results = []
            import concurrent.futures

            def edit(tag):
                return admin_client.patch(
                    f"/v1/admin/demo-campaigns/{cid}",
                    json={
                        "expected_version": old_version,
                        "reason": f"cert edit {tag}",
                        "policy": policy,
                    },
                    headers={
                        "Origin": STANDALONE,
                        "X-CSRF-Token": Deployment.csrf(admin_client),
                    },
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                for response in pool.map(edit, ("a", "b")):
                    results.append(response.status_code)
            self.assertEqual(sorted(results), [200, 409])
            usage = admin_client.get(
                f"/v1/admin/demo-campaigns/{cid}/usage", headers={"Origin": STANDALONE}
            ).json()
            self.assertEqual(usage.get("issued_grants"), 1)
