// apps/print-renderer/src/rendererCore.test.ts
//
// PGV-08 — Sandboxed renderer container: jest-оракулы чистого ядра
// (spec_passport_graphics_visual.md §13 строка PGV-08, критерий
// «Final image smoke кириллица/IH/A4, no-network/non-root/hard timeout»).
//
// Оракулы на своих данных (прецедент серии CERT): pHYs-инъекция AC16,
// честный dependency-манифест AC17, sandbox-политика AC19, контракт
// таймаута AC20, SSR print page из общего бандла PGV-07 (§4.1),
// deployment-константы. Браузерная приёмка — scripts/pgv08/verify_local.py
// (реальный Chromium), docker-сборка — build/Dockerfile (среда сессии
// без docker-демона — честная граница, пин R2).

import { crc32, deflateSync } from "node:zlib";
import {
  buildDependencyManifest,
  buildErrorBody,
  buildPrintHtml,
  buildSandboxLaunchSpec,
  buildRequestPolicy,
  clampTimeoutSeconds,
  DEFAULT_HARD_TIMEOUT_S,
  DEPENDENCY_CHECKS,
  ERROR_BODY_RETRYABILITY,
  injectPngPhys,
  parsePngChunks,
  RENDER_PAYLOAD_SCHEMA_VERSION,
  RENDERER_VERSION,
  RENDER_PORT_DEFAULT,
  sanitizeFrozenSvg,
  validateRenderPayload,
  type RenderPagePayload,
} from "./rendererCore";
import type { VisualPrintSnapshotV1 } from "../../../packages/ui/print/printSchema";

// ── Тестовый PNG-конструктор (минимальный валидный PNG, RGB 8-bit) ──

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
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // color type RGB
  const rowBytes = width * 3;
  const raw = Buffer.alloc((rowBytes + 1) * height);
  for (let y = 0; y < height; y += 1) {
    raw[y * (rowBytes + 1)] = 0; // filter none
    for (let x = 0; x < rowBytes; x += 1) {
      raw[y * (rowBytes + 1) + 1 + x] = (x + y) % 256;
    }
  }
  const idat = deflateSync(raw);
  const iend = Buffer.alloc(0);
  return Buffer.concat([signature, chunk("IHDR", ihdr), chunk("IDAT", idat), chunk("IEND", iend)]);
}

// ── Тестовый парсер чанков (независимый от реализации) ────────────

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

// ── Тестовый frozen-снапшот (свой ряд: кириллица, известные числа) ─

function makeSnapshot(overrides?: Partial<VisualPrintSnapshotV1>): VisualPrintSnapshotV1 {
  const base: VisualPrintSnapshotV1 = {
    schema_version: "pgv.visual_print_snapshot/1",
    view_id: "eda.ih_conditional.matrix",
    scope: "research",
    refs: { context_id: "ctx-0001", data_revision: "rev-2026-10-29" },
    result: {
      result_ref: "vr-a1b2c3d4e5f60718",
      result_schema_version: "pgv.visual_result/1",
      result_digest: "deadbeef",
      result_digest_reason: null,
    },
    data_artifact: {
      artifact_id: "art-1",
      artifact_version: "v3",
      source_hash: "aa11bb22",
      hash_algorithm: "sha256",
      hash_reason: null,
    },
    expected_context: {
      context_id: "ctx-0001",
      data_revision: "rev-2026-10-29",
      expected_data_digest: "cafe01",
    },
    dimensions: {
      target_column: "Валовой региональный продукт",
      date_column: "Год",
      entity_column: null,
      entity_id: null,
      mode: "univariate",
    },
    times: {
      computed_at: "2026-10-29T09:15:00+00:00",
      computed_at_reason: null,
      captured_at: "2026-10-29T09:20:00+00:00",
      captured_at_reason: null,
      checkpoint_confirmed_at: null,
      render_requested_at: null,
      timezone: "UTC",
      locale: "ru-RU",
    },
    checkpoint: null,
    display: {
      title: "Условное распределение цели по интервалам фактора",
      subtitle: "Модуль EDA / остановка «Взаимодействия признаков»",
      detail_level: "compact",
      sections: [],
    },
    method: {
      origin: "producer_first_export",
      method: "ih_conditional",
      parameters: { bins: 4 },
    },
    selection: { allowlist: ["bins"], values: { bins: 4 } },
    sampling: {
      applicable: true,
      mode: "full",
      point_cap: null,
      reason: null,
    },
    annotations: { revision: 0, author: "analyst", text: null },
    print: { profile_id: "figure-landscape", page_count: 1, theme: "light-print" },
    renderer_env: {
      renderer_version: null,
      font_profile: null,
      dependency_status: "available",
      unavailable_reason: null,
    },
    data_flow: { before_revision: null, after_revision: "rev-2026-10-29" },
    sensitive: {
      raw_data_included: false,
      sensitive_fields_policy: "metadata_only",
    },
    warnings: ["Демонстрационный оракул PGV-08: известные counts/rates/bins."],
    ...overrides,
  };
  return base;
}

const IH_SECTION = {
  section_id: "sec-ih",
  kind: "ih_conditional" as const,
  title: "Интервалы фактора → доля цели",
  ih_input: {
    feature_label: "Инвестиции в основной капитал",
    target_label: "Валовой региональный продукт",
    x_bins: ["[0; 100)", "[100; 250)", "[250; ∞)"],
    y_bins: ["низкая", "средняя", "высокая"],
    rows: [
      { x_bin: "[0; 100)", values: [60, 30, 10] },
      { x_bin: "[100; 250)", values: [25, 50, 25] },
      { x_bin: "[250; ∞)", values: [10, 20, 70] },
    ],
    n_observations: 9876,
    row_totals: [100, 200, 300],
    denominator_note: null,
  },
};

describe("PGV-08 rendererCore: версии контрактов", () => {
  it("пинует версию payload, версию рендерера и порт по умолчанию", () => {
    expect(RENDER_PAYLOAD_SCHEMA_VERSION).toBe("pgv.render_payload/1");
    expect(RENDERER_VERSION).toBe("print-renderer/1");
    expect(RENDER_PORT_DEFAULT).toBe(8907);
  });

  it("hard timeout по умолчанию равен render_timeout_s каталога PGV-01", () => {
    // PRINT_LIMITS.render_timeout_s = 60 (spec §7/§18 «PDF до 60 s»).
    expect(DEFAULT_HARD_TIMEOUT_S).toBe(60);
  });
});

describe("PGV-08 rendererCore: pHYs-инъекция 300 ppi (PGV-AC16)", () => {
  it("вставляет pHYs после IHDR с 11811 px/m для 300 ppi", () => {
    const png = makePng(24, 16);
    const out = injectPngPhys(png, 300);
    const chunks = readChunks(out);
    const types = chunks.map((c) => c.type);
    expect(types.indexOf("pHYs")).toBeGreaterThan(-1);
    // pHYs обязан идти сразу после IHDR и до IDAT.
    expect(types.indexOf("pHYs")).toBe(types.indexOf("IHDR") + 1);
    expect(types.indexOf("pHYs")).toBeLessThan(types.indexOf("IDAT"));
    const phys = chunks.find((c) => c.type === "pHYs")!.data;
    expect(phys.length).toBe(9);
    expect(phys.readUInt32BE(0)).toBe(11811); // 300 dpi / 0.0254
    expect(phys.readUInt32BE(4)).toBe(11811);
    expect(phys[8]).toBe(1); // unit = метр
    // CRC чанка честный (проверяется независимо): pos — позиция TYPE;
    // typeAndData = [pos, pos+13), CRC-поле на pos+13.
    const pos = out.indexOf(Buffer.from("pHYs", "ascii"));
    const typeAndData = out.subarray(pos, pos + 4 + 9);
    const crcStored = out.readUInt32BE(pos + 13) >>> 0;
    expect(crc32(typeAndData) >>> 0).toBe(crcStored);
  });

  it("сохраняет байты исходного изображения (IHDR/IDAT/IEND не менялись)", () => {
    const png = makePng(10, 8);
    const out = injectPngPhys(png, 300);
    const before = readChunks(png).filter((c) => c.type !== "pHYs");
    const after = readChunks(out).filter((c) => c.type !== "pHYs");
    expect(after.length).toBe(before.length);
    before.forEach((c, i) => {
      expect(after[i].type).toBe(c.type);
      expect(Buffer.compare(after[i].data, c.data)).toBe(0);
    });
  });

  it("заменяет существующий pHYs, а не дублирует (идемпотентность)", () => {
    const png = injectPngPhys(makePng(8, 8), 72);
    const twice = injectPngPhys(png, 300);
    const physChunks = readChunks(twice).filter((c) => c.type === "pHYs");
    expect(physChunks.length).toBe(1);
    expect(physChunks[0].data.readUInt32BE(0)).toBe(11811);
  });

  it("ppi→px/m конверсия честна: 72 ppi → 2835, 600 ppi → 23622", () => {
    const a = readChunks(injectPngPhys(makePng(4, 4), 72)).find((c) => c.type === "pHYs")!;
    expect(a.data.readUInt32BE(0)).toBe(2835);
    const b = readChunks(injectPngPhys(makePng(4, 4), 600)).find((c) => c.type === "pHYs")!;
    expect(b.data.readUInt32BE(0)).toBe(23622);
  });

  it("отказ на не-PNG входе (сигнатура) — без молчаливой порчи", () => {
    expect(() => injectPngPhys(Buffer.from("not a png"), 300)).toThrow();
  });

  it("parsePngChunks возвращает размеры IHDR (база смоука без растровых библиотек)", () => {
    const chunks = parsePngChunks(makePng(2480, 3508));
    expect(chunks.width).toBe(2480);
    expect(chunks.height).toBe(3508);
    expect(chunks.hasPhys).toBe(false);
    const withPhys = parsePngChunks(injectPngPhys(makePng(2400, 1500), 300));
    expect(withPhys.width).toBe(2400);
    expect(withPhys.height).toBe(1500);
    expect(withPhys.hasPhys).toBe(true);
    expect(withPhys.physPpuX).toBe(11811);
  });
});

describe("PGV-08 rendererCore: dependency-манифест (PGV-AC17, без ложного ready)", () => {
  const allPresent = {
    browserExecutable: "/opt/pw-browsers/chromium-1200/chrome-linux64/chrome",
    fontFiles: ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    bundleLoaded: true,
  };

  it("все зависимости на месте → available с зафиксированными чеками", () => {
    const manifest = buildDependencyManifest(allPresent);
    expect(manifest.dependency_status).toBe("available");
    expect(manifest.unavailable_reason).toBeNull();
    expect(manifest.checks.browser).toBe(true);
    expect(manifest.checks.fonts).toBe(true);
    expect(manifest.checks.bundle).toBe(true);
    expect(DEPENDENCY_CHECKS).toEqual(["browser", "fonts", "bundle"]);
  });

  it("нет браузера → unavailable/missing_browser, не available", () => {
    const manifest = buildDependencyManifest({ ...allPresent, browserExecutable: null });
    expect(manifest.dependency_status).toBe("unavailable");
    expect(manifest.unavailable_reason).toBe("missing_browser");
    expect(manifest.checks.browser).toBe(false);
  });

  it("нет шрифтов → unavailable/missing_fonts", () => {
    const manifest = buildDependencyManifest({ ...allPresent, fontFiles: [] });
    expect(manifest.dependency_status).toBe("unavailable");
    expect(manifest.unavailable_reason).toBe("missing_fonts");
  });

  it("бандл не загружен → unavailable/missing_bundle", () => {
    const manifest = buildDependencyManifest({ ...allPresent, bundleLoaded: false });
    expect(manifest.dependency_status).toBe("unavailable");
    expect(manifest.unavailable_reason).toBe("missing_bundle");
  });

  it("первый недостающий ресурс — единственная причина (детерминизм диагностики)", () => {
    const manifest = buildDependencyManifest({
      browserExecutable: null,
      fontFiles: [],
      bundleLoaded: false,
    });
    expect(manifest.unavailable_reason).toBe("missing_browser");
  });
});

describe("PGV-08 rendererCore: sandbox-политика (PGV-AC19)", () => {
  it("javascript отключён и service workers блокируются на странице рендера", () => {
    const spec = buildSandboxLaunchSpec();
    expect(spec.pageContextOptions.javaScriptEnabled).toBe(false);
    expect(spec.pageContextOptions.serviceWorkers).toBe("block");
  });

  it("политика запросов: http/https/file/blob/ftp — блок, data:/about:blank — разрешён", () => {
    const policy = buildRequestPolicy();
    expect(policy.shouldBlock("http://example.com/x.png")).toBe(true);
    expect(policy.shouldBlock("https://example.com/x.png")).toBe(true);
    expect(policy.shouldBlock("file:///etc/passwd")).toBe(true);
    expect(policy.shouldBlock("blob:https://x/y")).toBe(true);
    expect(policy.shouldBlock("ftp://x/y")).toBe(true);
    expect(policy.shouldBlock("data:image/png;base64,AAAA")).toBe(false);
    expect(policy.shouldBlock("about:blank")).toBe(false);
  });

  it("launch-спецификация без сетевых/фоновых служб, с пином цветового профиля", () => {
    const spec = buildSandboxLaunchSpec();
    expect(spec.chromiumArgs).toContain("--disable-background-networking");
    expect(spec.chromiumArgs).toContain("--disable-component-update");
    expect(spec.chromiumArgs).toContain("--disable-extensions");
    expect(spec.chromiumArgs).toContain("--disable-dev-shm-usage");
    expect(spec.chromiumArgs).toContain("--force-color-profile=srgb");
    expect(spec.chromiumArgs).toContain("--font-render-hinting=none");
    expect(spec.chromiumArgs).toContain("--hide-scrollbars");
    // Детерминизм: нет GPU, нет первых запусков.
    expect(spec.chromiumArgs).toContain("--disable-gpu");
    expect(spec.chromiumArgs).toContain("--no-first-run");
    expect(spec.chromiumArgs).toContain("--no-default-browser-check");
    expect(spec.chromiumArgs.join(" ")).not.toMatch(/remote-debugging-port/);
  });

  it("санитайзер frozen SVG удаляет script/foreignObject/on*-атрибуты и внешние ссылки", () => {
    const dirty = [
      "<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'>",
      "<script>fetch('http://evil')</script>",
      "<image href='http://127.0.0.1:9/x.png'/>",
      "<foreignObject><body>pwn</body></foreignObject>",
      "<rect width='10' height='10' fill='#2563EB'/>",
      "</svg>",
    ].join("");
    const result = sanitizeFrozenSvg(dirty);
    expect(result.xml).not.toMatch(/<script/i);
    expect(result.xml).not.toMatch(/foreignObject/i);
    expect(result.xml).not.toMatch(/onload/i);
    expect(result.xml).not.toMatch(/href='http/i);
    expect(result.xml).toContain("<rect");
    expect(result.warnings.length).toBeGreaterThan(0);
  });

  it("санитайзер пропускает чистый SVG без предупреждений (не портит научную геометрию)", () => {
    const clean = "<svg xmlns='http://www.w3.org/2000/svg'><rect fill='#2563EB'/></svg>";
    const result = sanitizeFrozenSvg(clean);
    expect(result.warnings.length).toBe(0);
    expect(result.xml).toBe(clean);
  });
});

describe("PGV-08 rendererCore: таймаут (PGV-AC20)", () => {
  it("effective timeout = min(requested, hard cap); запрос больше cap зажимается", () => {
    expect(clampTimeoutSeconds(30, 60)).toBe(30);
    expect(clampTimeoutSeconds(120, 60)).toBe(60);
    expect(clampTimeoutSeconds(null, 60)).toBe(60);
    expect(clampTimeoutSeconds(0, 60)).toBe(1);
    expect(clampTimeoutSeconds(-5, 60)).toBe(1);
  });

  it("тела ошибок: dependency_unavailable — терминальная (retryable=false), timeout — повторяемая", () => {
    expect(ERROR_BODY_RETRYABILITY.render_dependency_unavailable).toBe(false);
    expect(ERROR_BODY_RETRYABILITY.render_timeout).toBe(true);
    const dep = buildErrorBody("render_dependency_unavailable", "нет браузера");
    expect(dep.error.code).toBe("render_dependency_unavailable");
    expect(dep.error.retryable).toBe(false);
    const timeout = buildErrorBody("render_timeout", "60 s истекли");
    expect(timeout.error.retryable).toBe(true);
  });
});

describe("PGV-08 rendererCore: валидация payload pgv.render_payload/1", () => {
  const validPayload = (): RenderPagePayload => ({
    schema_version: "pgv.render_payload/1",
    request_id: "req-0001",
    snapshot: makeSnapshot(),
    sections: [IH_SECTION],
    options: {},
  });

  it("валидный payload проходит без нарушений", () => {
    const result = validateRenderPayload(validPayload());
    expect(result.violations).toEqual([]);
    expect(result.payload?.snapshot.view_id).toBe("eda.ih_conditional.matrix");
  });

  it("неверный schema_version → schema_version_mismatch", () => {
    const result = validateRenderPayload({
      ...validPayload(),
      schema_version: "pgv.render_payload/2",
    });
    expect(result.violations.map((v) => v.code)).toContain("schema_version_mismatch");
  });

  it("неизвестный профиль → invalid_profile (паритет кода PGV-01)", () => {
    const snapshot = makeSnapshot();
    snapshot.print.profile_id = "a3-poster" as never;
    const result = validateRenderPayload({ ...validPayload(), snapshot });
    expect(result.violations.map((v) => v.code)).toContain("invalid_profile");
  });

  it("неизвестный renderer_kind секции → invalid_section_kind", () => {
    const result = validateRenderPayload({
      ...validPayload(),
      sections: [{ ...IH_SECTION, kind: "waterfall" as never }],
    });
    expect(result.violations.map((v) => v.code)).toContain("invalid_section_kind");
  });

  it("пустой список секций → empty_sections", () => {
    const result = validateRenderPayload({ ...validPayload(), sections: [] });
    expect(result.violations.map((v) => v.code)).toContain("empty_sections");
  });

  it("не-уникальные section_id → duplicate_section", () => {
    const result = validateRenderPayload({
      ...validPayload(),
      sections: [IH_SECTION, { ...IH_SECTION }],
    });
    expect(result.violations.map((v) => v.code)).toContain("duplicate_section");
  });

  it("IH-секция без ih_input → missing_field (нет фабкации данных)", () => {
    const result = validateRenderPayload({
      ...validPayload(),
      sections: [{ ...IH_SECTION, ih_input: undefined } as never],
    });
    expect(result.violations.map((v) => v.code)).toContain("missing_field");
  });
});

describe("PGV-08 rendererCore: SSR print page из общего бандла PGV-07 (§4.1)", () => {
  const payload = (): RenderPagePayload => ({
    schema_version: "pgv.render_payload/1",
    request_id: "req-ssr-1",
    snapshot: makeSnapshot(),
    sections: [
      IH_SECTION,
      {
        section_id: "sec-table",
        kind: "html_table" as const,
        title: "Сводка по интервалам",
        headings: { row: ["Интервал", "Наблюдения", "Доля"], column: [] },
        rows: [
          ["[0; 100)", "100", "33,3 %"],
          ["[100; 250)", "200", "66,7 %"],
        ],
        units: [{ value: "набл.", reason: null }],
      },
    ],
    options: {},
  });

  it("HTML содержит кириллицу заголовка/подзаголовка и meta-состав §7", () => {
    const html = buildPrintHtml(payload(), 1, 1);
    expect(html).toContain("Условное распределение цели по интервалам фактора");
    expect(html).toContain("Модуль EDA / остановка «Взаимодействия признаков»");
    expect(html).toContain("Валовой региональный продукт");
    expect(html).toContain("Стр. 1 из 1");
    // Короткий ref результата в подвале (§7): shortRef keep=10.
    expect(html).toContain("vr-a1b2c3d…");
  });

  it("IH-матрица печатается полностью: bins, проценты, знаменатели, правило 100 % (AC02)", () => {
    const html = buildPrintHtml(payload(), 1, 1);
    expect(html).toContain("[0; 100)");
    expect(html).toContain("[250; ∞)");
    expect(html).toContain("60 %");
    expect(html).toContain("9 876");
    expect(html).toContain("суммируется до 100");
  });

  it("геометрия поверхности = px профиля (AC16) и шрифтовой стек DejaVu Sans", () => {
    const html = buildPrintHtml(
      {
        ...payload(),
        snapshot: makeSnapshot({
          print: { profile_id: "a4-portrait", page_count: 1, theme: "light-print" },
        }),
      },
      1,
      1,
    );
    expect(html).toContain("width:2480px");
    expect(html).toContain("height:3508px");
    expect(html).toContain("DejaVu Sans");
  });

  it("HTML без <script, без внешних URL (http/https/file), с CSP default-src 'none' (AC19)", () => {
    const html = buildPrintHtml(payload(), 1, 1);
    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/https?:\/\//);
    expect(html).not.toMatch(/file:\/\//);
    expect(html).toContain("default-src 'none'");
  });

  it("санитизированный svg_xml попадает в страницу как научная геометрия (§4.1 passthrough)", () => {
    const svg = "<svg xmlns='http://www.w3.org/2000/svg'><rect width='8' height='8' fill='#2563EB'/></svg>";
    const html = buildPrintHtml(
      {
        ...payload(),
        sections: [
          {
            section_id: "sec-chart",
            kind: "recharts_svg" as const,
            title: "Ряд",
            svg_xml: svg,
          },
        ],
      },
      1,
      1,
    );
    expect(html).toContain("<rect");
    expect(html).not.toMatch(/<script/i);
  });

  it("recharts_svg без svg_xml → честный placeholder, не выдуманный график", () => {
    const html = buildPrintHtml(
      {
        ...payload(),
        sections: [{ section_id: "sec-chart", kind: "recharts_svg" as const, title: "Ряд" }],
      },
      1,
      1,
    );
    expect(html).toContain("научная геометрия не приложена");
  });

  it("html_table секция печатает строки и заголовки; единицы объявлены", () => {
    const html = buildPrintHtml(payload(), 1, 1);
    expect(html).toContain("Интервал");
    expect(html).toContain("Наблюдения");
    expect(html).toContain("33,3 %");
    expect(html).toContain("набл.");
  });

  it("html_cards секция печатает подпись/значение/единицу", () => {
    const html = buildPrintHtml(
      {
        ...payload(),
        sections: [
          {
            section_id: "sec-cards",
            kind: "html_cards" as const,
            title: "Показатели",
            cards: [
              { label: "Наблюдений", value: "9 876", unit: { value: "набл.", reason: null } },
              { label: "Пропусков", value: "12", unit: { value: null, reason: "dimensionless" } },
            ],
          },
        ],
      },
      1,
      1,
    );
    expect(html).toContain("Наблюдений");
    expect(html).toContain("9 876");
    expect(html).toContain("без единицы (dimensionless)");
  });
});
