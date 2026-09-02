import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingSpectralPipeline } from "./PreprocessingSpectralPipeline";
import type { PreprocessingSpectralProfile } from "./PreprocessingSpectralOverview";


const RESPONSE = {
  applied: false, column: "Price", selected_periods: [12], confirmed_periods: [12],
  unconfirmed_periods: [], suggested_lags: [12],
  metadata: { kind: "spectral_selection", source_column: "Price", selected_periods: [12], frequencies: [1 / 12], confirmed_periods: [12], unconfirmed_periods: [], min_cycles: 3, max_candidates: 6, welch_segment_length: 64, detrend: "linear", window: "hann", wavelet: "cmor1.5-1.0", analysis_only: true, causal: false, modeling_safe: false, analyzed_on_n: 240, order_source: "time_column", order_column: "Date", frequency: "MS" },
};
const PROFILE = {
  column: "Price", applicable: true, saved_periods: [],
  candidates: [{ rank: 1, period: 12, period_rounded: 12, frequency: 1 / 12, confirmed: true, calendar_hint: "годовой цикл" }],
} as PreprocessingSpectralProfile;


describe("PreprocessingSpectralPipeline", () => {
  it("previews and persists selected periods only after confirmation", async () => {
    const onApplied = jest.fn();
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...RESPONSE, applied: true }) });
    render(<PreprocessingSpectralPipeline column="Price" profile={PROFILE} onApplied={onApplied} />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Период 12" }));
    fireEvent.click(screen.getByRole("button", { name: "Проверить выбор периодов" }));
    expect(await screen.findByText(/Лаги-кандидаты: 12/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Подтверждаю сохранение аналитического решения" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить периоды" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining("/dataset/preprocessing/spectral-selections"),
      expect.objectContaining({ method: "POST", body: expect.stringContaining('"apply":true') }),
    );
  });

  it("explains that analysis does not create features or mutate the dataset", () => {
    global.fetch = jest.fn();
    render(<PreprocessingSpectralPipeline column="Price" profile={PROFILE} onApplied={jest.fn()} />);
    expect(screen.getByText(/не создаёт лаговые признаки/i)).toBeInTheDocument();
    expect(screen.getByText(/полной истории/i)).toBeInTheDocument();
  });
});
