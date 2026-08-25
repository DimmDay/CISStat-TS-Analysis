import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { ValidationRangeOverview } from "./ValidationRangeOverview";

const PROFILE = {
  rule_source: "template",
  columns: [
    {
      column: "Price",
      rule_name: "Цена",
      min_allowed: 0,
      max_allowed: 100,
      actual_min: -5,
      actual_max: 80,
      total_count: 4,
      valid_count: 3,
      invalid_count: 1,
      invalid_pct: 25,
      invalid_examples: [-5],
    },
    {
      column: "Year",
      rule_name: "Год",
      min_allowed: 1990,
      max_allowed: 2030,
      actual_min: 2000,
      actual_max: 2024,
      total_count: 4,
      valid_count: 4,
      invalid_count: 0,
      invalid_pct: 0,
      invalid_examples: [],
    },
  ],
};

describe("ValidationRangeOverview", () => {
  it("renders a compliance bar and complete range matrix", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<ValidationRangeOverview refreshKey={1} />);

    expect(await screen.findByRole("img", { name: /В допустимом диапазоне: 7; нарушений: 1/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Матрица диапазонов колонок" })).toBeInTheDocument();
    expect(screen.getByText("Фактический min / max")).toBeInTheDocument();
    expect(screen.getByText("Допустимый min / max")).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
    expect(screen.getByText("Соответствует")).toBeInTheDocument();
  });

  it("explains when no range reference is configured", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ rule_source: "not_applicable", columns: [] }),
    });
    render(<ValidationRangeOverview refreshKey={1} />);

    expect(await screen.findByText(/Эталон диапазонов не задан/i)).toBeInTheDocument();
  });
});
