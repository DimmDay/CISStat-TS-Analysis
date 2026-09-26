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
      // PROGR-6: после preview фоном идёт POST /v1/progress/mentor/sanity-check
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ warnings: [] }) })
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

// ── PROGR-6 (§7.2): sanity-предупреждения Наставника в Мастере ────────

describe("PreprocessingRegularityPipeline + Наставник (PROGR-6)", () => {
  // Свежий fetch на каждый тест -- иначе mock.calls копятся между тестами.
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) });
  });

  function sanityCalls(): unknown[][] {
    return (global.fetch as unknown as jest.Mock).mock.calls.filter((call: unknown[]) =>
      String(call[0]).includes("/v1/progress/mentor/sanity-check"),
    );
  }

  it("после preview отправляет CorrectionOutcomeSummary (violations/rows из ответа, без статистик)", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) }) as unknown as typeof fetch;
    (global.fetch as unknown as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(CORRECTION_RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ warnings: [] }) });
    render(<PreprocessingRegularityPipeline onApplied={jest.fn()} />);

    await screen.findByRole("combobox", { name: "Стратегия исправления регулярности" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await waitFor(() => expect(sanityCalls()).toHaveLength(1));

    const [url, init] = sanityCalls()[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      stage: "preprocessing",
      node_id: "regularity",
      strategy: "interpolate",
      method: null,
      affected_count_before: 1,
      changed_count: 1, // 1 - 0: разность violations before/after
      still_affected_count: 0,
      rows_before: 11,
      rows_after: 12,
      stats_before: null, // статистик нет -- over_aggressive честно молчит
      stats_after: null,
    });
  });

  it("предупреждение рендерится НАД кнопкой применения и НЕ блокирует её (§12 п.8)", async () => {
    (global.fetch as unknown as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(CORRECTION_RESPONSE) })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            warnings: [
              {
                rule_id: "excessive_data_loss",
                severity: "warning",
                message: "Стратегия удалит 40% строк датасета.",
                suggested_action: "Проверьте порог.",
              },
            ],
          }),
      });
    render(<PreprocessingRegularityPipeline onApplied={jest.fn()} />);

    await screen.findByRole("combobox", { name: "Стратегия исправления регулярности" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Стратегия удалит 40% строк датасета.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    expect(screen.getByRole("button", { name: "Применить исправления" })).toBeEnabled();
  });

  it("сбой sanity-check не роняет Мастер (best-effort)", async () => {
    (global.fetch as unknown as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(PROFILE_RESPONSE) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(CORRECTION_RESPONSE) })
      .mockResolvedValueOnce({ ok: false, status: 503, json: () => Promise.resolve({}) });
    render(<PreprocessingRegularityPipeline onApplied={jest.fn()} />);

    await screen.findByRole("combobox", { name: "Стратегия исправления регулярности" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    expect(await screen.findByText("Нарушений: 1 → 0")).toBeInTheDocument();
    await waitFor(() => expect(sanityCalls()).toHaveLength(1));
    expect(
      screen.queryByRole("alert", { name: "Предупреждения Наставника" }),
    ).not.toBeInTheDocument();
  });
});
