/** Built Next shells + HTTPS first-party proxy + controlled HTTP authority protocol stub.
 * NOT a certification of authentication/storage: those have independent PostgreSQL tests.
 * Needs production .next and chromium. Uses ONLY explicitly synthetic public fixtures.
 */
const fs = require("fs"),
  path = require("path"),
  http = require("http"),
  https = require("https");
const { spawn, execFileSync } = require("child_process");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "../..");
// The execution sandbox may have no /tmp. Keep all browser artifacts in our workspace.
const browserTmp = fs.mkdtempSync(path.join(root, "../browser-tmp-"));
process.env.TMPDIR = browserTmp;
const { chromium } = require("playwright-core");
const shell = process.argv[2],
  enabled = process.argv[3] === "enabled";
assert(["standalone", "embedded"].includes(shell), "shell required");
assert(
  ["enabled", "disabled"].includes(process.argv[3]),
  "expected compiled public state required",
);
const LOGIN = "cert-public-demo",
  PASSWORD = "cert-public-pair-not-personal";
const caps = {
  registry_version: "authz-registry/1",
  capabilities_version: 2,
  can_run_baseline_models: true,
  can_tune_models: false,
  can_train_custom_models: false,
  restricted_stage_ids: ["scenario", "causal", "decision", "monitoring"],
  baseline_limits: {
    max_rows: 5000,
    max_folds: 3,
    max_horizon: 24,
    max_seasonal_period: 366,
    max_models: 3,
  },
  can_train_models: false,
  can_use_api: false,
  can_save_history: false,
  can_upload_own_data: true,
  max_dataset_rows: 5000,
  max_api_calls_per_month: 0,
  max_analyses_total: 10,
  trial_days: 14,
  watermark_exports: true,
};
const session = {
  subject_id: "synthetic-person",
  account_id: "synthetic-account",
  tenant_id: "synthetic-tenant",
  auth_session_id: "synthetic-sid",
  auth_method: "auth_session",
  role: "external_user",
  membership_role: "owner",
  account_plan: "starter",
  account_type: "mono",
  entitlement_version: 1,
  capabilities: caps,
};
let unavailable = false,
  delay = 0,
  next,
  browser;
const events = [],
  urls = [],
  children = [];
const listen = (server) => new Promise((r) => server.listen(0, "127.0.0.1", r));
const close = (server) => new Promise((r) => server.close(r));
const tmp = fs.mkdtempSync(path.join(root, "scripts/kabinet_demo_cert/tls-"));
const logPath = path.join(
  root,
  "scripts/kabinet_demo_cert/protocols",
  `next-${shell}-${enabled ? "enabled" : "disabled"}.txt`,
);
const log = fs.openSync(logPath, "w");
const upstream = http.createServer(async (req, res) => {
  let body = "";
  for await (const c of req) body += c;
  const route = req.url.split("?")[0];
  if (req.method === "POST")
    events.push({ path: route, body: body ? JSON.parse(body) : null });
  const send = (status, data, cookies) => {
    res.writeHead(status, {
      "content-type": "application/json",
      ...(cookies ? { "set-cookie": cookies } : {}),
    });
    res.end(JSON.stringify(data));
  };
  const rawCookie = req.headers.cookie || "";
  const demoCookie = rawCookie.includes("__Host-cisstat_auth=cert-session");
  const cookie =
    demoCookie || rawCookie.includes("__Host-cisstat_auth=cert-personal");
  if (route === "/v1/auth/csrf") {
    const proof = "c1.1234567890." + "A".repeat(32) + "." + "a".repeat(64);
    return send(200, { csrf_token: proof }, [
      "__Host-cisstat_csrf=" +
        proof +
        "; Path=/; Secure; HttpOnly; SameSite=Lax",
    ]);
  }
  if (route === "/v1/auth/me") {
    if (delay) await new Promise((r) => setTimeout(r, delay));
    return send(
      unavailable ? 503 : cookie ? 200 : 401,
      unavailable
        ? { detail: { code: "auth_authority_unavailable" } }
        : cookie
          ? { ...session, account_plan: demoCookie ? "demo" : "starter" }
          : { detail: { code: "authentication_required" } },
    );
  }
  if (route === "/v1/auth/demo/me")
    return send(
      demoCookie ? 200 : 401,
      demoCookie
        ? { grant_id: "synthetic-grant" }
        : { detail: { code: "authentication_required" } },
    );
  if (route === "/v1/auth/demo/limits")
    return send(200, {
      expires_at: "2099-01-01T00:00:00Z",
      requests_remaining: 7,
      analyses_remaining: 2,
    });
  if (route === "/v1/auth/demo/prepare")
    return send(200, { prepared: true }, [
      "__Host-cisstat_demo_resume=d1_fixture; Path=/; Secure; HttpOnly; SameSite=Lax",
    ]);
  if (route === "/v1/auth/demo/enter") {
    const v = JSON.parse(body);
    if (v.login !== LOGIN || v.password !== PASSWORD)
      return send(401, { detail: { code: "invalid_credential" } });
    return send(200, { status: "authenticated" }, [
      "__Host-cisstat_auth=cert-session; Path=/; Secure; HttpOnly; SameSite=Lax",
    ]);
  }
  if (route === "/v1/auth/demo/resume")
    return send(200, { status: "authenticated" }, [
      "__Host-cisstat_auth=cert-session; Path=/; Secure; HttpOnly; SameSite=Lax",
    ]);
  if (route === "/v1/auth/demo/leave")
    return send(200, { left: true }, [
      "__Host-cisstat_auth=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax",
    ]);
  if (route === "/v1/accounts")
    return send(200, {
      current_account_id: "synthetic-account",
      accounts: [
        {
          account_id: "synthetic-account",
          account_type: "mono",
          plan: "starter",
        },
      ],
    });
  if (route === "/v1/accounts/synthetic-account")
    return send(200, {
      account_id: "synthetic-account",
      tenant_id: "synthetic-tenant",
      account_type: "mono",
      plan: "starter",
      seats: 1,
      occupied: 1,
      free_seats: 0,
      entitlement_version: 1,
      can_manage: false,
      members: [],
      invitations: [],
      seat_requests: [],
    });
  return send(401, { detail: { code: "authentication_required" } });
});
let front;
(async () => {
  try {
    assert(
      fs.existsSync(path.join(root, "apps", shell, ".next/BUILD_ID")),
      "build required, no dev fallback",
    );
    execFileSync(
      "openssl",
      [
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        tmp + "/key.pem",
        "-out",
        tmp + "/cert.pem",
        "-days",
        "1",
        "-subj",
        "/CN=localhost",
      ],
      { stdio: "ignore" },
    );
    await listen(upstream);
    const reserve = http.createServer();
    await listen(reserve);
    const port = reserve.address().port;
    await close(reserve);
    front = https.createServer(
      {
        key: fs.readFileSync(tmp + "/key.pem"),
        cert: fs.readFileSync(tmp + "/cert.pem"),
      },
      (req, res) => {
        const outgoing = http.request(
          {
            hostname: "127.0.0.1",
            port,
            path: req.url,
            method: req.method,
            headers: req.headers,
          },
          (r) => {
            res.writeHead(r.statusCode, r.headers);
            r.pipe(res);
          },
        );
        outgoing.on("error", () => {
          res.writeHead(503);
          res.end();
        });
        req.pipe(outgoing);
      },
    );
    await listen(front);
    const origin = "https://127.0.0.1:" + front.address().port;
    next = spawn(
      process.execPath,
      [
        path.join(root, "node_modules/next/dist/bin/next"),
        "start",
        "-p",
        String(port),
        "-H",
        "127.0.0.1",
      ],
      {
        cwd: path.join(root, "apps", shell),
        env: {
          ...process.env,
          NODE_ENV: "production",
          NEXT_PUBLIC_DEMO_LOGIN: "runtime-must-not-win",
          NEXT_PUBLIC_DEMO_PASSWORD: "runtime-must-not-win",
          API_URL: "http://127.0.0.1:" + upstream.address().port,
          CISSTAT_PROXY_HTTP_UPSTREAMS: "127.0.0.1",
          CISSTAT_AUTH_PUBLIC_ORIGIN: origin,
        },
        stdio: ["ignore", log, log],
      },
    );
    children.push(next);
    let ready = false;
    for (let i = 0; i < 120; i++) {
      if (next.exitCode !== null)
        throw Error("Next exited, see bounded server log");
      try {
        const r = await fetch("http://127.0.0.1:" + port + "/demo");
        if (r.ok) {
          ready = true;
          break;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 250));
    }
    assert(ready, "Next readiness timeout");
    if (process.argv[4] === "http-only") {
      const { JSDOM } = require("jsdom");
      const jar = new Map();
      async function wire(url, method = "GET", body, extra = {}) {
        return new Promise((resolve, reject) => {
          const headers = {
            Origin: origin,
            "sec-fetch-site": "same-origin",
            ...extra,
          };
          if (jar.size)
            headers.Cookie = [...jar].map(([k, v]) => k + "=" + v).join("; ");
          if (body !== undefined) headers["Content-Type"] = "application/json";
          const req = https.request(
            origin + url,
            { method, headers, rejectUnauthorized: false },
            (r) => {
              let text = "";
              r.on("data", (c) => (text += c));
              r.on("end", () => {
                for (const raw of r.headers["set-cookie"] || []) {
                  const first = raw.split(";")[0],
                    at = first.indexOf("=");
                  jar.set(first.slice(0, at), first.slice(at + 1));
                }
                resolve({ status: r.statusCode, headers: r.headers, text });
              });
            },
          );
          req.on("error", reject);
          req.end(body === undefined ? undefined : JSON.stringify(body));
        });
      }
      const demo = await wire("/demo");
      assert.equal(demo.status, 200);
      const dom = new JSDOM(demo.text),
        doc = dom.window.document;
      assert.equal(doc.querySelector("h1").textContent, "Демо-режим платформы");
      assert.equal(
        doc.querySelector('meta[name="robots"]').content,
        "index, follow",
      );
      assert.equal(
        doc.querySelector('meta[name="referrer"]').content,
        "no-referrer",
      );
      const start = [...doc.querySelectorAll("button")].find(
        (b) => b.textContent.trim() === "Запустить демо-режим",
      );
      assert(start);
      assert.equal(
        !start.disabled,
        enabled,
        "build env, not conflicting runtime overrides",
      );
      assert(
        ![...doc.querySelectorAll("a")].some(
          (a) => a.href.includes(LOGIN) || a.href.includes(PASSWORD),
        ),
      );
      let compiledJS="";
      for(const script of doc.querySelectorAll("script[src]")){
        const src=script.getAttribute("src");
        if(src.startsWith("/_next/static/")){
          const asset=await wire(src);assert.equal(asset.status,200);compiledJS+=asset.text;
        }
      }
      for(const value of [LOGIN,PASSWORD])assert.equal(compiledJS.includes(value),enabled,"actual browser JS must reflect build-time pair");
      const navigator = await wire("/navigator");
      assert.equal(navigator.status, 200);
      const navdoc = new JSDOM(navigator.text).window.document;
      assert(
        [...navdoc.querySelectorAll('a[href="/demo"]')].some((a) =>
          a.textContent.includes("Попробовать в демо-режиме"),
        ),
      );
      if (shell === "standalone") {
        const header = [...doc.querySelectorAll('a[href="/dashboard"]')].find(
          (a) => a.textContent.trim() === "Вход",
        );
        assert(header);
        assert.equal(header.target, "_top");
        const dashboard = await wire("/dashboard");
        assert.equal(dashboard.status, 200);
        const d = new JSDOM(dashboard.text).window.document;
        assert.equal(
          d.querySelector('meta[name="robots"]').content,
          "noindex, nofollow",
        );
      }
      let refused = await wire("/api/v1/auth/demo/prepare", "POST");
      assert.equal(refused.status, 403);
      const csrf = await wire("/api/v1/auth/csrf");
      assert.equal(csrf.status, 200);
      const proof = JSON.parse(csrf.text).csrf_token;
      refused = await wire("/api/v1/auth/demo/prepare", "POST", undefined, {
        "X-CSRF-Token": proof,
        Origin: "https://wrong.example",
      });
      assert.equal(refused.status, 403);
      const headers = { "X-CSRF-Token": proof };
      assert.equal(
        (await wire("/api/v1/auth/demo/prepare", "POST", undefined, headers))
          .status,
        200,
      );
      if (enabled) {
        assert.equal(
          (
            await wire(
              "/api/v1/auth/demo/enter",
              "POST",
              { login: LOGIN, password: PASSWORD },
              headers,
            )
          ).status,
          200,
        );
        assert(jar.get("__Host-cisstat_auth"));
        assert.equal(
          (await wire("/api/v1/auth/demo/resume", "POST", undefined, headers))
            .status,
          200,
        );
      }
      assert.equal(
        (await wire("/api/v1/auth/demo/leave", "POST", undefined, headers))
          .status,
        200,
      );
      console.log(
        JSON.stringify({
          status: "PASS",
          shell,
          public_build: enabled ? "enabled" : "disabled",
          mode: "compiled SSR + real HTTPS/first-party proxy + controlled authority stub; NO browser/client navigation/layout claim",
          checks: [
            "actual built demo HTML/metadata/disabled state",
            "runtime cannot override compiled public pair",
            "navigator/header/dashboard markup",
            "proxy rejects missing CSRF/wrong Origin",
            "cookie/CSRF prepare-enter-resume-leave wire contract",
          ],
        }),
      );
      dom.window.close();
      return;
    }
    browser = await chromium.launch({
      executablePath: process.env.CISSTAT_CHROMIUM || "/usr/bin/chromium",
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 1000 },
    });
    context.on("request", (r) => urls.push(r.url()));
    const page = await context.newPage();
    await page.goto(origin + "/demo");
    await page
      .getByRole("heading", { name: "Демо-режим платформы", level: 1 })
      .waitFor();
    assert.equal(
      await page.locator("meta[name=robots]").getAttribute("content"),
      "index, follow",
    );
    assert.equal(
      await page.locator("meta[name=referrer]").getAttribute("content"),
      "no-referrer",
    );
    const start = page.getByRole("button", { name: "Запустить демо-режим" });
    assert.equal(
      await start.isEnabled(),
      enabled,
      "compiled public config must match build, never runtime overrides",
    );
    await page.getByLabel("Пароль кампании", { exact: true }).waitFor();
    if (enabled) {
      await start.click();
      await page.waitForURL("**/upload");
      await page
        .getByRole("complementary", { name: "Лимиты демо" })
        .getByText(/научных запросов: 7/)
        .waitFor();
      const enter = events.find((e) => e.path === "/v1/auth/demo/enter");
      assert(enter);
      assert.deepEqual(enter.body, { login: LOGIN, password: PASSWORD });
      assert(
        events.findIndex((e) => e.path === "/v1/auth/demo/prepare") <
          events.indexOf(enter),
      );
      await page.goto(origin + "/demo");
      await page
        .getByRole("button", { name: "Продолжить свой демо-доступ" })
        .click();
      await page.waitForURL("**/upload");
      assert.equal(
        events.find((e) => e.path === "/v1/auth/demo/resume").body,
        null,
      );
    }
    await page.goto(origin + "/demo");
    await page
      .getByRole("button", { name: "Завершить демо на этом устройстве" })
      .click();
    await page
      .getByRole("alert")
      .filter({ hasText: "Демо-вход на устройстве завершён" })
      .waitFor();
    assert(events.some((e) => e.path === "/v1/auth/demo/leave"));
    for (const width of [1440, 375]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(origin + "/demo");
      await page
        .getByRole("heading", { name: "Демо-режим платформы", level: 1 })
        .waitFor();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        "demo horizontal overflow",
      );
      const focused = await page.getByRole("button", {
        name: "Войти в кампанию",
      });
      await focused.focus();
      assert(await focused.evaluate((el) => el === document.activeElement));
      await page.goto(origin + "/navigator");
      const link = page
        .getByRole("link", { name: /Попробовать в демо-режиме/ })
        .first();
      await link.waitFor();
      assert.equal(await link.getAttribute("href"), "/demo");
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        "navigator horizontal overflow",
      );
    }
    if (shell === "standalone") {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(origin + "/demo");
      const entry = page.getByRole("link", { name: "Вход", exact: true });
      assert.equal(await entry.getAttribute("href"), "/dashboard");
      assert.equal(await entry.getAttribute("target"), "_top");
      delay = 1000;
      await page.goto(origin + "/dashboard");
      await page
        .getByRole("status")
        .filter({ hasText: "Проверяем вход" })
        .waitFor();
      assert(new URL(page.url()).pathname === "/dashboard");
      await page.waitForURL("**/login?return_to=/account");
      delay = 0;
      await context.addCookies([
        {
          name: "__Host-cisstat_auth",
          value: "cert-personal",
          url: origin,
          secure: true,
          httpOnly: true,
          sameSite: "Lax",
        },
      ]);
      await page.goto(origin + "/dashboard");
      await page.waitForURL("**/account");
      await context.clearCookies();
      unavailable = true;
      await page.goto(origin + "/dashboard");
      await page
        .getByRole("alert")
        .filter({ hasText: "Сервис авторизации недоступен" })
        .waitFor();
      await page.waitForTimeout(250);
      assert.equal(new URL(page.url()).pathname, "/dashboard");
      unavailable = false;
    }
    for (const value of [LOGIN, PASSWORD])
      assert(
        !urls.some((u) => u.includes(value)),
        "public pair leaked into URL",
      );
    const storage = await page.evaluate(() =>
      JSON.stringify([
        Object.entries(localStorage),
        Object.entries(sessionStorage),
      ]),
    );
    for (const value of [LOGIN, PASSWORD, "cert-session"])
      assert(
        !storage.includes(value),
        "credential persisted in browser storage",
      );
    console.log(
      JSON.stringify({
        status: "PASS",
        shell,
        public_build: enabled ? "enabled" : "disabled",
        browser: "Chromium",
        transport:
          "built Next + HTTPS + real first-party proxy + controlled authority stub",
        checks: [
          "metadata",
          "compiled-env",
          "form",
          "leave",
          "navigator desktop/mobile",
          "keyboard focus",
          "no credential URL/storage",
          ...(enabled
            ? ["prepare-enter-upload", "resume-upload"]
            : ["honest disabled"]),
          ...(shell === "standalone"
            ? ["header", "pivot loading/anonymous/authenticated/unavailable"]
            : []),
        ],
      }),
    );
    await context.close();
  } finally {
    if (browser) await browser.close();
    for (const child of children) {
      child.kill("SIGTERM");
      await new Promise((r) =>
        child.exitCode !== null ? r() : child.once("exit", r),
      );
    }
    if (front) await close(front);
    await close(upstream);
    fs.closeSync(log);
    fs.rmSync(tmp, { recursive: true, force: true });
    fs.rmSync(browserTmp, { recursive: true, force: true });
  }
})().catch((e) => {
  console.error(e.message);
  process.exitCode = 1;
});
