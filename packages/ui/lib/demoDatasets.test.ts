// packages/ui/lib/demoDatasets.test.ts
//
// Тесты для demoDatasets.ts. Проверяют:
// - детерминированность генерации (seeded PRNG -- один и тот же CSV
//   при каждом вызове, важно для воспроизводимой демонстрации)
// - структурную валидность CSV (заголовки, число строк, отсутствие
//   NaN/undefined в значениях; пустые ячейки -- только там, где датасет
//   ОБЪЯВЛЕННО содержит пропуски)
// - demoDatasetToFile действительно создаёт File с правильным именем/типом
// - forecast-monitor датасет (2026-09-16): первый в списке, 150 месячных
//   строк, ровно 3 пропуска и ровно 4 IQR-выброса, все значения > 0 --
//   симуляция «настоящего» набора для быстрого мониторинга модуля
//   «Прогнозирование» (нейро-модели честно отсекаются применимостью:
//   147 < 200, правило F04).

import { DEMO_DATASETS, demoDatasetToFile } from "./demoDatasets";

const FORECAST_ID = "forecast_monitor_n150";
const FORECAST_FILE = "forecast_monitor_synthetic_n150.csv";

/** Квантиль p на отсортированном массиве -- линейная интерполяция,
 * тот же метод по умолчанию, что np.quantile/pandas.quantile
 * (использует качество-тизер бэкенда и _iqr_outlier_ratio профиля). */
function quantile(sorted: number[], p: number): number {
  const pos = (sorted.length - 1) * p;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** Разбирает CSV forecast-monitor датасета в пары {date, rawValue}
 * (rawValue == "" для пропуска). */
function parseForecastCsv(csv: string): { date: string; rawValue: string }[] {
  const lines = csv.split("\n");
  const header = lines[0].split(",");
  expect(header).toEqual(["date", "value"]);
  return lines.slice(1).map((line) => {
    const [date, rawValue] = line.split(",");
    return { date, rawValue };
  });
}

describe("DEMO_DATASETS", () => {
  it("exposes exactly 4 datasets", () => {
    expect(DEMO_DATASETS).toHaveLength(4);
  });

  it("forecast monitor dataset is FIRST in the list (задача 2026-09-16)", () => {
    expect(DEMO_DATASETS[0].id).toBe(FORECAST_ID);
    expect(DEMO_DATASETS[0].fileName).toBe(FORECAST_FILE);
  });

  it("each dataset has a unique id", () => {
    const ids = DEMO_DATASETS.map((d) => d.id);
    expect(new Set(ids).size).toBe(4);
  });

  it("structural classes: 4 datasets cover 3 classes -- forecast monitor сознательно делит Univariate TS с retail", () => {
    const classes = DEMO_DATASETS.map((d) => d.structuralClassLabel);
    expect(new Set(classes).size).toBe(3);
    // Пропорция: 2 x Univariate TS + по одному Panel/Multivariate.
    expect(classes.filter((c) => c === "Univariate TS")).toHaveLength(2);
    expect(classes.filter((c) => c === "Panel Data — Balanced")).toHaveLength(1);
    expect(classes.filter((c) => c === "Multivariate TS")).toHaveLength(1);
  });

  it("each dataset has a unique industry", () => {
    const industries = DEMO_DATASETS.map((d) => d.industry);
    expect(new Set(industries).size).toBe(4);
  });

  it.each(DEMO_DATASETS.map((d) => [d.id, d]))("%s: generation is deterministic (same seed -> same CSV)", (_id, ds) => {
    const first = (ds as (typeof DEMO_DATASETS)[number]).generateCsv();
    const second = (ds as (typeof DEMO_DATASETS)[number]).generateCsv();
    expect(first).toBe(second);
  });

  it.each(DEMO_DATASETS.map((d) => [d.id, d]))("%s: well-formed CSV (empties allowed only as declared value-missings)", (_id, ds) => {
    const dataset = ds as (typeof DEMO_DATASETS)[number];
    const csv = dataset.generateCsv();
    const lines = csv.split("\n");
    expect(lines.length).toBeGreaterThan(10);

    const header = lines[0].split(",");
    expect(header.length).toBeGreaterThanOrEqual(2);

    // Пустые ячейки допустимы ТОЛЬКО в forecast-monitor датасете и
    // ТОЛЬКО в колонке value (объявленные пропуски); дата и все ячейки
    // остальных датасетов -- всегда заполнены, без NaN/undefined.
    const allowsMissing = dataset.id === FORECAST_ID;
    const valueIdx = header.indexOf("value");
    let emptyCount = 0;
    for (const line of lines.slice(1)) {
      const cells = line.split(",");
      expect(cells).toHaveLength(header.length);
      for (let c = 0; c < cells.length; c++) {
        if (cells[c] === "") {
          emptyCount++;
          expect(allowsMissing).toBe(true);
          expect(c).toBe(valueIdx);
        } else {
          expect(cells[c]).not.toBe("NaN");
          expect(cells[c]).not.toBe("undefined");
        }
      }
    }
    if (!allowsMissing) expect(emptyCount).toBe(0);
  });

  // ── forecast monitor (2026-09-16): структура ряда ──

  it("forecast monitor: 150 monthly rows 2013-01..2025-06, consecutive months", () => {
    const ds = DEMO_DATASETS.find((d) => d.id === FORECAST_ID)!;
    const rows = parseForecastCsv(ds.generateCsv());
    expect(rows).toHaveLength(150);
    expect(rows[0].date).toBe("2013-01-01");
    expect(rows[rows.length - 1].date).toBe("2025-06-01");
    for (let i = 1; i < rows.length; i++) {
      const prev = rows[i - 1].date.split("-").map(Number);
      const cur = rows[i].date.split("-").map(Number);
      const prevIdx = prev[0] * 12 + (prev[1] - 1);
      const curIdx = cur[0] * 12 + (cur[1] - 1);
      expect(curIdx).toBe(prevIdx + 1); // месячный шаг без разрывов дат
    }
  });

  it("forecast monitor: exactly 3 missing values, dates stay intact", () => {
    const ds = DEMO_DATASETS.find((d) => d.id === FORECAST_ID)!;
    const rows = parseForecastCsv(ds.generateCsv());
    const missing = rows.filter((r) => r.rawValue === "");
    expect(missing).toHaveLength(3);
    // Пропуск -- это пустое ЗНАЧЕНИЕ при сохранной дате (шаг дат
    // проверен в соседнем тесте), не удалённая строка.
    for (const m of missing) expect(m.date).toMatch(/^\d{4}-\d{2}-01$/);
  });

  it("forecast monitor: all values positive, exactly 4 IQR outliers", () => {
    const ds = DEMO_DATASETS.find((d) => d.id === FORECAST_ID)!;
    const rows = parseForecastCsv(ds.generateCsv());
    const values = rows
      .filter((r) => r.rawValue !== "")
      .map((r) => Number(r.rawValue));
    // Все значения положительные (включая глубокий провал-выброс).
    for (const v of values) expect(v).toBeGreaterThan(0);

    // IQR-заборы (1.5*IQR) на финальном ряде -- тот же метод, что
    // np.quantile (linear) в бэкенде.
    const sorted = [...values].sort((a, b) => a - b);
    const q1 = quantile(sorted, 0.25);
    const q3 = quantile(sorted, 0.75);
    const iqr = q3 - q1;
    const lower = q1 - 1.5 * iqr;
    const upper = q3 + 1.5 * iqr;
    const outliers = values.filter((v) => v < lower || v > upper);
    // Ровно 4 инжектированных выброса (3 спайка вверх + 1 провал вниз):
    // запасы дельт >= 15 против заборов, нативный шум sigma=3.2
    // заборов не достигает.
    expect(outliers).toHaveLength(4);
  });

  it("forecast monitor: rowsLabel and description mention 150 months, outliers and missings", () => {
    const ds = DEMO_DATASETS.find((d) => d.id === FORECAST_ID)!;
    expect(ds.rowsLabel).toContain("150");
    expect(ds.description).toContain("выброс");
    expect(ds.description).toContain("пропуск");
  });

  // ── прежние датасеты (без изменений) ──

  it("retail dataset: date column values are real distinct calendar dates, not epoch", () => {
    const retail = DEMO_DATASETS.find((d) => d.id === "retail_revenue")!;
    const lines = retail.generateCsv().split("\n");
    const dates = lines.slice(1, 6).map((l) => l.split(",")[0]);
    expect(dates).toEqual(["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04", "2023-01-05"]);
    expect(dates.every((d) => !d.startsWith("1970"))).toBe(true);
  });

  it("energy dataset: is a balanced panel (same date set repeated per region)", () => {
    const energy = DEMO_DATASETS.find((d) => d.id === "energy_consumption")!;
    const lines = energy.generateCsv().split("\n").slice(1);
    const rows = lines.map((l) => l.split(","));
    const regions = new Set(rows.map((r) => r[0]));
    expect(regions.size).toBe(5);

    const datesByRegion = new Map<string, Set<string>>();
    for (const [region, month] of rows) {
      if (!datesByRegion.has(region)) datesByRegion.set(region, new Set());
      datesByRegion.get(region)!.add(month);
    }
    const dateSets = Array.from(datesByRegion.values()).map((s) => Array.from(s).sort().join("|"));
    // Balanced panel: у ВСЕХ регионов идентичный набор дат
    expect(new Set(dateSets).size).toBe(1);
  });

  it("finance dataset: high >= low for every row (OHLC sanity)", () => {
    const finance = DEMO_DATASETS.find((d) => d.id === "finance_ohlcv")!;
    const lines = finance.generateCsv().split("\n").slice(1);
    for (const line of lines) {
      const [, , high, low] = line.split(",");
      expect(parseFloat(high)).toBeGreaterThanOrEqual(parseFloat(low));
    }
  });

  it("demoDatasetToFile creates a File with correct name and CSV mime type", () => {
    const ds = DEMO_DATASETS[0];
    const file = demoDatasetToFile(ds);
    expect(file.name).toBe(ds.fileName);
    expect(file.type).toBe("text/csv");
    expect(file.size).toBeGreaterThan(0);
  });
});
