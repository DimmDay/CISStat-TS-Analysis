// packages/ui/components/ForecastHistoryList.test.tsx
//
// История прогнозов: пустое состояние, элементы с параметрами,
// выбор активного и переключение чекбоксов сравнения.

import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";
import { ForecastHistoryList } from "./ForecastHistoryList";
import type { ForecastRun } from "../lib/forecasting";

function makeRun(id: string, name: string, overrides: Partial<ForecastRun> = {}): ForecastRun {
  return {
    forecast_id: id,
    model_card_id: "c-1",
    model_id: "naive",
    model_name: name,
    generated_at: "2026-09-14T10:00:00+00:00",
    horizon: 3,
    alpha: 0.05,
    alpha_effective: 0.05,
    alpha_source: "requested",
    ci_method: "empirical_oof_quantile",
    points: [],
    history: { labels: [], values: [] },
    expected_accuracy: {},
    prediction_interval_coverage: null,
    warnings: overrides.warnings ?? [],
    trace_events: [],
    lineage: {},
    sensitivity: null,
    ...overrides,
  } as ForecastRun;
}

describe("ForecastHistoryList", () => {
  it("пустая история -- честное пустое состояние", () => {
    render(
      <ForecastHistoryList
        forecasts={[]}
        activeForecastId={null}
        selectedForCompare={[]}
        onSelect={jest.fn()}
        onToggleCompare={jest.fn()}
      />,
    );
    expect(screen.getByTestId("forecast-history-empty")).toHaveTextContent(/Прогнозов пока нет/);
  });

  it("рендерит элементы с моделью, горизонтом и методом", () => {
    render(
      <ForecastHistoryList
        forecasts={[makeRun("f-1", "Naive"), makeRun("f-2", "ETS", { ci_method: "parametric_simulation" })]}
        activeForecastId="f-2"
        selectedForCompare={[]}
        onSelect={jest.fn()}
        onToggleCompare={jest.fn()}
      />,
    );
    const items = screen.getAllByTestId("forecast-history-item");
    expect(items).toHaveLength(2);
    expect(screen.getByText("ETS")).toBeInTheDocument();
    expect(screen.getByText(/parametric_simulation/)).toBeInTheDocument();
    // Активный элемент помечен aria-current.
    expect(screen.getByText("ETS").closest("button")).toHaveAttribute("aria-current", "true");
  });

  it("клик по элементу вызывает onSelect", () => {
    const onSelect = jest.fn();
    render(
      <ForecastHistoryList
        forecasts={[makeRun("f-1", "Naive")]}
        activeForecastId={null}
        selectedForCompare={[]}
        onSelect={onSelect}
        onToggleCompare={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Naive"));
    expect(onSelect).toHaveBeenCalledWith("f-1");
  });

  it("чекбокс сравнения вызывает onToggleCompare и озвучен для a11y", () => {
    const onToggle = jest.fn();
    render(
      <ForecastHistoryList
        forecasts={[makeRun("f-1", "Naive")]}
        activeForecastId={null}
        selectedForCompare={["f-1"]}
        onSelect={jest.fn()}
        onToggleCompare={onToggle}
      />,
    );
    const checkbox = screen.getByLabelText(/Выбрать прогноз Naive для сравнения/);
    expect(checkbox).toBeChecked();
    fireEvent.click(checkbox);
    expect(onToggle).toHaveBeenCalledWith("f-1");
  });

  it("первое предупреждение прогноза видно в истории", () => {
    render(
      <ForecastHistoryList
        forecasts={[makeRun("f-1", "Naive", { warnings: ["Горизонт 5 превышает проверенный бэктестом диапазон (2)"] })]}
        activeForecastId="f-1"
        selectedForCompare={[]}
        onSelect={jest.fn()}
        onToggleCompare={jest.fn()}
      />,
    );
    expect(screen.getByTestId("history-item-warning")).toHaveTextContent(/превышает проверенный/);
  });
});
