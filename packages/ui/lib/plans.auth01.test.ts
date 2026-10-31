import {
  capabilitiesFromDTO, getCapabilities, hasStageAccess, PLAN_DEFINITIONS, REGISTRY_VERSION,
  type CapabilitiesDTO,
} from "./plans";
import { ACCESS_REGISTRY } from "./access-contract.generated";
import { STAGE_DEFS } from "./stages";
import { NAVIGATOR_STOPS } from "./navigator-stops";

describe("AUTH-01 generated capability contract", () => {
  it.each(["demo", "starter"] as const)("%s has bounded baseline without legacy advanced access", plan => {
    const caps=getCapabilities("external_user", plan);
    expect(caps.registryVersion).toBe(REGISTRY_VERSION);
    expect(caps.canRunBaselineModels).toBe(true);
    expect(caps.canTuneModels).toBe(false);
    expect(caps.canTrainCustomModels).toBe(false);
    expect(caps.canTrainModels).toBe(false);
    expect(caps.baselineLimits.maxHorizon).toBeGreaterThan(0);
  });

  it("keeps the existing six progress stages and four application IDs", () => {
    expect(ACCESS_REGISTRY.stages.filter(s=>s.namespace==="scientific").map(s=>s.stage_id))
      .toEqual(STAGE_DEFS.map(s=>s.key));
    expect(ACCESS_REGISTRY.stages.filter(s=>s.namespace==="application").map(s=>s.stage_id))
      .toEqual(NAVIGATOR_STOPS.slice(6).map(s=>s.id));
  });

  it("does not infer application restrictions from a name in another namespace", () => {
    const demo=getCapabilities("external_user", "demo");
    expect(hasStageAccess(demo,"application","monitoring")).toBe(false);
    expect(hasStageAccess(demo,"service","documentation")).toBe(true);
    expect(hasStageAccess(demo,"scientific","eda")).toBe(true);
    expect(hasStageAccess(demo,"application","new")).toBe(false);
    expect(hasStageAccess(getCapabilities("external_user","starter"),"application","causal")).toBe(true);
  });

  it("returns isolated copies from the legacy adapter", () => {
    const first=getCapabilities("external_user", "demo");
    first.restrictedStageIds.length=0;
    first.baselineLimits.maxRows=999;
    first.canTuneModels=true;
    expect(getCapabilities("external_user","demo")).toEqual(PLAN_DEFINITIONS.demo);
  });

  it("uses server-effective fields rather than recomputing from a role", () => {
    const value: CapabilitiesDTO={
      registry_version:REGISTRY_VERSION, capabilities_version:2,
      can_run_baseline_models:true, can_tune_models:false, can_train_custom_models:false,
      can_train_models:false, can_use_api:false, can_upload_own_data:true, can_save_history:false,
      restricted_stage_ids:["causal"],
      baseline_limits:{max_rows:100,max_folds:1,max_horizon:5,max_models:1,max_seasonal_period:12},
      max_dataset_rows:100,max_api_calls_per_month:0,max_analyses_total:1,trial_days:1,watermark_exports:true,
    };
    expect(capabilitiesFromDTO(value).baselineLimits.maxRows).toBe(100);
    expect(capabilitiesFromDTO(value).canTuneModels).toBe(false);
    expect(()=>capabilitiesFromDTO({...value, registry_version:"old"} as unknown as CapabilitiesDTO)).toThrow("version");
  });
});
