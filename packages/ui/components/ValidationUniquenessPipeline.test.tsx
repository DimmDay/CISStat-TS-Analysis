import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationUniquenessPipeline } from "./ValidationUniquenessPipeline";


const PROFILE = {
  rule_source: "session",
  profile: {
    applicable: true, applicability_message: null, mode: "composite_key",
    key_columns: ["Country", "Year"], total_rows: 3, valid_rows: 1,
    duplicate_rows: 2, duplicate_groups: 1, redundant_rows: 1,
    duplicate_pct: 66.67, supported_actions: ["keep_first", "keep_last", "drop_all", "aggregate", "flag"],
    groups: [{ key_values: { Country: "A", Year: "2020" }, occurrences: 2, redundant_rows: 1, row_numbers: [1, 2] }],
  },
};

const PREVIEW = {
  applied: false, strategy: "keep_first", duplicate_rows: 2, redundant_rows: 1,
  rows_changed: 1, rows_removed: 1, still_duplicate_rows: 0, added_columns: [],
  profile: { ...PROFILE.profile, total_rows: 2, valid_rows: 2, duplicate_rows: 0, duplicate_groups: 0, redundant_rows: 0, duplicate_pct: 0, groups: [] },
};


describe("ValidationUniquenessPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
  });

  it("renders a four-step correction master with Streamlit strategies", async () => {
    render(<ValidationUniquenessPipeline onApplied={jest.fn()} />);

    expect(await screen.findByRole("region", { name: "Мастер исправления уникальности" })).toBeInTheDocument();
    expect(screen.getByText("1. Ключ и группы дублей")).toBeInTheDocument();
    expect(screen.getByText("2. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByText("3. Предпросмотр")).toBeInTheDocument();
    expect(screen.getByText("4. Применение")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Удалить лишние копии — оставить первую" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Агрегировать: mean / first" })).toBeInTheDocument();
  });

  it("previews and applies only after explicit confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<ValidationUniquenessPipeline onApplied={onApplied} />);

    await screen.findByText("1 группа · 2 строки · 1 лишняя копия");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Строк в дублях до: 2")).toBeInTheDocument();
    expect(screen.getByText("Строк в дублях после: 0")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/v1/session/dataset/uniqueness-corrections"),
      expect.objectContaining({ body: JSON.stringify({ strategy: "keep_first", apply: false }) })
    );

    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("shows the terminal passed state", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, profile: { ...PROFILE.profile, valid_rows: 3, duplicate_rows: 0, duplicate_groups: 0, redundant_rows: 0, duplicate_pct: 0, groups: [] } }),
    });
    render(<ValidationUniquenessPipeline onApplied={jest.fn()} />);

    expect(await screen.findByText(/Дубликаты не найдены/i)).toBeInTheDocument();
    expect(screen.getByText(/Исправление не требуется/i)).toBeInTheDocument();
  });
});
