import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { ValidationTextQualityOverview } from "./ValidationTextQualityOverview";


const PROFILE = {
  rule_source: "system",
  columns: [{
    column: "Country", total_count: 4, valid_count: 2, invalid_count: 2,
    invalid_pct: 50, min_length: 1, max_length: 500,
    issue_counts: { garbage: 1, empty: 0, too_short: 0, too_long: 0, whitespace: 1, pattern: 0 },
    invalid_examples: [" bad\\u0000", "  RU"],
    supported_actions: ["normalize", "replace_null", "drop_rows", "replace_unknown", "flag"],
  }],
};


describe("ValidationTextQualityOverview", () => {
  it("renders a quality bar and per-column matrix", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<ValidationTextQualityOverview refreshKey={1} />);

    expect(await screen.findByRole("img", { name: /Чистых значений: 2; нарушений: 2/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Матрица целостности текста" })).toBeInTheDocument();
    expect(screen.getByText("Мусор: 1; Пробелы: 1")).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
  });

  it("explains when the dataset has no text columns", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, json: () => Promise.resolve({ rule_source: "not_applicable", columns: [] }),
    });
    render(<ValidationTextQualityOverview refreshKey={1} />);

    expect(await screen.findByText(/В датасете нет текстовых колонок/i)).toBeInTheDocument();
  });
});
