// packages/ui/components/TsAnalysisEDA.test.tsx
//
// Тесты для компонента «Разведочный EDA» — в частности:
// 1. Рендер модуля и 11 исследований степпера
// 2. Кнопка «Справка» переключает секцию
// 3. Expandable description box: chevron, overlay, collapse

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TsAnalysisEDA } from "./TsAnalysisEDA";

let mockActiveDataset: { datasetId?: string; name: string; rows: number; sizeLabel: string } | null = null;

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ activeDataset: mockActiveDataset }),
}));

const STATS_RESPONSE = {
  min_non_null_for_stats: 2,
  columns: [
    {
      name: "Year",
      non_null_count: 4,
      stats: {
        mean: 2021.5,
        median: 2021.5,
        std: 1.29,
        skewness: 0,
        kurtosis: -1.2,
        q1: 2020.75,
        q3: 2022.25,
        iqr: 1.5,
        distribution_hint: "Близко к нормальному",
      },
    },
    {
      name: "Price",
      non_null_count: 4,
      stats: {
        mean: 25,
        median: 25,
        std: 12.91,
        skewness: 0,
        kurtosis: -1.2,
        q1: 17.5,
        q3: 32.5,
        iqr: 15,
        distribution_hint: "Близко к нормальному",
      },
    },
    {
      name: "Volume",
      non_null_count: 4,
      stats: {
        mean: 250,
        median: 250,
        std: 129.1,
        skewness: 0,
        kurtosis: -1.2,
        q1: 175,
        q3: 325,
        iqr: 150,
        distribution_hint: "Близко к нормальному",
      },
    },
  ],
};

const CORRELATION_RESPONSE = {
  column: "Price",
  applicable: true,
  reason: null,
  n_observations: 80,
  missing_count: 0,
  requested_max_lags: 40,
  max_lag: 20,
  alpha: 0.05,
  order_source: "time_column",
  order_column: "Date",
  order_warning: null,
  frequency: "D",
  acf: [
    { lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false },
    { lag: 1, value: 0.7, confidence_lower: -0.2, confidence_upper: 0.2, significant: true },
  ],
  pacf: [
    { lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false },
    { lag: 1, value: 0.65, confidence_lower: -0.2, confidence_upper: 0.2, significant: true },
  ],
  significant_acf_lags: [1],
  significant_pacf_lags: [1],
  ljung_box_lag: 10,
  ljung_box_pvalue: 0.002,
  is_white_noise: false,
  suggested_p: 1,
  suggested_q: 1,
};

const IH_RESPONSE = {
  column: "Price",
  applicable: true,
  reason: null,
  n_observations: 240,
  features_analyzed: 4,
  sharpness: 0.25,
  min_samples: 20,
  top_k: 10,
  max_lag: 3,
  permutations: 49,
  target_entropy: 2,
  target_bins: 4,
  order_source: "time_column",
  order_column: "Date",
  order_warning: null,
  frequency: "D",
  lag_features_included: true,
  results: [{
    feature: "Volume", kind: "numeric", dtype: "float64", n_observations: 240,
    r: 0.7, r_adjusted: 0.64, mi: 1.4, h_x: 2, h_y: 2,
    n_bins_x: 4, n_bins_y: 4, permutation_baseline: 0.06,
    p_value: 0.02, q_value: 0.04, significant: true, error: null,
  }],
  synergies: [],
  conditional_feature: "Volume",
  conditional_x_bins: ["0", "1"],
  conditional_y_bins: ["0", "1"],
  conditional_matrix: [{ x_bin: "0", values: [80, 20] }, { x_bin: "1", values: [20, 80] }],
  recommendations: ["Volume — наиболее информативный фактор"],
};

const SEASONALITY_RESPONSE = {
  column: "Price", applicable: true, reason: null, n_observations: 240, missing_count: 0,
  min_cycles: 3, max_candidates: 5, max_period: 80, detrend: "linear", window: "hann",
  order_source: "time_column", order_column: "Date", order_warning: null, frequency: "D",
  spectral_entropy: 0.2, dominant_period: 12, dominant_strength: 0.84, confirmed_periods: 1,
  fft: [{ frequency: 1 / 12, period: 12, amplitude: 3, power: null, is_peak: true }],
  periodogram: [{ frequency: 1 / 12, period: 12, amplitude: null, power: 4.5, is_peak: true }],
  candidates: [{
    rank: 1, period: 12, period_rounded: 12, frequency: 1 / 12, amplitude: 3, power: 4.5,
    power_share: 75, prominence: 4.2, spectral_snr: 30, autocorrelation: 0.9,
    seasonal_strength: 0.84, cycles: 20, confirmed: true, calendar_hint: null, harmonic_of: null,
  }],
  phase_period: 12,
  phase_profile: Array.from({ length: 12 }, (_, index) => ({ phase: index + 1, mean: index / 10, lower: index / 10 - 0.1, upper: index / 10 + 0.1, count: 20 })),
  recommendations: ["Подтверждён период 12"],
};

const STATIONARITY_RESPONSE = {
  column: "Price", applicable: true, reason: null, n_observations: 240, missing_count: 0,
  min_observations: 30, alpha: 0.05, requested_rolling_window: 12, rolling_window: 12,
  consensus: "stationary", recommendation: "Ряд стационарен вокруг уровня.",
  order_source: "time_column", order_column: "Date", order_warning: null, frequency: "D",
  breakpoint_index: 120, breakpoint_label: "2020-04-30T00:00:00",
  tests: [
    { id: "adf_level", label: "ADF (уровень)", null_hypothesis: "Единичный корень", alternative_hypothesis: "Стационарность вокруг уровня", available: true, statistic: -4.2, p_value: 0.001, lags: 2, reject_null: true, supports_stationarity: true, critical_values: { "5%": -2.9 }, note: null },
    { id: "adf_trend", label: "ADF (тренд)", null_hypothesis: "Единичный корень", alternative_hypothesis: "Стационарность вокруг тренда", available: true, statistic: -4.4, p_value: 0.004, lags: 2, reject_null: true, supports_stationarity: true, critical_values: { "5%": -3.4 }, note: null },
    { id: "kpss_level", label: "KPSS (уровень)", null_hypothesis: "Стационарность вокруг уровня", alternative_hypothesis: "Единичный корень", available: true, statistic: 0.1, p_value: 0.1, lags: 4, reject_null: false, supports_stationarity: true, critical_values: { "5%": 0.463 }, note: null },
    { id: "kpss_trend", label: "KPSS (тренд)", null_hypothesis: "Стационарность вокруг тренда", alternative_hypothesis: "Единичный корень", available: true, statistic: 0.05, p_value: 0.1, lags: 4, reject_null: false, supports_stationarity: true, critical_values: { "5%": 0.146 }, note: null },
    { id: "pp", label: "Phillips–Perron", null_hypothesis: "Единичный корень", alternative_hypothesis: "Стационарность вокруг уровня", available: true, statistic: -4.1, p_value: 0.001, lags: 12, reject_null: true, supports_stationarity: true, critical_values: { "5%": -2.9 }, note: null },
    { id: "zivot_andrews", label: "Zivot–Andrews", null_hypothesis: "Единичный корень с одним разрывом", alternative_hypothesis: "Стационарность с одним разрывом", available: true, statistic: -5.2, p_value: 0.02, lags: 2, reject_null: true, supports_stationarity: true, critical_values: { "5%": -4.8 }, note: null },
  ],
  rolling: Array.from({ length: 24 }, (_, index) => ({ index, label: `2020-01-${String(index + 1).padStart(2, "0")}T00:00:00`, value: index / 10, rolling_mean: index < 11 ? null : index / 10, rolling_std: index < 11 ? null : 0.3 })),
  rolling_sampled: false, rolling_original_count: 240,
  recommendations: ["ADF и KPSS согласованы."], warnings: [],
};

const DISTRIBUTION_RESPONSE = {
  column: "Price", applicable: true, reason: null, n_observations: 240,
  missing_count: 0, min_observations: 8, alpha: 0.05, requested_bins: 20,
  bins: 20, is_discrete: false, unique_count: 240, mean: 10, median: 9.8,
  std: 2, q1: 8.5, q3: 11.2, iqr: 2.7, mad: 1.3, skewness: 0.08,
  excess_kurtosis: -0.12, shape_label: "Почти симметричное распределение",
  normality_applicable: true, normality_status: "compatible", qq_r: 0.997,
  qq_slope: 1.95, qq_intercept: 10, tests: [
    { id: "shapiro", label: "Shapiro–Wilk", available: true, statistic: 0.99, p_value: 0.32, adjusted_p_value: 0.64, reject_normality: false, n_used: 240, calibration: "standard", note: null },
    { id: "jarque_bera", label: "Jarque–Bera", available: true, statistic: 0.8, p_value: 0.67, adjusted_p_value: 0.67, reject_normality: false, n_used: 240, calibration: "monte_carlo", note: "p-значение откалибровано методом Монте-Карло." },
    { id: "lilliefors", label: "K–S (Лиллиефорс)", available: true, statistic: 0.04, p_value: 0.44, adjusted_p_value: 0.64, reject_normality: false, n_used: 240, calibration: "table", note: null },
  ],
  histogram: [{ x0: 4, x1: 6, count: 10, density: 0.02, normal_expected_count: 8.2 }],
  density: [{ x: 4, empirical: 0.01, normal: 0.005 }, { x: 10, empirical: 0.2, normal: 0.199 }],
  qq: [{ theoretical: -2, observed: 6, reference: 6.1 }, { theoretical: 2, observed: 14, reference: 13.9 }],
  cdf: [{ x: 6, empirical: 0.03, normal: 0.023 }, { x: 14, empirical: 0.98, normal: 0.977 }],
  recommendation: "Форма ряда совместима с нормальным распределением.",
  recommendations: ["Сопоставьте вывод с Q–Q графиком."],
  warnings: ["Формальная нормальность для модели проверяется на остатках."],
};

const STRUCTURAL_BREAKS_RESPONSE = {
  column: "Price", applicable: true, reason: null, n_observations: 180, missing_count: 0,
  min_observations: 60, alpha: 0.05, requested_min_segment: 20, min_segment: 20,
  requested_penalty_multiplier: 2, penalty_multiplier: 2, penalty_value: 1.8,
  max_breaks: 10, jump: 1, model: "piecewise_linear", status: "breaks_detected",
  break_count: 1, supported_count: 1, order_source: "time_column", order_column: "Date",
  order_warning: null, frequency: "D", cusum: { statistic: 2.1, p_value: 0.001, reject_stability: true, critical_values: { "5%": 1.36 } },
  candidates: [{ rank: 1, index: 90, label: "2024-03-31T00:00:00", level_change: 3, standardized_level_change: 1.9, slope_before: 0.001, slope_after: 0.002, slope_change: 0.001, rss_gain: 0.88, chow_statistic: 340, p_value: 0.0001, adjusted_p_value: 0.0001, stability_support: 1, supported: true }],
  segments: [
    { id: 1, start_index: 0, end_index: 89, start_label: "2024-01-01T00:00:00", end_label: "2024-03-30T00:00:00", n_observations: 90, mean: 0, std: 0.2, slope: 0.001 },
    { id: 2, start_index: 90, end_index: 179, start_label: "2024-03-31T00:00:00", end_label: "2024-06-28T00:00:00", n_observations: 90, mean: 3, std: 0.2, slope: 0.002 },
  ],
  series: [{ index: 0, label: "2024-01-01T00:00:00", value: 0.1, fitted: 0, segment_id: 1 }, { index: 90, label: "2024-03-31T00:00:00", value: 3.1, fitted: 3, segment_id: 2 }],
  cusum_path: [{ index: 0, label: "2024-01-01T00:00:00", value: 0.1, upper: 1.36, lower: -1.36 }, { index: 90, label: "2024-03-31T00:00:00", value: 2.1, upper: 1.36, lower: -1.36 }],
  sensitivity: [{ penalty_multiplier: 1, index: 90, label: "2024-03-31T00:00:00" }, { penalty_multiplier: 2, index: 90, label: "2024-03-31T00:00:00" }],
  series_sampled: false, series_original_count: 180, cusum_sampled: false,
  recommendation: "Устойчивый структурный сдвиг около 2024-03-31.",
  recommendations: ["Проверьте модели по режимам."],
  warnings: ["Chow после выбора PELT является диагностикой."],
};

function routeFetch(input: RequestInfo | URL, init?: RequestInit) {
  const url = String(input);
  if (url.includes("/target-column")) {
    const selected = init?.method === "POST"
      ? JSON.parse(String(init.body)).column
      : null;
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        target_column: selected,
        suggested_column: "Price",
        available_columns: ["Year", "Price", "Volume"],
        has_dataset: true,
      }),
    });
  }
  if (url.includes("/dataset/stats")) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(STATS_RESPONSE) });
  }
  if (url.includes("/dataset/eda-correlation")) {
    const column = new URL(url).searchParams.get("column") ?? "Price";
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ...CORRELATION_RESPONSE, column }),
    });
  }
  if (url.includes("/dataset/eda-ih")) {
    const column = new URL(url).searchParams.get("column") ?? "Price";
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ...IH_RESPONSE, column }),
    });
  }
  if (url.includes("/dataset/eda-seasonality")) {
    const column = new URL(url).searchParams.get("column") ?? "Price";
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ...SEASONALITY_RESPONSE, column }),
    });
  }
  if (url.includes("/dataset/eda-stationarity")) {
    const column = new URL(url).searchParams.get("column") ?? "Price";
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ...STATIONARITY_RESPONSE, column }),
    });
  }
  if (url.includes("/dataset/eda-distribution")) {
    const column = new URL(url).searchParams.get("column") ?? "Price";
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ...DISTRIBUTION_RESPONSE, column }),
    });
  }
  if (url.includes("/dataset/eda-structural-breaks")) {
    const column = new URL(url).searchParams.get("column") ?? "Price";
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ...STRUCTURAL_BREAKS_RESPONSE, column }),
    });
  }
  if (url.includes("/dataset/distribution")) {
    const column = new URL(url).searchParams.get("column") ?? "Price";
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        column,
        non_null_count: 4,
        min: 10,
        max: 40,
        scatter: [{ x: 0, y: 10 }],
        scatter_sampled: false,
        scatter_sampling_method: null,
        scatter_original_count: 4,
        histogram: [{ x0: 10, x1: 20, count: 2 }],
        kde: [{ x: 10, y: 0.1 }],
      }),
    });
  }
  return Promise.reject(new Error(`Unexpected fetch: ${url}`));
}

describe("TsAnalysisEDA", () => {
  beforeEach(() => {
    mockActiveDataset = null;
    global.fetch = jest.fn(() => new Promise(() => {}));
  });

  it("renders the module title", () => {
    render(<TsAnalysisEDA />);
    expect(screen.getByText("Разведочный EDA")).toBeInTheDocument();
  });

  it("renders the right control-panel title with the validation/preprocessing layout", () => {
    render(<TsAnalysisEDA />);

    const controlPanelTitle = screen.getByRole("heading", {
      level: 2,
      name: "Панель управления",
    });

    expect(controlPanelTitle).toHaveClass("text-lg", "font-semibold", "text-neutral-800");
    expect(controlPanelTitle.closest("aside")).toHaveClass("pt-1");
  });

  it("renders all 11 EDA investigations in the stepper", () => {
    render(<TsAnalysisEDA />);
    const stepLabels = [
      "Описательные статистики", "Корреляция (ACF/PACF)", "IH-анализ",
      "Сезонность и периодичность", "Верификация стационарности",
      "Распределение", "Структурные сдвиги", "Отбор признаков",
      "Стратегия валидации", "Матрица моделей", "Паспорт свойств ряда",
    ];
    stepLabels.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  });

  it("uses the shared target selector and does not default to the numeric time axis", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);

    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    await waitFor(() => expect(selector).toHaveValue("Price"));
    expect(screen.getByRole("option", { name: "Year" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Volume" })).toBeInTheDocument();
    expect(
      await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Mean", { selector: "div" }).nextElementSibling).toHaveTextContent("25");

    fireEvent.change(selector, { target: { value: "Volume" } });
    await waitFor(() => expect(selector).toHaveValue("Volume"));
    await waitFor(() => {
      expect(screen.getByText("Mean", { selector: "div" }).nextElementSibling).toHaveTextContent("250");
    });
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/target-column"),
      expect.objectContaining({ method: "POST", body: JSON.stringify({ column: "Volume" }) }),
    );
  });

  it("refetches the shared target when the active dataset changes", async () => {
    mockActiveDataset = { datasetId: "dataset-a", name: "prices.csv", rows: 4, sizeLabel: "1 KB" };
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    const { rerender } = render(<TsAnalysisEDA />);

    await waitFor(() => {
      const targetGets = (global.fetch as jest.Mock).mock.calls.filter(
        ([url, options]) => String(url).includes("/target-column") && options?.method === "GET",
      );
      expect(targetGets).toHaveLength(1);
    });

    mockActiveDataset = { datasetId: "dataset-b", name: "prices.csv", rows: 8, sizeLabel: "2 KB" };
    rerender(<TsAnalysisEDA />);

    await waitFor(() => {
      const targetGets = (global.fetch as jest.Mock).mock.calls.filter(
        ([url, options]) => String(url).includes("/target-column") && options?.method === "GET",
      );
      expect(targetGets).toHaveLength(2);
    });
  });

  it("shows the specialized metric and pipeline descriptions", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });

    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/N = число непустых наблюдений/i)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Полный пайплайн" })[0]);
    expect(screen.getByText(/GET \/v1\/session\/dataset\/stats/i)).toBeInTheDocument();
  });

  it("recalculates the descriptive profile on demand", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });
    const statsCallsBefore = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/stats")).length;

    fireEvent.click(screen.getByRole("button", { name: "Пересчитать статистики" }));

    await waitFor(() => {
      const statsCallsAfter = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/stats")).length;
      expect(statsCallsAfter).toBe(statsCallsBefore + 1);
    });
  });

  it("loads correlation for the shared target and exposes three overview views", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    await waitFor(() => expect(selector).toHaveValue("Price"));

    fireEvent.click(screen.getByRole("button", { name: /^Корреляция \(ACF\/PACF\)/ }));

    expect(await screen.findByRole("img", { name: "График ACF для Price" })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/dataset/eda-correlation?column=Price&max_lags=40"),
      { credentials: "include" },
    );
    fireEvent.click(screen.getByRole("tab", { name: "PACF" }));
    expect(screen.getByRole("img", { name: "График PACF для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Таблица" }));
    expect(screen.getByRole("table", { name: "Значения ACF и PACF по лагам" })).toBeInTheDocument();
    expect(screen.getByText("Ljung–Box p", { selector: "div" }).nextElementSibling).toHaveTextContent("0,002");
  });

  it("shows the correlation-specific methodology and recalculates it", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });

    const correlationButton = screen.getByRole("button", { name: /^Корреляция \(ACF\/PACF\)/ });
    fireEvent.click(correlationButton);
    await screen.findByRole("img", { name: "График ACF для Price" });

    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/ACF\(k\) = corr/i)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Полный пайплайн" })[0]);
    expect(screen.getByText(/dataset\/eda-correlation/i)).toBeInTheDocument();

    const callsBefore = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-correlation")).length;
    fireEvent.click(screen.getByRole("button", { name: "Пересчитать корреляцию" }));
    await waitFor(() => {
      const callsAfter = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-correlation")).length;
      expect(callsAfter).toBe(callsBefore + 1);
    });
  });

  it("loads IH analysis for the shared target and exposes the visual overview", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    await waitFor(() => expect(selector).toHaveValue("Price"));

    fireEvent.click(screen.getByRole("button", { name: /^IH-анализ/ }));

    expect(await screen.findByRole("img", { name: "Рейтинг IH-информативности для Price" })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/dataset/eda-ih?column=Price&sharpness=0.25&min_samples=20&top_k=10&max_lag=3&permutations=49"),
      { credentials: "include" },
    );
    expect(screen.getByText("H(Y), бит", { selector: "div" }).nextElementSibling).toHaveTextContent("2");
    expect(screen.getByText("Топ R adj.", { selector: "div" }).nextElementSibling).toHaveTextContent("0,64");
  });

  it("uses IH-specific methodology, reacts to sharpness and supports refresh", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });
    fireEvent.click(screen.getByRole("button", { name: /^IH-анализ/ }));
    await screen.findByRole("img", { name: "Рейтинг IH-информативности для Price" });

    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/R\(Y\|X\) = I\(X;Y\)\/H\(Y\)/i)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Полный пайплайн" })[0]);
    expect(screen.getByText(/dataset\/eda-ih/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Резкость дискретизации" }), {
      target: { value: "0.5" },
    });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("sharpness=0.5"),
      { credentials: "include" },
    ));
    await screen.findByRole("button", { name: "Пересчитать IH-анализ" });

    const callsBefore = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-ih")).length;
    fireEvent.click(screen.getByRole("button", { name: "Пересчитать IH-анализ" }));
    await waitFor(() => {
      const callsAfter = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-ih")).length;
      expect(callsAfter).toBe(callsBefore + 1);
    });
  });

  it("loads seasonality for the shared target and exposes four overview views", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    await waitFor(() => expect(selector).toHaveValue("Price"));

    fireEvent.click(screen.getByRole("button", { name: /^Сезонность и периодичность/ }));

    expect(await screen.findByRole("img", { name: "FFT-спектр для Price" })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/dataset/eda-seasonality?column=Price&min_cycles=3&max_candidates=5"),
      { credentials: "include" },
    );
    fireEvent.click(screen.getByRole("tab", { name: "Периодограмма" }));
    expect(screen.getByRole("img", { name: "Периодограмма для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Фазовый профиль" }));
    expect(screen.getByRole("img", { name: "Фазовый профиль периода 12 для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Кандидаты" }));
    expect(screen.getByRole("table", { name: "Периоды-кандидаты" })).toBeInTheDocument();
    expect(screen.getByText("Топ-период", { selector: "div" }).nextElementSibling).toHaveTextContent("12");
  });

  it("uses seasonality-specific methodology, reacts to parameters and supports refresh", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });
    fireEvent.click(screen.getByRole("button", { name: /^Сезонность и периодичность/ }));
    await screen.findByRole("img", { name: "FFT-спектр для Price" });

    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/окно Hann сглаживает границы/i)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Полный пайплайн" })[0]);
    expect(screen.getByText(/dataset\/eda-seasonality/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Минимум полных циклов" }), { target: { value: "4" } });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("min_cycles=4"),
      { credentials: "include" },
    ));
    await screen.findByRole("button", { name: "Пересчитать сезонность" });

    const callsBefore = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-seasonality")).length;
    fireEvent.click(screen.getByRole("button", { name: "Пересчитать сезонность" }));
    await waitFor(() => {
      const callsAfter = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-seasonality")).length;
      expect(callsAfter).toBe(callsBefore + 1);
    });
  });

  it("loads stationarity for the shared target and exposes four overview views", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    await waitFor(() => expect(selector).toHaveValue("Price"));

    fireEvent.click(screen.getByRole("button", { name: /^Верификация стационарности/ }));

    expect(await screen.findByRole("img", { name: "Ряд и скользящее среднее для Price" })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/dataset/eda-stationarity?column=Price&alpha=0.05&rolling_window=12"),
      { credentials: "include" },
    );
    fireEvent.click(screen.getByRole("tab", { name: "Скользящее σ" }));
    expect(screen.getByRole("img", { name: "Скользящее стандартное отклонение для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "p-значения" }));
    expect(screen.getByRole("img", { name: "Сопоставление p-значений тестов стационарности для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Таблица" }));
    expect(screen.getByRole("table", { name: "Результаты тестов стационарности" })).toBeInTheDocument();
    expect(screen.getByText("Сводный вывод", { selector: "div" }).nextElementSibling).toHaveTextContent("Стационарен");
  });

  it("uses stationarity-specific methodology, reacts to alpha and supports refresh", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });
    fireEvent.click(screen.getByRole("button", { name: /^Верификация стационарности/ }));
    await screen.findByRole("img", { name: "Ряд и скользящее среднее для Price" });

    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/ADF и Phillips–Perron проверяют H₀: единичный корень/i)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Полный пайплайн" })[0]);
    expect(screen.getByText(/dataset\/eda-stationarity/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Уровень значимости α" }), { target: { value: "0.01" } });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("alpha=0.01"),
      { credentials: "include" },
    ));
    await screen.findByRole("button", { name: "Пересчитать стационарность" });

    const callsBefore = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-stationarity")).length;
    fireEvent.click(screen.getByRole("button", { name: "Пересчитать стационарность" }));
    await waitFor(() => {
      const callsAfter = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-stationarity")).length;
      expect(callsAfter).toBe(callsBefore + 1);
    });
  });

  it("loads distribution for the shared target and exposes five overview views", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    await waitFor(() => expect(selector).toHaveValue("Price"));

    fireEvent.click(screen.getByRole("button", { name: /^Распределение/ }));

    expect(await screen.findByRole("img", { name: "Гистограмма распределения для Price" })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/dataset/eda-distribution?column=Price&alpha=0.05&bins=20"),
      { credentials: "include" },
    );
    fireEvent.click(screen.getByRole("tab", { name: "Плотность" }));
    expect(screen.getByRole("img", { name: "Сравнение плотностей для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Q–Q" }));
    expect(screen.getByRole("img", { name: "Q–Q график для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "F(x)" }));
    expect(screen.getByRole("img", { name: "Сравнение функций распределения для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Тесты" }));
    expect(screen.getByRole("table", { name: "Тесты нормальности" })).toBeInTheDocument();
    expect(screen.getByText("Q–Q: r", { selector: "div" }).nextElementSibling).toHaveTextContent("0,997");
  });

  it("uses distribution-specific methodology, reacts to alpha and supports refresh", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });
    fireEvent.click(screen.getByRole("button", { name: /^Распределение/ }));
    await screen.findByRole("img", { name: "Гистограмма распределения для Price" });

    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/поправкой Лиллиефорса/i)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Полный пайплайн" })[0]);
    expect(screen.getByText(/dataset\/eda-distribution/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Уровень значимости α" }), { target: { value: "0.01" } });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("alpha=0.01"),
      { credentials: "include" },
    ));
    await screen.findByRole("button", { name: "Пересчитать распределение" });

    const callsBefore = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-distribution")).length;
    fireEvent.click(screen.getByRole("button", { name: "Пересчитать распределение" }));
    await waitFor(() => {
      const callsAfter = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-distribution")).length;
      expect(callsAfter).toBe(callsBefore + 1);
    });
  });

  it("loads structural breaks for the shared target and exposes five overview views", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    await waitFor(() => expect(selector).toHaveValue("Price"));

    fireEvent.click(screen.getByRole("button", { name: /^Структурные сдвиги/ }));

    expect(await screen.findByRole("img", { name: "Режимы и структурные сдвиги для Price" })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/dataset/eda-structural-breaks?column=Price&alpha=0.05&min_segment=20&penalty_multiplier=2"),
      { credentials: "include" },
    );
    fireEvent.click(screen.getByRole("tab", { name: "CUSUM" }));
    expect(screen.getByRole("img", { name: "CUSUM-диагностика для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Чувствительность" }));
    expect(screen.getByRole("img", { name: "Устойчивость точек PELT для Price" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Сегменты" }));
    expect(screen.getByRole("table", { name: "Сегменты ряда" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Кандидаты" }));
    expect(screen.getByRole("table", { name: "Кандидаты структурных сдвигов" })).toBeInTheDocument();
    expect(screen.getByText("Поддержано", { selector: "div" }).nextElementSibling).toHaveTextContent("1");
  });

  it("uses structural-break methodology, reacts to penalty and supports refresh", async () => {
    global.fetch = jest.fn(routeFetch) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });
    fireEvent.click(screen.getByRole("button", { name: /^Структурные сдвиги/ }));
    await screen.findByRole("img", { name: "Режимы и структурные сдвиги для Price" });

    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/Chow после выбора точки/i)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Полный пайплайн" })[0]);
    expect(screen.getByText(/dataset\/eda-structural-breaks/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Штраф PELT" }), { target: { value: "3" } });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("penalty_multiplier=3"),
      { credentials: "include" },
    ));

    const callsBefore = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-structural-breaks")).length;
    fireEvent.click(screen.getByRole("button", { name: "Пересчитать сдвиги" }));
    await waitFor(() => {
      const callsAfter = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/dataset/eda-structural-breaks")).length;
      expect(callsAfter).toBe(callsBefore + 1);
    });
  });

  it("does not mask an unknown structural-breaks 404 as a missing dataset", async () => {
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/dataset/eda-structural-breaks")) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve({ detail: "Маршрут структурных сдвигов не найден" }),
        });
      }
      return routeFetch(input, init);
    }) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });

    fireEvent.click(screen.getByRole("button", { name: /^Структурные сдвиги/ }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((item) => item.textContent?.includes("Маршрут структурных сдвигов не найден"))).toBe(true);
    expect(screen.queryByText("Загрузите датасет, чтобы исследовать структурные сдвиги.")).not.toBeInTheDocument();
  });

  // ── Кнопка «Справка» ──

  it("renders the 'Справка' button in the header", () => {
    render(<TsAnalysisEDA />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    expect(helpButton).toBeInTheDocument();
  });

  it("clicking 'Справка' shows help content in the central text area", () => {
    render(<TsAnalysisEDA />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });

    // До клика — плейсхолдер
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();

    // Клик
    fireEvent.click(helpButton);

    // После клика — появляется справка. Используем getAllByText, т.к.
    // regex /Цели модуля/i матчит ДВА элемента: подзаголовок «Справка — Цели
    // модуля и результаты EDA» и сам контент «Цели модуля "EDA"».
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("clicking 'Справка' toggles content off on second click", () => {
    render(<TsAnalysisEDA />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });

    // Первый клик — показываем
    fireEvent.click(helpButton);
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Второй клик — скрываем (toggle)
    fireEvent.click(helpButton);
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();
  });

  // ── Expandable Description Box ──

  it("description area has a minimum height (collapsed)", () => {
    render(<TsAnalysisEDA />);
    expect(screen.getByText("Описание")).toBeInTheDocument();
  });

  it("expand chevron is not visible when no content is loaded (no overflow)", () => {
    render(<TsAnalysisEDA />);
    // В начальном состоянии (плейсхолдер) нет overflow → нет chevron
    const expandBtn = screen.queryByTestId("desc-expand-btn");
    expect(expandBtn).toBeNull();
  });

  it("collapse chevron is not visible when description is not expanded", () => {
    render(<TsAnalysisEDA />);
    const collapseBtn = screen.queryByTestId("desc-collapse-btn");
    expect(collapseBtn).toBeNull();
  });

  it("collapse chevron appears inside description after expanding", () => {
    render(<TsAnalysisEDA />);
    // Сначала chevron нет
    expect(screen.queryByTestId("desc-collapse-btn")).toBeNull();

    // Кликаем справку для контента
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    fireEvent.click(helpButton);

    // После загрузки контента — компонент стабилен.
    // getAllByText, т.к. regex матчит и подзаголовок, и контент (см. выше).
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });
});
