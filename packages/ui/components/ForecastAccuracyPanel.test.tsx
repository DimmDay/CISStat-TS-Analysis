// packages/ui/components/ForecastAccuracyPanel.test.tsx
//
// Панель «Ожидаемая точность» (spec_forecasting2.md §5.4):
//  - обязательная дисклоужер-подпись «по результатам бэктеста»;
//  - сетка метрик из карты + mse=rmse^2;
//  - честное покрытие: значение или явное «недоступно для метода».

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ForecastAccuracyPanel } from "./ForecastAccuracyPanel";
import type { ForecastRun } from "../lib/forecasting";

function makeRun(overrides: Partial<ForecastRun> = {}): ForecastRun {
  return {
    forecast_id: "f-1",
    model_card_id: "c-1",
    model_id: "naive",
    model_name: "Naive",
    generated_at: "2026-09-14T10:00:00+00:00",
    horizon: 3,
    alpha: 0.05,
    alpha_effective: 0.05,
    alpha_source: "requested",
    ci_method: "empirical_oof_quantile",
    points: [],
    history: { labels: [], values: [] },
    expected_accuracy: { mae: 2.5, rmse: 3.2, mape: 4.1, mase: 0.9, mse: 10.24 },
    prediction_interval_coverage: 0.94,
    warnings: [],
    trace_events: [],
    lineage: {},
    sensitivity: null,
    ...overrides,
  } as ForecastRun;
}

describe("ForecastAccuracyPanel", () => {
  it("обязательная оговорка «по результатам бэктеста» видна (§5.4)", () => {
    render(<ForecastAccuracyPanel run={makeRun()} />);
    const disclaimer = screen.getByTestId("accuracy-disclaimer");
    expect(disclaimer).toHaveTextContent(/по результатам бэктеста/);
    expect(disclaimer).toHaveTextContent(/не точность этого прогноза/);
  });

  it("показывает исторические метрики карты без пересчёта", () => {
    render(<ForecastAccuracyPanel run={makeRun()} />);
    expect(screen.getByTestId("accuracy-mae")).toHaveTextContent("2.5000");
    expect(screen.getByTestId("accuracy-rmse")).toHaveTextContent("3.2000");
    expect(screen.getByTestId("accuracy-mape")).toHaveTextContent("4.1000");
    expect(screen.getByTestId("accuracy-mase")).toHaveTextContent("0.9000");
    expect(screen.getByTestId("accuracy-mse")).toHaveTextContent("10.2400");
  });

  it("пустая метрика честно отображается прочерком", () => {
    const run = makeRun({ expected_accuracy: { mae: null, rmse: null } });
    render(<ForecastAccuracyPanel run={run} />);
    expect(screen.getByTestId("accuracy-mae")).toHaveTextContent("—");
  });

  it("покрытие интервалов показывается процентом, когда посчитано", () => {
    render(<ForecastAccuracyPanel run={makeRun()} />);
    expect(screen.getByTestId("coverage")).toHaveTextContent("94.0%");
  });

  it("для не-эмпирического метода покрытие честно помечено недоступным", () => {
    const run = makeRun({ ci_method: "analytic", prediction_interval_coverage: null });
    render(<ForecastAccuracyPanel run={run} />);
    expect(screen.getByTestId("coverage")).toHaveTextContent(/недоступно для этого метода/);
  });
});
