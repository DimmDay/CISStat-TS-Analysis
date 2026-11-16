"""Real HTTP email proof -> upload -> scientific pipeline using issued resources."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from apps.api.authentication.personal_demo_migrations import apply_migration
from tests.integration import authcert_harness as H

Deployment = H.Deployment
STANDALONE = H.STANDALONE


@unittest.skipUnless(os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PG required")
class PersonalDemoHTTPTests(unittest.TestCase):
    def setUp(self):
        from urllib.parse import urlsplit, urlunsplit

        dsn = urlunsplit(
            urlsplit(os.environ["CISSTAT_AUTH_TEST_DSN"])._replace(path="/postgres")
        )
        # AUTH-CERT harness expects a postgres base URI; the native runner owns PG.
        if "?" not in dsn:
            dsn += "?"
        self.pg = patch.object(
            H, "pg", return_value=SimpleNamespace(get_uri=lambda: dsn)
        )
        self.pg.start()
        self.addCleanup(self.pg.stop)
        import tempfile
        from pathlib import Path

        from apps.api.artifact_store import (
            reset_artifact_object_store_for_testing,
            reset_artifact_registry_for_testing,
        )
        from apps.api.report_snapshot import reset_snapshot_registry_for_testing

        reset_snapshot_registry_for_testing()
        reset_artifact_registry_for_testing()
        reset_artifact_object_store_for_testing()
        tmp = tempfile.TemporaryDirectory(
            prefix="personal-http-", dir=Path(__file__).resolve().parents[3]
        )
        self.addCleanup(tmp.cleanup)
        with patch.object(H.tempfile, "mkdtemp", return_value=tmp.name):
            self.dep = Deployment()
        self.addCleanup(self.dep.stop)
        with self.dep.store.transaction() as tx:
            apply_migration(tx.connection)

    def test_verified_email_starts_research_without_operator_provisioning(self):
        letters = []
        delivery = SimpleNamespace(send=lambda to, subject, body: letters.append(body))
        env = {
            "CISSTAT_PERSONAL_DEMO_ENABLED": "1",
            "CISSTAT_AUTH_EMAIL_KEY": "test-only-email-key-0123456789abcdef0123456789",
        }
        with (
            patch.dict(os.environ, env),
            patch(
                "apps.api.authentication.providers.email_delivery.SmtpEmailDelivery.from_env",
                return_value=delivery,
            ),
            self.dep.http() as participant,
        ):
            availability = participant.get(
                "/v1/auth/personal-demo", headers={"Origin": STANDALONE}
            )
            self.assertEqual(availability.status_code, 200, availability.text)
            self.assertTrue(availability.json()["available"])
            started = Deployment.post(
                participant,
                "/v1/auth/email/start",
                json={"email": "new-person@example.test", "purpose": "trial_login"},
            )
            self.assertEqual(started.status_code, 200, started.text)
            self.assertFalse(self.dep.rows("auth_personal_trials"))
            token = letters[-1].split("email_challenge=")[1].split("&")[0]
            consumed = Deployment.post(
                participant, "/v1/auth/email/consume", json={"token": token}
            )
            self.assertEqual(consumed.status_code, 200, consumed.text)
            self.assertEqual(len(self.dep.rows("auth_personal_trials")), 1)
            self.assertEqual(
                self.dep.rows("auth_wallet_lots")[0]["available"], 100000000
            )
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
            scope_ids = (
                compare.json()
                .get("execution_scope", {})
                .get("included_backtest_model_ids")
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
            card = Deployment.post(participant, "/v1/session/modeling/card", json={})
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
            self.assertTrue(
                any(
                    b["metric"] == "analysis" and b["spent"] > 0
                    for b in self.dep.rows("auth_resource_budgets")
                )
            )

    def test_eleventh_upload_is_refused_and_failed_upload_does_not_spend(self):
        letters = []
        delivery = SimpleNamespace(send=lambda to, subject, body: letters.append(body))
        env = {
            "CISSTAT_PERSONAL_DEMO_ENABLED": "1",
            "CISSTAT_AUTH_EMAIL_KEY": "test-only-email-key-0123456789abcdef0123456789",
        }
        with (
            patch.dict(os.environ, env),
            patch(
                "apps.api.authentication.providers.email_delivery.SmtpEmailDelivery.from_env",
                return_value=delivery,
            ),
            self.dep.http() as client,
        ):
            Deployment.post(
                client,
                "/v1/auth/email/start",
                json={"email": "limited@example.test", "purpose": "trial_login"},
            )
            token = letters[-1].split("email_challenge=")[1].split("&")[0]
            proof = Deployment.post(
                client, "/v1/auth/email/consume", json={"token": token}
            )
            self.assertEqual(proof.status_code, 200, proof.text)
            bad = client.post(
                "/v1/internal/upload",
                files={"file": ("bad.csv", b"not,csv\n", "text/csv")},
                headers={"Origin": STANDALONE, "X-CSRF-Token": Deployment.csrf(client)},
            )
            self.assertGreaterEqual(bad.status_code, 400)
            self.assertFalse(self.dep.rows("auth_analysis_claims"))
            for n in range(10):
                Deployment.upload(client, name=f"trial-{n}.csv")
            self.assertEqual(len(self.dep.rows("auth_analysis_claims")), 10)
            with self.assertRaisesRegex(AssertionError, "quota_exceeded"):
                Deployment.upload(client, name="eleventh.csv")
            self.assertEqual(len(self.dep.rows("auth_analysis_claims")), 10)
