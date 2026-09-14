import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";

import { PreprocessingMissingOverview } from "./PreprocessingMissingOverview";

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
      column: "Price",
      dtype: "float64",
      semantic: "numeric",
      total_count: 4,
      missing_count: 2,
      non_missing_count: 2,
      missing_pct: 50,
      recommended_strategy: "median_mode",
      missing_examples: [1, 3],
    },
    {
      column: "Region",
      dtype: "object",
      semantic: "categorical",
      total_count: 4,
      missing_count: 0,
      non_missing_count: 4,
      missing_pct: 0,
      recommended_strategy: "none",
      missing_examples: [],
    },
  ],
  row_histogram: [{ missing_in_row: 1, row_count: 2 }],
};

describe("PreprocessingMissingOverview", () => {
  it("renders a completeness bar and per-column matrix", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<PreprocessingMissingOverview refreshKey={1} />);

    expect(await screen.findByRole("img", { name: /Заполнено ячеек: 6; пропусков: 2/i })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Матрица пропусков по колонкам" })).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
    expect(screen.getByText("Пройдено")).toBeInTheDocument();
    expect(screen.getByText("Заполнить медианой/модой")).toBeInTheDocument();
  });

  // Task w/n-3: бейдж-паттерн «Генерации признаков» (серые pill-бейджи с
  // рамкой, усиление фона при наведении) распространён на всю
  // «Предобработку». Контракт эталона
  // PreprocessingFeatureEngineeringOverview: tablist живёт ВНУТРИ шапки
  // Обзора (блок p-4 с border-b), классы mt-3 flex flex-wrap gap-2;
  // активный бейдж border-neutral-300 bg-neutral-200 text-neutral-800,
  // неактивный border-neutral-200 bg-neutral-50 text-neutral-500 с
  // hover:bg-neutral-100; семантика role="tab" + aria-selected.
  it("переключатели представлений следуют бейдж-паттерну «Генерации признаков»", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<PreprocessingMissingOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });

    const tablist = screen.getByRole("tablist", { name: "Представления проверки пропусков" });
    expect(tablist).toHaveClass("mt-3", "flex", "flex-wrap", "gap-2");
    expect(tablist.parentElement).toHaveClass("p-4");
    expect(tablist.parentElement?.className).toContain("border-b border-neutral-100");

    const active = screen.getByRole("tab", { name: "Таблица" });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(active).toHaveClass("border-neutral-300", "bg-neutral-200", "text-neutral-800");

    const inactive = screen.getByRole("tab", { name: "Матрица" });
    expect(inactive).toHaveAttribute("aria-selected", "false");
    expect(inactive).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(inactive).toHaveClass("border-neutral-200", "bg-neutral-50", "text-neutral-500", "hover:bg-neutral-100");
  });

  it("explains when the dataset has no columns", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        rule_source: "not_applicable",
        mode: "auto",
        status: "skipped",
        status_reason: "not_required",
        total_rows: 0,
        total_columns: 0,
        total_missing: 0,
        missing_rate_pct: null,
        rows_with_missing: 0,
        rows_with_missing_pct: null,
        empty_rows: 0,
        columns: [],
        row_histogram: [],
      }),
    });
    render(<PreprocessingMissingOverview refreshKey={1} />);

    expect(await screen.findByText(/проверка пропусков неприменима/i)).toBeInTheDocument();
  });

  it("shows a neutral explanation instead of the table when the check is disabled", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, mode: "disabled", status: "skipped", status_reason: "disabled" }),
    });
    render(<PreprocessingMissingOverview refreshKey={1} />);

    expect(await screen.findByRole("status")).toHaveTextContent("отключена аналитиком");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows an alert when the profile request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: "В сессии нет активного датасета" }) });
    render(<PreprocessingMissingOverview refreshKey={1} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("В сессии нет активного датасета");
  });

  it("switches to the matrix visualization tab and fetches its own data", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<PreprocessingMissingOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        columns: ["Price"],
        bins: [{ bin_index: 0, row_start: 0, row_end: 3, row_count: 4, missing_share: { Price: 0.5 } }],
        rows_per_bin: 4,
        total_rows: 4,
      }),
    });
    fireEvent.click(screen.getByRole("tab", { name: "Матрица" }));

    expect(await screen.findByText(/Каждый столбец матрицы/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Матрица пропусков по колонкам" })).not.toBeInTheDocument();
  });
});
