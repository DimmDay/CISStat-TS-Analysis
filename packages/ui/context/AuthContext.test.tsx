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
