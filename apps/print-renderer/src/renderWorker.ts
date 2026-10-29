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

import type { Browser, BrowserContext } from "playwright-core";

import {
  buildDependencyManifest,
  buildPrintHtml,
  buildRequestPolicy,
  buildSandboxLaunchSpec,
  clampTimeoutSeconds,
  DEFAULT_HARD_TIMEOUT_S,
  injectPngPhys,
  RENDERER_FONT_PROFILE,
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

export function readConfig(env: NodeJS.ProcessEnv = process.env): RendererConfig {
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
  private browserPromise: Promise<Browser> | null = null;
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

  private async ensureBrowser(): Promise<Browser> {
    if (!this.browserPromise) {
      this.browserPromise = (async () => {
        if (!this.playwrightModule) {
          this.playwrightModule = await import("playwright-core");
        }
        const manifest = this.dependencyManifest();
        if (manifest.dependency_status === "unavailable") {
          throw new RenderDependencyError(manifest.unavailable_reason ?? "unknown");
        }
        const spec = buildSandboxLaunchSpec();
        const executablePath =
          this.config.browserPath ?? (this.playwrightModule!.chromium.executablePath() as string);
        return this.playwrightModule!.chromium.launch({
          executablePath,
          headless: true,
          args: spec.chromiumArgs,
          timeout: 30_000,
        });
      })();
      this.browserPromise.catch(() => {
        // Провал запуска сбрасывает синглтон: следующий запрос честно
        // повторит диагностику (AC17 — без залипшего false-ready).
        this.browserPromise = null;
      });
    }
    return this.browserPromise;
  }

  /** Аварийное уничтожение браузера (AC20: зависший процесс не переживает таймаут). */
  private killBrowser(browser: Browser | null): void {
    try {
      // process() есть в рантайме playwright-core, но не в публичных
      // typings ряда версий — честный структурный каст.
      const proc = (
        browser as unknown as {
          process?: () => { pid?: number; kill: (signal: string) => void } | null;
        }
      ).process?.();
      if (proc && proc.pid) {
        proc.kill("SIGKILL");
      }
      void browser?.close({ reason: "hard timeout kill" }).catch(() => undefined);
    } catch {
      // Процесс мог уже умереть — не маскируем основной отказ.
    }
    this.browserPromise = null;
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
    if (this.active >= this.config.maxConcurrent) {
      throw new RendererBusyError(this.config.maxConcurrent);
    }
    this.active += 1;
    const startedAt = Date.now();
    let context: BrowserContext | null = null;
    let browser: Browser | null = null;
    let timedOut = false;
    let deadlineTimer: NodeJS.Timeout | null = null;
    const effectiveS = clampTimeoutSeconds(payload.options?.timeout_s, this.config.hardTimeoutS);
    try {
      const work = this.doRender(
        payload,
        pageIndex,
        pageCount,
        effectiveS,
        startedAt,
        (b) => {
          browser = b;
        },
        (c) => {
          context = c;
        },
      );
      const timeoutPromise = new Promise<never>((_, reject) => {
        deadlineTimer = setTimeout(() => {
          timedOut = true;
          reject(new RenderTimeoutError(effectiveS));
        }, effectiveS * 1000);
      });
      return await Promise.race([work, timeoutPromise]);
    } catch (error) {
      if (timedOut) {
        // AC20: таймаут убивает браузер (не только контекст) — зависший
        // рендер не должен переживать запрос ни процессом, ни потоком.
        this.killBrowser(browser);
        browser = null;
        context = null;
      }
      throw error;
    } finally {
      if (deadlineTimer) clearTimeout(deadlineTimer);
      try {
        if (context) await context.close();
      } catch {
        // Контекст мог уже умереть при kill.
      }
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
    setBrowser: (browser: Browser) => void,
    setContext: (context: BrowserContext) => void,
  ): Promise<RenderOutcome> {
    const manifest = this.dependencyManifest();
    if (manifest.dependency_status === "unavailable") {
      throw new RenderDependencyError(manifest.unavailable_reason ?? "unknown");
    }
    const browser = await this.ensureBrowser();
    setBrowser(browser);
    const spec = buildSandboxLaunchSpec();
    const scale = payload.options?.scale ?? 1;
    const html = buildPrintHtml(payload, pageIndex, pageCount);
    const profile = payload.snapshot.print;
    const geometry = payload.snapshot.print;
    const width = Math.round(profileWidthPx(geometry.profile_id) * scale);
    const height = Math.round(profileHeightPx(geometry.profile_id) * scale);

    const context = await browser.newContext({
      ...spec.pageContextOptions,
      viewport: { width: Math.max(50, width), height: Math.max(50, height) },
      deviceScaleFactor: 1,
      reducedMotion: "reduce",
      timezoneId: payload.snapshot.times.timezone || "UTC",
    });
    setContext(context);
    const page = await context.newPage();
    page.setDefaultTimeout(effectiveS * 1000);
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
    await page.setContent(html, { waitUntil: "load", timeout: effectiveS * 1000 });

    const surface = page.locator('[data-testid="print-page-surface"]');
    const rawPng = await surface.screenshot({ type: "png", timeout: effectiveS * 1000 });
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
  }

  /** Плавная остановка (SIGTERM): браузер закрывается, не бросая задач. */
  async shutdown(): Promise<void> {
    const promise = this.browserPromise;
    this.browserPromise = null;
    if (!promise) return;
    try {
      const browser = await promise;
      await browser.close();
    } catch {
      // Уже мёртв — не важно.
    }
  }
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
