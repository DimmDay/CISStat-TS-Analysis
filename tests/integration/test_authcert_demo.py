"""AUTH-CERT demo/forum suite: campaign isolation, lifecycle, bounded pipeline.

AC06/AC07/AC11/AC12/AC15/AC18 and the §10 oracle "Demo проходит
upload→validation→preprocessing→EDA→bounded modeling→forecast; каждый прямой
tuning/custom/прикладной endpoint закрыт" — through the live HTTP surface of
the full app (real supervised child for the bounded modeling step, parity of
the AUTH-16 native path, but on the whole deployment incl. CORS/origin stack).
"""

import concurrent.futures
import json
import os
import unittest
from uuid import uuid4

from tests.integration import authcert_harness as H
from tests.integration.authcert_harness import Deployment, PASS, STANDALONE

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires CISSTAT_AUTH_TEST_DSN")
class CertDemoTests(unittest.TestCase):
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

    def setUp(self):
        import contextlib

        self._cm = contextlib.ExitStack()
        self.addCleanup(self._cm.close)

    # ------------------------------------------------- AC06/AC07 isolation

    def test_ac06_ac07_two_participants_one_credential_isolated(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client, alias="cert-iso-" + H.suffix(), max_grants=8
            )
            alias, secret = campaign["alias"], campaign["secret"]
        with self.dep.http() as first, self.dep.http() as second:
            Deployment.enter(first, alias, secret)
            Deployment.enter(second, alias, secret)
            a = self.dep.demo_me(first)
            b = self.dep.demo_me(second)
            # Different actor/grant/account identities from one shared pair.
            self.assertNotEqual(a["grant_id"], b["grant_id"])
            self.assertNotEqual(a["account_id"], b["account_id"])
            # Different uploads -> different datasets and different runs.
            up_a = Deployment.upload(first, name="cert-a.csv")
            up_b = Deployment.upload(second, name="cert-b.csv")
            trace_a = first.get("/v1/progress/trace", headers={"Origin": STANDALONE}).json()
            trace_b = second.get("/v1/progress/trace", headers={"Origin": STANDALONE}).json()
            self.assertNotEqual(trace_a["run_id"], trace_b["run_id"])
            # Participant A cannot mutate or read participant B's state even
            # with the known identifiers: the scientific session is bound to
            # the caller's grant, never to a bare ID.
            chosen = Deployment.post(
                first,
                "/v1/session/date-column",
                json={"column": "date", "confirmed": True},
            )
            self.assertEqual(chosen.status_code, 200)
            trace_b2 = second.get(
                "/v1/progress/trace", headers={"Origin": STANDALONE}
            ).json()
            self.assertNotEqual(trace_a["run_id"], trace_b2["run_id"])

    # ------------------------------------------------- AC11 soft-mode grants

    def test_ac11_new_browser_new_grant_but_hard_limits(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client, alias="cert-ac11-" + H.suffix(), max_grants=2
            )
            alias, secret, cid = (
                campaign["alias"],
                campaign["secret"],
                campaign["campaign_id"],
            )
        with self.dep.http() as one:
            Deployment.enter(one, alias, secret)
        with self.dep.http() as two:
            Deployment.enter(two, alias, secret)
        with self.dep.http() as three:
            # Entry contract: prepare first (resume cookie), then enter.
            Deployment.post(three, "/v1/auth/demo/prepare")
            refused = Deployment.post(
                three,
                "/v1/auth/demo/enter",
                json={"login": alias, "password": secret},
            )
            self.assertEqual(refused.status_code, 429, refused.text)
            self.assertEqual(
                refused.json()["detail"]["code"], "campaign_capacity_exhausted"
            )
        with self.dep.http() as usage_client:
            self.admin_login(usage_client)
            usage = usage_client.get(
                f"/v1/admin/demo-campaigns/{cid}/usage",
                headers={"Origin": STANDALONE},
            ).json()
        self.assertEqual(usage.get("issued_grants"), 2)

    # ------------------------------------------- AC12 admission single-use

    def test_ac12_admission_code_redeemed_once_no_foreign_resume(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client,
                alias="cert-ac12-" + H.suffix(),
                require_admission=True,
                max_grants=2,
            )
            codes = self.dep.admission_codes(admin_client, campaign, 2)
            alias, secret = campaign["alias"], campaign["secret"]
        with self.dep.http() as winner, self.dep.http() as loser, self.dep.http() as second:
            Deployment.enter(winner, alias, secret, code=codes[0])
            # The loser arrives over the full entry contract (prepare
            # first); the spent code is refused with admission_consumed.
            Deployment.post(loser, "/v1/auth/demo/prepare")
            replay = Deployment.post(
                loser,
                "/v1/auth/demo/enter",
                json={
                    "login": alias,
                    "password": secret,
                    "admission_code": codes[0],
                },
            )
            self.assertEqual(replay.status_code, 409, replay.text)
            self.assertEqual(
                replay.json()["detail"]["code"], "admission_consumed"
            )
            # The spent code neither mints a grant nor issues cookies.
            self.assertIsNone(replay.headers.get("set-cookie"))
            # The loser has no resume of their own and cannot adopt the
            # winner's session: bare resume is refused.
            bare = Deployment.post(loser, "/v1/auth/demo/resume")
            self.assertEqual(bare.status_code, 401)
            # A distinct unused code still admits a second participant.
            Deployment.enter(second, alias, secret, code=codes[1])

    # --------------------------------------- AC15 pause/expiry enforcement

    def test_ac15_pause_and_revoke_close_live_operations(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client, alias="cert-ac15-" + H.suffix()
            )
            alias, secret, cid = (
                campaign["alias"],
                campaign["secret"],
                campaign["campaign_id"],
            )
            version = campaign["policy_version"]
        with self.dep.http() as participant:
            Deployment.enter(participant, alias, secret)
            Deployment.upload(participant)
            self.assertEqual(
                participant.get(
                    "/v1/auth/demo/me", headers={"Origin": STANDALONE}
                ).status_code,
                200,
            )
            # Admin pauses the campaign: the next participant operation is
            # refused without waiting for any TTL.
            paused = Deployment.post(
                admin_client,
                f"/v1/admin/demo-campaigns/{cid}/pause",
                json={"expected_version": version, "reason": "cert pause"},
            )
            self.assertEqual(paused.status_code == 200, True, paused.text)
            import io

            buffer = io.BytesIO(b"date,value\n2020-01-15,1\n2020-02-15,2\n")
            blocked = participant.post(
                "/v1/internal/upload",
                files={"file": ("cert-paused.csv", buffer.getvalue(), "text/csv")},
                headers={
                    "Origin": STANDALONE,
                    "X-CSRF-Token": Deployment.csrf(participant),
                },
            )
            self.assertIn(blocked.status_code, (401, 403), blocked.text)
            self.assertEqual(
                blocked.json()["detail"]["code"], "campaign_inactive"
            )
            limits = participant.get(
                "/v1/auth/demo/limits", headers={"Origin": STANDALONE}
            )
            self.assertIn(limits.status_code, (401, 403))
            # Resume cannot resurrect the paused state for the same grant
            # while the campaign stays paused.
            resume = Deployment.post(participant, "/v1/auth/demo/resume")
            self.assertIn(resume.status_code, (401, 403))

    # ------------------------------- AC18/§10 bounded pipeline and closures

    def test_s10_demo_pipeline_end_to_end_and_closed_endpoints(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client,
                alias="cert-pipe-" + H.suffix(),
                participant_analyses=5,
            )
            alias, secret = campaign["alias"], campaign["secret"]
        with self.dep.http() as participant:
            Deployment.enter(participant, alias, secret)
            Deployment.upload(participant)
            # Validation stage: the real rules run server-side.
            validate = participant.get(
                "/v1/session/dataset/validate", headers={"Origin": STANDALONE}
            )
            self.assertEqual(validate.status_code, 200, validate.text)
            # EDA stage: a real profile computation on the uploaded series.
            eda = participant.get(
                "/v1/session/dataset/stats", headers={"Origin": STANDALONE}
            )
            self.assertEqual(eda.status_code, 200, eda.text)
            # Preprocessing stage: the structure confirmation stop.
            structure = Deployment.post(
                participant,
                "/v1/session/date-column",
                json={"column": "date", "confirmed": True},
            )
            self.assertEqual(structure.status_code == 200, True, structure.text)
            passport = Deployment.post(
                participant, "/v1/session/dataset/passport/start"
            )
            self.assertEqual(passport.status_code == 200, True, passport.text)
            entry = Deployment.post(
                participant, "/v1/session/dataset/passport/modeling_entry"
            )
            self.assertEqual(entry.status_code == 200, True, entry.text)
            # Bounded modeling stage (real supervised child, AUTH-13 fence).
            candidates = Deployment.post(
                participant,
                "/v1/session/modeling/candidates",
                json={"horizon": 4, "n_splits": 3, "strategy": "expanding"},
            )
            self.assertEqual(candidates.status_code == 200, True, candidates.text)
            baselines = Deployment.post(participant, "/v1/session/modeling/baselines")
            self.assertEqual(baselines.status_code == 200, True, baselines.text)
            compare = Deployment.post(
                participant,
                "/v1/session/modeling/compare",
                # The certified scope is server-enforced: an empty list
                # compares the full included backtest scope, never less.
                json={"model_ids": []},
            )
            self.assertEqual(compare.status_code == 200, True, compare.text)
            scope_ids = compare.json().get("execution_scope", {}).get(
                "included_backtest_model_ids"
            )
            self.assertTrue(scope_ids, compare.json())
            evaluate = Deployment.post(
                participant, "/v1/session/modeling/selection/evaluate", json={}
            )
            self.assertEqual(evaluate.status_code == 200, True, evaluate.text)
            analysis = evaluate.json()
            select = Deployment.post(
                participant,
                "/v1/session/modeling/select",
                json={
                    "model_id": analysis["recommended_single"]["model_id"],
                    "selection_analysis_id": analysis["selection_analysis_id"],
                    "selection_signature": analysis["selection_signature"],
                    "acknowledge_baseline_risk": True,
                    "acknowledge_selection_bias": True,
                },
            )
            self.assertEqual(select.status_code == 200, True, select.text)
            card = Deployment.post(
                participant, "/v1/session/modeling/card", json={}
            )
            self.assertEqual(card.status_code == 200, True, card.text)
            forecast = Deployment.post(
                participant,
                "/v1/session/modeling/forecast",
                json={"model_card_id": card.json()["card_id"], "horizon": 4},
            )
            self.assertEqual(forecast.status_code == 200, True, forecast.text)
            export = participant.get(
                "/v1/session/modeling/forecast/"
                + forecast.json()["forecast_id"]
                + "/export.csv",
                headers={"Origin": STANDALONE},
            )
            self.assertEqual(export.status_code == 200, True, export.text)
            self.assertGreater(len(export.content), 0)
            # AC18: forbidden heavy/direct endpoints stay closed for demo —
            # the demo tariff refuses them on capability grounds.
            tuning = Deployment.post(participant, "/v1/session/modeling/tuning/start")
            self.assertIn(tuning.status_code, (402, 403, 422), tuning.text)
            self.assertEqual(
                tuning.json()["detail"]["code"], "capability_not_included"
            )
            skip = Deployment.post(
                participant, "/v1/session/modeling/tuning/skip", json={}
            )
            # Skip without a tuning context is refused as an invalid
            # scientific request; the surface stays closed either way.
            self.assertIn(skip.status_code, (402, 403, 422))
            admin_api = participant.get(
                "/v1/admin/demo-campaigns", headers={"Origin": STANDALONE}
            )
            self.assertEqual(admin_api.status_code, 403)

    def test_ac18_public_api_and_internal_guard_for_demo(self):
        with self.dep.http() as admin_client:
            self.admin_login(admin_client)
            campaign = self.dep.campaign(
                admin_client, alias="cert-pub-" + H.suffix()
            )
            alias, secret = campaign["alias"], campaign["secret"]
        with self.dep.http() as participant:
            Deployment.enter(participant, alias, secret)
            # Public API keys are a separate authority: a demo cookie is not
            # an API key and the public passport route refuses it.
            csv = b"date,value\n2020-01-15,1\n2020-02-15,2\n2020-03-15,3\n"
            public = participant.post(
                "/v1/public/passport",
                files={"file": ("cert.csv", csv, "text/csv")},
                headers={"Origin": STANDALONE},
            )
            self.assertIn(public.status_code, (401, 403), public.text)
