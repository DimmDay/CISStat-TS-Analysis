// packages/ui/components/TsAnalysisForecasting.test.tsx
//
// Контракты вкладки «Прогнозирование»:
//  - честные гейты: без датасета / без завершённого Моделирования / без карты;
//  - панель управления: селектор карт, горизонт, alpha, кнопка прогноза;
//  - генерация прогноза дергает POST /forecast и рендерит график+точность;
//  - история + чекбоксы сравнения; экспорт; шаги этапа со StatusIcon.

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TsAnalysisForecasting } from "./TsAnalysisForecasting";
import type { CardSummary, ForecastRun } from "../lib/forecasting";

// AppShell: stages/activeDataset -- фиксированный сценарий на тест.
// PROGR-4 (§6.1): log/addLogEntry/clearLog удалены из shell-контекста.
let mockStages: Record<string, string> = {};
let mockHasDataset = true;
// FORECAST-GATE-1: контролируемый стаб refreshSession (паттерн TasksHub):
// тест пересинхронизации подменяет stages «как это сделал бы провайдер».
const mockRefreshSession = jest.fn();
jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({
    activeDataset: mockHasDataset
      ? { datasetId: "d-1", name: "series.csv", rows: 96, sizeLabel: "3 КБ" }
      : null,
    stages: mockStages,
    lastActiveStage: null,
    targetColumn: null,
    sessionLoading: false,
    // Стабильная ссылка (как useCallback-refreshSession в реальном
    // провайдере): тест счётчика вызовов ловит и циклы по зависимости.
    refreshSession: mockRefreshSession,
  }),
}));

const CARD: CardSummary = {
  card_id: "c-1",
  model_id: "naive",
  model_name: "Naive",
  selection_kind: "single",
  horizon: 2,
  fingerprint: "a".repeat(64),
  created_at: "2026-09-14T10:00:00+00:00",
};

function makeRun(overrides: Partial<ForecastRun> = {}): ForecastRun {
  return {
    forecast_id: "f-1",
    model_card_id: "c-1",
    model_id: "naive",
    model_name: "Naive",
    generated_at: "2026-09-14T10:05:00+00:00",
    horizon: 2,
    alpha: 0.05,
    alpha_effective: 0.05,
    alpha_source: "requested",
    ci_method: "empirical_oof_quantile",
    points: [
      { step: 1, date: "2026-01-01T00:00:00", value: 101, ci_lower: 98, ci_upper: 104, is_anomalous: false },
      { step: 2, date: "2026-02-01T00:00:00", value: 102, ci_lower: 98.5, ci_upper: 105.5, is_anomalous: false },
    ],
    history: { labels: ["2025-11-01T00:00:00"], values: [100] },
    expected_accuracy: { mae: 1.5, rmse: 2.0 },
    prediction_interval_coverage: 0.95,
    warnings: [],
    trace_events: [],
    lineage: {},
    sensitivity: null,
    ...overrides,
  } as ForecastRun;
}

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({
    ok,
    status: ok ? 200 : 409,
    json: () => Promise.resolve(body),
  } as Response);
}

function installFetch({ cards = [CARD], forecasts = [] as ForecastRun[] } = {}) {
  const fetchMock = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/card")) return jsonResponse({ cards });
    if (url.endsWith("/forecast") && (init?.method ?? "GET") === "GET")
      return jsonResponse({ forecasts });
    return jsonResponse({}, false);
  });
  global.fetch = fetchMock as unknown as typeof global.fetch;
  return fetchMock;
}

beforeEach(() => {
  mockStages = { upload: "done", modeling: "done" };
  mockHasDataset = true;
});
afterEach(() => {
  jest.restoreAllMocks();
  mockRefreshSession.mockReset();
  delete (global as { fetch?: unknown }).fetch;
});

describe("TsAnalysisForecasting -- честные гейты", () => {
  it("без датасета -- гейт «Загрузите датасет», без обращения к API карт", async () => {
    mockHasDataset = false;
    const fetchMock = installFetch();
    render(<TsAnalysisForecasting />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByTestId("no-dataset-gate")).toHaveTextContent(/Загрузите датасет/);
    expect(screen.queryByTestId("generate-btn")).toBeDisabled();
  });

  it("Моделирование не завершено -- гейт про Model Card и этап Моделирования", async () => {
    mockStages = { upload: "done", modeling: "pending" };
    installFetch({ cards: [] });
    render(<TsAnalysisForecasting />);
    await waitFor(() => expect(screen.getByTestId("no-modeling-gate")).toBeInTheDocument());
    expect(screen.getByTestId("no-modeling-gate")).toHaveTextContent(/Моделирование/);
  });

  it("карт нет -- гейт со ссылкой на /modeling", async () => {
    installFetch({ cards: [] });
    render(<TsAnalysisForecasting />);
    await waitFor(() => expect(screen.getByTestId("no-card-gate")).toBeInTheDocument());
    const link = screen.getByTestId("no-card-gate").querySelector("a");
    expect(link).toHaveAttribute("href", "/modeling");
  });
});

// ── Пересинхронизация stages при монтировании (FORECAST-GATE-1) ──
// Сценарий тимлида: Model Card создана на «Моделировании»
// (create_model_card -> set_stage("modeling","done") на бэкенде), затем
// клиентская навигация на «Прогнозирование». Провайдер AppShell (layout)
// НЕ ремоунтится — в контексте остаётся stages, снятый при F5/upload;
// гейт no-modeling держал плейсхолдер и disabled «Построить прогноз»
// до перезагрузки страницы. Паттерн фикса — PREPR-4 (TasksHub):
// монтирование вкладки = refreshSession; сервер — источник истины о stages.
describe("Пересинхронизация stages при монтировании (FORECAST-GATE-1)", () => {
  it("после завершения Моделирования в другой вкладке гейт снимается без перезагрузки страницы", async () => {
    // Контекст ещё держит устаревшую стадию (навигация без F5)...
    mockStages = { upload: "done", modeling: "in_progress" };
    // ...а сервер уже знает правду: modeling=done (семантика applySessionResponse).
    mockRefreshSession.mockImplementation(async () => {
      mockStages = { upload: "done", modeling: "done" };
    });
    installFetch(); // /card отдаёт CARD — Model Card существует
    render(<TsAnalysisForecasting />);

    // Пересинхронизация снимает гейт «Завершите этап Моделирование»...
    await waitFor(() =>
      expect(screen.queryByTestId("no-modeling-gate")).not.toBeInTheDocument(),
    );
    expect(mockRefreshSession).toHaveBeenCalled();
    // ...и разблокирует «Построить прогноз» без F5.
    await waitFor(() => expect(screen.getByTestId("generate-btn")).toBeEnabled());
  });

  it("refreshSession вызывается ровно один раз на монтирование (без циклов)", async () => {
    mockStages = { upload: "done", modeling: "done" };
    mockRefreshSession.mockResolvedValue(undefined);
    installFetch();
    render(<TsAnalysisForecasting />);
    await waitFor(() => expect(screen.getByTestId("card-select")).toHaveValue("c-1"));
    expect(mockRefreshSession).toHaveBeenCalledTimes(1);
  });
});

describe("TsAnalysisForecasting -- готовый этап", () => {
  it("рендерит панель управления: селектор карты, горизонт по умолчанию из карты, alpha, кнопку", async () => {
    installFetch();
    render(<TsAnalysisForecasting />);
    // Ассерт по ЗНАЧЕНИЮ селектора, а не по факту существования элемента:
    // панель управления рендерится до загрузки карт (value=""), поэтому
    // findByTestId резолвится на первом кадре — в окружении Node 24/jest 30
    // это стабильная гонка с загрузкой /card (предсуществующий флейк
    // базлайна, не связанный с FORECAST-GATE-1).
    await waitFor(() => expect(screen.getByTestId("card-select")).toHaveValue("c-1"));
    const horizon = screen.getByTestId("horizon-input") as HTMLInputElement;
    expect(horizon.value).toBe("2"); // дефолт -- training.horizon карты
    expect(screen.getByTestId("alpha-select")).toHaveValue("0.05");
    expect(screen.getByTestId("generate-btn")).toBeEnabled();
    // Описание этапа и справка-кнопка.
    expect(screen.getByTestId("forecasting-help-btn")).toBeInTheDocument();
  });

  it("история пуста -- честное пустое состояние; шаги этапа показаны", async () => {
    installFetch();
    render(<TsAnalysisForecasting />);
    await waitFor(() => expect(screen.getByTestId("forecast-history-empty")).toBeInTheDocument());
    const steps = screen.getByTestId("forecasting-steps");
    expect(steps).toHaveTextContent("Прогноз построен");
    expect(steps).toHaveTextContent("Экспорт");
  });

  it("существующий прогноз из истории рендерит график и панель точности", async () => {
    installFetch({ forecasts: [makeRun()] });
    render(<TsAnalysisForecasting />);
    await waitFor(() => expect(screen.getByTestId("forecast-chart")).toBeInTheDocument());
    expect(screen.getByTestId("forecast-accuracy-panel")).toBeInTheDocument();
    expect(screen.getByTestId("accuracy-mae")).toHaveTextContent("1.5000");
    expect(screen.getByTestId("coverage")).toHaveTextContent("95.0%");
    expect(screen.getByTestId("export-csv")).toHaveAttribute("href", expect.stringContaining("/forecast/f-1/export.csv"));
    expect(screen.getByTestId("export-json")).toHaveAttribute("href", expect.stringContaining("/forecast/f-1/export.json"));
  });

  it("генерация: POST /forecast с картой/горизонтом/alpha, затем график нового прогноза", async () => {
    const fetchMock = installFetch();
    const created = makeRun({ forecast_id: "f-new", ci_method: "parametric_simulation", alpha_effective: 0.05 });
    render(<TsAnalysisForecasting />);
    const select = await screen.findByTestId("card-select");
    await waitFor(() => expect(select).toHaveValue("c-1"));
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/card")) return jsonResponse({ cards: [CARD] });
      if (url.endsWith("/forecast") && init?.method === "POST") {
        return jsonResponse(created);
      }
      if (url.endsWith("/forecast")) return jsonResponse({ forecasts: [] });
      return jsonResponse({}, false);
    });
    fireEvent.click(screen.getByTestId("generate-btn"));
    await waitFor(() => expect(screen.getByTestId("forecast-chart")).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find(
      ([input, init]) => String(input).endsWith("/forecast") && (init as RequestInit | undefined)?.method === "POST",
    ) as unknown as [RequestInfo | URL, RequestInit] | undefined;
    expect(postCall).toBeTruthy();
    const body = JSON.parse(String(postCall![1].body));
    expect(body).toEqual({ model_card_id: "c-1", horizon: null, alpha: 0.05 });
  });

  it("ошибка бэкенда при генерации показывается в role=alert", async () => {
    const fetchMock = installFetch();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/card")) return jsonResponse({ cards: [CARD] });
      // POST проверяется РАНЬШЕ GET-ветки: тот же URL /forecast.
      if (url.endsWith("/forecast") && init?.method === "POST") {
        return Promise.resolve({
          ok: false,
          status: 409,
          json: () => Promise.resolve({ detail: "Model Card устарела: ряд изменился" }),
        } as Response);
      }
      if (url.endsWith("/forecast")) return jsonResponse({ forecasts: [] });
      return jsonResponse({}, false);
    });
    render(<TsAnalysisForecasting />);
    await waitFor(() => expect(screen.getByTestId("card-select")).toHaveValue("c-1"));
    fireEvent.click(screen.getByTestId("generate-btn"));
    await waitFor(() => expect(screen.getByTestId("forecasting-error")).toBeInTheDocument());
    expect(screen.getByTestId("forecasting-error")).toHaveTextContent(/Model Card устарела/);
  });

  it("чекбоксы сравнения управляют подписью кнопки сравнения", async () => {
    installFetch({ forecasts: [makeRun(), makeRun({ forecast_id: "f-2", model_name: "ETS" })] });
    render(<TsAnalysisForecasting />);
    await waitFor(() => expect(screen.getAllByTestId("forecast-history-item")).toHaveLength(2));
    const button = screen.getByTestId("compare-btn");
    expect(button).toHaveTextContent("Сравнить (0)");
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/Выбрать прогноз Naive для сравнения/));
    fireEvent.click(screen.getByLabelText(/Выбрать прогноз ETS для сравнения/));
    expect(screen.getByTestId("compare-btn")).toHaveTextContent("Сравнить (2)");
    expect(screen.getByTestId("compare-btn")).toBeEnabled();
  });
});

// ── Замыкающая кнопка цепочки степперов (v1.1, §9.4 дополнения) ──
// Цепочка StepperNextModuleButton («Ведём исследователя за руку»)
// тянулась через все пять степперов и обрывалась на Прогнозировании
// (решение FORECAST-1). Теперь, когда хаб /tasks существует, цепочка
// замыкается: та же кнопка-приглашение в конце шагов этапа ведёт на
// /tasks. Компонент StepperNextModuleButton НЕ изменяется — только
// переиспользуется (label/href — единственные входы).

describe("Замыкающая кнопка цепочки «Перейти к задачам» (v1.1 §9.4)", () => {
  it("приглашение в конце шагов этапа ведёт на /tasks", async () => {
    installFetch();
    render(<TsAnalysisForecasting />);
    await waitFor(() => expect(screen.getByTestId("forecasting-steps")).toBeInTheDocument());

    const link = screen.getByRole("link", { name: /Перейти к задачам/ });
    expect(link).toHaveAttribute("href", "/tasks");
  });

  it("переиспользует StepperNextModuleButton без изменения компонента (контракт классов)", async () => {
    installFetch();
    const { container } = render(<TsAnalysisForecasting />);
    await waitFor(() => expect(screen.getByTestId("forecasting-steps")).toBeInTheDocument());

    const link = screen.getByRole("link", { name: /Перейти к задачам/ });
    // Стилевой контракт StepperNextModuleButton: пастельный фон,
    // индиго при наведении, та же рамка степпер-кнопок.
    expect(link.className).toContain("bg-brand-light/50");
    expect(link.className).toContain("hover:bg-brand");
    expect(link.className).toContain("hover:text-white");
    expect(link.className).toContain("rounded-md");
    // Светло-серая черта-разделитель на обёртке (переход к другому
    // модулю, а не ещё одна остановка этапа).
    const wrapper = link.parentElement;
    expect(wrapper?.className).toContain("border-t");
    expect(wrapper?.className).toContain("border-neutral-200");
    // Кнопка стоит ПОСЛЕ списка шагов этапа (конец «степпера»).
    const steps = screen.getByTestId("forecasting-steps");
    expect(steps.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Кнопка остаётся в левой колонке этапа, рядом с шагами.
    expect(container.querySelector("aside")?.contains(link)).toBe(true);
  });
});
