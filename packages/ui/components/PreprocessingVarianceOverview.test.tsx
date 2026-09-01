import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { PreprocessingVarianceOverview, type VarianceProfile } from "./PreprocessingVarianceOverview";


const DIAGNOSTICS = {
  rolling_window: 12, mean_std_correlation: 0.82, levene_statistic: 8.2,
  levene_pvalue: 0.001, block_variance_ratio: 6.3, arch_lm_lag: 10,
  arch_lm_pvalue: 0.02, skewness: 1.4, stability_score: 78.2,
};

const PROFILE: VarianceProfile = {
  column: "Price", applicable: true, reason: null, n_observations: 96,
  missing_count: 0, minimum: 2, maximum: 41, order_source: "time_column",
  order_column: "Date", selected_method: "box_cox", lambda_value: 0.18,
  needs_stabilization: true, diagnostics_before: DIAGNOSTICS,
  diagnostics_after: { ...DIAGNOSTICS, mean_std_correlation: 0.12, stability_score: 21.4 },
  candidates: [
    { method: "box_cox", label: "Box–Cox", available: true, reason: null, lambda_value: 0.18, stability_score: 21.4 },
    { method: "yeo_johnson", label: "Yeo–Johnson", available: true, reason: null, lambda_value: 0.12, stability_score: 24.1 },
    { method: "log", label: "Log", available: true, reason: null, lambda_value: null, stability_score: 28.1 },
  ],
  points: [
    { x: "2024-01-01T00:00:00", original: 10, transformed: 2.2, rolling_std_before: null, rolling_std_after: null },
    { x: "2024-02-01T00:00:00", original: 12, transformed: 2.4, rolling_std_before: 1.4, rolling_std_after: 0.2 },
  ],
  histogram: [{ bin: 1, original_x: 10, original_density: 0.1, transformed_x: 2, transformed_density: 0.2 }],
  warnings: [], recommendation: "Рекомендуется Box–Cox.", methodology_note: "Диагностический профиль.",
};


describe("PreprocessingVarianceOverview", () => {
  it("renders methodology and light-grey badge tabs", () => {
    render(<PreprocessingVarianceOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);
    expect(screen.getByText(/Box–Cox · λ=0.180/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "До / после" })).toHaveClass("bg-neutral-200");
    expect(screen.getByRole("tab", { name: "Скользящая σ" })).toHaveClass("bg-neutral-50");
    expect(screen.getByRole("link", { name: "SciPy Box–Cox" })).toHaveAttribute("href", expect.stringContaining("scipy.stats.boxcox"));
  });

  it("switches between method comparison, distributions and diagnostics", () => {
    render(<PreprocessingVarianceOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "Методы" }));
    expect(screen.getByRole("img", { name: "Сравнение методов стабилизации" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Диагностика" }));
    expect(screen.getAllByText("Brown–Forsythe").length).toBeGreaterThan(1);
  });

  it("shows an honest not-applicable reason", () => {
    render(<PreprocessingVarianceOverview profile={{ ...PROFILE, applicable: false, reason: "Ряд константный" }} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Ряд константный");
  });
});
