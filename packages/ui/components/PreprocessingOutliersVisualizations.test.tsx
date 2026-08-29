import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";

import {
  OutlierLineChart, OutlierHistogramChart, OutlierDensityChart, OutlierBoxplotChart,
} from "./PreprocessingOutliersVisualizations";

describe("OutlierLineChart", () => {
  it("prompts to pick a column when none is selected", () => {
    render(<OutlierLineChart column={null} />);
    expect(screen.getByText(/Выберите числовой признак/)).toBeInTheDocument();
  });

  it("shows a sampling notice when the backend sampled points", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        points: [{ x: 0, y: 1 }, { x: 1, y: 2 }],
        sampled: true, sampling_method: "lttb", original_count: 5000,
      }),
    });
    render(<OutlierLineChart column="Price" />);
    expect(await screen.findByText(/Показано 2 из 5000 точек/)).toBeInTheDocument();
  });

  it("shows an alert when the request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 422, json: () => Promise.resolve({ detail: "не числовая" }) });
    render(<OutlierLineChart column="Region" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("не числовая");
  });
});

describe("OutlierHistogramChart", () => {
  it("renders bounds hint when bounds are present", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        bins: [{ x0: 0, x1: 10, count: 5 }, { x0: 10, x1: 20, count: 2 }],
        bounds: { lower: -5, upper: 25 },
      }),
    });
    render(<OutlierHistogramChart column="Price" method="iqr" />);
    expect(await screen.findByText(/Границы метода \(пунктир\)/)).toBeInTheDocument();
  });

  it("explains when there are no bins", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ bins: [], bounds: null }) });
    render(<OutlierHistogramChart column="Price" method="iqr" />);
    expect(await screen.findByText("Нет данных.")).toBeInTheDocument();
  });
});

describe("OutlierDensityChart", () => {
  it("explains when density is undefined (constant column)", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ points: null }) });
    render(<OutlierDensityChart column="Price" />);
    expect(await screen.findByText(/Плотность не определена/)).toBeInTheDocument();
  });
});

describe("OutlierBoxplotChart", () => {
  it("renders both groups when data is present", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        column: "Price",
        outliers: { count: 1, min: 1000, q1: 1000, median: 1000, q3: 1000, max: 1000, mean: 1000 },
        normal: { count: 20, min: 5, q1: 8, median: 10, q3: 12, max: 15, mean: 10 },
      }),
    });
    render(<OutlierBoxplotChart column="Price" method="iqr" />);
    expect(await screen.findByText("Выброс")).toBeInTheDocument();
    expect(screen.getByText("Норма")).toBeInTheDocument();
    expect(screen.getByText("n=1, медиана=1000.00")).toBeInTheDocument();
  });

  it("shows 'no data' for an empty group", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ column: "Price", outliers: null, normal: { count: 5, min: 1, q1: 2, median: 3, q3: 4, max: 5, mean: 3 } }),
    });
    render(<OutlierBoxplotChart column="Price" method="iqr" />);
    expect(await screen.findByText("Нет данных")).toBeInTheDocument();
  });
});
