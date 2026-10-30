/**
 * PGV-08-CERT — Class A: независимые оракулы сертификатора на СВОИХ данных.
 *
 * Namespace p8cert-* — дизъюнктен repo-корпусу поставки
 * (apps/print-renderer/src/rendererCore.test.ts) и python-оракулам
 * tests/api/test_pgv08_render_container.py. Без импорта repo-фикстур:
 * свой ряд «Экспорт продукции» (12 345 наблюдений, согласные знаменатели),
 * свои ppi-значения (150/96/300), свои враждебные SVG-конструкты,
 * свои коды нарушений.
 *
 * Каналы кампании (scripts/pgv08cert/run_mutation_campaign.py):
 *   ORACLE = этот файл (Class A, GREEN на поставке 3500775);
 *   REPO   = author jest rendererCore.test.ts (35);
 *   PY     = author python deployment-оракулы (22; 10 RED — находка F-P8C1).
 *
 * Спека: spec_passport_graphics_visual.md §11–14 (PGV-08, AC16/17/19/20/23),
 * spec_documentation_logging.md §375 («HTML/SVG из внешних источников не
 * исполняются»), §543 («timeout renderer возвращает failed, а не
 * повреждённый ready файл»).
 */
import { deflateSync } from "node:zlib";
import { pngCrc32Oracle as crc32 } from "../testing/pngCrc32Oracle";

import {
  buildDependencyManifest,
  buildErrorBody,
  buildPrintHtml,
  buildRequestPolicy,
  buildSandboxLaunchSpec,
  clampTimeoutSeconds,
  DEFAULT_HARD_TIMEOUT_S,
  DEPENDENCY_CHECKS,
  ERROR_BODY_RETRYABILITY,
  escapeHtml,
  injectPngPhys,
  parsePngChunks,
  RENDER_PAYLOAD_SCHEMA_VERSION,
  RENDER_PORT_DEFAULT,
  RENDERER_FONT_PROFILE,
  RENDERER_VERSION,
  sanitizeFrozenSvg,
  validateRenderPayload,
  type RenderPagePayload,
  type RenderSectionContent,
} from "../../apps/print-renderer/src/rendererCore";
import { readConfig } from "../../apps/print-renderer/src/renderWorker";
import {
  a4Scenario,
  cyrillicScenario,
  ihScenario,
} from "../../apps/print-renderer/src/smokeScenarios";
import {
  PRINT_LIMITS,
  PRINT_PROFILE_CATALOG,
  resolvePrintProfile,
  type VisualPrintSnapshotV1,
} from "../../packages/ui/print/printSchema";

// ── Свой PNG-конструктор сертификатора (минимальный валидный PNG) ──

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, "ascii");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])) >>> 0, 0);
  return Buffer.concat([len, typeBuf, data, crc]);
}

function makePng(width: number, height: number): Buffer {
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2; // RGB
  const rowBytes = width * 3;
  const raw = Buffer.alloc((rowBytes + 1) * height);
  for (let y = 0; y < height; y += 1) {
    raw[y * (rowBytes + 1)] = 0;
    for (let x = 0; x < rowBytes; x += 1) {
      raw[y * (rowBytes + 1) + 1 + x] = (x * 7 + y * 3) % 251;
    }
  }
  return Buffer.concat([
    signature,
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function readChunks(png: Buffer): Array<{ type: string; data: Buffer }> {
  const out: Array<{ type: string; data: Buffer }> = [];
  let offset = 8;
  while (offset + 8 <= png.length) {
    const len = png.readUInt32BE(offset);
    const type = png.toString("ascii", offset + 4, offset + 8);
    out.push({ type, data: png.subarray(offset + 8, offset + 8 + len) });
    offset += 12 + len;
  }
  return out;
}

// ── Свой frozen-снапшот сертификатора («Экспорт продукции») ───────

function certSnapshot(overrides?: Partial<VisualPrintSnapshotV1>): VisualPrintSnapshotV1 {
  const base: VisualPrintSnapshotV1 = {
    schema_version: "pgv.visual_print_snapshot/1",
    view_id: "cert.pgv08.export_series",
    scope: "demo",
    refs: { context_id: "ctx-cert-08", data_revision: "rev-cert-2026-10-29" },
    result: {
      result_ref: "vr-cert08a1b2c3d4e5",
      result_schema_version: "pgv.visual_result/1",
      result_digest: "cert08digest",
      result_digest_reason: null,
    },
    data_artifact: {
      artifact_id: "art-cert-1",
      artifact_version: "v7",
      source_hash: "bb22cc33",
      hash_algorithm: "sha256",
      hash_reason: null,
    },
    expected_context: {
      context_id: "ctx-cert-08",
      data_revision: "rev-cert-2026-10-29",
      expected_data_digest: "cert08",
    },
    dimensions: {
      target_column: "Экспорт продукции",
      date_column: "Квартал",
      entity_column: null,
      entity_id: null,
      mode: "univariate",
    },
    times: {
      computed_at: "2026-10-29T08:00:00+00:00",
      computed_at_reason: null,
      captured_at: "2026-10-29T08:30:00+00:00",
      captured_at_reason: null,
      checkpoint_confirmed_at: null,
      render_requested_at: null,
      timezone: "UTC",
      locale: "ru-RU",
    },
    checkpoint: null,
    display: {
      title: "Экспорт & <данные> \"2026\" по округам",
      subtitle: "Корпус сертификатора PGV-08-CERT: свой ряд, свои counts",
      detail_level: "compact",
      sections: [],
    },
    method: {
      origin: "producer_freeze",
      method: "cert_oracle",
      parameters: { corpus: "p8cert" },
    },
    selection: { allowlist: ["corpus"], values: { corpus: "p8cert" } },
    sampling: { applicable: true, mode: "full", point_cap: null, reason: null },
    annotations: { revision: 3, author: "analyst", text: null },
    print: { profile_id: "figure-landscape", page_count: 1, theme: "light-print" },
    renderer_env: {
      renderer_version: null,
      font_profile: null,
      dependency_status: "available",
      unavailable_reason: null,
    },
    data_flow: { before_revision: null, after_revision: "rev-cert-2026-10-29" },
    sensitive: { raw_data_included: false, sensitive_fields_policy: "metadata_only" },
    warnings: ["Фикстура сертификатора PGV-08-CERT: собственные counts/rates/bins."],
    ...overrides,
  };
  return base;
}

/** Своя IH-фикстура: знаменатели СОГЛАСНЫ (4000+4200+4145 = 12 345). */
const CERT_IH: RenderSectionContent = {
  section_id: "cert-ih",
  kind: "ih_conditional",
  title: "Доля экспорта по интервалам инвестиций",
  ih_input: {
    feature_label: "Инвестиции в основной капитал",
    target_label: "Экспорт продукции",
    x_bins: ["[0; 50)", "[50; 120)", "[120; ∞)"],
    y_bins: ["низкий", "средний", "высокий"],
    rows: [
      { x_bin: "[0; 50)", values: [55, 25, 20] },
      { x_bin: "[50; 120)", values: [30, 45, 25] },
      { x_bin: "[120; ∞)", values: [15, 35, 50] },
    ],
    n_observations: 12345,
    row_totals: [4000, 4200, 4145],
    denominator_note: null,
  },
};

const CERT_TABLE: RenderSectionContent = {
  section_id: "cert-table",
  kind: "html_table",
  title: "Экспорт по федеральным округам",
  headings: { row: ["Округ", "Объём", "Доля"], column: [] },
  rows: [
    ["Центральный ФО", "12 345", "41,7 %"],
    ["Приволжский ФО", "6 789", "22,9 %"],
  ],
  units: [{ value: "млн руб.", reason: null }],
};

function certPayload(sections: RenderSectionContent[], overrides?: Record<string, unknown>): RenderPagePayload {
  return {
    schema_version: RENDER_PAYLOAD_SCHEMA_VERSION,
    request_id: "cert-req-0001",
    snapshot: certSnapshot(),
    sections,
    options: {},
    ...overrides,
  } as RenderPagePayload;
}

// ── Версии контрактов и пины каталога ─────────────────────────────

describe("p8cert A1: версии контрактов и пины каталога PGV-01", () => {
  it("версии payload/рендерера/шрифтового профиля и порт зафиксированы", () => {
    expect(RENDER_PAYLOAD_SCHEMA_VERSION).toBe("pgv.render_payload/1");
    expect(RENDERER_VERSION).toBe("print-renderer/1");
    expect(RENDERER_FONT_PROFILE).toBe("print-fonts-dejavu/1");
    expect(RENDER_PORT_DEFAULT).toBe(8907);
  });

  it("hard timeout пинуется каталогом PGV-01 (не литералом)", () => {
    expect(DEFAULT_HARD_TIMEOUT_S).toBe(PRINT_LIMITS.render_timeout_s);
    expect(DEFAULT_HARD_TIMEOUT_S).toBe(60);
  });
});

// ── pHYs-инъекция (AC16) на своих ppi-значениях ───────────────────

describe("p8cert A2: pHYs-инъекция на своих ppi (AC16)", () => {
  it("150 ppi → 5906 px/m, позиция сразу после IHDR, до IDAT", () => {
    const out = injectPngPhys(makePng(12, 9), 150);
    const types = readChunks(out).map((c) => c.type);
    expect(types.indexOf("pHYs")).toBe(types.indexOf("IHDR") + 1);
    expect(types.indexOf("pHYs")).toBeLessThan(types.indexOf("IDAT"));
    const phys = readChunks(out).find((c) => c.type === "pHYs")!.data;
    expect(phys.length).toBe(9);
    expect(phys.readUInt32BE(0)).toBe(5906); // 150/0.0254 = 5905.51 → 5906
    expect(phys.readUInt32BE(4)).toBe(5906);
    expect(phys[8]).toBe(1); // unit = метр
  });

  it("96 ppi → 3780 px/m; 300 ppi → 11811 px/m (конверсия честна)", () => {
    const p96 = readChunks(injectPngPhys(makePng(4, 4), 96)).find((c) => c.type === "pHYs")!;
    expect(p96.data.readUInt32BE(0)).toBe(3780); // 96/0.0254 = 3779.53 → 3780
    const p300 = readChunks(injectPngPhys(makePng(4, 4), 300)).find((c) => c.type === "pHYs")!;
    expect(p300.data.readUInt32BE(0)).toBe(11811);
  });

  it("CRC чанка честен (независимый пересчёт сертификатора)", () => {
    const out = injectPngPhys(makePng(6, 4), 300);
    const pos = out.indexOf(Buffer.from("pHYs", "ascii"));
    const typeAndData = out.subarray(pos, pos + 4 + 9);
    expect(out.readUInt32BE(pos + 13) >>> 0).toBe(crc32(typeAndData) >>> 0);
  });

  it("байты изображения не меняются; повторная инъекция идемпотентна", () => {
    const src = makePng(7, 5);
    const once = injectPngPhys(src, 96);
    const before = readChunks(src).filter((c) => c.type !== "pHYs");
    const after = readChunks(once).filter((c) => c.type !== "pHYs");
    expect(after.length).toBe(before.length);
    before.forEach((c, i) => {
      expect(after[i].type).toBe(c.type);
      expect(Buffer.compare(after[i].data, c.data)).toBe(0);
    });
    const twice = injectPngPhys(once, 300);
    const physList = readChunks(twice).filter((c) => c.type === "pHYs");
    expect(physList.length).toBe(1);
    expect(physList[0].data.readUInt32BE(0)).toBe(11811);
  });

  it("не-PNG вход → отказ без молчаливой порчи; parsePngChunks честен", () => {
    expect(() => injectPngPhys(Buffer.from("сертификатор", "utf8"), 300)).toThrow();
    const info = parsePngChunks(injectPngPhys(makePng(11, 13), 150));
    expect(info.width).toBe(11);
    expect(info.height).toBe(13);
    expect(info.hasPhys).toBe(true);
    expect(info.physPpuX).toBe(5906);
    expect(info.idatBytes).toBeGreaterThan(0);
  });
});

// ── Dependency-манифест (AC17) на своих комбинациях ──────────────

describe("p8cert A3: dependency-манифест (AC17, без ложного ready)", () => {
  const ok = {
    browserExecutable: "/opt/pw-browsers/chromium-1200/chrome-linux/chrome",
    fontFiles: ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    bundleLoaded: true,
  };

  it("полный комплект → available; порядок чеков зафиксирован", () => {
    const m = buildDependencyManifest(ok);
    expect(m.dependency_status).toBe("available");
    expect(m.unavailable_reason).toBeNull();
    expect(m.checks).toEqual({ browser: true, fonts: true, bundle: true });
    expect(DEPENDENCY_CHECKS).toEqual(["browser", "fonts", "bundle"]);
  });

  it("пустая строка пути браузера не признаётся зависимостью (ложный ready исключён)", () => {
    const m = buildDependencyManifest({ ...ok, browserExecutable: "" });
    expect(m.dependency_status).toBe("unavailable");
    expect(m.unavailable_reason).toBe("missing_browser");
  });

  it("шрифты/бандл по отдельности дают свои причины; приоритет browser→fonts→bundle", () => {
    expect(buildDependencyManifest({ ...ok, fontFiles: [] }).unavailable_reason).toBe("missing_fonts");
    expect(buildDependencyManifest({ ...ok, bundleLoaded: false }).unavailable_reason).toBe("missing_bundle");
    expect(
      buildDependencyManifest({ browserExecutable: null, fontFiles: [], bundleLoaded: false }).unavailable_reason,
    ).toBe("missing_browser");
  });
});

// ── Sandbox: launch-spec + политика запросов (AC19) ──────────────

describe("p8cert A4: sandbox-политика (AC19)", () => {
  it("JS выключен, service workers блокируются, CSP не обходится", () => {
    const spec = buildSandboxLaunchSpec();
    expect(spec.pageContextOptions.javaScriptEnabled).toBe(false);
    expect(spec.pageContextOptions.serviceWorkers).toBe("block");
    expect(spec.pageContextOptions.bypassCSP).toBe(false);
  });

  it("--no-sandbox сознательно НЕ ставится (fail-closed, §12); цветовой пин на месте", () => {
    const args = buildSandboxLaunchSpec().chromiumArgs;
    expect(args).not.toContain("--no-sandbox");
    expect(args).toContain("--force-color-profile=srgb");
    expect(args).toContain("--font-render-hinting=none");
    expect(args.join(" ")).not.toMatch(/remote-debugging-port/);
  });

  it("перечисленные внешние/файловые схемы блокируются; data:/about:blank/пусто — разрешены (регистронезависимо)", () => {
    const policy = buildRequestPolicy();
    for (const blocked of [
      "http://example.com/a.png",
      "https://example.com/a.png",
      "file:///etc/shadow",
      "blob:https://x/1",
      "ftp://host/f",
      "ws://x/ws",
      "wss://x/wss",
      "HTTP://UPPERCASE.RU/x",
    ]) {
      expect(policy.shouldBlock(blocked)).toBe(true);
    }
    for (const allowed of ["", "about:blank", "data:image/png;base64,iVBORw0KGgo="]) {
      expect(policy.shouldBlock(allowed)).toBe(false);
    }
    expect(policy.blockReason("file:///etc/shadow")).toBe("file_url_blocked");
    expect(policy.blockReason("https://example.com/x")).toBe("external_url_blocked");
    expect(policy.blockReason("about:blank")).toBeNull();
  });

  it("санитайзер удаляет свои враждебные конструкты и считает честные warnings", () => {
    const dirty =
      "<svg xmlns='http://www.w3.org/2000/svg'>" +
      "<script type='text/javascript'>alert(2)</script>" +
      "<a xlink:href='https://evil.example/x'><circle r='5'/></a>" +
      "<rect onerror='pwn()' width='2' height='2'/>" +
      "<foreignObject><p>cert</p></foreignObject>" +
      "<image src='http://evil.example/i.png'/>" +
      "</svg>";
    const res = sanitizeFrozenSvg(dirty);
    expect(res.xml).not.toMatch(/<script/i);
    expect(res.xml).not.toMatch(/foreignObject/i);
    expect(res.xml).not.toMatch(/onerror/i);
    expect(res.xml).not.toMatch(/evil\.example/);
    expect(res.xml).toContain("<circle");
    expect(res.warnings.length).toBe(4); // script/xlink/on*/foreignObject/src — fail-visible
  });

  it("чистый SVG сертификатора проходит без изменений и без warnings", () => {
    const clean = "<svg xmlns='http://www.w3.org/2000/svg'><circle r='3' fill='#1D4ED8'/></svg>";
    const res = sanitizeFrozenSvg(clean);
    expect(res.xml).toBe(clean);
    expect(res.warnings.length).toBe(0);
  });
});

// ── Таймаут/ошибки (AC20) на своих значениях ─────────────────────

describe("p8cert A5: таймаут и retryability (AC20)", () => {
  it("зажим [1, cap]: запрос больше cap не расширяет лимит", () => {
    expect(clampTimeoutSeconds(45, 60)).toBe(45);
    expect(clampTimeoutSeconds(61, 60)).toBe(60);
    expect(clampTimeoutSeconds(null, 60)).toBe(60);
    expect(clampTimeoutSeconds(0, 60)).toBe(1);
    expect(clampTimeoutSeconds(-3, 60)).toBe(1);
    expect(clampTimeoutSeconds(Number.NaN, 60)).toBe(60);
    expect(clampTimeoutSeconds(5, 0)).toBe(1); // вырожденный cap → минимум 1 s
  });

  it("матрица retryability полная; неизвестный код — честный false", () => {
    expect(ERROR_BODY_RETRYABILITY).toEqual({
      render_dependency_unavailable: false,
      render_timeout: true,
      renderer_busy: true,
      invalid_payload: false,
      payload_too_large: false,
      internal_render_error: false,
    });
    const unknown = buildErrorBody("cert_unknown_code", "нет такого");
    expect(unknown.error.retryable).toBe(false);
    expect(unknown.error.renderer_version).toBe(RENDERER_VERSION);
  });
});

// ── Валидация payload (паритет кодов PGV-01) на своей матрице ────

describe("p8cert A6: валидация payload pgv.render_payload/1", () => {
  it("валидный payload сертификатора — 0 нарушений", () => {
    const res = validateRenderPayload(certPayload([CERT_IH, CERT_TABLE]));
    expect(res.violations).toEqual([]);
    expect(res.payload?.snapshot.view_id).toBe("cert.pgv08.export_series");
  });

  it("своя матрица нарушений: коды паритета PGV-01", () => {
    const wrongVersion = validateRenderPayload({ ...certPayload([CERT_IH]), schema_version: "pgv.render_payload/9" });
    expect(wrongVersion.violations.map((v) => v.code)).toContain("schema_version_mismatch");

    const noReq = validateRenderPayload(certPayload([CERT_IH], { request_id: "" }));
    expect(noReq.violations.map((v) => v.code)).toContain("missing_field");

    const notObject = validateRenderPayload("строка вместо payload");
    expect(notObject.violations[0].code).toBe("missing_field");
    expect(notObject.payload).toBeNull();

    const noSnapshot = validateRenderPayload(certPayload([CERT_IH], { snapshot: null }));
    expect(noSnapshot.violations.map((v) => v.code)).toContain("missing_field");

    const badProfile = certPayload([CERT_IH]);
    (badProfile.snapshot.print as { profile_id: string }).profile_id = "poster-a0" as never;
    expect(validateRenderPayload(badProfile).violations.map((v) => v.code)).toContain("invalid_profile");

    const empty = validateRenderPayload(certPayload([]));
    expect(empty.violations.map((v) => v.code)).toContain("empty_sections");

    const badKind = validateRenderPayload(certPayload([{ ...CERT_TABLE, kind: "gauge" } as never]));
    expect(badKind.violations.map((v) => v.code)).toContain("invalid_section_kind");

    const dup = validateRenderPayload(certPayload([CERT_IH, { ...CERT_IH }]));
    expect(dup.violations.map((v) => v.code)).toContain("duplicate_section");

    const noIh = validateRenderPayload(certPayload([{ ...CERT_IH, ih_input: undefined } as never]));
    expect(noIh.violations.map((v) => v.code)).toContain("missing_field");

    const noHeadings = validateRenderPayload(certPayload([{ ...CERT_TABLE, headings: undefined } as never]));
    expect(noHeadings.violations.map((v) => v.code)).toContain("missing_table_headings");

    const noCells = validateRenderPayload(
      certPayload([
        {
          section_id: "cert-hm",
          kind: "html_heatmap",
          row_headings: ["r1"],
          column_headings: ["c1"],
        } as never,
      ]),
    );
    expect(noCells.violations.map((v) => v.code)).toContain("missing_field");

    const noCards = validateRenderPayload(
      certPayload([{ section_id: "cert-cards", kind: "html_cards" } as never]),
    );
    expect(noCards.violations.map((v) => v.code)).toContain("missing_field");
  });
});

// ── SSR print page (§4.1 общий бандл) на своём контенте ──────────

describe("p8cert A7: SSR print page на своих данных (§4.1, AC02/04/16/19/23)", () => {
  it("кириллица заголовка/таблицы; ru-группировка своего числа 12 345", () => {
    const html = buildPrintHtml(certPayload([CERT_IH, CERT_TABLE]), 1, 1);
    expect(html).toContain("Экспорт &amp; &lt;данные&gt; &quot;2026&quot; по округам");
    expect(html).toContain("Центральный ФО");
    expect(html).toContain("12 345");
    expect(html).toContain("6 789");
    expect(html).toContain("млн руб.");
  });

  it("IH-фикстура сертификатора печатается: bins/проценты/согласный знаменатель (AC02)", () => {
    const html = buildPrintHtml(certPayload([CERT_IH]), 1, 1);
    expect(html).toContain("[120; ∞)");
    expect(html).toContain("55 %");
    expect(html).toContain("Наблюдений: 12 345");
    expect(html).toContain("суммируется до 100");
    expect(html).toContain("4 145"); // построчный знаменатель в ru-группировке
  });

  it("геометрия a4-landscape из бандла: 3508×2480 и DejaVu Sans (AC16)", () => {
    const html = buildPrintHtml(
      certPayload([CERT_TABLE], {
        snapshot: certSnapshot({
          print: { profile_id: "a4-landscape", page_count: 1, theme: "light-print" },
        }),
      }),
      1,
      1,
    );
    expect(html).toContain("width:3508px");
    expect(html).toContain("height:2480px");
    expect(html).toContain("DejaVu Sans");
    expect(html).toContain("Стр. 1 из 1");
  });

  it("CSP default-src 'none', base about:blank, белый фон; без script/внешних URL (AC19/AC23)", () => {
    const html = buildPrintHtml(certPayload([CERT_TABLE]), 1, 1);
    expect(html).toContain("default-src 'none'");
    expect(html).toContain('<base href="about:blank">');
    expect(html).toContain("background:#FFFFFF");
    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/https?:\/\//);
    expect(html).not.toMatch(/file:\/\//);
  });

  it("escapeHtml сертификатора: полная пятёрка спецсимволов", () => {
    expect(escapeHtml('&<>"\'')).toBe("&amp;&lt;&gt;&quot;&#39;");
    expect(escapeHtml("Ряд & ряд <ряд> \"ряд\" 'ряд'")).toBe(
      "Ряд &amp; ряд &lt;ряд&gt; &quot;ряд&quot; &#39;ряд&#39;",
    );
  });

  it("html_heatmap: явный домен и честный «нет данных» для null-ячейки", () => {
    const html = buildPrintHtml(
      certPayload([
        {
          section_id: "cert-hm",
          kind: "html_heatmap",
          title: "Матрица сертификатора",
          row_headings: ["Q1", "Q2"],
          column_headings: ["Экспорт", "Импорт"],
          cells: [
            [10, null],
            [50, 30],
          ],
          cell_texts: [
            [null, null],
            [null, null],
          ],
          domain: [0, 50],
        },
      ]),
      1,
      1,
    );
    expect(html).toContain("Матрица сертификатора");
    expect(html).toContain("Q1");
    expect(html).toContain("нет данных");
    // Контракт formatNumberRu (PGV-07): хвостовые нули дробной части срезаются
    // (10,0 → «10»; 50,0 → «50») — ожидание скорректировано по факту контракта.
    expect(html).toContain(">10<");
    expect(html).toContain(">50<");
    expect(html).toContain(">30<");
  });

  it("recharts_svg: чистая геометрия проходит; без svg_xml — честный placeholder", () => {
    const withSvg = buildPrintHtml(
      certPayload([
        {
          section_id: "cert-chart",
          kind: "recharts_svg",
          title: "Ряд экспорта",
          svg_xml: "<svg xmlns='http://www.w3.org/2000/svg'><rect width='4' height='4' fill='#1D4ED8'/></svg>",
        },
      ]),
      1,
      1,
    );
    expect(withSvg).toContain("<rect");
    expect(withSvg).not.toMatch(/<script/i);

    const placeholder = buildPrintHtml(
      certPayload([{ section_id: "cert-chart", kind: "recharts_svg", title: "Ряд экспорта" }]),
      1,
      1,
    );
    expect(placeholder).toContain("научная геометрия не приложена");
  });
});

// ── Конфиг worker'а: env-allowlist и деградация значений ─────────

describe("p8cert A8: readConfig (env allowlist CISSTAT_PRINT_RENDERER_*)", () => {
  it("дефолты: порт 8907, timeout 60 из каталога, concurrency 2, тело 8 MiB, TTL 30", () => {
    const cfg = readConfig({});
    expect(cfg.port).toBe(8907);
    expect(cfg.hardTimeoutS).toBe(60);
    expect(cfg.maxConcurrent).toBe(2);
    expect(cfg.maxBodyBytes).toBe(8388608);
    expect(cfg.readyzCacheS).toBe(30);
    expect(cfg.browserPath).toBeNull();
    expect(cfg.fontFiles).toContain("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf");
  });

  it("невалидные int-значения деградируют к дефолту; явные env читаются", () => {
    const bad = readConfig({ CISSTAT_PRINT_RENDERER_PORT: "abc", CISSTAT_PRINT_RENDERER_MAX_CONCURRENT: "0" });
    expect(bad.port).toBe(8907);
    expect(bad.maxConcurrent).toBe(2);
    const good = readConfig({ CISSTAT_PRINT_RENDERER_PORT: "9100", CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S: "45" });
    expect(good.port).toBe(9100);
    expect(good.hardTimeoutS).toBe(45);
  });
});

// ── Смоук-фикстуры поставки: валидность payload'ов ───────────────

describe("p8cert A9: смоук-фикстуры поставки — payload валиден, структура согласна", () => {
  it("три сценария проходят validateRenderPayload без нарушений", () => {
    for (const payload of [cyrillicScenario(), ihScenario(), a4Scenario()]) {
      const res = validateRenderPayload(payload);
      expect(res.violations).toEqual([]);
      expect(res.payload).not.toBeNull();
      expect(resolvePrintProfile(payload.snapshot.print.profile_id)).toBeDefined();
    }
  });

  it("геометрии смоук-сценариев согласны с каталогом PGV-01 (px/ppi)", () => {
    for (const payload of [cyrillicScenario(), ihScenario(), a4Scenario()]) {
      const profile = resolvePrintProfile(payload.snapshot.print.profile_id)!;
      expect(profile.ppi).toBe(300);
      expect(PRINT_PROFILE_CATALOG.some((p) => p.id === profile.id)).toBe(true);
    }
  });
});
