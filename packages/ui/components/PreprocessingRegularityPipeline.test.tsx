import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PreprocessingRegularityPipeline } from "./PreprocessingRegularityPipeline";

const PROFILE_RESPONSE = {
  mode: "auto", status: "warning", status_reason: null,
  profile: {
    applicable: true, applicability_message: null, date_column: "Date", entity_column: null,
    target_frequency: "MS", detected_frequency: "MS", gap_threshold_multiplier: 1.5,
    is_sorted: true, sort_violations: 0, invalid_date_count: 0, duplicate_count: 0,
    gap_count: 1, missing_period_count: 1, total_violations: 1, groups: [],
    supported_actions: ["sort", "interpolate", "ffill", "bfill", "asfreq", "fictitious_zero", "flag"],
  },
};

const CORRECTION_RESPONSE = {
  applied: false, strategy: "interpolate", frequency: "MS",
  rows_before: 11, rows_after: 12, rows_added: 1, duplicates_aggregated: 0,
  total_violations_before: 1, total_violations_after: 0,
  sort_violations_before: 0, sort_violations_after: 0,
  added_columns: [],
  profile: { ...PROFILE_RESPONSE.profile, gap_count: 0, total_violations: 0 },
};

describe("PreprocessingRegularityPipeline", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) });
  });

  it("renders the four-step correction flow with strategy and frequency", async () => {
    render(<PreprocessingRegularityPipeline onApplied={jest.fn()} />);

    expect(screen.getByRole("region", { name: "Мастер исправления регулярности" })).toBeInTheDocument();
    expect(await screen.findByRole("combobox", { name: "Стратегия исправления регулярности" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Целевая частота (pandas frequency alias)" })).toHaveValue("MS");
  });

  it("hides the frequency field for strategies that do not resample", async () => {
    render(<PreprocessingRegularityPipeline onApplied={jest.fn()} />);
    await screen.findByRole("combobox", { name: "Стратегия исправления регулярности" });

    fireEvent.change(screen.getByRole("combobox", { name: "Стратегия исправления регулярности" }), { target: { value: "sort" } });

    expect(screen.queryByRole("textbox", { name: "Целевая частота (pandas frequency alias)" })).not.toBeInTheDocument();
    expect(screen.getByText(/Не требуется для этой стратегии/)).toBeInTheDocument();
  });

  it("previews and applies only after confirmation", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(CORRECTION_RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...CORRECTION_RESPONSE, applied: true }) });
    const onApplied = jest.fn();
    render(<PreprocessingRegularityPipeline onApplied={onApplied} />);

    await screen.findByRole("combobox", { name: "Стратегия исправления регулярности" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Нарушений: 1 → 0")).toBeInTheDocument();

    const apply = screen.getByRole("button", { name: "Применить исправления" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(apply);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it("shows a positive terminal state when there are no violations", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...PROFILE_RESPONSE, status: "done", profile: { ...PROFILE_RESPONSE.profile, gap_count: 0, total_violations: 0 } }),
    });
    render(<PreprocessingRegularityPipeline onApplied={jest.fn()} />);
    expect(await screen.findByText(/Нарушений регулярности не найдено/)).toBeInTheDocument();
  });

  it("shows a neutral message when not applicable", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ mode: "auto", status: "skipped", status_reason: "not_required", profile: { ...PROFILE_RESPONSE.profile, applicable: false } }),
    });
    render(<PreprocessingRegularityPipeline onApplied={jest.fn()} />);
    expect(await screen.findByText(/мастер недоступен/)).toBeInTheDocument();
  });
});
