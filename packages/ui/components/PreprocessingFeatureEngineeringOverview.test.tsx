import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { PreprocessingFeatureEngineeringOverview, type FeatureGenerationProfile } from "./PreprocessingFeatureEngineeringOverview";


const profile: FeatureGenerationProfile = {
  column: "Price", applicable: true, reason: null, n_observations: 120,
  order_source: "time_column", order_column: "Date", frequency: "MS",
  regular: true, spectral_periods: [12], suggested_lags: [1, 12],
  suggested_rolling_windows: [3, 12], suggested_calendar_features: ["month_cyclic", "year"],
  suggested_fourier_periods: [12], generated: false, saved_feature_names: [],
  max_lookback: 12, preview_feature_count: 12,
  preview_points: [
    { x: "2020-01-01", target: 10, lag: null, rolling: null, fourier: 0 },
    { x: "2021-01-01", target: 12, lag: 10, rolling: 11, fourier: 0 },
  ],
  lag_correlations: [{ lag: 1, correlation: 0.8, selected: true }, { lag: 12, correlation: 0.9, selected: true }],
  availability: [{ name: "Price_lag_12", family: "lag", available_count: 108, missing_count: 12, coverage: 0.9 }],
  cyclic_points: [{ x: "2020-01-01", feature: "fourier_p12_k1_sin", value: 0 }],
  catalog: [{ name: "Price_lag_12", family: "lag", formula: "y[t-12]", lookback: 12, known_in_advance: false, causal: true, missing_count: 12, coverage: 0.9 }],
  warnings: [], recommendation: "Проверьте признаки временной валидацией.",
  methodology_note: "Target-derived признаки используют только прошлое.",
};


describe("PreprocessingFeatureEngineeringOverview", () => {
  it("renders five overview visualizations", () => {
    render(<PreprocessingFeatureEngineeringOverview profile={profile} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("img", { name: /Превью сгенерированных признаков/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Лаг-корреляции" }));
    expect(screen.getByRole("img", { name: /Корреляции цели с прошлыми лагами/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Доступность" }));
    expect(screen.getByRole("img", { name: /Доступность признаков после warm-up/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Циклы" }));
    expect(screen.getByRole("img", { name: /Календарные и Fourier циклы/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Каталог" }));
    expect(screen.getByRole("table", { name: /Каталог рекомендуемых признаков/i })).toBeInTheDocument();
  });

  it("supports loading, errors and not-applicable states", () => {
    const { rerender } = render(<PreprocessingFeatureEngineeringOverview profile={null} loading error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Строим безопасные");
    rerender(<PreprocessingFeatureEngineeringOverview profile={null} loading={false} error="Ошибка" noDataset={false} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Ошибка");
    rerender(<PreprocessingFeatureEngineeringOverview profile={{ ...profile, applicable: false, reason: "Нерегулярная сетка" }} loading={false} error={null} noDataset={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Нерегулярная сетка");
  });
});
