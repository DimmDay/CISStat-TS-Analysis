import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { PreprocessingSmoothingOverview, type SmoothingProfile } from "./PreprocessingSmoothingOverview";


const DIAGNOSTICS = {
  normalized_roughness: 2.4, difference_std_ratio: 0.8, lag1_autocorrelation: 0.2,
  high_frequency_power_share: 0.48, standard_deviation: 3.2,
};

const PROFILE: SmoothingProfile = {
  column: "Price", applicable: true, reason: null, n_observations: 96,
  order_source: "time_column", order_column: "Date", frequency: "MS", regular: true,
  selected_method: "ema", selected_parameters: { span: 7 }, needs_smoothing: true,
  diagnostics_before: DIAGNOSTICS,
  diagnostics_after: { ...DIAGNOSTICS, normalized_roughness: 0.7, high_frequency_power_share: 0.12 },
  candidates: [
    { method: "ema", label: "EMA", causal: true, available: true, reason: null, parameter_label: "span=7", correlation: 0.9, roughness_reduction_pct: 70, high_frequency_reduction_pct: 75, variance_retained_pct: 72, residual_ljung_box_pvalue: 0.2 },
    { method: "lowess", label: "LOWESS", causal: false, available: true, reason: null, parameter_label: "frac=0.2", correlation: 0.92, roughness_reduction_pct: 80, high_frequency_reduction_pct: 82, variance_retained_pct: 68, residual_ljung_box_pvalue: 0.1 },
  ],
  points: [
    { x: "2024-01-01T00:00:00", original: 10, smoothed: 10, residual: 0 },
    { x: "2024-02-01T00:00:00", original: 13, smoothed: 11, residual: 2 },
  ],
  spectrum: [{ frequency: 0.1, before: 0.7, after: 0.2 }],
  residual_acf: [{ lag: 0, value: 1 }, { lag: 1, value: 0.1 }],
  warnings: [], recommendation: "Высокочастотная составляющая выражена.",
  methodology_note: "Эвристика, не статистический тест.",
};


describe("PreprocessingSmoothingOverview", () => {
  it("renders five visual views and official methodology links", () => {
    render(<PreprocessingSmoothingOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("tablist", { name: "Графики сглаживания ряда" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Ряд" })).toHaveClass("bg-neutral-200");
    expect(screen.getByRole("link", { name: "pandas rolling" })).toHaveAttribute("href", expect.stringContaining("Series.rolling"));
    expect(screen.getByRole("link", { name: "SciPy Savitzky–Golay" })).toHaveAttribute("href", expect.stringContaining("savgol_filter"));
  });

  it("switches between residual, method, spectrum and diagnostic views", () => {
    render(<PreprocessingSmoothingOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "Методы" }));
    expect(screen.getByRole("img", { name: "Сравнение методов сглаживания" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Спектр" }));
    expect(screen.getByRole("img", { name: "Спектр до и после сглаживания" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Диагностика" }));
    expect(screen.getAllByText(/не статистический тест/i).length).toBeGreaterThan(0);
  });

  it("shows an honest not-applicable reason", () => {
    render(<PreprocessingSmoothingOverview profile={{ ...PROFILE, applicable: false, reason: "Ряд константный" }} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Ряд константный");
  });
});
