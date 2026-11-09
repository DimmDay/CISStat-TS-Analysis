/** Shared server handler. The API remains the authentication authority. */
import routes from "./proxy-routes.generated.json";
type Config = { origin: string; apiUrl: string };
const cookieNames = new Set([
  "__Host-cisstat_auth",
  "__Host-cisstat_csrf",
  "__Host-cisstat_demo_resume",
  "cisstat_session_id",
]);
const incoming = [
  "accept",
  "content-type",
  "range",
  "origin",
  "sec-fetch-site",
  "sec-fetch-mode",
  "sec-fetch-dest",
  "x-csrf-token",
  "x-csrf-request",
  "x-api-key",
  "idempotency-key",
];
const outgoing = [
  "content-type",
  "content-disposition",
  "content-range",
  "accept-ranges",
  "retry-after",
  "x-request-id",
];
const patterns = routes.map(({ method, path }) => ({
  method,
  re: new RegExp(
    "^" +
      path
        .split("/")
        .map((part) =>
          part.startsWith("{")
            ? "[A-Za-z0-9_.~-]+"
            : part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
        )
        .join("/") +
      "$",
  ),
}));
class Reject extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}
function fail(status: number, code: string): never {
  throw new Reject(status, code);
}
function error(status: number, code: string, csrf = false) {
  return new Response(
    JSON.stringify({
      detail: {
        code,
        message:
          status === 503 ? "Сервис временно недоступен" : "Запрос отклонён",
      },
    }),
    {
      status,
      headers: {
        "content-type": "application/json",
        "cache-control": "private, no-store",
        pragma: "no-cache",
        "x-content-type-options": "nosniff",
        ...(csrf ? { "x-cisstat-csrf": "required" } : {}),
      },
    },
  );
}
function configuration(config: Config) {
  const origin = new URL(config.origin),
    api = new URL(config.apiUrl);
  if (
    origin.origin !== config.origin ||
    origin.protocol !== "https:" ||
    origin.username ||
    origin.password ||
    origin.hostname.includes("*")
  )
    fail(503, "proxy_unavailable");
  if (
    api.username ||
    api.password ||
    api.hostname.includes("*") ||
    api.pathname !== "/" ||
    api.search ||
    api.hash ||
    (api.protocol !== "https:" && !httpUpstreamAllowed(api.hostname))
  )
    fail(503, "proxy_unavailable");
  return { origin: origin.origin, api };
}

// AUTH-06-OPS-PHASE1-V2.1 (2026-11-05, VM cisstat-api): инцидент первого
// входа -- web собран с NODE_ENV=production, внутренний хоп compose
// API_URL=http://api:8000 (приватная docker-сеть, наружу не торчит), и
// прежняя https-only гвард production отклоняла ЛЮБОЙ запрос /api/v1/* с
// 503 proxy_unavailable до пересылки в api (Vercel-эра проходила: render.com
// по https). Разрешение на http-хоп -- ЯВНОЕ операторское решение: реестр
// допуска CISSTAT_PROXY_HTTP_UPSTREAMS (имена через запятую, без учёта
// регистра). Fail-closed: переменная не задана -> прежнее поведение.
// Dev-loopback (не-production: 127.0.0.1/localhost/[::1]) сохранён как был.
function httpUpstreamAllowed(hostname: string): boolean {
  if (
    process.env.NODE_ENV !== "production" &&
    ["127.0.0.1", "localhost", "[::1]"].includes(hostname)
  )
    return true;
  return (process.env.CISSTAT_PROXY_HTTP_UPSTREAMS ?? "")
    .split(",")
    .map((name) => name.trim().toLowerCase())
    .includes(hostname.toLowerCase());
}
function requestCookies(raw: string) {
  if (raw.length > 8192) fail(400, "invalid_credential");
  const selected = new Map<string, string>();
  for (const part of raw.split(";")) {
    const at = part.indexOf("=");
    if (at < 0) continue;
    const name = part.slice(0, at).trim(),
      value = part.slice(at + 1).trim();
    if (!cookieNames.has(name)) continue;
    if (selected.has(name) || !/^[A-Za-z0-9_.-]*$/.test(value))
      fail(400, "invalid_credential");
    selected.set(name, value);
  }
  return selected;
}
function responseCookies(headers: Headers) {
  const getter = (headers as Headers & { getSetCookie?: () => string[] })
    .getSetCookie;
  const values = getter
    ? getter.call(headers)
    : (headers.get("set-cookie") ?? "")
        .split(/,(?=\s*[^;,\s=]+=)/)
        .filter(Boolean);
  const result: string[] = [];
  for (const value of values) {
    const [pair, ...attributes] = value.split(";").map((s) => s.trim()),
      name = pair.slice(0, pair.indexOf("="));
    if (!cookieNames.has(name)) continue;
    const attrs = new Map<string, string>(
      attributes.map((v): [string, string] => {
        const at = v.indexOf("=");
        return at < 0
          ? [v.toLowerCase(), ""]
          : [v.slice(0, at).toLowerCase(), v.slice(at + 1)];
      }),
    );
    if (attrs.has("domain") || attrs.get("path") !== "/")
      fail(502, "invalid_upstream_cookie");
    if (name === "cisstat_session_id") {
      result.push(
        pair +
          "; Path=/; Secure; HttpOnly; SameSite=Lax" +
          (attrs.has("max-age") ? "; Max-Age=" + attrs.get("max-age") : "") +
          (attrs.has("expires") ? "; Expires=" + attrs.get("expires") : ""),
      );
      continue;
    }
    if (
      !attrs.has("secure") ||
      !attrs.has("httponly") ||
      !["lax", "strict"].includes((attrs.get("samesite") ?? "").toLowerCase())
    )
      fail(502, "invalid_upstream_cookie");
    result.push(value);
  }
  return result;
}
async function readBody(request: Request, max: number) {
  if (Number(request.headers.get("content-length") ?? 0) > max)
    fail(413, "request_too_large");
  if (!request.body) return undefined;
  const reader = request.body.getReader(),
    chunks: Uint8Array[] = [];
  let size = 0,
    cancelled = false;
  const cancel = () => {
    cancelled = true;
    void reader.cancel().catch(() => {});
  };
  const timer = setTimeout(cancel, 15000);
  request.signal.addEventListener("abort", cancel, { once: true });
  try {
    if (request.signal.aborted) cancel();
    for (;;) {
      const part = await reader.read();
      if (cancelled) fail(408, "request_timeout");
      if (part.done) break;
      size += part.value.byteLength;
      if (size > max) {
        await reader.cancel();
        fail(413, "request_too_large");
      }
      chunks.push(part.value);
    }
    const joined = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      joined.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return joined.buffer;
  } finally {
    clearTimeout(timer);
    request.signal.removeEventListener("abort", cancel);
  }
}
export async function proxyRequest(
  request: Request,
  config: Config,
  upstream: typeof fetch = fetch,
): Promise<Response> {
  try {
    const { origin, api } = configuration(config),
      url = new URL(request.url),
      method = request.method.toUpperCase();
    if (!url.pathname.startsWith("/api/v1/") || /[%\\]/.test(url.pathname))
      fail(404, "route_not_found");
    const path = url.pathname.slice(4),
      matches = patterns.filter((p) => p.re.test(path));
    if (!matches.length) fail(404, "route_not_found");
    if (
      !matches.some((p) => p.method === method) ||
      (method === "GET" && path.endsWith("/restore"))
    )
      fail(405, "method_not_allowed");
    const source = request.headers.get("origin"),
      site = request.headers.get("sec-fetch-site");
    if (
      (source !== null && source !== origin) ||
      (site !== null && !["same-origin", "same-site", "none"].includes(site))
    )
      fail(403, "csrf_invalid");
    const selected = requestCookies(request.headers.get("cookie") ?? ""),
      unsafe = !["GET", "HEAD", "OPTIONS"].includes(method);
    if (unsafe && source !== origin) fail(403, "csrf_invalid");
    if (
      path === "/v1/auth/csrf" &&
      source === null &&
      !(request.headers.get("x-csrf-request") === "1" && site === "same-origin")
    )
      fail(403, "csrf_invalid");
    if (unsafe) {
      const proof = request.headers.get("x-csrf-token");
      if (
        !proof ||
        proof !== selected.get("__Host-cisstat_csrf") ||
        proof.length > 180
      )
        return error(403, "csrf_invalid", true);
    }
    const headers = new Headers();
    for (const name of incoming) {
      const value = request.headers.get(name);
      if (value !== null) headers.set(name, value);
    }
    if (selected.size)
      headers.set(
        "cookie",
        Array.from(selected, ([k, v]) => k + "=" + v).join("; "),
      );
    const result = await upstream(new URL(path + url.search, api), {
      method,
      headers,
      body: unsafe
        ? await readBody(
            request,
            path.startsWith("/v1/auth/") ? 16384 : 52 * 1024 * 1024,
          )
        : undefined,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(120000)]),
    });
    if (result.status >= 300 && result.status < 400) {
      await result.body?.cancel();
      fail(502, "upstream_redirect");
    }
    const output = new Headers({
      "cache-control": "private, no-store",
      pragma: "no-cache",
      "x-content-type-options": "nosniff",
      "content-security-policy":
        "default-src 'none'; frame-ancestors 'none'; sandbox",
    });
    for (const name of outgoing) {
      const value = result.headers.get(name);
      if (value !== null) output.set(name, value);
    }
    for (const value of responseCookies(result.headers))
      output.append("set-cookie", value);
    return new Response(result.body, {
      status: result.status,
      headers: output,
    });
  } catch (caught) {
    return caught instanceof Reject
      ? error(caught.status, caught.code)
      : error(503, "proxy_unavailable");
  }
}
export function firstPartyProxy(request: Request) {
  return proxyRequest(request, {
    origin: process.env.CISSTAT_AUTH_PUBLIC_ORIGIN ?? "",
    apiUrl: process.env.API_URL ?? "",
  });
}
