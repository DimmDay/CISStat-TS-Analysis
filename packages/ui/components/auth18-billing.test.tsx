import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BillingPanel } from "./BillingPanel";
import { billingRequest, safeCheckout } from "../lib/billing";
import { TeamAccount } from "../lib/team";
jest.mock("../lib/billing", () => ({
  ...jest.requireActual("../lib/billing"),
  billingRequest: jest.fn(),
}));
const req = billingRequest as jest.Mock;
const account = {
  account_id: "account",
  entitlement_version: 3,
  seat_requests: [{ request_id: "request", state: "pending", seats: 4 }],
} as TeamAccount;
test("quote requires explicit confirmation; status never inferred from return URL", async () => {
  req.mockReset();
  req.mockResolvedValueOnce({
    quote_id: "q",
    digest: "digest",
    expires_at: "2099-01-01T00:00:00Z",
    snapshot: {
      amount_minor: 101,
      currency: "RUB",
      seats: 4,
      price_version: "v1",
      terms_version: "terms",
      sandbox: true,
      reduction_policy: "disabled",
    },
  });
  render(<BillingPanel account={account} />);
  fireEvent.click(screen.getByText("Рассчитать стоимость 4 мест"));
  await screen.findByText(/К оплате: 1.01 RUB/);
  expect(req).toHaveBeenCalledTimes(1);
  req.mockResolvedValueOnce({
    order_id: "o",
    state: "pending",
    checkout_url: null,
  });
  fireEvent.click(screen.getByText("Подтвердить предложение"));
  await waitFor(() => expect(req).toHaveBeenCalledTimes(2));
  expect(req.mock.calls[1][1]).toEqual({ quote_digest: "digest" });
  expect(screen.queryByText("Открыть ЮKassa")).toBeNull();
});
test("provider redirect allowlist excludes userinfo, HTTP and other hosts", () => {
  expect(safeCheckout("https://yoomoney.ru/checkout/a")).toBeTruthy();
  for (const value of [
    "http://yoomoney.ru/a",
    "https://yoomoney.ru.evil/a",
    "https://evil@yoomoney.ru/a",
    "javascript:alert(1)",
  ])
    expect(safeCheckout(value)).toBeUndefined();
});
