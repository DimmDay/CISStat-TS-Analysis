import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";

import { EdaModelMatrixOverview, type EdaModelMatrixResponse } from "./EdaModelMatrixOverview";


const criterion = (id: string, status: "pass" | "attention" | "fail" | "unknown" | "not_required") => ({
  id, label: id, status, observed: "наблюдение", requirement: "требование",
  conclusion: "вывод", blocking: status === "fail",
});

const PROFILE: EdaModelMatrixResponse = {
  column: "Price", applicable: true, reason: null, task: "forecast", horizon: 12,
  spec_version: "1.0.0-draft",
  profile: {
    n_observations: 240, missing_count: 0, numeric_series_count: 2, n_exogenous: 1,
    order_source: "time_column", order_column: "Date", frequency: "MS", is_regular: true,
    temporal_status: "regular", seasonality_status: "present", seasonal_periods: [12],
    stationarity_status: "stationary", has_negative_values: false,
  },
  summary: { total_models: 24, candidates: 5, conditional: 8, blocked: 11, ready: 9, catalog_only: 15 },
  families: [
    { family_id: "baselines", family_name: "Базовые модели", candidates: 2, conditional: 1, blocked: 1, ready: 4, catalog_only: 0 },
    { family_id: "tree_ml", family_name: "Деревья и бустинг", candidates: 0, conditional: 4, blocked: 0, ready: 0, catalog_only: 4 },
  ],
  models: [
    { model_id: "naive", model_name: "Naive", family_id: "baselines", family_name: "Базовые модели", compatibility: "candidate", platform_status: "ready", min_observations: 2, supports_exogenous: false, libraries: [], training_time: "instant", criteria: [criterion("history", "pass"), criterion("task", "pass"), criterion("platform", "pass")], blocking_reasons: [], cautions: [] },
    { model_id: "xgboost", model_name: "XGBoost", family_id: "tree_ml", family_name: "Деревья и бустинг", compatibility: "conditional", platform_status: "catalog_only", min_observations: 100, supports_exogenous: true, libraries: ["xgboost"], training_time: "seconds_to_minutes", criteria: [criterion("history", "pass"), criterion("features", "attention"), criterion("platform", "attention")], blocking_reasons: [], cautions: ["Нужны лаговые признаки"] },
    { model_id: "var", model_name: "VAR", family_id: "multivariate", family_name: "Многомерные", compatibility: "blocked", platform_status: "catalog_only", min_observations: 100, supports_exogenous: true, libraries: ["statsmodels"], training_time: "seconds", criteria: [criterion("task", "fail"), criterion("platform", "attention")], blocking_reasons: ["Выбран одномерный прогноз"], cautions: [] },
  ],
  shortlist: ["naive", "xgboost"], runnable_shortlist: ["naive"],
  recommendation: "Сравните shortlist на временных folds.",
  methodology_note: "Матрица проверяет предпосылки, но не прогнозную точность.",
  warnings: [],
};

const PARAMETERS = { task: "forecast" as const, horizon: 12 };


describe("EdaModelMatrixOverview", () => {
  it("visualizes requirements, families, shortlist and exact matrix from one response", () => {
    render(<EdaModelMatrixOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={PARAMETERS} onParametersChange={jest.fn()} />);

    expect(screen.getByRole("table", { name: "Тепловая карта применимости моделей" })).toBeInTheDocument();
    expect(screen.getByText("Naive")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Семейства" }));
    expect(screen.getByRole("img", { name: "Сводка применимости по семействам" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Shortlist" }));
    expect(screen.getByRole("heading", { name: "XGBoost" })).toBeInTheDocument();
    expect(screen.getByText(/только каталог/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Детали" }));
    expect(screen.getByRole("table", { name: "Детальные выводы матрицы моделей" })).toBeInTheDocument();
  });

  it("updates task and horizon without another target selector", () => {
    const onChange = jest.fn();
    render(<EdaModelMatrixOverview profile={PROFILE} loading={false} error={null} noDataset={false} parameters={PARAMETERS} onParametersChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Задача"), { target: { value: "volatility" } });
    expect(onChange).toHaveBeenCalledWith({ task: "volatility" });
    fireEvent.change(screen.getByLabelText("Горизонт"), { target: { value: "24" } });
    expect(onChange).toHaveBeenCalledWith({ horizon: 24 });
    expect(screen.queryByLabelText(/исследуемый признак/i)).not.toBeInTheDocument();
  });
});
