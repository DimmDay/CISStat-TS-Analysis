/** @jest-environment node */
import { proxyRequest } from "./firstPartyProxy";
const origin = "https://standalone.example",
  config = { origin, apiUrl: "https://api.example" };
const request = (
  method = "GET",
  path = "/api/v1/auth/me",
  headers: Record<string, string> = {},
) =>
  new Request(origin + path, {
    method,
    headers: { "sec-fetch-site": "same-origin", ...headers },
    ...(method === "POST" ? { body: "{}" } : {}),
  });
let upstream: jest.Mock;
beforeEach(() => {
  upstream = jest
    .fn()
    .mockResolvedValue(
      new Response("{}", { headers: { "content-type": "application/json" } }),
    );
});
test("both origins use fixed target, only allowlisted headers and cookies", async () => {
  for (const site of [origin, "https://embedded.example"]) {
    const r = await proxyRequest(
      new Request(site + "/api/v1/auth/me", {
        headers: {
          origin: site,
          cookie:
            "portal=SECRET; __Host-cisstat_auth=sid; cisstat_session_id=resource",
          "x-role": "admin",
          "x-subject-id": "victim",
          "x-forwarded-host": "evil",
          authorization: "Bearer forged",
        },
      }),
      { ...config, origin: site },
      upstream,
    );
    expect(r.status).toBe(200);
    const [target, init] = upstream.mock.calls.at(-1)!;
    expect(String(target)).toBe("https://api.example/v1/auth/me");
    const h = new Headers(init.headers);
    expect(h.get("cookie")).toBe(
      "__Host-cisstat_auth=sid; cisstat_session_id=resource",
    );
    for (const name of [
      "host",
      "authorization",
      "x-role",
      "x-subject-id",
      "x-forwarded-host",
    ])
      expect(h.has(name)).toBe(false);
    expect(init.redirect).toBe("manual");
    expect(init.cache).toBe("no-store");
  }
});
test("missing/null/forged/sibling Origin or cross-site fails before forwarding", async () => {
  for (const headers of [
    {},
    { origin: "null" },
    { origin: origin + ".evil" },
    { origin: "https://embedded.example" },
    { origin, "sec-fetch-site": "cross-site" },
  ])
    expect(
      (
        await proxyRequest(
          request("POST", "/api/v1/auth/logout", headers),
          config,
          upstream,
        )
      ).status,
    ).toBe(403);
  expect(upstream).not.toHaveBeenCalled();
});
test("reserved CSRF retry signal is only issued before forwarding", async () => {
  const r = await proxyRequest(
    request("POST", "/api/v1/auth/logout", { origin }),
    config,
    upstream,
  );
  expect(r.headers.get("x-cisstat-csrf")).toBe("required");
  expect(upstream).not.toHaveBeenCalled();
  const headers = {
    origin,
    cookie: "__Host-cisstat_csrf=proof",
    "x-csrf-token": "proof",
  };
  expect(
    (
      await proxyRequest(
        request("POST", "/api/v1/auth/logout", headers),
        config,
        upstream,
      )
    ).status,
  ).toBe(200);
  expect(upstream).toHaveBeenCalledTimes(1);
  upstream.mockResolvedValue(
    new Response("{}", {
      status: 403,
      headers: { "x-cisstat-csrf": "required" },
    }),
  );
  expect(
    (await proxyRequest(request(), config, upstream)).headers.has(
      "x-cisstat-csrf",
    ),
  ).toBe(false);
});
test("unknown routes/methods/encoded traversal and duplicate cookies are rejected", async () => {
  for (const path of ["/api/v1/not-reviewed", "/api/v1/auth/me%2F..%2Flogin"])
    expect(
      (await proxyRequest(request("GET", path), config, upstream)).status,
    ).toBe(404);
  expect((await proxyRequest(request("DELETE"), config, upstream)).status).toBe(
    405,
  );
  expect(
    (
      await proxyRequest(
        request("GET", "/api/v1/auth/me", {
          cookie: "__Host-cisstat_auth=a; __Host-cisstat_auth=b",
        }),
        config,
        upstream,
      )
    ).status,
  ).toBe(400);
  expect(upstream).not.toHaveBeenCalled();
});
test("multiple cookies retain expiry commas; auth cookie weakening fails closed", async () => {
  const h = new Headers();
  h.append(
    "set-cookie",
    "__Host-cisstat_auth=sid; Path=/; Secure; HttpOnly; SameSite=Lax",
  );
  h.append(
    "set-cookie",
    "__Host-cisstat_csrf=proof; Path=/; Secure; HttpOnly; SameSite=Lax; Expires=Sun, 01 Nov 2026 15:00:00 GMT",
  );
  h.append("set-cookie", "portal=secret; Path=/");
  upstream.mockResolvedValue(new Response("{}", { headers: h }));
  const r = await proxyRequest(request(), config, upstream);
  expect(r.headers.getSetCookie()).toHaveLength(2);
  expect(r.headers.get("cache-control")).toContain("no-store");
  expect(r.headers.getSetCookie().join(";")).toContain("Sun, 01 Nov");
  upstream.mockResolvedValue(
    new Response("{}", {
      headers: {
        "set-cookie":
          "__Host-cisstat_auth=sid; Domain=example; Path=/; Secure; HttpOnly; SameSite=Lax",
      },
    }),
  );
  expect((await proxyRequest(request(), config, upstream)).status).toBe(502);
});
test("upstream redirects never followed; error details never disclosed", async () => {
  upstream.mockResolvedValue(
    new Response(null, {
      status: 302,
      headers: { location: "https://evil.example/?token=SECRET" },
    }),
  );
  const r = await proxyRequest(request(), config, upstream);
  expect(r.status).toBe(502);
  expect(r.headers.has("location")).toBe(false);
  upstream.mockRejectedValue(new Error("PRIVATE_UPSTREAM"));
  const fail = await proxyRequest(request(), config, upstream);
  expect(fail.status).toBe(503);
  expect(await fail.text()).not.toContain("PRIVATE_UPSTREAM");
});
test("bad config and oversized auth body never reach upstream", async () => {
  for (const cfg of [
    { ...config, origin: "https://*.vercel.app" },
    { ...config, apiUrl: "https://user:secret@api.example" },
    { ...config, apiUrl: "https://api.example/v1" },
  ])
    expect((await proxyRequest(request(), cfg, upstream)).status).toBe(503);
  const huge = new Request(origin + "/api/v1/auth/login", {
    method: "POST",
    body: "x".repeat(20000),
    headers: {
      origin,
      cookie: "__Host-cisstat_csrf=proof",
      "x-csrf-token": "proof",
      "content-length": "20000",
    },
  });
  expect((await proxyRequest(huge, config, upstream)).status).toBe(413);
  expect(upstream).not.toHaveBeenCalled();
});
test("binary response and insecure legacy pointer deletion are transported safely", async () => {
  upstream.mockResolvedValue(
    new Response(new Uint8Array([1, 2, 3]), {
      headers: {
        "content-type": "application/octet-stream",
        "set-cookie": 'cisstat_session_id=""; Max-Age=0; Path=/; SameSite=lax',
      },
    }),
  );
  const r = await proxyRequest(
    request("GET", "/api/v1/progress/runs/run/report"),
    config,
    upstream,
  );
  expect(new Uint8Array(await r.arrayBuffer())).toEqual(
    new Uint8Array([1, 2, 3]),
  );
  expect(r.headers.getSetCookie()[0]).toContain(
    "Secure; HttpOnly; SameSite=Lax",
  );
});

test("production http upstream requires explicit operator allowlist (VM cisstat-api incident 2026-11-05)", async () => {
  // Инцидент первого входа на VM: web собран с NODE_ENV=production, а
  // внутренний хоп compose -- API_URL=http://api:8000 (приватная docker-сеть).
  // Гвард отклонял ЛЮБОЙ запрос /api/v1/* с 503 proxy_unavailable, до api
  // ничего не доходило; на Vercel-эре гвард проходил (render.com по https).
  const prevNodeEnv = process.env.NODE_ENV,
    prevAllow = process.env.CISSTAT_PROXY_HTTP_UPSTREAMS;
  try {
    process.env.NODE_ENV = "production";
    delete process.env.CISSTAT_PROXY_HTTP_UPSTREAMS;
    // 1) production + http + без allowlist -> 503 (прежнее fail-closed поведение)
    expect(
      (
        await proxyRequest(
          request(),
          { ...config, apiUrl: "http://api:8000" },
          upstream,
        )
      ).status,
    ).toBe(503);
    // 2) allowlist без нужного хоста -> по-прежнему 503
    process.env.CISSTAT_PROXY_HTTP_UPSTREAMS = "other-host";
    expect(
      (
        await proxyRequest(
          request(),
          { ...config, apiUrl: "http://api:8000" },
          upstream,
        )
      ).status,
    ).toBe(503);
    // 3) allowlist называет хост -> запрос уходит на http-upstream
    process.env.CISSTAT_PROXY_HTTP_UPSTREAMS = "api";
    const ok = await proxyRequest(
      request(),
      { ...config, apiUrl: "http://api:8000" },
      upstream,
    );
    expect(ok.status).toBe(200);
    expect(String(upstream.mock.calls.at(-1)![0])).toBe(
      "http://api:8000/v1/auth/me",
    );
    // 4) сверка регистров и пробелов в allowlist (hostname URL уже lowercased)
    process.env.CISSTAT_PROXY_HTTP_UPSTREAMS = "  API ,other";
    expect(
      (
        await proxyRequest(
          request(),
          { ...config, apiUrl: "http://api:8000" },
          upstream,
        )
      ).status,
    ).toBe(200);
  } finally {
    if (prevNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = prevNodeEnv;
    if (prevAllow === undefined) delete process.env.CISSTAT_PROXY_HTTP_UPSTREAMS;
    else process.env.CISSTAT_PROXY_HTTP_UPSTREAMS = prevAllow;
  }
});

test("https upstream never requires allowlist, even in production", async () => {
  const prevNodeEnv = process.env.NODE_ENV;
  try {
    process.env.NODE_ENV = "production";
    delete process.env.CISSTAT_PROXY_HTTP_UPSTREAMS;
    expect(
      (await proxyRequest(request(), config, upstream)).status,
    ).toBe(200);
  } finally {
    if (prevNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = prevNodeEnv;
  }
});
