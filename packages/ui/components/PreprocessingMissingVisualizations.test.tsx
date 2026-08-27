import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";

import { MissingMatrixChart, MissingCorrelationChart, MissingBoxplotChart } from "./PreprocessingMissingVisualizations";

describe("MissingMatrixChart", () => {
  it("renders bins and column labels once data loads", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        columns: ["Price", "Region"],
        bins: [
          { bin_index: 0, row_start: 0, row_end: 1, row_count: 2, missing_share: { Price: 1, Region: 0 } },
          { bin_index: 1, row_start: 2, row_end: 3, row_count: 2, missing_share: { Price: 0, Region: 0.5 } },
        ],
        rows_per_bin: 2,
        total_rows: 4,
      }),
    });
    render(<MissingMatrixChart />);

    expect(await screen.findByText(/Каждый столбец матрицы/)).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText("Region")).toBeInTheDocument();
    expect(screen.getByText("строка 0")).toBeInTheDocument();
    expect(screen.getByText("строка 3")).toBeInTheDocument();
  });

  it("shows an alert when the request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: "нет датасета" }) });
    render(<MissingMatrixChart />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет датасета");
  });
});

describe("MissingCorrelationChart", () => {
  it("renders a correlation table for at least two columns", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ columns: ["A", "B"], matrix: [[1, 0.8], [0.8, 1]] }),
    });
    render(<MissingCorrelationChart />);

    const table = await screen.findByRole("table", { name: "Корреляция пропусков между колонками" });
    expect(table).toBeInTheDocument();
    expect(screen.getAllByText("0.80").length).toBeGreaterThan(0);
  });

  it("explains when fewer than two varying columns are available", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ columns: [], matrix: [] }) });
    render(<MissingCorrelationChart />);
    expect(await screen.findByText(/Нужно минимум две колонки/)).toBeInTheDocument();
  });
});

describe("MissingBoxplotChart", () => {
  const columns = [
    { column: "Price", dtype: "float64", semantic: "numeric" as const, total_count: 4, missing_count: 0, non_missing_count: 4, missing_pct: 0, recommended_strategy: "none" as const, missing_examples: [] },
    { column: "Region", dtype: "object", semantic: "categorical" as const, total_count: 4, missing_count: 2, non_missing_count: 2, missing_pct: 50, recommended_strategy: "median_mode" as const, missing_examples: [2, 3] },
  ];

  it("fetches and renders both group summaries for the default column pair", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        value_column: "Price", indicator_column: "Region",
        with_missing: { count: 2, min: 100, q1: 120, median: 150, q3: 180, max: 200, mean: 150 },
        without_missing: { count: 2, min: 10, q1: 12, median: 15, q3: 18, max: 20, mean: 15 },
      }),
    });
    render(<MissingBoxplotChart columns={columns} />);

    expect(await screen.findByText(/С пропуском в «Region»/)).toBeInTheDocument();
    expect(screen.getByText(/Без пропуска в «Region»/)).toBeInTheDocument();
    expect(screen.getByText("n=2, медиана=150.00")).toBeInTheDocument();
  });

  it("explains when there are no numeric columns", () => {
    global.fetch = jest.fn();
    render(<MissingBoxplotChart columns={[columns[1]]} />);
    expect(screen.getByText(/нет числовых колонок/)).toBeInTheDocument();
  });

  it("refetches when the analyst switches the indicator column", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        value_column: "Price", indicator_column: "Region",
        with_missing: { count: 2, min: 100, q1: 120, median: 150, q3: 180, max: 200, mean: 150 },
        without_missing: { count: 2, min: 10, q1: 12, median: 15, q3: 18, max: 20, mean: 15 },
      }),
    });
    render(<MissingBoxplotChart columns={columns} />);
    await screen.findByText(/С пропуском в «Region»/);

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("value_column=Price&indicator_column=Region"),
      expect.anything()
    );
  });
});
