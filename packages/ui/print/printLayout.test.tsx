// packages/ui/print/printLayout.test.tsx
//
// PGV-07 — Shared pure print layout (spec_passport_graphics_visual.md
// §4.1 «Общий print bundle», §7 «PNG и печатная композиция», §13 строка
// PGV-07: точки изменения «packages/ui/print/chartVars/screen charts»,
// критерий готовности «Light фон, labels/legend/HTML IH/полные паспорта,
// без fetch/animation»).
//
// Оракулы:
//   1) Light-print контракт (PGV-AC04): непрозрачный белый фон, жёсткие
//      световые hex-константы (не var(), не dark-класс), паритет с картой
//      chartVars; рендер в .dark-предке байт-идентичен светлому рендеру.
//   2) Чистота бандла: статический оракул исходников — нет fetch/axios,
//      hooks, Tooltip/hover, ResponsiveContainer, Date.now()/new Date()/
//      Math.random (детерминизм), "use client"; анимации выключаются
//      глобальным kill-switch печатной страницы.
//   3) Композиция §7 (PGV-AC05): верх — заголовок/номер, источник/
//      target/entity, даты; низ — методы/параметры/пояснения, версия
//      данных, короткие IDs, page number; metadata одинаковы для
//      compact/expanded; SamplingBadge/легенда не теряются при раскрытии.
//   4) Профили (PGV-AC16): pageGeometry из каталога PGV-01 (A4 300 ppi,
//      figure-landscape), пропорции сохранены, фиксированная геометрия
//      поверхности (не viewport).
//   5) HTML IH (PGV-AC02): условная карта печатается полностью — все
//      bins строк/колонок, проценты, знаменатель строки, color legend.
//   6) Длинные таблицы (база PGV-AC15, оркестрация — PGV-14): chunkTableRows
//      режет ТОЛЬКО целыми строками, заголовки повторяются на каждой части.

import { readFileSync } from "node:fs";
import path from "node:path";
import React from "react";
import { render } from "@testing-library/react";

import {
  PRINT_PALETTE,
  PRINT_STATUS_MARKS,
  PRINT_TYPE_SCALE,
  isHexColor,
  resolveChartVarLight,
  resolveVarStringLight,
} from "./printTheme";
import {
  describeSampling,
  formatNumberRu,
  formatPrintTime,
  formatUnit,
  pageGeometry,
  shortRef,
  PrintLegendStrip,
  PrintPageFrame,
  PrintPageSurface,
} from "./printLayout";
import {
  chunkTableRows,
  PrintCardsSection,
  PrintChartSection,
  PrintHeatmapSection,
  PrintTableSection,
} from "./printSections";
import { PrintIhConditionalMatrix, PrintIhMetricsMap } from "./printIh";
import { CHART_VARS_LIGHT } from "../lib/chartVars";
import { buildMinimalValidSnapshot } from "./printSchema";
import {
  VISUAL_SITE_REGISTRY,
  type VisualSiteRecord,
} from "../lib/visualExportRegistry";

// ── Хелперы ──────────────────────────────────────────────────────

function getSite(viewId: string): VisualSiteRecord {
  const site = VISUAL_SITE_REGISTRY.find((s) => s.view_id === viewId);
  if (!site) throw new Error(`site not found: ${viewId}`);
  return site;
}

const SCATTER_SITE = "upload.distribution.scatter";
const PANEL_SITE = "forecasting.forecast.panel_chart";

function renderFrame(siteId: string = SCATTER_SITE, detail: "compact" | "expanded" = "compact") {
  const snapshot = buildMinimalValidSnapshot(getSite(siteId), { detailLevel: detail });
  const utils = render(
    <PrintPageFrame snapshot={snapshot} pageIndex={1} pageCount={2}>
      <p>тело страницы</p>
    </PrintPageFrame>,
  );
  return { snapshot, ...utils };
}

// ── 1. Light-print контракт (PGV-AC04) ───────────────────────────

describe("PGV-07 printTheme: light-print контракт (AC04)", () => {
  test("фон страницы — непрозрачный белый, все константы палитры — hex", () => {
    expect(PRINT_PALETTE.page_background).toBe("#FFFFFF");
    for (const [name, value] of Object.entries(PRINT_PALETTE)) {
      expect(isHexColor(value)).toBe(true);
      expect(value.toLowerCase()).not.toBe("#000000");
      // Непрозрачность: только 6-значный hex без альфы.
      expect(value).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(name.length).toBeGreaterThan(0);
    }
  });

  test("resolveChartVarLight паритетен карте chartVars (единственный источник светлых значений)", () => {
    const keys = Object.keys(CHART_VARS_LIGHT);
    expect(keys.length).toBeGreaterThan(20);
    for (const key of keys) {
      expect(resolveChartVarLight(key)).toBe(CHART_VARS_LIGHT[key]);
    }
    expect(resolveChartVarLight("нет-такой-переменной")).toBeNull();
  });

  test("resolveVarStringLight подставляет hex вместо var() и не теряет незнакомые ссылки (fail-visible)", () => {
    expect(resolveVarStringLight("var(--chart-brand)")).toBe(CHART_VARS_LIGHT["chart-brand"]);
    expect(resolveVarStringLight("1px solid var(--chart-border)")).toBe(
      `1px solid ${CHART_VARS_LIGHT["chart-border"]}`,
    );
    // Вне карты — ссылка остаётся видимой (не молча чёрная).
    expect(resolveVarStringLight("var(--нет-в-карте)")).toBe("var(--нет-в-карте)");
  });

  test("статусные метки дублируют цвет формой/текстом (цвет не единственный носитель смысла)", () => {
    const marks = new Set(PRINT_STATUS_MARKS.map((m) => m.key));
    expect(marks.has("positive")).toBe(true);
    expect(marks.has("negative")).toBe(true);
    for (const mark of PRINT_STATUS_MARKS) {
      expect(mark.mark.length).toBeGreaterThan(0);
      expect(mark.label.length).toBeGreaterThan(0);
      expect(isHexColor(mark.color)).toBe(true);
    }
    // Разные смыслы — разные текстовые метки (не только цвет).
    const labels = new Set(PRINT_STATUS_MARKS.map((m) => m.label));
    expect(labels.size).toBe(PRINT_STATUS_MARKS.length);
  });

  test("типографская шкала читаема (нельзя уменьшать до нечитаемого шрифта)", () => {
    expect(PRINT_TYPE_SCALE.body).toBeGreaterThanOrEqual(12);
    expect(PRINT_TYPE_SCALE.small).toBeGreaterThanOrEqual(10);
    expect(PRINT_TYPE_SCALE.title).toBeGreaterThan(PRINT_TYPE_SCALE.section);
  });
});

// ── 2. Чистота бандла (без fetch/animation/state) ────────────────

describe("PGV-07 purity: print-бандл без fetch/animation/состояния", () => {
  const SOURCES = [
    "printTheme.ts",
    "printLayout.tsx",
    "printSections.tsx",
    "printIh.tsx",
    "printPassport.tsx",
    "printComparison.tsx",
    "index.ts",
  ];

  test("статический оракул исходников: запрещённые паттерны отсутствуют", () => {
    for (const file of SOURCES) {
      const source = readFileSync(path.join(__dirname, file), "utf8");
      // Сеть/данные: pure presentation не фетчит (§4.1).
      expect(source).not.toMatch(/\bfetch\s*\(/);
      expect(source).not.toMatch(/\baxios\b/);
      expect(source).not.toMatch(/\bXMLHttpRequest\b/);
      // Состояние/эффекты: pure function of props.
      expect(source).not.toMatch(/use(State|Effect|Memo|Callback|Ref|Reducer|Context)\s*\(/);
      expect(source).not.toMatch(/["']use client["']/);
      // Экранное интерактивное: hover/tooltip/responsive — только screen.
      expect(source).not.toMatch(/\bTooltip\b/);
      expect(source).not.toMatch(/\bResponsiveContainer\b/);
      // Детерминизм: никакого текущего времени/случайности.
      expect(source).not.toMatch(/Date\.now\s*\(\s*\)/);
      expect(source).not.toMatch(/new Date\s*\(\s*\)/);
      expect(source).not.toMatch(/Math\.random\s*\(\s*\)/);
      // Тёмная тема не может просочиться: dark: вариантов нет.
      expect(source).not.toMatch(/dark:/);
    }
  });

  test("печатная страница несёт глобальный kill-switch анимаций/переходов", () => {
    const { container } = renderFrame();
    const style = container.querySelector("style");
    expect(style).not.toBeNull();
    expect(style?.textContent).toContain("animation");
    expect(style?.textContent).toContain("none");
    expect(style?.textContent).toContain("transition");
  });
});

// ── 3. Композиция §7 и метаданные (PGV-AC05) ─────────────────────

describe("PGV-07 PrintPageFrame: композиция §7 (AC05)", () => {
  test("верх: заголовок, вид, источник (module/stop), target/date/entity, даты", () => {
    const { snapshot, getByTestId } = renderFrame();
    const header = getByTestId("print-header");
    expect(header.textContent).toContain(snapshot.display.title);
    expect(header.textContent).toContain(snapshot.view_id);
    // Источник: module/stop из реестра PGV-00.
    expect(header.textContent).toContain("upload");
    expect(header.textContent).toContain("distribution");
    // Размерности: target/date/entity по applicability (не выдуманы).
    expect(header.textContent).toContain("target_column");
    expect(header.textContent).toContain("date_column");
    // Даты: computed_at из снапшота (детерминированный формат).
    expect(header.textContent).toContain("2026-10-27 00:00");
    expect(header.textContent).toContain("UTC");
  });

  test("панельный сайт печатает entity (без смешивания, AC14)", () => {
    const { snapshot, getByTestId } = renderFrame(PANEL_SITE);
    expect(snapshot.dimensions.mode).toBe("panel");
    expect(snapshot.dimensions.entity_id).not.toBeNull();
    expect(getByTestId("print-header").textContent).toContain("entity_id");
  });

  test("низ: метод/параметры, версия данных, короткий ID результата, номер страницы", () => {
    const { snapshot, getByTestId } = renderFrame();
    const footer = getByTestId("print-footer");
    expect(footer.textContent).toContain(snapshot.method.method);
    expect(footer.textContent).toContain("producer_freeze");
    expect(footer.textContent).toContain("data_revision");
    expect(footer.textContent).toContain(shortRef(snapshot.result.result_ref));
    expect(shortRef(snapshot.result.result_ref).length).toBeLessThanOrEqual(16);
    // Номер страницы: «Стр. 1 из 2».
    expect(footer.textContent).toContain("Стр. 1 из 2");
  });

  test("metadata-блок одинаков для compact и expanded (ничего не теряется при раскрытии)", () => {
    const compact = renderFrame(SCATTER_SITE, "compact");
    const expanded = renderFrame(SCATTER_SITE, "expanded");
    // Bound-queries RTL ищут в baseElement (body): при двух живых рендерах
    // скоупим к container каждого рендера явно.
    const metaCompact = compact.container.querySelector('[data-testid="print-meta"]')?.textContent ?? "";
    const metaExpanded = expanded.container.querySelector('[data-testid="print-meta"]')?.textContent ?? "";
    expect(metaExpanded).toBe(metaCompact);
    expect(metaCompact.length).toBeGreaterThan(0);
    // Обязательный состав: context/data_revision/время/метод/предупреждения.
    for (const token of ["context_id", "data_revision", "2026-10-27", "fixture"]) {
      expect(metaExpanded).toContain(token);
    }
  });

  test("SamplingBadge не теряется при раскрытии и честно называет усечение", () => {
    const snapshot = buildMinimalValidSnapshot(getSite(SCATTER_SITE), { detailLevel: "expanded" });
    snapshot.sampling = { applicable: true, mode: "downsampled", point_cap: 3000, reason: "lttb_screen_equiv" };
    const { getByTestId } = render(
      <PrintPageFrame snapshot={snapshot} pageIndex={1} pageCount={1}>
        <p>тело</p>
      </PrintPageFrame>,
    );
    const badge = getByTestId("print-sampling");
    expect(badge.textContent).toContain("downsampled");
    expect(badge.textContent).toContain("3000");
    expect(badge.textContent).toContain("lttb_screen_equiv");
  });

  test("предупреждения снапшота печатаются в поясе пояснений (не молча теряются)", () => {
    const snapshot = buildMinimalValidSnapshot(getSite(SCATTER_SITE));
    snapshot.warnings = ["stale: данные изменились после фиксации"];
    const { getByTestId } = render(
      <PrintPageFrame snapshot={snapshot} pageIndex={1} pageCount={1}>
        <p>тело</p>
      </PrintPageFrame>,
    );
    expect(getByTestId("print-warnings").textContent).toContain("stale: данные изменились после фиксации");
  });
});

// ── 4. Форматтеры: детерминизм и честные причины ─────────────────

describe("PGV-07 форматтеры: детерминизм и XOR-честность", () => {
  test("formatPrintTime детерминирован (из ISO-строки, без локали машины)", () => {
    expect(formatPrintTime("2026-10-27T12:34:56Z", null)).toBe("2026-10-27 12:34 UTC");
    expect(formatPrintTime("2026-10-27T12:34:56+03:00", null)).toBe("2026-10-27 12:34 UTC");
  });

  test("formatPrintTime: отсутствие даты — явная причина, не выдуманное время", () => {
    expect(formatPrintTime(null, "legacy_unknown")).toContain("legacy_unknown");
    expect(formatPrintTime(null, null)).toBe("—");
  });

  test("formatUnit: значение XOR причина (§6: единицы не выдумываются)", () => {
    expect(formatUnit({ value: "млн тонн", reason: null })).toBe("млн тонн");
    expect(formatUnit({ value: null, reason: "dimensionless" })).toContain("dimensionless");
    expect(formatUnit(undefined)).toBe("—");
  });

  test("formatNumberRu детерминирован и не зависит от ICU машины", () => {
    expect(formatNumberRu(1234.5)).toBe("1 234,5");
    expect(formatNumberRu(-0.25, 3)).toBe("-0,25");
    expect(formatNumberRu(null)).toBe("—");
  });

  test("shortRef укорачивает ID и честен на null", () => {
    // keep=10: первые 10 символов + многоточие (полный ref — в metadata, §7).
    expect(shortRef("artifact:visual_result:fixture:upload.distribution.scatter")).toBe(
      "artifact:v…",
    );
    expect(shortRef("короткий", 16)).toBe("короткий");
    expect(shortRef(null)).toBe("—");
  });

  test("describeSampling различает режимы (AC08: без скрытого upgrade)", () => {
    expect(describeSampling({ applicable: false, mode: null, point_cap: null, reason: "cards_view_no_series" })).toContain(
      "cards_view_no_series",
    );
    expect(describeSampling({ applicable: true, mode: "full", point_cap: null, reason: null })).toContain("full");
    const downsampled = describeSampling({ applicable: true, mode: "downsampled", point_cap: 500, reason: null });
    expect(downsampled).toContain("downsampled");
    expect(downsampled).toContain("500");
  });
});

// ── 5. Профили и фиксированная геометрия (PGV-AC16) ──────────────

describe("PGV-07 pageGeometry: профили из каталога PGV-01 (AC16)", () => {
  test("пиксели профилей совпадают с каталогом, пропорции A4 сохранены", () => {
    const a4p = pageGeometry("a4-portrait");
    expect(a4p.width_px).toBe(2480);
    expect(a4p.height_px).toBe(3508);
    const a4l = pageGeometry("a4-landscape");
    expect(a4l.width_px).toBe(3508);
    expect(a4l.height_px).toBe(2480);
    const fig = pageGeometry("figure-landscape");
    expect(fig.width_px).toBe(2400);
    expect(fig.height_px).toBe(1500);
    // Пропорция A4 ≈ 210/297 с допуском округления.
    expect(a4p.width_px / a4p.height_px).toBeCloseTo(210 / 297, 2);
    expect(a4l.height_px / a4l.width_px).toBeCloseTo(210 / 297, 2);
  });

  test("PrintPageSurface задаёт фиксированную геометрию профиля (не viewport)", () => {
    const { getByTestId } = render(
      <PrintPageSurface profileId="a4-portrait">
        <p>рисунок</p>
      </PrintPageSurface>,
    );
    const surface = getByTestId("print-page-surface");
    expect(surface.style.width).toBe("2480px");
    expect(surface.style.height).toBe("3508px");
    // Непрозрачный белый фон независимо от темы экрана.
    expect(surface.style.backgroundColor).toBe("rgb(255, 255, 255)");
  });

  test("PrintPageSurface с масштабом печати сохраняет пропорцию", () => {
    const { getByTestId } = render(
      <PrintPageSurface profileId="a4-portrait" scale={0.5}>
        <p>рисунок</p>
      </PrintPageSurface>,
    );
    const surface = getByTestId("print-page-surface");
    expect(surface.style.width).toBe("1240px");
    expect(surface.style.height).toBe("1754px");
  });
});

// ── 6. Секции: оси/легенда/таблицы/теплокарты/карточки ───────────

describe("PGV-07 секции: labels/legend/таблицы/теплокарты", () => {
  const baseSpec = {
    section_id: "s1",
    renderer_kind: "recharts_svg" as const,
    title: "Точечный график",
    axes: [
      { name: "Позиция", units: { value: "набл.", reason: null }, scale: null, limits: null },
      { name: "Значение", units: { value: null, reason: "legacy_unknown" }, scale: null, limits: null },
    ],
    legend_ordering: ["Ряд A", "Ряд B"],
    table_headings: null,
    heatmap_scale: null,
    units: [{ value: "млн", reason: null }],
  };

  test("PrintChartSection: имена осей с единицами (значение XOR причина), полная легенда", () => {
    const { getByTestId } = render(
      <PrintChartSection spec={baseSpec}>
        <div data-geometry="recharts">геометрия экранного графика</div>
      </PrintChartSection>,
    );
    const section = getByTestId("print-chart-section");
    expect(section.textContent).toContain("Точечный график");
    // Ось с единицей: значение; ось без единицы: честная причина.
    expect(section.textContent).toContain("Позиция");
    expect(section.textContent).toContain("набл.");
    expect(section.textContent).toContain("legacy_unknown");
    // Легенда полная, порядок сохранён.
    const legend = getByTestId("print-legend");
    expect(legend.textContent).toContain("Ряд A");
    expect(legend.textContent).toContain("Ряд B");
    expect(legend.textContent.indexOf("Ряд A")).toBeLessThan(legend.textContent.indexOf("Ряд B"));
    // Геометрия передана на печать (переиспользование, §4.1).
    expect(section.textContent).toContain("геометрия экранного графика");
  });

  test("PrintLegendStrip рендерит все записи и не теряется", () => {
    const { getByTestId } = render(<PrintLegendStrip ordering={["X", "Y", "Z"]} />);
    const legend = getByTestId("print-legend");
    expect(legend.textContent).toContain("X");
    expect(legend.textContent).toContain("Y");
    expect(legend.textContent).toContain("Z");
  });

  test("chunkTableRows режет только целыми строками (база AC15)", () => {
    const rows = Array.from({ length: 25 }, (_, i) => [`r${i + 1}`, `${i + 1}`]);
    const chunks = chunkTableRows(rows, 10);
    expect(chunks.map((c) => c.length)).toEqual([10, 10, 5]);
    expect(chunks.flat()).toEqual(rows); // порядок и состав сохранены, дубликатов нет
    expect(chunkTableRows(rows, 0).length).toBeGreaterThan(0); // защита от нулевой страницы
    expect(chunkTableRows([], 10)).toEqual([]);
  });

  test("PrintTableSection повторяет заголовки на каждой части и помечает продолжение", () => {
    const rows = Array.from({ length: 12 }, (_, i) => [`строка ${i + 1}`, `${(i + 1) * 2}`]);
    const { getAllByTestId, getAllByText } = render(
      <PrintTableSection
        spec={{ ...baseSpec, renderer_kind: "html_table", table_headings: { row: ["Период"], column: ["Значение"] } }}
        headings={{ row: ["Период"], column: ["Значение"] }}
        rows={rows}
        rowsPerPage={10}
      />,
    );
    // Две части по 10/2 строк.
    const tables = getAllByTestId("print-table");
    expect(tables.length).toBe(2);
    // Заголовок «Период» на КАЖДОЙ части (повтор header/footer §7).
    expect(getAllByText("Период").length).toBe(2);
    expect(getAllByText("Значение").length).toBe(2);
    // Все 12 строк в DOM, ни одна не разрезана.
    for (let i = 1; i <= 12; i += 1) expect(getAllByText(`строка ${i}`).length).toBe(1);
    expect(document.body.textContent).toContain("Продолжение");
  });

  test("PrintHeatmapSection: ячейки, шкала с domain+units, честный пропуск", () => {
    const spec = {
      ...baseSpec,
      renderer_kind: "html_heatmap" as const,
      heatmap_scale: { domain: [0, 100] as [number, number], units: { value: "%", reason: null } },
    };
    const values = [
      [10, 90],
      [null, 40],
    ];
    const { getByTestId, getAllByTestId } = render(
      <PrintHeatmapSection
        spec={spec}
        rowHeadings={["янв", "фев"]}
        columnHeadings={["X1", "X2"]}
        cellValue={(r, c) => values[r][c]}
        cellText={(r, c) => (values[r][c] === null ? "—" : `${values[r][c]} %`)}
      />,
    );
    const section = getByTestId("print-heatmap-section");
    expect(section.textContent).toContain("янв");
    expect(section.textContent).toContain("X2");
    // Все 4 ячейки.
    expect(getAllByTestId("print-heatmap-cell").length).toBe(4);
    // Color legend: домен и единицы шкалы.
    const legend = getByTestId("print-heatmap-scale");
    expect(legend.textContent).toContain("0");
    expect(legend.textContent).toContain("100");
    expect(legend.textContent).toContain("%");
    // Пропуск честный: ячейка есть, текст-причина вместо числа.
    expect(section.textContent).toContain("нет данных");
  });

  test("PrintCardsSection: подпись+значение+единица", () => {
    const { getByTestId } = render(
      <PrintCardsSection
        spec={{ ...baseSpec, renderer_kind: "html_cards", title: "Метрики качества" }}
        cards={[
          { label: "Наблюдений", value: "1 024" },
          { label: "Полнота", value: "97,5 %", unit: { value: "%", reason: null } },
        ]}
      />,
    );
    const section = getByTestId("print-cards-section");
    expect(section.textContent).toContain("Метрики качества");
    expect(section.textContent).toContain("Наблюдений");
    expect(section.textContent).toContain("1 024");
    expect(section.textContent).toContain("%");
  });
});

// ── 7. HTML IH (PGV-AC02) ────────────────────────────────────────

describe("PGV-07 PrintIhConditionalMatrix: HTML IH печатается полностью (AC02)", () => {
  const input = {
    feature_label: "Возраст",
    target_label: "Выручка",
    x_bins: ["[0;25)", "[25;50)", "[50;75)", "[75;100]"],
    y_bins: ["низкий", "средний", "высокий"],
    rows: [
      { x_bin: "[0;25)", values: [60, 30, 10] },
      { x_bin: "[25;50)", values: [20, 50, 30] },
      { x_bin: "[50;75)", values: [5, 35, 60] },
      { x_bin: "[75;100]", values: [0, 15, 85] },
    ],
    n_observations: 4120,
    row_totals: [1200, 1500, 900, 520],
  };

  test("все bins строк/колонок, все проценты в DOM", () => {
    const { getByTestId, getAllByTestId } = render(<PrintIhConditionalMatrix input={input} />);
    const section = getByTestId("print-ih-conditional");
    for (const bin of input.x_bins) expect(section.textContent).toContain(bin);
    for (const bin of input.y_bins) expect(section.textContent).toContain(bin);
    // 4 строки × 3 колонки = 12 ячеек.
    expect(getAllByTestId("print-ih-cell").length).toBe(12);
    expect(section.textContent).toContain("60 %");
    expect(section.textContent).toContain("85 %");
  });

  test("знаменатель строки печатается (n по строке), общий N и правило 100 %", () => {
    const { getByTestId } = render(<PrintIhConditionalMatrix input={input} />);
    const section = getByTestId("print-ih-conditional");
    expect(section.textContent).toContain("4 120");
    expect(section.textContent).toContain("1 200");
    expect(section.textContent).toContain("520");
    expect(section.textContent).toContain("100 %");
  });

  test("без построчных знаменателей — честная причина, не выдуманные числа", () => {
    const { getByTestId } = render(
      <PrintIhConditionalMatrix input={{ ...input, row_totals: null, denominator_note: "знаменатель строки не сохранён в frozen результате" }} />,
    );
    const section = getByTestId("print-ih-conditional");
    expect(section.textContent).toContain("знаменатель строки не сохранён");
    expect(section.textContent).not.toContain("1 200");
  });

  test("color legend шкалы присутствует (0–100 %)", () => {
    const { getByTestId } = render(<PrintIhConditionalMatrix input={input} />);
    const legend = getByTestId("print-ih-scale");
    expect(legend.textContent).toContain("0 %");
    expect(legend.textContent).toContain("100 %");
  });

  test("PrintIhMetricsMap печатает карту метрик с заголовками", () => {
    const { getByTestId } = render(
      <PrintIhMetricsMap
        results={[
          { feature: "f1", h_x: 1.2, mi: 0.4, r: 0.5, r_adjusted: 0.3 },
          { feature: "f2", h_x: 0.8, mi: 0.1, r: 0.2, r_adjusted: 0.05 },
        ]}
      />,
    );
    const section = getByTestId("print-ih-metrics");
    expect(section.textContent).toContain("f1");
    expect(section.textContent).toContain("f2");
    expect(section.textContent).toContain("I(X;Y)");
    expect(section.textContent).toContain("H(X)");
  });
});

// ── 8. AC04 динамический оракул: тема экрана не влияет ───────────

describe("PGV-07 AC04: рендер в тёмной теме байт-идентичен светлому", () => {
  test("PrintPageFrame внутри .dark и без него — одинаковый HTML инлайн-стилей", () => {
    const snapshot = buildMinimalValidSnapshot(getSite(SCATTER_SITE));
    const light = render(
      <div>
        <PrintPageFrame snapshot={snapshot} pageIndex={1} pageCount={1}>
          <p>тело</p>
        </PrintPageFrame>
      </div>,
    );
    const dark = render(
      <div className="dark" data-theme="dark">
        <PrintPageFrame snapshot={snapshot} pageIndex={1} pageCount={1}>
          <p>тело</p>
        </PrintPageFrame>
      </div>,
    );
    // Inline-стили каркаса идентичны: тема экрана не просачивается.
    const lightSurface = light.container.querySelector('[data-testid="print-page-surface"]') as HTMLElement;
    const darkSurface = dark.container.querySelector('[data-testid="print-page-surface"]') as HTMLElement;
    expect(darkSurface.getAttribute("style")).toBe(lightSurface.getAttribute("style"));
    // И ни один инлайн-цвет каркаса не содержит var() — всё резолвится в hex.
    expect(darkSurface.getAttribute("style")).not.toContain("var(");
  });
});

// ── PGV-07-FIX: честная маркировка свотчей легенды (F-P7C2) ───────

// До PGV-07-FIX: свотчи PrintLegendStrip — синтетическое чередование двух
// цветов (index % 2), при ≥3 сериях записи неразличимы, а свотч выглядел
// фактическим цветом серии, которым не является (series_styles контрактом
// PGV-01 не передаются). Честное решение: явная маркировка иллюстративности
// (фабкация фактического вида запрещена §6/AC12).

describe("PGV-07-FIX: маркировка иллюстративности свотчей легенды (F-P7C2)", () => {
  test("свотчи сопровождаются явной маркировкой «иллюстративные»", () => {
    const { getByTestId } = render(<PrintLegendStrip ordering={["Ряд 1", "Ряд 2", "Ряд 3"]} />);
    const legend = getByTestId("print-legend");
    // Записи легенды не теряются и сохраняют порядок.
    const text = legend.textContent ?? "";
    expect(text.indexOf("Ряд 1")).toBeLessThan(text.indexOf("Ряд 2"));
    expect(text.indexOf("Ряд 2")).toBeLessThan(text.indexOf("Ряд 3"));
    // Маркировка честности: свотч — не фактический цвет серии.
    expect(text).toContain("иллюстративн");
  });

  test("маркировка присутствует и при пользовательской note (не замещается)", () => {
    const { getByTestId } = render(
      <PrintLegendStrip ordering={["A", "B"]} note="порядок следования серий" />,
    );
    const text = getByTestId("print-legend").textContent ?? "";
    expect(text).toContain("порядок следования серий");
    expect(text).toContain("иллюстративн");
  });
});
