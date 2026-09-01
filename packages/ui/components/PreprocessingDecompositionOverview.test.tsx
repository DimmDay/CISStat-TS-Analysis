import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { PreprocessingDecompositionOverview, type PreprocessingDecompositionProfile } from "./PreprocessingDecompositionOverview";


const PROFILE: PreprocessingDecompositionProfile = {
  column: "Price", date_column: "Date", applicable: true, reason: null,
  method: "STL", robust: true, frequency: "MS", period: 12, n_points: 60,
  sampled: false, original_count: 60, trend_strength: 0.91,
  seasonal_strength: 0.88, residual_mean: 0.01, residual_std: 1.2,
  ljung_box_lag: 12, ljung_box_pvalue: 0.21, jarque_bera_pvalue: 0.08,
  points: [
    { x: "2024-01-01T00:00:00", observed: 10, trend: 9, seasonal: 1.2, resid: -0.2 },
    { x: "2024-02-01T00:00:00", observed: 12, trend: 9.5, seasonal: 2, resid: 0.5 },
  ],
  seasonal_pattern: [{ phase: 1, label: "1", value: 1.2 }],
  residual_acf: [{ lag: 0, value: 1 }, { lag: 1, value: 0.1 }],
  warnings: [], recommendation: "Сезонность выражена.", methodology_note: "STL additive",
};


describe("PreprocessingDecompositionOverview", () => {
  it("renders diagnostics and light-grey badge tabs", () => {
    render(<PreprocessingDecompositionOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);

    expect(screen.getByText(/STL · период 12/)).toBeInTheDocument();
    const active = screen.getByRole("tab", { name: "Компоненты" });
    const inactive = screen.getByRole("tab", { name: "Сезонный профиль" });
    expect(active).toHaveClass("bg-neutral-200");
    expect(inactive).toHaveClass("bg-neutral-50");
    expect(active).not.toHaveClass("bg-brand");
  });

  it("switches graph views with accessible tabs", () => {
    render(<PreprocessingDecompositionOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "ACF остатка" }));
    expect(screen.getByRole("img", { name: "ACF остатка STL" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "ACF остатка" })).toHaveAttribute("aria-selected", "true");
  });

  it("shows an honest not-applicable reason", () => {
    render(<PreprocessingDecompositionOverview profile={{ ...PROFILE, applicable: false, reason: "Ряд нерегулярный" }} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Ряд нерегулярный");
  });
});
