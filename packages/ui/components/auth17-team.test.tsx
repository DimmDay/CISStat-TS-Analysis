import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { AccountScreen } from "./AccountScreen";
import { useAuth } from "../context/AuthContext";
import { teamRequest } from "../lib/team";
jest.mock("../context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("../lib/team", () => ({
  teamRequest: jest.fn(),
  commandKey: () => "test-key",
}));
const request = teamRequest as jest.Mock,
  auth = useAuth as jest.Mock;
const detail = {
  account_id: "account17",
  tenant_id: "tenant17",
  account_type: "multi",
  plan: "starter",
  seats: 2,
  occupied: 1,
  free_seats: 1,
  entitlement_version: 3,
  can_manage: true,
  members: [
    {
      subject_id: "owner17",
      account_role: "owner",
      status: "active",
      label: "Owner",
    },
  ],
  invitations: [],
  seat_requests: [],
};
beforeEach(() => {
  request.mockReset();
  auth.mockReturnValue({
    status: "authenticated",
    session: { subject_id: "owner17", account_id: "account17" },
    logout: jest.fn(),
  });
  request.mockImplementation(async (path: string = "") =>
    path === ""
      ? { current_account_id: "account17", accounts: [detail] }
      : detail,
  );
});
test("anonymous invitation page requires personal login and issues no requests", () => {
  auth.mockReturnValue({ status: "anonymous", session: null });
  render(<AccountScreen />);
  expect(screen.getByRole("link", { name: "Войти" })).toHaveAttribute(
    "href",
    "/login?return_to=%2Faccount",
  );
  expect(request).not.toHaveBeenCalled();
});
test("owner capacity change is explicitly pending and gated by reason", async () => {
  render(<AccountScreen />);
  const button = await screen.findByRole("button", { name: "Подать заявку" });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Причина действия"), {
    target: { value: "Нужен аналитик" },
  });
  request.mockImplementation(async (path: string = "", body?: unknown) =>
    body
      ? { state: "pending", capacity_changed: false }
      : path === ""
        ? { current_account_id: "account17", accounts: [detail] }
        : detail,
  );
  fireEvent.click(button);
  expect(await screen.findByRole("status")).toHaveTextContent(
    "До подтверждения места и квоты не изменяются",
  );
  expect(request).toHaveBeenCalledWith("/account17/seat-requests", {
    seats: 2,
    reason: "Нужен аналитик",
    expected_version: 3,
    idempotency_key: "test-key",
  });
});
test("member cannot see invite/capacity/transfer actions", async () => {
  request.mockImplementation(async (path: string = "") =>
    path === ""
      ? { current_account_id: "account17", accounts: [detail] }
      : { ...detail, can_manage: false },
  );
  render(<AccountScreen />);
  await screen.findByRole("heading", { name: "Участники" });
  expect(
    screen.queryByRole("button", { name: "Подать заявку" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Создать приглашение на 24 часа" }),
  ).not.toBeInTheDocument();
});
test("one-time invitation is visible only from successful command response", async () => {
  render(<AccountScreen />);
  await screen.findByRole("button", { name: "Создать приглашение на 24 часа" });
  fireEvent.change(screen.getByLabelText("Причина действия"), {
    target: { value: "Team" },
  });
  fireEvent.change(screen.getByLabelText("Получатель"), {
    target: { value: "bob@example.org" },
  });
  request.mockImplementation(async (path: string = "", body?: unknown) =>
    body
      ? { invitation_token: "i17_once" }
      : path === ""
        ? { current_account_id: "account17", accounts: [detail] }
        : detail,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Создать приглашение на 24 часа" }),
  );
  expect(await screen.findByLabelText("Выданный код приглашения")).toHaveValue(
    "i17_once",
  );
  fireEvent.click(screen.getByRole("button", { name: "Скрыть код" }));
  expect(
    screen.queryByLabelText("Выданный код приглашения"),
  ).not.toBeInTheDocument();
});

test("a personal trial OWNER is not offered leaving the last OWNER seat", async () => {
  request.mockImplementation(async (path: string = "") =>
    path === ""
      ? { current_account_id: "account17", accounts: [detail] }
      : { ...detail, account_type: "mono", plan: "demo", can_manage: false },
  );
  render(<AccountScreen />);
  await screen.findByRole("heading", { name: "Участники" });
  expect(
    screen.queryByRole("button", { name: "Покинуть команду" }),
  ).not.toBeInTheDocument();
});
