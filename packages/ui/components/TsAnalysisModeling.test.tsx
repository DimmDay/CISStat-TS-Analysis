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
const MOCK_CANDIDATES_RESPONSE = {
  candidates: [
    {
      model_id: "naive",
      model_name: "Naive",
      family_id: "baselines",
      level: "RECOMMENDED",
      rule_id: "P07",
      message: "Baseline-модель всегда рекомендуется",
      rank: 1,
    },
    {
      model_id: "seasonal_naive",
      model_name: "Seasonal Naive",
      family_id: "baselines",
      level: "RECOMMENDED",
      rule_id: "P07",
      message: "Baseline-модель всегда рекомендуется",
      rank: 1,
    },
    {
      model_id: "drift",
      model_name: "Drift",
      family_id: "baselines",
      level: "RECOMMENDED",
      rule_id: "P07",
      message: "Baseline-модель всегда рекомендуется",
      rank: 1,
    },
    {
      model_id: "mean",
      model_name: "Mean",
      family_id: "baselines",
      level: "RECOMMENDED",
      rule_id: "P07",
      message: "Baseline-модель всегда рекомендуется",
      rank: 1,
    },
    {
      model_id: "ets",
      model_name: "ETS (Auto)",
      family_id: "exponential_smoothing",
      level: "RECOMMENDED",
      rule_id: "P01",
      message: "Модель рекомендована для данного профиля",
      rank: 1,
    },
    {
      model_id: "arima_auto",
      model_name: "Auto-ARIMA",
      family_id: "arima",
      level: "RECOMMENDED",
      rule_id: "P02",
      message: "Модель рекомендована для данного профиля",
      rank: 1,
    },
    {
      model_id: "garch",
      model_name: "GARCH(p,q)",
      family_id: "volatility",
      level: "NOT_RECOMMENDED",
      rule_id: "D03",
      message: "Модель не рекомендуется: область не financial",
      rank: 3,
    },
    {
      model_id: "prophet",
      model_name: "Prophet",
      family_id: "structural",
      level: "CONDITIONALLY_APPLICABLE",
      rule_id: "C03",
      message: "Условно применима: нет сезонности",
      rank: 2,
    },
    {
      model_id: "var",
      model_name: "VAR",
      family_id: "multivariate",
      level: "NOT_APPLICABLE",
      rule_id: "F02",
      message: "Неприменима: одномерный ряд",
      rank: 4,
    },
  ],
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
// @ts-ignore — mock fetch с частичным Response
const mockFetch: any = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
  })
);
// @ts-ignore
global.fetch = mockFetch;

// ═══════════════════════════════════════════════════════════
// Test suites
// ═══════════════════════════════════════════════════════════

describe("TsAnalysisModeling", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockActiveDataset = null; // ← по умолчанию без датасета
    // Восстановим mock по умолчанию (success)
    mockFetch.mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      })
    );
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
      expect(screen.getByText(label)).toBeInTheDocument();
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
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/models/candidates"),
      expect.objectContaining({ method: "POST" })
    );
  });

  it("renders candidate pool after successful fetch", async () => {
    render(<TsAnalysisModeling />);
    await waitFor(() => {
      expect(screen.getByTestId("candidate-pool")).toBeInTheDocument();
    });
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

  // ── 8. Кнопка «Загрузить пул» ──

  it("renders the 'Загрузить пул' button", () => {
    render(<TsAnalysisModeling />);
    const btn = screen.getByTestId("fetch-candidates-btn");
    expect(btn).toBeInTheDocument();
  });

  it("clicking 'Загрузить пул' triggers fetch", async () => {
    render(<TsAnalysisModeling />);
    // Первый fetch уже был при маунте
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    // Кликаем кнопку
    const btn = screen.getByTestId("fetch-candidates-btn");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
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
    mockFetch.mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_CANDIDATES_RESPONSE),
      })
    );
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
