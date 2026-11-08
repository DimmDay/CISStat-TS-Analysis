"""AUTH-11 real PostgreSQL authority + HTTP routers + negative route matrix."""

import os
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from apps.api.access_registry import REGISTRY
from apps.api.accounts.lifecycle import AccountChange, AccountLifecycle
from apps.api.plans import PLAN_DEFINITIONS, PlanName
from apps.api.scientific import guarded_operation
from tests.integration import test_auth09_objects as previous

ORIGIN = previous.ORIGIN
DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires disposable PostgreSQL")
class ScientificSQLTests(unittest.TestCase):
    cleanup = previous.OwnershipSQLTests.cleanup
    client = previous.OwnershipSQLTests.client
    post = previous.OwnershipSQLTests.post
    legacy = previous.OwnershipSQLTests.legacy
    migrate = previous.OwnershipSQLTests.migrate

    def setUp(self):
        previous.OwnershipSQLTests.setUp(self)
        from apps.api.routers import (
            diagnostics,
            diagnostics_internal,
            forecasting_session,
            internal,
            modeling_session,
            models,
            public,
            tasks_session,
            upload_db,
        )

        for module, prefix in [
            (internal, "/v1/internal"),
            (public, "/v1/public"),
            (models, "/v1/models"),
            (diagnostics, "/v1/models"),
            (diagnostics_internal, "/v1/internal"),
            (modeling_session, "/v1/session/modeling"),
            (forecasting_session, "/v1/session/modeling"),
            (tasks_session, "/v1/session/tasks"),
            (upload_db, "/v1/internal/upload/db"),
        ]:
            self.app.include_router(module.router, prefix=prefix)
        self.app.include_router(upload_db.public_router, prefix="/v1/public/upload/db")
        self.owner = self.client()

    def change(self, **changes):
        with self.access.transaction(readonly=True) as tx:
            account = tx.accounts.get(self.account.account_id)
        return AccountLifecycle(self.access).change(
            self.account.account_id,
            expected_version=account.entitlement_version,
            change=AccountChange(**changes),
            reason="AUTH11 disposable test",
        )

    def upload(self, client=None, n=80):
        client = client or self.owner
        proof = client.get("/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
            "csrf_token"
        ]
        csv = "date,v\n" + "\n".join(
            f"{date.date().isoformat()},{i + 1}"
            for i, date in enumerate(pd.date_range("2020-01-01", periods=n))
        )
        r = client.post(
            "/v1/internal/upload",
            files={"file": ("data.csv", csv, "text/csv")},
            headers={"Origin": ORIGIN, "X-CSRF-Token": proof},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return self.sessions.get(client.cookies.get("cisstat_session_id"))

    def card(self, session, model="ets", source="model_default"):
        entry = {
            "card": {
                "model_info": {"model_id": model, "selection_kind": "single"},
                "data_summary": {"n_observations": len(session.dataframe)},
                "training": {"horizon": 12, "n_folds": 2, "params_source": source},
            }
        }
        session.modeling_artifacts = {
            "profile": {"seasonal_periods": [12]},
            "validation_strategy": {"horizon": 12, "n_splits": 2, "gap": 0},
            "model_cards": {"card-a": entry},
            "forecasts": {
                "forecast-a": {
                    "forecast_id": "forecast-a",
                    "model_id": model,
                    "model_card_id": "card-a",
                    "horizon": 12,
                    "lineage": {
                        "seasonal_period": 12,
                        "n_history": len(session.dataframe),
                    },
                }
            },
        }
        self.sessions.save(session)
        return entry

    def test_every_scientific_and_research_route_requires_auth_before_payload(self):
        anon = TestClient(self.app, base_url=ORIGIN)
        count = 0
        for entry, binding in REGISTRY.bindings.items():
            if not entry.startswith("api:") or not guarded_operation(
                binding.operation_id
            ):
                continue
            _, method, path = entry.split(":", 2)
            path = re.sub(r"\{[^}]+\}", "unknown", path)
            with self.subTest(entry=entry):
                r = anon.request(
                    method, path, json={} if method not in {"GET", "HEAD"} else None
                )
                self.assertEqual(r.status_code, 401, r.text)
                self.assertEqual(r.headers.get("cache-control"), "no-store")
            count += 1
        self.assertGreater(count, 170)

    def test_unauthorized_upload_rejected_before_multipart_decode(self):
        r = TestClient(self.app, base_url=ORIGIN).post(
            "/v1/internal/upload",
            content=b"not multipart",
            headers={"Content-Type": "multipart/form-data; boundary=broken"},
        )
        self.assertEqual(r.status_code, 401, r.text)

    def test_demo_baseline_internal_uses_actual_series_not_browser_profile(self):
        self.change(plan="demo")
        self.upload()
        body = {
            "model_id": "naive",
            "profile": {
                "n_observations": 2,
                "frequency": "M",
                "has_seasonality": False,
            },
            "train_ratio": 0.8,
        }
        r = self.post(self.owner, "/v1/internal/models/backtest", body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data_source"], "session")
        self.assertEqual(r.json()["n_train"] + r.json()["n_test"], 80)

    def test_all_advanced_tuning_and_step_alternatives_deny_before_kernel(self):
        self.change(plan="starter")
        self.upload()
        paths = [
            "/v1/internal/models/backtest",
            "/v1/internal/models/diagnostics",
            "/v1/session/modeling/backtest",
            "/v1/session/modeling/tune",
            "/v1/session/modeling/tuning/start",
            "/v1/session/modeling/tuning/step",
            "/v1/session/modeling/jobs/start",
            "/v1/session/modeling/jobs/job-x/step",
            "/v1/session/modeling/forecast/forecast-x/sensitivity",
        ]
        with patch("apps.api.routers.models._run_backtest_with_series") as kernel:
            for path in paths:
                with self.subTest(path=path):
                    r = self.post(
                        self.owner,
                        path,
                        {
                            "model_id": "ets",
                            "profile": {"n_observations": 2},
                            "job_id": "x",
                            "expected_step": 0,
                            "expected_trial_index": 0,
                        },
                    )
                    self.assertEqual(r.status_code, 402, r.text)
            kernel.assert_not_called()
        self.assertEqual(
            self.owner.get("/v1/session/modeling/jobs/job-x").status_code, 402
        )

    def test_foreign_same_person_account_denied_before_db_and_body(self):
        session = self.upload()
        other = self.client(account=self.other)
        other.cookies.set(
            "cisstat_session_id",
            session.session_id,
            domain="ownership.example",
            path="/",
        )
        with patch("apps.api.routers.upload_db.init_db_connection") as connector:
            for path in ["/v1/internal/upload/db/test", "/v1/internal/upload/db/load"]:
                r = self.post(other, path, {"connection": {"invalid": "body"}})
                self.assertEqual(r.status_code, 404, r.text)
            connector.assert_not_called()

    def test_db_probe_and_load_share_current_own_upload_capability(self):
        caps = PLAN_DEFINITIONS[PlanName.PROFESSIONAL].model_copy(
            update={"can_upload_own_data": False}
        )
        with (
            patch.dict(PLAN_DEFINITIONS, {PlanName.PROFESSIONAL: caps}),
            patch("apps.api.routers.upload_db.init_db_connection") as connector,
        ):
            for path in ["/v1/internal/upload/db/test", "/v1/internal/upload/db/load"]:
                r = self.post(self.owner, path, {})
                self.assertEqual(r.status_code, 402, r.text)
            connector.assert_not_called()

    def test_oversized_file_never_registers_file_or_session(self):
        caps = PLAN_DEFINITIONS[PlanName.PROFESSIONAL].model_copy(
            update={"max_dataset_rows": 3}
        )
        proof = self.owner.get("/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
            "csrf_token"
        ]
        with (
            patch.dict(PLAN_DEFINITIONS, {PlanName.PROFESSIONAL: caps}),
            patch("apps.api.upload_common.get_dataset_file_store") as files,
        ):
            r = self.owner.post(
                "/v1/internal/upload",
                files={"file": ("big.csv", "v\n1\n2\n3\n4\n", "text/csv")},
                headers={"Origin": ORIGIN, "X-CSRF-Token": proof},
            )
            self.assertEqual(r.status_code, 402, r.text)
            files.assert_not_called()
        self.assertFalse(self.owner.cookies.get("cisstat_session_id"))

    def test_downgrade_blocks_saved_model_state_card_forecast_export_and_xai(self):
        session = self.upload()
        self.card(session)
        self.change(plan="starter")
        paths = [
            "/v1/session/modeling/state",
            "/v1/session/modeling/card",
            "/v1/session/modeling/card/card-a",
            "/v1/session/modeling/forecast",
            "/v1/session/modeling/forecast/forecast-a",
            "/v1/session/modeling/forecast/forecast-a/export.csv",
            "/v1/session/modeling/forecast/forecast-a/export.json",
            "/v1/session/tasks/causes?card_id=card-a",
        ]
        for path in paths:
            with self.subTest(path=path):
                r = self.owner.get(
                    path, headers={"X-Role": "admin", "X-Plan": "enterprise"}
                )
                self.assertEqual(r.status_code, 402, r.text)
        r = self.post(
            self.owner,
            "/v1/session/modeling/forecast",
            {
                "model_card_id": "card-a",
                "model_id": "naive",
                "params_source": "model_default",
            },
        )
        self.assertEqual(r.status_code, 402, r.text)

    def test_unknown_saved_baseline_provenance_does_not_become_default(self):
        session = self.upload()
        self.card(session, model="naive", source=None)
        self.change(plan="starter")
        r = self.owner.get("/v1/session/modeling/card/card-a")
        self.assertEqual(r.status_code, 402, r.text)

    def test_saved_default_baseline_card_remains_readable(self):
        session = self.upload()
        self.card(session, model="naive")
        self.change(plan="starter")
        r = self.owner.get("/v1/session/modeling/card/card-a")
        self.assertEqual(r.status_code, 200, r.text)

    def test_demo_application_alias_and_history_restore_denied(self):
        session = self.upload()
        self.card(session, model="naive")
        self.change(plan="demo")
        self.assertEqual(self.owner.get("/v1/session/tasks/causes").status_code, 403)
        self.assertEqual(
            self.post(
                self.owner, f"/v1/progress/runs/{session.run_id}/restore"
            ).status_code,
            402,
        )
        self.assertEqual(
            self.post(self.owner, "/v1/session/stage/causal").status_code, 403
        )

    def test_authority_outage_safe_503_never_reaches_scientific_reader(self):
        from apps.api.authentication.errors import AuthStoreUnavailable

        broken = SimpleNamespace(
            transaction=lambda **kw: (_ for _ in ()).throw(AuthStoreUnavailable())
        )
        self.app.state.auth_access_store = broken
        r = self.owner.get("/v1/internal/rules/templates")
        self.assertEqual(r.status_code, 503, r.text)
        self.assertNotIn("postgres", r.text)

    def test_membership_revoke_is_effective_next_request(self):
        member = self.client(member=True)
        self.assertEqual(member.get("/v1/internal/rules/templates").status_code, 200)
        with self.access.transaction(readonly=True) as tx:
            account = tx.accounts.get(self.account.account_id)
        AccountLifecycle(self.access).membership(
            self.account.account_id,
            self.member.subject_id,
            expected_version=account.entitlement_version,
            status="revoked",
            reason="native AUTH11",
        )
        self.assertIn(
            member.get("/v1/internal/rules/templates").status_code, (401, 403)
        )

    def test_internal_analyst_role_cannot_upgrade_demo_account(self):
        with self.access.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_identities SET platform_role='internal_analyst',subject_version=subject_version+1 WHERE subject_id=%s",
                (self.person.subject_id,),
            )
        self.change(plan="demo")
        analyst = self.client()
        r = self.post(
            analyst,
            "/v1/internal/models/backtest",
            {"model_id": "ets", "profile": {"n_observations": 30, "frequency": "M"}},
        )
        self.assertEqual(r.status_code, 402, r.text)

    def api(self, scopes=None):
        from apps.api.authentication.api_key_contract import IssueKeyBody
        from apps.api.authentication.api_key_migrations import apply_migration
        from apps.api.authentication.api_keys import APIKeyService

        with self.access.transaction() as tx:
            apply_migration(tx.connection)
        service = APIKeyService(self.access)
        self.app.state.auth_api_key_service = service
        key = service.issue(
            self.owner.cookies.get("__Host-cisstat_auth"),
            IssueKeyBody(
                label="native AUTH11",
                expires_in_days=1,
                scopes=scopes or ["api.compute"],
            ),
            origin=ORIGIN,
        )
        client = TestClient(self.app, base_url=ORIGIN)
        client.headers["X-API-Key"] = key.secret
        return client

    def test_starter_api_baseline_allowed_advanced_and_scope_bypass_denied(self):
        self.change(plan="starter")
        api = self.api()
        body = {
            "model_id": "naive",
            "profile": {
                "n_observations": 80,
                "frequency": "M",
                "has_seasonality": False,
            },
            "train_ratio": 0.8,
        }
        r = api.post("/v1/models/backtest", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            api.post(
                "/v1/models/backtest", json={**body, "model_id": "ets"}
            ).status_code,
            402,
        )
        self.assertEqual(
            api.post("/v1/internal/models/backtest", json=body).status_code, 403
        )
        read = self.api(scopes=["api.read"])
        self.assertEqual(read.post("/v1/models/backtest", json=body).status_code, 403)
        self.assertEqual(
            self.post(self.owner, "/v1/models/backtest", body).status_code, 401
        )

    def test_actual_engine_input_is_rechecked_after_ingress(self):
        self.change(plan="starter")
        api = self.api()
        cap = PLAN_DEFINITIONS[PlanName.STARTER].model_copy(
            update={"max_dataset_rows": 100}
        )
        body = {
            "model_id": "naive",
            "profile": {
                "n_observations": 80,
                "frequency": "M",
                "has_seasonality": False,
            },
            "train_ratio": 0.8,
        }
        with (
            patch.dict(PLAN_DEFINITIONS, {PlanName.STARTER: cap}),
            patch(
                "apps.api.routers.models._generate_series",
                return_value=list(range(6000)),
            ),
        ):
            r = api.post("/v1/models/backtest", json=body)
            self.assertEqual(r.status_code, 402, r.text)
            self.assertEqual(r.json()["detail"]["code"], "dataset_limit_exceeded")

    def test_demo_session_baseline_pipeline_positive(self):
        self.change(plan="demo")
        self.upload(n=120)
        r = self.post(
            self.owner, "/v1/session/date-column", {"column": "date", "confirmed": True}
        )
        self.assertEqual(r.status_code, 200, r.text)
        for stage in ("start", "modeling_entry"):
            r = self.post(self.owner, "/v1/session/dataset/passport/" + stage)
            self.assertEqual(r.status_code, 200, r.text)
        r = self.post(
            self.owner,
            "/v1/session/modeling/candidates",
            {"horizon": 4, "n_splits": 3, "strategy": "expanding"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        for item in r.json()["catalog"]:
            if item["model_id"] not in REGISTRY.baseline_model_ids:
                self.assertFalse(item["available_actions"])
        r = self.post(self.owner, "/v1/session/modeling/baselines")
        self.assertEqual(r.status_code, 200, r.text)
        results = r.json().get("backtests", {})
        ids = (
            set(results)
            if isinstance(results, dict)
            else {item["model_id"] for item in results}
        )
        self.assertTrue(ids)
        self.assertTrue(ids <= set(REGISTRY.baseline_model_ids))
        r = self.post(
            self.owner,
            "/v1/session/modeling/compare",
            {"model_ids": ["naive", "drift"]},
        )
        self.assertEqual(r.status_code, 200, r.text)
        r = self.post(self.owner, "/v1/session/modeling/selection/evaluate", {})
        self.assertEqual(r.status_code, 200, r.text)
        analysis = r.json()
        chosen = analysis["recommended_single"]["model_id"]
        r = self.post(
            self.owner,
            "/v1/session/modeling/select",
            {
                "model_id": chosen,
                "selection_analysis_id": analysis["selection_analysis_id"],
                "selection_signature": analysis["selection_signature"],
                "acknowledge_baseline_risk": True,
                "acknowledge_selection_bias": True,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        r = self.post(self.owner, "/v1/session/modeling/card", {})
        self.assertEqual(r.status_code, 200, r.text)
        card_id = r.json()["card_id"]
        r = self.post(
            self.owner,
            "/v1/session/modeling/forecast",
            {"model_card_id": card_id, "horizon": 4},
        )
        self.assertEqual(r.status_code, 200, r.text)
        forecast_id = r.json()["forecast_id"]
        for path in (
            "/v1/session/modeling/state",
            f"/v1/session/modeling/forecast/{forecast_id}",
            f"/v1/session/modeling/forecast/{forecast_id}/export.csv",
        ):
            result = self.owner.get(path)
            self.assertEqual(result.status_code, 200, result.text)

    def test_json_suffix_cannot_bypass_actual_series_row_limit(self):
        import json

        cap = PLAN_DEFINITIONS[PlanName.PROFESSIONAL].model_copy(
            update={"max_dataset_rows": 3}
        )
        proof = self.owner.get("/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
            "csrf_token"
        ]
        payload = {
            "series": [{"date": f"2020-01-0{i + 1}", "value": i} for i in range(4)]
        }
        with (
            patch.dict(PLAN_DEFINITIONS, {PlanName.PROFESSIONAL: cap}),
            patch(
                "apps.api.routers.internal.calculate_ts_passport", return_value={}
            ) as kernel,
        ):
            r = self.owner.post(
                "/v1/internal/passport",
                content=json.dumps(payload),
                headers={
                    "Content-Type": "application/vnd.api+json",
                    "Origin": ORIGIN,
                    "X-CSRF-Token": proof,
                },
            )
            self.assertEqual(r.status_code, 402, r.text)
            kernel.assert_not_called()

    def test_validation_does_not_echo_database_credentials(self):
        secret = "disposable-credential-must-not-echo"
        r = self.post(
            self.owner,
            "/v1/internal/upload/db/test",
            {"connection": {"db_type": "unknown", "password": secret}},
        )
        self.assertEqual(r.status_code, 422, r.text)
        self.assertNotIn(secret, r.text)
        self.assertNotIn("input", r.text)
        self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_missing_content_type_cannot_bypass_actual_rows(self):
        import json

        cap = PLAN_DEFINITIONS[PlanName.PROFESSIONAL].model_copy(
            update={"max_dataset_rows": 3}
        )
        proof = self.owner.get("/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
            "csrf_token"
        ]
        body = {"series": [{"date": f"2020-01-0{i + 1}", "value": i} for i in range(4)]}
        with (
            patch.dict(PLAN_DEFINITIONS, {PlanName.PROFESSIONAL: cap}),
            patch("apps.api.routers.internal.calculate_ts_passport") as kernel,
        ):
            r = self.owner.post(
                "/v1/internal/passport",
                content=json.dumps(body),
                headers={"Origin": ORIGIN, "X-CSRF-Token": proof},
            )
            self.assertEqual(r.status_code, 402, r.text)
            kernel.assert_not_called()

    def test_db_limit_is_derived_from_current_cap_and_actual_rows(self):
        from unittest.mock import Mock

        cap = PLAN_DEFINITIONS[PlanName.PROFESSIONAL].model_copy(
            update={"max_dataset_rows": 3}
        )
        body = {
            "connection": {
                "db_type": "postgresql",
                "host": "db.example.com",
                "port": 5432,
                "database": "sales",
                "user": "test",
                "password": "disposable",
                "ssl": False,
            },
            "sql": "SELECT * FROM sample",
            "row_limit": 1000,
        }
        connection = SimpleNamespace(close=Mock())
        result = SimpleNamespace(
            dataframe=pd.DataFrame({"v": [1, 2, 3]}), truncated=True, row_limit=3
        )
        with (
            patch.dict(PLAN_DEFINITIONS, {PlanName.PROFESSIONAL: cap}),
            patch(
                "apps.api.routers.upload_db.init_db_connection", return_value=connection
            ),
            patch(
                "apps.api.routers.upload_db.load_db_dataframe", return_value=result
            ) as reader,
        ):
            r = self.post(self.owner, "/v1/internal/upload/db/load", body)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(reader.call_args.kwargs["row_limit"], 3)
            connection.close.assert_called_once()
        session = self.sessions.get(self.owner.cookies.get("cisstat_session_id"))
        self.assertEqual(len(session.dataframe), 3)

    def test_expanded_dataframe_is_checked_before_session_mutation(self):
        from apps.api.scientific import execution_scope

        session = self.upload(n=2)
        before = session.dataframe.copy(deep=True)
        cap = PLAN_DEFINITIONS[PlanName.DEMO].model_copy(update={"max_dataset_rows": 3})
        admission = SimpleNamespace(
            caps=cap,
            operation_id="preprocessing.correct_dataset_preprocessing_regularity",
            context=SimpleNamespace(
                request_id="native",
                subject_id=str(self.person.subject_id),
                tenant_id=str(self.account.tenant_id),
                auth_method="auth_session",
            ),
        )
        with execution_scope(admission), self.assertRaises(Exception) as error:
            session.set_dataframe(
                pd.DataFrame({"v": [1, 2, 3, 4]}), reason="fault injected expansion"
            )
        self.assertEqual(error.exception.status_code, 402)
        pd.testing.assert_frame_equal(session.dataframe, before)

    def test_global_rule_override_cannot_mutate_other_accounts(self):
        r = self.owner.patch("/v1/internal/rules/update", json={})
        self.assertEqual(r.status_code, 403)  # missing CSRF first
        proof = self.owner.get("/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
            "csrf_token"
        ]
        r = self.owner.patch(
            "/v1/internal/rules/update",
            json={"template_id": "default", "ranges": []},
            headers={"Origin": ORIGIN, "X-CSRF-Token": proof},
        )
        self.assertEqual(r.status_code, 501, r.text)


if __name__ == "__main__":
    unittest.main()
