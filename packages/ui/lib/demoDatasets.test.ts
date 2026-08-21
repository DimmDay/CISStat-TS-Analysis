// packages/ui/lib/demoDatasets.test.ts
//
// Тесты для demoDatasets.ts (2026-08-19). Проверяют:
// - детерминированность генерации (seeded PRNG -- один и тот же CSV
//   при каждом вызове, важно для воспроизводимой демонстрации)
// - структурную валидность CSV (заголовки, число строк, отсутствие
//   NaN/undefined в значениях)
// - demoDatasetToFile действительно создаёт File с правильным именем/типом

import { DEMO_DATASETS, demoDatasetToFile } from "./demoDatasets";

describe("DEMO_DATASETS", () => {
  it("exposes exactly 3 datasets", () => {
    expect(DEMO_DATASETS).toHaveLength(3);
  });

  it("each dataset has a unique id and distinct structural class", () => {
    const ids = DEMO_DATASETS.map((d) => d.id);
    expect(new Set(ids).size).toBe(3);
    const classes = DEMO_DATASETS.map((d) => d.structuralClassLabel);
    expect(new Set(classes).size).toBe(3); // все три класса разные
  });

  it("each dataset has a unique industry", () => {
    const industries = DEMO_DATASETS.map((d) => d.industry);
    expect(new Set(industries).size).toBe(3);
  });

  it.each(DEMO_DATASETS.map((d) => [d.id, d]))("%s: generation is deterministic (same seed -> same CSV)", (_id, ds) => {
    const first = (ds as (typeof DEMO_DATASETS)[number]).generateCsv();
    const second = (ds as (typeof DEMO_DATASETS)[number]).generateCsv();
    expect(first).toBe(second);
  });

  it.each(DEMO_DATASETS.map((d) => [d.id, d]))("%s: produces well-formed CSV with header + non-empty rows", (_id, ds) => {
    const csv = (ds as (typeof DEMO_DATASETS)[number]).generateCsv();
    const lines = csv.split("\n");
    expect(lines.length).toBeGreaterThan(10);

    const header = lines[0].split(",");
    expect(header.length).toBeGreaterThanOrEqual(2);

    // Все строки данных имеют то же число колонок, что и заголовок,
    // и ни одно значение не пустое/NaN/undefined.
    for (const line of lines.slice(1)) {
      const cells = line.split(",");
      expect(cells).toHaveLength(header.length);
      for (const cell of cells) {
        expect(cell).not.toBe("");
        expect(cell).not.toBe("NaN");
        expect(cell).not.toBe("undefined");
      }
    }
  });

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
