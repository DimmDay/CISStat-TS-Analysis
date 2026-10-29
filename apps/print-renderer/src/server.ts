// apps/print-renderer/src/server.ts
//
// PGV-08 — Sandboxed renderer container: HTTP-сервис рендера PNG.
//
// Маршруты (§11/§12):
//   GET  /healthz    — liveness (без проверок зависимостей);
//   GET  /readyz     — readiness: browser/fonts/bundle + mini-smoke PNG
//                      (AC17: недостающий ресурс — честный
//                      render_dependency_unavailable, никогда не ложный
//                      ready); результат кэшируется на readyzCacheS;
//   POST /v1/render  — frozen payload pgv.render_payload/1 → PNG профиля
//                      (300 ppi pHYs, AC16) с hard timeout (AC20);
//   POST /v1/smoke   — полный смоук кириллица/IH/A4 (критерий §13),
//                      JSON-отчёт со структурой/хэшами PNG.
//
// Безопасность (AC19/AC21): env только CISSTAT_PRINT_RENDERER_*; никаких
// cookie/секретов («worker без browser secrets»); тело запроса ограничено
// maxBodyBytes (payload — метаданные/нормализованный контент, не сырой
// DataFrame); журналы — JSON-строки без содержимого payload.
//
// Запуск: node dist/.../server.js (или smoke.js --serve).

import { createServer, IncomingMessage, Server, ServerResponse } from "node:http";

import {
  buildDependencyManifest,
  buildErrorBody,
  RENDER_PAYLOAD_SCHEMA_VERSION,
  RENDERER_FONT_PROFILE,
  RENDERER_VERSION,
  validateRenderPayload,
  type RenderPagePayload,
} from "./rendererCore";
import {
  PrintRenderWorker,
  ReadyzCache,
  RendererBusyError,
  RenderDependencyError,
  RenderTimeoutError,
  readConfig,
} from "./renderWorker";
import { runFullSmoke, runProbeSmoke, type SmokeReport } from "./smokeScenarios";

const config = readConfig();
const worker = new PrintRenderWorker(config);
const readyzCache = new ReadyzCache(config.readyzCacheS);

// ── Журналирование (без содержимого payload — AC21) ───────────────

function log(level: "info" | "warn" | "error", event: string, fields: Record<string, unknown> = {}): void {
  const line = JSON.stringify({ ts_level: level, event, renderer_version: RENDERER_VERSION, ...fields });
  process.stdout.write(`${line}\n`);
}

// ── HTTP-хелперы ──────────────────────────────────────────────────

function sendJson(res: ServerResponse, status: number, body: unknown, extraHeaders: Record<string, string> = {}): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
    ...extraHeaders,
  });
  res.end(payload);
}

function sendPng(res: ServerResponse, png: Buffer, outcome: Record<string, string>): void {
  res.writeHead(200, {
    "Content-Type": "image/png",
    "Content-Length": png.length,
    "Content-Disposition": `attachment; filename="${outcome.filename}"`,
    ...outcome,
  });
  res.end(png);
}

function readBody(req: IncomingMessage, maxBytes: number, onOverflow: () => void): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    let settled = false;
    req.on("data", (chunk: Buffer) => {
      if (settled) return;
      total += chunk.length;
      if (total > maxBytes) {
        settled = true;
        // Сначала честный ответ 413 (запись в сокет), затем прекращаем
        // чтение: уничтожение сокета ДО ответа давало «connection reset»
        // вместо контракта payload_too_large (413).
        onOverflow();
        reject(new BodyTooLargeError(maxBytes));
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      if (!settled) resolve(Buffer.concat(chunks));
    });
    req.on("error", reject);
  });
}

class BodyTooLargeError extends Error {
  readonly maxBytes: number;
  constructor(maxBytes: number) {
    super(`payload_too_large: тело превышает ${maxBytes} байт`);
    this.name = "BodyTooLargeError";
    this.maxBytes = maxBytes;
  }
}

// ── Readiness (AC17 + §12: smoke в readiness) ─────────────────────

async function computeReadiness(): Promise<{
  status: number;
  body: Record<string, unknown>;
}> {
  const manifest = worker.dependencyManifest();
  if (manifest.dependency_status === "unavailable") {
    return {
      status: 503,
      body: {
        status: "unavailable",
        dependency_status: manifest.dependency_status,
        unavailable_reason: manifest.unavailable_reason,
        checks: manifest.checks,
        renderer_version: RENDERER_VERSION,
        font_profile: RENDERER_FONT_PROFILE,
      },
    };
  }
  // Mini-smoke (scale=0.05, малый профиль): реальный PNG кириллицы —
  // §12 «Readiness отдельно проверяет browser/fonts/print bundle и smoke».
  try {
    const probe = await runProbeSmoke(worker);
    if (probe.verdict !== "passed") {
      // AC17: провал smoke-probe — НЕ ready (ложный ready запрещён).
      return {
        status: 503,
        body: {
          status: "unavailable",
          dependency_status: "unavailable",
          unavailable_reason: "smoke_probe_failed",
          probe_error: probe.error,
          checks: { ...manifest.checks, smoke: false },
          renderer_version: RENDERER_VERSION,
        },
      };
    }
    return {
      status: 200,
      body: {
        status: "ready",
        dependency_status: "available",
        checks: { ...manifest.checks, smoke: true },
        smoke: probe,
        renderer_version: RENDERER_VERSION,
        font_profile: RENDERER_FONT_PROFILE,
        payload_version: RENDER_PAYLOAD_SCHEMA_VERSION,
      },
    };
  } catch (error) {
    const reason = error instanceof RenderDependencyError ? error.reason : "smoke_probe_failed";
    return {
      status: 503,
      body: {
        status: "unavailable",
        dependency_status: "unavailable",
        unavailable_reason: reason,
        checks: { ...manifest.checks, smoke: false },
        renderer_version: RENDERER_VERSION,
      },
    };
  }
}

// ── Маршруты ──────────────────────────────────────────────────────

async function handleRender(req: IncomingMessage, res: ServerResponse): Promise<void> {
  let raw: Buffer;
  try {
    raw = await readBody(req, config.maxBodyBytes, () => {
      sendJson(res, 413, buildErrorBody("payload_too_large", `тело превышает ${config.maxBodyBytes} байт`), {
        "X-Render-Retryable": "false",
        "Connection": "close",
      });
      // Ответ доставлен — остаток запроса можно остановить.
      res.on("finish", () => req.destroy());
    });
  } catch (error) {
    if (error instanceof BodyTooLargeError) {
      return; // ответ уже отправлен onOverflow
    }
    throw error;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw.length > 0 ? raw.toString("utf8") : "null");
  } catch {
    sendJson(res, 400, buildErrorBody("invalid_payload", "тело запроса не JSON"));
    return;
  }
  const validation = validateRenderPayload(parsed);
  if (validation.violations.length > 0 || validation.payload === null) {
    sendJson(res, 422, {
      ...buildErrorBody("invalid_payload", "payload не прошёл валидацию pgv.render_payload/1"),
      violations: validation.violations,
    });
    return;
  }
  const payload: RenderPagePayload = validation.payload;
  const manifest = worker.dependencyManifest();
  if (manifest.dependency_status === "unavailable") {
    sendJson(res, 503, buildErrorBody("render_dependency_unavailable", manifest.unavailable_reason ?? "unknown"), {
      "X-Render-Retryable": "false",
      "X-Render-Dependency-Reason": manifest.unavailable_reason ?? "unknown",
    });
    return;
  }
  try {
    const outcome = await worker.renderPayload(payload, 1, payload.snapshot.print.page_count || 1);
    log("info", "render_ok", {
      request_id: payload.request_id,
      profile: payload.snapshot.print.profile_id,
      width: outcome.width,
      height: outcome.height,
      bytes: outcome.png.length,
      duration_ms: outcome.durationMs,
      sha256: outcome.sha256,
      sanitizer_warnings: outcome.sanitizerWarnings.length,
    });
    sendPng(res, outcome.png, {
      "X-Renderer-Version": RENDERER_VERSION,
      "X-Render-Payload-Version": RENDER_PAYLOAD_SCHEMA_VERSION,
      "X-Render-Profile": payload.snapshot.print.profile_id,
      "X-Render-Width": String(outcome.width),
      "X-Render-Height": String(outcome.height),
      "X-Render-Ppi": String(outcome.ppi),
      "X-Render-Duration-Ms": String(outcome.durationMs),
      "X-Render-Sha256": outcome.sha256,
      "X-Render-Sanitized-Warnings": String(outcome.sanitizerWarnings.length),
      filename: `page-1-${payload.snapshot.print.profile_id}.png`,
    });
  } catch (error) {
    if (error instanceof RenderTimeoutError) {
      log("warn", "render_timeout", { request_id: payload.request_id, timeout_s: error.timeoutS });
      sendJson(res, 503, buildErrorBody("render_timeout", error.message), {
        "X-Render-Retryable": "true",
      });
      return;
    }
    if (error instanceof RendererBusyError) {
      sendJson(res, 429, buildErrorBody("renderer_busy", error.message), {
        "X-Render-Retryable": "true",
      });
      return;
    }
    if (error instanceof RenderDependencyError) {
      sendJson(res, 503, buildErrorBody("render_dependency_unavailable", error.reason), {
        "X-Render-Retryable": "false",
        "X-Render-Dependency-Reason": error.reason,
      });
      return;
    }
    log("error", "render_failed", {
      request_id: payload.request_id,
      error: error instanceof Error ? error.message : String(error),
    });
    sendJson(res, 500, buildErrorBody("internal_render_error", "рендер не выполнен; детали в журнале"), {
      "X-Render-Retryable": "false",
    });
  }
}

async function handleSmoke(res: ServerResponse): Promise<void> {
  const manifest = worker.dependencyManifest();
  if (manifest.dependency_status === "unavailable") {
    sendJson(res, 503, buildErrorBody("render_dependency_unavailable", manifest.unavailable_reason ?? "unknown"), {
      "X-Render-Retryable": "false",
    });
    return;
  }
  const report: SmokeReport = await runFullSmoke(worker);
  sendJson(res, report.verdict === "passed" ? 200 : 503, report);
}

export function createRendererServer(): Server {
  return createServer((req, res) => {
    void (async () => {
      const url = (req.url ?? "/").split("?")[0];
      try {
        if (req.method === "GET" && url === "/healthz") {
          sendJson(res, 200, { status: "ok", renderer_version: RENDERER_VERSION });
          return;
        }
        if (req.method === "GET" && url === "/readyz") {
          const cached = readyzCache.get();
          if (cached) {
            sendJson(res, cached.status, cached.body, {
              "X-Readyz-Cache": "hit",
              ...(cached.status === 503 ? { "X-Render-Retryable": "false" } : {}),
            });
            return;
          }
          const readiness = await computeReadiness();
          readyzCache.set(readiness.status, readiness.body);
          sendJson(res, readiness.status, readiness.body, {
            "X-Readyz-Cache": "miss",
            ...(readiness.status === 503 ? { "X-Render-Retryable": "false" } : {}),
          });
          return;
        }
        if (req.method === "POST" && url === "/v1/render") {
          await handleRender(req, res);
          return;
        }
        if (req.method === "POST" && url === "/v1/smoke") {
          await handleSmoke(res);
          return;
        }
        sendJson(res, 404, buildErrorBody("invalid_payload", `нет маршрута ${req.method} ${url}`));
      } catch (error) {
        log("error", "unhandled_route_error", {
          method: req.method,
          url,
          error: error instanceof Error ? error.message : String(error),
        });
        if (!res.headersSent) {
          sendJson(res, 500, buildErrorBody("internal_render_error", "внутренняя ошибка сервиса"));
        } else {
          res.end();
        }
      }
    })();
  });
}

// ── Запуск (node dist/.../server.js) ──────────────────────────────

export function startRendererServer(): Server {
  const server = createRendererServer();
  server.listen(config.port, "0.0.0.0", () => {
    log("info", "renderer_listening", {
      port: config.port,
      hard_timeout_s: config.hardTimeoutS,
      max_concurrent: config.maxConcurrent,
      max_body_bytes: config.maxBodyBytes,
    });
  });
  const shutdown = (signal: string): void => {
    log("info", "renderer_shutdown", { signal });
    server.close(() => undefined);
    void worker.shutdown().finally(() => process.exit(0));
    // AC20: плавная остановка не может висеть вечно.
    setTimeout(() => process.exit(0), 5000).unref();
  };
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));
  return server;
}

if (require.main === module) {
  startRendererServer();
}
