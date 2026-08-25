import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { ValidationUniquenessOverview } from "./ValidationUniquenessOverview";


const RESPONSE = {
  rule_source: "template",
  profile: {
    applicable: true, applicability_message: null, mode: "composite_key",
    key_columns: ["Country", "Year"], total_rows: 5, valid_rows: 1,
    duplicate_rows: 4, duplicate_groups: 2, redundant_rows: 2,
    duplicate_pct: 80, supported_actions: ["keep_first", "keep_last", "drop_all", "aggregate", "flag"],
    groups: [
      { key_values: { Country: "A", Year: "2020" }, occurrences: 2, redundant_rows: 1, row_numbers: [1, 2] },
      { key_values: { Country: "B", Year: "2020" }, occurrences: 2, redundant_rows: 1, row_numbers: [4, 5] },
    ],
  },
};


describe("ValidationUniquenessOverview", () => {
  it("renders the row distribution and duplicate group matrix", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(RESPONSE) });
    render(<ValidationUniquenessOverview refreshKey={1} />);

    expect(await screen.findByRole("img", { name: /Уникальных строк: 1; строк в группах дублей: 4/i })).toBeInTheDocument();
    expect(screen.getByText("Составной ключ: Country + Year")).toBeInTheDocument();
    expect(screen.getByText("Лишних копий — 2")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Группы дубликатов" })).toBeInTheDocument();
    expect(screen.getByText("Country=A · Year=2020")).toBeInTheDocument();
  });

  it("shows the passed state without a placeholder", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...RESPONSE, profile: { ...RESPONSE.profile, valid_rows: 5, duplicate_rows: 0, duplicate_groups: 0, redundant_rows: 0, duplicate_pct: 0, groups: [] } }),
    });
    render(<ValidationUniquenessOverview refreshKey={1} />);

    expect(await screen.findByText("Дубликаты не найдены")).toBeInTheDocument();
    expect(screen.getByText(/проверены по составному ключу Country \+ Year/i)).toBeInTheDocument();
  });
});

