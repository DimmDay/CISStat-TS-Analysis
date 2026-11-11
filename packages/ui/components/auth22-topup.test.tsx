import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TopupPanel } from "./TopupPanel";
import { billingRequest, safeCheckout } from "../lib/billing";
import { TeamAccount } from "../lib/team";
jest.mock("../lib/billing", () => ({
  ...jest.requireActual("../lib/billing"),
  billingRequest: jest.fn(),
}));
const req = billingRequest as jest.Mock;
const account = {
  account_id: "account",
  account_type: "multi",
  plan: "professional",
  entitlement_version: 3,
  seat_requests: [],
} as unknown as TeamAccount;
const packages = [
  {
    package_id: "pkg-1",
    title: "100 CU",
    units: 100000000,
    price_minor: 4900,
    currency: "RUB",
    price_version: "v1",
    terms_version: "t1",
  },
];
test("browser return never credits: order status stays server-side and pending", async () => {
  req.mockReset();
  req.mockResolvedValueOnce({ packages, orders: [] });
  render(<TopupPanel account={account} />);
  fireEvent.click(screen.getByText("Показать пакеты пополнения"));
  await screen.findByText(/100 CU за 49.00 RUB/);
  req.mockResolvedValueOnce({
    quote_id: "q",
    digest: "d",
    expires_at: "2099-01-01T00:00:00Z",
    snapshot: {
      title: "100 CU",
      units: 100000000,
      amount_minor: 4900,
      currency: "RUB",
      price_version: "v1",
      terms_version: "t1",
    },
  });
  fireEvent.click(screen.getByText(/100 CU: 100 CU за 49.00 RUB/));
  await screen.findByText(/Предложение до/);
  expect(screen.getByText(/100 CU к оплате 49.00 RUB/)).toBeTruthy();
  req.mockResolvedValueOnce({
    order_id: "o1",
    state: "pending",
    units: 100000000,
    checkout_url: null,
  });
  fireEvent.click(screen.getByText("Подтвердить предложение"));
  await waitFor(() => expect(req).toHaveBeenCalledTimes(3));
  expect(req.mock.calls[1][1]).toEqual({
    package_id: "pkg-1",
    expected_version: 3,
    reason: "OWNER requested top-up quote",
    idempotency_key: expect.any(String),
  });
  expect(req.mock.calls[2][0]).toBe("/account/topups");
  // No checkout link without a server-provided URL; state text is honest.
  expect(screen.queryByText("Открыть ЮKassa")).toBeNull();
  expect(screen.getByText(/Ожидает оплаты или сверки/)).toBeTruthy();
});
test("provider redirect allowlist is reused; expired quote disables confirm", async () => {
  expect(safeCheckout("https://yookassa.ru/checkout/a")).toBeTruthy();
  for (const value of [
    "http://yookassa.ru/a",
    "https://yookassa.ru.evil/a",
    "javascript:alert(1)",
  ])
    expect(safeCheckout(value)).toBeUndefined();
  req.mockReset();
  req.mockResolvedValueOnce({ packages, orders: [] });
  render(<TopupPanel account={account} />);
  fireEvent.click(screen.getByText("Показать пакеты пополнения"));
  await screen.findByText(/100 CU за 49.00 RUB/);
  req.mockResolvedValueOnce({
    quote_id: "q",
    digest: "d",
    expires_at: "2020-01-01T00:00:00Z",
    snapshot: {
      title: "100 CU",
      units: 100000000,
      amount_minor: 4900,
      currency: "RUB",
      price_version: "v1",
      terms_version: "t1",
    },
  });
  fireEvent.click(screen.getByText(/100 CU: 100 CU за 49.00 RUB/));
  await screen.findByText(/Предложение до/);
  expect(screen.getByText("Подтвердить предложение")).toHaveProperty(
    "disabled",
    true,
  );
});
test("empty catalog and terminal states render honest messages", async () => {
  req.mockReset();
  req.mockResolvedValueOnce({
    packages: [],
    orders: [
      { order_id: "o", state: "credited", units: 100000000, checkout_url: null },
    ],
  });
  render(<TopupPanel account={account} />);
  fireEvent.click(screen.getByText("Показать пакеты пополнения"));
  await screen.findByText("Пополнение CU ещё не настроено. Обратитесь к оператору.");
  expect(screen.getByText(/CU зачислены на баланс аккаунта/)).toBeTruthy();
  expect(req).toHaveBeenCalledWith("/account/topups");
});
