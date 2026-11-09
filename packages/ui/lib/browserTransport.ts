/** CSRF adapter; never monkey-patches global fetch. */
export const AUTH_PREFIX = "/api/v1/auth";
export async function csrfProof(signal?: AbortSignal): Promise<string> {
  const r = await fetch(AUTH_PREFIX + "/csrf", {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { "X-CSRF-Request": "1" },
    signal,
  });
  if (!r.ok) throw new Error("Не удалось защитить запрос. Повторите попытку.");
  const data = await r.json();
  if (
    typeof data.csrf_token !== "string" ||
    !/^c1\.[0-9]+\.[A-Za-z0-9_-]{32}\.[0-9a-f]{64}$/.test(data.csrf_token)
  )
    throw new Error("Некорректный ответ сервиса входа.");
  return data.csrf_token;
}
function governed(input: RequestInfo | URL) {
  if (typeof window === "undefined") return false;
  const raw =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
  const url = new URL(raw, window.location.origin);
  return (
    url.origin === window.location.origin && url.pathname.startsWith("/api/v1/")
  );
}
export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  if (!governed(input)) return fetch(input, init);
  const outgoingMethod = (init?.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(outgoingMethod)) {
    const headers = new Headers(init?.headers);
    if (!headers.has("Idempotency-Key"))
      headers.set(
        "Idempotency-Key",
        Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
          b.toString(16).padStart(2, "0"),
        ).join(""),
      );
    init = { ...init, headers };
  }
  const response = await fetch(input, init);
  const method = (
    init?.method ??
    (typeof Request !== "undefined" && input instanceof Request
      ? input.method
      : "GET")
  ).toUpperCase();
  // Reserved header is removed from all upstream responses. Only our local
  // refusal BEFORE forwarding can cause one resend, never an uncertain outcome.
  if (
    !["GET", "HEAD", "OPTIONS"].includes(method) &&
    response.status === 403 &&
    response.headers?.get("x-cisstat-csrf") === "required" &&
    !(typeof Request !== "undefined" && input instanceof Request) &&
    !(
      typeof ReadableStream !== "undefined" &&
      init?.body instanceof ReadableStream
    )
  ) {
    const proof = await csrfProof(init?.signal ?? undefined);
    const headers = new Headers(init?.headers);
    headers.set("X-CSRF-Token", proof);
    return fetch(input, { ...init, headers });
  }
  return response;
}
