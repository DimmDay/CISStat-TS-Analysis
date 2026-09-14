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
  it("fills the workspace with chart views but keeps long views scrollable", () => {
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

    const ranking = screen.getByRole("img", { name: "Рейтинг IH-информативности для Target" });
    expect(ranking).toHaveClass("min-h-0", "flex-1");
    expect(ranking).not.toHaveClass("h-[270px]");
    expect(ranking.closest("section")).toHaveClass("flex", "overflow-y-auto", "feed-scroll");

    fireEvent.click(screen.getByRole("tab", { name: "Карта метрик" }));
    const metricsSection = screen.getByRole("table", { name: "Карта энтропийных метрик" }).closest("section");
    expect(metricsSection).toHaveClass("overflow-y-auto");
    expect(screen.getByRole("table", { name: "Карта энтропийных метрик" }).parentElement).toHaveClass("shrink-0");
  });

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

  // Task w/n-4: бейдж-паттерн переключателей представлений «Обзора»
  // вкладки «Предобработка» (эталон «Генерации признаков») — tablist
  // внутри шапки Обзора (p-3 с border-b), mt-3 flex flex-wrap gap-2;
  // геометрия эталона px-3 py-1 text-xs; активный border-neutral-300
  // bg-neutral-200 text-neutral-800, неактивный border-neutral-200
  // bg-neutral-50 text-neutral-500 hover:bg-neutral-100.
  it("переключатели представлений следуют бейдж-паттерну «Обзора» «Предобработки»", () => {
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

    const tablist = screen.getByRole("tablist", { name: "Представления IH-анализа" });
    expect(tablist).toHaveClass("mt-3", "flex", "flex-wrap", "gap-2");
    expect(tablist.parentElement).toHaveClass("p-3");
    expect(tablist.parentElement?.className).toContain("border-b border-neutral-100");

    const active = screen.getByRole("tab", { name: "Рейтинг" });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(active).toHaveClass("border-neutral-300", "bg-neutral-200", "text-neutral-800");

    const inactive = screen.getByRole("tab", { name: "Карта метрик" });
    expect(inactive).toHaveAttribute("aria-selected", "false");
    expect(inactive).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(inactive).toHaveClass("border-neutral-200", "bg-neutral-50", "text-neutral-500", "hover:bg-neutral-100");
  });
});
