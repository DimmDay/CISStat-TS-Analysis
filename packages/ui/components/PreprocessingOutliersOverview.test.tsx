import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";

import { PreprocessingOutliersOverview } from "./PreprocessingOutliersOverview";

const PROFILE = {
  rule_source: "system",
  mode: "auto",
  status: "warning",
  status_reason: null,
  method: "iqr",
  total_rows: 21,
  total_numeric_columns: 2,
  total_outliers: 1,
  outlier_rate_pct: 2.4,
  affected_columns: ["Price"],
  columns: [
    {
      column: "Price", sample_size: 21, outlier_count: 1, outlier_pct: 4.76,
      recommended_method: "iqr", bounds: { lower: -5, upper: 25 },
      outlier_examples: [20], insufficient_sample: false,
    },
    {
      column: "Clean", sample_size: 21, outlier_count: 0, outlier_pct: 0,
      recommended_method: "iqr", bounds: { lower: -3, upper: 30 },
      outlier_examples: [], insufficient_sample: false,
    },
  ],
};

describe("PreprocessingOutliersOverview", () => {
  it("renders a per-column outlier table with bounds", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<PreprocessingOutliersOverview refreshKey={1} />);

    expect(await screen.findByRole("table", { name: "Выбросы по числовым колонкам" })).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
    expect(screen.getByText("Пройдено")).toBeInTheDocument();
    expect(screen.getByText("-5.00 … 25.00")).toBeInTheDocument();
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
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });

    const tablist = screen.getByRole("tablist", { name: "Представления проверки выбросов" });
    expect(tablist).toHaveClass("mt-3", "flex", "flex-wrap", "gap-2");
    expect(tablist.parentElement).toHaveClass("p-4");
    expect(tablist.parentElement?.className).toContain("border-b border-neutral-100");

    const active = screen.getByRole("tab", { name: "Таблица" });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(active).toHaveClass("border-neutral-300", "bg-neutral-200", "text-neutral-800");

    const inactive = screen.getByRole("tab", { name: "Линейный" });
    expect(inactive).toHaveAttribute("aria-selected", "false");
    expect(inactive).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(inactive).toHaveClass("border-neutral-200", "bg-neutral-50", "text-neutral-500", "hover:bg-neutral-100");
  });

  it("explains when there are no numeric columns", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, columns: [] }),
    });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    expect(await screen.findByText(/нет числовых колонок/i)).toBeInTheDocument();
  });

  it("shows a neutral explanation when the check is disabled", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, mode: "disabled", status: "skipped", status_reason: "disabled" }),
    });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    expect(await screen.findByRole("status")).toHaveTextContent("отключена аналитиком");
  });

  it("shows an alert when the profile request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: "нет датасета" }) });
    render(<PreprocessingOutliersOverview refreshKey={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет датасета");
  });

  it("switches to a chart tab and shows the globally selected feature", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
    render(<PreprocessingOutliersOverview refreshKey={1} column="Price" />);
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ bins: [{ x0: 0, x1: 10, count: 3 }], bounds: null }),
    });
    fireEvent.click(screen.getByRole("tab", { name: "Гистограмма" }));

    expect(await screen.findByText(/Признак:/)).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Выбросы по числовым колонкам" })).not.toBeInTheDocument();
  });
});
