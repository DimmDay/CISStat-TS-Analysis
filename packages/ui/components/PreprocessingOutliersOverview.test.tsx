import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { PreprocessingOutliersOverview } from "./PreprocessingOutliersOverview";

const PROFILE = {
  rule_source: "system",
  mode: "auto",
  status: "warning",
  status_reason: null,
  method: "iqr",
  total_rows: 21,
  total_numeric_columns: 2,
  total_outliers: 1,
  outlier_rate_pct: 2.4,
  affected_columns: ["Price"],
  columns: [
    {
      column: "Price", sample_size: 21, outlier_count: 1, outlier_pct: 4.76,
      recommended_method: "iqr", bounds: { lower: -5, upper: 25 },
      outlier_examples: [20], insufficient_sample: false,
    },
    {
      column: "Clean", sample_size: 21, outlier_count: 0, outlier_pct: 0,
      recommended_method: "iqr", bounds: { lower: -3, upper: 30 },
      outlier_examples: [], insufficient_sample: false,
    },
  ],
};

describe("PreprocessingOutliersOverview", () => {
  it("renders a per-column outlier table with bounds", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<PreprocessingOutliersOverview refreshKey={1} />);

    expect(await screen.findByRole("table", { name: "Выбросы по числовым колонкам" })).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
    expect(screen.getByText("Пройдено")).toBeInTheDocument();
    expect(screen.getByText("-5.00 … 25.00")).toBeInTheDocument();
  });

  it("explains when there are no numeric columns", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, columns: [] }),
    });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    expect(await screen.findByText(/нет числовых колонок/i)).toBeInTheDocument();
  });

  it("shows a neutral explanation when the check is disabled", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, mode: "disabled", status: "skipped", status_reason: "disabled" }),
    });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    expect(await screen.findByRole("status")).toHaveTextContent("отключена аналитиком");
  });

  it("shows an alert when the profile request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: "нет датасета" }) });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет датасета");
  });
});
