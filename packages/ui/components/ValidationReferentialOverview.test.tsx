import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { ValidationReferentialOverview } from "./ValidationReferentialOverview";


const PROFILE = {
  rule_source: "template",
  rules: [{
    rule_index: 0, rule_name: "Код страны существует", child_column: "CountryCode",
    allowed_values: ["BY", "KZ"], reference_count: 2, applicable: true,
    applicability_message: null, total_count: 3, valid_count: 2, invalid_count: 1,
    invalid_pct: 33.33, invalid_values: [{ value: "XX", count: 1 }],
    default_value: "BY", default_valid: true,
    supported_actions: ["mode", "replace_null", "drop_rows", "replace_default", "flag"],
  }],
};


describe("ValidationReferentialOverview", () => {
  it("renders an orphan ratio and rule matrix", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<ValidationReferentialOverview refreshKey={1} />);

    expect(await screen.findByRole("img", { name: /Связанных записей: 2; сиротских записей: 1/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Матрица ссылочной целостности" })).toBeInTheDocument();
    expect(screen.getByText("Код страны существует")).toBeInTheDocument();
    expect(screen.getByText("XX × 1")).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
  });

  it("explains when no foreign-key reference exists", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, json: () => Promise.resolve({ rule_source: "not_applicable", rules: [] }),
    });
    render(<ValidationReferentialOverview refreshKey={1} />);

    expect(await screen.findByText(/Правила ссылочной целостности не заданы/i)).toBeInTheDocument();
  });
});

