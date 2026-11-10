import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LoginScreen } from "./LoginScreen";
import { AuthProvider } from "../context/AuthContext";
import { authMe, authCommand, AuthFailure } from "../lib/authClient";
import { authEntryFlags } from "../lib/browserTransport";

jest.mock("../lib/authClient", () => ({
  ...jest.requireActual("../lib/authClient"),
  authMe: jest.fn(),
  authCommand: jest.fn(),
}));
jest.mock("../lib/browserTransport", () => ({
  ...jest.requireActual("../lib/browserTransport"),
  authEntryFlags: jest.fn(),
}));

const me = authMe as jest.Mock,
  command = authCommand as jest.Mock,
  flags = authEntryFlags as jest.Mock;



const session = {
  subject_id: "person",
  account_id: "account",
  auth_session_id: "sid",
  auth_method: "auth_session",
  role: "external_user",
  membership_role: "owner",
  account_plan: "starter",
  account_type: "mono",
  entitlement_version: 1,
  capabilities: {},
};

function renderForm(
  returnTo = "//evil.example",
  externalNavigate?: (url: string) => void,
) {
  const navigate = jest.fn();
  render(
    <AuthProvider>
      <LoginScreen
        returnTo={returnTo}
        onNavigate={navigate}
        onExternalNavigate={externalNavigate}
      />
    </AuthProvider>,
  );
  return navigate;
}

beforeEach(() => {
  jest.clearAllMocks();
  me.mockResolvedValue(null);
  flags.mockResolvedValue({ oidc: false, email_trial: false });
  window.history.replaceState(null, "", "/login");
});

test("external entry surfaces stay hidden when flags are off", async () => {
  flags.mockResolvedValue({ oidc: false, email_trial: false });
  renderForm();
  await screen.findByRole("button", { name: "Войти" });
  expect(
    screen.queryByRole("button", { name: "Войти через корпоративный SSO" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Отправить письмо для входа" }),
  ).not.toBeInTheDocument();
});

test("oidc start redirects top-level to the authorize URL", async () => {
  flags.mockResolvedValue({ oidc: true, email_trial: false });
  const assign = jest.fn();
  command.mockResolvedValueOnce({
    authorize_url: "https://idp.example.test/authorize?state=o1",
  });
  renderForm("//evil.example", assign);
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Войти через корпоративный SSO",
    }),
  );
  await waitFor(() =>
    expect(assign).toHaveBeenCalledWith(
      "https://idp.example.test/authorize?state=o1",
    ),
  );
  expect(command).toHaveBeenCalledWith("oidc/start", { purpose: "login" });
});

test("email trial start shows the uniform mailbox answer", async () => {
  flags.mockResolvedValue({ oidc: false, email_trial: true });
  command.mockResolvedValueOnce({ status: "email_sent" });
  renderForm();
  fireEvent.change(await screen.findByLabelText(/Вход по email/), {
    target: { value: "user@example.ru" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Отправить письмо для входа" }),
  );
  await screen.findByText(/Проверьте почту/);
  expect(command).toHaveBeenCalledWith("email/start", {
    email: "user@example.ru",
    purpose: "trial_login",
  });
});

test("email delivery failure keeps the closed answer and shows a safe error", async () => {
  flags.mockResolvedValue({ oidc: false, email_trial: true });
  command.mockRejectedValueOnce(
    new AuthFailure(503, "email_delivery_unavailable"),
  );
  renderForm();
  fireEvent.change(await screen.findByLabelText(/Вход по email/), {
    target: { value: "user@example.ru" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Отправить письмо для входа" }),
  );
  await screen.findByRole("alert");
  expect(screen.queryByText(/Проверьте почту/)).not.toBeInTheDocument();
});

test("magic link is confirmed by an explicit POST only", async () => {
  window.history.replaceState(
    null,
    "",
    "/login?email_challenge=e1_" + "A".repeat(43),
  );
  me.mockResolvedValueOnce(null).mockResolvedValue(session);
  command.mockResolvedValueOnce({ status: "authenticated" });
  const navigate = renderForm();
  fireEvent.click(
    await screen.findByRole("button", { name: "Подтвердить вход" }),
  );
  await waitFor(() =>
    expect(command).toHaveBeenCalledWith("email/consume", {
      token: "e1_" + "A".repeat(43),
    }),
  );
  expect(window.location.search).not.toContain("email_challenge");
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/"));
});

test("account_required with a selection token re-POSTs the same command", async () => {
  me.mockResolvedValueOnce(null).mockResolvedValue(session);
  command
    .mockResolvedValueOnce({
      status: "account_required",
      accounts: [{ account_id: "mono", label: "Личный аккаунт 1 — Стартовый" }],
      selection_token: "k1_" + "B".repeat(43),
    })
    .mockResolvedValueOnce({ status: "authenticated" });
  const navigate = renderFormWithLink();
  fireEvent.click(
    await screen.findByRole("button", { name: "Подтвердить вход" }),
  );
  await screen.findByLabelText(/Аккаунт/);
  fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
  await waitFor(() =>
    expect(command).toHaveBeenNthCalledWith(2, "email/consume", {
      selection: "k1_" + "B".repeat(43),
      account_id: "mono",
    }),
  );
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/"));
});

function renderFormWithLink() {
  window.history.replaceState(
    null,
    "",
    "/login?email_challenge=e1_" + "C".repeat(43),
  );
  return renderForm();
}
