import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { PreprocessingSpectralOverview, type PreprocessingSpectralProfile } from "./PreprocessingSpectralOverview";


export const SPECTRAL_PROFILE: PreprocessingSpectralProfile = {
  column: "Price", applicable: true, reason: null, n_observations: 240, missing_count: 0,
  min_cycles: 3, max_candidates: 6, max_period: 80, detrend: "linear", window: "hann",
  order_source: "time_column", order_column: "Date", order_warning: null, frequency: "MS",
  spectral_entropy: 0.22, dominant_period: 12, dominant_strength: 0.78, confirmed_periods: 1,
  frequency_resolution: 1 / 240, nyquist_frequency: 0.5, welch_segment_length: 64, welch_segments: 6,
  wavelet_method: "cmor1.5-1.0", wavelet_period_min: 2, wavelet_period_max: 80,
  analysis_only: true, causal: false, modeling_safe: false, saved_periods: [],
  fft: [{ frequency: 1 / 12, period: 12, amplitude: 3, power: null, is_peak: true }],
  periodogram: [{ frequency: 1 / 12, period: 12, amplitude: null, power: 4, is_peak: true }],
  welch: [{ frequency: 1 / 12, period: 12, amplitude: null, power: 3.5, power_share: 0.72, is_peak: true }],
  bands: [
    { id: "low", label: "Низкие", frequency_min: 0, frequency_max: 0.1, power_share: 0.75 },
    { id: "mid", label: "Средние", frequency_min: 0.1, frequency_max: 0.25, power_share: 0.2 },
    { id: "high", label: "Высокие", frequency_min: 0.25, frequency_max: 0.5, power_share: 0.05 },
  ],
  candidates: [{ rank: 1, period: 12, period_rounded: 12, frequency: 1 / 12, amplitude: 3, power: 4, power_share: 72, prominence: 3.8, spectral_snr: 18, autocorrelation: 0.84, seasonal_strength: 0.78, cycles: 20, confirmed: true, calendar_hint: "годовой цикл", harmonic_of: null }],
  phase_period: 12,
  phase_profile: Array.from({ length: 12 }, (_, index) => ({ phase: index + 1, mean: Math.sin(2 * Math.PI * index / 12), lower: -0.1, upper: 0.1, count: 20 })),
  wavelet: [
    { x: "2010-01-01T00:00:00", index: 0, period: 12, power: 4, normalized_power: 0.9, edge_affected: true },
    { x: "2015-01-01T00:00:00", index: 60, period: 12, power: 5, normalized_power: 1, edge_affected: false },
  ],
  wavelet_global: [{ period: 12, power_share: 0.7 }],
  recommendations: ["Подтверждён период 12."], warnings: [],
  methodology_note: "Пики являются диагностическими кандидатами.",
};


describe("PreprocessingSpectralOverview", () => {
  it("renders five visual views and official methodology links", () => {
    render(<PreprocessingSpectralOverview profile={SPECTRAL_PROFILE} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("tablist", { name: "Представления спектрального анализа" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SciPy periodogram" })).toHaveAttribute("href", expect.stringContaining("periodogram"));
    expect(screen.getByRole("link", { name: "SciPy Welch" })).toHaveAttribute("href", expect.stringContaining("welch"));
    expect(screen.getByRole("link", { name: "PyWavelets CWT" })).toHaveAttribute("href", expect.stringContaining("cwt"));
  });

  it("switches through Welch, CWT, phase and candidates", () => {
    render(<PreprocessingSpectralOverview profile={SPECTRAL_PROFILE} loading={false} error={null} noDataset={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "Welch PSD" }));
    expect(screen.getByRole("img", { name: "Welch PSD и частотные диапазоны" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "CWT" }));
    expect(screen.getByRole("img", { name: "CWT скалограмма" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Фазовый профиль" }));
    expect(screen.getByRole("img", { name: "Фазовый профиль периода 12" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Кандидаты" }));
    expect(screen.getByRole("table", { name: "Спектральные периоды-кандидаты" })).toBeInTheDocument();
  });

  it("shows an honest not-applicable reason", () => {
    render(<PreprocessingSpectralOverview profile={{ ...SPECTRAL_PROFILE, applicable: false, reason: "Временная сетка нерегулярна" }} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Временная сетка нерегулярна");
  });
});
