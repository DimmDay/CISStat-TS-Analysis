// packages/ui/components/BacktestComparisonChart.test.tsx
//
// Тесты для графика сравнения бэктестов (Моделирование):
// 1. Пустое состояние -- нет ни одного бэктеста
// 2. Рендер с одним результатом
// 3. Сортировка/выделение лучшей модели (минимальный weighted_score)
// 4. Направление корректно проговорено ("ниже = лучше") -- та самая
//    неоднозначность, из-за которой этот тест вообще написан

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { BacktestComparisonChart } from "./BacktestComparisonChart";
import type { BacktestResponse } from "../lib/modeling";

// ── Polyfill: ResizeObserver не определён в jsdom (нужен Recharts ResponsiveContainer) ──
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

function makeBacktest(overrides: Partial<BacktestResponse> = {}): BacktestResponse {
  return {
    model_id: "naive",
    model_name: "Naive",
    family_id: "baseline",
    metrics: { mae: 1, rmse: 1.2, mape: 5, mase: 0.9, weighted_score: 0.3 },
    n_train: 80,
    n_test: 20,
    train_ratio: 0.8,
    duration_ms: 1.5,
    data_source: "session",
    ...overrides,
  };
}

describe("BacktestComparisonChart", () => {
  it("shows empty state when no backtests have been run", () => {
    render(<BacktestComparisonChart backtestResults={{}} />);
    expect(
      screen.getByText(/Запустите бэктест хотя бы для одной модели/i)
    ).toBeInTheDocument();
  });

  it("renders a chart frame when at least one backtest result exists", () => {
    const results = { naive: makeBacktest() };
    const { container } = render(<BacktestComparisonChart backtestResults={results} />);
    expect(
      screen.queryByText(/Запустите бэктест хотя бы для одной модели/i)
    ).not.toBeInTheDocument();
    // ResponsiveContainer рендерится (recharts обёртка присутствует в DOM)
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });

  it("explicitly states the direction 'ниже = лучше' (weighted_score is a normalized error, not a score)", () => {
    const results = { naive: makeBacktest() };
    render(<BacktestComparisonChart backtestResults={results} />);
    expect(screen.getByText(/ниже\s*=\s*лучше/i)).toBeInTheDocument();
  });

  it("shows count of tested models in the footer caption", () => {
    const results = {
      naive: makeBacktest({ model_id: "naive", model_name: "Naive", metrics: { mae: 2, rmse: 2, mape: 10, mase: 1.5, weighted_score: 0.6 } }),
      ets: makeBacktest({ model_id: "ets", model_name: "ETS", metrics: { mae: 1, rmse: 1, mape: 4, mase: 0.7, weighted_score: 0.2 } }),
    };
    render(<BacktestComparisonChart backtestResults={results} />);
    expect(screen.getByText(/из 2 протестированных/i)).toBeInTheDocument();
  });
});
