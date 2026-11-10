import { apiFetch, csrfProof } from "./browserTransport";
export async function billingRequest(path: string, body?: unknown) {
  const r = await apiFetch("/api/v1/billing" + path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers:
      body === undefined
        ? {}
        : {
            "Content-Type": "application/json",
            "X-CSRF-Token": await csrfProof(),
          },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const code = await r
      .json()
      .then((v) => v.detail?.code)
      .catch(() => "");
    const messages: Record<string, string> = {
      billing_not_configured: "Оплата ещё не настроена.",
      billing_cycle_unavailable:
        "Платёжный цикл ещё не настроен. Обратитесь к оператору.",
      recent_login_required:
        "Войдите заново и подтвердите MFA, затем повторите действие.",
      billing_reduction_not_approved:
        "Условия уменьшения мест ещё не утверждены.",
    };
    throw new Error(
      messages[code] ??
        "Не удалось выполнить платёжный запрос. Обновите состояние; повторная оплата не требуется.",
    );
  }
  return r.json();
}
export function safeCheckout(value: unknown): string | undefined {
  if (typeof value !== "string") return;
  try {
    const u = new URL(value);
    if (
      u.protocol === "https:" &&
      ["yoomoney.ru", "yookassa.ru"].includes(u.hostname) &&
      !u.username &&
      !u.password &&
      (!u.port || u.port === "443")
    )
      return u.href;
  } catch {}
}
