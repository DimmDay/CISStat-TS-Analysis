"use client";
import { useRef, useState } from "react";
import { billingRequest, safeCheckout } from "../lib/billing";
import { commandKey, TeamAccount } from "../lib/team";
type Order = { order_id: string; state: string; checkout_url: string | null };
type Quote = {
  quote_id: string;
  digest: string;
  expires_at: string;
  snapshot: {
    amount_minor: number;
    currency: string;
    seats: number;
    terms_version: string;
    price_version: string;
    sandbox: boolean;
    reduction_policy: string;
    proration_at: string;
    cycle_ends_at: string;
  };
};
export function BillingPanel({ account }: { account: TeamAccount }) {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const lock = useRef(false);
  async function run(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Оплата недоступна.");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="space-y-2 rounded border p-3">
      <h2>Оплата изменения мест</h2>
      <p>
        Тестовый контур ЮKassa. Реальная оплата пока недоступна. Места появятся
        после подтверждения провайдером. Возврат со страницы оплаты не
        подтверждает платёж.
      </p>
      <button
        disabled={busy}
        onClick={() =>
          void run(async () => {
            const data = await billingRequest(
              `/${account.account_id}/subscription`,
            );
            setOrders(data.orders);
          })
        }
      >
        Обновить статус оплаты
      </button>
      {account.seat_requests
        .filter((r) => r.state === "pending")
        .map((r) => (
          <button
            key={r.request_id}
            disabled={busy}
            onClick={() =>
              void run(async () => {
                setQuote(null);
                setQuote(
                  await billingRequest(`/${account.account_id}/quotes`, {
                    request_id: r.request_id,
                    expected_version: account.entitlement_version,
                    reason: "OWNER requested seat quote",
                    idempotency_key: commandKey(),
                  }),
                );
              })
            }
          >
            Рассчитать стоимость {r.seats} мест
          </button>
        ))}
      {quote && (
        <div>
          <p>
            Всего мест: {quote.snapshot.seats}. К оплате:{" "}
            {(quote.snapshot.amount_minor / 100).toFixed(2)}{" "}
            {quote.snapshot.currency}.
          </p>
          <p>
            Прайс: {quote.snapshot.price_version}; условия:{" "}
            {quote.snapshot.terms_version}. Предложение до {quote.expires_at}.
          </p>
          <p>
            Период расчёта: {quote.snapshot.proration_at} —{" "}
            {quote.snapshot.cycle_ends_at}.
          </p>
          {quote.snapshot.reduction_policy === "no-refund" && (
            <p>
              При уменьшении мест возврат за текущий период не предусмотрен.
            </p>
          )}
          <button
            disabled={busy || Date.now() >= Date.parse(quote.expires_at)}
            onClick={() =>
              void run(async () => {
                const order = await billingRequest(
                  `/${account.account_id}/quotes/${quote.quote_id}/confirm`,
                  { quote_digest: quote.digest },
                );
                setOrders((old) => [
                  order,
                  ...old.filter((o) => o.order_id !== order.order_id),
                ]);
                setQuote(null);
              })
            }
          >
            Подтвердить предложение
          </button>
        </div>
      )}
      {orders.map((o) => (
        <p key={o.order_id}>
          Заказ {o.order_id}:{" "}
          {(
            {
              pending: "Ожидает оплаты или сверки",
              applied: "Места подтверждены — обновите аккаунт",
              canceled: "Платёж отменён",
              review_required:
                "Нужна сверка оператором; не оплачивайте повторно",
              paid_review: "Оплата получена; требуется проверка оператором",
            } as Record<string, string>
          )[o.state] ?? "Требуется проверка"}
          {o.state === "pending" && safeCheckout(o.checkout_url) && (
            <a
              href={safeCheckout(o.checkout_url)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Открыть ЮKassa
            </a>
          )}
        </p>
      ))}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
