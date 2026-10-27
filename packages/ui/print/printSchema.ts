// packages/ui/print/printSchema.ts
//
// PGV-01 — print schema/metadata/profile (spec_passport_graphics_visual.md
// §6 «Данные и метаданные визуализаций», §7 «PNG и печатная композиция»,
// §13 строка PGV-01; критерий готовности: «Result/version/date/units/
// sampling обязательны по applicability, параметры trusted»).
//
// Состав (versioned contracts):
//   - VisualResult/1        — immutable frozen input producer'а (spec §6);
//   - VisualPrintSnapshot/1 — frozen печатная основа: refs/version/hash,
//     оси/легенда/метод, sampling, print profile, renderer env (spec §6);
//   - PrintSetManifest/1    — комплект страниц ZIP: порядок/имена/роли/
//     hash ПОЛЬЗОВАТЕЛЬСКИМ ПОЛЕМ, не внутрь PNG bytes (spec §7);
//   - каталог print-профилей (figure-landscape / A4 300 ppi) и лимиты §7.
//
// Источник истины — этот модуль; JSON-твин config/print_schema.json
// (генератор scripts/pgv01/export_print_schema.ts) — для Python-зеркала
// apps/api/print_schema.py (preflight PGV-02/09) и doc-проверок. Паритет
// гвардят jest-оракулы printSchema.test.ts (паттерн EDU-API-1/PGV-00).
//
// Обязательность metadata «по applicability» выводится из реестра PGV-00
// (packages/ui/lib/visualExportRegistry.ts): scope сайта (demo/research/
// passport/comparison), его required_refs и renderer_kind определяют
// обязательный набор полей снапшота. Единицы/даты не выдумываются:
// отсутствие — только с явной null-причиной (legacy_unknown и пр., §6/§8).
//
// Границы PGV-01: схемы/валидация/профили — НЕ runtime. Durable store,
// jobs, PNG renderer и UI — PGV-02…09/13/15 (spec §13). Существующие
// пути скачивания не меняются.

import type { VisualSiteRecord, VisualRendererKind } from "../lib/visualExportRegistry";

// ── Версии схем ──────────────────────────────────────────────────

export const PRINT_SCHEMA_DOCUMENT_VERSION = "pgv.print_schema/1";
export const VISUAL_RESULT_SCHEMA_VERSION = "pgv.visual_result/1";
export const VISUAL_PRINT_SNAPSHOT_SCHEMA_VERSION = "pgv.visual_print_snapshot/1";
export const PRINT_MANIFEST_SCHEMA_VERSION = "pgv.print_manifest/1";
export const PRINT_PROFILES_SCHEMA_VERSION = "pgv.print_profiles/1";

// ── Print-профили (spec §7) ──────────────────────────────────────

export type PrintProfileId = "figure-landscape" | "a4-portrait" | "a4-landscape";

export interface PrintProfileSpec {
  id: PrintProfileId;
  label_ru: string;
  orientation: "landscape" | "portrait";
  width_px: number;
  height_px: number;
  ppi: number;
  width_in: number;
  height_in: number;
  width_mm: number;
  height_mm: number;
  is_default: boolean;
  /** Назначение профиля; физический размер, не рост информативности (§7). */
  notes: string;
}

export const PRINT_PROFILE_CATALOG: readonly PrintProfileSpec[] = [
  {
    id: "figure-landscape",
    label_ru: "Рисунок (альбомная)",
    orientation: "landscape",
    width_px: 2400,
    height_px: 1500,
    ppi: 300,
    width_in: 8,
    height_in: 5,
    width_mm: 203.2,
    height_mm: 127,
    is_default: true,
    notes:
      "Профиль «Рисунок» для статьи/вставки: 8×5 дюймов при 300 ppi = 2400×1500 px. Физический профиль, не увеличение информативности выборки (spec §7).",
  },
  {
    id: "a4-portrait",
    label_ru: "Лист A4 (книжная)",
    orientation: "portrait",
    width_px: 2480,
    height_px: 3508,
    ppi: 300,
    width_in: 8.2667,
    height_in: 11.6933,
    width_mm: 210,
    height_mm: 297,
    is_default: false,
    notes:
      "A4 при 300 ppi — 2480×3508 px (spec §7); физический лист 210×297 мм. Пиксели — закреплённое округление спеки (210 мм / 25.4 × 300 = 2480.3).",
  },
  {
    id: "a4-landscape",
    label_ru: "Лист A4 (альбомная)",
    orientation: "landscape",
    width_px: 3508,
    height_px: 2480,
    ppi: 300,
    width_in: 11.6933,
    height_in: 8.2667,
    width_mm: 297,
    height_mm: 210,
    is_default: false,
    notes:
      "A4 при 300 ppi — 3508×2480 px (spec §7); физический лист 297×210 мм. Для широких матриц и панельных комплектов.",
  },
] as const;

export const DEFAULT_PRINT_PROFILE_ID: PrintProfileId = "figure-landscape";

export function resolvePrintProfile(id: string): PrintProfileSpec | undefined {
  return PRINT_PROFILE_CATALOG.find((profile) => profile.id === id);
}

/**
 * Согласованность px⇄мм⇄ppi профиля (PGV-AC16): физический размер при
 * заявленном ppi даёт заявленные пиксели с допуском округления ≤1px.
 */
export function profilePixelConsistency(profile: PrintProfileSpec): boolean {
  const tolerancePx = 1;
  const widthFromMm = (profile.width_mm / 25.4) * profile.ppi;
  const heightFromMm = (profile.height_mm / 25.4) * profile.ppi;
  return (
    Math.abs(profile.width_px - widthFromMm) <= tolerancePx &&
    Math.abs(profile.height_px - heightFromMm) <= tolerancePx
  );
}

// ── Лимиты печати (spec §7) ──────────────────────────────────────

export interface PrintLimits {
  max_megapixels_per_page: number;
  max_pages_per_set: number;
  max_output_bytes: number;
  render_timeout_s: number;
  concurrency_per_tenant: number;
  concurrency_global: number;
}

export const PRINT_LIMITS: PrintLimits = {
  max_megapixels_per_page: 12,
  max_pages_per_set: 20,
  max_output_bytes: 52428800, // 50 MiB
  render_timeout_s: 60,
  concurrency_per_tenant: 1,
  concurrency_global: 2,
} as const;

// ── Units: значение XOR причина (spec §6 «не выдумывать единицы») ─

export interface UnitDeclaration {
  value: string | null;
  reason: string | null;
}

export const UNIT_REASON_DIMENSIONLESS = "dimensionless";
export const UNIT_REASON_LEGACY_UNKNOWN = "legacy_unknown";

/** Юнит объявлен честно: ровно одно из value/reason (XOR). */
export function isUnitDeclared(unit: UnitDeclaration): boolean {
  const hasValue = typeof unit?.value === "string" && unit.value.trim().length > 0;
  const hasReason = typeof unit?.reason === "string" && unit.reason.trim().length > 0;
  return hasValue !== hasReason;
}

// ── Sampling (spec §6: sampling/point cap/truncation; §10.1) ─────

export type SamplingMode = "full" | "downsampled" | "windowed" | "aggregated" | "truncated";

export const SAMPLING_MODES: readonly SamplingMode[] = [
  "full",
  "downsampled",
  "windowed",
  "aggregated",
  "truncated",
];

/** Режимы с явной точкой отсечения: point_cap обязателен (PGV-AC08). */
export const SAMPLING_MODES_REQUIRING_POINT_CAP: readonly SamplingMode[] = [
  "downsampled",
  "windowed",
  "truncated",
];

export interface SamplingDeclaration {
  applicable: boolean;
  mode: SamplingMode | null;
  point_cap: number | null;
  reason: string | null;
}

/**
 * Sampling обязателен по applicability сайта (критерий PGV-01):
 * серии/таблицы/матрицы допускают усечение/прореживание и обязаны
 * декларировать режим; html_cards (счётчики/badges) — нет.
 * Уточнение по view_params (zoom/window) — producer-адаптеры PGV-03.
 */
export function samplingRequiredForSite(site: VisualSiteRecord): boolean {
  return site.renderer_kind !== "html_cards";
}

// ── Trusted-параметры (критерий «параметры trusted», spec §6) ────

export type ParameterOrigin = "producer_freeze" | "producer_first_export";

export const PARAMETER_ORIGINS: readonly ParameterOrigin[] = [
  "producer_freeze",
  "producer_first_export",
];

export interface TrustedParameters {
  origin: ParameterOrigin;
  method: string | null;
  parameters: Record<string, unknown>;
}

/**
 * Клиентский display selection: ключи — ТОЛЬКО allowlist view_params
 * реестра PGV-00. Authoritative series/caption от клиента не принимаются
 * (spec §6: «Клиент передаёт ref и allowlisted display selection»).
 */
export interface ClientDisplaySelection {
  allowlist: string[];
  values: Record<string, unknown>;
}

// ── Секции печатного содержимого ────────────────────────────────

/** Базовые kinds секций; «mixed» сайт = несколько секций разных kinds. */
export type SectionRendererKind = Exclude<VisualRendererKind, "mixed">;

export interface AxisSpec {
  name: string;
  units: UnitDeclaration;
  scale: string | null;
  limits: [number, number] | null;
}

export interface PrintSectionSpec {
  section_id: string;
  renderer_kind: SectionRendererKind;
  title: string | null;
  axes: AxisSpec[];
  legend_ordering: string[];
  table_headings: { row: string[]; column: string[] } | null;
  heatmap_scale: { domain: [number, number] | null; units: UnitDeclaration } | null;
  units: UnitDeclaration[];
}

export const SECTION_RENDERER_KINDS: readonly SectionRendererKind[] = [
  "recharts_svg",
  "html_table",
  "html_heatmap",
  "html_cards",
];

// ── Scope и обязательные refs (spec §6/§8) ───────────────────────

export type SnapshotScope = "demo" | "research" | "passport" | "comparison";

/**
 * Обязательные refs по scope. Version (data_revision) обязателен для
 * research/passport (критерий PGV-01 «version … обязателен по
 * applicability»); demo версионируется демо-датасетом; comparison —
 * frozen vintage refs реестра.
 */
export const MANDATORY_REFS_BY_SCOPE: Record<SnapshotScope, readonly string[]> = {
  demo: ["demo_dataset_id"],
  research: ["context_id", "data_revision"],
  passport: ["context_id", "snapshot_id", "data_revision", "schema_version"],
  comparison: ["research_run_id", "comparison_id"],
} as const;

/**
 * Scope сайта выводится из его refs/остановки реестра PGV-00:
 * demo — статические preview Навигатора; passport — паспортные остановки;
 * comparison — D12-сверка на frozen vintages; остальное — research.
 */
export function resolveSnapshotScope(site: VisualSiteRecord): SnapshotScope {
  const refs = new Set(site.required_refs);
  if (refs.has("demo_dataset_id")) return "demo";
  if (refs.has("comparison_id")) return "comparison";
  if (refs.has("snapshot_id") || site.stop_id === "passport") return "passport";
  return "research";
}

/** Обязательные refs снапшота: мандат scope + все заявленные сайтом. */
export function resolveSnapshotRefRequirements(site: VisualSiteRecord): {
  scope: SnapshotScope;
  mandatory_refs: string[];
} {
  const scope = resolveSnapshotScope(site);
  const mandatory = new Set<string>([...MANDATORY_REFS_BY_SCOPE[scope], ...site.required_refs]);
  return { scope, mandatory_refs: [...mandatory].sort() };
}

// ── VisualPrintSnapshot/1 (spec §6) ──────────────────────────────

export interface VisualPrintSnapshotV1 {
  schema_version: typeof VISUAL_PRINT_SNAPSHOT_SCHEMA_VERSION;
  view_id: string;
  scope: SnapshotScope;
  /** Все заявленные сайтом refs + мандат scope (context/data_revision/…). */
  refs: Record<string, string>;
  /** Frozen VisualResult: ref/version/hash — «Result» критерия PGV-01. */
  result: {
    result_ref: string;
    result_schema_version: string;
    result_digest: string | null;
    result_digest_reason: string | null;
  };
  /** Данные: artifact id/version/hash с честной причиной отсутствия. */
  data_artifact: {
    artifact_id: string | null;
    artifact_version: string | null;
    source_hash: string | null;
    hash_algorithm: string | null;
    hash_reason: string | null;
  };
  /** Ожидаемый контекст фиксации — база 409 context_changed (PGV-AC07). */
  expected_context: {
    context_id: string | null;
    data_revision: string | null;
    expected_data_digest: string | null;
  };
  /** Target/date/entity по applicability; mode без смешивания (AC14). */
  dimensions: {
    target_column: string | null;
    date_column: string | null;
    entity_column: string | null;
    entity_id: string | null;
    mode: "univariate" | "panel";
  };
  /** Времена: computed/captured/checkpoint confirmed + render_requested отдельно; tz/locale. */
  times: {
    computed_at: string | null;
    computed_at_reason: string | null;
    captured_at: string | null;
    captured_at_reason: string | null;
    checkpoint_confirmed_at: string | null;
    render_requested_at: string | null;
    timezone: string;
    locale: string;
  };
  /** Reused checkpoint — подтверждение и ссылка на исходный снимок (AC11). */
  checkpoint: { reused: boolean; source_snapshot_ref: string | null } | null;
  display: {
    title: string;
    subtitle: string | null;
    detail_level: "compact" | "expanded" | "sampling";
    sections: PrintSectionSpec[];
  };
  /** Trusted-параметры producer; клиенту — только selection allowlist. */
  method: TrustedParameters;
  selection: ClientDisplaySelection;
  sampling: SamplingDeclaration;
  /** Analyst annotation — отдельный versioned текст (spec §6). */
  annotations: { revision: number; author: "analyst"; text: string | null };
  print: { profile_id: PrintProfileId; page_count: number; theme: "light-print" };
  /** Renderer env: versions + честный статус зависимостей (AC17). */
  renderer_env: {
    renderer_version: string | null;
    font_profile: string | null;
    dependency_status: "available" | "unavailable" | "unknown";
    unavailable_reason: string | null;
  };
  /** Before/after input/output revisions (spec §6). */
  data_flow: { before_revision: string | null; after_revision: string | null };
  /** Metadata без raw данных; политика чувствительных полей (AC19/AC21). */
  sensitive: { raw_data_included: boolean; sensitive_fields_policy: string };
  warnings: string[];
}

// ── VisualResult/1 (spec §6: immutable artifact) ─────────────────

export interface VisualResultV1 {
  schema_version: typeof VISUAL_RESULT_SCHEMA_VERSION;
  view_id: string;
  payload: {
    kind: SectionRendererKind;
    series_cap: number | null;
    digest: string | null;
    digest_reason: string | null;
  };
  parameters: TrustedParameters;
  units: UnitDeclaration[];
  sampling: SamplingDeclaration;
  warnings: string[];
  execution: {
    execution_ref: string | null;
    result_ref: string;
    computed_at: string | null;
    computed_at_reason: string | null;
  };
}

// ── PrintSetManifest/1 (spec §7: ZIP = PNG + manifest + metadata) ─

export interface PrintSetManifestV1 {
  schema_version: typeof PRINT_MANIFEST_SCHEMA_VERSION;
  set_id: string;
  render_version: string;
  profile_id: PrintProfileId;
  pages: Array<{
    filename: string;
    page_role: string;
    index: number;
    width_px: number;
    height_px: number;
    png_sha256: string;
  }>;
  metadata_filename: string;
  dependencies: string[];
  data_included: boolean;
}

// ── Нарушения схемы ──────────────────────────────────────────────

export interface PrintSchemaViolation {
  code: string;
  path: string;
  message: string;
}

/** Стабильный контракт кодов для PGV-02/09 (422 invalid_selection/profile и пр.). */
const VIOLATION_CODES: readonly string[] = [
  "ambiguous_unit",
  "ambiguous_source_hash",
  "ambiguous_date",
  "data_included_forbidden",
  "duplicate_filename",
  "empty_sections",
  "invalid_profile",
  "invalid_section_kind",
  "missing_axes",
  "missing_checkpoint_confirmation",
  "missing_data_version",
  "missing_date",
  "missing_digest",
  "missing_expected_context",
  "missing_field",
  "missing_heatmap_scale",
  "missing_page_hash",
  "missing_point_cap",
  "missing_renderer_reason",
  "missing_required_ref",
  "missing_result_ref",
  "missing_sampling",
  "missing_sampling_reason",
  "missing_sampling_mode",
  "missing_source_hash",
  "missing_table_headings",
  "missing_title",
  "missing_units",
  "mixed_needs_multiple_sections",
  "page_order_gap",
  "panel_mixing",
  "raw_data_included_forbidden",
  "schema_version_mismatch",
  "section_kind_mismatch",
  "selection_not_allowlisted",
  "theme_not_light_print",
  "untrusted_parameter_origin",
] as const;

export function printSchemaViolationCodes(): string[] {
  return [...VIOLATION_CODES];
}

function violation(code: string, path: string, message: string): PrintSchemaViolation {
  return { code, path, message };
}

// ── Робастные акцессоры (валидаторы не бросают на malformed) ─────

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function strArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function isHex64(value: unknown): boolean {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

// ── Units-валидация ──────────────────────────────────────────────

function validateUnitValue(unit: unknown, path: string, out: PrintSchemaViolation[]): void {
  if (!isRecord(unit)) {
    out.push(violation("missing_units", path, "unit declaration must be an object"));
    return;
  }
  const hasValue = str(unit.value) !== null;
  const hasReason = str(unit.reason) !== null;
  if (hasValue && hasReason) {
    out.push(violation("ambiguous_unit", path, "unit value и reason взаимоисключающи (spec §6: не выдумывать единицы)"));
  } else if (!hasValue && !hasReason) {
    out.push(violation("missing_units", path, "unit требует value XOR явную null-причину"));
  }
}

function validateUnitsList(units: unknown, path: string, out: PrintSchemaViolation[]): void {
  if (!Array.isArray(units) || units.length === 0) {
    out.push(violation("missing_units", path, "секция обязана декларировать units (пусть и с null-причиной)"));
    return;
  }
  units.forEach((unit, i) => validateUnitValue(unit, `${path}[${i}]`, out));
}

// ── Trusted origin / selection ───────────────────────────────────

function validateTrustedParameters(
  method: unknown,
  selection: unknown,
  site: VisualSiteRecord | undefined,
  out: PrintSchemaViolation[],
): void {
  const methodRec = asRecord(method);
  const origin = str(methodRec.origin);
  if (origin === null || !PARAMETER_ORIGINS.includes(origin as ParameterOrigin)) {
    out.push(
      violation(
        "untrusted_parameter_origin",
        "method.origin",
        `origin должен быть одним из ${PARAMETER_ORIGINS.join("/")} — параметры trusted, клиентские не принимаются`,
      ),
    );
  }

  const selectionRec = asRecord(selection);
  const allowlist = strArray(selectionRec.allowlist);
  if (site) {
    const viewParams = new Set(site.view_params);
    for (const key of allowlist) {
      if (!viewParams.has(key)) {
        out.push(
          violation(
            "selection_not_allowlisted",
            `selection.allowlist.${key}`,
            "client selection keys обязаны входить в view_params реестра (spec §6: allowlisted display selection)",
          ),
        );
      }
    }
  }
  const values = asRecord(selectionRec.values);
  for (const key of Object.keys(values)) {
    if (!allowlist.includes(key)) {
      out.push(
        violation("selection_not_allowlisted", `selection.values.${key}`, "значение selection вне allowlist"),
      );
    }
  }
}

// ── Sampling-валидация ───────────────────────────────────────────

function validateSampling(
  sampling: unknown,
  required: boolean,
  out: PrintSchemaViolation[],
): void {
  const rec = asRecord(sampling);
  const applicable = rec.applicable === true;
  if (required && !applicable) {
    out.push(
      violation("missing_sampling", "sampling", "sampling обязателен по applicability (серии/таблицы/матрицы)"),
    );
    return;
  }
  if (!applicable) {
    if (str(rec.reason) === null) {
      out.push(
        violation(
          "missing_sampling_reason",
          "sampling.reason",
          "not applicable требует явной причины (html_cards и пр.)",
        ),
      );
    }
    return;
  }
  const mode = str(rec.mode);
  if (mode === null || !SAMPLING_MODES.includes(mode as SamplingMode)) {
    out.push(violation("missing_sampling_mode", "sampling.mode", "режим sampling обязателен"));
    return;
  }
  if ((SAMPLING_MODES_REQUIRING_POINT_CAP as readonly string[]).includes(mode)) {
    const cap = num(rec.point_cap);
    if (cap === null || cap <= 0) {
      out.push(
        violation(
          "missing_point_cap",
          "sampling.point_cap",
          `${mode} требует явный point_cap — скрытого detail upgrade нет (PGV-AC08)`,
        ),
      );
    }
  }
}

// ── Секции: содержательные требования по renderer_kind (spec §6) ─

function validateSection(
  section: unknown,
  path: string,
  out: PrintSchemaViolation[],
): void {
  const rec = asRecord(section);
  const kind = str(rec.renderer_kind);
  if (kind === null || !SECTION_RENDERER_KINDS.includes(kind as SectionRendererKind)) {
    out.push(violation("invalid_section_kind", `${path}.renderer_kind`, "недопустимый renderer_kind секции"));
    return;
  }
  // Units обязательны всегда (spec §6: row/column headings, единицы и легенда).
  validateUnitsList(rec.units, `${path}.units`, out);

  if (kind === "recharts_svg") {
    const axes = Array.isArray(rec.axes) ? rec.axes : [];
    if (axes.length === 0) {
      out.push(violation("missing_axes", `${path}.axes`, "график обязан декларировать оси"));
    }
    axes.forEach((axis, i) => {
      const axisRec = asRecord(axis);
      if (str(axisRec.name) === null) {
        out.push(violation("missing_axes", `${path}.axes[${i}].name`, "имя оси обязательно"));
      }
      validateUnitValue(axisRec.units, `${path}.axes[${i}].units`, out);
    });
  }
  if (kind === "html_table") {
    const headings = asRecord(rec.table_headings);
    const row = strArray(headings.row);
    const column = strArray(headings.column);
    if (!isRecord(rec.table_headings) || row.length === 0 || column.length === 0) {
      out.push(
        violation(
          "missing_table_headings",
          `${path}.table_headings`,
          "таблица обязана нести заголовки строк/колонок (axes_applicability=not_applicable, spec §6)",
        ),
      );
    }
  }
  if (kind === "html_heatmap") {
    const scale = asRecord(rec.heatmap_scale);
    const domain = Array.isArray(scale.domain) ? scale.domain : null;
    const domainOk =
      domain !== null &&
      domain.length === 2 &&
      domain.every((v) => typeof v === "number" && Number.isFinite(v));
    if (!isRecord(rec.heatmap_scale) || !domainOk || !isRecord(scale.units)) {
      out.push(
        violation(
          "missing_heatmap_scale",
          `${path}.heatmap_scale`,
          "тепловая карта обязана декларировать цветовую шкалу с domain и units (spec §6)",
        ),
      );
    } else {
      validateUnitValue(scale.units, `${path}.heatmap_scale.units`, out);
    }
  }
}

function validateSectionComposition(
  sections: unknown,
  site: VisualSiteRecord | undefined,
  out: PrintSchemaViolation[],
): void {
  if (!Array.isArray(sections) || sections.length === 0) {
    out.push(violation("empty_sections", "display.sections", "снапшот обязан нести хотя бы одну секцию"));
    return;
  }
  sections.forEach((section, i) => validateSection(section, `display.sections[${i}]`, out));
  if (!site) return;
  if (site.renderer_kind === "mixed") {
    if (sections.length < 2) {
      out.push(
        violation(
          "mixed_needs_multiple_sections",
          "display.sections",
          "mixed render-site обязан нести несколько секций разных kinds",
        ),
      );
    }
  } else if (sections.length !== 1 || asRecord(sections[0]).renderer_kind !== site.renderer_kind) {
    out.push(
      violation(
        "section_kind_mismatch",
        "display.sections",
        `сайт ${site.view_id} рендерит ${site.renderer_kind} — состав секций обязан соответствовать`,
      ),
    );
  }
}

// ── Дата/время: значение XOR причина (spec §6/§8, PGV-AC12) ──────

function validateTimeXor(
  value: unknown,
  reason: unknown,
  path: string,
  code: string,
  out: PrintSchemaViolation[],
): void {
  const hasValue = str(value) !== null;
  const hasReason = str(reason) !== null;
  if (hasValue && hasReason) {
    out.push(violation("ambiguous_date", path, "время и причина отсутствия взаимоисключающи"));
  } else if (!hasValue && !hasReason) {
    out.push(violation(code, path, "время обязательно либо явная null-причина (не выдумывать timestamps)"));
  }
}

// ── validateVisualPrintSnapshot ──────────────────────────────────

export function validateVisualPrintSnapshot(
  value: unknown,
  site?: VisualSiteRecord,
): PrintSchemaViolation[] {
  const out: PrintSchemaViolation[] = [];
  if (!isRecord(value)) {
    return [violation("missing_field", "(root)", "print snapshot must be an object")];
  }

  if (value.schema_version !== VISUAL_PRINT_SNAPSHOT_SCHEMA_VERSION) {
    out.push(
      violation(
        "schema_version_mismatch",
        "schema_version",
        `ожидается ${VISUAL_PRINT_SNAPSHOT_SCHEMA_VERSION}`,
      ),
    );
  }

  const viewId = str(value.view_id);
  if (viewId === null) {
    out.push(violation("missing_field", "view_id", "view_id обязателен"));
  } else if (site && viewId !== site.view_id) {
    out.push(violation("missing_field", "view_id", `view_id не совпадает с реестром (${site.view_id})`));
  }

  // Scope: из реестра (если сайт передан) либо из самого снапшота.
  const scope = (site ? resolveSnapshotScope(site) : str(value.scope)) as SnapshotScope | null;
  if (scope === null || !(scope in MANDATORY_REFS_BY_SCOPE)) {
    out.push(violation("missing_field", "scope", "scope обязателен: demo/research/passport/comparison"));
  } else if (value.scope !== scope) {
    out.push(violation("missing_field", "scope", `scope обязан быть ${scope} (по applicability реестра)`));
  }

  // Refs: мандат scope + все заявленные сайтом required_refs.
  const refs = asRecord(value.refs);
  if (scope !== null) {
    const mandatory = new Set<string>([
      ...MANDATORY_REFS_BY_SCOPE[scope],
      ...(site ? site.required_refs : []),
    ]);
    for (const refKey of [...mandatory].sort()) {
      if (str(refs[refKey]) === null) {
        out.push(
          violation(
            "missing_required_ref",
            `refs.${refKey}`,
            `ref обязателен по applicability (scope=${scope})`,
          ),
        );
      }
    }
  }

  // Result (критерий PGV-01 «Result … обязателен»).
  const result = asRecord(value.result);
  if (str(result.result_ref) === null || str(result.result_schema_version) === null) {
    out.push(
      violation("missing_result_ref", "result", "result_ref/result_schema_version обязательны (frozen VisualResult)"),
    );
  }
  const resultDigest = str(result.result_digest);
  const resultDigestReason = str(result.result_digest_reason);
  if (resultDigest === null && resultDigestReason === null) {
    out.push(violation("missing_source_hash", "result.result_digest", "digest XOR явная причина отсутствия"));
  } else if (resultDigest !== null && resultDigestReason !== null) {
    out.push(violation("ambiguous_source_hash", "result.result_digest", "digest и reason взаимоисключающи"));
  }

  // Data artifact: version + hash XOR reason (для БД — hash извлечённого
  // результата, spec §6; legacy_unknown честен, PGV-AC12).
  const dataArtifact = asRecord(value.data_artifact);
  if (str(dataArtifact.artifact_version) === null) {
    out.push(violation("missing_data_version", "data_artifact.artifact_version", "версия данных обязательна"));
  }
  const sourceHash = str(dataArtifact.source_hash);
  const hashReason = str(dataArtifact.hash_reason);
  if (sourceHash === null && hashReason === null) {
    out.push(violation("missing_source_hash", "data_artifact.source_hash", "source_hash XOR явная причина"));
  } else if (sourceHash !== null && hashReason !== null) {
    out.push(violation("ambiguous_source_hash", "data_artifact.source_hash", "hash и reason взаимоисключающи"));
  }

  // Expected context — база 409 context_changed (PGV-AC07): обязателен
  // для research-снапшотов (freeze сверяется с текущими данными).
  if (scope === "research") {
    const expected = asRecord(value.expected_context);
    if (str(expected.context_id) === null || str(expected.data_revision) === null) {
      out.push(
        violation(
          "missing_expected_context",
          "expected_context",
          "research-снапшот обязан нести context_id+data_revision для проверки freeze (PGV-AC07)",
        ),
      );
    }
  }

  // Времена: computed/captured — значение XOR причина; render_requested
  // отдельно; timezone/locale обязательны (spec §6).
  const times = asRecord(value.times);
  validateTimeXor(times.computed_at, times.computed_at_reason, "times.computed_at", "missing_date", out);
  validateTimeXor(times.captured_at, times.captured_at_reason, "times.captured_at", "missing_date", out);
  if (str(times.render_requested_at) === null) {
    out.push(
      violation("missing_field", "times.render_requested_at", "render_requested_at фиксируется отдельно"),
    );
  }
  if (str(times.timezone) === null || str(times.locale) === null) {
    out.push(violation("missing_field", "times.timezone/locale", "timezone и locale обязательны"));
  }

  // Reused checkpoint: подтверждение + ссылка на исходный снимок (AC11).
  const checkpoint = asRecord(value.checkpoint);
  if (checkpoint.reused === true) {
    const confirmedAt = str(asRecord(value.times).checkpoint_confirmed_at);
    const sourceRef = str(checkpoint.source_snapshot_ref);
    if (confirmedAt === null || sourceRef === null) {
      out.push(
        violation(
          "missing_checkpoint_confirmation",
          "checkpoint",
          "reused checkpoint обязан нести confirmed_at и source_snapshot_ref (PGV-AC11: без ложной четвёртой копии)",
        ),
      );
    }
  }

  // Display: title + секции по renderer_kind сайта.
  const display = asRecord(value.display);
  if (str(display.title) === null) {
    out.push(violation("missing_title", "display.title", "заголовок печатного представления обязателен"));
  }
  const detailLevel = str(display.detail_level);
  if (detailLevel === null || !["compact", "expanded", "sampling"].includes(detailLevel)) {
    out.push(violation("missing_field", "display.detail_level", "detail_level обязателен"));
  }
  validateSectionComposition(display.sections, site, out);

  // Trusted-параметры + allowlist selection (критерий «параметры trusted»).
  validateTrustedParameters(value.method, value.selection, site, out);

  // Sampling по applicability.
  validateSampling(value.sampling, site ? samplingRequiredForSite(site) : true, out);

  // Панельная семантика (PGV-AC14): без смешивания.
  const dimensions = asRecord(value.dimensions);
  const mode = str(dimensions.mode);
  if (site) {
    if (site.applicability === "panel") {
      if (mode !== "panel") {
        out.push(violation("panel_mixing", "dimensions.mode", "панельный сайт обязан печататься в mode=panel"));
      }
      if (str(dimensions.entity_column) === null && str(refs.entity_column) === null) {
        out.push(
          violation("missing_required_ref", "dimensions.entity_column", "панельный вид обязан нести entity_column"),
        );
      }
    }
    if (site.applicability === "univariate" && str(dimensions.entity_id) !== null) {
      out.push(
        violation(
          "panel_mixing",
          "dimensions.entity_id",
          "entity на univariate виде — смешивание panel/univariate запрещено (PGV-AC14)",
        ),
      );
    }
  } else if (mode === "panel" && str(dimensions.entity_column) === null) {
    out.push(violation("panel_mixing", "dimensions", "mode=panel требует entity_column"));
  }

  // Print profile: резолвится в каталоге; light-print обязателен (spec §3.4).
  const print = asRecord(value.print);
  const profileId = str(print.profile_id);
  if (profileId === null || resolvePrintProfile(profileId) === undefined) {
    out.push(violation("invalid_profile", "print.profile_id", "профиль обязан быть из каталога (422 invalid_profile — PGV-09)"));
  }
  const pageCount = num(print.page_count);
  if (pageCount === null || pageCount < 1 || !Number.isInteger(pageCount)) {
    out.push(violation("missing_field", "print.page_count", "page_count — положительное целое"));
  }
  if (print.theme !== "light-print") {
    out.push(violation("theme_not_light_print", "print.theme", "всегда light-print (spec §3.4)"));
  }

  // Renderer env: unavailable без причины нечестен (PGV-AC17).
  const rendererEnv = asRecord(value.renderer_env);
  const dependencyStatus = str(rendererEnv.dependency_status);
  if (dependencyStatus === null || !["available", "unavailable", "unknown"].includes(dependencyStatus)) {
    out.push(violation("missing_field", "renderer_env.dependency_status", "dependency_status обязателен"));
  }
  if (dependencyStatus === "unavailable" && str(rendererEnv.unavailable_reason) === null) {
    out.push(
      violation(
        "missing_renderer_reason",
        "renderer_env.unavailable_reason",
        "unavailable требует явной причины (PGV-AC17: render_dependency_unavailable, не ложный ready)",
      ),
    );
  }

  // Sensitive: raw данные в metadata запрещены (spec §3.5, PGV-AC19/21).
  const sensitive = asRecord(value.sensitive);
  if (sensitive.raw_data_included !== false) {
    out.push(
      violation(
        "raw_data_included_forbidden",
        "sensitive.raw_data_included",
        "metadata не вкладывает raw данные (spec §11: raw данные не вкладываются автоматически)",
      ),
    );
  }
  if (str(sensitive.sensitive_fields_policy) === null) {
    out.push(violation("missing_field", "sensitive.sensitive_fields_policy", "политика чувствительных полей обязательна"));
  }

  // Annotations: versioned текст аналитика (spec §6).
  const annotations = asRecord(value.annotations);
  const revision = num(annotations.revision);
  if (revision === null || revision < 0 || !Number.isInteger(revision)) {
    out.push(violation("missing_field", "annotations.revision", "revision аннотаций — неотрицательное целое"));
  }

  return out;
}

// ── validateVisualResult ─────────────────────────────────────────

export function validateVisualResult(value: unknown): PrintSchemaViolation[] {
  const out: PrintSchemaViolation[] = [];
  if (!isRecord(value)) {
    return [violation("missing_field", "(root)", "visual result must be an object")];
  }

  if (value.schema_version !== VISUAL_RESULT_SCHEMA_VERSION) {
    out.push(
      violation("schema_version_mismatch", "schema_version", `ожидается ${VISUAL_RESULT_SCHEMA_VERSION}`),
    );
  }
  if (str(value.view_id) === null) {
    out.push(violation("missing_field", "view_id", "view_id обязателен"));
  }

  const payload = asRecord(value.payload);
  const kind = str(payload.kind);
  if (kind === null || !SECTION_RENDERER_KINDS.includes(kind as SectionRendererKind)) {
    out.push(violation("invalid_section_kind", "payload.kind", "payload.kind — базовый renderer_kind"));
  }
  const digest = str(payload.digest);
  const digestReason = str(payload.digest_reason);
  if (digest === null && digestReason === null) {
    out.push(violation("missing_digest", "payload.digest", "digest XOR явная причина (legacy_unknown честен)"));
  } else if (digest !== null && digestReason !== null) {
    out.push(violation("ambiguous_source_hash", "payload.digest", "digest и reason взаимоисключающи"));
  }

  validateTrustedParameters(value.parameters, { allowlist: [], values: {} }, undefined, out);
  validateUnitsList(asRecord(value).units, "units", out);
  validateSampling(value.sampling, true, out);

  const execution = asRecord(value.execution);
  if (str(execution.result_ref) === null) {
    out.push(violation("missing_result_ref", "execution.result_ref", "result_ref обязателен"));
  }
  validateTimeXor(execution.computed_at, execution.computed_at_reason, "execution.computed_at", "missing_date", out);

  return out;
}

// ── validatePrintSetManifest ─────────────────────────────────────

export function validatePrintSetManifest(value: unknown): PrintSchemaViolation[] {
  const out: PrintSchemaViolation[] = [];
  if (!isRecord(value)) {
    return [violation("missing_field", "(root)", "manifest must be an object")];
  }

  if (value.schema_version !== PRINT_MANIFEST_SCHEMA_VERSION) {
    out.push(
      violation("schema_version_mismatch", "schema_version", `ожидается ${PRINT_MANIFEST_SCHEMA_VERSION}`),
    );
  }
  if (str(value.set_id) === null) {
    out.push(violation("missing_field", "set_id", "set_id обязателен"));
  }
  if (str(value.render_version) === null) {
    out.push(violation("missing_field", "render_version", "render_version обязательна (spec §7)"));
  }
  const profileId = str(value.profile_id);
  if (profileId === null || resolvePrintProfile(profileId) === undefined) {
    out.push(violation("invalid_profile", "profile_id", "профиль обязан быть из каталога"));
  }
  if (str(value.metadata_filename) === null) {
    out.push(violation("missing_field", "metadata_filename", "metadata_filename обязателен (hash вне PNG bytes)"));
  }

  const pages = Array.isArray(value.pages) ? value.pages : [];
  const seenFilenames = new Set<string>();
  pages.forEach((page, i) => {
    const rec = asRecord(page);
    const path = `pages[${i}]`;
    const filename = str(rec.filename);
    if (filename === null) {
      out.push(violation("missing_field", `${path}.filename`, "имя файла страницы обязательно"));
    } else if (seenFilenames.has(filename)) {
      out.push(violation("duplicate_filename", `${path}.filename`, `дубликат имени страницы: ${filename}`));
    } else {
      seenFilenames.add(filename);
    }
    const index = num(rec.index);
    if (index === null || index < 1 || !Number.isInteger(index)) {
      out.push(violation("page_order_gap", `${path}.index`, "index страницы — целое ≥ 1"));
    }
    const width = num(rec.width_px);
    const height = num(rec.height_px);
    if (width === null || width <= 0 || height === null || height <= 0) {
      out.push(violation("missing_field", `${path}.width_px/height_px`, "пиксели страницы обязательны"));
    }
    if (!isHex64(rec.png_sha256)) {
      out.push(
        violation(
          "missing_page_hash",
          `${path}.png_sha256`,
          "hash PNG хранится в manifest отдельным полем, не внутрь PNG bytes (spec §7)",
        ),
      );
    }
  });
  // Непрерывность порядка 1..n (spec §7: порядок страниц).
  const indexes = pages
    .map((page) => num(asRecord(page).index))
    .filter((index): index is number => index !== null)
    .sort((a, b) => a - b);
  indexes.forEach((index, i) => {
    if (index !== i + 1) {
      out.push(violation("page_order_gap", "pages.index", "порядок страниц должен быть непрерывным 1..n"));
    }
  });

  if (value.data_included !== false) {
    out.push(
      violation(
        "data_included_forbidden",
        "data_included",
        "ZIP — контейнер PNG и метаданных; raw DataFrame не вкладывается (spec §7, PGV-AC21)",
      ),
    );
  }

  return out;
}

// ── Builder: минимальный валидный снапшот по сайту реестра ───────
//
// Используется оракулом реестр⇄схема (все 89 сайтов), а позже —
// producer-адаптерами PGV-03 как эталон обязательного состава.

export interface SnapshotBuildOverrides {
  detailLevel?: "compact" | "expanded" | "sampling";
  checkpointReused?: boolean;
}

function buildSectionsForKind(rendererKind: VisualRendererKind): PrintSectionSpec[] {
  const chartSection: PrintSectionSpec = {
    section_id: "chart",
    renderer_kind: "recharts_svg",
    title: null,
    axes: [
      { name: "X", units: { value: "date", reason: null }, scale: "time", limits: null },
      { name: "Y", units: { value: "value", reason: null }, scale: "linear", limits: null },
    ],
    legend_ordering: ["series-1"],
    table_headings: null,
    heatmap_scale: null,
    units: [{ value: "value", reason: null }],
  };
  const tableSection: PrintSectionSpec = {
    section_id: "table",
    renderer_kind: "html_table",
    title: null,
    axes: [],
    legend_ordering: [],
    table_headings: { row: ["Строка"], column: ["Колонка"] },
    heatmap_scale: null,
    units: [{ value: null, reason: UNIT_REASON_DIMENSIONLESS }],
  };
  if (rendererKind === "mixed") return [chartSection, tableSection];
  if (rendererKind === "recharts_svg") return [chartSection];
  if (rendererKind === "html_table") return [tableSection];
  if (rendererKind === "html_heatmap") {
    return [
      {
        section_id: "heatmap",
        renderer_kind: "html_heatmap",
        title: null,
        axes: [],
        legend_ordering: [],
        table_headings: null,
        heatmap_scale: { domain: [0, 1], units: { value: "share", reason: null } },
        units: [{ value: "share", reason: null }],
      },
    ];
  }
  return [
    {
      section_id: "cards",
      renderer_kind: "html_cards",
      title: null,
      axes: [],
      legend_ordering: [],
      table_headings: null,
      heatmap_scale: null,
      units: [{ value: null, reason: UNIT_REASON_DIMENSIONLESS }],
    },
  ];
}

export function buildMinimalValidSnapshot(
  site: VisualSiteRecord,
  overrides: SnapshotBuildOverrides = {},
): VisualPrintSnapshotV1 {
  const scope = resolveSnapshotScope(site);
  const refs: Record<string, string> = {};
  for (const refKey of resolveSnapshotRefRequirements(site).mandatory_refs) {
    refs[refKey] = `fixture:${refKey}`;
  }
  const demo = scope === "demo";
  const mode: "univariate" | "panel" = site.applicability === "panel" ? "panel" : "univariate";
  const samplingRequired = samplingRequiredForSite(site);
  const checkpointReused = overrides.checkpointReused === true;

  return {
    schema_version: VISUAL_PRINT_SNAPSHOT_SCHEMA_VERSION,
    view_id: site.view_id,
    scope,
    refs,
    result: {
      result_ref: `artifact:visual_result:fixture:${site.view_id}`,
      result_schema_version: VISUAL_RESULT_SCHEMA_VERSION,
      result_digest: "a".repeat(64),
      result_digest_reason: null,
    },
    data_artifact: demo
      ? {
          artifact_id: null,
          artifact_version: "demo-v1",
          source_hash: null,
          hash_algorithm: null,
          hash_reason: "demo_dataset",
        }
      : {
          artifact_id: "artifact:data:fixture",
          artifact_version: "v1",
          source_hash: "b".repeat(64),
          hash_algorithm: "sha256",
          hash_reason: null,
        },
    expected_context: demo
      ? { context_id: null, data_revision: null, expected_data_digest: null }
      : {
          context_id: refs.context_id ?? null,
          data_revision: refs.data_revision ?? null,
          expected_data_digest: null,
        },
    dimensions: {
      target_column: refs.target_column ?? null,
      date_column: refs.date_column ?? null,
      entity_column: refs.entity_column ?? null,
      entity_id: mode === "panel" ? "fixture:entity" : null,
      mode,
    },
    times: {
      computed_at: "2026-10-27T00:00:00Z",
      computed_at_reason: null,
      captured_at: "2026-10-27T00:00:00Z",
      captured_at_reason: null,
      checkpoint_confirmed_at: checkpointReused ? "2026-10-27T12:00:00Z" : null,
      render_requested_at: "2026-10-27T00:00:01Z",
      timezone: "UTC",
      locale: "ru-RU",
    },
    checkpoint: checkpointReused ? { reused: true, source_snapshot_ref: "snapshot:fixture" } : null,
    display: {
      title: site.view_id,
      subtitle: null,
      detail_level: overrides.detailLevel ?? "compact",
      sections: buildSectionsForKind(site.renderer_kind),
    },
    method: { origin: "producer_freeze", method: "fixture", parameters: {} },
    selection: { allowlist: [...site.view_params], values: {} },
    sampling: samplingRequired
      ? { applicable: true, mode: "full", point_cap: null, reason: null }
      : { applicable: false, mode: null, point_cap: null, reason: "cards_view_no_series" },
    annotations: { revision: 0, author: "analyst", text: null },
    print: { profile_id: DEFAULT_PRINT_PROFILE_ID, page_count: 1, theme: "light-print" },
    renderer_env: {
      renderer_version: "print-renderer-fixture/1",
      font_profile: "dejavu-sans/1",
      dependency_status: "available",
      unavailable_reason: null,
    },
    data_flow: { before_revision: null, after_revision: null },
    sensitive: { raw_data_included: false, sensitive_fields_policy: "redacted" },
    warnings: [],
  };
}

// ── JSON-твин (config/print_schema.json) ─────────────────────────

export interface PrintSchemaDocument {
  schema_version: string;
  generated_from: string;
  pgv_task: string;
  schema_versions: {
    document: string;
    visual_result: string;
    visual_print_snapshot: string;
    print_manifest: string;
    profiles: string;
  };
  profiles: PrintProfileSpec[];
  default_profile_id: PrintProfileId;
  limits: PrintLimits;
  rules: {
    scope_derivation: Record<string, string>;
    mandatory_refs_by_scope: Record<SnapshotScope, readonly string[]>;
    sampling: {
      applicable_renderer_kinds: string[];
      exempt_renderer_kinds: string[];
      modes: readonly string[];
      modes_requiring_point_cap: readonly string[];
    };
    units: { rule: string; dimensionless_reason: string; legacy_unknown_reason: string };
    trusted_parameters: {
      origins: readonly string[];
      selection_allowlist_source: string;
    };
    section_composition: { mixed_minimum_sections: number };
    sensitive: { raw_data_included: boolean };
  };
  section_requirements: Record<
    SectionRendererKind,
    { axes: string; table_headings: string; heatmap_scale: string; units: string }
  >;
  violation_codes: string[];
}

export function serializePrintSchema(): PrintSchemaDocument {
  return {
    schema_version: PRINT_SCHEMA_DOCUMENT_VERSION,
    generated_from: "packages/ui/print/printSchema.ts",
    pgv_task: "PGV-01",
    schema_versions: {
      document: PRINT_SCHEMA_DOCUMENT_VERSION,
      visual_result: VISUAL_RESULT_SCHEMA_VERSION,
      visual_print_snapshot: VISUAL_PRINT_SNAPSHOT_SCHEMA_VERSION,
      print_manifest: PRINT_MANIFEST_SCHEMA_VERSION,
      profiles: PRINT_PROFILES_SCHEMA_VERSION,
    },
    profiles: PRINT_PROFILE_CATALOG.map((profile) => ({ ...profile })),
    default_profile_id: DEFAULT_PRINT_PROFILE_ID,
    limits: { ...PRINT_LIMITS },
    rules: {
      scope_derivation: {
        demo: "refs.demo_dataset_id",
        comparison: "refs.comparison_id",
        passport: "refs.snapshot_id либо stop_id == passport",
        research: "остальные runtime-сайты реестра",
      },
      mandatory_refs_by_scope: MANDATORY_REFS_BY_SCOPE,
      sampling: {
        applicable_renderer_kinds: ["recharts_svg", "html_table", "html_heatmap", "mixed"],
        exempt_renderer_kinds: ["html_cards"],
        modes: SAMPLING_MODES,
        modes_requiring_point_cap: SAMPLING_MODES_REQUIRING_POINT_CAP,
      },
      units: {
        rule: "value XOR reason (spec §6: не выдумывать единицы)",
        dimensionless_reason: UNIT_REASON_DIMENSIONLESS,
        legacy_unknown_reason: UNIT_REASON_LEGACY_UNKNOWN,
      },
      trusted_parameters: {
        origins: PARAMETER_ORIGINS,
        selection_allowlist_source: "packages/ui/lib/visualExportRegistry.ts#view_params",
      },
      section_composition: { mixed_minimum_sections: 2 },
      sensitive: { raw_data_included: false },
    },
    section_requirements: {
      recharts_svg: {
        axes: "обязательны: имя + units каждой оси",
        table_headings: "not_applicable",
        heatmap_scale: "not_applicable",
        units: "обязательны (value XOR reason)",
      },
      html_table: {
        axes: "not_applicable (axes_applicability=not_applicable)",
        table_headings: "обязательны: заголовки строк и колонок",
        heatmap_scale: "not_applicable",
        units: "обязательны (value XOR reason)",
      },
      html_heatmap: {
        axes: "not_applicable",
        table_headings: "not_applicable",
        heatmap_scale: "обязательна: domain + units шкалы",
        units: "обязательны (value XOR reason)",
      },
      html_cards: {
        axes: "not_applicable",
        table_headings: "not_applicable",
        heatmap_scale: "not_applicable",
        units: "обязательны (value XOR reason, dimensionless честен)",
      },
    },
    violation_codes: [...VIOLATION_CODES],
  };
}
