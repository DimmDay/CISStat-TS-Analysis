import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationConsistencyPipeline } from "./ValidationConsistencyPipeline";


const PROFILE = {
  rule_source: "session",
  rules: [
    {
      rule_index: 0, rule_name: "Хронология по странам", rule_type: "chronology",
      description: "Годы возрастают", columns: ["Year"], time_column: "Year",
      group_column: "Country", applicable: true, applicability_message: null,
      checked_count: 4, valid_count: 3, invalid_count: 1, affected_rows: 2,
      invalid_examples: ["Country=A: 2022 → 2021"],
      supported_actions: ["sort_chronology", "drop_rows", "replace_null", "flag"],
    },
    {
      rule_index: 1, rule_name: "Цена неотрицательна", rule_type: "negative_price",
      description: "Цена неотрицательна", columns: ["Price"], time_column: null,
      group_column: null, applicable: true, applicability_message: null,
      checked_count: 5, valid_count: 5, invalid_count: 0, affected_rows: 0,
      invalid_examples: [], supported_actions: ["drop_rows", "replace_null", "flag"],
    },
  ],
};

const PREVIEW = {
  applied: false,
  strategy: "sort_chronology",
  total_violations: 1,
  total_changed: 3,
  total_still_invalid: 0,
  rows_removed: 0,
  added_columns: [],
  rules: [{
    rule_index: 0, rule_name: "Хронология по странам", invalid_count: 1,
    affected_rows: 2, changed_count: 3, still_invalid: 0, flag_column: null,
  }],
  profile: [{ ...PROFILE.rules[0], invalid_count: 0, affected_rows: 0, valid_count: 4, invalid_examples: [] }],
};


describe("ValidationConsistencyPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
  });

  it("renders the four-step rule correction flow", async () => {
    render(<ValidationConsistencyPipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления логики и хронологии" })).toBeInTheDocument();
    expect(await screen.findByText("1. Правила с нарушениями")).toBeInTheDocument();
    expect(screen.getByText("2. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByText("3. Предпросмотр")).toBeInTheDocument();
    expect(screen.getByText("4. Применение")).toBeInTheDocument();
    expect(await screen.findByRole("checkbox", { name: "Выбрать правило Хронология по странам" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Выбрать правило Цена неотрицательна" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "Восстановить хронологический порядок" })).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<ValidationConsistencyPipeline onApplied={onApplied} />);

    await screen.findByText("Хронология по странам");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Нарушений до: 1")).toBeInTheDocument();
    expect(screen.getByText("Нарушений после: 0")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/v1/session/dataset/consistency-corrections"),
      expect.objectContaining({ body: JSON.stringify({ rule_indices: [0], strategy: "sort_chronology", apply: false }) })
    );

    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("links to rule management when no rules apply", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ rule_source: "not_applicable", rules: [] }),
    });
    const onOpenRules = jest.fn();
    render(<ValidationConsistencyPipeline onApplied={jest.fn()} onOpenRules={onOpenRules} />);

    expect(await screen.findByText(/Эталон логики и хронологии не задан/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Открыть управление правилами" }));
    expect(onOpenRules).toHaveBeenCalledTimes(1);
  });

  it("shows the passed terminal state", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        ...PROFILE,
        rules: PROFILE.rules.map((item) => ({ ...item, invalid_count: 0, affected_rows: 0, invalid_examples: [] })),
      }),
    });
    render(<ValidationConsistencyPipeline onApplied={jest.fn()} />);

    expect(await screen.findByText(/Все применимые правила логики и хронологии соблюдены/i)).toBeInTheDocument();
    expect(screen.getByText(/Исправление не требуется/i)).toBeInTheDocument();
  });
});
