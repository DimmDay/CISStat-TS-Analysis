import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationInclusionPipeline } from "./ValidationInclusionPipeline";


const PROFILE = {
  rule_source: "session",
  columns: [{
    column: "Country", allowed_values: ["A", "B"], allowed_count: 2,
    total_count: 3, valid_count: 2, invalid_count: 1, invalid_pct: 33.33,
    invalid_values: [{ value: "X", count: 1 }], default_value: "A",
    default_valid: true, supported_actions: ["mode", "replace_null", "drop_rows", "replace_default", "flag"],
  }],
};

const PREVIEW = {
  applied: false, strategy: "mode", total_violations: 1, total_changed: 1,
  total_still_invalid: 0, rows_removed: 0, added_columns: [],
  columns: [{ column: "Country", invalid_count: 1, changed_count: 1, still_invalid: 0, replacement_value: "A", flag_column: null }],
  profile: [{ ...PROFILE.columns[0], valid_count: 3, invalid_count: 0, invalid_pct: 0, invalid_values: [] }],
};


describe("ValidationInclusionPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
  });

  it("renders the four-step domain correction flow", async () => {
    render(<ValidationInclusionPipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления принадлежности к набору" })).toBeInTheDocument();
    expect(screen.getByText("1. Правила и колонки")).toBeInTheDocument();
    expect(screen.getByText("2. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByText("3. Предпросмотр")).toBeInTheDocument();
    expect(screen.getByText("4. Применение")).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Выбрать колонку Country" })).toBeChecked();
    expect(screen.getByRole("option", { name: "Заменить модой допустимых значений" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Заменить значением по умолчанию" })).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<ValidationInclusionPipeline onApplied={onApplied} />);

    await screen.findByText("Country");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Исправлено значений: 1")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      2, expect.stringContaining("/v1/session/dataset/inclusion-corrections"),
      expect.objectContaining({ body: JSON.stringify({ columns: ["Country"], strategy: "mode", apply: false }) })
    );
    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("links to rule management when no domains apply", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true, json: () => Promise.resolve({ rule_source: "not_applicable", columns: [] }),
    });
    const onOpenRules = jest.fn();
    render(<ValidationInclusionPipeline onApplied={jest.fn()} onOpenRules={onOpenRules} />);

    expect(await screen.findByText(/Эталон допустимых наборов не задан/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Открыть управление правилами" }));
    expect(onOpenRules).toHaveBeenCalledTimes(1);
  });
});
