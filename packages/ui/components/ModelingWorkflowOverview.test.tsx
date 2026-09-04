import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ModelingWorkflowOverview } from "./ModelingWorkflowOverview";


const ranking = [
  { rank: 1, model_id: "drift", model_name: "Drift", family_id: "baselines", applicability_level: "RECOMMENDED", metrics: { mae: 1, rmse: 1.2, mape: 2, mase: 0.8 }, normalized_metrics: { mae: 0, rmse: 0, mape: 0, mase: 0 }, weighted_score: 0, baseline_eligible: true, baseline_note: "лучше Naive", backtest_run_id: "run-drift", diagnostics: { overall_status: "pass", passed: ["ljung_box", "jarque_bera", "arch_lm", "durbin_watson"], warnings: [], failed: [], not_applicable: [], diagnostics_signature: "diag-drift" }, fold_stability: { metric: "rmse", fold_values: [1.1, 1.3], mean: 1.2, std: 0.1, coefficient_of_variation: 0.0833, fold_ranks: [1, 1], mean_rank: 1, rank_std: 0, top1_rate: 1 } },
  { rank: 2, model_id: "naive", model_name: "Naive", family_id: "baselines", applicability_level: "CONDITIONALLY_APPLICABLE", metrics: { mae: 2, rmse: 2.2, mape: 3, mase: 1 }, normalized_metrics: { mae: 1, rmse: 1, mape: 1, mase: 1 }, weighted_score: 1, baseline_eligible: true, baseline_note: "сопоставима", backtest_run_id: "run-naive", diagnostics: { overall_status: "warning", passed: ["ljung_box", "durbin_watson"], warnings: ["jarque_bera"], failed: [], not_applicable: ["arch_lm"], diagnostics_signature: "diag-naive" }, fold_stability: { metric: "rmse", fold_values: [2, 2.4], mean: 2.2, std: 0.2, coefficient_of_variation: 0.0909, fold_ranks: [2, 2], mean_rank: 2, rank_std: 0, top1_rate: 0 } },
];

const comparison = {
  comparison_id: "cmp-1",
  comparison_signature: "comparison-abcdef",
  fingerprint: "fingerprint-123",
  cohort_id: "cohort-123456",
  normalization: "min_max_within_comparable_pool",
  ranking_policy: "forecast_metrics_only_diagnostics_separate",
  diagnostics_policy: "current_oof_report_required_not_scored",
  metric_weights: { mae: 0.35, rmse: 0.25, mape: 0.2, mase: 0.2 },
  ranking,
  error_correlation: {
    model_ids: ["drift", "naive"], n_points: 6,
    values: [[1, 0.42], [0.42, 1]], unavailable_pairs: [],
  },
  warnings: [],
};

const selectionAnalysis = {
  selection_analysis_id: "selection-123",
  selection_signature: "selection-signature-abcdef",
  comparison_id: comparison.comparison_id,
  comparison_signature: comparison.comparison_signature,
  cohort_id: comparison.cohort_id,
  policy: {
    version: "selection-v1-equal-weight", primary_metric: "rmse",
    max_member_relative_gap: 0.1, max_error_correlation: 0.8,
    min_oof_points: 8, min_ensemble_relative_improvement: 0.01,
    min_fold_win_rate: 0.5, practical_tie_relative: 0.01,
  },
  recommended_single: {
    model_id: "drift", primary_metric: "rmse", primary_loss: 1.2,
    practical_ties: ["drift"], relative_improvement_vs_best_baseline: 0.4545,
  },
  best_baseline: { model_id: "naive", primary_metric: "rmse", primary_loss: 2.2 },
  ensemble: {
    status: "not_eligible", strategy: "simple_average", member_ids: ["drift", "naive"],
    weights: [0.5, 0.5], error_correlation: 0.91,
    relative_improvement_vs_best_single: null, relative_improvement_vs_best_baseline: null,
    fold_win_rate: null, backtest: null, diagnostics: null,
    reasons: ["Корреляция OOF-ошибок выше порога диверсификации."],
  },
  recommended_candidate: { kind: "single", model_id: "drift" },
  evaluation_contract: {
    source: "exact_aligned_selection_oof", estimate_status: "selection_oof_reused",
    independent_holdout: false, requires_acknowledgement: true,
  },
  warnings: ["Tuning и selection используют один OOF cohort; итоговая оценка может быть оптимистичной."],
};

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

beforeEach(() => {
  jest.clearAllMocks();
});

test("shows the exact EDA cohort used by tuning", async () => {
  const onBacktestPromoted = jest.fn();
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      model_id: "ets", best_params: { trend: "add" }, strategy: "sliding",
      cohort_id: "cohort-1234567890", folds: [
        { fold: 1, train_start: 10, train_end: 49, test_start: 51, test_end: 52, gap: 1 },
        { fold: 2, train_start: 12, train_end: 51, test_start: 53, test_end: 54, gap: 1 },
      ],
      preprocessing: { fit_policy: "per_train_fold", evaluation_scale: "value" },
      promoted_backtest: { model_id: "ets", metrics: {}, oof_predictions: [] },
    }),
  });
  render(<ModelingWorkflowOverview stageId="tuning" modelIds={["ets"]} onBacktestPromoted={onBacktestPromoted} />);

  fireEvent.click(screen.getByRole("button", { name: "Запустить тюнинг" }));

  await waitFor(() => expect(screen.getByTestId("tuning-plan-summary")).toBeInTheDocument());
  expect(screen.getByTestId("tuning-plan-summary")).toHaveTextContent("sliding");
  expect(screen.getByTestId("tuning-plan-summary")).toHaveTextContent("2 folds");
  expect(screen.getByTestId("tuning-plan-summary")).toHaveTextContent("per_train_fold");
  expect(screen.getByTestId("tuning-plan-summary")).toHaveTextContent("cohort-1234");
  expect(onBacktestPromoted).toHaveBeenCalledWith(expect.objectContaining({ model_id: "ets" }));
});

test("renders traceable OOF diagnostics for a baseline model", async () => {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      model_id: "naive", residuals_source: "backtest_oof",
      params_source: "model_default", cohort_id: "cohort-abcdef",
      params: {}, parameter_signature: "params-123",
      backtest_run_id: "run-123", residuals_signature: "residuals-123",
      preprocessing: { fit_policy: "per_train_fold", evaluation_scale: "value" },
      diagnostics: [
        { test: "ljung_box", applicable: true, statistic: 2.1, p_value: 0.71, status: "pass" },
        { test: "jarque_bera", applicable: true, statistic: 7.4, p_value: 0.025, status: "warning" },
        { test: "arch_lm", applicable: false, statistic: null, p_value: null, status: "warning", reason: "Недостаточно наблюдений" },
        { test: "durbin_watson", applicable: true, statistic: 1.9, p_value: null, status: "pass" },
      ],
    }),
  });
  render(<ModelingWorkflowOverview stageId="diagnostics" modelIds={["naive"]} />);

  expect(screen.getByRole("option", { name: "naive" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Проверить остатки" }));

  await waitFor(() => expect(screen.getByTestId("diagnostics-report")).toBeInTheDocument());
  expect(screen.getByTestId("diagnostics-lineage")).toHaveTextContent("backtest_oof");
  expect(screen.getByTestId("diagnostics-lineage")).toHaveTextContent("model_default");
  expect(screen.getByTestId("diagnostics-lineage")).toHaveTextContent("cohort-abcd");
  expect(screen.getByTestId("diagnostics-lineage")).toHaveTextContent("params-123");
  expect(screen.getByTestId("diagnostics-lineage")).toHaveTextContent("per_train_fold");
  expect(screen.getByText("Ljung–Box")).toBeInTheDocument();
  expect(screen.getByText("Jarque–Bera")).toBeInTheDocument();
  expect(screen.getByText("ARCH-LM")).toBeInTheDocument();
  expect(screen.getByText("Durbin–Watson")).toBeInTheDocument();
  expect(screen.getAllByText("Пройдено")).toHaveLength(2);
  expect(screen.getByText("Неприменимо")).toBeInTheDocument();
});

test("runs comparison and renders transparent ranking", async () => {
  mockFetch.mockResolvedValueOnce({ ok: true, json: async () => comparison });
  render(<ModelingWorkflowOverview stageId="comparison" modelIds={["naive", "drift"]} />);

  fireEvent.click(screen.getByRole("button", { name: "Сравнить модели" }));

  await waitFor(() => expect(screen.getByText("Drift")).toBeInTheDocument());
  expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining("/v1/session/modeling/compare"), expect.objectContaining({ credentials: "include" }));
  expect(screen.getByText(/min-max внутри сопоставимого пула/)).toBeInTheDocument();
  expect(screen.getByTestId("comparison-lineage")).toHaveTextContent("comparison-ab");
  expect(screen.getByTestId("comparison-ranking")).toHaveTextContent("1.200 ± 0.100");
  expect(screen.getByTestId("comparison-ranking")).toHaveTextContent("Рекомендована");
  expect(screen.getByTestId("comparison-ranking")).toHaveTextContent("Пройдено");
  expect(screen.getByTestId("comparison-ranking")).toHaveTextContent("Предупреждение");
  expect(screen.getByTestId("error-correlation-matrix")).toHaveTextContent("0.420");

  fireEvent.change(screen.getByLabelText("Фильтр диагностики"), { target: { value: "warning" } });
  expect(screen.queryByText("Drift")).not.toBeInTheDocument();
  expect(screen.getByText("Naive")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Фильтр диагностики"), { target: { value: "all" } });
  fireEvent.change(screen.getByLabelText("Фильтр применимости"), { target: { value: "RECOMMENDED" } });
  expect(screen.getByText("Drift")).toBeInTheDocument();
  expect(screen.queryByText("Naive")).not.toBeInTheDocument();
});

test("shows which diagnostics are missing from the comparable pool", async () => {
  mockFetch.mockResolvedValueOnce({
    ok: false,
    status: 409,
    json: async () => ({
      detail: {
        message: "Для comparison нужны diagnostics каждого backtest",
        missing_diagnostics: ["naive", "drift"],
      },
    }),
  });
  render(<ModelingWorkflowOverview stageId="comparison" modelIds={["naive", "drift"]} />);

  fireEvent.click(screen.getByRole("button", { name: "Сравнить модели" }));

  await waitFor(() => expect(screen.getByText(/naive, drift/)).toBeInTheDocument());
});


test("selects a ranked model and generates downloadable Model Card", async () => {
  mockFetch
    .mockResolvedValueOnce({ ok: true, json: async () => comparison })
    .mockResolvedValueOnce({ ok: true, json: async () => selectionAnalysis })
    .mockResolvedValueOnce({ ok: true, json: async () => ({
      selected_model_id: "drift", selected_kind: "single",
      selection_analysis_id: "selection-123", selection_signature: "selection-signature-abcdef",
      primary_metric: "rmse", primary_loss: 1.2, best_baseline_loss: 2.2,
      ensemble_status: "not_eligible", ensemble_recommended: false,
      ensemble_members: [], independent_holdout: false,
    }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ card_id: "card-1", card: { model_info: { model_id: "drift" } } }) });
  const { rerender } = render(<ModelingWorkflowOverview stageId="selection" modelIds={["naive", "drift"]} />);
  fireEvent.click(screen.getByRole("button", { name: "Загрузить рейтинг" }));
  await waitFor(() => screen.getByRole("button", { name: "Верифицировать выбор" }));
  fireEvent.click(screen.getByRole("button", { name: "Верифицировать выбор" }));
  await waitFor(() => expect(screen.getByTestId("selection-analysis")).toBeInTheDocument());
  expect(screen.getByTestId("selection-analysis")).toHaveTextContent("Selection SHA: selection-sig");
  expect(screen.getByTestId("selection-analysis")).toHaveTextContent("Baseline: naive (2.200)");
  expect(screen.getByTestId("ensemble-verdict")).toHaveTextContent("Не допущен к проверке");
  expect(screen.getByTestId("ensemble-verdict")).toHaveTextContent("Корреляция OOF-ошибок выше порога");
  expect(screen.getByRole("button", { name: "Выбрать Drift" })).toBeDisabled();
  fireEvent.click(screen.getByLabelText("Подтвердить отсутствие независимого holdout"));
  fireEvent.click(screen.getByRole("button", { name: "Выбрать Drift" }));
  await waitFor(() => expect(screen.getByText("Выбран кандидат (single): drift")).toBeInTheDocument());
  expect(mockFetch.mock.calls[2]?.[1]).toEqual(expect.objectContaining({
    body: expect.stringContaining('"selection_signature":"selection-signature-abcdef"'),
  }));

  rerender(<ModelingWorkflowOverview stageId="model_card" modelIds={["naive", "drift"]} />);
  fireEvent.click(screen.getByRole("button", { name: "Сформировать Model Card" }));
  await waitFor(() => expect(screen.getByText("card-1")).toBeInTheDocument());
  expect(screen.getByText(/"model_id": "drift"/)).toBeInTheDocument();
});
