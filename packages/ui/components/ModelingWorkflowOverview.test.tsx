import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ModelingWorkflowOverview } from "./ModelingWorkflowOverview";


const ranking = [
  { rank: 1, model_id: "drift", model_name: "Drift", family_id: "baselines", metrics: { mae: 1, rmse: 1.2, mape: 2, mase: 0.8 }, weighted_score: 0, baseline_eligible: true, baseline_note: "лучше Naive" },
  { rank: 2, model_id: "naive", model_name: "Naive", family_id: "baselines", metrics: { mae: 2, rmse: 2.2, mape: 3, mase: 1 }, weighted_score: 1, baseline_eligible: true, baseline_note: "сопоставима" },
];

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

beforeEach(() => {
  jest.clearAllMocks();
});

test("runs comparison and renders transparent ranking", async () => {
  mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ comparison_id: "cmp-1", normalization: "min_max_within_comparable_pool", metric_weights: {}, ranking, warnings: [] }) });
  render(<ModelingWorkflowOverview stageId="comparison" modelIds={["naive", "drift"]} />);

  fireEvent.click(screen.getByRole("button", { name: "Сравнить модели" }));

  await waitFor(() => expect(screen.getByText("Drift")).toBeInTheDocument());
  expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining("/v1/session/modeling/compare"), expect.objectContaining({ credentials: "include" }));
  expect(screen.getByText(/min-max внутри сопоставимого пула/)).toBeInTheDocument();
});


test("selects a ranked model and generates downloadable Model Card", async () => {
  mockFetch
    .mockResolvedValueOnce({ ok: true, json: async () => ({ comparison_id: "cmp-1", normalization: "min_max_within_comparable_pool", metric_weights: {}, ranking, warnings: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ selected_model_id: "drift", ensemble_recommended: false }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ card_id: "card-1", card: { model_info: { model_id: "drift" } } }) });
  const { rerender } = render(<ModelingWorkflowOverview stageId="selection" modelIds={["naive", "drift"]} />);
  fireEvent.click(screen.getByRole("button", { name: "Загрузить рейтинг" }));
  await waitFor(() => screen.getByRole("button", { name: "Выбрать Drift" }));
  fireEvent.click(screen.getByRole("button", { name: "Выбрать Drift" }));
  await waitFor(() => expect(screen.getByText("Выбрана модель: drift")).toBeInTheDocument());

  rerender(<ModelingWorkflowOverview stageId="model_card" modelIds={["naive", "drift"]} />);
  fireEvent.click(screen.getByRole("button", { name: "Сформировать Model Card" }));
  await waitFor(() => expect(screen.getByText("card-1")).toBeInTheDocument());
  expect(screen.getByText(/"model_id": "drift"/)).toBeInTheDocument();
});
