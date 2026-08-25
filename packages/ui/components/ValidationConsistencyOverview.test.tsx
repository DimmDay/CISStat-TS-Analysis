import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { ValidationConsistencyOverview } from "./ValidationConsistencyOverview";


const PROFILE = {
  rule_source: "template",
  rules: [
    {
      rule_index: 0,
      rule_name: "Хронология по странам",
      rule_type: "chronology",
      description: "Годы возрастают внутри страны",
      columns: ["Year"],
      time_column: "Year",
      group_column: "Country",
      applicable: true,
      applicability_message: null,
      checked_count: 4,
      valid_count: 3,
      invalid_count: 1,
      affected_rows: 2,
      invalid_examples: ["Country=A: 2022 → 2021"],
      supported_actions: ["sort_chronology", "drop_rows", "replace_null", "flag"],
    },
    {
      rule_index: 1,
      rule_name: "Цена неотрицательна",
      rule_type: "negative_price",
      description: "Цена не может быть отрицательной",
      columns: ["Price"],
      time_column: null,
      group_column: null,
      applicable: true,
      applicability_message: null,
      checked_count: 5,
      valid_count: 5,
      invalid_count: 0,
      affected_rows: 0,
      invalid_examples: [],
      supported_actions: ["drop_rows", "replace_null", "flag"],
    },
  ],
};


describe("ValidationConsistencyOverview", () => {
  it("renders a compliance bar and rule matrix", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<ValidationConsistencyOverview refreshKey={1} />);

    expect(await screen.findByRole("img", { name: /Проверок соблюдено: 8; нарушений: 1/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Матрица логики и хронологии" })).toBeInTheDocument();
    expect(screen.getByText("Хронология по странам")).toBeInTheDocument();
    expect(screen.getByText("Year · группы: Country")).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
    expect(screen.getByText("Соответствует")).toBeInTheDocument();
  });

  it("explains when no applicable consistency reference exists", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ rule_source: "not_applicable", rules: [] }),
    });
    render(<ValidationConsistencyOverview refreshKey={1} />);

    expect(await screen.findByText(/Эталон логики и хронологии не задан/i)).toBeInTheDocument();
  });
});
