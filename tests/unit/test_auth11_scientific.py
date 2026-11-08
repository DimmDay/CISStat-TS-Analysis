"""AUTH-11 policy/normalization and request execution fence oracles."""

import os
import unittest
from contextvars import copy_context
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from apps.api.plans import PLAN_DEFINITIONS, PlanName
from apps.api.scientific import authorize_execution, execution_scope, scientific_mode
from apps.api.scientific_workload import model_workloads


class ScientificUnitTests(unittest.TestCase):
    def test_production_cannot_disable_guard(self):
        for mode in ("legacy_dev", "off", "shadow", "unknown"):
            with (
                self.subTest(mode=mode),
                patch.dict(os.environ, {
                    "CISSTAT_STORAGE_MODE": "required",
                    "CISSTAT_SCIENTIFIC_GUARD_MODE": mode,
                }),
                self.assertRaises(HTTPException),
            ):
                scientific_mode()
        with patch.dict(
            os.environ,
            {"CISSTAT_STORAGE_MODE": "required", "CISSTAT_SCIENTIFIC_GUARD_MODE": ""},
        ):
            self.assertEqual(scientific_mode(), "enforce")

    def test_actual_engine_values_override_ingress_claims(self):
        admission = SimpleNamespace(
            caps=PLAN_DEFINITIONS[PlanName.DEMO],
            operation_id="modeling.backtest",
            context=SimpleNamespace(request_id="unit"),
        )
        with execution_scope(admission):
            authorize_execution(
                model_id="naive", rows=50, folds=2, horizon=12, seasonal_period=12
            )
            for kwargs in (
                {"model_id": "ets"},
                {"rows": 5001},
                {"folds": 4},
                {"horizon": 25},
                {"seasonal_period": 367},
                {"custom_parameters": True},
            ):
                actual = {
                    "model_id": "naive",
                    "rows": 50,
                    "folds": 2,
                    "horizon": 12,
                    "seasonal_period": 12,
                    **kwargs,
                }
                with self.assertRaises(HTTPException):
                    authorize_execution(**actual)
        self.assertIsNone(
            copy_context().get(
                __import__(
                    "apps.api.scientific", fromlist=["ACTIVE_ADMISSION"]
                ).ACTIVE_ADMISSION,
                None,
            )
        )

    def test_actual_period_inside_parameters_cannot_hide_behind_scalar(self):
        admission = SimpleNamespace(
            caps=PLAN_DEFINITIONS[PlanName.DEMO],
            operation_id="modeling.backtest",
            context=SimpleNamespace(request_id="unit", role="admin"),
        )
        with execution_scope(admission), self.assertRaises(HTTPException) as error:
            authorize_execution(
                model_id="seasonal_naive",
                rows=100,
                folds=1,
                horizon=12,
                seasonal_period=12,
                parameters={"seasonal_period": 730},
            )
        self.assertEqual(error.exception.status_code, 402)

    def test_defaults_bounded_but_explicit_saved_validation_preserved(self):
        from apps.api.scientific import bounded_default

        admission = SimpleNamespace(caps=PLAN_DEFINITIONS[PlanName.DEMO])
        with execution_scope(admission):
            self.assertEqual(bounded_default("folds", 5), 3)
            self.assertEqual(bounded_default("horizon", 12), 12)
            session = SimpleNamespace(
                dataframe=list(range(80)),
                modeling_artifacts={
                    "validation_strategy": {"n_splits": 8, "horizon": 12}
                },
            )
            request = SimpleNamespace(
                path_params={},
                query_params={},
                url=SimpleNamespace(path="/v1/session/modeling/backtest"),
            )
            self.assertEqual(
                model_workloads(
                    "modeling.backtest", request, {"model_id": "naive"}, session
                )[0].folds,
                8,
            )

    def test_all_declared_scientific_routes_have_common_dependency(self):
        from pathlib import Path

        from apps.api.access_registry import REGISTRY
        from apps.api.scientific import guarded_operation
        from scripts.auth00.inventory import discovery

        root = Path(__file__).resolve().parents[2]
        entries = {e["id"]: e for e in discovery(root) if e["kind"] == "api"}
        guarded = {
            key
            for key, binding in REGISTRY.bindings.items()
            if key.startswith("api:") and guarded_operation(binding.operation_id)
        }
        self.assertEqual(len(guarded), 173)
        for key in guarded:
            self.assertIn("scientific_guard", entries[key]["dependencies"], key)

    def test_unknown_route_denied_before_invalid_json(self):
        from fastapi import APIRouter, Depends, FastAPI
        from fastapi.testclient import TestClient

        from apps.api.scientific import ScientificRoute, scientific_guard

        app = FastAPI()
        router = APIRouter(
            route_class=ScientificRoute, dependencies=[Depends(scientific_guard)]
        )
        calls = []

        @router.post("/v1/session/not-reviewed")
        def endpoint(payload: dict):
            calls.append(payload)
            return payload

        app.include_router(router)
        with patch.dict(os.environ, {"CISSTAT_STORAGE_MODE": "required"}):
            response = TestClient(app).post(
                "/v1/session/not-reviewed",
                content=b"invalid-json",
                headers={"content-type": "application/json"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json()["detail"]["request_id"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertFalse(calls)

    def test_local_staging_hint_selects_current_auth_manifest(self):
        import importlib.util
        import tempfile
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "scripts/local_gates.py"
        spec = importlib.util.spec_from_file_location("auth11_gates", path)
        gates = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gates)
        with tempfile.TemporaryDirectory() as temp:
            gates.ROOT = Path(temp)
            for relative in [
                "scripts/auth10/files.txt",
                "scripts/auth10/hotfix01/files.txt",
                "scripts/auth11/files.txt",
            ]:
                p = gates.ROOT / relative
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("fixture")
            self.assertEqual(gates.staging_manifests(), ["scripts/auth11/files.txt"])

    def test_saved_forecast_does_not_trust_browser_model_id(self):
        session = SimpleNamespace(
            dataframe=list(range(80)),
            modeling_artifacts={
                "model_cards": {
                    "card-a": {
                        "card": {
                            "model_info": {"model_id": "ets"},
                            "data_summary": {"n_observations": 80},
                            "training": {
                                "horizon": 12,
                                "n_folds": 3,
                                "params_source": "tuning",
                            },
                        }
                    }
                },
                "forecasts": {
                    "forecast-a": {
                        "model_id": "ets",
                        "model_card_id": "card-a",
                        "horizon": 12,
                        "lineage": {"seasonal_period": 12, "n_history": 80},
                    }
                },
            },
        )
        req = SimpleNamespace(
            path_params={"forecast_id": "forecast-a"}, query_params={}
        )
        values = model_workloads(
            "forecasting.get_forecast",
            req,
            {"model_id": "naive", "params_source": "model_default"},
            session,
        )
        self.assertEqual(values[0].model_ids, ("ets",))
        self.assertTrue(values[0].custom_parameters)

    def test_backtest_uses_saved_validation_and_actual_rows(self):
        session = SimpleNamespace(
            dataframe=list(range(6000)),
            modeling_artifacts={
                "validation_strategy": {"horizon": 30, "n_splits": 8, "gap": 4},
                "profile": {"seasonal_periods": [12]},
            },
        )
        req = SimpleNamespace(
            path_params={},
            query_params={},
            url=SimpleNamespace(path="/v1/session/modeling/backtest"),
        )
        value = model_workloads(
            "modeling.backtest",
            req,
            {"model_id": "naive", "rows": 1, "horizon": 1, "n_splits": 1},
            session,
        )[0]
        self.assertEqual((value.rows, value.folds, value.horizon), (6000, 8, 34))


if __name__ == "__main__":
    unittest.main()
