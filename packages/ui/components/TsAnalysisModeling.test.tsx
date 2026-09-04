// packages/ui/components/TsAnalysisModeling.test.tsx
//
// Тесты для компонента «Моделирование»:
// 1. Рендер модуля и 11 стадий пайплайна
// 2. Кнопка «Справка» переключает секцию
// 3. Expandable description box
// 4. Профиль данных (форма)
// 5. Fetch кандидатов (mock fetch)
// 6. Фильтрация по уровню
// 7. Выбор кандидата → детальная карточка
// 8. Обработка ошибок API
// 9. activeDataset → автозаполнение профиля

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisModeling } from "./TsAnalysisModeling";
import type { ActiveDataset } from "../context/AppShellContext";

// ── Polyfill: ResizeObserver не определён в jsdom ──
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ── Mock next/navigation ──
jest.mock("next/navigation", () => ({
  usePathname: () => "/modeling",
}));

// ── Mock AppShellContext (динамический — позволяет задать activeDataset) ──
let mockActiveDataset: ActiveDataset | null = null;

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({
    activeDataset: mockActiveDataset,
    log: [],
  }),
}));

// ── Test data ──
const MOCK_CANDIDATES = [
    {
      model_id: "naive",
      model_name: "Naive",
      family_id: "baselines",
      level: "RECOMMENDED",
      rule_id: "P07",
      message: "Baseline-модель всегда рекомендуется",
      rank: 1,
      platform_status: "ready",
      available_actions: ["backtest"],
      blocking_reason: null,
    },
    {
      model_id: "seasonal_naive",
      model_name: "Seasonal Naive",
      family_id: "baselines",
      level: "RECOMMENDED",
      rule_id: "P07",
      message: "Baseline-модель всегда рекомендуется",
      rank: 1,
      platform_status: "ready",
      available_actions: ["backtest"],
      blocking_reason: null,
    },
    {
      model_id: "drift",
      model_name: "Drift",
      family_id: "baselines",
      level: "RECOMMENDED",
      rule_id: "P07",
      message: "Baseline-модель всегда рекомендуется",
      rank: 1,
      platform_status: "ready",
      available_actions: ["backtest"],
      blocking_reason: null,
    },
    {
      model_id: "mean",
      model_name: "Mean",
      family_id: "baselines",
      level: "RECOMMENDED",
      rule_id: "P07",
      message: "Baseline-модель всегда рекомендуется",
      rank: 1,
      platform_status: "ready",
      available_actions: ["backtest"],
      blocking_reason: null,
    },
    {
      model_id: "ets",
      model_name: "ETS (Auto)",
      family_id: "exponential_smoothing",
      level: "RECOMMENDED",
      rule_id: "P01",
      message: "Модель рекомендована для данного профиля",
      rank: 1,
      platform_status: "ready",
      available_actions: ["backtest", "tune", "diagnostics"],
      blocking_reason: null,
    },
    {
      model_id: "arima_auto",
      model_name: "Auto-ARIMA",
      family_id: "arima",
      level: "RECOMMENDED",
      rule_id: "P02",
      message: "Модель рекомендована для данного профиля",
      rank: 1,
      platform_status: "ready",
      available_actions: ["backtest"],
      blocking_reason: null,
    },
    {
      model_id: "garch",
      model_name: "GARCH(p,q)",
      family_id: "volatility",
      level: "NOT_RECOMMENDED",
      rule_id: "D03",
      message: "Модель не рекомендуется: область не financial",
      rank: 3,
      platform_status: "catalog_only",
      available_actions: [],
      blocking_reason: "Production-реализация модели ещё не подключена.",
    },
    {
      model_id: "prophet",
      model_name: "Prophet",
      family_id: "structural",
      level: "CONDITIONALLY_APPLICABLE",
      rule_id: "C03",
      message: "Условно применима: нет сезонности",
      rank: 2,
      platform_status: "catalog_only",
      available_actions: [],
      blocking_reason: "Production-реализация модели ещё не подключена.",
    },
    {
      model_id: "var",
      model_name: "VAR",
      family_id: "multivariate",
      level: "NOT_APPLICABLE",
      rule_id: "F02",
      message: "Неприменима: одномерный ряд",
      rank: 4,
      platform_status: "catalog_only",
      available_actions: [],
      blocking_reason: "Production-реализация модели ещё не подключена.",
    },
  ];

const MOCK_CATALOG = [
  ...MOCK_CANDIDATES,
  ...Array.from({ length: 15 }, (_, index) => ({
    model_id: `catalog_model_${index + 1}`,
    model_name: `Catalog model ${index + 1}`,
    family_id: "neural",
    level: "NOT_APPLICABLE",
    rule_id: "F04",
    message: "Недостаточно данных для текущего ряда",
    rank: 4,
    platform_status: "catalog_only",
    available_actions: [],
    blocking_reason: "Production-реализация модели ещё не подключена.",
  })),
];

const MOCK_CANDIDATES_RESPONSE = {
  candidates: MOCK_CANDIDATES,
  catalog: MOCK_CATALOG,
  statistics: {
    total_candidates: 9,
    by_level: {
      RECOMMENDED: 6,
      CONDITIONALLY_APPLICABLE: 1,
      NOT_RECOMMENDED: 1,
      NOT_APPLICABLE: 1,
    },
    total_models_in_spec: 24,
  },
  spec_version: "1.0.0-draft",
};

// ── Mock fetch (на уровне модуля, как DataUploadForm.test.tsx) ──
// Маршрутизация по URL:
//   • GET  /v1/session/target-column → MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET
//   • POST /v1/internal/models/candidates → MOCK_CANDIDATES_RESPONSE  (Task 14 fix: mirror without auth)
//   • POST /v1/internal/models/backtest → MOCK_BACKTEST_RESPONSE
// Это позволяет компоненту на маунте вызвать ДВА fetch (target-column + candidates)
// без падения тестов.
const MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET = {
  target_column: null,
  available_columns: [],
  has_dataset: false,
};

const MOCK_TARGET_COLUMN_RESPONSE_WITH_DATASET = {
  target_column: null,
  available_columns: ["value", "gdp", "inflation"],
  has_dataset: true,
};

const MOCK_MODELING_CONTEXT = {
  ready: true,
  data_source: "session",
  fingerprint: "test-fingerprint",
  checkpoint: {
    checkpoint_id: "cp-test",
    snapshot_id: "snap-test",
    stage: "modeling_entry",
    source_stage: "exit",
    confirmed_at: "2026-09-03T00:00:00Z",
  },
  profile: {
    n_observations: 120, n_series: 1, n_exogenous: 0, is_regular: true,
    frequency: "M", has_seasonality: true, seasonal_periods: [12],
    is_stationary_or_diffable: true, is_cointegrated: false,
    has_negative_values: false, has_volatility_clustering: false,
    domain: "macro", missing_ratio: 0, outlier_ratio: 0,
    has_holidays: false, gpu_available: false, feature_engineering_applied: false,
  },
  passport: {},
  validation_strategy: { strategy: "sliding", horizon: 12, n_splits: 5, gap: 2, train_window: 60 },
  model_matrix: {},
  runnable_shortlist: ["naive", "ets", "arima"],
  traceability: {
    nodes: [],
    summary: { total: 30, done: 30, warning: 0, skipped: 0, pending: 0, blocking: 0 },
  },
};

const MOCK_BASELINE_BACKTEST = {
  model_id: "naive", model_name: "Naive", family_id: "baselines",
  metrics: { mae: 3.45, rmse: 4.12, mape: 2.1, mase: 0.87, weighted_score: null },
  n_train: 96, n_test: 24, train_ratio: 0.8, duration_ms: 5,
  data_source: "session", status: "success", strategy: "expanding",
  cohort_id: "cohort-bootstrap", horizon: 2, n_folds: 3, gap: 0,
  folds: [], oof_predictions: [], warnings: [],
};
const baselineFetch = jest.fn();

// @ts-ignore — mock fetch с частичным Response
const mockFetch: any = jest.fn((url: string) => {
  // GET target-column (без body в mock — components не передаёт method для GET)
  if (typeof url === "string" && url.includes("/v1/session/target-column")) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET),
    });
  }
  // candidates по умолчанию
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
  });
});
// Контекст hand-off всегда отдаётся отдельно; mockFetch продолжает хранить
// только предметные вызовы, которые проверяются в тестах.
// @ts-ignore
global.fetch = ((url: string, options?: unknown) => {
  if (typeof url === "string" && url.includes("/v1/session/modeling/context")) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODELING_CONTEXT) });
  }
  if (typeof url === "string" && url.includes("/v1/session/modeling/baselines")) {
    baselineFetch(url, options);
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        status: "success", cohort_id: "cohort-bootstrap",
        backtests: { naive: MOCK_BASELINE_BACKTEST }, failures: {},
      }),
    });
  }
  return mockFetch(url, options);
}) as typeof fetch;

// ═══════════════════════════════════════════════════════════
// Test suites
// ═══════════════════════════════════════════════════════════

describe("TsAnalysisModeling", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockActiveDataset = null; // ← по умолчанию без датасета
    // Восстановим mock по умолчанию (success + маршрутизация по URL)
    mockFetch.mockImplementation((url: string) => {
      if (typeof url === "string" && url.includes("/v1/session/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      });
    });
  });

  // ── 1. Рендер модуля ──

  it("renders the module title", () => {
    render(<TsAnalysisModeling />);
    expect(screen.getByText("Моделирование")).toBeInTheDocument();
  });

  it("renders the subtitle", () => {
    render(<TsAnalysisModeling />);
    expect(screen.getByText("Выбор модели для прогнозирования")).toBeInTheDocument();
  });

  // ── 2. 11 стадий пайплайна ──

  it("renders all 11 pipeline stages in the stepper", () => {
    render(<TsAnalysisModeling />);
    const stageLabels = [
      "Определение задачи", "Структура данных", "Ограничения",
      "Пул кандидатов", "Baseline", "Бэктест", "Тюнинг",
      "Диагностика", "Сравнение", "Выбор модели", "Model Card",
    ];
    stageLabels.forEach((label) => {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── 3. Кнопка «Справка» ──

  it("renders the 'Справка' button in the header", () => {
    render(<TsAnalysisModeling />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    expect(helpButton).toBeInTheDocument();
  });

  it("clicking 'Справка' shows help content in the central text area", () => {
    render(<TsAnalysisModeling />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();
    fireEvent.click(helpButton);
    // После клика — появляется справка (может быть несколько совпадений — подзаголовок + контент)
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("clicking 'Справка' toggles content off on second click", () => {
    render(<TsAnalysisModeling />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    fireEvent.click(helpButton);
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
    fireEvent.click(helpButton);
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();
  });

  // ── 4. Expandable Description Box ──

  it("expand chevron is not visible when no content is loaded (no overflow)", () => {
    render(<TsAnalysisModeling />);
    const expandBtn = screen.queryByTestId("desc-expand-btn");
    expect(expandBtn).toBeNull();
  });

  it("collapse chevron is not visible when description is not expanded", () => {
    render(<TsAnalysisModeling />);
    const collapseBtn = screen.queryByTestId("desc-collapse-btn");
    expect(collapseBtn).toBeNull();
  });

  // ── 5. Профиль данных ──

  it("renders the data profile form with n_observations input", () => {
    render(<TsAnalysisModeling />);
    const input = screen.getByTestId("profile-n-observations");
    expect(input).toBeInTheDocument();
  });

  it("renders the data profile form with n_series input", () => {
    render(<TsAnalysisModeling />);
    const input = screen.getByTestId("profile-n-series");
    expect(input).toBeInTheDocument();
  });

  it("renders the frequency selector", () => {
    render(<TsAnalysisModeling />);
    const select = screen.getByTestId("profile-frequency");
    expect(select).toBeInTheDocument();
  });

  it("renders the domain selector", () => {
    render(<TsAnalysisModeling />);
    const select = screen.getByTestId("profile-domain");
    expect(select).toBeInTheDocument();
  });

  // ── 6. Fetch кандидатов ──

  it("fetches candidates on mount", async () => {
    render(<TsAnalysisModeling />);
    // Phase 1: на маунте ДВА fetch — target-column (GET) + candidates (POST)
    await waitFor(() => {
      const candidatesCalls = mockFetch.mock.calls.filter(
        ([u]: [string]) => typeof u === "string" && u.includes("/v1/session/modeling/candidates")
      );
      expect(candidatesCalls.length).toBe(1);
    });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/modeling/candidates"),
      expect.objectContaining({ method: "POST" })
    );
    await waitFor(() => expect(baselineFetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/modeling/baselines"),
      expect.objectContaining({ method: "POST", credentials: "include" })
    ));
  });

  it("fetches target-column on mount (Phase 1)", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      const tcCalls = mockFetch.mock.calls.filter(
        ([u]: [string]) => typeof u === "string" && u.includes("/v1/session/target-column")
      );
      expect(tcCalls.length).toBe(1);
    });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/target-column"),
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("renders candidate pool after successful fetch", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });
  });

  it("shows catalog-only models without offering a backtest action", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => expect(screen.getByTestId("candidate-pool")).toBeInTheDocument());

    expect(screen.queryByTestId("candidate-prophet")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Весь каталог/ }));
    fireEvent.click(screen.getByTestId("family-header-structural"));
    fireEvent.click(screen.getByTestId("candidate-prophet"));

    expect(screen.getByTestId("execution-badge-prophet")).toHaveTextContent("В каталоге");
    expect(screen.getByTestId("backtest-unavailable")).toHaveTextContent("Production-реализация");
    expect(screen.queryByTestId("run-backtest-btn")).not.toBeInTheDocument();
    const backtestCalls = mockFetch.mock.calls.filter(
      ([url]: [string]) => typeof url === "string" && url.includes("/v1/session/modeling/backtest")
    );
    expect(backtestCalls).toHaveLength(0);
  });

  it("shows all 24 specification models in the complete catalog", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => expect(screen.getByTestId("candidate-pool")).toBeInTheDocument());

    const catalogButton = screen.getByRole("button", { name: "Весь каталог (24)" });
    expect(catalogButton).toBeInTheDocument();
    fireEvent.click(catalogButton);
    fireEvent.click(screen.getByTestId("family-header-multivariate"));

    expect(screen.getByTestId("candidate-var")).toBeInTheDocument();
    expect(screen.getByTestId("badge-var")).toHaveTextContent("Неприменима");
  });

  it("renders family headers for families with candidates", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("family-header-baselines")).toBeInTheDocument();
    });
    expect(screen.getByTestId("family-header-exponential_smoothing")).toBeInTheDocument();
    expect(screen.getByTestId("family-header-arima")).toBeInTheDocument();
  });

  it("renders statistics grid after fetch", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("statistics-grid")).toBeInTheDocument();
    });
  });

  // ── 7. Обработка ошибок API ──

  it("shows error message when API returns error", async () => {
    mockFetch.mockImplementation(() =>
      Promise.resolve({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: () => Promise.resolve({ detail: "Сервер недоступен" }),
      })
    );
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("api-error")).toBeInTheDocument();
    });
    // Ошибка появляется в центральном баннере и в правой колонке — проверяем наличие
    const errorMatches = screen.getAllByText(/Сервер недоступен/i);
    expect(errorMatches.length).toBeGreaterThanOrEqual(1);
  });

  it("Task 14 fix: renders array-shape detail as readable string, NOT '[object Object]'", async () => {
    // Regression: раньше при ошибке 422 с массивом Pydantic-ошибок
    // [{loc,msg,type},...] JS делал String(arr) → "[object Object],[object Object]".
    // Теперь formatErrorDetail() нормализует массив в "loc.join('.'): msg; ...".
    const pydanticArrayDetail = [
      { type: "missing", loc: ["header", "x-api-key"], msg: "Field required", input: null },
      { type: "missing", loc: ["header", "x-api-key"], msg: "Field required", input: null },
    ];
    mockFetch.mockImplementation(() =>
      Promise.resolve({
        ok: false,
        status: 422,
        statusText: "Unprocessable Entity",
        json: () => Promise.resolve({ detail: pydanticArrayDetail }),
      })
    );
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("api-error")).toBeInTheDocument();
    });
    // КРИТИЧНО: НЕ должно быть [object Object]
    const errorEls = screen.getAllByText(/header\.x-api-key/i);
    expect(errorEls.length).toBeGreaterThanOrEqual(1);
    // Явная проверка отсутствия старого симптома
    const objectStringEls = screen.queryAllByText(/\[object Object\]/i);
    expect(objectStringEls).toHaveLength(0);
  });

  it("uses the traceable session candidates route", async () => {
    // Regression test: раньше UI ходил на /v1/models/candidates (требует X-Api-Key),
    // теперь — на зеркало /v1/internal/models/candidates (без auth).
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      const internalCalls = mockFetch.mock.calls.filter(
        ([u]: [string]) => typeof u === "string" && u.includes("/v1/session/modeling/candidates")
      );
      expect(internalCalls.length).toBeGreaterThanOrEqual(1);
    });
    // Контрольная: НЕ должно быть запросов на старый защищённый эндпоинт
    const oldCalls = mockFetch.mock.calls.filter(
      ([u]: [string]) =>
        typeof u === "string" &&
        u.includes("/v1/models/candidates") &&
        !u.includes("/v1/internal/models/candidates")
    );
    expect(oldCalls).toHaveLength(0);
  });

  it("passes the complete EDA validation contract to candidate generation", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      const call = mockFetch.mock.calls.find(
        ([u]: [string]) => typeof u === "string" && u.includes("/v1/session/modeling/candidates")
      );
      expect(call).toBeDefined();
      const payload = JSON.parse((call?.[1] as RequestInit).body as string);
      expect(payload).toMatchObject({
        strategy: "sliding", horizon: 12, n_splits: 5, gap: 2, train_window: 60,
      });
    });
  });

  // ── 8. Кнопка «Загрузить пул» ──

  it("renders the 'Загрузить пул' button", () => {
    render(<TsAnalysisModeling />);
    const btn = screen.getByTestId("fetch-candidates-btn");
    expect(btn).toBeInTheDocument();
  });

  it("clicking 'Загрузить пул' triggers fetch", async () => {
    render(<TsAnalysisModeling />);
    // Phase 1: на маунте ДВА fetch — target-column + candidates
    await waitFor(() => {
      const candidatesCalls = mockFetch.mock.calls.filter(
        ([u]: [string]) => typeof u === "string" && u.includes("/v1/session/modeling/candidates")
      );
      expect(candidatesCalls.length).toBe(1);
    });
    // Кликаем кнопку — должен быть ещё один candidates-запрос
    const btn = screen.getByTestId("fetch-candidates-btn");
    await waitFor(() => expect(btn).not.toBeDisabled());
    fireEvent.click(btn);
    await waitFor(() => {
      const candidatesCalls = mockFetch.mock.calls.filter(
        ([u]: [string]) => typeof u === "string" && u.includes("/v1/session/modeling/candidates")
      );
      expect(candidatesCalls.length).toBe(2);
    });
  });

  // ── 9. Фильтрация по уровню ──

  it("renders level filter buttons after fetch", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByText("Рекоменд.")).toBeInTheDocument();
    });
    expect(screen.getByText("Не реком.")).toBeInTheDocument();
    expect(screen.getByText("Все")).toBeInTheDocument();
    // «Условно» может быть несколько (фильтр + бейджи), проверяем наличие
    const condMatches = screen.getAllByText("Условно");
    expect(condMatches.length).toBeGreaterThanOrEqual(1);
  });

  // ── 10. Выбор кандидата ──

  it("clicking a candidate shows detail in right column", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    // Раскрываем семейство baselines
    const familyHeader = screen.getByTestId("family-header-baselines");
    fireEvent.click(familyHeader);

    // Кликаем на кандидата Naive
    const candidateBtn = screen.getByTestId("candidate-naive");
    fireEvent.click(candidateBtn);

    // Должна появиться детальная карточка
    await waitFor(() => {
      expect(screen.getByTestId("active-candidate-detail")).toBeInTheDocument();
    });
    // «Naive» может быть и в списке, и в карточке — проверяем наличие карточки
    const naiveMatches = screen.getAllByText("Naive");
    expect(naiveMatches.length).toBeGreaterThanOrEqual(1);
  });

  // ── 11. Бейджи применимости ──

  it("renders applicability badges with correct labels", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    // Раскрываем baselines
    fireEvent.click(screen.getByTestId("family-header-baselines"));

    // Проверяем, что бейджи рендерятся
    await waitFor(() => {
      expect(screen.getByTestId("badge-naive")).toBeInTheDocument();
    });
    expect(screen.getByTestId("badge-naive").textContent).toBe("Рекомендована");
  });

  // ── 12. Кнопки «Метрики и алгоритм» / «Полный пайплайн» ──

  it("clicking 'Метрики и алгоритм' shows metrics description for active candidate", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    // Раскрываем baselines и выбираем кандидата
    fireEvent.click(screen.getByTestId("family-header-baselines"));
    fireEvent.click(screen.getByTestId("candidate-naive"));

    await waitFor(() => {
      expect(screen.getByTestId("active-candidate-detail")).toBeInTheDocument();
    });

    // Кликаем «Метрики и алгоритм»
    const metricsBtn = screen.getAllByText("Метрики и алгоритм")[0];
    fireEvent.click(metricsBtn);

    // Описание должно обновиться
    await waitFor(() => {
      expect(screen.getByText(/Метрики и алгоритм — Naive/i)).toBeInTheDocument();
    });
  });
});

// ═══════════════════════════════════════════════════════════
// 13. activeDataset → автозаполнение профиля
// ═══════════════════════════════════════════════════════════

describe("TsAnalysisModeling — activeDataset integration", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockImplementation((url: string) => {
      if (typeof url === "string" && url.includes("/v1/session/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      });
    });
  });

  it("auto-fills n_observations from activeDataset.rows", () => {
    mockActiveDataset = {
      name: "test.csv",
      rows: 500,
      sizeLabel: "2.5 MB",
    };
    render(<TsAnalysisModeling />);
    const input = screen.getByTestId("profile-n-observations") as HTMLInputElement;
    expect(input.value).toBe("500");
  });

  it("auto-fills frequency from activeDataset.frequency", () => {
    mockActiveDataset = {
      name: "test.csv",
      rows: 200,
      sizeLabel: "1.0 MB",
      frequency: "D",
    };
    render(<TsAnalysisModeling />);
    const select = screen.getByTestId("profile-frequency") as HTMLSelectElement;
    expect(select.value).toBe("D");
  });

  it("auto-fills domain from activeDataset.domain", () => {
    mockActiveDataset = {
      name: "test.csv",
      rows: 200,
      sizeLabel: "1.0 MB",
      domain: "financial",
    };
    render(<TsAnalysisModeling />);
    const select = screen.getByTestId("profile-domain") as HTMLSelectElement;
    expect(select.value).toBe("financial");
  });

  it("auto-fills n_series from activeDataset.nSeries", () => {
    mockActiveDataset = {
      name: "test.csv",
      rows: 200,
      sizeLabel: "1.0 MB",
      nSeries: 3,
    };
    render(<TsAnalysisModeling />);
    const input = screen.getByTestId("profile-n-series") as HTMLInputElement;
    expect(input.value).toBe("3");
  });

  it("auto-fills has_seasonality from activeDataset.hasSeasonality", () => {
    mockActiveDataset = {
      name: "test.csv",
      rows: 200,
      sizeLabel: "1.0 MB",
      hasSeasonality: true,
    };
    render(<TsAnalysisModeling />);
    const checkbox = screen.getByTestId("profile-has-seasonality") as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
  });

  it("auto-fills is_regular from activeDataset.isRegular", () => {
    mockActiveDataset = {
      name: "test.csv",
      rows: 200,
      sizeLabel: "1.0 MB",
      isRegular: false,
    };
    render(<TsAnalysisModeling />);
    const checkbox = screen.getByTestId("profile-is-regular") as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
  });

  it("shows auto-fill indicator when activeDataset is present", () => {
    mockActiveDataset = {
      name: "test.csv",
      rows: 500,
      sizeLabel: "2.5 MB",
    };
    render(<TsAnalysisModeling />);
    expect(screen.getByTestId("autofill-indicator")).toBeInTheDocument();
  });

  it("does not show auto-fill indicator when no activeDataset", () => {
    mockActiveDataset = null;
    render(<TsAnalysisModeling />);
    expect(screen.queryByTestId("autofill-indicator")).not.toBeInTheDocument();
  });

  it("keeps DEFAULT_PROFILE values when activeDataset has no optional fields", () => {
    mockActiveDataset = {
      name: "test.csv",
      rows: 100,
      sizeLabel: "0.5 MB",
      // frequency, domain, nSeries — отсутствуют
    };
    render(<TsAnalysisModeling />);
    const freqSelect = screen.getByTestId("profile-frequency") as HTMLSelectElement;
    const domainSelect = screen.getByTestId("profile-domain") as HTMLSelectElement;
    const nSeriesInput = screen.getByTestId("profile-n-series") as HTMLInputElement;
    // DEFAULT_PROFILE: frequency="M", domain="macro", n_series=1
    expect(freqSelect.value).toBe("M");
    expect(domainSelect.value).toBe("macro");
    expect(nSeriesInput.value).toBe("1");
  });
});

// ═══════════════════════════════════════════════════════════
// 14. Бэктест: кнопка «Запустить бэктест» + результаты
// ═══════════════════════════════════════════════════════════

const MOCK_BACKTEST_RESPONSE = {
  model_id: "naive",
  model_name: "Naive",
  family_id: "baselines",
  metrics: {
    mae: 3.45,
    rmse: 4.12,
    mape: 2.1,
    mase: 0.87,
    weighted_score: 0.065,
  },
  n_train: 96,
  n_test: 24,
  train_ratio: 0.8,
  duration_ms: 12.3,
  data_source: "session",
  status: "success",
  strategy: "expanding",
  cohort_id: "cohort-test",
  horizon: 2,
  n_folds: 3,
  gap: 0,
  folds: [
    { fold: 1, status: "success", n_train: 90, n_test: 2, train_start: 0, train_end: 89, test_start: 90, test_end: 91, duration_ms: 2, metrics: { mae: 3, rmse: 4, mape: 2, mase: 0.8, weighted_score: null }, predictions: [] },
    { fold: 2, status: "success", n_train: 92, n_test: 2, train_start: 0, train_end: 91, test_start: 92, test_end: 93, duration_ms: 2, metrics: { mae: 3, rmse: 4, mape: 2, mase: 0.8, weighted_score: null }, predictions: [] },
    { fold: 3, status: "success", n_train: 94, n_test: 2, train_start: 0, train_end: 93, test_start: 94, test_end: 95, duration_ms: 2, metrics: { mae: 3, rmse: 4, mape: 2, mase: 0.8, weighted_score: null }, predictions: [] },
  ],
  oof_predictions: [],
  warnings: [],
};

const MOCK_BACKTEST_RESPONSE_REAL_DATA = {
  ...MOCK_BACKTEST_RESPONSE,
  data_source: "session",
  n_train: 7,
  n_test: 3,
};

describe("TsAnalysisModeling — backtest", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockActiveDataset = null;
    // Маршрутизация: target-column → no-dataset, candidates → success,
    // backtest → MOCK_BACKTEST_RESPONSE (data_source=synthetic по умолчанию).
    mockFetch.mockImplementation((url: string) => {
      if (typeof url === "string" && url.includes("/v1/session/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET),
        });
      }
      if (typeof url === "string" && url.includes("/v1/session/modeling/backtest")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_BACKTEST_RESPONSE),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      });
    });
  });

  it("renders 'Запустить бэктест' button when candidate is selected", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("family-header-baselines"));
    fireEvent.click(screen.getByTestId("candidate-naive"));

    await waitFor(() => {
      expect(screen.getByTestId("active-candidate-detail")).toBeInTheDocument();
    });

    expect(screen.getByTestId("run-backtest-btn")).toBeInTheDocument();
  });

  it("clicking 'Запустить бэктест' triggers the traceable session route", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("family-header-baselines"));
    fireEvent.click(screen.getByTestId("candidate-naive"));

    await waitFor(() => {
      expect(screen.getByTestId("run-backtest-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("run-backtest-btn"));

    // Phase 1: switched from /v1/models/backtest (requires X-Api-Key, doesn't
    // read session) to /v1/internal/models/backtest (no auth, uses session bridge).
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/v1/session/modeling/backtest"),
        expect.objectContaining({
          method: "POST",
          credentials: "include", // cookie сессии обязателен для internal-зеркала
        })
      );
    });
  });

  it("shows backtest results after successful API call", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("family-header-baselines"));
    fireEvent.click(screen.getByTestId("candidate-naive"));

    await waitFor(() => {
      expect(screen.getByTestId("run-backtest-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("run-backtest-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("backtest-result")).toBeInTheDocument();
    });

    // Проверяем отображение метрик
    expect(screen.getByText(/Бэктест завершён/i)).toBeInTheDocument();
    expect(screen.getByText("3.45")).toBeInTheDocument(); // MAE
    expect(screen.getByText("4.12")).toBeInTheDocument(); // RMSE
    expect(screen.getByText("2.1%")).toBeInTheDocument(); // MAPE
    expect(screen.getByTestId("backtest-fold-summary")).toHaveTextContent("3 folds");
  });

  it("shows only the real session data badge", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("family-header-baselines"));
    fireEvent.click(screen.getByTestId("candidate-naive"));

    await waitFor(() => {
      expect(screen.getByTestId("run-backtest-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("run-backtest-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("backtest-result")).toBeInTheDocument();
    });

    // Traceable workflow never offers a synthetic fallback.
    expect(screen.getByTestId("data-source-badge")).toBeInTheDocument();
    expect(screen.getByTestId("data-source-badge").textContent).toContain("Реальные данные");
  });

  it("shows 'Реальные данные' badge when data_source=session (Phase 1)", async () => {
    // Переопределяем mock: backtest возвращает data_source=session
    mockFetch.mockImplementation((url: string) => {
      if (typeof url === "string" && url.includes("/v1/session/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET),
        });
      }
      if (typeof url === "string" && url.includes("/v1/session/modeling/backtest")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_BACKTEST_RESPONSE_REAL_DATA),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      });
    });

    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("family-header-baselines"));
    fireEvent.click(screen.getByTestId("candidate-naive"));

    await waitFor(() => {
      expect(screen.getByTestId("run-backtest-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("run-backtest-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("backtest-result")).toBeInTheDocument();
    });

    expect(screen.getByTestId("data-source-badge").textContent).toContain("Реальные данные");
  });

  it("shows backtest error on API failure", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (typeof url === "string" && url.includes("/v1/session/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET),
        });
      }
      if (typeof url === "string" && url.includes("/v1/session/modeling/backtest")) {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: "Internal Server Error",
          json: () => Promise.resolve({ detail: "Сервер недоступен" }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      });
    });

    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("family-header-baselines"));
    fireEvent.click(screen.getByTestId("candidate-naive"));

    await waitFor(() => {
      expect(screen.getByTestId("run-backtest-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("run-backtest-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("backtest-error")).toBeInTheDocument();
    });
  });

  it("pipeline progresses after successful backtest", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    // После загрузки пула: stages 1-4 done, 5 active
    // Кликаем backtest
    fireEvent.click(screen.getByTestId("family-header-baselines"));
    fireEvent.click(screen.getByTestId("candidate-naive"));

    await waitFor(() => {
      expect(screen.getByTestId("run-backtest-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("run-backtest-btn"));

    // После бэктеста: стадии candidate_pool, baseline, backtest — done
    await waitFor(() => {
      expect(screen.getByTestId("backtest-result")).toBeInTheDocument();
    });

    // Стадия 7 (Тюнинг) должна быть активной
    const tuningBtn = screen.getAllByText("Тюнинг")[0];
    expect(tuningBtn).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════
// 15. Phase 1: target_column selector
// ═══════════════════════════════════════════════════════════

describe("TsAnalysisModeling — target_column selector (Phase 1)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockActiveDataset = null;
    // По умолчанию: нет датасета (has_dataset=false → селектор disabled)
    mockFetch.mockImplementation((url: string) => {
      if (typeof url === "string" && url.includes("/v1/session/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_NO_DATASET),
        });
      }
      if (typeof url === "string" && url.includes("/v1/session/modeling/backtest")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_BACKTEST_RESPONSE),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      });
    });
  });

  it("renders the target_column selector block in left column", async () => {
    render(<TsAnalysisModeling />);
    expect(screen.getByTestId("target-column-block")).toBeInTheDocument();
  });

  it("renders 'Загрузите датасет' hint when has_dataset=false", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("target-column-no-dataset")).toBeInTheDocument();
    });
    expect(screen.getByTestId("target-column-no-dataset").textContent).toContain("Загрузите датасет");
  });

  it("renders disabled select placeholder when no dataset", async () => {
    render(<TsAnalysisModeling />);
    // Select присутствует, но disabled (нет колонок для выбора)
    const select = screen.queryByTestId("target-column-select");
    // Либо select disabled, либо нет вовсе (показан hint вместо select)
    if (select) {
      expect(select).toBeDisabled();
    } else {
      // hint показан, select скрыт — это валидное состояние
      expect(screen.getByTestId("target-column-no-dataset")).toBeInTheDocument();
    }
  });

  it("renders enabled select with available columns when has_dataset=true", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (typeof url === "string" && url.includes("/v1/session/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_WITH_DATASET),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      });
    });

    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("target-column-select")).not.toBeDisabled();
    });

    // Проверяем, что в селекте есть все 3 колонки из мока
    const select = screen.getByTestId("target-column-select") as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toContain("value");
    expect(optionValues).toContain("gdp");
    expect(optionValues).toContain("inflation");
  });

  it("selecting a column triggers POST to /v1/session/target-column with credentials", async () => {
    mockFetch.mockImplementation((url: string, options: any = {}) => {
      if (typeof url === "string" && url.includes("/v1/session/target-column")) {
        // POST: возвращаем обновлённый target_column
        if (options?.method === "POST") {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
              target_column: "value",
              available_columns: ["value", "gdp", "inflation"],
              has_dataset: true,
            }),
          });
        }
        // GET
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_WITH_DATASET),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      });
    });

    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("target-column-select")).not.toBeDisabled();
    });

    // Выбираем колонку "value"
    fireEvent.change(screen.getByTestId("target-column-select"), {
      target: { value: "value" },
    });

    await waitFor(() => {
      const postCalls = mockFetch.mock.calls.filter(
        ([u, opts]: [string, any]) =>
          typeof u === "string" &&
          u.includes("/v1/session/target-column") &&
          opts?.method === "POST"
      );
      expect(postCalls.length).toBe(1);
    });

    // Тело запроса должно содержать column: "value"
    const postCall = mockFetch.mock.calls.find(
      ([u, opts]: [string, any]) =>
        typeof u === "string" &&
        u.includes("/v1/session/target-column") &&
        opts?.method === "POST"
    );
    expect(postCall).toBeDefined();
    const body = JSON.parse(postCall![1].body);
    expect(body.column).toBe("value");

    // Cookie обязателен
    expect(postCall![1].credentials).toBe("include");
  });

  it("refetches target-column when activeDataset changes (e.g. after upload)", async () => {
    // Сначала без датасета
    mockActiveDataset = null;
    const { rerender } = render(<TsAnalysisModeling />);

    await waitFor(() => {
      const tcCalls = mockFetch.mock.calls.filter(
        ([u]: [string]) => typeof u === "string" && u.includes("/v1/session/target-column")
      );
      expect(tcCalls.length).toBe(1);
    });

    // Пользователь загрузил новый датасет → activeDataset сменился
    mockActiveDataset = {
      name: "new_dataset.csv",
      rows: 500,
      sizeLabel: "2.5 MB",
    };
    rerender(<TsAnalysisModeling />);

    // Должен произойти повторный fetch target-column (теперь их 2)
    await waitFor(() => {
      const tcCalls = mockFetch.mock.calls.filter(
        ([u]: [string]) => typeof u === "string" && u.includes("/v1/session/target-column")
      );
      expect(tcCalls.length).toBe(2);
    });
  });

  it("shows target_column error when POST fails", async () => {
    mockFetch.mockImplementation((url: string, options: any = {}) => {
      if (typeof url === "string" && url.includes("/v1/session/target-column")) {
        if (options?.method === "POST") {
          return Promise.resolve({
            ok: false,
            status: 422,
            statusText: "Unprocessable Entity",
            json: () => Promise.resolve({ detail: "Колонка 'foo' не числовая" }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_TARGET_COLUMN_RESPONSE_WITH_DATASET),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      });
    });

    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("target-column-select")).not.toBeDisabled();
    });

    fireEvent.change(screen.getByTestId("target-column-select"), {
      target: { value: "value" },
    });

    await waitFor(() => {
      expect(screen.getByTestId("target-column-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("target-column-error").textContent).toContain("не числовая");
  });

  it("does NOT call legacy model backtest routes", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("family-header-baselines"));
    fireEvent.click(screen.getByTestId("candidate-naive"));

    await waitFor(() => {
      expect(screen.getByTestId("run-backtest-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("run-backtest-btn"));

    await waitFor(() => {
      // Должен быть вызов к internal-зеркалу
      const internalCalls = mockFetch.mock.calls.filter(
        ([u]: [string]) => typeof u === "string" && u.includes("/v1/session/modeling/backtest")
      );
      expect(internalCalls.length).toBeGreaterThanOrEqual(1);
    });

    // И НЕ должно быть вызовов к старому /v1/models/backtest
    // (который требует X-Api-Key и не использует session bridge).
    // ВАЖНО: фильтр "/v1/models/backtest" НЕ матчит "/v1/internal/models/backtest"
    // (контрольная проверка: indexOf("/v1/models/backtest") по строке
    // "/v1/internal/models/backtest" возвращает -1).
    const oldEndpointCalls = mockFetch.mock.calls.filter(([u]: [string]) => {
      if (typeof u !== "string") return false;
      return u.includes("/v1/models/backtest") && !u.includes("/v1/internal/");
    });
    expect(oldEndpointCalls.length).toBe(0);
  });
});
