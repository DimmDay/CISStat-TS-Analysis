import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext";
import { authMe, authCommand, AuthFailure } from "../lib/authClient";
jest.mock("../lib/authClient", () => ({
  ...jest.requireActual("../lib/authClient"),
  authMe: jest.fn(),
  authCommand: jest.fn(),
}));
const me = authMe as jest.Mock,
  command = authCommand as jest.Mock,
  session = {
    subject_id: "person",
    account_id: "account",
    auth_session_id: "sid",
    auth_method: "auth_session",
    role: "admin",
  };
function Probe() {
  const a = useAuth();
  return (
    <>
      <output>
        {a.status}:{a.session?.subject_id ?? "none"}
      </output>
      <button onClick={() => void a.logout().catch(() => {})}>Logout</button>
    </>
  );
}
test("focus applies downgraded server caps under the same SID and invalidates old caches", async () => {
  const raw = { registry_version: "authz-registry/1", capabilities_version: 2,
    can_run_baseline_models: true, can_tune_models: true, can_train_custom_models: true,
    restricted_stage_ids: [], baseline_limits: { max_rows: 50000, max_folds: 5, max_horizon: 48, max_seasonal_period: 366, max_models: 3 },
    can_train_models: true, can_use_api: true, can_save_history: true, can_upload_own_data: true,
    max_dataset_rows: null, max_api_calls_per_month: 50000, max_analyses_total: null, trial_days: null, watermark_exports: false };
  function CapsProbe() {
    const auth = useAuth();
    return <output>{auth.session?.capabilities?.can_tune_models ? "tuning" : "baseline"}</output>;
  }
  me.mockResolvedValueOnce({ ...session, entitlement_version: 10, capabilities: raw });
  const reload = jest.fn();
  render(<AuthProvider onExternalSessionChange={reload}><CapsProbe /></AuthProvider>);
  await screen.findByText("tuning");
  me.mockResolvedValueOnce({ ...session, entitlement_version: 11, capabilities: { ...raw, can_tune_models: false } });
  fireEvent(window, new Event("focus"));
  await screen.findByText("baseline");
  expect(reload).toHaveBeenCalledTimes(1);
});
beforeEach(() => jest.clearAllMocks());
test("stale me cannot resurrect logged out identity", async () => {
  let resolve!: (v: unknown) => void;
  me.mockReturnValueOnce(new Promise((r) => (resolve = r)));
  command.mockResolvedValue(null);
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  fireEvent.click(screen.getByText("Logout"));
  await screen.findByText("anonymous:none");
  await act(async () => resolve(session));
  expect(screen.getByText("anonymous:none")).toBeInTheDocument();
});
test("503 unavailable, focus rereads revoke and clears caches on identity transition", async () => {
  me.mockRejectedValueOnce(new AuthFailure(503, "unavailable"));
  const reload = jest.fn();
  render(
    <AuthProvider onExternalSessionChange={reload}>
      <Probe />
    </AuthProvider>,
  );
  await screen.findByText("unavailable:none");
  me.mockResolvedValueOnce(session);
  fireEvent(window, new Event("focus"));
  await screen.findByText("authenticated:person");
  me.mockResolvedValueOnce(null);
  fireEvent(window, new Event("focus"));
  await screen.findByText("anonymous:none");
  expect(reload).toHaveBeenCalledTimes(1);
});
test("failed logout is not successful local signout", async () => {
  me.mockResolvedValue(session);
  command.mockRejectedValue(new AuthFailure(503, "unavailable"));
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  await screen.findByText("authenticated:person");
  fireEvent.click(screen.getByText("Logout"));
  await waitFor(() => expect(command).toHaveBeenCalledWith("logout"));
  expect(screen.getByText("authenticated:person")).toBeInTheDocument();
});
