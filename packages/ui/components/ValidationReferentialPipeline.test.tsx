import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationReferentialPipeline } from "./ValidationReferentialPipeline";


const PROFILE = {
  rule_source: "session",
  rules: [{
    rule_index: 0, rule_name: "Код страны существует", child_column: "CountryCode",
    allowed_values: ["BY", "KZ"], reference_count: 2, applicable: true,
    applicability_message: null, total_count: 3, valid_count: 2, invalid_count: 1,
    invalid_pct: 33.33, invalid_values: [{ value: "XX", count: 1 }],
    default_value: "BY", default_valid: true,
    supported_actions: ["mode", "replace_null", "drop_rows", "replace_default", "flag"],
  }],
};

const PREVIEW = {
  applied: false, strategy: "mode", total_violations: 1, total_changed: 1,
  total_still_invalid: 0, rows_removed: 0, added_columns: [],
  rules: [{ rule_index: 0, rule_name: "Код страны существует", child_column: "CountryCode", invalid_count: 1, changed_count: 1, still_invalid: 0, replacement_value: "BY", flag_column: null }],
  profile: [{ ...PROFILE.rules[0], valid_count: 3, invalid_count: 0, invalid_pct: 0, invalid_values: [] }],
};


describe("ValidationReferentialPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
  });

  it("renders the four-step referential correction flow", async () => {
    render(<ValidationReferentialPipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления ссылочной целостности" })).toBeInTheDocument();
    expect(screen.getByText("1. Правила и связи")).toBeInTheDocument();
    expect(screen.getByText("2. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByText("3. Предпросмотр")).toBeInTheDocument();
    expect(screen.getByText("4. Применение")).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Выбрать правило Код страны существует" })).toBeChecked();
    expect(screen.getByRole("option", { name: "Заменить модой связанных значений" })).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<ValidationReferentialPipeline onApplied={onApplied} />);

    await screen.findByText("Код страны существует");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Исправлено значений: 1")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      2, expect.stringContaining("/v1/session/dataset/referential-corrections"),
      expect.objectContaining({ body: JSON.stringify({ rule_indices: [0], strategy: "mode", apply: false }) })
    );
    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("links to rule management when no reference applies", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true, json: () => Promise.resolve({ rule_source: "not_applicable", rules: [] }),
    });
    const onOpenRules = jest.fn();
    render(<ValidationReferentialPipeline onApplied={jest.fn()} onOpenRules={onOpenRules} />);

    expect(await screen.findByText(/Правила ссылочной целостности не заданы/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Открыть управление правилами" }));
    expect(onOpenRules).toHaveBeenCalledTimes(1);
  });
});

