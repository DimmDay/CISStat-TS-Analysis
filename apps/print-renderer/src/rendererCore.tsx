// apps/print-renderer/src/rendererCore.tsx
//
// PGV-08 — Sandboxed renderer container: ЧИСТОЕ ЯДРО рендерера
// (spec_passport_graphics_visual.md §13 строка PGV-08; критерий
// «Final image smoke кириллица/IH/A4, no-network/non-root/hard timeout»).
//
// Границы ядра (jest-оракулы rendererCore.test.ts):
//   • версии контрактов (pgv.render_payload/1, print-renderer/1, порт 8907);
//   • валидация payload (паритет кодов PGV-01: invalid_profile,
//     invalid_section_kind, empty_sections, missing_field, ...);
//   • dependency-манифест (AC17: missing browser/fonts/bundle → честный
//     render_dependency_unavailable, никогда не ложный ready; §12
//     «Readiness отдельно проверяет browser/fonts/print bundle»);
//   • sandbox-политика (AC19: JS/serviceWorkers выключены, все внешние
//     схемы блокируются, --force-color-profile=srgb для детерминизма);
//   • санитайзер frozen SVG (AC19: script/foreignObject/on*/внешние href);
//   • pHYs-инъекция 300 ppi (AC16: px⇄мм⇄ppi согласованы, PNG несёт
//     физический размер; 300 dpi = 11811 px/m);
//   • SSR print page ИЗ ОБЩЕГО БАНДЛА PGV-07 (§4.1: «без второй
//     реализации» — PrintPageFrame/printSections/printIh используются
//     напрямую, react-dom/server);
//   • hard timeout контракт (AC20: зажим в [1, hard], kill по превышении
//     — в renderWorker; тела ошибок с честной retryability).
//
// Чистота: без fetch/сети/времени/случайности; БЕЗ playwright-core
// (браузерный слой — renderWorker.ts, jest-оракулы ядро не тянут).

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { crc32 } from "node:zlib";
import { deflateSync } from "node:zlib";

import type { PrintProfileId, UnitDeclaration, VisualPrintSnapshotV1 } from "../../../packages/ui/print/printSchema";
import { PRINT_PROFILE_CATALOG, resolvePrintProfile } from "../../../packages/ui/print/printSchema";
import { PRINT_LIMITS } from "../../../packages/ui/print/printSchema";
import {
  PrintPageFrame,
  formatNumberRu,
} from "../../../packages/ui/print/printLayout";
import {
  PrintTableSection,
  PrintHeatmapSection,
  PrintCardsSection,
  PrintChartSection,
} from "../../../packages/ui/print/printSections";
import { PrintIhConditionalMatrix } from "../../../packages/ui/print/printIh";
import type { PrintIhConditionalInput } from "../../../packages/ui/print/printIh";

// ── Версии контрактов ─────────────────────────────────────────────

/** Версия payload рендера (versioned, паритет схем PGV-01). */
export const RENDER_PAYLOAD_SCHEMA_VERSION = "pgv.render_payload/1";

/** Версия рендерера (renderer_env.renderer_value снапшота, PGV-01 §6). */
export const RENDERER_VERSION = "print-renderer/1";

/** Пин шрифтового профиля контейнера (§12: fonts pinned). */
export const RENDERER_FONT_PROFILE = "print-fonts-dejavu/1";

/** Порт HTTP-сервиса рендера по умолчанию (не пересекается с 8000/3000/8501). */
export const RENDER_PORT_DEFAULT = 8907;

/**
 * Hard timeout по умолчанию — render_timeout_s каталога PGV-01 (60 s;
 * spec §18 «PDF до 60 s», §11 «Timeout убивает browser process/context»).
 * Пин через каталог: изменение PGV-01 автоматически видно оракулу.
 */
export const DEFAULT_HARD_TIMEOUT_S: number = PRINT_LIMITS.render_timeout_s;

// ── Payload: pgv.render_payload/1 ─────────────────────────────────

/**
 * Содержимое секции для рендера. Спек-метаданные (title/axes/legend/
 * units) живут в snapshot.display.sections (PGV-01); payload несёт
 * КОНТЕНТ секции — frozen данные producer'а, без пересчёта науки (AC06).
 */
export type RenderSectionContent =
  | { section_id: string; kind: "html_table"; title?: string | null; headings: { row: string[]; column: string[] }; rows: readonly (readonly string[])[]; rows_per_page?: number; caption?: string | null; units?: UnitDeclaration[] }
  | { section_id: string; kind: "html_heatmap"; title?: string | null; row_headings: readonly string[]; column_headings: readonly string[]; cells: readonly (readonly (number | null)[])[]; cell_texts: readonly (readonly (string | null)[])[]; domain?: [number, number] | null; units?: UnitDeclaration }
  | { section_id: string; kind: "html_cards"; title?: string | null; cards: readonly { label: string; value: string; unit?: { value: string | null; reason: string | null } }[] }
  | { section_id: string; kind: "ih_conditional"; title?: string | null; ih_input: PrintIhConditionalInput }
  | { section_id: string; kind: "recharts_svg"; title?: string | null; svg_xml?: string | null; height_px?: number };

/** Payload POST /v1/render: frozen снапшот PGV-01 + контент секций. */
export interface RenderPagePayload {
  schema_version: typeof RENDER_PAYLOAD_SCHEMA_VERSION;
  request_id: string;
  snapshot: VisualPrintSnapshotV1;
  sections: readonly RenderSectionContent[];
  /** Опции рендера: timeout_s (зажим hard cap'ом, AC20); scale — только probe. */
  options?: { timeout_s?: number | null; scale?: number | null };
}

/** Нарушение валидации (паритет кодов PGV-01 для PGV-09-интеграции). */
export interface RenderPayloadViolation {
  code: string;
  path: string;
  message: string;
}

const SECTION_KINDS: readonly string[] = [
  "html_table",
  "html_heatmap",
  "html_cards",
  "ih_conditional",
  "recharts_svg",
];

function violation(code: string, path: string, message: string): RenderPayloadViolation {
  return { code, path, message };
}

/** Валидация payload: коды — паритет VIOLATION_CODES PGV-01 (422). */
export function validateRenderPayload(raw: unknown): {
  violations: RenderPayloadViolation[];
  payload: RenderPagePayload | null;
} {
  const out: RenderPayloadViolation[] = [];
  if (typeof raw !== "object" || raw === null) {
    return { violations: [violation("missing_field", ".", "payload обязан быть объектом")], payload: null };
  }
  const value = raw as Record<string, unknown>;

  if (value.schema_version !== RENDER_PAYLOAD_SCHEMA_VERSION) {
    out.push(
      violation(
        "schema_version_mismatch",
        "schema_version",
        `ожидается ${RENDER_PAYLOAD_SCHEMA_VERSION}`,
      ),
    );
  }
  if (typeof value.request_id !== "string" || value.request_id.length === 0) {
    out.push(violation("missing_field", "request_id", "request_id обязателен"));
  }
  const snapshot = value.snapshot as VisualPrintSnapshotV1 | undefined;
  if (typeof snapshot !== "object" || snapshot === null) {
    out.push(violation("missing_field", "snapshot", "frozen snapshot (PGV-01) обязателен"));
    return { violations: out, payload: null };
  }
  const profile = (snapshot as VisualPrintSnapshotV1).print?.profile_id;
  if (typeof profile !== "string" || resolvePrintProfile(profile) === undefined) {
    out.push(
      violation("invalid_profile", "snapshot.print.profile_id", "профиль обязан быть из каталога PGV-01"),
    );
  }

  const sections = value.sections;
  if (!Array.isArray(sections) || sections.length === 0) {
    out.push(violation("empty_sections", "sections", "список секций не может быть пустым"));
  } else {
    const seen = new Set<string>();
    sections.forEach((section, index) => {
      const path = `sections[${index}]`;
      const rec = section as Record<string, unknown> | null;
      if (typeof rec !== "object" || rec === null) {
        out.push(violation("missing_field", path, "секция обязана быть объектом"));
        return;
      }
      const kind = rec.kind;
      if (typeof kind !== "string" || !SECTION_KINDS.includes(kind)) {
        out.push(violation("invalid_section_kind", `${path}.kind`, "недопустимый renderer_kind секции"));
        return;
      }
      const sectionId = rec.section_id;
      if (typeof sectionId !== "string" || sectionId.length === 0) {
        out.push(violation("missing_field", `${path}.section_id`, "section_id обязателен"));
      } else if (seen.has(sectionId)) {
        out.push(violation("duplicate_section", `${path}.section_id`, "section_id не уникален"));
      } else {
        seen.add(sectionId);
      }
      if (kind === "ih_conditional" && typeof rec.ih_input !== "object") {
        out.push(
          violation("missing_field", `${path}.ih_input`, "ih_conditional обязан нести frozen ih_input"),
        );
      }
      if (kind === "html_table" && typeof rec.headings !== "object") {
        out.push(violation("missing_table_headings", `${path}.headings`, "таблица обязана нести headings"));
      }
      if (kind === "html_heatmap") {
        if (!Array.isArray(rec.row_headings) || !Array.isArray(rec.column_headings)) {
          out.push(violation("missing_field", `${path}`, "теплокарта обязана нести заголовки строк/колонок"));
        }
        if (!Array.isArray(rec.cells)) {
          out.push(violation("missing_field", `${path}.cells`, "теплокарта обязана нести ячейки"));
        }
      }
      if (kind === "html_cards" && !Array.isArray(rec.cards)) {
        out.push(violation("missing_field", `${path}.cards`, "карточки обязаны нести cards"));
      }
    });
  }

  if (out.length > 0) return { violations: out, payload: null };
  return { violations: [], payload: value as unknown as RenderPagePayload };
}

// ── Dependency-манифест (AC17: без ложного ready) ─────────────────

export const DEPENDENCY_CHECKS: readonly string[] = ["browser", "fonts", "bundle"];

export interface DependencyInputs {
  /** Путь к executable Chromium (null/пустой — зависимости нет). */
  browserExecutable: string | null;
  /** Пинованные файлы шрифтов (пусто — зависимости нет). */
  fontFiles: readonly string[];
  /** Print-бандл PGV-07 импортирован и резолвится. */
  bundleLoaded: boolean;
}

export interface DependencyManifest {
  dependency_status: "available" | "unavailable" | "unknown";
  unavailable_reason: string | null;
  checks: { browser: boolean; fonts: boolean; bundle: boolean };
  renderer_version: string;
  font_profile: string;
}

/**
 * Честный манифест зависимостей (§12): readiness отдельно проверяет
 * browser/fonts/print bundle; первый недостающий ресурс даёт
 * детерминированную причину (missing_browser/missing_fonts/missing_bundle).
 * Код причины потребляется как render_dependency_unavailable (AC17,
 * terminal — бесполезный retry исключён).
 */
export function buildDependencyManifest(inputs: DependencyInputs): DependencyManifest {
  const browserOk = typeof inputs.browserExecutable === "string" && inputs.browserExecutable.length > 0;
  const fontsOk = Array.isArray(inputs.fontFiles) && inputs.fontFiles.length > 0;
  const bundleOk = inputs.bundleLoaded === true;
  let status: DependencyManifest["dependency_status"] = "available";
  let reason: string | null = null;
  if (!browserOk) {
    status = "unavailable";
    reason = "missing_browser";
  } else if (!fontsOk) {
    status = "unavailable";
    reason = "missing_fonts";
  } else if (!bundleOk) {
    status = "unavailable";
    reason = "missing_bundle";
  }
  return {
    dependency_status: status,
    unavailable_reason: reason,
    checks: { browser: browserOk, fonts: fontsOk, bundle: bundleOk },
    renderer_version: RENDERER_VERSION,
    font_profile: RENDERER_FONT_PROFILE,
  };
}

// ── Sandbox-политика (AC19) ───────────────────────────────────────

/**
 * Аргументы запуска Chromium: детерминизм (--force-color-profile=srgb,
 * --font-render-hinting=none, --hide-scrollbars) + отключение фоновых
 * сетевых/компонентных служб. Chromium-песочница НЕ выключается
 * (--no-sandbox не используется) — контейнер работает от non-root
 * пользователя; в orchestrator-средах без user namespaces документируется
 * deployment-README (risks R1) — граница сети/скриптов держится слоями
 * ниже (JS off, request-block, CSP, network none).
 */
export function buildSandboxLaunchSpec(): {
  chromiumArgs: string[];
  pageContextOptions: { javaScriptEnabled: false; serviceWorkers: "block"; bypassCSP: false };
} {
  return {
    chromiumArgs: [
      "--disable-background-networking",
      "--disable-component-update",
      "--disable-sync",
      "--disable-extensions",
      "--disable-breakpad",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--no-first-run",
      "--no-default-browser-check",
      "--no-pings",
      "--metrics-recording-only",
      "--force-color-profile=srgb",
      "--font-render-hinting=none",
      "--hide-scrollbars",
      "--disable-features=Translate,BackForwardCache,OptimizationHints,MediaRouter",
    ],
    pageContextOptions: {
      javaScriptEnabled: false,
      serviceWorkers: "block",
      bypassCSP: false,
    },
  };
}

export interface RequestPolicy {
  shouldBlock(url: string): boolean;
  /** Причина блокировки (для журнала; null — не блокируется). */
  blockReason(url: string): string | null;
}

/**
 * Политика запросов страницы (AC19: «Script/remote image/SSRF/file URL
 * не исполняются»): все внешние/файловые схемы блокируются ДО сети;
 * разрешены только data: и about:blank (страница — инлайн-HTML от SSR).
 */
export function buildRequestPolicy(): RequestPolicy {
  const blockedPrefixes = ["http://", "https://", "file://", "blob:", "ftp://", "ws://", "wss://"];
  const shouldBlock = (url: string): boolean => {
    const lowered = (url ?? "").toLowerCase().trim();
    if (lowered === "" || lowered === "about:blank") return false;
    if (lowered.startsWith("data:")) return false;
    return blockedPrefixes.some((prefix) => lowered.startsWith(prefix));
  };
  return {
    shouldBlock,
    blockReason(url: string): string | null {
      if (!shouldBlock(url)) return null;
      const lowered = url.toLowerCase().trim();
      if (lowered.startsWith("file://")) return "file_url_blocked";
      if (lowered.startsWith("data:") || lowered === "about:blank") return null;
      return "external_url_blocked";
    },
  };
}

// ── Санитайзер frozen SVG (AC19) ──────────────────────────────────

export interface SanitizeResult {
  xml: string;
  warnings: string[];
}

/**
 * Санитайзер СЕРИАЛИЗОВАННОЙ научной геометрии (frozen producer SVG,
 * §4.1 passthrough). Пользовательский HTML/SVG запрещён — вход идёт
 * только из frozen снапшота; санитайзер — защита в глубину:
 *   • <script>…</script> удаляются;
 *   • foreignObject удаляется (HTML-in-SVG);
 *   • on*-обработчики удаляются;
 *   • внешние ссылки (http/https/file/blob/protocol-relative) в
 *     href/src/xlink:href заменяются честным пустым значением.
 * Удаления НЕ молчаливы: каждое попадает в warnings (fail-visible).
 */
export function sanitizeFrozenSvg(xml: string): SanitizeResult {
  const warnings: string[] = [];
  let out = xml ?? "";
  if (/<script[\s>]/i.test(out)) {
    out = out.replace(/<script[\s\S]*?<\/script\s*>/gi, "").replace(/<script[^>]*\/?>/gi, "");
    warnings.push("svg: удалён <script>");
  }
  if (/foreignObject/i.test(out)) {
    out = out.replace(/<foreignObject[\s\S]*?<\/foreignObject\s*>/gi, "").replace(/<foreignObject[^>]*\/?>/gi, "");
    warnings.push("svg: удалён foreignObject");
  }
  if (/\son[a-zA-Z]+\s*=/i.test(out)) {
    out = out.replace(/\son[a-zA-Z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, "");
    warnings.push("svg: удалены on*-обработчики");
  }
  const externalRef = /(\s(?:href|xlink:href|src)\s*=\s*)(["'])(?!data:|#)(?:https?:|file:|blob:|ftp:|\/\/)[^"']*\2/gi;
  if (externalRef.test(out)) {
    out = out.replace(externalRef, "$1$2$2");
    warnings.push("svg: удалены внешние ссылки (href/src)");
  }
  return { xml: out, warnings };
}

// ── Hard timeout (AC20) ───────────────────────────────────────────

/**
 * Эффективный таймаут: зажим запроса в [1, hardCap]. Запрос больше cap
 * НЕ расширяет hard limit (§11: «Timeout убивает … не оставляет
 * неограниченный thread»); неположительные значения — минимум 1 s.
 */
export function clampTimeoutSeconds(requested: number | null | undefined, hardCap: number): number {
  const cap = Math.max(1, Math.floor(hardCap));
  if (typeof requested !== "number" || !Number.isFinite(requested)) return cap;
  return Math.min(cap, Math.max(1, Math.floor(requested)));
}

/** Коды ошибок рендера и их честная повторяемость (для X-Render-Retryable). */
export const ERROR_BODY_RETRYABILITY: Record<string, boolean> = {
  render_dependency_unavailable: false,
  render_timeout: true,
  renderer_busy: true,
  invalid_payload: false,
  payload_too_large: false,
  internal_render_error: false,
};

export interface RenderErrorBody {
  error: { code: string; message: string; retryable: boolean; renderer_version: string };
}

/** Единое тело ошибки рендера (потребитель — PGV-09 document_jobs). */
export function buildErrorBody(code: string, message: string): RenderErrorBody {
  const retryable = ERROR_BODY_RETRYABILITY[code] ?? false;
  return { error: { code, message, retryable, renderer_version: RENDERER_VERSION } };
}

// ── PNG: pHYs-инъекция (AC16) ─────────────────────────────────────

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function pngChunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, "ascii");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])) >>> 0, 0);
  return Buffer.concat([len, typeBuf, data, crc]);
}

/** ppi → px/метр (PNG pHYs, unit=1): 300 ppi → 11811 px/m. */
export function ppiToPixelsPerMeter(ppi: number): number {
  return Math.round(ppi / 0.0254);
}

export interface PngStructureInfo {
  width: number;
  height: number;
  hasPhys: boolean;
  physPpuX: number | null;
  physPpuY: number | null;
  idatBytes: number;
}

/** Байт-разбор PNG (смоук внутри контейнера — без растровых библиотек). */
export function parsePngChunks(png: Buffer): PngStructureInfo {
  if (png.length < 8 || !png.subarray(0, 8).equals(PNG_SIGNATURE)) {
    throw new Error("Не PNG: сигнатура не совпала");
  }
  let offset = 8;
  let width = 0;
  let height = 0;
  let hasPhys = false;
  let physPpuX: number | null = null;
  let physPpuY: number | null = null;
  let idatBytes = 0;
  while (offset + 8 <= png.length) {
    const len = png.readUInt32BE(offset);
    const type = png.toString("ascii", offset + 4, offset + 8);
    const data = png.subarray(offset + 8, offset + 8 + len);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
    } else if (type === "pHYs") {
      hasPhys = true;
      physPpuX = data.readUInt32BE(0);
      physPpuY = data.readUInt32BE(4);
    } else if (type === "IDAT") {
      idatBytes += len;
    }
    offset += 12 + len;
    if (type === "IEND") break;
  }
  return { width, height, hasPhys, physPpuX, physPpuY, idatBytes };
}

/**
 * Вставка/замена pHYs чанка (AC16): PNG рендера несёт ФИЗИЧЕСКИЙ размер
 * профиля (300 ppi → 11811 px/m). Чанк ставится сразу после IHDR (до
 * PLTE/IDAT — требования PNG-спеки к порядку ancillary chunks), CRC
 * пересчитывается, существующий pHYs заменяется (идемпотентность).
 * Байты изображения (IHDR/IDAT/IEND) не меняются.
 */
export function injectPngPhys(png: Buffer, ppi: number): Buffer {
  if (png.length < 8 || !png.subarray(0, 8).equals(PNG_SIGNATURE)) {
    throw new Error("injectPngPhys: вход не PNG (сигнатура)");
  }
  const ppu = ppiToPixelsPerMeter(ppi);
  const phys = Buffer.alloc(9);
  phys.writeUInt32BE(ppu, 0);
  phys.writeUInt32BE(ppu, 4);
  phys[8] = 1; // unit = метр
  const physChunk = pngChunk("pHYs", phys);
  // Позиция сразу после IHDR-чанка: 8 (сигнатура) + 12 + 13 (IHDR).
  const ihdrEnd = 8 + 12 + 13;
  // Идемпотентность: если pHYs уже есть сразу после IHDR — вырезаем.
  const len = png.readUInt32BE(ihdrEnd);
  const nextType = png.toString("ascii", ihdrEnd + 4, ihdrEnd + 8);
  let head: Buffer;
  let tail: Buffer;
  if (nextType === "pHYs") {
    head = png.subarray(0, ihdrEnd);
    tail = png.subarray(ihdrEnd + 12 + len);
  } else {
    head = png.subarray(0, ihdrEnd);
    tail = png.subarray(ihdrEnd);
  }
  return Buffer.concat([head, physChunk, tail]);
}

// ── SSR print page (§4.1: общий бандл PGV-07, без второй реализации) ──

const CSP_META =
  "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src none; script-src 'none'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";

function renderSectionElement(section: RenderSectionContent): React.ReactElement {
  if (section.kind === "html_table") {
    return React.createElement(PrintTableSection, {
      key: section.section_id,
      spec: {
        section_id: section.section_id,
        renderer_kind: "html_table",
        title: section.title ?? null,
        axes: [],
        legend_ordering: [],
        table_headings: section.headings,
        heatmap_scale: null,
        units: section.units ?? [],
      },
      headings: section.headings,
      rows: section.rows,
      rowsPerPage: section.rows_per_page,
      caption: section.caption ?? null,
    });
  }
  if (section.kind === "html_heatmap") {
    const domain: [number, number] = section.domain ?? defaultHeatDomain(section.cells);
    return React.createElement(PrintHeatmapSection, {
      key: section.section_id,
      spec: {
        section_id: section.section_id,
        renderer_kind: "html_heatmap",
        title: section.title ?? null,
        axes: [],
        legend_ordering: [],
        table_headings: null,
        heatmap_scale: {
          domain,
          units: section.units ?? { value: null, reason: "dimensionless" },
        },
        units: [],
      },
      rowHeadings: section.row_headings,
      columnHeadings: section.column_headings,
      cellValue: (row: number, column: number) => section.cells[row]?.[column] ?? null,
      cellText: (row: number, column: number) => {
        const text = section.cell_texts?.[row]?.[column];
        if (text !== null && text !== undefined) return text;
        const cell = section.cells[row]?.[column];
        return cell === null || cell === undefined ? "нет данных" : formatNumberRu(cell, 1);
      },
    });
  }
  if (section.kind === "html_cards") {
    return React.createElement(PrintCardsSection, {
      key: section.section_id,
      spec: {
        section_id: section.section_id,
        renderer_kind: "html_cards",
        title: section.title ?? null,
        axes: [],
        legend_ordering: [],
        table_headings: null,
        heatmap_scale: null,
        units: [],
      },
      cards: section.cards,
    });
  }
  if (section.kind === "ih_conditional") {
    return React.createElement(
      "section",
      { key: section.section_id, style: { display: "flex", flexDirection: "column", gap: 8 } },
      [
        section.title ? React.createElement("h3", { key: "t", style: { fontSize: 14, fontWeight: 600, margin: 0 } }, section.title) : null,
        React.createElement(PrintIhConditionalMatrix, { key: "ih", input: section.ih_input }),
      ],
    );
  }
  // recharts_svg: научная геометрия — сериализованный frozen SVG
  // (§4.1 passthrough: экранная геометрия, не вторая реализация).
  const sanitized = sanitizeFrozenSvg(section.svg_xml ?? "");
  if (!sanitized.xml.trim()) {
    return React.createElement(
      "section",
      { key: section.section_id, "data-testid": "print-chart-unwired" },
      React.createElement(
        "p",
        { style: { fontSize: 12, color: "#525252" } },
        "научная геометрия не приложена к frozen снапшоту (подключение экранной геометрии — PGV-10…12); график не фабрикуется",
      ),
    );
  }
  return React.createElement(PrintChartSection, {
    key: section.section_id,
    spec: {
      section_id: section.section_id,
      renderer_kind: "recharts_svg",
      title: section.title ?? null,
      axes: [],
      legend_ordering: [],
      table_headings: null,
      heatmap_scale: null,
      units: [],
    },
    heightPx: section.height_px ?? 900,
    children: React.createElement("div", {
      style: { width: "100%", maxWidth: "100%" },
      // dangerouslySetInnerHTML осознанно: вход — санитизированный frozen
      // SVG producer'а (AC19: sanitizeFrozenSvg + JS-off + CSP + request-block).
      dangerouslySetInnerHTML: { __html: sanitized.xml },
    }),
  });
}

/** Домен шкалы теплокарты по фактическим ячейкам (без фабкации: пусто → [0, 1]). */
function defaultHeatDomain(cells: readonly (readonly (number | null)[])[]): [number, number] {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const row of cells) {
    for (const cell of row) {
      if (cell === null || cell === undefined) continue;
      if (cell < min) min = cell;
      if (cell > max) max = cell;
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  return [min, max];
}

export interface PrintHtmlResult {
  html: string;
  /** Предупреждения санитайзера (fail-visible, AC19). */
  sanitizer_warnings: string[];
}

/**
 * Полный HTML print page из frozen снапшота И ОБЩЕГО БАНДЛА PGV-07:
 * lang="ru", CSP meta (default-src 'none'), base about:blank, инлайн-тело
 * (print-бандл сам несёт светлую тему инлайном — AC04). Никаких <script>
 * и внешних URL: страница рендерится с JS-off и request-block'ом (AC19).
 */
export function buildPrintHtml(
  payload: RenderPagePayload,
  pageIndex: number,
  pageCount: number,
): string {
  const snapshot = payload.snapshot;
  const profileId = snapshot.print.profile_id;
  const profile = resolvePrintProfile(profileId) ?? PRINT_PROFILE_CATALOG[0];
  // scale — только для быстрого probe/readiness (мини-рендер); продовые
  // рендеры всегда scale=1 (полные px профиля, лимит 12 MP PGV-01).
  const scale = payload.options?.scale ?? 1;
  const body = renderToStaticMarkup(
    React.createElement(
      PrintPageFrame,
      { snapshot, pageIndex, pageCount, profileId: profile.id, scale },
      payload.sections.map((section) => renderSectionElement(section)),
    ),
  );
  const sanitizerWarnings: string[] = [];
  for (const section of payload.sections) {
    if (section.kind === "recharts_svg" && section.svg_xml) {
      sanitizerWarnings.push(...sanitizeFrozenSvg(section.svg_xml).warnings);
    }
  }
  const html = [
    "<!DOCTYPE html>",
    '<html lang="ru">',
    "<head>",
    '<meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${CSP_META}">`,
    '<base href="about:blank">',
    // Reset: поверхность профиля — от (0,0); фон страницы белый на весь
    // документ (AC04: непрозрачный light-print, без прозрачных полей).
    "<style>html,body{margin:0;padding:0;background:#FFFFFF}</style>",
    `<title>${escapeHtml(snapshot.display.title)}</title>`,
    "</head>",
    "<body>",
    body,
    "</body>",
    "</html>",
  ].join("");
  return html;
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
