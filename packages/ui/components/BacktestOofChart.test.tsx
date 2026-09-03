import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { BacktestOofChart } from "./BacktestOofChart";
import type { BacktestResponse } from "../lib/modeling";

global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

const result: BacktestResponse = {
  model_id: "naive", model_name: "Naive", family_id: "baselines",
  metrics: { mae: 1, rmse: 1, mape: 1, mase: 1, weighted_score: null },
  n_train: 40, n_test: 4, train_ratio: 0.8, duration_ms: 2,
  data_source: "session", status: "success", strategy: "expanding",
  cohort_id: "cohort", horizon: 2, n_folds: 2, gap: 0,
  folds: [], warnings: [],
  oof_predictions: [
    { fold: 1, horizon_step: 1, index: 40, label: "2024-01", actual: 10, predicted: 9, residual: 1 },
    { fold: 1, horizon_step: 2, index: 41, label: "2024-02", actual: 11, predicted: 9, residual: 2 },
    { fold: 2, horizon_step: 1, index: 42, label: "2024-03", actual: 12, predicted: 11, residual: 1 },
    { fold: 2, horizon_step: 2, index: 43, label: "2024-04", actual: 13, predicted: 11, residual: 2 },
  ],
};

describe("BacktestOofChart", () => {
  it("renders actual and fixed-origin OOF forecasts with fold count", () => {
    render(<BacktestOofChart result={result} />);
    expect(screen.getByRole("img", { name: /OOF прогноз Naive/i })).toBeInTheDocument();
    expect(screen.getByText(/4 OOF-точки · 2 folds/i)).toBeInTheDocument();
  });

  it("does not invent a chart when OOF predictions are absent", () => {
    render(<BacktestOofChart result={{ ...result, oof_predictions: [] }} />);
    expect(screen.getByText(/OOF-прогнозы отсутствуют/i)).toBeInTheDocument();
  });
});
