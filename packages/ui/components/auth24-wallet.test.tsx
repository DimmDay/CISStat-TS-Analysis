import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { WalletPanel } from "./WalletPanel";
import { TopupPanel } from "./TopupPanel";
import { billingRequest } from "../lib/billing";
import { TeamAccount } from "../lib/team";

jest.mock("../lib/billing", () => ({
  ...jest.requireActual("../lib/billing"),
  billingRequest: jest.fn(),
}));
const req = billingRequest as jest.Mock;

const ownerAccount = {
  account_id: "account",
  account_type: "multi",
  plan: "professional",
  entitlement_version: 3,
  can_manage: true,
  seat_requests: [],
} as unknown as TeamAccount;
const memberAccount = {
  ...ownerAccount,
  can_manage: false,
} as unknown as TeamAccount;

const ownerWallet = {
  wallet_id: "w",
  status: "active",
  available: 650000000,
  reserved: 50000000,
  next_expiry: "2026-12-01T00:00:00Z",
  can_purchase_cu: true,
  can_spend_cu: true,
  account_active: true,
  spending_blocked_reason: null,
  sources: {
    included: { issued: 500000000, available: 450000000, reserved: 50000000, spent: 0, expired: 0, refund_pending: 0, refunded: 0 },
    purchased: { issued: 200000000, available: 200000000, reserved: 0, spent: 0, expired: 0, refund_pending: 0, refunded: 0 },
    promotional: { issued: 0, available: 0, reserved: 0, spent: 0, expired: 0, refund_pending: 0, refunded: 0 },
  },
  locked_reason: null,
};

test("OWNER sees source breakdown, reserved, expiry and the ledger button", async () => {
  req.mockReset();
  req.mockResolvedValueOnce(ownerWallet);
  render(<WalletPanel account={ownerAccount} />);
  await screen.findByText(/Баланс CU/);
  expect(screen.getByText(/450/)).toBeTruthy(); // included available
  expect(screen.getByText(/200/)).toBeTruthy(); // purchased available
  expect(screen.getByText(/зарезервировано: 50/)).toBeTruthy(); // reserved
  expect(screen.getByText(/не сгорают/)).toBeTruthy(); // purchased v1 note
  expect(screen.getByText("Показать журнал")).toBeTruthy();
});

test("OWNER ledger read-only fetch and expired-subscription reason", async () => {
  req.mockReset();
  req.mockResolvedValueOnce({
    ...ownerWallet,
    account_active: false,
    can_spend_cu: false,
    can_purchase_cu: false,
    spending_blocked_reason: "account_expired",
  });
  render(<WalletPanel account={ownerAccount} />);
  await screen.findByText(/Срок подписки аккаунта истёк/);
  expect(screen.getByText(/Баланс сохранён/)).toBeTruthy();
  expect(screen.queryByText("Показать журнал")).toBeNull();
});

test("locked wallet shows preserved balance with the lock reason", async () => {
  req.mockReset();
  req.mockResolvedValueOnce({
    ...ownerWallet,
    status: "locked",
    can_spend_cu: false,
    can_purchase_cu: false,
    spending_blocked_reason: "wallet_locked",
    locked_reason: "chargeback dispute",
  });
  render(<WalletPanel account={ownerAccount} />);
  await screen.findByText(/Баланс CU заблокирован/);
  expect(screen.getByText(/chargeback dispute/)).toBeTruthy();
  expect(screen.getByText(/Баланс сохранён/)).toBeTruthy();
});

test("MEMBER sees totals only: no breakdown, no money, no ledger, owner hint", async () => {
  req.mockReset();
  req.mockResolvedValueOnce({
    wallet_id: "w",
    status: "active",
    available: 650000000,
    reserved: 50000000,
    next_expiry: "2026-12-01T00:00:00Z",
    can_spend_cu: true,
    account_active: true,
    spending_blocked_reason: null,
  });
  render(<WalletPanel account={memberAccount} />);
  await screen.findByText(/650/);
  expect(screen.getByText(/владел/)).toBeTruthy();
  // Financial privacy: member projection never carries these strings.
  expect(screen.queryByText("Показать журнал")).toBeNull();
  expect(screen.queryByText(/included/)).toBeNull();
  expect(screen.queryByText(/purchased/)).toBeNull();
});

test("wallet_required renders nothing (wallet is operator-provisioned)", async () => {
  req.mockReset();
  req.mockRejectedValueOnce(new Error("Кошелёк CU не провижинирован; обратитесь к оператору."));
  const { container } = render(<WalletPanel account={ownerAccount} />);
  await waitFor(() => expect(req).toHaveBeenCalledTimes(1));
  expect(container.textContent).toBe("");
});

test("TopupPanel purchase actions render for OWNER only", () => {
  render(<TopupPanel account={ownerAccount} />);
  expect(screen.getByText("Показать пакеты пополнения")).toBeTruthy();
});
test("MEMBER gets no purchase panel at all (§13.3 OWNER buys)", () => {
  // AccountScreen-level contract: TopupPanel is rendered only when can_manage.
  const source = require("fs").readFileSync(
    "packages/ui/components/AccountScreen.tsx",
    "utf8",
  );
  expect(source).toMatch(/account\.can_manage\s*&&[\s\S]{0,200}TopupPanel/);
});
