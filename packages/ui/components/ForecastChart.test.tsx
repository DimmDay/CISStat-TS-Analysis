// packages/ui/components/ForecastChart.test.tsx
//
// График прогноза (§5.3): композиция факт + прогноз + область интервала +
// маркеры аномалий; подпись с уровнем интервала и методом.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { buildRows, ForecastChart } from "./ForecastChart";
import type { ForecastRun } from "../lib/forecasting";

// recharts ResponsiveContainer требует ResizeObserver (как BacktestOofChart.test).
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

function makeRun(overrides: Partial<ForecastRun> = {}): ForecastRun {
  return {
    forecast_id: "f-1",
    model_card_id: "c-1",
    model_id: "naive",
    model_name: "Naive",
    generated_at: "2026-09-14T10:00:00+00:00",
    horizon: 2,
    alpha: 0.05,
    alpha_effective: 0.05,
    alpha_source: "requested",
    ci_method: "empirical_oof_quantile",
    points: [
      { step: 1, date: "2026-01-01T00:00:00", value: 101, ci_lower: 98, ci_upper: 104, is_anomalous: false },
      { step: 2, date: "2026-02-01T00:00:00", value: 102, ci_lower: 98.5, ci_upper: 105.5, is_anomalous: true },
    ],
    history: {
      labels: ["2025-11-01T00:00:00", "2025-12-01T00:00:00"],
      values: [99.5, 100.5],
    },
    expected_accuracy: {},
    prediction_interval_coverage: null,
    warnings: [],
    trace_events: [],
    lineage: {},
    sensitivity: null,
    ...overrides,
  } as ForecastRun;
}

describe("ForecastChart", () => {
  it("рендерит контейнер с role=img и aria-label с моделью и горизонтом", () => {
    render(<ForecastChart run={makeRun()} />);
    const chart = screen.getByTestId("forecast-chart");
    expect(chart).toHaveAttribute("role", "img");
    expect(chart).toHaveAttribute("aria-label", expect.stringContaining("Naive"));
    expect(chart).toHaveAttribute("aria-label", expect.stringContaining("2 шагов"));
    // Прецедент BacktestOofChart.test: в jsdom ResponsiveContainer не
    // материализует svg (нулевые размеры) -- структурный контракт прижат
    // role/aria/caption, а не наличием svg.
  });

  it("подпись называет уровень интервала и метод", () => {
    render(<ForecastChart run={makeRun()} />);
    const caption = screen.getByText(/Чёрный — факт/).closest("p")!;
    expect(caption).toHaveTextContent("95%");
    expect(caption).toHaveTextContent("empirical_oof_quantile");
  });

  it("последняя фактическая точка соединяется с прогнозной линией (мост, §5.3) -- контракт данных", () => {
    // Мост -- производное данных buildRows (чистая функция, вынесена для
    // проверки без рендера): последняя строка истории получает прогноз=факт.
    const rows = buildRows(makeRun());
    expect(rows).toHaveLength(4); // 2 истории + 2 прогноза
    expect(rows[1]).toMatchObject({ actual: 100.5, forecast: 100.5 }); // мост
    expect(rows[0].forecast).toBeNull();
    expect(rows[2]).toMatchObject({ actual: null, forecast: 101 });
    expect(rows[3]).toMatchObject({ forecast: 102, ci_lower: 98.5 });
  });

  it("пустой список точек -- честное пустое состояние", () => {
    render(<ForecastChart run={makeRun({ points: [] })} />);
    expect(screen.getByText(/Прогнозные точки отсутствуют/)).toBeInTheDocument();
  });
});
