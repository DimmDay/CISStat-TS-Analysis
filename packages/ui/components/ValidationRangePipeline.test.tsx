import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationRangePipeline } from "./ValidationRangePipeline";

const PROFILE = {
  rule_source: "session",
  columns: [
    {
      column: "Price", rule_name: "Цена", min_allowed: 0, max_allowed: 100,
      actual_min: -5, actual_max: 80, total_count: 2, valid_count: 1,
      invalid_count: 1, invalid_pct: 50, invalid_examples: [-5],
    },
    {
      column: "Year", rule_name: "Год", min_allowed: 1990, max_allowed: 2030,
      actual_min: 2000, actual_max: 2024, total_count: 2, valid_count: 2,
      invalid_count: 0, invalid_pct: 0, invalid_examples: [],
    },
  ],
};

const PREVIEW = {
  applied: false,
  strategy: "clip",
  total_violations: 1,
  total_changed: 1,
  total_still_invalid: 0,
  rows_removed: 0,
  added_columns: [],
  columns: [{
    column: "Price", invalid_count: 1, changed_count: 1,
    still_invalid: 0, invalid_examples: [-5], flag_column: null,
  }],
  profile: [{ ...PROFILE.columns[0], actual_min: 0, invalid_count: 0, valid_count: 2, invalid_pct: 0, invalid_examples: [] }],
};

describe("ValidationRangePipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
  });

  it("renders the four-step correction flow", async () => {
    render(<ValidationRangePipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления диапазонов" })).toBeInTheDocument();
    expect(await screen.findByText("1. Правила и колонки")).toBeInTheDocument();
    expect(screen.getByText("2. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByText("3. Предпросмотр")).toBeInTheDocument();
    expect(screen.getByText("4. Применение")).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Выбрать колонку Price" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку Year" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "Кэпировать до границ" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Удалить строки с нарушениями" })).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<ValidationRangePipeline onApplied={onApplied} />);

    await screen.findByText("Price");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Исправлено значений: 1")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/v1/session/dataset/range-corrections"),
      expect.objectContaining({ body: JSON.stringify({ columns: ["Price"], strategy: "clip", apply: false }) })
    );

    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("links directly to rule management when no rules apply", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ rule_source: "not_applicable", columns: [] }),
    });
    const onOpenRules = jest.fn();
    render(<ValidationRangePipeline onApplied={jest.fn()} onOpenRules={onOpenRules} />);

    expect(await screen.findByText(/Эталон диапазонов не задан/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Открыть управление правилами" }));
    expect(onOpenRules).toHaveBeenCalledTimes(1);
  });

  it("shows a positive terminal state when all range rules pass", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        ...PROFILE,
        columns: PROFILE.columns.map((item) => ({ ...item, invalid_count: 0, invalid_pct: 0, invalid_examples: [] })),
      }),
    });
    render(<ValidationRangePipeline onApplied={jest.fn()} />);

    expect(await screen.findByText(/Все значения находятся в допустимых диапазонах/i)).toBeInTheDocument();
    expect(screen.getByText(/Исправление не требуется/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Предпросмотр изменений" })).toBeDisabled();
  });
});
