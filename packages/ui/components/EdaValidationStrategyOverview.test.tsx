import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { EdaValidationStrategyOverview, type EdaValidationStrategyResponse } from "./EdaValidationStrategyOverview";


const PROFILE: EdaValidationStrategyResponse = {
  column: "Price", applicable: true, reason: null, strategy: "expanding",
  horizon: 10, requested_splits: 3, effective_splits: 3, gap: 2,
  train_window: 40, min_train_observations: 20, n_observations: 100,
  missing_count: 0, required_observations: 52, initial_train_size: 68,
  unused_observations: 0, test_coverage: 30, order_source: "time_column",
  order_column: "Date", order_warning: null, frequency: "D", comparable_duration: true,
  folds: [
    { fold: 1, train_start: 0, train_end: 67, train_size: 68, gap_start: 68, gap_end: 69, gap_size: 2, test_start: 70, test_end: 79, test_size: 10, train_start_label: "2024-01-01", train_end_label: "2024-03-08", test_start_label: "2024-03-11", test_end_label: "2024-03-20" },
    { fold: 2, train_start: 0, train_end: 77, train_size: 78, gap_start: 78, gap_end: 79, gap_size: 2, test_start: 80, test_end: 89, test_size: 10, train_start_label: "2024-01-01", train_end_label: "2024-03-18", test_start_label: "2024-03-21", test_end_label: "2024-03-30" },
    { fold: 3, train_start: 0, train_end: 87, train_size: 88, gap_start: 88, gap_end: 89, gap_size: 2, test_start: 90, test_end: 99, test_size: 10, train_start_label: "2024-01-01", train_end_label: "2024-03-28", test_start_label: "2024-03-31", test_end_label: "2024-04-09" },
  ],
  alternatives: [
    { strategy: "expanding", label: "Расширяющееся окно", suitable: true, required_observations: 52, reason: "Максимум истории" },
    { strategy: "sliding", label: "Скользящее окно", suitable: true, required_observations: 72, reason: "Свежая история" },
    { strategy: "single", label: "Финальный holdout", suitable: true, required_observations: 32, reason: "Финальная оценка" },
  ],
  recommendation: "Expanding window использует всю доступную историю.",
  recommendations: ["Горизонт должен совпадать с эксплуатацией."], warnings: [],
};


const PARAMETERS = { strategy: "expanding" as const, horizon: 10, nSplits: 3, gap: 2, trainWindow: 40 };


describe("EdaValidationStrategyOverview", () => {
  it("visualizes folds, train growth, alternatives and exact table", () => {
    render(<EdaValidationStrategyOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={PARAMETERS} onParametersChange={jest.fn()} />);

    expect(screen.getByRole("img", { name: "Схема временных folds для Price" })).toBeInTheDocument();
    expect(screen.getAllByText("Train").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("tab", { name: "Размер train" }));
    expect(screen.getByRole("img", { name: "Рост обучающего окна для Price" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Альтернативы" }));
    expect(screen.getByRole("heading", { name: "Скользящее окно" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Таблица" }));
    expect(screen.getByRole("table", { name: "Границы временной валидации" })).toBeInTheDocument();
  });

  it("updates strategy and horizon without adding another target selector", () => {
    const onChange = jest.fn();
    render(<EdaValidationStrategyOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={PARAMETERS} onParametersChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Схема"), { target: { value: "sliding" } });
    expect(onChange).toHaveBeenCalledWith({ strategy: "sliding" });
    fireEvent.change(screen.getByLabelText("Горизонт"), { target: { value: "12" } });
    expect(onChange).toHaveBeenCalledWith({ horizon: 12 });
    expect(screen.queryByLabelText("Исследуемый признак:")).not.toBeInTheDocument();
  });

  it("shows an explainable insufficient-data state", () => {
    render(<EdaValidationStrategyOverview profile={{ ...PROFILE, applicable: false, reason: "Недостаточно наблюдений: нужно 120" }} loading={false} error={null} noDataset={false} parameters={PARAMETERS} onParametersChange={jest.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Недостаточно наблюдений");
  });
});
