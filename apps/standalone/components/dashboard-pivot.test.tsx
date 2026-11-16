// apps/standalone/components/dashboard-pivot.test.tsx
//
// AUTH-KABINET-DEMO (2026-11-15): пивот /dashboard — цель надписи «Вход»
// ProductHeader. Сценарий тимлида: авторизован → /account, нет →
// /login?return_to=/account (safeReturnTo уже содержит /account).
// fail-closed: недоступный сервис — сообщение без автопереходов.
// Моки: authMe/authCommand (паттерн auth19), next/navigation useRouter.
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { AuthProvider } from "@cisstat/ui/context/AuthContext";
import { DashboardPivot } from "./DashboardPivot";
import { authMe } from "@cisstat/ui/lib/authClient";

jest.mock("@cisstat/ui/lib/authClient", () => ({
  ...jest.requireActual("@cisstat/ui/lib/authClient"),
  authMe: jest.fn(),
  authCommand: jest.fn(),
}));
const mockReplace = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

const me = authMe as jest.Mock;
const session = {
  subject_id: "person",
  account_id: "account",
  auth_session_id: "sid",
  auth_method: "auth_session",
  role: "external_user",
  membership_role: "owner",
  entitlement_version: 1,
};

beforeEach(() => {
  me.mockReset();
  mockReplace.mockReset();
});

function renderPivot() {
  return render(
    <AuthProvider>
      <DashboardPivot />
    </AuthProvider>,
  );
}

test("authenticated user is redirected to /account", async () => {
  me.mockResolvedValue(session);
  renderPivot();
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/account"));
  expect(mockReplace).not.toHaveBeenCalledWith("/login?return_to=/account");
});

test("anonymous visitor is redirected to /login with return_to=/account", async () => {
  me.mockResolvedValue(null);
  renderPivot();
  await waitFor(() =>
    expect(mockReplace).toHaveBeenCalledWith("/login?return_to=/account"),
  );
});

test("unavailable service fails closed without automatic redirects", async () => {
  me.mockRejectedValue(new Error("down"));
  renderPivot();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Сервис авторизации недоступен.",
  );
  expect(mockReplace).not.toHaveBeenCalled();
});

test("loading waits for authority without speculative redirect", async () => {
  let resolve!: (value: null) => void;
  me.mockReturnValue(
    new Promise<null>((done) => {
      resolve = done;
    }),
  );
  renderPivot();
  expect(screen.getByRole("status")).toHaveTextContent("Проверяем вход");
  expect(mockReplace).not.toHaveBeenCalled();
  resolve(null);
  await waitFor(() =>
    expect(mockReplace).toHaveBeenCalledWith("/login?return_to=/account"),
  );
});
