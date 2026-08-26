import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationTextQualityPipeline } from "./ValidationTextQualityPipeline";


const PROFILE = {
  rule_source: "system",
  columns: [{
    column: "Country", total_count: 3, valid_count: 2, invalid_count: 1,
    invalid_pct: 33.33, min_length: 1, max_length: 500,
    issue_counts: { garbage: 1, empty: 0, too_short: 0, too_long: 0, whitespace: 0, pattern: 0 },
    invalid_examples: ["bad\\u0000"],
    supported_actions: ["normalize", "replace_null", "drop_rows", "replace_unknown", "flag"],
  }],
};

const PREVIEW = {
  applied: false, strategy: "normalize", total_violations: 1, total_changed: 1,
  total_still_invalid: 0, rows_removed: 0, added_columns: [],
  columns: [{ column: "Country", invalid_count: 1, changed_count: 1, still_invalid: 0, flag_column: null }],
  profile: [{ ...PROFILE.columns[0], valid_count: 3, invalid_count: 0, invalid_pct: 0, invalid_examples: [] }],
};


describe("ValidationTextQualityPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
  });

  it("renders the four-step text correction flow", async () => {
    render(<ValidationTextQualityPipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления целостности текста" })).toBeInTheDocument();
    expect(screen.getByText("1. Колонки и нарушения")).toBeInTheDocument();
    expect(screen.getByText("2. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByText("3. Предпросмотр")).toBeInTheDocument();
    expect(screen.getByText("4. Применение")).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Выбрать колонку Country" })).toBeChecked();
    expect(screen.getByRole("option", { name: "Очистить и нормализовать" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Только отметить флагом" })).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<ValidationTextQualityPipeline onApplied={onApplied} />);

    await screen.findByText("Country");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Исправлено значений: 1")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      2, expect.stringContaining("/v1/session/dataset/text-quality-corrections"),
      expect.objectContaining({ body: JSON.stringify({ columns: ["Country"], strategy: "normalize", apply: false }) })
    );
    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("shows that a clean profile needs no correction", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE, columns: [{ ...PROFILE.columns[0], invalid_count: 0, valid_count: 3 }] }),
    });
    render(<ValidationTextQualityPipeline onApplied={jest.fn()} />);

    expect(await screen.findByText(/Нарушения целостности текста не найдены/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Предпросмотр изменений" })).toBeDisabled();
  });
});
