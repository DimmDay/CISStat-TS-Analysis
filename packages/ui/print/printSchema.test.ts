// packages/ui/print/printSchema.test.ts
//
// PGV-01 — print schema/metadata/profile (spec_passport_graphics_visual.md
// §6/§7/§13; строка PGV-01: точки изменения «shared schemas, registry»,
// критерий готовности «Result/version/date/units/sampling обязательны по
// applicability, параметры trusted»).
//
// Оракулы:
//   1) Каталог print-профилей и лимиты §7: figure-landscape / A4 300 ppi
//      (2480×3508 / 3508×2480), согласованность px⇄мм (PGV-AC16).
//   2) Обязательность metadata снапшота по applicability реестра PGV-00:
//      result/version/date/units/sampling; честные null-причины вместо
//      выдуманных единиц и дат (PGV-AC05/AC08/AC12).
//   3) Trusted-параметры: origin только producer_freeze/producer_first_export,
//      client selection — allowlist по view_params реестра.
//   4) Панельная семантика: entity по applicability, без смешивания
//      (PGV-AC14); reused checkpoint — confirmed_at/ref (PGV-AC11).
//   5) Манифест комплекта: порядок/имена/роли/hash отдельными полями,
//      без raw данных (PGV-AC21) — hash не внутрь PNG bytes.
//   6) Согласованность реестр⇄схема: каждый из 93 render-sites PGV-00
//      удовлетворяет обязательному набору refs своей scope (cross-check
//      «уточнение required_refs — PGV-01», docs/pgv00_render_site_inventory.md §7).
//   7) Паритет TS⇄JSON: config/print_schema.json — структурно честный твин
//      (паттерн EDU-API-1/PGV-00) — для Python-зеркала и PGV-02/09.

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import {
  DEFAULT_PRINT_PROFILE_ID,
  MANDATORY_REFS_BY_SCOPE,
  PRINT_LIMITS,
  PRINT_MANIFEST_SCHEMA_VERSION,
  PRINT_PROFILE_CATALOG,
  PRINT_PROFILES_SCHEMA_VERSION,
  VISUAL_PRINT_SNAPSHOT_SCHEMA_VERSION,
  VISUAL_RESULT_SCHEMA_VERSION,
  buildMinimalValidSnapshot,
  isUnitDeclared,
  printSchemaViolationCodes,
  profilePixelConsistency,
  resolvePrintProfile,
  resolveSnapshotScope,
  samplingRequiredForSite,
  serializePrintSchema,
  validatePrintSetManifest,
  validateVisualPrintSnapshot,
  validateVisualResult,
  type VisualPrintSnapshotV1,
} from "./printSchema";
import {
  PGV_REGISTRY_SCHEMA_VERSION,
  VISUAL_SITE_REGISTRY,
  type VisualSiteRecord,
} from "../lib/visualExportRegistry";

// ── Хелперы ──────────────────────────────────────────────────────

function getSite(viewId: string): VisualSiteRecord {
  const site = VISUAL_SITE_REGISTRY.find((s) => s.view_id === viewId);
  if (!site) throw new Error(`site not found in registry: ${viewId}`);
  return site;
}

function codes(violations: ReturnType<typeof validateVisualPrintSnapshot>): string[] {
  return violations.map((v) => v.code);
}

// ── 1. Версии схем и профили (spec §7, PGV-AC16) ─────────────────

describe("PGV-01: версии схем и каталог print-профилей", () => {
  it("версии схем закреплены (versioned contracts, spec §6)", () => {
    expect(VISUAL_RESULT_SCHEMA_VERSION).toBe("pgv.visual_result/1");
    expect(VISUAL_PRINT_SNAPSHOT_SCHEMA_VERSION).toBe("pgv.visual_print_snapshot/1");
    expect(PRINT_MANIFEST_SCHEMA_VERSION).toBe("pgv.print_manifest/1");
    expect(PRINT_PROFILES_SCHEMA_VERSION).toBe("pgv.print_profiles/1");
  });

  it("каталог профилей: ровно 3 профиля spec §7 — figure-landscape и A4 portrait/landscape", () => {
    expect(PRINT_PROFILE_CATALOG.map((p) => p.id)).toEqual([
      "figure-landscape",
      "a4-portrait",
      "a4-landscape",
    ]);
    expect(PRINT_PROFILE_CATALOG.every((p) => p.ppi === 300)).toBe(true);
  });

  it("A4 при 300 ppi — ровно 2480×3508 (portrait) и 3508×2480 (landscape) px (spec §7)", () => {
    const portrait = resolvePrintProfile("a4-portrait");
    const landscape = resolvePrintProfile("a4-landscape");
    expect(portrait).toBeDefined();
    expect(landscape).toBeDefined();
    expect([portrait!.width_px, portrait!.height_px]).toEqual([2480, 3508]);
    expect([landscape!.width_px, landscape!.height_px]).toEqual([3508, 2480]);
    expect(portrait!.width_mm).toBe(210);
    expect(portrait!.height_mm).toBe(297);
  });

  it("пиксели согласованы с физическим размером при 300 ppi (PGV-AC16, допуск округления ≤1px)", () => {
    for (const profile of PRINT_PROFILE_CATALOG) {
      expect(profilePixelConsistency(profile)).toBe(true);
    }
    // Пропорции A4 сохранены: 2480/3508 ≈ 210/297 (intended proportions).
    const portrait = resolvePrintProfile("a4-portrait")!;
    const ratioPx = portrait.width_px / portrait.height_px;
    const ratioMm = portrait.width_mm / portrait.height_mm;
    expect(Math.abs(ratioPx - ratioMm)).toBeLessThan(0.01);
  });

  it("профиль по умолчанию — figure-landscape; неизвестный профиль не резолвится (422 invalid_profile — PGV-09)", () => {
    expect(DEFAULT_PRINT_PROFILE_ID).toBe("figure-landscape");
    expect(resolvePrintProfile("figure-landscape")).toBeDefined();
    expect(resolvePrintProfile("poster-huge")).toBeUndefined();
    expect(resolvePrintProfile("")).toBeUndefined();
  });

  it("лимиты §7 закреплены: 12 MP/стр, 20 стр, 50 MiB, 60 s, tenant=1/global=2", () => {
    expect(PRINT_LIMITS).toEqual({
      max_megapixels_per_page: 12,
      max_pages_per_set: 20,
      max_output_bytes: 52428800,
      render_timeout_s: 60,
      concurrency_per_tenant: 1,
      concurrency_global: 2,
    });
  });
});

// ── 2. Units: честные единицы с XOR-причиной (spec §6) ───────────

describe("PGV-01: units — значение XOR причина, без выдуманных единиц", () => {
  it("unit объявлен: ровно одно из value/reason", () => {
    expect(isUnitDeclared({ value: "usd", reason: null })).toBe(true);
    expect(isUnitDeclared({ value: null, reason: "dimensionless" })).toBe(true);
    expect(isUnitDeclared({ value: null, reason: "legacy_unknown" })).toBe(true);
  });

  it("unit не объявлен: оба null или оба заполнены — нечестно", () => {
    expect(isUnitDeclared({ value: null, reason: null })).toBe(false);
    expect(isUnitDeclared({ value: "usd", reason: "dimensionless" })).toBe(false);
  });
});

// ── 3. Обязательность metadata по applicability ─────────────────

describe("PGV-01: обязательные refs по scope (Result/version/date по applicability)", () => {
  it("scope выводится из реестра: demo / research / passport / comparison", () => {
    expect(resolveSnapshotScope(getSite("navigator.upload.chart.series"))).toBe("demo");
    expect(resolveSnapshotScope(getSite("eda.feature_select.matrix"))).toBe("research");
    expect(resolveSnapshotScope(getSite("upload.passport.panel"))).toBe("passport");
    expect(resolveSnapshotScope(getSite("forecasting.monitoring.d12"))).toBe("comparison");
  });

  it("обязательные refs по scope закреплены (version обязателен для research/passport)", () => {
    expect(MANDATORY_REFS_BY_SCOPE.demo).toEqual(["demo_dataset_id"]);
    expect(MANDATORY_REFS_BY_SCOPE.research).toEqual(["context_id", "data_revision"]);
    expect(MANDATORY_REFS_BY_SCOPE.passport).toEqual([
      "context_id",
      "snapshot_id",
      "data_revision",
      "schema_version",
    ]);
    expect(MANDATORY_REFS_BY_SCOPE.comparison).toEqual(["research_run_id", "comparison_id"]);
  });

  it("research-снапшот без data_revision — нарушение missing_required_ref (критерий version)", () => {
    const site = getSite("upload.distribution.scatter");
    const snapshot = buildMinimalValidSnapshot(site);
    const broken: VisualPrintSnapshotV1 = {
      ...snapshot,
      refs: Object.fromEntries(
        Object.entries(snapshot.refs).filter(([key]) => key !== "data_revision"),
      ),
    };
    const violations = validateVisualPrintSnapshot(broken, site);
    expect(codes(violations)).toContain("missing_required_ref");
  });

  it("все заявленные refs реестра (required_refs) обязательны в снапшоте — по applicability", () => {
    const site = getSite("forecasting.forecast.chart");
    const snapshot = buildMinimalValidSnapshot(site);
    for (const ref of site.required_refs) {
      expect(snapshot.refs[ref]).toBeTruthy();
    }
    const withoutForecastRef: VisualPrintSnapshotV1 = {
      ...snapshot,
      refs: Object.fromEntries(
        Object.entries(snapshot.refs).filter(([key]) => key !== "forecast_artifact_ref"),
      ),
    };
    expect(codes(validateVisualPrintSnapshot(withoutForecastRef, site))).toContain(
      "missing_required_ref",
    );
  });

  it("date честна: computed_at null без reason — нарушение; с reason legacy_unknown — валидно (PGV-AC12)", () => {
    const site = getSite("upload.distribution.scatter");
    const base = buildMinimalValidSnapshot(site);
    const noDateNoReason: VisualPrintSnapshotV1 = {
      ...base,
      times: { ...base.times, computed_at: null, computed_at_reason: null },
    };
    expect(codes(validateVisualPrintSnapshot(noDateNoReason, site))).toContain("missing_date");

    const legacyUnknown: VisualPrintSnapshotV1 = {
      ...base,
      times: { ...base.times, computed_at: null, computed_at_reason: "legacy_unknown" },
    };
    expect(validateVisualPrintSnapshot(legacyUnknown, site)).toEqual([]);
  });

  it("результат обязателен (Result): result_ref/result_schema_version пустые — нарушение", () => {
    const site = getSite("upload.distribution.scatter");
    const base = buildMinimalValidSnapshot(site);
    const noResult: VisualPrintSnapshotV1 = {
      ...base,
      result: { ...base.result, result_ref: "", result_schema_version: "" },
    };
    const violationCodes = codes(validateVisualPrintSnapshot(noResult, site));
    expect(violationCodes).toContain("missing_result_ref");
  });
});

// ── 4. Содержательные требования по renderer_kind (units/legend) ──

describe("PGV-01: содержательные требования секций по renderer_kind", () => {
  it("recharts_svg: оси с именами и units обязательны; ось без units — нарушение (PGV-AC05)", () => {
    const chartSite = getSite("upload.chart.series");
    const snapshot = buildMinimalValidSnapshot(chartSite);
    expect(validateVisualPrintSnapshot(snapshot, chartSite)).toEqual([]);

    const broken = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    broken.display.sections[0].axes[0].units = { value: null, reason: null };
    expect(codes(validateVisualPrintSnapshot(broken, chartSite))).toContain("missing_units");
  });

  it("html_table: заголовки строк/колонок обязательны (axes_applicability=not_applicable, spec §6)", () => {
    const site = getSite("upload.overview.preview");
    const snapshot = buildMinimalValidSnapshot(site);
    expect(validateVisualPrintSnapshot(snapshot, site)).toEqual([]);

    const broken = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    broken.display.sections[0].table_headings = null;
    expect(codes(validateVisualPrintSnapshot(broken, site))).toContain(
      "missing_table_headings",
    );
  });

  it("html_heatmap: цветовая шкала с domain и units обязательна (spec §6 heatmap scale/domain)", () => {
    const site = getSite("eda.feature_select.matrix");
    const snapshot = buildMinimalValidSnapshot(site);
    expect(validateVisualPrintSnapshot(snapshot, site)).toEqual([]);

    const broken = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    broken.display.sections[0].heatmap_scale = null;
    expect(codes(validateVisualPrintSnapshot(broken, site))).toContain(
      "missing_heatmap_scale",
    );
  });

  it("detail_level compact/expanded не теряет обязательную metadata (PGV-AC05)", () => {
    const site = getSite("upload.chart.series");
    const compact = buildMinimalValidSnapshot(site, { detailLevel: "compact" });
    const expanded = buildMinimalValidSnapshot(site, { detailLevel: "expanded" });
    expect(compact.display.detail_level).toBe("compact");
    expect(expanded.display.detail_level).toBe("expanded");
    // Оба валидны: обязательные поля не зависят от detail_level.
    expect(validateVisualPrintSnapshot(compact, site)).toEqual([]);
    expect(validateVisualPrintSnapshot(expanded, site)).toEqual([]);
  });
});

// ── 5. Sampling: по applicability, без скрытого upgrade (PGV-AC08) ─

describe("PGV-01: sampling обязателен по applicability, режимы различимы", () => {
  it("samplingRequiredForSite: графики/таблицы/heatmap — да; html_cards — нет", () => {
    expect(samplingRequiredForSite(getSite("upload.chart.series"))).toBe(true);
    expect(samplingRequiredForSite(getSite("upload.overview.preview"))).toBe(true);
    expect(samplingRequiredForSite(getSite("eda.feature_select.matrix"))).toBe(true);
    expect(samplingRequiredForSite(getSite("upload.quality.teaser"))).toBe(false);
  });

  it("график без sampling-блока — нарушение missing_sampling", () => {
    const site = getSite("upload.chart.series");
    const snapshot = buildMinimalValidSnapshot(site);
    const broken: VisualPrintSnapshotV1 = {
      ...snapshot,
      sampling: { applicable: false, mode: null, point_cap: null, reason: null },
    };
    expect(codes(validateVisualPrintSnapshot(broken, site))).toContain("missing_sampling");
  });

  it("downsampled без point_cap — нарушение missing_point_cap (нет скрытого detail upgrade)", () => {
    const site = getSite("upload.chart.series");
    const snapshot = buildMinimalValidSnapshot(site);
    const broken: VisualPrintSnapshotV1 = {
      ...snapshot,
      sampling: { applicable: true, mode: "downsampled", point_cap: null, reason: null },
    };
    expect(codes(validateVisualPrintSnapshot(broken, site))).toContain("missing_point_cap");
    const withCap: VisualPrintSnapshotV1 = {
      ...snapshot,
      sampling: { applicable: true, mode: "downsampled", point_cap: 500, reason: null },
    };
    expect(validateVisualPrintSnapshot(withCap, site)).toEqual([]);
  });

  it("html_cards: sampling not applicable с явной причиной — валидно", () => {
    const site = getSite("upload.quality.teaser");
    const snapshot = buildMinimalValidSnapshot(site);
    expect(snapshot.sampling.applicable).toBe(false);
    expect(snapshot.sampling.reason).toBeTruthy();
    expect(validateVisualPrintSnapshot(snapshot, site)).toEqual([]);
  });
});

// ── 6. Trusted-параметры (критерий «параметры trusted») ──────────

describe("PGV-01: параметры trusted — producer freeze, client selection по allowlist", () => {
  it("origin client запрещён: только producer_freeze/producer_first_export", () => {
    const site = getSite("upload.chart.series");
    const snapshot = buildMinimalValidSnapshot(site);
    const clientAuthored = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    clientAuthored.method.origin = "client_request" as unknown as "producer_freeze";
    expect(codes(validateVisualPrintSnapshot(clientAuthored, site))).toContain(
      "untrusted_parameter_origin",
    );
  });

  it("client selection вне allowlist view_params реестра — нарушение selection_not_allowlisted", () => {
    const site = getSite("upload.chart.series");
    const snapshot = buildMinimalValidSnapshot(site);
    const intruder = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    intruder.selection.allowlist = [...site.view_params, "authoritative_series_override"];
    expect(codes(validateVisualPrintSnapshot(intruder, site))).toContain(
      "selection_not_allowlisted",
    );
  });

  it("selection в пределах view_params — валидно", () => {
    const site = getSite("forecasting.forecast.chart");
    const snapshot = buildMinimalValidSnapshot(site);
    snapshot.selection.values = { origin: "2025-01", horizon: 12 };
    expect(validateVisualPrintSnapshot(snapshot, site)).toEqual([]);
  });
});

// ── 7. Панельная семантика и checkpoint (PGV-AC11/AC14) ──────────

describe("PGV-01: панель без смешивания; reused checkpoint с подтверждением", () => {
  it("панельный вид (panel) требует entity_column и mode=panel (PGV-AC14)", () => {
    const site = getSite("modeling.panel.metrics");
    const snapshot = buildMinimalValidSnapshot(site);
    expect(snapshot.dimensions.mode).toBe("panel");
    expect(snapshot.dimensions.entity_column).toBeTruthy();
    expect(validateVisualPrintSnapshot(snapshot, site)).toEqual([]);
  });

  it("entity_id на чисто univariate виде — нарушение panel_mixing (смешивание запрещено)", () => {
    const site = getSite("upload.distribution.scatter");
    const snapshot = buildMinimalValidSnapshot(site);
    const mixed = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    mixed.dimensions.entity_id = "Kazakhstan";
    expect(codes(validateVisualPrintSnapshot(mixed, site))).toContain("panel_mixing");
  });

  it("reused checkpoint без confirmed_at/source_snapshot_ref — нарушение (PGV-AC11)", () => {
    const site = getSite("eda.passport.panel");
    const snapshot = buildMinimalValidSnapshot(site, { checkpointReused: true });
    expect(snapshot.checkpoint?.reused).toBe(true);
    expect(snapshot.times.checkpoint_confirmed_at).toBeTruthy();
    expect(snapshot.checkpoint?.source_snapshot_ref).toBeTruthy();
    expect(validateVisualPrintSnapshot(snapshot, site)).toEqual([]);

    const broken = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    broken.times.checkpoint_confirmed_at = null;
    broken.checkpoint!.source_snapshot_ref = null;
    const violationCodes = codes(validateVisualPrintSnapshot(broken, site));
    expect(violationCodes).toContain("missing_checkpoint_confirmation");
  });
});

// ── 8. Renderer env, sensitive-политика (PGV-AC17/AC19/AC21) ─────

describe("PGV-01: честный renderer env и sensitive-политика metadata", () => {
  it("dependency_status unavailable без причины — нарушение (PGV-AC17)", () => {
    const site = getSite("upload.chart.series");
    const snapshot = buildMinimalValidSnapshot(site);
    const broken = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    broken.renderer_env.dependency_status = "unavailable";
    broken.renderer_env.unavailable_reason = null;
    expect(codes(validateVisualPrintSnapshot(broken, site))).toContain(
      "missing_renderer_reason",
    );
    const honest = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    honest.renderer_env.dependency_status = "unavailable";
    honest.renderer_env.unavailable_reason = "print_renderer_not_deployed";
    expect(validateVisualPrintSnapshot(honest, site)).toEqual([]);
  });

  it("raw данные в metadata запрещены схемой (raw_data_included=false — пин, PGV-AC21)", () => {
    const site = getSite("upload.chart.series");
    const snapshot = buildMinimalValidSnapshot(site);
    expect(snapshot.sensitive.raw_data_included).toBe(false);
    const broken = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    broken.sensitive.raw_data_included = true;
    expect(codes(validateVisualPrintSnapshot(broken, site))).toContain(
      "raw_data_included_forbidden",
    );
  });

  it("schema_version чужой версии — нарушение schema_version_mismatch", () => {
    const site = getSite("upload.chart.series");
    const snapshot = buildMinimalValidSnapshot(site);
    const broken = JSON.parse(JSON.stringify(snapshot)) as VisualPrintSnapshotV1;
    (broken as { schema_version: string }).schema_version = "pgv.visual_print_snapshot/2";
    expect(codes(validateVisualPrintSnapshot(broken, site))).toContain(
      "schema_version_mismatch",
    );
  });
});

// ── 9. Согласованность реестр⇄схема (93 sites, уточнение PGV-01) ──

describe("PGV-01: registry cross-check — каждый render-site PGV-00 валиден по схеме", () => {
  it("research-scope сайты несут context_id+data_revision (version обязателен; уточнение required_refs PGV-01)", () => {
    const gaps: string[] = [];
    for (const site of VISUAL_SITE_REGISTRY) {
      if (resolveSnapshotScope(site) !== "research") continue;
      const refs = new Set(site.required_refs);
      for (const mandatory of MANDATORY_REFS_BY_SCOPE.research) {
        if (!refs.has(mandatory)) gaps.push(`${site.view_id}: -${mandatory}`);
      }
    }
    expect(gaps).toEqual([]);
  });

  it("минимальный валидный снапшот строится и валиден для всех 93 сайтов реестра", () => {
    const problems: string[] = [];
    for (const site of VISUAL_SITE_REGISTRY) {
      const snapshot = buildMinimalValidSnapshot(site);
      const violations = validateVisualPrintSnapshot(snapshot, site);
      if (violations.length > 0) {
        problems.push(`${site.view_id}: ${violations.map((v) => v.code).join(",")}`);
      }
    }
    expect(problems).toEqual([]);
  });

  it("паритет TS⇄JSON: config/print_schema.json — структурно честный твин print-схемы", () => {
    const jsonPath = path.resolve(__dirname, "..", "..", "..", "config", "print_schema.json");
    expect(existsSync(jsonPath)).toBe(true);
    const json = JSON.parse(readFileSync(jsonPath, "utf-8")) as ReturnType<typeof serializePrintSchema>;
    expect(json).toEqual(serializePrintSchema());
    expect(json.schema_version).toBe("pgv.print_schema/1");
    expect(json.pgv_task).toBe("PGV-01");
  });
});

// ── 10. Манифест комплекта (ZIP: PNG + manifest + metadata, §7) ──

describe("PGV-01: манифест комплекта — порядок/hash отдельно от PNG bytes (PGV-AC21)", () => {
  const base = {
    schema_version: PRINT_MANIFEST_SCHEMA_VERSION,
    set_id: "set-0001",
    render_version: "print-renderer/1",
    profile_id: "a4-portrait",
    metadata_filename: "metadata.json",
    dependencies: [],
    data_included: false,
  };
  const page = (name: string, index: number, hash: string) => ({
    filename: name,
    page_role: "passport.groups",
    index,
    width_px: 2480,
    height_px: 3508,
    png_sha256: hash,
  });

  it("валидный манифест проходит", () => {
    const manifest = {
      ...base,
      pages: [page("page-01.png", 1, "a".repeat(64)), page("page-02.png", 2, "b".repeat(64))],
    };
    expect(validatePrintSetManifest(manifest)).toEqual([]);
  });

  it("дубликаты имён страниц и разрыв порядка — нарушения", () => {
    const dup = { ...base, pages: [page("page-01.png", 1, "c".repeat(64)), page("page-01.png", 2, "d".repeat(64))] };
    expect(codes(validatePrintSetManifest(dup))).toContain("duplicate_filename");
    const gap = { ...base, pages: [page("page-01.png", 1, "c".repeat(64)), page("page-02.png", 3, "d".repeat(64))] };
    expect(codes(validatePrintSetManifest(gap))).toContain("page_order_gap");
  });

  it("hash страницы обязателен; data_included=true запрещён (без raw данных)", () => {
    const noHash = { ...base, pages: [page("page-01.png", 1, "")] };
    expect(codes(validatePrintSetManifest(noHash))).toContain("missing_page_hash");
    const withData = { ...base, pages: [], data_included: true };
    expect(codes(validatePrintSetManifest(withData))).toContain("data_included_forbidden");
  });
});

// ── 11. VisualResult/1 — immutable frozen input (spec §6) ────────

describe("PGV-01: VisualResult/1 — нормализованный frozen input", () => {
  const validResult = {
    schema_version: VISUAL_RESULT_SCHEMA_VERSION,
    view_id: "upload.chart.series",
    payload: {
      kind: "recharts_svg",
      series_cap: null,
      digest: "d".repeat(64),
      digest_reason: null,
    },
    parameters: { origin: "producer_freeze", method: "line", parameters: {} },
    units: [{ value: "usd", reason: null }],
    sampling: { applicable: true, mode: "full", point_cap: null, reason: null },
    warnings: [],
    execution: {
      execution_ref: "exec-1",
      result_ref: "artifact:visual_result:1",
      computed_at: "2026-10-27T00:00:00Z",
      computed_at_reason: null,
    },
  };

  it("валидный VisualResult проходит", () => {
    expect(validateVisualResult(validResult)).toEqual([]);
  });

  it("client-authored parameters в VisualResult — нарушение untrusted_parameter_origin", () => {
    const broken = {
      ...validResult,
      parameters: { origin: "client_request", method: "line", parameters: {} },
    };
    expect(validateVisualResult(broken).map((v) => v.code)).toContain(
      "untrusted_parameter_origin",
    );
  });

  it("digest XOR digest_reason (честный digest либо причина)", () => {
    const broken = {
      ...validResult,
      payload: { ...validResult.payload, digest: null, digest_reason: null },
    };
    expect(validateVisualResult(broken).map((v) => v.code)).toContain("missing_digest");
  });

  it("коды нарушений стабильны (контракт для PGV-02/09: 422 invalid_selection/profile и пр.)", () => {
    const stable = printSchemaViolationCodes();
    for (const code of [
      "missing_required_ref",
      "missing_result_ref",
      "missing_date",
      "missing_units",
      "missing_sampling",
      "missing_point_cap",
      "untrusted_parameter_origin",
      "selection_not_allowlisted",
      "panel_mixing",
      "missing_checkpoint_confirmation",
      "missing_renderer_reason",
      "raw_data_included_forbidden",
      "schema_version_mismatch",
    ]) {
      expect(stable).toContain(code);
    }
  });
});

// ── 12. Реестр PGV-00 не повреждён уточнением PGV-01 ─────────────

describe("PGV-01: уточнение required_refs сохраняет инварианты PGV-00", () => {
  it("schema_version реестра и denominator не менялись", () => {
    expect(PGV_REGISTRY_SCHEMA_VERSION).toBe("pgv.visual_registry/1");
    expect(VISUAL_SITE_REGISTRY.length).toBe(93);
  });

  it("уточнённые записи PGV-01 несут data_revision (version обязателен)", () => {
    for (const viewId of ["upload.structure.schema", "forecasting.accuracy.metrics"]) {
      const site = getSite(viewId);
      expect(site.required_refs).toContain("data_revision");
    }
  });
});
