import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { ValidationSufficiencyOverview } from "./ValidationSufficiencyOverview";


const PROFILE = {
  rule_source: "session", plan: {},
  profile: {
    applicable: true, applicability_message: null, date_column: "Date", entity_column: "Country", target_column: "Value",
    frequency: "D", seasonal_period: 2, groups_total: 2, sufficient_groups: 1, insufficient_groups: 1, total_failed_checks: 2,
    thresholds: [], supported_actions: ["restrict_models", "flag_groups", "drop_groups"],
    groups: [
      { group: "A", rows_total: 6, valid_observations: 6, invalid_target_count: 0, invalid_date_count: 0, unique_timestamps: 6, frequency: "D", seasonal_period: 2, seasonal_cycles: 3, failed_checks: 0, passed_checks: 6, checks: [], available_capabilities: ["ARIMA"], unavailable_capabilities: [] },
      { group: "B", rows_total: 3, valid_observations: 3, invalid_target_count: 0, invalid_date_count: 0, unique_timestamps: 3, frequency: "D", seasonal_period: 2, seasonal_cycles: 1, failed_checks: 2, passed_checks: 4, checks: [], available_capabilities: ["Тренд"], unavailable_capabilities: ["ARIMA", "ML"] },
    ],
  },
};


describe("ValidationSufficiencyOverview", () => {
  it("renders group coverage and applicability matrix", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<ValidationSufficiencyOverview refreshKey={1} />);

    expect(await screen.findByRole("img", { name: /Достаточных групп: 1; ограниченных групп: 1/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Матрица достаточности наблюдений" })).toBeInTheDocument();
    expect(screen.getByText("ARIMA, ML")).toBeInTheDocument();
    expect(screen.getByText("Ограниченный выбор моделей")).toBeInTheDocument();
  });
});

