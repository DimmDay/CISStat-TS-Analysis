/**
 * PGV-07-CERT — Class A: независимые оракулы сертификатора на СВОИХ данных.
 *
 * Namespace p7cert-* — дизъюнктен repo-корпусу поставки (printLayout.test /
 * printPassport.test / printSchema.test) и пробам (probe_findings).
 * Дизъюнкт пинится статикой U01 с анти-самотриггером (проверка только
 * packages/ui/print — не scripts/pgv07cert).
 *
 * Метод серии CERT (прецеденты PGV-00…06-CERT): собственные данные иной
 * формы/масштаба, прегистрированные ожидания, без импорта repo-фикстур.
 * Каналы: этот файл (ORACLE) + repo-корпус поставки (REPO, 48 тестов).
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import React from "react";
import { render } from "@testing-library/react";

// ── Модули поставки (аудируемый объект) ──────────────────────────
import {
  PRINT_FONT_STACK,
  PRINT_PALETTE,
  PRINT_STATUS_MARKS,
  PRINT_THEME_VERSION,
  PRINT_TYPE_SCALE,
  isHexColor,
  resolveChartVarLight,
  resolveVarStringLight,
} from "../../packages/ui/print/printTheme";
import {
  describeSampling,
  formatNumberRu,
  formatPrintTime,
  formatUnit,
  pageGeometry,
  shortRef,
  PrintLegendStrip,
  PrintNotes,
  PrintPageFrame,
  PrintPageSurface,
  PrintSectionTitle,
} from "../../packages/ui/print/printLayout";
import {
  chunkTableRows,
  describeAxis,
  heatColor,
  PrintCardsSection,
  PrintChartSection,
  PrintHeatmapSection,
  PrintTableSection,
} from "../../packages/ui/print/printSections";
import {
  PrintIhConditionalMatrix,
  PrintIhMetricsMap,
} from "../../packages/ui/print/printIh";
import {
  flattenPassportGroup,
  KNOWN_PASSPORT_GROUPS,
  KNOWN_PASSPORT_SCHEMA_VERSIONS,
  PrintPassportPage,
  type PrintPassportRecord,
} from "../../packages/ui/print/printPassport";
import {
  PASSPORT_COMPARISON_SCHEMA_VERSION,
  PrintPassportComparisonPage,
  type PrintComparisonSnapshot,
} from "../../packages/ui/print/printComparison";
import * as printBarrel from "../../packages/ui/print";
// ── Субстрат (PGV-01/PGV-00, не мутируется) ─────────────────────
import { buildMinimalValidSnapshot, PARAMETER_ORIGINS } from "../../packages/ui/print/printSchema";
import { CHART_VARS_LIGHT } from "../../packages/ui/lib/chartVars";
import { VISUAL_SITE_REGISTRY, type VisualSiteRecord } from "../../packages/ui/lib/visualExportRegistry";

// ── Собственные сайты сертификатора (иная форма, чем repo) ───────
function p7site(viewId: string): VisualSiteRecord {
  const s = VISUAL_SITE_REGISTRY.find((x) => x.view_id === viewId);
  if (!s) throw new Error(`site not found: ${viewId}`);
  return s;
}
const MY_CHART_SITE = "validation.data_types.matrix"; // html_heatmap research (реальный site реестра)
const MY_PANEL_SITE = "forecasting.forecast.panel_chart"; // panel
const MY_CHART2 = "eda.feature_select.matrix"; // html_table/matrica research

// ═════════════════════════════════════════════════════════════════
// U-блок: контрактные пины сертификатора (не зависят от данных)
// ═════════════════════════════════════════════════════════════════

describe("p7cert U: контракт и границы корпуса", () => {
  test("U01 дизъюнкт namespace: p7cert не встречается в print-модулях (анти-самотриггер: проверяем только packages/ui/print)", () => {
    const sources = ["printTheme.ts", "printLayout.tsx", "printSections.tsx", "printIh.tsx", "printPassport.tsx", "printComparison.tsx", "index.ts", "printLayout.test.tsx", "printPassport.test.tsx"];
    for (const f of sources) {
      const src = readFileSync(path.join(__dirname, "../../packages/ui/print", f), "utf8");
      expect(src.includes("p7cert")).toBe(false);
    }
  });

  test("U02 версии контрактов print-бандла pinned", () => {
    expect(PRINT_THEME_VERSION).toBe("pgv.print_theme/1");
    expect(PASSPORT_COMPARISON_SCHEMA_VERSION).toBe("pgv.passport_comparison/1");
  });

  test("U03 barrel экспортирует все 6 модулей (состав пинуется ключами)", () => {
    const keys = Object.keys(printBarrel as Record<string, unknown>);
    for (const required of ["PRINT_PALETTE", "PrintPageFrame", "PrintPageSurface", "chunkTableRows", "heatColor", "PrintIhConditionalMatrix", "PrintPassportPage", "PrintPassportComparisonPage", "resolveChartVarLight"]) {
      expect(keys).toContain(required);
    }
  });

  test("U04 PRINT_PALETTE: собственная транскрипция ключевых светлых значений из globals.css :root (chart-brand/chart-blue/chart-grid/chart-border)", () => {
    // Независимая сверка с фактическим :root (не через CHART_VARS_LIGHT —
    // напрямую из globals.css), прецедент зеркала ForecastExportMenu.vars.
    const css = readFileSync(path.join(__dirname, "../../packages/ui/globals.css"), "utf8");
    const rootBlock = css.slice(css.indexOf(":root"), css.indexOf("}", css.indexOf(":root")));
    const expectVar = (name: string, hex: string) => {
      expect(rootBlock).toContain(`--${name}: ${hex}`);
    };
    expectVar("chart-brand", "#2E3192");
    expectVar("chart-blue", "#2563EB");
    expectVar("chart-grid", "#F0F0F0");
    expectVar("chart-border", "#E5E5E5");
    // Палитра печати несёт ТЕ ЖЕ фактические значения (не придуманные).
    expect(PRINT_PALETTE.accent).toBe("#2E3192");
    expect(PRINT_PALETTE.series_blue).toBe("#2563EB");
    expect(PRINT_PALETTE.grid).toBe("#F0F0F0");
    expect(PRINT_PALETTE.border).toBe("#E5E5E5");
  });

  test("U05 статусные цвета печати затемнены относительно экранной карты (честное решение контраста, не копия)", () => {
    for (const key of ["status-success", "status-error", "status-warning"]) {
      const screen = CHART_VARS_LIGHT[key];
      const printedKey = key.replace("status-", "status_") as keyof typeof PRINT_PALETTE;
      const printed = PRINT_PALETTE[printedKey];
      expect(isHexColor(printed)).toBe(true);
      // Затемнение: яркость печатного цвета ниже экранного (контраст на белом).
      const lum = (hex: string) => {
        const n = parseInt(hex.slice(1), 16);
        return 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
      };
      expect(lum(printed)).toBeLessThan(lum(screen));
    }
  });

  test("U06 ORIGIN_LABELS каркаса покрывают PARAMETER_ORIGINS схемы PGV-01", () => {
    // PARAMETER_ORIGINS — readonly-массив значений origin (схема PGV-01).
    expect(PARAMETER_ORIGINS).toContain("producer_freeze");
    expect(PARAMETER_ORIGINS).toContain("producer_first_export");
    // Свои данные каркаса: оба origin получают человекочитаемую подпись.
    const snap = buildMinimalValidSnapshot(p7site(MY_CHART2));
    for (const origin of PARAMETER_ORIGINS) {
      const withOrigin = { ...snap, method: { ...snap.method, origin } };
      const { getByTestId, unmount } = render(<PrintPageFrame snapshot={withOrigin} pageIndex={1} pageCount={1} />);
      expect(getByTestId("print-footer").textContent).toContain(origin);
      unmount();
    }
  });

  test("U07 шрифтовой стек печати pinned и без web-ссылок", () => {
    expect(PRINT_FONT_STACK).toContain("DejaVu Sans");
    expect(PRINT_FONT_STACK).not.toMatch(/https?:/);
    expect(PRINT_FONT_STACK.endsWith("sans-serif")).toBe(true);
  });

  test("U08 KNOWN_PASSPORT_SCHEMA_VERSIONS: allowlist ровно 1.0–1.2 (документация движка сравнения)", () => {
    expect(KNOWN_PASSPORT_SCHEMA_VERSIONS).toEqual(["passport/1.0", "passport/1.1", "passport/1.2"]);
  });

  test("U09 статический оракул сертификатора: дополнительные запрещённые паттерны (сеть печати не отсоединена от repo-корпуса)", () => {
    const sources = ["printTheme.ts", "printLayout.tsx", "printSections.tsx", "printIh.tsx", "printPassport.tsx", "printComparison.tsx"];
    for (const f of sources) {
      const src = readFileSync(path.join(__dirname, "../../packages/ui/print", f), "utf8");
      // Свои паттерны (repo-оракул не дублируется):
      expect(src).not.toMatch(/toLocaleString|toLocaleDateString|toLocaleTimeString|Intl\./); // лоکلезависимость
      expect(src).not.toMatch(/dangerouslySetInnerHTML|innerHTML/);
      expect(src).not.toMatch(/window\.open|target:\s*["']_blank/);
      expect(src).not.toMatch(/localStorage|sessionStorage|document\.cookie/);
      expect(src).not.toMatch(/process\.env/);
    }
  });

  test("U10 бандл не смонтирован в продуктовый граф (граница PGV-07; экраны — PGV-10…12)", () => {
    // components/ и apps/ не импортируют print-бандл (кроме самого print/ и тестов).
    for (const f of ["packages/ui/components/ForecastChart.tsx", "packages/ui/components/DatasetPassportPanel.tsx", "packages/ui/index.ts"]) {
      const src = readFileSync(path.join(__dirname, "../..", f), "utf8");
      expect(src.includes('/print"')).toBe(false);
      expect(src.includes("./print")).toBe(false);
    }
  });
});

// ═════════════════════════════════════════════════════════════════
// A-блок: оракулы на СВОИХ данных (иная форма/масштаб)
// ═════════════════════════════════════════════════════════════════

describe("p7cert A1: форматтеры — собственные числа/времена (детерминизм и честность)", () => {
  test("A1.1 formatNumberRu: крупный масштаб, шесть знаков, ноль, целое", () => {
    expect(formatNumberRu(1234567.891011, 6)).toBe("1 234 567,891011");
    expect(formatNumberRu(0, 1)).toBe("0");
    expect(formatNumberRu(42, 1)).toBe("42");
    expect(formatNumberRu(0.5, 3)).toBe("0,5");
  });

  test("A1.2 formatNumberRu: нечисловое — честный прочерк (не 0)", () => {
    expect(formatNumberRu(Number.NaN)).toBe("—");
    expect(formatNumberRu(Number.POSITIVE_INFINITY)).toBe("—");
    expect(formatNumberRu(undefined)).toBe("—");
  });

  test("A1.3 formatPrintTime: короткая ISO без секунд печатается, мусор — прочерк/причина", () => {
    expect(formatPrintTime("2026-01-02T03:04", null, "UTC")).toBe("2026-01-02 03:04 UTC");
    expect(formatPrintTime("", "fixture_missing")).toBe("неизвестно (fixture_missing)");
    expect(formatPrintTime("мусор", null)).toBe("—");
  });

  test("A1.4 formatPrintTime: причина приоритетнее прочерка только при отсутствии ISO", () => {
    expect(formatPrintTime(undefined, "producer_not_reported")).toContain("producer_not_reported");
    expect(formatPrintTime("2026-01-02T03:04:00Z", "не-важно", "UTC")).toBe("2026-01-02 03:04 UTC");
  });

  test("A1.5 formatUnit: собственные единицы и причина dimensionless", () => {
    expect(formatUnit({ value: "тыс. руб.", reason: null })).toBe("тыс. руб.");
    expect(formatUnit({ value: null, reason: "index_dimensionless" })).toBe("без единицы (index_dimensionless)");
    expect(formatUnit({ value: null, reason: null })).toBe("—");
  });

  test("A1.6 shortRef: keep=1 — минимум; ref ровно keep — без многоточия", () => {
    expect(shortRef("abcdefghijk", 1)).toBe("a…");
    expect(shortRef("abcdefghij", 10)).toBe("abcdefghij");
    expect(shortRef("abcdefghija", 10)).toBe("abcdefghij…");
    expect(shortRef("", 10)).toBe("—");
  });

  test("A1.7 describeSampling: все режимы различимы на своих данных (AC08)", () => {
    expect(describeSampling({ applicable: false, mode: null, point_cap: null, reason: "нет ряда" })).toBe("сэмплинг не применим: нет ряда");
    expect(describeSampling({ applicable: false, mode: null, point_cap: null, reason: null })).toBe("сэмплинг не применим");
    expect(describeSampling({ applicable: true, mode: "windowed", point_cap: null, reason: null })).toContain("windowed");
    expect(describeSampling({ applicable: true, mode: "truncated", point_cap: 12, reason: "flat_cap" })).toBe("сэмплинг: truncated, потолок 12 точек, причина: flat_cap");
  });

  test("A1.8 describeAxis: своя ось — имя с единицей и честная ось без единицы", () => {
    expect(describeAxis({ name: "Лаг", units: { value: "мес.", reason: null }, scale: null, limits: null })).toBe("Лаг (мес.)");
    expect(describeAxis({ name: "ACF", units: { value: null, reason: "dimensionless" }, scale: null, limits: null })).toContain("dimensionless");
  });
});

describe("p7cert A2: геометрия профилей и поверхность (AC16) на своих данных", () => {
  test("A2.1 все три профиля; неизвестный — явный отказ (не молчаливый viewport)", () => {
    const fig = pageGeometry("figure-landscape");
    expect(fig.ppi).toBe(300);
    expect(fig.aspect).toBeCloseTo(2400 / 1500, 6);
    const a4l = pageGeometry("a4-landscape");
    expect(a4l.aspect).toBeCloseTo(3508 / 2480, 6);
    expect(() => pageGeometry("нет-профиля" as never)).toThrow();
  });

  test("A2.2 PrintPageSurface: scale=0.25 — четверть пикселей, фон белый непрозрачный", () => {
    const { getByTestId } = render(
      <PrintPageSurface profileId="figure-landscape" scale={0.25} testId="p7cert-surface">
        <p>рисунок</p>
      </PrintPageSurface>,
    );
    const surface = getByTestId("p7cert-surface");
    expect(surface.style.width).toBe("600px");
    expect(surface.style.height).toBe("375px");
    expect(surface.style.backgroundColor).toBe("rgb(255, 255, 255)");
    expect(surface.style.overflow).toBe("hidden");
  });

  test("A2.3 PrintPageSurface: scale по умолчанию 1 — полный профиль A4", () => {
    const { getByTestId } = render(<PrintPageSurface profileId="a4-landscape" testId="p7cert-surface-full" />);
    expect(getByTestId("p7cert-surface-full").style.width).toBe("3508px");
  });
});

describe("p7cert A3: каркас страницы (AC05) на своём research-сайте", () => {
  function myFrame(siteId: string, detail: "compact" | "expanded" = "compact") {
    const snapshot = buildMinimalValidSnapshot(p7site(siteId), { detailLevel: detail });
    return { snapshot, ...render(<PrintPageFrame snapshot={snapshot} pageIndex={2} pageCount={5} source="EDA / Корреляции" />) };
  }

  test("A3.1 header: вид/источник (явный source приоритетнее деривации)/target/даты/режим", () => {
    const { snapshot, getByTestId } = myFrame(MY_CHART_SITE);
    const header = getByTestId("print-header").textContent ?? "";
    expect(header).toContain(snapshot.display.title);
    expect(header).toContain(MY_CHART_SITE);
    expect(header).toContain("EDA / Корреляции");
    expect(header).toContain("target_column");
    expect(header).toContain("2026-10-27 00:00 UTC");
    expect(header).toContain("univariate");
  });

  test("A3.2 footer: метод+origin, версия данных, короткий результат, профиль, номер страницы", () => {
    const { snapshot, getByTestId } = myFrame(MY_CHART_SITE);
    const footer = getByTestId("print-footer").textContent ?? "";
    expect(footer).toContain("fixture");
    expect(footer).toContain("producer_freeze");
    expect(footer).toContain("фиксация producer'а");
    expect(footer).toContain(shortRef(snapshot.result.result_ref));
    expect(footer).toContain("Стр. 2 из 5");
    expect(footer).toContain("light-print");
  });

  test("A3.3 панельный сайт: entity_id печатается; univariate — нет (AC14-дух)", () => {
    const panel = render(<PrintPageFrame snapshot={buildMinimalValidSnapshot(p7site(MY_PANEL_SITE))} pageIndex={1} pageCount={1} />);
    expect((panel.container.querySelector('[data-testid="print-header"]')?.textContent ?? "")).toContain("entity_id");
    const single = render(<PrintPageFrame snapshot={buildMinimalValidSnapshot(p7site(MY_CHART_SITE))} pageIndex={1} pageCount={1} />);
    expect((single.container.querySelector('[data-testid="print-header"]')?.textContent ?? "")).not.toContain("entity_id");
  });

  test("A3.4 reused-checkpoint строка в header при checkpointReused", () => {
    const snapshot = buildMinimalValidSnapshot(p7site(MY_CHART_SITE), { checkpointReused: true });
    const { getByTestId } = render(<PrintPageFrame snapshot={snapshot} pageIndex={1} pageCount={1} />);
    const header = getByTestId("print-header").textContent ?? "";
    expect(header).toContain("checkpoint");
    expect(header).toContain("reused");
    expect(header).toContain("2026-10-27 12:00 UTC");
  });

  test("A3.5 kill-switch анимаций присутствует и охватывает все элементы (пин текста)", () => {
    const { container } = myFrame(MY_CHART_SITE);
    const style = container.querySelector("style")?.textContent ?? "";
    expect(style).toContain("animation: none");
    expect(style).toContain("transition: none");
    expect(style).toContain("!important");
  });

  test("A3.6 warnings печатаются PrintNotes (свои предупреждения, не repo-строки)", () => {
    const snapshot = buildMinimalValidSnapshot(p7site(MY_CHART_SITE));
    snapshot.warnings = ["p7cert-warning: пример устаревания", "p7cert-warning-2: частичная сетка"];
    const { getByTestId } = render(<PrintPageFrame snapshot={snapshot} pageIndex={1} pageCount={1} />);
    const notes = getByTestId("print-warnings").textContent ?? "";
    expect(notes).toContain("p7cert-warning: пример устаревания");
    expect(notes).toContain("p7cert-warning-2");
  });

  test("A3.7 PrintNotes пустой список — ничего не рендерит (data-testid отсутствует)", () => {
    const { container } = render(<PrintNotes items={[]} />);
    expect(container.querySelector('[data-testid="print-warnings"]')).toBeNull();
  });
});

describe("p7cert A4: секции на своих данных", () => {
  const mySpec = {
    section_id: "p7cert-s1",
    renderer_kind: "recharts_svg" as const,
    title: "Матрица корреляций (свои данные)",
    axes: [
      { name: "Фактор", units: { value: "категория", reason: null }, scale: null, limits: null },
      { name: "Коэффициент", units: { value: null, reason: "dimensionless" }, scale: null, limits: null },
    ],
    legend_ordering: ["Фактор 1", "Фактор 2", "Фактор 3"],
    table_headings: null,
    heatmap_scale: null,
    units: [],
  };

  test("A4.1 PrintChartSection: оси/легенда 3 записи в порядке/геометрия children", () => {
    const { getByTestId, getByText } = render(
      <PrintChartSection spec={mySpec}>
        <div data-p7cert-geometry="1">научная геометрия</div>
      </PrintChartSection>,
    );
    const section = getByTestId("print-chart-section").textContent ?? "";
    expect(section).toContain("Фактор (категория)");
    expect(section).toContain("dimensionless");
    const legend = getByTestId("print-legend").textContent ?? "";
    expect(legend.indexOf("Фактор 1")).toBeLessThan(legend.indexOf("Фактор 2"));
    expect(legend.indexOf("Фактор 2")).toBeLessThan(legend.indexOf("Фактор 3"));
    expect(getByText("научная геометрия")).not.toBeNull();
  });

  test("A4.2 chunkTableRows: свои размеры — 7 строк по 3, дробный размер floor, пустой вход, размер 1", () => {
    const rows = Array.from({ length: 7 }, (_, i) => [`стр-${i}`, `${i}`]);
    const chunks = chunkTableRows(rows, 3);
    expect(chunks.map((c) => c.length)).toEqual([3, 3, 1]);
    expect(chunkTableRows(rows, 3.9).map((c) => c.length)).toEqual([3, 3, 1]); // floor(3.9)=3
    expect(chunkTableRows(rows, 100).length).toBe(1);
    expect(chunkTableRows([], 5)).toEqual([]);
    // Ремутация M16: rowsPerPage=1 — каждая строка отдельной частью (пин floor-минимума).
    expect(chunkTableRows(rows, 1).map((c) => c.length)).toEqual([1, 1, 1, 1, 1, 1, 1]);
    // Плоское восстановление без потерь и дубликатов.
    const flat = chunks.flat();
    expect(flat.length).toBe(7);
    expect(new Set(flat.map((r) => r[0])).size).toBe(7);
  });

  test("A4.3 PrintTableSection: 7 строк по 3 на части — 3 таблицы, заголовки ×3, продолжение ×2, все строки ровно по разу", () => {
    const rows = Array.from({ length: 7 }, (_, i) => [`p7cert-стр-${i + 1}`, `${(i + 1) * 10}`]);
    const { getAllByTestId, getAllByText } = render(
      <PrintTableSection
        spec={{ ...mySpec, renderer_kind: "html_table" }}
        headings={{ row: ["Позиция"], column: ["Значение"] }}
        rows={rows}
        rowsPerPage={3}
      />,
    );
    expect(getAllByTestId("print-table").length).toBe(3);
    expect(getAllByText("Позиция").length).toBe(3);
    expect(getAllByText("Значение").length).toBe(3);
    for (let i = 1; i <= 7; i += 1) expect(getAllByText(`p7cert-стр-${i}`).length).toBe(1);
    expect(getAllByText(/Продолжение/).length).toBe(2);
  });

  test("A4.4 PrintTableSection: единицы секции печатаются в подписи", () => {
    const { container } = render(
      <PrintTableSection
        spec={{ ...mySpec, renderer_kind: "html_table", units: [{ value: "тыс. тонн", reason: null }] }}
        headings={{ row: ["Месяц"], column: ["Объём"] }}
        rows={[["янв", "100"]]}
      />,
    );
    expect(container.textContent).toContain("Единицы: тыс. тонн");
  });

  test("A4.5 heatColor: интерполяция середины домена, отрицательный домен, строгая монотонность синевы", () => {
    const mid = heatColor(50, [0, 100]);
    expect(mid).toBe("rgb(146, 177, 245)"); // (255+37)/2, (255+99)/2, (255+235)/2
    const neg = heatColor(0, [-10, 10]);
    expect(neg).toBe("rgb(146, 177, 245)");
    const q1 = heatColor(25, [0, 100]);
    const q3 = heatColor(75, [0, 100]);
    // Интерполяция белый(255,255,255)→series_blue(37,99,235): насыщенность растёт
    // по падению RED-канала; монотонность проверяем по RED (255→37).
    const red = (c: string) => parseInt(c.replace(/[^\d]/g, " ").trim().split(/\s+/)[0], 10);
    expect(red(q1)).toBeGreaterThan(red(mid));
    expect(red(mid)).toBeGreaterThan(red(q3));
    // Ремутация M19: значения вне домена зажаты (clamp, не экстраполяция).
    expect(heatColor(-10, [0, 100])).toBe("rgb(255, 255, 255)");
    expect(heatColor(500, [0, 100])).toBe("rgb(37, 99, 235)");
  });

  test("A4.6 PrintHeatmapSection: своя матрица 3×4, 2 пропуска, шкала с domain/units, все ячейки", () => {
    const spec = {
      ...mySpec,
      renderer_kind: "html_heatmap" as const,
      heatmap_scale: { domain: [-1, 1] as [number, number], units: { value: "r", reason: null } },
    };
    const values: (number | null)[][] = [
      [1, -1, 0, null],
      [0.5, null, -0.5, 0.25],
      [null, null, null, null],
    ];
    const { getByTestId, getAllByTestId } = render(
      <PrintHeatmapSection
        spec={spec}
        rowHeadings={["А", "Б", "В"]}
        columnHeadings={["x1", "x2", "x3", "x4"]}
        cellValue={(r, c) => values[r][c]}
        cellText={(r, c) => `v=${values[r][c]}`}
      />,
    );
    expect(getAllByTestId("print-heatmap-cell").length).toBe(12);
    const section = getByTestId("print-heatmap-section").textContent ?? "";
    for (const h of ["А", "Б", "В", "x1", "x4"]) expect(section).toContain(h);
    expect(section).toContain("нет данных");
    const scale = getByTestId("print-heatmap-scale").textContent ?? "";
    expect(scale).toContain("-1");
    expect(scale).toContain("1");
    expect(scale).toContain("r");
  });

  test("A4.7 PrintHeatmapSection: домен по умолчанию [0,1] при null-scale (не фабкация фактического домена)", () => {
    const spec = { ...mySpec, renderer_kind: "html_heatmap" as const, heatmap_scale: null };
    const { getByTestId } = render(
      <PrintHeatmapSection
        spec={spec}
        rowHeadings={["Р"]}
        columnHeadings={["c1"]}
        cellValue={() => 0.5}
        cellText={() => "0,5"}
      />,
    );
    const scale = getByTestId("print-heatmap-scale").textContent ?? "";
    expect(scale).toContain("0");
    expect(scale).toContain("1");
  });

  test("A4.8 PrintCardsSection: свои карточки с единицей-причиной", () => {
    const { getByTestId } = render(
      <PrintCardsSection
        spec={{ ...mySpec, renderer_kind: "html_cards", title: "p7cert-метрики" }}
        cards={[
          { label: "R²", value: "0,8623" },
          { label: "Лаги", value: "24", unit: { value: null, reason: "count_dimensionless" } },
        ]}
      />,
    );
    const text = getByTestId("print-cards-section").textContent ?? "";
    expect(text).toContain("p7cert-метрики");
    expect(text).toContain("0,8623");
    expect(text).toContain("count_dimensionless");
  });
});

describe("p7cert A5: HTML IH на своих данных (AC02)", () => {
  const ih = {
    feature_label: "Сезон",
    target_label: "Продажи",
    x_bins: ["зима", "весна", "лето", "осень", "межсезонье"],
    y_bins: ["низкие", "высокие"],
    rows: [
      { x_bin: "зима", values: [25, 75] },
      { x_bin: "весна", values: [50, 50] },
      { x_bin: "лето", values: [90, 10] },
      { x_bin: "осень", values: [33.3, 66.7] },
      { x_bin: "межсезонье", values: [60, 40] },
    ],
    n_observations: 9876,
    row_totals: [1200, 2000, 500, 3000, 2176],
  };

  test("A5.1 все 5×2 ячеек, свои проценты, знаменатели строк, общий N, правило строки", () => {
    const { getByTestId, getAllByTestId } = render(<PrintIhConditionalMatrix input={ih} />);
    expect(getAllByTestId("print-ih-cell").length).toBe(10);
    const section = getByTestId("print-ih-conditional").textContent ?? "";
    for (const bin of ih.x_bins) expect(section).toContain(bin);
    for (const bin of ih.y_bins) expect(section).toContain(bin);
    expect(section).toContain("25 %");
    expect(section).toContain("90 %");
    expect(section).toContain("33,3 %");
    expect(section).toContain("9 876");
    expect(section).toContain("3 000");
    expect(section).toContain("2 176");
    // Ремутация M24: правило строки печатается явно (не только legend шкалы).
    expect(section).toContain("суммируется до 100 %");
  });

  test("A5.2 частичные row_totals (null в середине) — печатается прочерк в этой строке, остальные — числа", () => {
    const { container } = render(<PrintIhConditionalMatrix input={{ ...ih, row_totals: [1200, null, 500, 3000, 2176] }} />);
    const text = container.textContent ?? "";
    expect(text).toContain("1 200");
    expect(text).toContain("500");
    // Строка с null — прочерк (formatNumberRu(null)); причина отсутствует, т.к. массив есть.
    expect(text).not.toContain("не сохранён");
  });

  test("A5.3 row_totals короче rows — недостающие строки: прочерк, без фабкации", () => {
    const { container } = render(<PrintIhConditionalMatrix input={{ ...ih, row_totals: [1200] }} />);
    const text = container.textContent ?? "";
    expect(text).toContain("1 200");
    expect(text).not.toContain("2 176"); // 2176 не печатается (нет факта)
    expect(text).toContain("9 876");
  });

  test("A5.4 denom note честно печатается при row_totals=null", () => {
    const { container } = render(
      <PrintIhConditionalMatrix input={{ ...ih, row_totals: null, denominator_note: "p7cert-причина отсутствия знаменателей" }} />,
    );
    expect(container.textContent).toContain("p7cert-причина отсутствия знаменателей");
  });

  test("A5.5 цветовая шкала 0–100 % с легендой", () => {
    const { getByTestId } = render(<PrintIhConditionalMatrix input={ih} />);
    const scale = getByTestId("print-ih-scale").textContent ?? "";
    expect(scale).toContain("0 %");
    expect(scale).toContain("100 %");
    expect(scale).toContain("доля строки");
  });

  test("A5.6 PrintIhMetricsMap: свои метрики в ru-формате 4 знаков", () => {
    const { getByTestId } = render(
      <PrintIhMetricsMap
        results={[
          { feature: "p7cert-фактор", h_x: 2.321928, mi: 0.811278, r: 0.35, r_adjusted: 0.345678 },
        ]}
      />,
    );
    const text = getByTestId("print-ih-metrics").textContent ?? "";
    expect(text).toContain("p7cert-фактор");
    expect(text).toContain("2,3219");
    expect(text).toContain("0,3457");
  });
});

// ── Паспорт: собственная запись иной формы ───────────────────────

function p7record(overrides: Partial<PrintPassportRecord> = {}): PrintPassportRecord {
  return {
    schema_version: "pgv.passport_history/1",
    snapshot_ref: "artifact:passport:p7snap-0001",
    session_snapshot_id: "p7snap-0001",
    artifact_id: "artifact:passport:p7snap-0001",
    stage: "modeling_entry",
    universe: "single",
    content_status: "present",
    content_gap_reason: null,
    passport: {
      basic_stats: { n: 1234, mean: -12.75, std: 8.125, min: -40, max: 60 },
      freq: { value: "MS" },
      stationarity: { value: 0.0121, is_stationary: false },
      determinism: { value: 0.995 },
      autocorrelation: { value: 0.42, is_white_noise: false, is_ok: false, tested_lag: 12, applicable: true },
      normality: { value: 999.5 },
      trend: { direction: "down", slope: -3.25 },
      seasonality: { strength: 0.81, is_seasonal: true, period: 12, applicable: true },
      hurst: { value: 0.39 },
      correlations: { top3: { lag_1: 0.81, lag_2: 0.6, lag_3: 0.47 } },
      fft: { dominant_periods: [12, 6, 4], applicable: true },
      wavelet: { applicable: false, reason: "ряд короче 32 точек" },
      p7cert_custom_group: { metric_a: 1.5, metric_b: "текст" },
    },
    target_column: "value_rub",
    date_column: "period_dt",
    context_id: "ctx-p7cert-777",
    data_revision: "rev-p7cert-3",
    captured_at: "2026-10-28T14:30:00Z",
    created_at: "2026-10-28T14:30:02Z",
    fingerprint: null,
    fingerprint_reason: "legacy_unknown",
    source_hash: "b".repeat(64),
    source_hash_reason: null,
    passport_schema_version: "passport/1.2",
    passport_schema_version_reason: null,
    calculation_version: "calc-p7cert-1",
    calculation_version_reason: null,
    ...overrides,
  };
}

describe("p7cert A6: печатный паспорт на своих данных (§8)", () => {
  test("A6.1 все 12 известных групп + неизвестная группа по ключу; ничего не выброшено; отсутствующие группы НЕ фабкуются", () => {
    const { getByTestId } = render(<PrintPassportPage record={p7record()} pageIndex={1} pageCount={2} />);
    const text = getByTestId("print-passport-page").textContent ?? "";
    for (const g of KNOWN_PASSPORT_GROUPS) expect(text).toContain(g.label);
    expect(text).toContain("p7cert_custom_group");
    expect(text).toContain("metric_a");
    expect(text).toContain("1,5");
    // Ремутация M25: группа без факта в записи — заголовок/секция не печатаются.
    const stripped = p7record();
    const passport = { ...stripped.passport } as Record<string, unknown>;
    delete passport.seasonality;
    delete passport.hurst;
    const partial = render(<PrintPassportPage record={{ ...stripped, passport }} pageIndex={1} pageCount={1} />);
    const ptext = (partial.container.querySelector('[data-testid="print-passport-page"]')?.textContent ?? "");
    expect(ptext).not.toContain("Сезонность");
    expect(ptext).not.toContain("Показатель Хёрста");
    expect(ptext).toContain("Тренд"); // присутствующие остались
  });

  test("A6.2 реальные формы данных паспорта (applicable:true) разворачиваются по полям", () => {
    const { getByTestId } = render(<PrintPassportPage record={p7record()} pageIndex={1} pageCount={2} />);
    const text = getByTestId("print-passport-page").textContent ?? "";
    expect(text).not.toContain("[object Object]"); // нет фабкации объектом
    expect(text).toContain("0,42"); // autocorrelation.value
    expect(text).toContain("12"); // tested_lag
    expect(text).toContain("0,81"); // seasonality.strength / lag_1
    expect(text).toContain("12; 6; 4"); // fft.dominant_periods (массив — '; ' join)
  });

  test("A6.3 особые случаи схемы: направление словами, стационарность текстом; group-level applicable:false — reason виден честно (фабкации нет)", () => {
    const { getByTestId } = render(<PrintPassportPage record={p7record()} pageIndex={1} pageCount={2} />);
    const text = getByTestId("print-passport-page").textContent ?? "";
    expect(text).toContain("нисходящий");
    expect(text).toContain("нестационарен");
    // Группа с applicable:false: reason печатается (нечего не выдумывается; см. Class B F-P7C3 —
    // заявленная в доке семантика «не применимо: …» — мёртвая ветка).
    expect(text).toContain("ряд короче 32 точек");
  });

  test("A6.4 XOR-честность: fingerprint отсутствует — причина legacy_unknown, не выдуманный хэш", () => {
    const { getByTestId } = render(<PrintPassportPage record={p7record()} pageIndex={1} pageCount={2} />);
    const text = getByTestId("print-passport-page").textContent ?? "";
    expect(text).toContain("legacy_unknown");
    expect(text).not.toContain("ffffffff");
    expect(text).toContain("b".repeat(64)); // source_hash присутствует AS-IS
  });

  test("A6.5 провенанс полный: этап/снимок/время/context/revision/schema/calculation", () => {
    const { getByTestId } = render(<PrintPassportPage record={p7record()} pageIndex={1} pageCount={2} />);
    const text = getByTestId("print-passport-page").textContent ?? "";
    for (const token of ["modeling_entry", "p7snap-0001", "2026-10-28 14:30", "ctx-p7cert-777", "rev-p7cert-3", "passport/1.2", "calc-p7cert-1", "value_rub", "period_dt"]) {
      expect(text).toContain(token);
    }
  });

  test("A6.6 content-гэп: баннер с причиной, паспортных таблиц нет (фабкация запрещена)", () => {
    const { getByTestId, queryByTestId } = render(
      <PrintPassportPage record={p7record({ content_status: "corrupt", content_gap_reason: "p7cert-integrity", passport: null })} pageIndex={1} pageCount={1} />,
    );
    expect(getByTestId("print-passport-content-gap").textContent).toContain("p7cert-integrity");
    expect(queryByTestId("print-passport-groups")).toBeNull();
  });

  test("A6.7 unsupported_schema: passport/2.0 — баннер; известная 1.2 — без баннера", () => {
    const a = render(<PrintPassportPage record={p7record({ passport_schema_version: "passport/2.0" })} pageIndex={1} pageCount={1} />);
    expect((a.container.querySelector('[data-testid="print-passport-unsupported-schema"]')?.textContent ?? "")).toContain("passport/2.0");
    const b = render(<PrintPassportPage record={p7record()} pageIndex={1} pageCount={1} />);
    expect(b.container.querySelector('[data-testid="print-passport-unsupported-schema"]')).toBeNull();
  });

  test("A6.8 схема отсутствует (legacy_unknown) — баннер unsupported_schema + причина в провенансе + группы печатаются как есть", () => {
    const { getByTestId } = render(
      <PrintPassportPage record={p7record({ passport_schema_version: null, passport_schema_version_reason: "legacy_unknown" })} pageIndex={1} pageCount={1} />,
    );
    const banner = getByTestId("print-passport-unsupported-schema").textContent ?? "";
    expect(banner).toContain("unsupported_schema");
    // Причина отсутствия версии печатается в строке провенанса (schema: …).
    expect(getByTestId("print-passport-page").textContent).toContain("legacy_unknown");
    expect(getByTestId("print-passport-groups")).not.toBeNull();
  });

  test("A6.9 flattenPassportGroup: вложенность — свои dict'ы без applicable разворачиваются с префиксом", () => {
    const rows = flattenPassportGroup({ outer: { inner: 5, deeper: { leaf: "x" } }, plain: 7 });
    const labels = rows.map((r) => r.label);
    expect(labels).toContain("outer.inner");
    expect(labels).toContain("outer.deeper.leaf");
    expect(labels).toContain("plain");
    const values = Object.fromEntries(rows.map((r) => [r.label, r.value]));
    expect(values["outer.inner"]).toBe("5");
    expect(values["outer.deeper.leaf"]).toBe("x");
    expect(values["plain"]).toBe("7");
  });

  test("A6.10 flattenPassportGroup: applicable:true группы — applicable печатается «Да», поля не теряются", () => {
    const rows = flattenPassportGroup({ value: 0.5, applicable: true });
    const map = Object.fromEntries(rows.map((r) => [r.label, r.value]));
    expect(map["value"]).toBe("0,5");
    expect(map["applicable"]).toBe("Да");
  });

  test("A6.11 фактическая семантика вложенного applicable:false — рекурсия по полям, applicable подавлена, без фабкации (док-расхождение — Class B F-P7C3)", () => {
    const rows = flattenPassportGroup({ nested: { applicable: false, reason: "p7cert-причина", value: null } });
    const map = Object.fromEntries(rows.map((r) => [r.label, r.value]));
    expect(map["nested.reason"]).toBe("p7cert-причина");
    expect(map["nested.value"]).toBe("—");
    expect(rows.some((r) => r.label === "nested.applicable")).toBe(false); // подавлена
  });

  test("A6.12 номер страницы паспорта: свои значения", () => {
    const { getByTestId } = render(<PrintPassportPage record={p7record()} pageIndex={7} pageCount={9} />);
    expect(getByTestId("print-passport-page").textContent).toContain("Стр. 7 из 9");
  });
});

// ── Сравнение: собственный снапшот иной формы ────────────────────

function p7comparison(overrides: Partial<PrintComparisonSnapshot> = {}): PrintComparisonSnapshot {
  return {
    schema_version: PASSPORT_COMPARISON_SCHEMA_VERSION,
    mode: "explicit_refs",
    run_id: "run-p7cert-42",
    ordered_refs: ["artifact:passport:p7a", "artifact:passport:p7b", "artifact:passport:p7c"],
    path: ["start", "validation", "exit"],
    comparisons: [
      {
        from_stage: "start",
        to_stage: "validation",
        from_snapshot_id: "p7a",
        to_snapshot_id: "p7b",
        comparison: {
          metrics: {
            "Среднее": { v_old: -12.75, v_new: -10.25, delta: 2.5, delta_pct: -19.6078 },
            "Станд. отклонение": { v_old: 8.125, v_new: 8.125, delta: 0, delta_pct: 0 },
          },
          qualitative_changes: ["p7cert: форма ряда изменилась"],
          categorical_changes: { "freq.value": { v_old: "MS", v_new: "D", changed: true } },
          list_changes: { "fft.dominant_periods": { added: [6, 4], removed: [24], changed: true } },
          boolean_changes: { "stationarity.is_stationary": { v_old: false, v_new: true, changed: true } },
          summary: "изменилось 5 свойств",
        },
        cross_context: false,
      },
      {
        from_stage: "validation",
        to_stage: "exit",
        from_snapshot_id: "p7b",
        to_snapshot_id: "p7c",
        comparison: {
          metrics: { "Среднее": { v_old: -10.25, v_new: -9.75, delta: 0.5, delta_pct: 4.878 } },
          qualitative_changes: [],
          categorical_changes: {},
          list_changes: {},
          boolean_changes: {},
          summary: "изменений почти нет",
        },
        cross_context: false,
      },
    ],
    confirmation: null,
    checkpoint: null,
    context: { context_id: "ctx-p7cert-cmp", data_revision: "rev-p7cert-9" },
    cross_context: true,
    aliases: [{ path_position: 1 }],
    method_versions: { engine: { id: "app.core.passport._compare_ts_props", version: "v1.0" }, records: [] },
    definitions: {
      absolute: "delta = v_new - v_old",
      relative: "delta_pct = (delta / abs(v_old)) * 100",
      zero_denominator_reason: "p7cert: при |v_old| <= 1e-10 относительное изменение не определено",
      delta_color: "цвет delta не означает статистическую значимость",
    },
    gaps: [
      { at: "path.hurst", snapshot_ref: null, reason: "content_missing", detail: "p7cert: группа отсутствует в снимке p7c" },
    ],
    completeness: "partial",
    ...overrides,
  };
}

describe("p7cert A7: печатное сравнение на своих данных (§9/AC13)", () => {
  test("A7.1 три этапа-колонки, значения, дельты со знаком, вторая пара только для общей метрики", () => {
    const { getByTestId } = render(<PrintPassportComparisonPage snapshot={p7comparison()} />);
    const text = getByTestId("print-comparison-page").textContent ?? "";
    expect(text).toContain("start → validation → exit");
    expect(text).toContain("-12,75");
    expect(text).toContain("+2,5");
    expect(text).toContain("−19,6 %"); // signedNumber — typographic minus U+2212
    expect(text).toContain("Δ start → validation");
    expect(text).toContain("Δ validation → exit");
    // Вторая пара не несёт «Станд. отклонение» — прочерк, не фабкация.
    expect(text).toContain("—");
  });

  test("A7.2 категория/список/булево/качественные — свои изменения", () => {
    const { getByTestId } = render(<PrintPassportComparisonPage snapshot={p7comparison()} />);
    const text = getByTestId("print-comparison-page").textContent ?? "";
    expect(text).toContain("MS → D");
    expect(text).toContain("Добавлено 6; 4");
    expect(text).toContain("Удалено 24");
    expect(text).toContain("Нет → Да");
    expect(text).toContain("p7cert: форма ряда изменилась");
  });

  test("A7.3 zero-denominator definition и non-significance печатаются из своих definitions", () => {
    const { getByTestId } = render(<PrintPassportComparisonPage snapshot={p7comparison()} />);
    const defs = getByTestId("print-comparison-definitions").textContent ?? "";
    expect(defs).toContain("p7cert: при |v_old| <= 1e-10");
    expect(defs).toContain("не означает статистическую значимость");
    expect(defs).toContain("delta = v_new - v_old");
  });

  test("A7.4 gaps: свой gap с reason/detail, полнота partial", () => {
    const { getByTestId } = render(<PrintPassportComparisonPage snapshot={p7comparison()} />);
    const gaps = getByTestId("print-comparison-gaps").textContent ?? "";
    expect(gaps).toContain("path.hurst");
    expect(gaps).toContain("content_missing");
    expect(gaps).toContain("p7cert: группа отсутствует в снимке p7c");
    expect(gaps).toContain("partial");
  });

  test("A7.5 cross_context бейдж (свой явный режим)", () => {
    const { getByTestId } = render(<PrintPassportComparisonPage snapshot={p7comparison()} />);
    expect(getByTestId("print-comparison-page").textContent).toContain("cross_context");
  });

  test("A7.6 confirmation reused/unchanged: свои значения, отдельная строка (AC11)", () => {
    const { getByTestId } = render(
      <PrintPassportComparisonPage
        snapshot={p7comparison({
          confirmation: {
            checkpoint_ref: "artifact:passport_checkpoint:p7ck",
            confirmed_at: "2026-10-29T09:15:00Z",
            confirmed_at_reason: null,
            reused: true,
            unchanged: false,
            reused_ref: "artifact:passport:p7b",
            previous_ref: "artifact:passport:p7a",
          },
          checkpoint: {
            checkpoint_ref: "artifact:passport_checkpoint:p7ck",
            checkpoint_artifact_id: "artifact:passport_checkpoint:p7ck",
            stage: "modeling_entry",
            universe: "single",
            confirmed_at: "2026-10-29T09:15:00Z",
            confirmed_at_reason: null,
            flags: { reused: true },
            provenance: { producer_capture: true },
          },
        })}
      />,
    );
    const conf = getByTestId("print-comparison-confirmation").textContent ?? "";
    expect(conf).toContain("2026-10-29 09:15");
    expect(conf).toContain("artifact:passport:p7b");
    expect(conf).toContain("без повторного расчёта");
    expect(conf).toContain("modeling_entry");
  });

  test("A7.7 confirmation с причиной времени: честная причина вместо выдуманной даты (AC12-дух)", () => {
    const { getByTestId } = render(
      <PrintPassportComparisonPage
        snapshot={p7comparison({
          confirmation: {
            checkpoint_ref: null,
            confirmed_at: null,
            confirmed_at_reason: "legacy_unknown",
            reused: false,
            unchanged: false,
            reused_ref: null,
            previous_ref: null,
          },
          checkpoint: null,
        })}
      />,
    );
    const conf = getByTestId("print-comparison-confirmation").textContent ?? "";
    expect(conf).toContain("legacy_unknown");
  });

  test("A7.8 футер: schema/aliases count/пар count — свои значения", () => {
    const { getByTestId } = render(<PrintPassportComparisonPage snapshot={p7comparison()} pageIndex={3} pageCount={4} />);
    const footer = getByTestId("print-comparison-page").textContent ?? "";
    expect(footer).toContain("pgv.passport_comparison/1");
    expect(footer).toContain("aliases: 1");
    expect(footer).toContain("пар: 2");
    expect(footer).toContain("Стр. 3 из 4");
  });
});

describe("p7cert A8: AC04 динамический оракул на своих данных (тема не просачивается)", () => {
  test("A8.1 паспорт: .dark-предок — style идентичен светлому", () => {
    const record = p7record();
    const light = render(
      <div><PrintPassportPage record={record} pageIndex={1} pageCount={1} /></div>,
    );
    const dark = render(
      <div className="dark" data-theme="dark"><PrintPassportPage record={record} pageIndex={1} pageCount={1} /></div>,
    );
    const ls = light.container.querySelector('[data-testid="print-passport-page"]') as HTMLElement;
    const ds = dark.container.querySelector('[data-testid="print-passport-page"]') as HTMLElement;
    expect(ds.getAttribute("style")).toBe(ls.getAttribute("style"));
    expect(ds.getAttribute("style")).not.toContain("var(");
  });

  test("A8.2 сравнение: .dark-предок — style идентичен светлому", () => {
    const snap = p7comparison();
    const light = render(<div><PrintPassportComparisonPage snapshot={snap} /></div>);
    const dark = render(<div className="dark"><PrintPassportComparisonPage snapshot={snap} /></div>);
    const ls = light.container.querySelector('[data-testid="print-comparison-page"]') as HTMLElement;
    const ds = dark.container.querySelector('[data-testid="print-comparison-page"]') as HTMLElement;
    expect(ds.getAttribute("style")).toBe(ls.getAttribute("style"));
  });

  test("A8.3 каркас на своём сайте: .dark-предок — style идентичен", () => {
    const snap = buildMinimalValidSnapshot(p7site(MY_CHART2));
    const light = render(<div><PrintPageFrame snapshot={snap} pageIndex={1} pageCount={1} /></div>);
    const dark = render(<div className="dark"><PrintPageFrame snapshot={snap} pageIndex={1} pageCount={1} /></div>);
    const ls = light.container.querySelector('[data-testid="print-page-surface"]') as HTMLElement;
    const ds = dark.container.querySelector('[data-testid="print-page-surface"]') as HTMLElement;
    expect(ds.getAttribute("style")).toBe(ls.getAttribute("style"));
  });
});

describe("p7cert A9: AC05 байт-равенство meta compact/expanded на своём сайте", () => {
  test("A9.1 meta-блок идентичен; обязательный состав на месте", () => {
    const compact = render(<PrintPageFrame snapshot={buildMinimalValidSnapshot(p7site(MY_CHART2), { detailLevel: "compact" })} pageIndex={1} pageCount={1} />);
    const expanded = render(<PrintPageFrame snapshot={buildMinimalValidSnapshot(p7site(MY_CHART2), { detailLevel: "expanded" })} pageIndex={1} pageCount={1} />);
    const mc = compact.container.querySelector('[data-testid="print-meta"]')?.textContent ?? "";
    const me = expanded.container.querySelector('[data-testid="print-meta"]')?.textContent ?? "";
    expect(me).toBe(mc);
    for (const token of ["context_id", "data_revision", "рассчитано", "зафиксировано"]) {
      expect(me).toContain(token);
    }
  });
});

describe("p7cert A10: PrintLegendStrip/PrintSectionTitle — свои данные", () => {
  test("A10.1 легенда с note; записи все, порядок сохранён", () => {
    const { getByTestId } = render(<PrintLegendStrip ordering={["Альфа", "Бета", "Гамма", "Дельта"]} note="p7cert-note" />);
    const text = getByTestId("print-legend").textContent ?? "";
    for (const s of ["Альфа", "Бета", "Гамма", "Дельта", "p7cert-note"]) expect(text).toContain(s);
    expect(text.indexOf("Альфа")).toBeLessThan(text.indexOf("Дельта"));
  });

  test("A10.2 PrintSectionTitle рендерит текст своего раздела", () => {
    const { container } = render(<PrintSectionTitle>p7cert-раздел</PrintSectionTitle>);
    expect(container.textContent).toContain("p7cert-раздел");
  });

  test("A10.3 PRINT_STATUS_MARKS: знаки различимы, уникальны и непусты (свой пин)", () => {
    const marks = PRINT_STATUS_MARKS.map((m) => m.mark);
    expect(new Set(marks).size).toBe(marks.length);
    for (const m of marks) expect(m.length).toBeGreaterThan(0); // ремутация M02
    const colors = PRINT_STATUS_MARKS.map((m) => m.color);
    expect(new Set(colors).size).toBe(colors.length);
  });

  test("A10.4 PRINT_TYPE_SCALE: микро-порог 9, small 10 — читаемость ограничена контрактом", () => {
    expect(PRINT_TYPE_SCALE.micro).toBeGreaterThanOrEqual(9);
    expect(PRINT_TYPE_SCALE.small).toBeGreaterThanOrEqual(10);
  });

  test("A10.5 resolveVarStringLight: смешанная строка с двумя var() и текстом (свои значения)", () => {
    const out = resolveVarStringLight("0 0 var(--chart-blue) / var(--chart-border)");
    expect(out).toBe(`0 0 ${CHART_VARS_LIGHT["chart-blue"]} / ${CHART_VARS_LIGHT["chart-border"]}`);
  });

  test("A10.6 resolveChartVarLight: --префикс и без — оба пути", () => {
    expect(resolveChartVarLight("--chart-brand")).toBe(CHART_VARS_LIGHT["chart-brand"]);
    expect(resolveChartVarLight("chart-brand")).toBe(CHART_VARS_LIGHT["chart-brand"]);
    expect(resolveChartVarLight("--unknown-p7cert")).toBeNull();
  });

  test("A10.7 isHexColor: собственные граничные случаи", () => {
    expect(isHexColor("#ABCDEF")).toBe(true);
    expect(isHexColor("#abcdef")).toBe(true);
    expect(isHexColor("#ABCDE")).toBe(false);
    expect(isHexColor("#ABCDEFG")).toBe(false);
    expect(isHexColor("rgb(0,0,0)")).toBe(false);
    expect(isHexColor("")).toBe(false);
  });
});
