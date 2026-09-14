import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";

import { PreprocessingRegularityOverview } from "./PreprocessingRegularityOverview";

const PROFILE_RESPONSE = {
  mode: "auto",
  status: "warning",
  status_reason: null,
  profile: {
    applicable: true,
    applicability_message: null,
    date_column: "Date",
    entity_column: null,
    target_frequency: "MS",
    detected_frequency: "MS",
    gap_threshold_multiplier: 1.5,
    is_sorted: true,
    sort_violations: 0,
    invalid_date_count: 0,
    duplicate_count: 0,
    gap_count: 1,
    missing_period_count: 1,
    total_violations: 1,
    groups: [
      {
        group: "Весь датасет", observations: 11, inferred_frequency: "MS", modal_interval: "31 days",
        gap_count: 1, missing_period_count: 1, duplicate_count: 0, sort_violations: 0, gap_examples: [],
      },
    ],
    supported_actions: ["sort", "interpolate", "ffill", "bfill", "asfreq", "fictitious_zero", "flag"],
  },
};

describe("PreprocessingRegularityOverview", () => {
  it("renders the group table with gap counts", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) });
    render(<PreprocessingRegularityOverview refreshKey={1} />);

    expect(await screen.findByRole("table", { name: "Регулярность по группам" })).toBeInTheDocument();
    expect(screen.getByText("Найдены проблемы")).toBeInTheDocument();
    expect(screen.getByText(/Временная ось: Date/)).toBeInTheDocument();
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
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) });
    render(<PreprocessingRegularityOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Регулярность по группам" });

    const tablist = screen.getByRole("tablist", { name: "Представления проверки регулярности" });
    expect(tablist).toHaveClass("mt-3", "flex", "flex-wrap", "gap-2");
    expect(tablist.parentElement).toHaveClass("p-4");
    expect(tablist.parentElement?.className).toContain("border-b border-neutral-100");

    const active = screen.getByRole("tab", { name: "Таблица" });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(active).toHaveClass("border-neutral-300", "bg-neutral-200", "text-neutral-800");

    const inactive = screen.getByRole("tab", { name: "Интервалы" });
    expect(inactive).toHaveAttribute("aria-selected", "false");
    expect(inactive).toHaveClass("rounded-full", "border", "px-3", "py-1", "text-xs");
    expect(inactive).toHaveClass("border-neutral-200", "bg-neutral-50", "text-neutral-500", "hover:bg-neutral-100");
  });

  it("explains when no date column was detected", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        mode: "auto", status: "skipped", status_reason: "not_required",
        profile: { ...PROFILE_RESPONSE.profile, applicable: false, applicability_message: "Не найдена колонка с датой.", date_column: null, groups: [] },
      }),
    });
    render(<PreprocessingRegularityOverview refreshKey={1} />);
    expect(await screen.findByText("Не найдена колонка с датой.")).toBeInTheDocument();
  });

  it("shows a neutral explanation when disabled", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE_RESPONSE, mode: "disabled", status: "skipped", status_reason: "disabled" }),
    });
    render(<PreprocessingRegularityOverview refreshKey={1} />);
    expect(await screen.findByRole("status")).toHaveTextContent("отключена аналитиком");
  });

  it("shows an alert when the profile request fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: "нет датасета" }) });
    render(<PreprocessingRegularityOverview refreshKey={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет датасета");
  });

  it("switches to the intervals chart tab", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) });
    render(<PreprocessingRegularityOverview refreshKey={1} />);
    await screen.findByRole("table", { name: "Регулярность по группам" });

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ group: "Весь датасет", bins: [{ x0: 0, x1: 100, count: 3 }], modal_seconds: 50, threshold_seconds: 75 }),
    });
    fireEvent.click(screen.getByRole("tab", { name: "Интервалы" }));

    expect(await screen.findByText(/распределение интервалов/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Регулярность по группам" })).not.toBeInTheDocument();
  });
});
