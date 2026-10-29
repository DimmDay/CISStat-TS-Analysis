// apps/print-renderer/src/renderWorker.ts
//
// PGV-08 — Sandboxed renderer container: браузерный слой (playwright-core,
// пин 1.57.0 == chromium-1200) поверх чистого ядра rendererCore.
//
// §11: «Timeout убивает browser process/context, не оставляет
// неограниченный thread; temp cleanup обязателен» — по превышении
// эффективного таймаута контекст закрывается, зависший процесс браузера
// убивается SIGKILL'ом (AC20), временная директория удаляется в finally.
//
// AC19 (sandbox): страница рендера создаётся с javaScriptEnabled=false,
// serviceWorkers=block, bypassCSP=false; ВСЕ внешние/файловые запросы
// абортятся политикой buildRequestPolicy() ДО сети; контейнер дополнительно
// работает в network_mode: none (защита в глубину).
//
// AC17: браузер/шрифты/бандл проверяются манифестом до запуска; недостающий
// ресурс — render_dependency_unavailable (терминальная), никогда не ложный
// ready. Работает как сервисный capability: env только CISSTAT_PRINT_RENDERER_*
// (никаких cookie/секретов — PGV-AC19 «worker без browser secrets»).

import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { Worker } from "node:worker_threads";
import { join } from "node:path";
import { createLaunchGuard, type LaunchGuard } from "./launchGuard";

import type { Browser, BrowserContext, BrowserServer } from "playwright-core";

import {
  buildDependencyManifest,
  buildPrintHtml,
  buildRequestPolicy,
  buildSandboxLaunchSpec,
  clampTimeoutSeconds,
  DEFAULT_HARD_TIMEOUT_S,
  injectPngPhys,
  RENDERER_FONT_PROFILE,
  validateRenderPayload,
  RENDERER_VERSION,
  type DependencyManifest,
  type RenderPagePayload,
} from "./rendererCore";

// ── Конфигурация (env allowlist: только CISSTAT_PRINT_RENDERER_*) ──

export interface RendererConfig {
  port: number;
  browserPath: string | null;
  hardTimeoutS: number;
  maxConcurrent: number;
  maxBodyBytes: number;
  fontFiles: string[];
  tmpDir: string;
  readyzCacheS: number;
}

const DEFAULT_FONT_FILES = [
  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
];

export function readConfig(env: Record<string, string | undefined> = process.env): RendererConfig {
  const intEnv = (name: string, fallback: number): number => {
    const raw = env[name];
    if (raw === undefined || raw === "") return fallback;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  };
  const fontFiles = env.CISSTAT_PRINT_RENDERER_FONT_FILES
    ? env.CISSTAT_PRINT_RENDERER_FONT_FILES.split(":").filter((p) => p.length > 0)
    : DEFAULT_FONT_FILES;
  return {
    port: intEnv("CISSTAT_PRINT_RENDERER_PORT", 8907),
    browserPath: env.CISSTAT_PRINT_RENDERER_BROWSER_PATH || null,
    hardTimeoutS: intEnv("CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S", DEFAULT_HARD_TIMEOUT_S),
    maxConcurrent: intEnv("CISSTAT_PRINT_RENDERER_MAX_CONCURRENT", 2),
    maxBodyBytes: intEnv("CISSTAT_PRINT_RENDERER_MAX_BODY_BYTES", 8388608),
    fontFiles,
    tmpDir: env.CISSTAT_PRINT_RENDERER_TMP_DIR || tmpdir(),
    readyzCacheS: intEnv("CISSTAT_PRINT_RENDERER_READYZ_CACHE_S", 30),
  };
}

// ── Ошибки рендера (контракт кодов PGV-08) ────────────────────────

export class RenderDependencyError extends Error {
  readonly reason: string;
  constructor(reason: string) {
    super(`render_dependency_unavailable: ${reason}`);
    this.name = "RenderDependencyError";
    this.reason = reason;
  }
}

export class RenderTimeoutError extends Error {
  readonly timeoutS: number;
  constructor(timeoutS: number) {
    super(`render_timeout: превышен hard timeout ${timeoutS} s`);
    this.name = "RenderTimeoutError";
    this.timeoutS = timeoutS;
  }
}

export class RendererBusyError extends Error {
  readonly maxConcurrent: number;
  constructor(maxConcurrent: number) {
    super(`renderer_busy: максимум ${maxConcurrent} параллельных рендеров`);
    this.name = "RendererBusyError";
    this.maxConcurrent = maxConcurrent;
  }
}

// ── Кэш readiness (healthcheck не должен порождать рендеры чаще TTL) ──

export class ReadyzCache {
  private readonly ttlMs: number;
  private entry: { at: number; status: number; body: Record<string, unknown> } | null = null;

  constructor(ttlSeconds: number) {
    this.ttlMs = Math.max(0, ttlSeconds) * 1000;
  }

  get(): { status: number; body: Record<string, unknown> } | null {
    if (!this.entry) return null;
    if (Date.now() - this.entry.at > this.ttlMs) return null;
    return { status: this.entry.status, body: this.entry.body };
  }

  set(status: number, body: Record<string, unknown>): void {
    this.entry = { at: Date.now(), status, body };
  }
}

// ── Worker ────────────────────────────────────────────────────────

interface RenderOutcome {
  png: Buffer;
  width: number;
  height: number;
  ppi: number;
  durationMs: number;
  sha256: string;
  sanitizerWarnings: string[];
}

export class PrintRenderWorker {
  private readonly config: RendererConfig;
  private readonly servers = new Set<BrowserServer>();
  private readonly launches = new Set<LaunchGuard>();
  private stopping = false;
  private playwrightModule: typeof import("playwright-core") | null = null;
  private active = 0;

  constructor(config: RendererConfig) {
    this.config = config;
  }

  /** Dependency-манифест (AC17): browser/fonts/bundle — до всякого рендера. */
  dependencyManifest(bundleLoaded = true): DependencyManifest {
    const manifest = buildDependencyManifest({
      browserExecutable: this.resolveBrowserExecutable(),
      fontFiles: this.config.fontFiles.filter((file) => existsSync(file)),
      bundleLoaded,
    });
    return manifest;
  }

  /** Резолв executable: явный env-пин или реестр playwright-core.
   *  AC17: путь обязан СУЩЕСТВОВАТЬ — непустая строка не признаётся
   *  зависимостью (иначе — ложный ready). */
  private resolveBrowserExecutable(): string | null {
    if (this.config.browserPath) {
      return existsSync(this.config.browserPath) ? this.config.browserPath : null;
    }
    // Без playwright-модуля честно считаем браузер ненайденным (AC17):
    // resolve делаем лениво через реестр при первом запуске.
    if (!this.playwrightModule) {
      // Проверка наличия модуля без импорта браузера.
      try {
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        require.resolve("playwright-core");
      } catch {
        return null;
      }
    }
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { chromium } = require("playwright-core");
      const path = chromium.executablePath() as string;
      return typeof path === "string" && path.length > 0 && existsSync(path) ? path : null;
    } catch {
      return null;
    }
  }

  /** A separate browser server per admitted render avoids cancelling another job.
   * launchServer owns and kills an incomplete launch on its own bounded timeout.
   * Its public process() handle supports a real SIGKILL (Browser has no such API).
   */
  private async ensureBrowser(
    remainingMs: () => number,
    onServer: (server: BrowserServer) => void,
    onGuard: (guard: LaunchGuard) => void,
    cancelled: () => boolean,
  ): Promise<Browser> {
    if (!this.playwrightModule) this.playwrightModule = await import("playwright-core");
    if (cancelled() || this.stopping) throw new RenderTimeoutError(0);
    const spec = buildSandboxLaunchSpec();
    const guard = createLaunchGuard(this.config.tmpDir);
    this.launches.add(guard);
    onGuard(guard);
    const actualExecutable = this.config.browserPath ?? this.playwrightModule.chromium.executablePath();
    const server = await this.playwrightModule.chromium.launchServer({
      executablePath: "/bin/sh",
      ignoreDefaultArgs: true,
      headless: true,
      host: "127.0.0.1",
      // Browser receives no platform secrets inherited from the API environment.
      env: { HOME: this.config.tmpDir, TMPDIR: this.config.tmpDir, LANG: "C.UTF-8", LC_ALL: "C.UTF-8" },
      chromiumSandbox: true,
      // Explicit Chromium flags because the executable is the shell gate.
      args: [guard.wrapper, actualExecutable, "--remote-debugging-pipe", "--headless",
        `--user-data-dir=${join(guard.directory, "profile")}`, ...spec.chromiumArgs],
      timeout: remainingMs(),
    });
    this.servers.add(server);
    onServer(server);
    if (cancelled() || this.stopping) {
      this.killBrowser(server);
      throw new RenderTimeoutError(0);
    }
    return this.playwrightModule.chromium.connect(server.wsEndpoint(), { timeout: remainingMs() });
  }

  /** SIGKILL belongs to this render's BrowserServer, never a shared Browser. */
  private killBrowser(server: BrowserServer | null): void {
    if (!server) return;
    // Playwright 1.57 kills the entire browser process group with SIGKILL.
    // Do not first ChildProcess.kill(): it marks the parent killed and can
    // prevent Playwright from reaping its descendants.
    void server.kill().catch(() => undefined);
    this.servers.delete(server);
  }

  /**
   * Рендер одной страницы: SSR из общего бандла PGV-07 → headless
   * Chromium (JS off, request-block, CSP) → скриншот поверхности профиля
   * → pHYs 300 ppi (AC16).
   *
   * Hard timeout (AC20, §11 «Timeout убивает browser process/context»):
   * дедлайн покрывает ВЕСЬ рендер — от dependency-манифеста до pHYs
   * (SSR/layout/скриншот НЕ могут выйти за cap); превышение —
   * RenderTimeoutError + SIGKILL браузера + cleanup в finally.
   */
  async renderPayload(
    payload: RenderPagePayload,
    pageIndex: number,
    pageCount: number,
  ): Promise<RenderOutcome> {
    if (validateRenderPayload(payload).payload === null) {
      throw new Error("invalid_payload: render input violates the shared contract");
    }
    if (this.stopping) throw new RenderDependencyError("renderer_stopping");
    if (this.active >= this.config.maxConcurrent) {
      throw new RendererBusyError(this.config.maxConcurrent);
    }
    this.active += 1;
    const startedAt = Date.now();
    const effectiveS = clampTimeoutSeconds(payload.options?.timeout_s, this.config.hardTimeoutS);
    const deadlineAt = startedAt + effectiveS * 1000;
    let server: BrowserServer | null = null;
    let launch: LaunchGuard | null = null;
    let timedOut = false;
    const abort = new AbortController();
    let deadlineTimer: NodeJS.Timeout | null = null;
    const cancelled = () => timedOut || Date.now() >= deadlineAt || this.stopping;
    const remainingMs = () => Math.max(1, deadlineAt - Date.now());
    try {
      const work = this.doRender(payload, pageIndex, pageCount, effectiveS, startedAt,
        remainingMs, cancelled, abort.signal, (value) => { server = value; }, (value) => { launch = value; });
      const deadline = new Promise<never>((_, reject) => {
        deadlineTimer = setTimeout(() => {
          timedOut = true;
          abort.abort();
          launch?.cancel();
          this.killBrowser(server);
          reject(new RenderTimeoutError(effectiveS));
        }, remainingMs());
      });
      return await Promise.race([work, deadline]);
    } catch (error) {
      abort.abort();
      launch?.cancel();
      this.killBrowser(server);
      // Playwright's launch/connect timeout may win a few ms before our timer.
      if (timedOut || (error instanceof Error && error.name === "TimeoutError")) {
        timedOut = true;
        throw new RenderTimeoutError(effectiveS);
      }
      throw error;
    } finally {
      if (deadlineTimer) clearTimeout(deadlineTimer);
      this.active -= 1;
    }
  }

  /** Тело рендера без дедлайна (гонка — в renderPayload). */
  private async doRender(
    payload: RenderPagePayload,
    pageIndex: number,
    pageCount: number,
    effectiveS: number,
    startedAt: number,
    remainingMs: () => number,
    cancelled: () => boolean,
    signal: AbortSignal,
    setServer: (server: BrowserServer) => void,
    setGuard: (guard: LaunchGuard) => void,
  ): Promise<RenderOutcome> {
    const manifest = this.dependencyManifest();
    if (manifest.dependency_status === "unavailable") {
      throw new RenderDependencyError(manifest.unavailable_reason ?? "unknown");
    }
    let ownedServer: BrowserServer | null = null;
    let ownedGuard: LaunchGuard | null = null;
    let context: BrowserContext | null = null;
    try {
    const browser = await this.ensureBrowser(remainingMs, value => {
      ownedServer = value;
      setServer(value);
    }, value => { ownedGuard = value; setGuard(value); }, cancelled);
    if (cancelled()) throw new RenderTimeoutError(effectiveS);
    const spec = buildSandboxLaunchSpec();
    const scale = payload.options?.scale ?? 1;
    const html = await renderHtmlInWorker(payload, pageIndex, pageCount, signal);
    if (cancelled()) throw new RenderTimeoutError(effectiveS);
    const profile = payload.snapshot.print;
    const geometry = payload.snapshot.print;
    const width = Math.round(profileWidthPx(geometry.profile_id) * scale);
    const height = Math.round(profileHeightPx(geometry.profile_id) * scale);

    context = await browser.newContext({
      ...spec.pageContextOptions,
      viewport: { width: Math.max(50, width), height: Math.max(50, height) },
      deviceScaleFactor: 1,
      reducedMotion: "reduce",
      timezoneId: payload.snapshot.times.timezone || "UTC",
    });
    if (cancelled()) throw new RenderTimeoutError(effectiveS);
    const page = await context.newPage();
    page.setDefaultTimeout(remainingMs());
    const policy = buildRequestPolicy();
    await page.route("**/*", (route) => {
      const url = route.request().url();
      if (policy.shouldBlock(url)) {
        void route.abort("blockedbyclient");
        return;
      }
      void route.continue();
    });

    // Инлайн-HTML через setContent (без file://-навигации: политика
    // AC19 блокирует file://; вход страницы — только SSR-строка из
    // общего бандла). Temp-след Chromium (профиль контекста) убирается
    // context.close() в finally; /tmp контейнера — tmpfs (ephemeral).
    await page.setContent(html, { waitUntil: "load", timeout: remainingMs() });

    const surface = page.locator('[data-testid="print-page-surface"]');
    const rawPng = await surface.screenshot({ type: "png", timeout: remainingMs() });
    const ppi = profilePpi(geometry.profile_id);
    const png = injectPngPhys(rawPng, ppi);
    return {
      png,
      width,
      height,
      ppi,
      durationMs: Date.now() - startedAt,
      sha256: createHash("sha256").update(png).digest("hex"),
      sanitizerWarnings: collectSanitizerWarnings(payload),
    };
    } finally {
      try {
      try { await context?.close(); } catch { /* killed context */ }
      if (ownedServer) {
        // Normal completion also closes this job's browser; late completions
        // after cancellation cannot keep a browser or start a new page.
        if (cancelled()) this.killBrowser(ownedServer);
        else {
          try { await ownedServer.close(); }
          catch (error) { ownedGuard?.cancel(); this.killBrowser(ownedServer); throw error; }
          finally { this.servers.delete(ownedServer); }
        }
      }
      } finally {
        if (ownedGuard) {
          if (cancelled() || !ownedServer) ownedGuard.cancel();
          ownedGuard.cleanup();
          this.launches.delete(ownedGuard);
        }
      }
    }
  }

  async shutdown(): Promise<void> {
    this.stopping = true;
    for (const guard of this.launches) guard.cancel();
    for (const server of this.servers) this.killBrowser(server);
  }

}

/** SSR is CPU-bound: a JS timer cannot preempt it on the HTTP event loop.
 * The shared PGV-07 renderer runs in a terminable worker thread instead. */
export function renderHtmlInWorker(
  payload: RenderPagePayload, pageIndex: number, pageCount: number, signal: AbortSignal,
): Promise<string> {
  if (signal.aborted) return Promise.reject(new RenderTimeoutError(0));
  return new Promise((resolve, reject) => {
    const thread = new Worker(join(__dirname, "htmlWorker.js"), {
      workerData: { payload, pageIndex, pageCount },
      resourceLimits: { maxOldGenerationSizeMb: 256 },
    });
    let settled = false;
    const finish = (error?: Error, html?: string) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", cancel);
      void thread.terminate().catch(() => undefined);
      if (error) reject(error); else resolve(html!);
    };
    const cancel = () => finish(new RenderTimeoutError(0));
    signal.addEventListener("abort", cancel, { once: true });
    thread.once("message", message => {
      if (typeof message.html === "string") finish(undefined, message.html);
      else finish(new Error("print SSR failed"));
    });
    thread.once("error", error => finish(error));
    thread.once("exit", () => { if (!settled) finish(new Error("print SSR exited before result")); });
    if (signal.aborted) cancel();
  });
}

// ── Профильные геометрии (зеркало каталога PGV-01 для clip'а) ─────

const PROFILE_GEOMETRY: Record<string, { width: number; height: number; ppi: number }> = {
  "figure-landscape": { width: 2400, height: 1500, ppi: 300 },
  "a4-portrait": { width: 2480, height: 3508, ppi: 300 },
  "a4-landscape": { width: 3508, height: 2480, ppi: 300 },
};

function profileWidthPx(profileId: string): number {
  const geo = PROFILE_GEOMETRY[profileId];
  if (!geo) throw new Error(`Неизвестный профиль: ${profileId}`);
  return geo.width;
}

function profileHeightPx(profileId: string): number {
  const geo = PROFILE_GEOMETRY[profileId];
  if (!geo) throw new Error(`Неизвестный профиль: ${profileId}`);
  return geo.height;
}

function profilePpi(profileId: string): number {
  const geo = PROFILE_GEOMETRY[profileId];
  if (!geo) throw new Error(`Неизвестный профиль: ${profileId}`);
  return geo.ppi;
}

function collectSanitizerWarnings(payload: RenderPagePayload): string[] {
  const warnings: string[] = [];
  for (const section of payload.sections) {
    if (section.kind === "recharts_svg" && section.svg_xml) {
      // Повторный прогон санитайзера для отчёта (fail-visible, AC19):
      // buildPrintHtml уже применял его при SSR.
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { sanitizeFrozenSvg } = require("./rendererCore") as typeof import("./rendererCore");
      warnings.push(...sanitizeFrozenSvg(section.svg_xml).warnings);
    }
  }
  return warnings;
}

export { RENDERER_VERSION, RENDERER_FONT_PROFILE };
