import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { EdaDescriptiveOverview, type DescriptiveStatsResponse } from "./EdaDescriptiveOverview";

jest.mock("./DistributionCharts", () => ({
  HistogramDistributionChart: ({ data }: { data: { column: string } | null }) => (
    <div data-testid="histogram-chart">Гистограмма: {data?.column}</div>
  ),
  KdeDistributionChart: ({ data }: { data: { column: string } | null }) => (
    <div data-testid="kde-chart">KDE: {data?.column}</div>
  ),
  ScatterDistributionChart: ({ data }: { data: { column: string } | null }) => (
    <div data-testid="scatter-chart">Разброс: {data?.column}</div>
  ),
  SamplingBadge: () => null,
}));

const PROFILE: DescriptiveStatsResponse = {
  min_non_null_for_stats: 2,
  columns: [
    {
      name: "Price",
      non_null_count: 4,
      stats: {
        mean: 25,
        median: 25,
        std: 12.91,
        skewness: 0,
        kurtosis: -1.2,
        q1: 17.5,
        q3: 32.5,
        iqr: 15,
        distribution_hint: "Близко к нормальному",
      },
    },
    { name: "Sparse", non_null_count: 1, stats: null },
  ],
};

const DISTRIBUTION = {
  column: "Price",
  non_null_count: 4,
  min: 10,
  max: 40,
  scatter: [{ x: 0, y: 10 }, { x: 1, y: 20 }],
  scatter_sampled: false,
  scatter_sampling_method: null,
  scatter_original_count: 4,
  histogram: [{ x0: 10, x1: 20, count: 2 }],
  kde: [{ x: 10, y: 0.1 }, { x: 20, y: 0.2 }],
};

describe("EdaDescriptiveOverview", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(DISTRIBUTION),
    });
  });

  it("renders the descriptive table for every numeric feature", () => {
    render(
      <EdaDescriptiveOverview
        profile={PROFILE}
        activeFeature="Price"
        loading={false}
        error={null}
        noDataset={false}
      />,
    );

    expect(screen.getByRole("table", { name: "Описательные статистики по числовым признакам" })).toBeInTheDocument();
    expect(screen.getByText("Близко к нормальному")).toBeInTheDocument();
    expect(screen.getByText(/Недостаточно данных \(n=1, минимум 2\)/)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("switches between visualization tabs and reuses one distribution response", async () => {
    render(
      <EdaDescriptiveOverview
        profile={PROFILE}
        activeFeature="Price"
        loading={false}
        error={null}
        noDataset={false}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Гистограмма" }));
    expect(await screen.findByTestId("histogram-chart")).toHaveTextContent("Price");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/dataset/distribution?column=Price"),
      { credentials: "include" },
    );

    fireEvent.click(screen.getByRole("tab", { name: "KDE" }));
    expect(screen.getByTestId("kde-chart")).toHaveTextContent("Price");
    fireEvent.click(screen.getByRole("tab", { name: "Разброс" }));
    expect(screen.getByTestId("scatter-chart")).toHaveTextContent("Price");
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("explains when the active dataset has no numeric features", () => {
    render(
      <EdaDescriptiveOverview
        profile={{ columns: [], min_non_null_for_stats: 2 }}
        activeFeature=""
        loading={false}
        error={null}
        noDataset={false}
      />,
    );

    expect(screen.getByText(/нет числовых признаков/i)).toBeInTheDocument();
  });

  it("shows the backend error instead of a fabricated overview", () => {
    render(
      <EdaDescriptiveOverview
        profile={null}
        activeFeature=""
        loading={false}
        error="В сессии нет активного датасета"
        noDataset={false}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("В сессии нет активного датасета");
  });
});
