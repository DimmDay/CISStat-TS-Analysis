// packages/ui/components/ProgressDrawer.test.tsx
//
// Тесты контейнера правой панели «Прогресс» (Task PROGR-4, spec_progress.md
// §6.1-§6.2 + аддендум §4.2): механика -- прямой повтор архитектуры
// EventsLogDrawer (затемнение bg-black/20 закрывает по клику, крестик,
// translate-x транзишн), ширина -- ровно 2×w-80 = w-[40rem] (§4.2),
// шапка -- датасет/признак/дата/run_id/"Начат N мин назад" (§6.1),
// данные -- ОДИН запрос GET /v1/progress/trace с готовым состоянием
// (PROGR-10, Расхождение №1), "Развернуть трассу" -- переключатель §6.2.

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProgressDrawer } from "./ProgressDrawer";

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({
    activeDataset: { name: "fao_prices.csv", rows: 120, sizeLabel: "12 КБ" },
    targetColumn: "Price",
  }),
}));

const TRACE_RESPONSE = {
  run_id: "RUN-AB12CD34",
  started_at: "2026-09-25T09:00:00+00:00",
  events: [
    {
      event_id: "e-1",
      run_id: "RUN-AB12CD34",
      ts: "2026-09-25T09:00:00+00:00",
      stage: "upload",
      node_id: "structure_confirmed",
      event_type: "upload_completed",
      payload: { name: "fao_prices.csv", rows: 120, columns: 5 },
      actor: "user",
      timestamp: "2026-09-25T09:00:00+00:00",
    },
  ],
  // Готовое состояние (PROGR-10): статусы/свёртки считает бэкенд.
  node_statuses: { "upload/structure_confirmed": "done" } as Record<string, string>,
  stages: [
    {
      stage: "upload",
      fold: "passed",
      done_count: 1,
      warning_nodes: 0,
      total_nodes: 1,
    },
    {
      stage: "validation",
      fold: "not_started",
      done_count: 0,
      warning_nodes: 0,
      total_nodes: 10,
    },
  ],
};

function mockFetch(trace = TRACE_RESPONSE) {
  global.fetch = jest.fn((url: string) => {
    if (String(url).includes("/v1/progress/trace")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(trace) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as jest.Mock;
}

describe("ProgressDrawer", () => {
  beforeEach(() => {
    mockFetch();
  });

  it("панель — aside с aria-controls-целью id='progress-drawer' и aria-label", () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    const panel = screen.getByLabelText("Прогресс исследования");
    expect(panel.tagName).toBe("ASIDE");
    expect(panel).toHaveAttribute("id", "progress-drawer");
  });

  it("ширина панели w-[40rem] (аддендум §4.2: ровно 2×w-80)", () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    const panel = screen.getByLabelText("Прогресс исследования");
    expect(panel.className).toContain("w-[40rem]");
  });

  it("открытая панель сдвинута в экран (translate-x-0), фиксирована справа", () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    const panel = screen.getByLabelText("Прогресс исследования");
    expect(panel.className).toContain("translate-x-0");
    expect(panel.className).toContain("fixed");
    expect(panel.className).toContain("right-0");
  });

  it("закрытая панель сдвинута за экран (translate-x-full), но в DOM", () => {
    render(<ProgressDrawer open={false} onClose={jest.fn()} />);
    const panel = screen.getByLabelText("Прогресс исследования");
    expect(panel.className).toContain("translate-x-full");
    expect(panel.className).not.toContain("translate-x-0");
  });

  it("затемнение фона bg-black/20 закрывает панель по клику вне неё (§6.1)", () => {
    const onClose = jest.fn();
    const { container } = render(<ProgressDrawer open onClose={onClose} />);
    const backdrop = container.querySelector(".bg-black\\/20");
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("при закрытой панели затемнения нет", () => {
    const { container } = render(<ProgressDrawer open={false} onClose={jest.fn()} />);
    expect(container.querySelector(".bg-black\\/20")).toBeNull();
  });

  it("крестик в шапке закрывает панель (aria-label='Закрыть', §6.1)", () => {
    const onClose = jest.fn();
    render(<ProgressDrawer open onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("шапка §6.1: датасет, признак, run_id", async () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText(/fao_prices\.csv/)).toBeInTheDocument());
    expect(screen.getByText(/Price/)).toBeInTheDocument();
    expect(screen.getByText("RUN-AB12CD34")).toBeInTheDocument();
  });

  it("шапка: «Начат N мин назад» считается от started_at слоя 1", async () => {
    // 12.5 минут + floor => устойчиво к миллисекундному дрейфу прогона.
    const started = new Date(Date.now() - 12.5 * 60 * 1000).toISOString();
    mockFetch({ ...TRACE_RESPONSE, started_at: started });
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText(/Начат 12 мин назад/)).toBeInTheDocument());
  });

  it("без run_id (сессия без датасета) шапка показывает прочерк, не пустоту", async () => {
    mockFetch({ run_id: null, started_at: null, events: [], node_statuses: {}, stages: [] });
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("—")).toBeInTheDocument());
  });

  it("данные трассы запрашиваются при открытии панели", async () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => {
      const calls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
      expect(calls.some((u) => u.includes("/v1/progress/trace"))).toBe(true);
    });
  });

  it("PROGR-10: ОДИН запрос трассы -- /modeling/forecast не опрашивается", async () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("RUN-AB12CD34")).toBeInTheDocument());
    const calls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
    expect(calls.filter((u) => u.includes("/v1/progress/trace")).length).toBe(1);
    expect(calls.some((u) => u.includes("/modeling/forecast"))).toBe(false);
  });

  it("готовое состояние из /trace рендерится как есть (вычисление на бэкенде)", async () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() =>
      expect(screen.getByText("1/1, пройдено")).toBeInTheDocument(),
    );
  });

  it("при закрытой панели fetch не выполняется", () => {
    render(<ProgressDrawer open={false} onClose={jest.fn()} />);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("«Развернуть трассу ▾» переключает видимость лога (aria-expanded, §6.2)", async () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("RUN-AB12CD34")).toBeInTheDocument());
    const toggle = screen.getByRole("button", { name: /Развернуть трассу/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("log")).toBeNull();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("log")).toBeInTheDocument();
  });

  it("пустая трасса: блок-схема рендерится, в шапке прочерки", async () => {
    mockFetch({ run_id: null, started_at: null, events: [], node_statuses: {}, stages: [] });
    render(<ProgressDrawer open onClose={jest.fn()} />);
    // Все стадии без событий -- «не начато» на каждой карточке.
    await waitFor(() => expect(screen.getAllByText("не начато").length).toBeGreaterThan(0));
  });

  it("сбой сети не роняет панель (best-effort, как хук PROGR-3)", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network down")) as jest.Mock;
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getAllByText("не начато").length).toBeGreaterThan(0));
    expect(screen.getByLabelText("Прогресс исследования")).toBeInTheDocument();
  });
});

// ── PROGR-5.1: полоса действий «Пауза»/«Сохранить точку» (§5.1-§5.2, §6.3) ──

const RUN_DETAIL = {
  run_id: "RUN-AB12CD34",
  session_id: "s-1",
  dataset_fingerprint: "fp",
  dataset_name: "fao_prices.csv",
  target_column: "Price",
  created_at: "2026-09-25T09:00:00+00:00",
  last_active_at: "2026-09-25T09:05:00+00:00",
  status: "active",
  events: [],
  checkpoints: [],
  events_total: 0,
};

function mockFetchWithRunDetail(
  trace = TRACE_RESPONSE,
  runDetail: unknown | null = RUN_DETAIL,
  pauseResponse: unknown = { run_id: "RUN-AB12CD34", status: "paused", event: {} },
) {
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    const urlStr = String(url);
    if (urlStr.includes("/v1/progress/trace")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(trace) });
    }
    if (urlStr.includes("/v1/progress/runs/RUN-AB12CD34") && !init?.method) {
      if (runDetail === null) {
        return Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(runDetail) });
    }
    if (urlStr.includes("/pause") && init?.method === "POST") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(pauseResponse) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  }) as jest.Mock;
}

describe("ProgressDrawer + ProgressCheckpointBar (PROGR-5.1, §6.3)", () => {
  beforeEach(() => {
    mockFetchWithRunDetail();
  });

  it("при известном run_id запрашивается деталь запуска слоя 2 (статус/чекпоинты)", async () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => {
      const calls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
      expect(calls.some((u) => u.includes("/v1/progress/runs/RUN-AB12CD34"))).toBe(true);
    });
  });

  it("полоса действий рендерится: бейдж статуса и кнопки «Пауза»/«Сохранить точку»", async () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("В работе")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Пауза" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Сохранить точку/ })).toBeEnabled();
  });

  it("без run_id полоса действий не рендерится (действиям запуска неоткуда взяться)", async () => {
    mockFetchWithRunDetail({ run_id: null, started_at: null, events: [], node_statuses: {}, stages: [] });
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("—")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Пауза" })).toBeNull();
  });

  it("N-4: успешная «Пауза» НЕ закрывает панель (панель живёт во фронтенде) и обновляет данные", async () => {
    const onClose = jest.fn();
    render(<ProgressDrawer open onClose={onClose} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Пауза" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Пауза" }));
    await waitFor(() => {
      const calls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
      // refetch трассы слоя 1 после действия (run_paused зеркалится в слой 1)
      expect(calls.filter((u) => u.includes("/v1/progress/trace")).length).toBe(2);
    });
    // Панель всё ещё открыта, крестик не нажат
    const panel = screen.getByLabelText("Прогресс исследования");
    expect(panel.className).toContain("translate-x-0");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("отказ слоя 2 (503): панель не падает, кнопки полосы disabled (best-effort)", async () => {
    mockFetchWithRunDetail(TRACE_RESPONSE, null);
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText(/RUN-AB12CD34/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Пауза" })).toBeDisabled());
    expect(screen.getByLabelText("Прогресс исследования")).toBeInTheDocument();
  });

  it("отказ 404 (запуск не найден): панель не падает, действия disabled", async () => {
    mockFetchWithRunDetail(TRACE_RESPONSE, null);
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes("/v1/progress/trace")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(TRACE_RESPONSE) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    }) as jest.Mock;
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText(/RUN-AB12CD34/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Пауза" })).toBeDisabled());
  });

  it("статус paused из слоя 2: бейдж «На паузе» и кнопка «Продолжить»", async () => {
    mockFetchWithRunDetail(TRACE_RESPONSE, { ...RUN_DETAIL, status: "paused" });
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("На паузе")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Продолжить" })).toBeEnabled();
  });
});

// ── PROGR-6: секция «Наставник» (§6.2 макет «[Наставник →]», §7.1) ────

const NEXT_STEP_RESPONSE = {
  run_id: "RUN-AB12CD34",
  run_status: "active",
  last_active_stage: "upload",
  phase_text: "Исследование на этапе «Загрузка».",
  summary: {
    stage: "upload",
    total_nodes: 1,
    done_count: 1,
    warning_nodes: 0,
    nodes: [{ node_id: "structure_confirmed", status: "done" }],
  },
  recommendation: null,
  history_warnings: [],
};

describe("ProgressDrawer + MentorPanel (PROGR-6, §6.2/§7.1)", () => {
  beforeEach(() => {
    mockFetchWithRunDetail();
    const originalFetch = global.fetch as jest.Mock;
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes("/mentor/next-step")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(NEXT_STEP_RESPONSE) });
      }
      return originalFetch(url, init);
    }) as jest.Mock;
  });

  it("кнопка «Наставник →» в полосе открывает секцию Наставника внутри панели", async () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Наставник →" })).toBeEnabled());
    expect(screen.queryByLabelText("Наставник")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Наставник →" }));
    const mentor = screen.getByLabelText("Наставник");
    expect(mentor).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Критичных подсказок нет/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Наставник →" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("N-4: открытие «Наставника» не закрывает панель «Прогресс»", async () => {
    const onClose = jest.fn();
    render(<ProgressDrawer open onClose={onClose} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Наставник →" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Наставник →" }));
    await waitFor(() => expect(screen.getByLabelText("Наставник")).toBeInTheDocument());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Прогресс исследования").className).toContain("translate-x-0");
  });

  it("повторный клик «Наставник →» закрывает секцию (тогглер)", async () => {
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Наставник →" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Наставник →" }));
    await waitFor(() => expect(screen.getByLabelText("Наставник")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Наставник →" }));
    expect(screen.queryByLabelText("Наставник")).toBeNull();
  });

  it("без run_id ни полосы, ни секции «Наставник» нет", async () => {
    mockFetchWithRunDetail({ run_id: null, started_at: null, events: [], node_statuses: {}, stages: [] });
    render(<ProgressDrawer open onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("—")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Наставник →" })).toBeNull();
  });
});
