import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { ValidationInclusionOverview } from "./ValidationInclusionOverview";


const PROFILE = {
  rule_source: "template",
  columns: [{
    column: "Country", allowed_values: ["A", "B"], allowed_count: 2,
    total_count: 4, valid_count: 2, invalid_count: 2, invalid_pct: 50,
    invalid_values: [{ value: "X", count: 2 }], default_value: "A",
    default_valid: true, supported_actions: ["mode", "replace_null", "drop_rows", "replace_default", "flag"],
  }],
};


describe("ValidationInclusionOverview", () => {
  it("renders a compliance bar and domain matrix", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<ValidationInclusionOverview refreshKey={1} />);

    expect(await screen.findByRole("img", { name: /Допустимых значений: 2; нарушений: 2/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Матрица принадлежности к наборам" })).toBeInTheDocument();
    expect(screen.getByText("A, B")).toBeInTheDocument();
    expect(screen.getByText("X × 2")).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
  });

  it("explains when no domain reference exists", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, json: () => Promise.resolve({ rule_source: "not_applicable", columns: [] }),
    });
    render(<ValidationInclusionOverview refreshKey={1} />);

    expect(await screen.findByText(/Эталон допустимых наборов не задан/i)).toBeInTheDocument();
  });
});

