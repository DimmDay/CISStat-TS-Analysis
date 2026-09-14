import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { EdaSeasonalityOverview, type EdaSeasonalityResponse } from "./EdaSeasonalityOverview";


const PROFILE: EdaSeasonalityResponse = {
  column: "Price", applicable: true, reason: null, n_observations: 240, missing_count: 0,
  min_cycles: 3, max_candidates: 5, max_period: 80, detrend: "linear", window: "hann",
  order_source: "time_column", order_column: "Date", order_warning: null, frequency: "D",
  spectral_entropy: 0.21, dominant_period: 12, dominant_strength: 0.82, confirmed_periods: 1,
  fft: [{ frequency: 1 / 12, period: 12, amplitude: 3, power: null, is_peak: true }],
  periodogram: [{ frequency: 1 / 12, period: 12, amplitude: null, power: 4.5, is_peak: true }],
  candidates: [{
    rank: 1, period: 12, period_rounded: 12, frequency: 1 / 12, amplitude: 3, power: 4.5,
    power_share: 72, prominence: 4.2, spectral_snr: 30, autocorrelation: 0.91,
    seasonal_strength: 0.82, cycles: 20, confirmed: true, calendar_hint: null, harmonic_of: null,
  }],
  phase_period: 12,
  phase_profile: Array.from({ length: 12 }, (_, index) => ({ phase: index + 1, mean: index / 10, lower: index / 10 - 0.1, upper: index / 10 + 0.1, count: 20 })),
  recommendations: ["Подтверждён период 12"],
};


describe("EdaSeasonalityOverview", () => {
  it("switches four visualizations backed by one seasonality profile", () => {
    render(<EdaSeasonalityOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={{ minCycles: 3, maxCandidates: 5 }} onParametersChange={jest.fn()} />);

    expect(screen.getByRole("img", { name: "FFT-спектр для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Периодограмма" }));
    expect(screen.getByRole("img", { name: "Периодограмма для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Фазовый профиль" }));
    expect(screen.getByRole("img", { name: "Фазовый профиль периода 12 для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Кандидаты" }));
    expect(screen.getByRole("table", { name: "Периоды-кандидаты" })).toBeInTheDocument();
    expect(screen.getByText("подтверждён")).toBeInTheDocument();
  });

  it("updates analysis parameters without creating another target selector", () => {
    const onParametersChange = jest.fn();
    render(<EdaSeasonalityOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={{ minCycles: 3, maxCandidates: 5 }} onParametersChange={onParametersChange} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Минимум полных циклов" }), { target: { value: "4" } });
    expect(onParametersChange).toHaveBeenCalledWith({ minCycles: 4 });
    expect(screen.queryByRole("combobox", { name: /исследуемый признак/i })).not.toBeInTheDocument();
  });

  it("shows an honest not-applicable state", () => {
    render(<EdaSeasonalityOverview profile={{ ...PROFILE, applicable: false, reason: "Временная сетка нерегулярна" }} loading={false} error={null} noDataset={false} parameters={{ minCycles: 3, maxCandidates: 5 }} onParametersChange={jest.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Временная сетка нерегулярна");
  });

  // Task w/n-4: бейдж-паттерн переключателей представлений «Обзора»
  // вкладки «Предобработка» (эталон «Генерации признаков») — tablist
  // внутри шапки Обзора (p-4 с border-b), mt-3 flex flex-wrap gap-2;
  // геометрия эталона px-3 py-1 text-xs; активный border-neutral-300
  // bg-neutral-200 text-neutral-800, неактивный border-neutral-200
  // bg-neutral-50 text-neutral-500 hover:bg-neutral-100.
  it("переключатели представлений следуют бейдж-паттерну «Обзора» «Предобработки»", () => {
    render(<EdaSeasonalityOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={{ minCycles: 3, maxCandidates: 5 }} onParametersChange={jest.fn()} />);

    const tablist = screen.getByRole("tablist", { name: "Представления сезонности и периодичности" });
    expect(tablist).toHaveClass("mt-3", "flex", "flex-wrap", "gap-2");
    expect(tablist.parentElement).toHaveClass("p-4");
    expect(tablist.parentElement?.className).toContain("border-b border-neutral-100");

    const active = screen.getByRole("tab", { name: "FFT" });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(active).toHaveClass("border-neutral-300", "bg-neutral-200", "text-neutral-800");

    const inactive = screen.getByRole("tab", { name: "Периодограмма" });
    expect(inactive).toHaveAttribute("aria-selected", "false");
    expect(inactive).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(inactive).toHaveClass("border-neutral-200", "bg-neutral-50", "text-neutral-500", "hover:bg-neutral-100");
  });
});
