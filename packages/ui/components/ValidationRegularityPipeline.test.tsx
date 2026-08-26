import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ValidationRegularityPipeline } from "./ValidationRegularityPipeline";


const PROFILE = {
  rule_source: "session",
  profile: {
    applicable: true, applicability_message: null, date_column: "Date", entity_column: "Country",
    target_frequency: "D", detected_frequency: null, gap_threshold_multiplier: 1.5,
    is_sorted: true, sort_violations: 0, invalid_date_count: 0, duplicate_count: 0,
    gap_count: 1, missing_period_count: 1, total_violations: 1,
    groups: [{ group: "Country=A", observations: 3, inferred_frequency: null, modal_interval: "1 days", gap_count: 1, missing_period_count: 1, duplicate_count: 0, sort_violations: 0, gap_examples: [] }],
    supported_actions: ["sort", "interpolate", "ffill", "bfill", "asfreq", "fictitious_zero", "flag"],
  },
};

const PREVIEW = {
  applied: false, strategy: "interpolate", frequency: "D", rows_before: 6, rows_after: 7,
  rows_added: 1, duplicates_aggregated: 0, total_violations_before: 1, total_violations_after: 0,
  sort_violations_before: 0, sort_violations_after: 0, added_columns: [], profile: { ...PROFILE.profile, gap_count: 0, missing_period_count: 0, total_violations: 0 },
};


describe("ValidationRegularityPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE) });
  });

  it("renders the four-step regularity correction flow", async () => {
    render(<ValidationRegularityPipeline onApplied={jest.fn()} onOpenRules={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления равномерности шага" })).toBeInTheDocument();
    expect(screen.getByText("1. Ось времени и группы")).toBeInTheDocument();
    expect(screen.getByText("2. Стратегия исправления")).toBeInTheDocument();
    expect(screen.getByText("3. Предпросмотр")).toBeInTheDocument();
    expect(screen.getByText("4. Применение")).toBeInTheDocument();
    expect(await screen.findByText("Date")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Resample + Interpolate" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Только отметить флагом" })).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PREVIEW) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...PREVIEW, applied: true }) });
    const onApplied = jest.fn();
    render(<ValidationRegularityPipeline onApplied={onApplied} onOpenRules={jest.fn()} />);

    await screen.findByText("Date");
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Добавлено строк: 1")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenNthCalledWith(
      2, expect.stringContaining("/v1/session/dataset/regularity-corrections"),
      expect.objectContaining({ body: JSON.stringify({ strategy: "interpolate", frequency: "D", apply: false }) })
    );
    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("links to rules when a time axis is not configured", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({
      rule_source: "not_applicable", profile: { ...PROFILE.profile, applicable: false, applicability_message: "Не определена временная колонка", date_column: null, groups: [] },
    }) });
    const onOpenRules = jest.fn();
    render(<ValidationRegularityPipeline onApplied={jest.fn()} onOpenRules={onOpenRules} />);

    expect(await screen.findByText(/Не определена временная колонка/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Открыть управление правилами" }));
    expect(onOpenRules).toHaveBeenCalledTimes(1);
  });
});
