"""AUTH-01 contract tests: no scientific stack, DB or application startup."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.api.plans import AuthenticatedPrincipal, Capabilities, PLAN_DEFINITIONS, PlanName, Role


class RegistryTests(unittest.TestCase):
    def setUp(self):
        from apps.api import access_registry as registry
        self.r = registry
        self.demo = PLAN_DEFINITIONS[PlanName.DEMO]
        self.pro = PLAN_DEFINITIONS[PlanName.PROFESSIONAL]

    def work(self, **changes):
        values = dict(model_ids=("naive",), rows=100, folds=2, horizon=12,
                      seasonal_period=1, custom_parameters=False)
        values.update(changes)
        return self.r.ModelWorkload(**values)

    def test_demo_starter_split_without_reinterpreting_legacy_flag(self):
        for plan in (PlanName.DEMO, PlanName.STARTER):
            caps = PLAN_DEFINITIONS[plan]
            self.assertTrue(caps.can_run_baseline_models)
            self.assertFalse(caps.can_train_models)
            self.assertFalse(caps.can_tune_models)
            self.assertFalse(caps.can_train_custom_models)

    def test_all_six_scientific_stages_accessible_for_demo(self):
        for stage in ("upload", "validation", "preprocessing", "eda", "modeling", "forecasting"):
            self.assertTrue(self.r.stage_allowed(self.demo, "scientific", stage))
        for stage in ("scenario", "causal", "decision", "monitoring"):
            self.assertFalse(self.r.stage_allowed(self.demo, "application", stage))
            self.assertTrue(self.r.stage_allowed(self.pro, "application", stage))

    def test_unknown_stage_or_namespace_denied_even_with_empty_restrictions(self):
        for namespace, stage in [("scientific", "new"), ("invented", "eda"), ("application", "eda")]:
            self.assertFalse(self.r.stage_allowed(self.pro, namespace, stage))

    def test_baseline_model_allowlist_exact_and_case_sensitive(self):
        for model in ("naive", "seasonal_naive", "drift"):
            self.assertTrue(self.r.evaluate_operation(self.demo, "modeling.backtest", workload=self.work(model_ids=(model,))).allowed)
        for model in ("mean", "arima", "NAIVE", "naive ", "__unknown__"):
            self.assertFalse(self.r.evaluate_operation(self.demo, "modeling.backtest", workload=self.work(model_ids=(model,))).allowed)

    def test_unknown_operation_and_version_are_denied_for_every_plan(self):
        for caps in PLAN_DEFINITIONS.values():
            self.assertEqual(self.r.evaluate_operation(caps, "unknown").code, "unknown_operation")
            self.assertEqual(self.r.evaluate_entry(caps, "api:POST:/unreviewed").code, "unknown_entry")
            self.assertEqual(self.r.evaluate_operation(caps, "upload.file.load", registry_version="old").code, "registry_version_mismatch")

    def test_model_selector_is_mandatory_and_rejects_mixed_advanced_for_demo(self):
        self.assertEqual(self.r.evaluate_operation(self.demo, "modeling.backtest").code, "model_context_required")
        self.assertFalse(self.r.evaluate_operation(self.demo, "modeling.backtest", workload=self.work(model_ids=("naive", "arima"))).allowed)
        self.assertFalse(self.r.evaluate_operation(self.demo, "modeling.backtest", workload=self.work(custom_parameters=True)).allowed)

    def test_finite_baseline_bounds_exact_boundary(self):
        cap = self.demo.baseline_limits
        good = self.work(rows=cap.max_rows, folds=cap.max_folds, horizon=cap.max_horizon,
                         seasonal_period=cap.max_seasonal_period)
        self.assertTrue(self.r.evaluate_operation(self.demo, "modeling.backtest", workload=good).allowed)
        for field, limit in [("rows", cap.max_rows), ("folds", cap.max_folds), ("horizon", cap.max_horizon), ("seasonal_period", cap.max_seasonal_period)]:
            self.assertEqual(self.r.evaluate_operation(self.demo, "modeling.backtest", workload=self.work(**{field:limit+1})).code, "dataset_limit_exceeded" if field == "rows" else "baseline_limit_exceeded")

    def test_untrusted_workload_types_and_empty_model_sets_rejected(self):
        from pydantic import ValidationError
        for kwargs in ({"rows":True}, {"folds":0}, {"horizon":1.1}, {"model_ids":()}, {"model_ids":("naive", "naive")}):
            with self.assertRaises(ValidationError):
                self.work(**kwargs)

    def test_tuning_custom_and_placeholder_do_not_use_baseline_flag(self):
        for operation in ("modeling.tune", "modeling.tune.start", "modeling.tune.step", "modeling.tune.status", "modeling.tune.cancel", "modeling.custom.train"):
            self.assertFalse(self.r.evaluate_operation(self.demo, operation, workload=self.work()).allowed)
            self.assertTrue(self.r.evaluate_operation(self.pro, operation, workload=self.work()).allowed)
        self.assertEqual(self.r.evaluate_operation(self.pro, "modeling.train.placeholder").code, "operation_unavailable")

    def test_aliases_share_canonical_decision(self):
        paths = ("/v1/models/backtest", "/v1/internal/models/backtest", "/v1/session/modeling/backtest")
        self.assertEqual({self.r.REGISTRY.bindings["api:POST:"+p].operation_id for p in paths}, {"modeling.backtest"})
        for path in paths:
            self.assertFalse(self.r.evaluate_entry(self.demo, "api:POST:"+path, workload=self.work(model_ids=("arima",))).allowed)
        self.assertEqual(self.r.evaluate_entry(self.demo, "api:POST:/v1/session/modeling/backtest", workload=self.work()).code, "functional_allowed")
        self.assertEqual(self.r.evaluate_entry(self.demo, "api:POST:/v1/models/backtest", workload=self.work()).code, "api_not_included")

    def test_generic_jobs_are_tuning_and_legacy_aliases_cannot_bypass(self):
        for entry in ("api:POST:/v1/session/modeling/jobs/start", "api:POST:/v1/session/modeling/tuning/start", "api:POST:/v1/session/modeling/jobs/{job_id}/step", "api:GET:/v1/session/modeling/jobs/{job_id}"):
            self.assertFalse(self.r.evaluate_entry(self.demo, entry).allowed)
            self.assertTrue(self.r.REGISTRY.bindings[entry].operation_id.startswith("modeling.tune"))

    def test_application_aliases_and_monitoring_namespaces(self):
        for operation in ("application.causes.inspect", "application.scenarios.inspect", "application.decisions.inspect", "application.monitoring.inspect"):
            self.assertFalse(self.r.evaluate_operation(self.demo, operation).allowed)
            self.assertTrue(self.r.evaluate_operation(PLAN_DEFINITIONS[PlanName.STARTER], operation).allowed)
        self.assertTrue(self.r.evaluate_operation(self.demo, "eda.correlation").allowed)
        self.assertTrue(self.r.evaluate_operation(self.demo, "documentation.monitoring.read").allowed)

    def test_stage_selector_cannot_introduce_unknown_or_application_stage(self):
        for stage in (None, "unknown", "causal"):
            self.assertFalse(self.r.evaluate_entry(self.pro, "api:POST:/v1/session/stage/{stage}", stage=stage).allowed)
        self.assertTrue(self.r.evaluate_entry(self.demo, "api:POST:/v1/session/stage/{stage}", stage="eda").allowed)

    def test_analytical_caps_never_authorize_admin_or_scoped_service(self):
        for entry in ("api:GET:/v1/progress/admin/overview", "api:GET:/v1/logs/audit", "api:POST:/v1/documentation/org-profiles"):
            self.assertEqual(self.r.evaluate_entry(self.pro, entry).code, "external_policy_required")

    def test_legacy_constructed_caps_fail_closed_for_new_flags(self):
        caps = Capabilities(can_train_models=True, can_use_api=True, can_save_history=True, can_upload_own_data=True)
        self.assertFalse(caps.can_run_baseline_models)
        self.assertFalse(caps.can_tune_models)
        self.assertFalse(caps.can_train_custom_models)

    def test_principal_capabilities_are_copies_and_staff_compatibility_explicit(self):
        principal = AuthenticatedPrincipal(principal_id="fixture", role=Role.EXTERNAL_USER, plan=PlanName.DEMO)
        caps = principal.capabilities
        caps.can_tune_models = True
        self.assertFalse(principal.capabilities.can_tune_models)
        for role in (Role.ADMIN, Role.INTERNAL_ANALYST):
            self.assertTrue(AuthenticatedPrincipal(principal_id="fixture", role=role).capabilities.can_tune_models)

    def test_bindings_cover_all_api_and_task_aliases_of_auth00(self):
        report = json.loads((ROOT / "docs/auth00/inventory.json").read_text(encoding="utf-8"))
        expected = {e["id"] for e in report["entries"] if e["kind"] in {"api", "task_alias"}}
        self.assertEqual(set(self.r.REGISTRY.bindings), expected)
        for entry in report["entries"]:
            if entry["id"] in expected and entry["stage_namespace"] == "scientific":
                operation = self.r.REGISTRY.operations[self.r.REGISTRY.bindings[entry["id"]].operation_id]
                self.assertEqual(operation.stage_namespace, "scientific")

    def test_registry_rejects_invalid_references_duplicates_and_unknown_capabilities(self):
        from pydantic import ValidationError
        raw = self.r.REGISTRY.model_dump(mode="json")
        for mutate in (
            lambda d: d["bindings"]["api:GET:/health"].update(operation_id="typo"),
            lambda d: d["operations"]["modeling.backtest"].update(capability="typo"),
            lambda d: d["operations"]["modeling.backtest"].update(stage="unknown"),
            lambda d: d["operations"]["modeling.backtest"].update(operation_id="other"),
        ):
            candidate=copy.deepcopy(raw); mutate(candidate)
            with self.assertRaises(ValidationError): self.r.AccessRegistry.model_validate(candidate)

    def test_generated_contract_drift_gate(self):
        result = subprocess.run([sys.executable, "scripts/auth01/generate.py", "--check"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_serialized_restrictions_have_stable_order(self):
        self.assertEqual(self.demo.model_dump(mode="json")["restricted_stage_ids"], ["causal", "decision", "monitoring", "scenario"])

    def test_openapi_install_has_dtos_versions_and_route_binding_without_new_route(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app=FastAPI()
        @app.post("/v1/session/modeling/backtest", response_model=Capabilities)
        def sample(): return self.demo
        before = [r.path for r in app.routes]
        self.r.install_openapi_contract(app)
        schema=app.openapi()
        self.assertEqual(schema["components"]["schemas"]["Capabilities"], self.r.contract_openapi()["components"]["schemas"]["Capabilities"])
        self.assertEqual(schema["paths"]["/v1/session/modeling/backtest"]["post"]["x-cisstat-operation-id"], "modeling.backtest")
        self.assertEqual([r.path for r in app.routes],before)
        self.assertEqual(app.openapi(),schema)
        self.assertTrue(TestClient(app).post("/v1/session/modeling/backtest").json()["can_run_baseline_models"])

    def test_raw_json_duplicate_keys_are_rejected(self):
        with self.assertRaises(ValueError): self.r.load_registry('{"registry_version":"a","registry_version":"b"}')

    def test_saved_model_outputs_and_selection_need_same_fit_context(self):
        for entry in ("api:GET:/v1/session/modeling/state", "api:GET:/v1/session/modeling/card/{card_id}", "api:GET:/v1/session/modeling/forecast/{forecast_id}", "api:GET:/v1/session/modeling/forecast/{forecast_id}/export.csv", "api:POST:/v1/session/modeling/compare", "api:POST:/v1/session/modeling/select"):
            self.assertEqual(self.r.evaluate_entry(self.demo, entry).code,"model_context_required")
            self.assertFalse(self.r.evaluate_entry(self.demo, entry, workload=self.work(model_ids=("arima",))).allowed)
            self.assertTrue(self.r.evaluate_entry(self.demo, entry, workload=self.work()).allowed)

    def test_effective_dataset_ceiling_is_intersected_with_baseline_ceiling(self):
        caps=self.demo.model_copy(update={"max_dataset_rows":10})
        self.assertEqual(self.r.evaluate_operation(caps,"modeling.backtest",workload=self.work(rows=11)).code,"dataset_limit_exceeded")

    def test_inventory_gate_rejects_new_or_removed_entry(self):
        report=json.loads((ROOT/"docs/auth00/inventory.json").read_text(encoding="utf-8"))
        self.r.validate_inventory(report)
        report["entries"].append({"id":"api:POST:/unreviewed", "kind":"api"})
        with self.assertRaises(ValueError): self.r.validate_inventory(report)

    def test_generated_file_tampering_fails_read_only_check(self):
        from scripts.auth01.generate import check, generated_files
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for path,text in generated_files().items():
                target=root/path; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(text,encoding="utf-8",newline="\n")
            (root/"docs/auth00").mkdir()
            (root/"docs/auth00/inventory.json").write_bytes((ROOT/"docs/auth00/inventory.json").read_bytes())
            check(root)
            target=root/"packages/ui/lib/access-contract.generated.ts"
            original=target.read_text(encoding="utf-8")
            tampered=original.replace("canTuneModels: boolean", "canTuneModels: string")
            self.assertNotEqual(original,tampered)
            target.write_text(tampered,encoding="utf-8",newline="\n")
            with self.assertRaises(ValueError): check(root)
            self.assertEqual(target.read_text(encoding="utf-8"),tampered)


if __name__ == "__main__":
    unittest.main()
