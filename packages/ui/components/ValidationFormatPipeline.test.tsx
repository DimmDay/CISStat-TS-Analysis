import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationFormatPipeline } from "./ValidationFormatPipeline";

const PROFILE = {
  rule_source: "session",
  columns: [
    {
      column: "Email",
      pattern: "^[^@]+@[^@]+$",
      threshold: 100,
      total_count: 2,
      valid_count: 1,
      invalid_count: 1,
      match_pct: 50,
      invalid_examples: ["broken"],
    },
    {
      column: "Phone",
      pattern: "^\\+7\\d{10}$",
      threshold: 100,
      total_count: 1,
      valid_count: 1,
      invalid_count: 0,
      match_pct: 100,
      invalid_examples: [],
    },
  ],
};

const PREVIEW = {
  applied: false,
  strategy: "replace_null",
  total_violations: 1,
  total_changed: 1,
  total_still_invalid: 0,
  added_columns: [],
  columns: [{
    column: "Email",
    invalid_count: 1,
    changed_count: 1,
    still_invalid: 0,
    invalid_examples: ["broken"],
    flag_column: null,
  }],
  profile: [{ ...PROFILE.columns[0], invalid_count: 0, valid_count: 1, match_pct: 100, invalid_examples: [] }],
};

describe("ValidationFormatPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
  });

  it("loads the active rules and renders the four-step Streamlit correction flow", async () => {
    render(<ValidationFormatPipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления форматов и шаблонов" })).toBeInTheDocument();
    expect(await screen.findByText("1. Правила и колонки")).toBeInTheDocument();
    expect(screen.getByText("2. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByText("3. Предпросмотр")).toBeInTheDocument();
    expect(screen.getByText("4. Применение")).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Выбрать колонку Email" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Выбрать колонку Phone" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Стратегия исправления" })).toBeEnabled();
  });

  it("previews and applies only after explicit confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<ValidationFormatPipeline onApplied={onApplied} />);

    await screen.findByText("Email");
    fireEvent.change(screen.getByRole("combobox", { name: "Стратегия исправления" }), {
      target: { value: "replace_null" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));

    expect(await screen.findByText("Исправлено значений: 1")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/v1/session/dataset/format-corrections"),
      expect.objectContaining({ body: JSON.stringify({ columns: ["Email"], strategy: "replace_null", apply: false }) })
    );

    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);

    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Изменения применены, проверка запущена повторно")).toBeInTheDocument();
  });

  it("explains when no format rules apply", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ rule_source: "not_applicable", columns: [] }),
    });
    const onOpenRules = jest.fn();
    render(<ValidationFormatPipeline onApplied={jest.fn()} onOpenRules={onOpenRules} />);

    expect(await screen.findByText(/Эталон форматов не задан/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Открыть управление правилами" }));
    expect(onOpenRules).toHaveBeenCalledTimes(1);
  });

  it("shows a positive terminal state when every active format rule passes", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        rule_source: "template",
        columns: PROFILE.columns.map((item) => ({
          ...item,
          valid_count: item.total_count,
          invalid_count: 0,
          match_pct: 100,
          invalid_examples: [],
        })),
      }),
    });
    render(<ValidationFormatPipeline onApplied={jest.fn()} />);

    expect(await screen.findByText(/Все значения соответствуют активным правилам форматов/i)).toBeInTheDocument();
    expect(screen.getByText(/Исправление не требуется/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Предпросмотр изменений" })).toBeDisabled();
  });
});
