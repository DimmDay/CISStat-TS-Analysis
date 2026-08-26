import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingMissingPipeline } from "./PreprocessingMissingPipeline";

const PROFILE = {
  rule_source: "system",
  mode: "auto",
  status: "warning",
  status_reason: null,
  total_rows: 4,
  total_columns: 2,
  total_missing: 2,
  missing_rate_pct: 25,
  rows_with_missing: 2,
  rows_with_missing_pct: 50,
  empty_rows: 0,
  columns: [
    {
      column: "Price", dtype: "float64", semantic: "numeric", total_count: 4,
      missing_count: 2, non_missing_count: 2, missing_pct: 50,
      recommended_strategy: "median_mode", missing_examples: [1, 3],
    },
    {
      column: "Region", dtype: "object", semantic: "categorical", total_count: 4,
      missing_count: 0, non_missing_count: 4, missing_pct: 0,
      recommended_strategy: "none", missing_examples: [],
    },
  ],
  row_histogram: [],
};

const PREVIEW = {
  applied: false,
  strategy: "median_mode",
  total_missing: 2,
  total_changed: 2,
  total_still_missing: 0,
  rows_removed: 0,
  added_columns: [],
  columns: [{
    column: "Price", missing_count: 2, changed_count: 2,
    still_missing: 0, missing_examples: [1, 3], flag_column: null,
    stats_before: { mean: 30, median: 28, std: 14.14 },
    stats_after: { mean: 30, median: 27, std: 11.55 },
  }],
  profile: [
    { ...PROFILE.columns[0], missing_count: 0, missing_pct: 0, missing_examples: [] },
    PROFILE.columns[1],
  ],
};

describe("PreprocessingMissingPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
  });

  it("renders the four-step correction flow with columns pre-selected", async () => {
    render(<PreprocessingMissingPipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления пропусков" })).toBeInTheDocument();
    expect(await screen.findByText("1. Колонки с пропусками")).toBeInTheDocument();
    expect(screen.getByText("2. Стратегия исправления")).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Выбрать колонку Price" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку Region" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "Линейная интерполяция" })).toBeInTheDocument();
  });

  it("disables non-numeric columns when interpolation is selected", async () => {
    render(<PreprocessingMissingPipeline onApplied={jest.fn()} />);
    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });

    fireEvent.change(screen.getByRole("combobox", { name: "Стратегия исправления пропусков" }), {
      target: { value: "interpolate" },
    });

    expect(screen.getByText("Интерполяция недоступна для нечисловой колонки")).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<PreprocessingMissingPipeline onApplied={onApplied} />);

    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Исправлено значений: 2")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/v1/session/dataset/missing-corrections"),
      expect.objectContaining({ body: JSON.stringify({ columns: ["Price"], strategy: "median_mode", apply: false }) })
    );

    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("shows the before/after impact forecast for numeric columns", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) });
    render(<PreprocessingMissingPipeline onApplied={jest.fn()} />);

    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));

    expect(await screen.findByText("Прогноз влияния на статистики")).toBeInTheDocument();
    expect(screen.getByText("30 → 30")).toBeInTheDocument(); // mean не меняется
    expect(screen.getByText(/14,14 → 11,55/)).toBeInTheDocument(); // std падает
  });

  it("shows a positive terminal state when there are no missing values", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, total_missing: 0, columns: PROFILE.columns.map((item) => ({ ...item, missing_count: 0, missing_pct: 0, missing_examples: [] })) }),
    });
    render(<PreprocessingMissingPipeline onApplied={jest.fn()} />);

    expect(await screen.findByText("Пропусков в датасете не найдено.")).toBeInTheDocument();
  });
});
