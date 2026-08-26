import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import { ValidationRegularityOverview } from "./ValidationRegularityOverview";


const PROFILE = {
  rule_source: "system",
  profile: {
    applicable: true, applicability_message: null, date_column: "Date", entity_column: "Country",
    target_frequency: "D", detected_frequency: null, gap_threshold_multiplier: 1.5,
    is_sorted: true, sort_violations: 0, invalid_date_count: 0, duplicate_count: 0,
    gap_count: 1, missing_period_count: 1, total_violations: 1,
    groups: [
      { group: "Country=A", observations: 3, inferred_frequency: null, modal_interval: "1 days", gap_count: 1, missing_period_count: 1, duplicate_count: 0, sort_violations: 0, gap_examples: [{ previous_date: "2024-01-01", current_date: "2024-01-03", missing_periods: 1 }] },
      { group: "Country=B", observations: 3, inferred_frequency: "D", modal_interval: "1 days", gap_count: 0, missing_period_count: 0, duplicate_count: 0, sort_violations: 0, gap_examples: [] },
    ], supported_actions: ["sort", "interpolate", "ffill", "bfill", "asfreq", "fictitious_zero", "flag"],
  },
};


describe("ValidationRegularityOverview", () => {
  it("renders coverage bar and group matrix", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<ValidationRegularityOverview refreshKey={1} />);

    expect(await screen.findByRole("img", { name: /Регулярных групп: 1; проблемных групп: 1/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Матрица равномерности временного шага" })).toBeInTheDocument();
    expect(screen.getByText("Country=A")).toBeInTheDocument();
    expect(screen.getByText("1 пропущен")).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
  });

  it("explains when no time axis is available", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({
      rule_source: "not_applicable", profile: { ...PROFILE.profile, applicable: false, applicability_message: "Не определена временная колонка", date_column: null, groups: [] },
    }) });
    render(<ValidationRegularityOverview refreshKey={1} />);

    expect(await screen.findByText(/Не определена временная колонка/i)).toBeInTheDocument();
  });
});
