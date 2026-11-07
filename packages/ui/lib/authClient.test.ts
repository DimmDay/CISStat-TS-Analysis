import { safeReturnTo, authMe, AuthFailure } from "./authClient";
// Wire fixture follows the server DTO, independent of the principal's role.
const caps = {
  registry_version: "authz-registry/1", capabilities_version: 2,
  can_run_baseline_models: true, can_tune_models: false, can_train_custom_models: false,
  restricted_stage_ids: ["scenario", "causal", "decision", "monitoring"],
  baseline_limits: { max_rows: 5000, max_folds: 3, max_horizon: 24, max_seasonal_period: 366, max_models: 3 },
  can_train_models: false, can_use_api: false, can_save_history: false, can_upload_own_data: true,
  max_dataset_rows: 5000, max_api_calls_per_month: 0, max_analyses_total: 10,
  trial_days: 14, watermark_exports: true,
};
test("return_to is an exact local allowlist without query/hash/token", () => {
  for (const value of [
    "//evil.example",
    "https://evil.example",
    "/\\evil.example",
    "/%2f%2fevil.example",
    "/admin?token=secret",
    "/admin#secret",
    "javascript:alert(1)",
    null,
    ["/admin", "//evil"],
  ])
    expect(safeReturnTo(value)).toBe("/");
  expect(safeReturnTo("/admin")).toBe("/admin");
  expect(safeReturnTo("/upload")).toBe("/upload");
});
test("me projects safe fields; 503 is unavailable, only 401 is anonymous", async () => {
  const data = {
    subject_id: "person",
    account_id: "account",
    auth_method: "auth_session",
    role: "admin", account_plan: "demo", account_type: "mono",
    entitlement_version: 9, plan_expires_at: null, capabilities: caps,
    token: "SECRET",
  };
  global.fetch = jest
    .fn()
    .mockResolvedValue({ ok: true, status: 200, json: async () => data });
  expect(await authMe()).not.toHaveProperty("token");
  const session = await authMe();
  expect(session?.capabilities.can_tune_models).toBe(false);
  expect(session?.account_plan).toBe("demo");
  expect(session?.entitlement_version).toBe(9);
  (global.fetch as jest.Mock).mockResolvedValue({
    ok: false,
    status: 503,
    json: async () => ({ detail: { code: "unavailable", message: "PRIVATE" } }),
  });
  await expect(authMe()).rejects.toBeInstanceOf(AuthFailure);
  (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 401 });
  expect(await authMe()).toBeNull();
});

test("me refuses missing or unsupported effective capabilities instead of role fallback", async () => {
  for (const capabilities of [undefined, null, { ...caps, capabilities_version: 999 }]) {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({
      subject_id: "person", account_id: "account", auth_method: "auth_session",
      role: "admin", account_plan: "demo", account_type: "mono",
      entitlement_version: 9, plan_expires_at: null, capabilities,
    }) });
    await expect(authMe()).rejects.toBeInstanceOf(AuthFailure);
  }
});
