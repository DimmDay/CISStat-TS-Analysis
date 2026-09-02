import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PreprocessingFeatureEngineeringPipeline } from "./PreprocessingFeatureEngineeringPipeline";
import type { FeatureGenerationProfile } from "./PreprocessingFeatureEngineeringOverview";


const profile = {
  column: "Price", applicable: true, n_observations: 120,
  suggested_lags: [1, 12], suggested_rolling_windows: [3, 12],
  suggested_calendar_features: ["month_cyclic", "year"], suggested_fourier_periods: [12],
  spectral_periods: [12], preview_feature_count: 12, max_lookback: 12,
} as FeatureGenerationProfile;


describe("PreprocessingFeatureEngineeringPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ applied: false, feature_names: ["Price_lag_1", "Price_lag_12"], rows_before: 120, rows_after: 108, rows_dropped: 12, max_lookback: 12 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ applied: true, feature_names: ["Price_lag_1", "Price_lag_12"], rows_before: 120, rows_after: 108, rows_dropped: 12, max_lookback: 12 }) });
  });

  it("previews then separately confirms causal feature generation", async () => {
    const onApplied = jest.fn();
    render(<PreprocessingFeatureEngineeringPipeline column="Price" profile={profile} onApplied={onApplied} />);
    expect(screen.getByText(/Периоды из спектрального анализа: 12/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Проверить набор признаков" }));
    await screen.findByText(/Будет добавлено: 2/);
    expect(screen.getByText(/Будет удалено начальных строк: 12/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Подтверждаю применение набора признаков"));
    fireEvent.click(screen.getByRole("button", { name: "Сгенерировать признаки" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body)).toMatchObject({
      column: "Price", lags: [1, 12], drop_warmup_rows: true, apply: false,
    });
  });
});
