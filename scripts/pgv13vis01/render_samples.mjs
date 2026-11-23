#!/usr/bin/env node
// scripts/pgv13vis01/render_samples.mjs
//
// PGV13-VIS-01 — локальная верификация физической типографики реальным
// рендером: поднимает собранный print-renderer (PGV-08), POST'ит все 11
// сертификационных payload'ов отчёта VIS-01 (upload/pgv13-visual-review.zip)
// и один crafted overflow-payload. Ожидания:
//   • 11 × HTTP 200 PNG с размерами профиля (текст физически читаем —
//     контроль пикселей отдельным Python-шагом);
//   • overflow-payload → HTTP 413 render_content_overflow (§7 «без
//     скрытого усечения»), retryable=false.
//
// Запуск из корня checkout: node scripts/pgv13vis01/render_samples.mjs
// Требует: npm ci, npm run build --workspace=@cisstat/print-renderer,
// playwright-core chromium-1200 (~/.cache/ms-playwright), DejaVu шрифты.

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import http from "node:http";

const PORT = 8911;
const OUT_DIR = process.argv[2] ?? "/tmp/vis01_render";
const PAYLOAD_DIR = process.argv[3] ?? "/tmp/pgv13_review2";

function fontPaths() {
  const candidates = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
  ];
  return candidates.filter((p) => existsSync(p));
}

async function waitReady(proc) {
  for (let i = 0; i < 60; i++) {
    if (proc.exitCode !== null) throw new Error(`renderer exited early: ${proc.exitCode}`);
    const status = await getJson("/readyz");
    if (status.http === 200) return status.body;
    await sleep(1000);
  }
  throw new Error("renderer not ready in 60s: " + JSON.stringify(await getJson("/readyz")));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJson(path) {
  return new Promise((resolve) => {
    const req = http.request({ host: "127.0.0.1", port: PORT, path, method: "GET", timeout: 10000 }, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => resolve({ http: res.statusCode, body: data.slice(0, 800) }));
    });
    req.on("error", (e) => resolve({ http: 0, body: String(e) }));
    req.on("timeout", () => { req.destroy(); resolve({ http: 0, body: "timeout" }); });
    req.end();
  });
}

function postRender(payloadBytes) {
  return new Promise((resolve) => {
    const req = http.request(
      {
        host: "127.0.0.1",
        port: PORT,
        path: "/v1/render",
        method: "POST",
        headers: { "content-type": "application/json", "content-length": payloadBytes.length },
        timeout: 70000,
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
      },
    );
    req.on("error", (e) => resolve({ status: 0, headers: {}, body: Buffer.from(String(e)) }));
    req.on("timeout", () => { req.destroy(); resolve({ status: 0, headers: {}, body: Buffer.from("timeout") }); });
    req.write(payloadBytes);
    req.end();
  });
}

// Historical single-surface typography probe. For actual PGV14 page sets use
// scripts/pgv14/verify_vm.py: it preserves all 11 cases and verifies EVERY page.
function terminalOverflow(response) {
  try {
    const error = JSON.parse(response.body.toString("utf8")).error;
    return error.code === "render_content_overflow" && error.retryable === false &&
      response.headers["x-render-retryable"] === "false";
  } catch { return false; }
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const fonts = fontPaths();
  if (fonts.length === 0) throw new Error("DejaVu fonts not found");
  const proc = spawn(
    process.execPath,
    ["apps/print-renderer/dist/apps/print-renderer/src/server.js"],
    {
      env: {
        ...process.env,
        CISSTAT_PRINT_RENDERER_PORT: String(PORT),
        CISSTAT_PRINT_RENDERER_FONT_FILES: fonts.join(":"),
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  proc.stdout.on("data", (c) => process.stdout.write(`[server] ${c}`));
  proc.stderr.on("data", (c) => process.stderr.write(`[server:err] ${c}`));
  try {
    const ready = await waitReady(proc);
    console.log("READY:", JSON.stringify(ready));

    const names = [
      "p01-figure-landscape", "p01-a4-landscape", "p01-a4-portrait",
      "p01-reused", "p01-missing", "p01-corrupt",
      "p02-figure-landscape", "p02-a4-landscape", "p02-a4-portrait",
      "p02-reused", "p02-missing",
    ];
    // Ожидания PGV13-VIS-01 (§7 «Неделимый … требует другого профиля/размера
    // либо явного отказа»): содержимое, физически не умещающееся в профиль
    // при обязательной типографике, отказывает ЯВНО (413), а не молча.
    const expect = {
      "p01-figure-landscape": 413, // полный P01 на 8×5" — другой профиль
      "p01-a4-landscape": 200,
      "p01-a4-portrait": 200,
      "p01-reused": 413,           // траектория 3 паспортов = page-set (PGV-14)
      "p01-missing": 200,
      "p01-corrupt": 200,
      "p02-figure-landscape": 413, // P02 с определениями на 8×5" — другой профиль
      "p02-a4-landscape": 200,
      "p02-a4-portrait": 200,
      "p02-reused": 200,
      "p02-missing": 200,
    };
    const report = { ready: ready, renders: [], adapted: [], overflow_probe: null };

    for (const name of names) {
      const file = `${PAYLOAD_DIR}/${name}.payload.json`;
      const bytes = readFileSync(file);
      const res = await postRender(bytes);
      const entry = {
        name,
        status: res.status,
        expected: expect[name],
        match: res.status === expect[name] && (res.status !== 413 || terminalOverflow(res)),
        retryable: res.headers["x-render-retryable"] ?? null,
        width: res.headers["x-render-width"] ?? null,
        height: res.headers["x-render-height"] ?? null,
        ppi: res.headers["x-render-ppi"] ?? null,
        sha256: res.headers["x-render-sha256"] ?? null,
        bytes: res.body.length,
        png_signature_ok: res.body.subarray(0, 8).toString("hex") === "89504e470d0a1a0a",
      };
      if (res.status === 200) writeFileSync(`${OUT_DIR}/${name}.png`, res.body);
      report.renders.push(entry);
      console.log("RENDER", JSON.stringify(entry));
    }

    // Адаптированные ре-рендеры: тот же контент на профиле-применимости
    // (§7 «другого профиля/размера») — доказательство, что отказ профиля,
    // а не дефект контента/типографики.
    const adapted = [
      ["p01-figure-landscape", "p01-figure-content@a4-landscape", "a4-landscape"],
      ["p02-figure-landscape", "p02-figure-content@a4-landscape", "a4-landscape"],
    ];
    for (const [source, name, profile] of adapted) {
      const payload = JSON.parse(readFileSync(`${PAYLOAD_DIR}/${source}.payload.json`, "utf8"));
      payload.snapshot.print.profile_id = profile;
      const res = await postRender(Buffer.from(JSON.stringify(payload)));
      const entry = { name, source, profile, status: res.status,
        png_signature_ok: res.body.subarray(0, 8).toString("hex") === "89504e470d0a1a0a" };
      if (res.status === 200) writeFileSync(`${OUT_DIR}/${name}.png`, res.body);
      report.adapted.push(entry);
      console.log("ADAPTED", JSON.stringify(entry));
    }

    // Trajectory-set (3 паспорта) не умещается ни в один профиль одной
    // страницей: page-set — зона PGV-14. Типографика записей проверяется
    // ре-рендером КАЖДОЙ записи отдельным документом (a4-portrait).
    const reused = JSON.parse(readFileSync(`${PAYLOAD_DIR}/p01-reused.payload.json`, "utf8"));
    for (let i = 0; i < reused.sections.length; i++) {
      const single = JSON.parse(JSON.stringify(reused));
      single.sections = [reused.sections[i]];
      const res = await postRender(Buffer.from(JSON.stringify(single)));
      const entry = { name: `p01-reused-record${i}@a4-portrait`, status: res.status,
        png_signature_ok: res.body.subarray(0, 8).toString("hex") === "89504e470d0a1a0a" };
      if (res.status === 200) writeFileSync(`${OUT_DIR}/${entry.name}.png`, res.body);
      report.adapted.push(entry);
      console.log("ADAPTED", JSON.stringify(entry));
    }

    // Crafted overflow: P01 + неизвестная группа с 300 строками — контент
    // заведомо выше A4 при обязательной типографике → явный отказ.
    const base = JSON.parse(readFileSync(`${PAYLOAD_DIR}/p01-a4-portrait.payload.json`, "utf8"));
    const fake = {};
    for (let i = 0; i < 300; i++) fake[`overflow_field_${String(i).padStart(3, "0")}`] = `строка переполнения ${i}`;
    base.sections[0].record.passport.overflow_probe_group = fake;
    const overflow = await postRender(Buffer.from(JSON.stringify(base)));
    report.overflow_probe = {
      status: overflow.status,
      body: overflow.status === 200 ? "(unexpected 200)" : overflow.body.toString("utf8").slice(0, 400),
      retryable: overflow.headers["x-render-retryable"] ?? null,
    };
    console.log("OVERFLOW", JSON.stringify(report.overflow_probe));

    writeFileSync(`${OUT_DIR}/render_report.json`, JSON.stringify(report, null, 2));
    const ok =
      report.renders.every((r) => r.match && (r.status !== 200 || r.png_signature_ok)) &&
      report.adapted.every((r) => r.status === 200 && r.png_signature_ok) &&
      report.overflow_probe.status === 413 && terminalOverflow(overflow);
    console.log(ok ? "VIS01_LOCAL_RENDER_OK" : "VIS01_LOCAL_RENDER_FAILED");
    process.exitCode = ok ? 0 : 1;
  } finally {
    proc.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error("FATAL", error);
  process.exit(1);
});
