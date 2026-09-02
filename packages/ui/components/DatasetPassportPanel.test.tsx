import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { DatasetPassportPanel } from "./DatasetPassportPanel";

const EMPTY_POINT = {
  captured: false,
  captured_at: null,
  is_stale: null,
  fingerprint: null,
  history_count: 0,
};

const START_POINT = {
  captured: true,
  captured_at: "2026-09-02T12:00:00+00:00",
  is_stale: true,
  fingerprint: "start-fingerprint",
  history_count: 1,
};

const READY_STATUS = {
  has_dataset: true,
  target_column: "value",
  date_column: "date",
  series_ready: true,
  reason: null,
  current_fingerprint: "current-fingerprint",
  start: START_POINT,
  validation: EMPTY_POINT,
  exit: EMPTY_POINT,
};

const DATE_RESPONSE = {
  date_column: "date",
  suggested_column: "date",
  candidates: [{ name: "date", score: 1 }],
  has_dataset: true,
  passport_history_reset: false,
};

const PASSPORT = {
  basic_stats: { n: 84, mean: 21.234, std: 2.5, min: 17, max: 27 },
  freq: { value: "D", is_regular: true },
  stationarity: { value: 0.012, is_stationary: true },
  determinism: { value: 0.73, is_deterministic: true },
  autocorrelation: { value: 0.003, is_white_noise: false },
  normality: { value: 0.18, is_normal: true },
  trend: { slope: 0.05, direction: "up" },
  seasonality: { strength: 0.67, is_seasonal: true },
  hurst: { value: 0.61, type: "persistent" },
  correlations: { top3: { companion: 0.91 } },
  fft: { dominant_periods: [7, 14] },
};

const CAPTURE_RESPONSE = {
  snapshot_id: "snapshot-1",
  stage: "start",
  passport: PASSPORT,
  fingerprint: "current-fingerprint",
  target_column: "value",
  date_column: "date",
  captured_at: "2026-09-02T12:05:00+00:00",
};

function response(body: unknown, ok = true, status = 200): Promise<Response> {
  return Promise.resolve({ ok, status, json: () => Promise.resolve(body) } as Response);
}

function mockPassportFetch(options?: {
  status?: Record<string, unknown>;
  date?: Record<string, unknown>;
  capture?: Record<string, unknown>;
  compare?: unknown;
}) {
  const status = options?.status ?? READY_STATUS;
  const date = options?.date ?? DATE_RESPONSE;
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    if (url.includes("/dataset/passport/status")) return response(status);
    if (url.includes("/date-column")) return response(date);
    if (url.includes("/dataset/passport/compare")) return response(options?.compare ?? {});
    if (url.includes("/dataset/passport/") && init?.method === "POST") {
      return response(options?.capture ?? CAPTURE_RESPONSE);
    }
    return response({ detail: "not found" }, false, 404);
  }) as unknown as typeof fetch;
}

describe("DatasetPassportPanel", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it.each([
    ["start", "Паспорт свойств ряда: Загрузка", "Рассчитать паспорт на загрузке"],
    ["validation", "Паспорт свойств ряда: Валидация", "Рассчитать паспорт после валидации"],
    ["exit", "Паспорт свойств ряда: Предобработка", "Рассчитать итоговый паспорт"],
  ] as const)("renders the %s panel outside a check status", async (stage, title, action) => {
    mockPassportFetch();

    render(<DatasetPassportPanel stage={stage} targetColumn="value" />);

    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: action })).toBeInTheDocument();
    expect(screen.queryByText(/проверка пройдена/i)).not.toBeInTheDocument();
  });

  it("persists a suggested date column before capturing start and renders the passport", async () => {
    const statusWithoutDate = {
      ...READY_STATUS,
      date_column: null,
      series_ready: false,
      reason: "Не выбрана временная колонка ряда",
      start: EMPTY_POINT,
    };
    const dateWithoutSelection = { ...DATE_RESPONSE, date_column: null };
    mockPassportFetch({ status: statusWithoutDate, date: dateWithoutSelection });

    render(<DatasetPassportPanel stage="start" targetColumn="value" suggestedDateColumn="date" />);

    const button = await screen.findByRole("button", { name: "Рассчитать паспорт на загрузке" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/v1/session/date-column"),
        expect.objectContaining({ method: "POST", body: JSON.stringify({ column: "date" }) }),
      );
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/dataset/passport/start"),
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(await screen.findByText("84")).toBeInTheDocument();
    expect(screen.getByText("0,012 · стационарен")).toBeInTheDocument();
    expect(screen.getByText("7; 14")).toBeInTheDocument();
  });

  it("keeps validation disabled until start exists and explains why", async () => {
    mockPassportFetch({ status: { ...READY_STATUS, start: EMPTY_POINT } });

    render(<DatasetPassportPanel stage="validation" targetColumn="value" />);

    const button = await screen.findByRole("button", { name: "Рассчитать паспорт после валидации" });
    await waitFor(() => {
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Сначала зафиксируйте паспорт на вкладке «Загрузка»");
    });
  });

  it("does not offer rewriting start after a downstream snapshot", async () => {
    const validation = { ...START_POINT, is_stale: true };
    mockPassportFetch({ status: { ...READY_STATUS, validation } });

    render(<DatasetPassportPanel stage="start" targetColumn="value" />);

    const button = await screen.findByRole("button", { name: "Рассчитать паспорт на загрузке" });
    await waitFor(() => {
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Baseline нельзя менять после фиксации следующей точки");
    });
  });

  it("disables an unchanged validation snapshot but allows a stale one", async () => {
    const validation = { ...START_POINT, fingerprint: "validation-fingerprint" };
    mockPassportFetch({ status: { ...READY_STATUS, validation: { ...validation, is_stale: false } } });
    const { rerender } = render(
      <DatasetPassportPanel stage="validation" targetColumn="value" />,
    );

    let button = await screen.findByRole("button", { name: "Рассчитать паспорт после валидации" });
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAttribute("title", "Свойства ряда не изменились с последнего расчёта");

    mockPassportFetch({ status: { ...READY_STATUS, validation: { ...validation, is_stale: true } } });
    rerender(<DatasetPassportPanel stage="validation" targetColumn="value-3" />);
    button = await screen.findByRole("button", { name: "Рассчитать паспорт после валидации" });
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("shows history count and a compare action after validation capture", async () => {
    const validation = { ...START_POINT, history_count: 3, is_stale: false };
    mockPassportFetch({ status: { ...READY_STATUS, validation } });

    render(<DatasetPassportPanel stage="validation" targetColumn="value" />);

    expect(await screen.findByText("Снимков в истории: 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сравнить паспорта свойств" })).toBeInTheDocument();
  });

  it("shows an explicit notice when a target change resets passport history", async () => {
    mockPassportFetch();

    render(
      <DatasetPassportPanel
        stage="start"
        targetColumn="volume"
        historyResetNotice="Смена исследуемого признака «value» → «volume» сбросила цепочку паспортов."
      />,
    );

    expect(await screen.findByText(/сбросила цепочку паспортов/i)).toBeInTheDocument();
  });

  it("renders the full start-validation-exit trajectory and qualitative changes", async () => {
    const comparison = {
      path: ["start", "validation", "exit"],
      target_column: "value",
      date_column: "date",
      comparisons: [
        {
          from_stage: "start",
          to_stage: "validation",
          from_snapshot_id: "s1",
          to_snapshot_id: "s2",
          comparison: {
            metrics: {
              "ADF p-value (стационарность)": { v_old: 0.2, v_new: 0.04, delta: -0.16, delta_pct: -80 },
            },
            summary: "Изменения после валидации",
            qualitative_changes: ["Стационарность: стало ✅ Да"],
            categorical_changes: {},
            list_changes: {},
            boolean_changes: {},
          },
        },
        {
          from_stage: "validation",
          to_stage: "exit",
          from_snapshot_id: "s2",
          to_snapshot_id: "s3",
          comparison: {
            metrics: {
              "ADF p-value (стационарность)": { v_old: 0.04, v_new: 0.01, delta: -0.03, delta_pct: -75 },
            },
            summary: "Изменения после предобработки",
            qualitative_changes: [],
            categorical_changes: { "Частота ряда": { v_old: "D", v_new: "B", changed: true } },
            list_changes: { "Доминирующие частоты (FFT)": { added: [7], removed: [14], changed: true } },
            boolean_changes: {},
          },
        },
      ],
    };
    const exit = { ...START_POINT, history_count: 1, is_stale: false };
    mockPassportFetch({ status: { ...READY_STATUS, exit }, compare: comparison });

    render(<DatasetPassportPanel stage="exit" targetColumn="value" />);
    fireEvent.click(await screen.findByRole("button", { name: "Сравнить паспорта свойств" }));

    expect(await screen.findByRole("columnheader", { name: "Загрузка" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Валидация" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Предобработка" })).toBeInTheDocument();
    expect(screen.getByText("Стационарность: стало ✅ Да")).toBeInTheDocument();
    expect(screen.getByText("+ 7")).toHaveClass("text-green-700");
    expect(screen.getByText("− 14")).toHaveClass("line-through");
    expect(screen.getByText(/Частота ряда: D → B/)).toBeInTheDocument();
  });

  it("shows an API detail instead of hiding capture failures", async () => {
    mockPassportFetch();
    global.fetch = jest.fn((url: string) => {
      if (url.includes("/dataset/passport/status")) return response(READY_STATUS);
      if (url.includes("/date-column")) return response(DATE_RESPONSE);
      return response({ detail: "Свойства ряда не изменились" }, false, 409);
    }) as unknown as typeof fetch;

    render(<DatasetPassportPanel stage="validation" targetColumn="value" />);
    const button = await screen.findByRole("button", { name: "Рассчитать паспорт после валидации" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    expect(await screen.findByRole("alert")).toHaveTextContent("Свойства ряда не изменились");
  });
});
