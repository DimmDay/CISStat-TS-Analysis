"use client";
import { useRef, useState } from "react";
import { billingRequest, safeCheckout } from "../lib/billing";
import { commandKey, TeamAccount } from "../lib/team";
type Package = {
  package_id: string;
  title: string;
  units: number;
  price_minor: number;
  currency: string;
  price_version: string;
  terms_version: string;
};
type Order = {
  order_id: string;
  state: string;
  units: number;
  checkout_url: string | null;
};
type Quote = {
  quote_id: string;
  digest: string;
  expires_at: string;
  snapshot: {
    title: string;
    units: number;
    amount_minor: number;
    currency: string;
    price_version: string;
    terms_version: string;
  };
};
const STATES: Record<string, string> = {
  pending: "Ожидает оплаты или сверки",
  credited: "CU зачислены на баланс аккаунта",
  canceled: "Платёж отменён",
  review_required: "Нужна сверка оператора; не оплачивайте повторно",
  paid_review: "Оплата получена; требуется проверка оператора",
};
const REFUND_STATES: Record<string, string> = {
  pending: "Возврат создан; CU под удержанием до подтверждения провайдером",
  refunded: "Возврат выполнен; CU погашены",
  failed: "Возврат не выполнен; CU разблокированы",
  review_required: "Нужна сверка оператора",
};
export function TopupPanel({ account }: { account: TeamAccount }) {
  const [packages, setPackages] = useState<Package[] | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [refunds, setRefunds] = useState<Record<string, { refund_id: string; state: string }>>({});
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
      setError(e instanceof Error ? e.message : "Пополнение недоступно.");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="space-y-2 rounded border p-3">
      <h2>Пополнение баланса CU</h2>
      <p>
        Покупка CU не меняет тариф, места и права доступа. Возврат со страницы
        оплаты не подтверждает платёж: статус появится после проверки
        провайдером.
      </p>
      <button
        disabled={busy}
        onClick={() =>
          void run(async () => {
            setQuote(null);
            const data = await billingRequest(`/${account.account_id}/topups`);
            setPackages(data.packages);
            setOrders(data.orders);
          })
        }
      >
        Показать пакеты пополнения
      </button>
      {packages?.length === 0 && (
        <p>Пополнение CU ещё не настроено. Обратитесь к оператору.</p>
      )}
      {packages?.map((p) => (
        <button
          key={p.package_id}
          disabled={busy}
          onClick={() =>
            void run(async () => {
              setQuote(
                await billingRequest(`/${account.account_id}/topup-quotes`, {
                  package_id: p.package_id,
                  expected_version: account.entitlement_version,
                  reason: "OWNER requested top-up quote",
                  idempotency_key: commandKey(),
                }),
              );
            })
          }
        >
          {p.title}: {(p.units / 1000000).toFixed(0)} CU за{" "}
          {(p.price_minor / 100).toFixed(2)} {p.currency}
        </button>
      ))}
      {quote && (
        <div>
          <p>
            {quote.snapshot.title}:{" "}
            {(quote.snapshot.units / 1000000).toFixed(0)} CU к оплате{" "}
            {(quote.snapshot.amount_minor / 100).toFixed(2)}{" "}
            {quote.snapshot.currency}.
          </p>
          <p>
            Прайс: {quote.snapshot.price_version}; условия:{" "}
            {quote.snapshot.terms_version}. Предложение до {quote.expires_at}.
          </p>
          <button
            disabled={busy || Date.now() >= Date.parse(quote.expires_at)}
            onClick={() =>
              void run(async () => {
                const order = await billingRequest(
                  `/${account.account_id}/topups`,
                  {
                    quote_id: quote.quote_id,
                    quote_digest: quote.digest,
                    expected_version: account.entitlement_version,
                    reason: "OWNER confirmed top-up quote",
                    idempotency_key: commandKey(),
                  },
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
          Заказ {o.order_id} ({(o.units / 1000000).toFixed(0)} CU):{" "}
          {STATES[o.state] ?? "Требуется проверка"}
          {o.state === "pending" && safeCheckout(o.checkout_url) && (
            <a
              href={safeCheckout(o.checkout_url)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Открыть ЮKassa
            </a>
          )}
          {o.state === "credited" && (
            <>
              {" "}
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const refund = await billingRequest(
                      `/${account.account_id}/topups/${o.order_id}/refunds`,
                      {
                        expected_version: account.entitlement_version,
                        reason: "OWNER requested self-service refund of the unused purchased lot",
                        idempotency_key: commandKey(),
                      },
                    );
                    setRefunds((old) => ({
                      ...old,
                      [o.order_id]: {
                        refund_id: refund.refund_id,
                        state: refund.state,
                      },
                    }));
                  })
                }
              >
                Запросить возврат
              </button>
              {refunds[o.order_id] && (
                <span>
                  {" "}
                  Возврат: {REFUND_STATES[refunds[o.order_id].state] ?? refunds[o.order_id].state}
                </span>
              )}
            </>
          )}
        </p>
      ))}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
