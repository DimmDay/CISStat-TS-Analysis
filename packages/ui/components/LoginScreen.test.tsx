import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LoginScreen } from "./LoginScreen";
import { AuthProvider } from "../context/AuthContext";
import { authMe, authCommand, AuthFailure } from "../lib/authClient";
jest.mock("../lib/authClient", () => ({
  ...jest.requireActual("../lib/authClient"),
  authMe: jest.fn(),
  authCommand: jest.fn(),
}));
const me = authMe as jest.Mock,
  command = authCommand as jest.Mock;
const session = {
  subject_id: "person",
  account_id: "account",
  auth_session_id: "sid",
  auth_method: "auth_session",
  role: "admin",
};
const challenge = {
  status: "challenge_required",
  purpose: "login",
  challenge_token: "c1_" + "A".repeat(43),
  expires_at: new Date(Date.now() + 300000).toISOString(),
};
function form() {
  const navigate = jest.fn();
  render(
    <AuthProvider>
      <LoginScreen returnTo="//evil.example" onNavigate={navigate} />
    </AuthProvider>,
  );
  return navigate;
}
async function password() {
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Войти" })).not.toBeDisabled(),
  );
  fireEvent.change(screen.getByLabelText("Логин"), {
    target: { value: "named-admin" },
  });
  fireEvent.change(screen.getByLabelText("Пароль"), {
    target: { value: "SECRET-PASSWORD" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Войти" }));
}
beforeEach(() => {
  jest.clearAllMocks();
  me.mockResolvedValue(null);
});
test("no redirect before MFA and server me", async () => {
  command
    .mockResolvedValueOnce(challenge)
    .mockResolvedValueOnce({ status: "authenticated" });
  const navigate = form();
  await password();
  await screen.findByLabelText("Код из приложения");
  expect(navigate).not.toHaveBeenCalled();
  me.mockResolvedValue(session);
  fireEvent.change(screen.getByLabelText("Код из приложения"), {
    target: { value: "123456" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить вход" }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/"));
});
test("recovery, enrollment, and one-time backup codes acknowledgement", async () => {
  command
    .mockResolvedValueOnce(challenge)
    .mockResolvedValueOnce({ ...challenge, purpose: "enroll_start" })
    .mockResolvedValueOnce({
      ...challenge,
      purpose: "enroll",
      secret: "BASE32KEY",
    })
    .mockResolvedValueOnce({
      status: "authenticated",
      recovery_codes: ["r1_SECRET"],
    });
  const navigate = form();
  await password();
  fireEvent.click(
    await screen.findByRole("button", { name: "Использовать резервный код" }),
  );
  fireEvent.change(screen.getByLabelText("Резервный код"), {
    target: { value: "r1_OLD" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Восстановить MFA" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Получить ключ настройки" }),
  );
  await screen.findByDisplayValue("BASE32KEY");
  me.mockResolvedValue(session);
  fireEvent.change(screen.getByLabelText("Код из приложения"), {
    target: { value: "123456" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить вход" }));
  await screen.findByText("r1_SECRET");
  expect(navigate).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Коды сохранены — продолжить" }),
  );
  expect(screen.queryByText("r1_SECRET")).not.toBeInTheDocument();
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/"));
});
test("errors do not echo private details or leave password", async () => {
  command.mockRejectedValue(new AuthFailure(503, "PRIVATE"));
  const navigate = form();
  await password();
  await screen.findByRole("alert");
  expect(navigate).not.toHaveBeenCalled();
  expect(document.body.textContent).not.toContain("PRIVATE");
  expect(screen.getByLabelText("Пароль")).toHaveValue("");
});
test("account choice requires password again", async () => {
  command
    .mockResolvedValueOnce({
      status: "account_required",
      accounts: [{ account_id: "own", label: "Личный аккаунт" }],
    })
    .mockResolvedValueOnce(challenge);
  form();
  await password();
  await screen.findByLabelText(/Аккаунт/);
  expect(screen.getByLabelText("Пароль")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Пароль"), {
    target: { value: "SECOND-PASSWORD" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Войти" }));
  await screen.findByLabelText("Код из приложения");
  expect(command).toHaveBeenNthCalledWith(2, "login", {
    login: "named-admin",
    password: "SECOND-PASSWORD",
    account_id: "own",
  });
});
test("expired challenge returns to login without redirect", async () => {
  command.mockResolvedValue({
    ...challenge,
    expires_at: new Date(Date.now() - 1).toISOString(),
  });
  const navigate = form();
  await password();
  await screen.findByText("Время подтверждения истекло. Войдите заново.");
  expect(navigate).not.toHaveBeenCalled();
});
test("issued session still needs successful me", async () => {
  command.mockResolvedValue({ status: "authenticated" });
  const navigate = form();
  await password();
  await screen.findByRole("alert");
  expect(navigate).not.toHaveBeenCalled();
});
