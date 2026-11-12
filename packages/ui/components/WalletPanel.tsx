"use client";
import { useEffect, useRef, useState } from "react";
import { billingRequest } from "../lib/billing";
import { TeamAccount } from "../lib/team";

type WalletView = {
  wallet_id: string;
  status: string;
  available: number;
  reserved: number;
  next_expiry: string | null;
  can_purchase_cu: boolean;
  can_spend_cu: boolean;
  account_active: boolean;
  spending_blocked_reason: string | null;
  sources?: Record<
    string,
    {
      issued: number;
      available: number;
      reserved: number;
      spent: number;
      expired: number;
      refund_pending: number;
      refunded: number;
    }
  >;
  locked_reason?: string | null;
};

type LedgerView = {
  lots: {
    lot_id: string;
    source: string;
    available: number;
    expires_at: string | null;
    origin_order: string | null;
    origin_ref: string | null;
  }[];
  postings: {
    posting_id: string;
    event: string;
    available_delta: number;
    created_at: string;
  }[];
  orders: { order_id: string; state: string; units: number }[];
  refunds: { refund_id: string; state: string; amount_minor: number; currency: string }[];
  disputes: { dispute_id: string; state: string; spent_units: number }[];
};

const SOURCE_LABELS: Record<string, string> = {
  included: "Включено по подписке (included)",
  purchased: "Купленные пакеты (purchased)",
  promotional: "Промо (promotional)",
};
const ORDER_STATES: Record<string, string> = {
  pending: "Ожидает оплаты",
  credited: "Зачтён",
  canceled: "Отменён",
  review_required: "Сверка оператора",
  paid_review: "Оплата получена; проверка оператора",
};
const REFUND_STATES: Record<string, string> = {
  pending: "Ожидает подтверждения провайдером",
  refunded: "Выполнен",
  failed: "Не выполнен",
  review_required: "Сверка оператора",
};
const DISPUTE_STATES: Record<string, string> = {
  open: "Открыт",
  lost: "Проигран",
  won: "Выигран",
};

function cu(micro: number): string {
  const whole = Math.trunc(micro / 1_000_000);
  const rest = Math.abs(micro) % 1_000_000;
  return rest === 0 ? String(whole) : (micro / 1_000_000).toFixed(3);
}

export function WalletPanel({ account }: { account: TeamAccount }) {
  const [wallet, setWallet] = useState<WalletView | null>(null),
    [ledger, setLedger] = useState<LedgerView | null>(null),
    [hidden, setHidden] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const lock = useRef(false);
  const owner = account.can_manage === true;
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const data = await billingRequest(`/${account.account_id}/wallet`);
        setWallet(data);
      } catch (e) {
        // A non-provisioned wallet is a normal state: the panel stays hidden.
        if (String((e as Error).message).includes("не провижинирован")) {
          setHidden(true);
        } else if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : "Баланс CU недоступен.");
        }
      }
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account.account_id]);
  async function run(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Баланс CU недоступен.");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  if (hidden) return null;
  if (!wallet) {
    return error ? (
      <section className="space-y-2 rounded border p-3">
        <h2>Баланс CU</h2>
        <p role="alert">{error}</p>
      </section>
    ) : null;
  }
  const locked = wallet.spending_blocked_reason === "wallet_locked";
  return (
    <section className="space-y-2 rounded border p-3">
      <h2>Баланс CU</h2>
      {!wallet.account_active && (
        <p>
          Срок подписки аккаунта истёк. Баланс сохранён; новые вычисления
          недоступны до восстановления доступа.
        </p>
      )}
      {locked && (
        <p>
          Баланс CU заблокирован. Баланс сохранён; новые вычисления
          недоступны до снятия блокировки.
          {owner && wallet.locked_reason ? ` Причина: ${wallet.locked_reason}.` : ""}
        </p>
      )}
      <p>
        Доступно: <strong>{cu(wallet.available)}</strong> CU
        {wallet.reserved > 0 && <> · зарезервировано: {cu(wallet.reserved)} CU</>}
        {wallet.next_expiry && (
          <>
            {" "}
            · ближайшее сгорание части баланса:{" "}
            {new Date(wallet.next_expiry).toLocaleString("ru-RU")}
          </>
        )}
        .
      </p>
      {owner && wallet.sources ? (
        <>
          <ul>
            {Object.entries(wallet.sources).map(([source, b]) => (
              <li key={source}>
                {SOURCE_LABELS[source] ?? source}: доступно {cu(b.available)} CU
                {b.reserved > 0 && <> · в резерве {cu(b.reserved)}</>}
                {b.refund_pending > 0 && <> · под возвратом {cu(b.refund_pending)}</>}
                {b.spent > 0 && <> · израсходовано {cu(b.spent)}</>}
                {b.expired > 0 && <> · сгорело {cu(b.expired)}</>}
              </li>
            ))}
          </ul>
          <p className="text-sm">
            Купленные пакеты (purchased) не сгорают в текущей версии; сгорают
            только включённые по подписке и промо-начисления.
          </p>
          {!ledger && !locked && wallet.account_active && (
            <button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  setLedger(
                    await billingRequest(`/${account.account_id}/wallet/ledger`),
                  );
                })
              }
            >
              Показать журнал
            </button>
          )}
          {ledger && (
            <div className="text-sm">
              <p>Журнал (последние записи):</p>
              <ul>
                {ledger.orders.map((o) => (
                  <li key={"o" + o.order_id}>
                    Заказ {o.order_id}: {ORDER_STATES[o.state] ?? o.state} ·{" "}
                    {cu(o.units)} CU
                  </li>
                ))}
                {ledger.refunds.map((r) => (
                  <li key={"r" + r.refund_id}>
                    Возврат {r.refund_id}: {REFUND_STATES[r.state] ?? r.state} ·{" "}
                    {(r.amount_minor / 100).toFixed(2)} {r.currency}
                  </li>
                ))}
                {ledger.disputes.map((d) => (
                  <li key={"d" + d.dispute_id}>
                    Спор {d.dispute_id}: {DISPUTE_STATES[d.state] ?? d.state} ·
                    расход {cu(d.spent_units)} CU
                  </li>
                ))}
                {ledger.postings.map((p) => (
                  <li key={p.posting_id}>
                    {new Date(p.created_at).toLocaleString("ru-RU")} · {p.event}{" "}
                    {p.available_delta >= 0 ? "+" : ""}
                    {cu(p.available_delta)} CU
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : (
        !owner && (
          <p className="text-sm">
            Пополнение и возвраты CU выполняет владелец аккаунта; обратитесь к
            нему при нехватке баланса.
          </p>
        )
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
