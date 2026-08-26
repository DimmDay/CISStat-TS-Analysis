import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationSufficiencyPipeline } from "./ValidationSufficiencyPipeline";


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
const PREVIEW = { applied: false, strategy: "restrict_models", rows_before: 9, rows_after: 9, rows_removed: 0, added_columns: [], eligible_groups: ["A"], insufficient_groups: ["B"], profile: PROFILE.profile };


describe("ValidationSufficiencyPipeline", () => {
  it("previews and persists a safe analysis plan", async () => {
    (global.fetch as jest.Mock) = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<ValidationSufficiencyPipeline onApplied={onApplied} onOpenRules={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер решений по достаточности" })).toBeInTheDocument();
    expect(await screen.findByText("Value")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр решения" }));
    expect(await screen.findByText(/Достаточные группы: A/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить план анализа" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю выбранное решение/i }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить план анализа" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });
});
