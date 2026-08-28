import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { EdaIhOverview, type EdaIhResponse } from "./EdaIhOverview";


const PROFILE: EdaIhResponse = {
  column: "Target",
  applicable: true,
  reason: null,
  n_observations: 240,
  features_analyzed: 4,
  sharpness: 0.25,
  min_samples: 20,
  top_k: 10,
  max_lag: 3,
  permutations: 49,
  target_entropy: 2,
  target_bins: 4,
  order_source: "time_column",
  order_column: "Date",
  order_warning: null,
  frequency: "D",
  lag_features_included: true,
  results: [
    {
      feature: "Signal", kind: "numeric", dtype: "float64", n_observations: 240,
      r: 0.72, r_adjusted: 0.68, mi: 1.44, h_x: 2, h_y: 2,
      n_bins_x: 4, n_bins_y: 4, permutation_baseline: 0.04,
      p_value: 0.02, q_value: 0.04, significant: true, error: null,
    },
    {
      feature: "Target[t−1]", kind: "lag", dtype: "float64", n_observations: 239,
      r: 0.38, r_adjusted: 0.31, mi: 0.76, h_x: 2, h_y: 2,
      n_bins_x: 4, n_bins_y: 4, permutation_baseline: 0.07,
      p_value: 0.04, q_value: 0.04, significant: true, error: null,
    },
  ],
  synergies: [
    {
      pair: "Signal + Segment", feature_1: "Signal", feature_2: "Segment",
      r_1: 0.72, r_2: 0.2, r_combined: 0.8,
      incremental_gain: 0.08, interaction_delta: -0.12,
    },
  ],
  conditional_feature: "Signal",
  conditional_x_bins: ["0", "1"],
  conditional_y_bins: ["0", "1"],
  conditional_matrix: [
    { x_bin: "0", values: [90, 10] },
    { x_bin: "1", values: [10, 90] },
  ],
  recommendations: ["Signal — наиболее информативный фактор"],
};


describe("EdaIhOverview", () => {
  it("switches across all IH visualizations backed by one profile", () => {
    render(
      <EdaIhOverview
        profile={PROFILE}
        loading={false}
        error={null}
        noDataset={false}
        parameters={{ sharpness: 0.25, minSamples: 20, topK: 10, maxLag: 3 }}
        onParametersChange={jest.fn()}
      />,
    );

    expect(screen.getByRole("img", { name: "Рейтинг IH-информативности для Target" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Карта метрик" }));
    expect(screen.getByRole("table", { name: "Карта энтропийных метрик" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Синергия" }));
    expect(screen.getByRole("img", { name: "График взаимодействия факторов" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Условная карта" }));
    expect(screen.getByRole("table", { name: "Условное распределение цели по интервалам фактора" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Таблица" }));
    expect(screen.getByRole("table", { name: "Результаты IH-анализа" })).toBeInTheDocument();
  });

  it("updates sharpness without owning a second target selector", () => {
    const onParametersChange = jest.fn();
    render(
      <EdaIhOverview
        profile={PROFILE}
        loading={false}
        error={null}
        noDataset={false}
        parameters={{ sharpness: 0.25, minSamples: 20, topK: 10, maxLag: 3 }}
        onParametersChange={onParametersChange}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Резкость дискретизации" }), {
      target: { value: "0.5" },
    });
    expect(onParametersChange).toHaveBeenCalledWith({ sharpness: 0.5 });
    expect(screen.queryByRole("combobox", { name: /целевая переменная/i })).not.toBeInTheDocument();
  });

  it("shows an honest not-applicable state", () => {
    render(
      <EdaIhOverview
        profile={{ ...PROFILE, applicable: false, reason: "Энтропия цели равна нулю" }}
        loading={false}
        error={null}
        noDataset={false}
        parameters={{ sharpness: 0.25, minSamples: 20, topK: 10, maxLag: 3 }}
        onParametersChange={jest.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Энтропия цели равна нулю");
  });
});
