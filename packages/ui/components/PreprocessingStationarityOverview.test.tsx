import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { PreprocessingStationarityOverview, type StationarityProfile } from "./PreprocessingStationarityOverview";


const PROFILE: StationarityProfile = {
  column: "Price", applicable: true, reason: null, n_observations: 180, missing_count: 0,
  min_observations: 30, alpha: 0.05, order_source: "time_column", order_column: "Date",
  frequency: "MS", regular: true, seasonal_period: 12, selected_method: "first_difference",
  needs_transformation: true, consensus_before: "non-stationary", consensus_after: "stationary",
  lost_observations: 1, acf_lag1_before: 0.97, acf_lag1_after: -0.08,
  variance_before: 14, variance_after: 1.1, over_differencing_warning: false,
  tests: [
    { id: "adf_level", label: "ADF (уровень)", null_hypothesis: "Единичный корень", before_p_value: 0.4, after_p_value: 0.001, before_supports_stationarity: false, after_supports_stationarity: true },
    { id: "kpss_level", label: "KPSS (уровень)", null_hypothesis: "Стационарность", before_p_value: 0.01, after_p_value: 0.1, before_supports_stationarity: false, after_supports_stationarity: true },
  ],
  candidates: [
    { method: "first_difference", label: "Первая разность", available: true, reason: null, consensus: "stationary", lost_observations: 1, adf_p_value: 0.001, kpss_p_value: 0.1, acf_lag1: -0.08, variance_ratio: 0.08, over_differencing_warning: false },
    { method: "seasonal_difference", label: "Сезонная разность", available: true, reason: null, consensus: "inconclusive", lost_observations: 12, adf_p_value: 0.03, kpss_p_value: 0.01, acf_lag1: 0.4, variance_ratio: 0.2, over_differencing_warning: false },
  ],
  points: [
    { x: "2024-01-01T00:00:00", original: 10, transformed: null, rolling_mean_z_before: null, rolling_mean_z_after: null, rolling_std_ratio_before: null, rolling_std_ratio_after: null },
    { x: "2024-02-01T00:00:00", original: 11, transformed: 1, rolling_mean_z_before: 0.2, rolling_mean_z_after: 0.1, rolling_std_ratio_before: 1.4, rolling_std_ratio_after: 1.0 },
  ],
  acf: [{ lag: 0, before: 1, after: 1, confidence_before: 0.15, confidence_after: 0.15 }, { lag: 1, before: 0.97, after: -0.08, confidence_before: 0.15, confidence_after: 0.15 }],
  warnings: [], recommendation: "Рекомендуется первая разность.",
  methodology_note: "ADF и KPSS имеют противоположные H0; применяйте минимум необходимых разностей.",
};


describe("PreprocessingStationarityOverview", () => {
  it("renders five visual views and official methodology links", () => {
    render(<PreprocessingStationarityOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("tablist", { name: "Графики стационарности ряда" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "statsmodels ADF" })).toHaveAttribute("href", expect.stringContaining("adfuller"));
    expect(screen.getByRole("link", { name: "statsmodels KPSS" })).toHaveAttribute("href", expect.stringContaining("kpss"));
    expect(screen.getByRole("link", { name: "FPP3 differencing" })).toHaveAttribute("href", expect.stringContaining("stationarity"));
  });

  it("switches through rolling diagnostics, tests, ACF and candidates", () => {
    render(<PreprocessingStationarityOverview profile={PROFILE} loading={false} error={null} noDataset={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "Rolling μ/σ" }));
    expect(screen.getByRole("img", { name: "Скользящие среднее и отклонение" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Тесты" }));
    expect(screen.getByRole("img", { name: "P-значения до и после преобразования" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "ACF" }));
    expect(screen.getByRole("img", { name: "ACF до и после преобразования" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Кандидаты" }));
    expect(screen.getByRole("table", { name: "Сравнение преобразований стационарности" })).toBeInTheDocument();
  });

  it("shows an honest not-applicable reason", () => {
    render(<PreprocessingStationarityOverview profile={{ ...PROFILE, applicable: false, reason: "Временная сетка нерегулярна" }} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Временная сетка нерегулярна");
  });
});
