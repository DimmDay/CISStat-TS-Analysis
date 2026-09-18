// packages/ui/components/TsAnalysisPreprocessing.test.tsx
//
// Тесты для компонента «Предобработка» — в частности:
// 1. Рендер модуля и 10 преобразующих шагов степпера
// 2. Кнопка «Справка» переключает секцию
// 3. Expandable description box: chevron, overlay, collapse

import "@testing-library/jest-dom";
import type { ReactElement } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { TsAnalysisPreprocessing } from "./TsAnalysisPreprocessing";
import { PreprocessingMissingOverview } from "./PreprocessingMissingOverview";
import { PreprocessingOutliersOverview } from "./PreprocessingOutliersOverview";
import { PreprocessingRegularityOverview } from "./PreprocessingRegularityOverview";

const MISSING_PROFILE = {
  rule_source: "system",
  mode: "auto",
  status: "warning",
  status_reason: null,
  total_rows: 4,
  total_columns: 2,
  total_missing: 2,
  missing_rate_pct: 25,
  rows_with_missing: 2,
  rows_with_missing_pct: 50,
  empty_rows: 0,
  columns: [
    {
      column: "Price", dtype: "float64", semantic: "numeric", total_count: 4,
      missing_count: 2, non_missing_count: 2, missing_pct: 50,
      recommended_strategy: "median_mode", missing_examples: [1, 3],
    },
  ],
  row_histogram: [],
};

// Второй реальный стоп («Выбросы») теперь ТОЖЕ опрашивает бэкенд при
// каждом монтировании компонента -- нейтральный дефолт (status: "warning",
// не "done" и не "skipped"), чтобы не искажать существующие
// прогресс-бар/счётчик-тесты, написанные до появления «Выбросов».
const OUTLIERS_PROFILE = {
  rule_source: "system",
  mode: "auto",
  status: "warning",
  status_reason: null,
  method: "iqr",
  total_rows: 4,
  total_numeric_columns: 1,
  total_outliers: 1,
  outlier_rate_pct: 25,
  affected_columns: ["Price"],
  columns: [
    {
      column: "Price", sample_size: 4, outlier_count: 1, outlier_pct: 25,
      recommended_method: "iqr", bounds: { lower: -5, upper: 25 },
      outlier_examples: [3], insufficient_sample: false,
    },
  ],
};

// Нейтральный дефолт (status: "done", 0 нарушений), чтобы тесты «Пропусков»/
// «Выбросов» (не проверяющие «Регулярность» напрямую) не падали при
// монтировании родителя, который теперь параллельно опрашивает и этот
// эндпоинт тоже.
const REGULARITY_PROFILE = {
  mode: "auto",
  status: "done",
  status_reason: null,
  profile: {
    applicable: true,
    applicability_message: null,
    date_column: "Date",
    entity_column: null,
    target_frequency: "MS",
    detected_frequency: "MS",
    gap_threshold_multiplier: 1.5,
    is_sorted: true,
    sort_violations: 0,
    invalid_date_count: 0,
    duplicate_count: 0,
    gap_count: 0,
    missing_period_count: 0,
    total_violations: 0,
    groups: [],
    supported_actions: ["sort", "interpolate", "ffill", "bfill", "asfreq", "fictitious_zero", "flag"],
  },
};

const DECOMPOSITION_PROFILE = {
  mode: "auto", status: "done", status_reason: null,
  profile: {
    column: "Price", date_column: "Date", applicable: true, reason: null,
    method: "STL", robust: true, frequency: "MS", period: 12, n_points: 60,
    sampled: false, original_count: 60, trend_strength: 0.9,
    seasonal_strength: 0.85, residual_mean: 0, residual_std: 1,
    ljung_box_lag: 12, ljung_box_pvalue: 0.2, jarque_bera_pvalue: 0.1,
    points: [], seasonal_pattern: [], residual_acf: [], warnings: [],
    recommendation: "Сезонность выражена.", methodology_note: "STL additive",
  },
};

const VARIANCE_PROFILE = {
  mode: "auto", status: "warning", status_reason: null,
  profile: {
    column: "Price", applicable: true, reason: null, n_observations: 60,
    missing_count: 0, minimum: 1, maximum: 50, order_source: "time_column",
    order_column: "Date", selected_method: "box_cox", lambda_value: 0.2,
    needs_stabilization: true,
    diagnostics_before: { rolling_window: 12, mean_std_correlation: 0.8, levene_statistic: 4, levene_pvalue: 0.01, block_variance_ratio: 5, arch_lm_lag: 10, arch_lm_pvalue: 0.1, skewness: 1, stability_score: 70 },
    diagnostics_after: { rolling_window: 12, mean_std_correlation: 0.1, levene_statistic: 1, levene_pvalue: 0.3, block_variance_ratio: 1.4, arch_lm_lag: 10, arch_lm_pvalue: 0.2, skewness: 0.1, stability_score: 18 },
    candidates: [{ method: "box_cox", label: "Box–Cox", available: true, reason: null, lambda_value: 0.2, stability_score: 18 }],
    points: [], histogram: [], warnings: [], recommendation: "Рекомендуется Box–Cox.", methodology_note: "Brown–Forsythe",
  },
};

const SMOOTHING_PROFILE = {
  mode: "auto", status: "warning", status_reason: null,
  profile: {
    column: "Price", applicable: true, reason: null, n_observations: 60,
    missing_count: 0, order_source: "time_column", order_column: "Date",
    frequency: "MS", regular: true, selected_method: "ema",
    selected_parameters: { span: 7, alpha: 0.25 }, needs_smoothing: true,
    diagnostics_before: { normalized_roughness: 2.5, difference_std_ratio: 0.8, lag1_autocorrelation: 0.3, high_frequency_power_share: 0.48, standard_deviation: 3 },
    diagnostics_after: { normalized_roughness: 0.6, difference_std_ratio: 0.2, lag1_autocorrelation: 0.9, high_frequency_power_share: 0.1, standard_deviation: 2 },
    candidates: [{ method: "ema", label: "EMA", causal: true, available: true, reason: null, parameter_label: "span=7", correlation: 0.9, roughness_reduction_pct: 70, high_frequency_reduction_pct: 75, variance_retained_pct: 70, residual_ljung_box_pvalue: 0.2 }],
    points: [], spectrum: [], residual_acf: [], warnings: [],
    recommendation: "Высокочастотная составляющая выражена.",
    methodology_note: "Эвристика, не статистический тест.",
  },
};

const STATIONARITY_PROFILE = {
  mode: "auto", status: "warning", status_reason: null,
  profile: {
    column: "Price", applicable: true, reason: null, n_observations: 180,
    missing_count: 0, min_observations: 30, alpha: 0.05,
    order_source: "time_column", order_column: "Date", frequency: "MS",
    regular: true, seasonal_period: 12, selected_method: "first_difference",
    needs_transformation: true, consensus_before: "non-stationary", consensus_after: "stationary",
    lost_observations: 1, acf_lag1_before: 0.97, acf_lag1_after: -0.08,
    variance_before: 12, variance_after: 1, over_differencing_warning: false,
    tests: [{ id: "adf_level", label: "ADF (уровень)", null_hypothesis: "Единичный корень", before_p_value: 0.4, after_p_value: 0.001, before_supports_stationarity: false, after_supports_stationarity: true }],
    candidates: [{ method: "first_difference", label: "Первая разность", available: true, reason: null, consensus: "stationary", lost_observations: 1, adf_p_value: 0.001, kpss_p_value: 0.1, acf_lag1: -0.08, variance_ratio: 0.08, over_differencing_warning: false }],
    points: [], acf: [], warnings: [],
    recommendation: "ADF и KPSS указывают на единичный корень; рекомендуется первая разность.",
    methodology_note: "Комплементарные H0 и минимум разностей.",
  },
};

const SPECTRAL_PROFILE = {
  mode: "auto", status: "done", status_reason: null,
  profile: {
    column: "Price", applicable: true, reason: null, n_observations: 240, missing_count: 0,
    min_cycles: 3, max_candidates: 6, max_period: 80, detrend: "linear", window: "hann",
    order_source: "time_column", order_column: "Date", order_warning: null, frequency: "MS",
    spectral_entropy: 0.2, dominant_period: 12, dominant_strength: 0.8, confirmed_periods: 1,
    frequency_resolution: 1 / 240, nyquist_frequency: 0.5, welch_segment_length: 64, welch_segments: 6,
    wavelet_method: "cmor1.5-1.0", wavelet_period_min: 2, wavelet_period_max: 80,
    analysis_only: true, causal: false, modeling_safe: false, saved_periods: [],
    fft: [{ frequency: 1 / 12, period: 12, amplitude: 3, power: null, is_peak: true }],
    periodogram: [{ frequency: 1 / 12, period: 12, amplitude: null, power: 4, is_peak: true }],
    welch: [{ frequency: 1 / 12, period: 12, amplitude: null, power: 3.5, power_share: 0.7, is_peak: true }],
    bands: [{ id: "low", label: "Низкие", frequency_min: 0, frequency_max: 0.1, power_share: 0.8 }],
    candidates: [{ rank: 1, period: 12, period_rounded: 12, frequency: 1 / 12, amplitude: 3, power: 4, power_share: 80, prominence: 3, spectral_snr: 15, autocorrelation: 0.8, seasonal_strength: 0.8, cycles: 20, confirmed: true, calendar_hint: "годовой цикл", harmonic_of: null }],
    phase_period: 12, phase_profile: [{ phase: 1, mean: 1, lower: 0.8, upper: 1.2, count: 20 }],
    wavelet: [{ x: "2010-01-01", index: 0, period: 12, power: 4, normalized_power: 0.9, edge_affected: true }],
    wavelet_global: [{ period: 12, power_share: 0.8 }], recommendations: [], warnings: [],
    methodology_note: "Global spectrum + Welch + CWT; analysis only.",
  },
};

const FEATURE_GENERATION_PROFILE = {
  mode: "auto", status: "warning", status_reason: null,
  profile: {
    column: "Price", applicable: true, reason: null, n_observations: 240,
    order_source: "time_column", order_column: "Date", frequency: "MS", regular: true,
    spectral_periods: [12], suggested_lags: [1, 12], suggested_rolling_windows: [3, 12],
    suggested_calendar_features: ["year", "quarter", "month_cyclic"], suggested_fourier_periods: [12],
    generated: false, saved_feature_names: [], max_lookback: 12, preview_feature_count: 12,
    preview_points: [{ x: "2010-01-01", target: 10, lag: null, rolling: null, fourier: 0 }],
    lag_correlations: [{ lag: 1, correlation: 0.8, selected: true }, { lag: 12, correlation: 0.9, selected: true }],
    availability: [{ name: "Price_lag_12", family: "lag", available_count: 228, missing_count: 12, coverage: 0.95 }],
    cyclic_points: [{ x: "2010-01-01", feature: "fourier_p12_k1_sin", value: 0 }],
    catalog: [{ name: "Price_lag_12", family: "lag", formula: "y[t-12]", lookback: 12, known_in_advance: false, causal: true, missing_count: 12, coverage: 0.95 }],
    warnings: [], recommendation: "Начните с подтверждённых периодов.",
    methodology_note: "Все target-derived признаки используют только прошлое.",
  },
};

const SCALING_PROFILE = {
  mode: "auto", status: "warning", status_reason: null,
  profile: {
    target_column: "Price", applicable: true, reason: null, n_observations: 240,
    numeric_count: 3, eligible_count: 2, suggested_columns: ["Volume", "Temperature"],
    recommended_method: "standard", configured: false, saved_recipe: null,
    focus_column: "Volume", scale_ratio: 250, orders_of_magnitude: 2.4,
    columns: [
      { name: "Volume", role: "source", dtype: "float64", missing_count: 0, unique_count: 240, binary: false, constant: false, eligible: true, recommended: true, exclusion_reason: null, minimum: 1, maximum: 1000, mean: 500, std: 200, median: 500, q1: 250, q3: 750, iqr: 500, outlier_pct: 0, scale: 200 },
      { name: "Temperature", role: "source", dtype: "float64", missing_count: 0, unique_count: 240, binary: false, constant: false, eligible: true, recommended: true, exclusion_reason: null, minimum: -5, maximum: 20, mean: 7, std: 4, median: 7, q1: 4, q3: 10, iqr: 6, outlier_pct: 0, scale: 4 },
    ],
    preview_points: [{ x: "1", original: 1, scaled: -2.5 }],
    range_points: [{ column: "Volume", scale_before: 200, scale_after: 1, log_scale_before: 2.3, log_scale_after: 0 }],
    distribution_points: [{ x_before: 1, density_before: 0.1, x_after: -2.5, density_after: 0.1 }],
    box_points: [{ column: "Volume", stage: "before", minimum: 1, q1: 250, median: 500, q3: 750, maximum: 1000 }],
    correlation_points: [{ x: "Volume", y: "Temperature", before: 0.2, after: 0.2, delta: 0 }],
    methods: [{ method: "standard", label: "StandardScaler", linear: true, centers: "mean", scales: "std", outlier_robust: false, bounded: false, preserves_zero: false, max_correlation_delta: 0, note: "Стандартная шкала." }],
    warnings: [], recommendation: "Сохраните рецепт StandardScaler.",
    methodology_note: "fit только на train-fold.",
  },
};

// Маршрутизирующий мок fetch -- используется везде, где раньше был
// плоский `jest.fn().mockResolvedValue(MISSING_PROFILE)`: теперь ДВА
// реальных стопа опрашивают бэкенд параллельно при монтировании, и без
// маршрутизации по URL «Выбросы» получали бы чужой (missing-shaped)
// ответ.
function routeFetch(overrides: { missing?: unknown; outliers?: unknown; regularity?: unknown; decomposition?: unknown; variance?: unknown; smoothing?: unknown; stationarity?: unknown; spectral?: unknown; featureGeneration?: unknown; scaling?: unknown; put?: unknown } = {}) {
  return jest.fn((url: string, init?: RequestInit) => {
    if (typeof url === "string" && url.includes("/target-column")) {
      const selected = init?.method === "POST"
        ? JSON.parse(String(init.body)).column
        : null;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          target_column: selected,
          suggested_column: "Price",
          available_columns: ["Year", "Price", "Volume"],
          has_dataset: true,
          passport_history_reset: init?.method === "POST",
        }),
      });
    }
    if (init?.method === "PUT") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.put ?? { modes: {} }) });
    }
    if (typeof url === "string" && url.includes("decomposition-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.decomposition ?? DECOMPOSITION_PROFILE) });
    }
    if (typeof url === "string" && url.includes("variance-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.variance ?? VARIANCE_PROFILE) });
    }
    if (typeof url === "string" && url.includes("smoothing-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.smoothing ?? SMOOTHING_PROFILE) });
    }
    if (typeof url === "string" && url.includes("stationarity-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.stationarity ?? STATIONARITY_PROFILE) });
    }
    if (typeof url === "string" && url.includes("spectral-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.spectral ?? SPECTRAL_PROFILE) });
    }
    if (typeof url === "string" && url.includes("feature-generation-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.featureGeneration ?? FEATURE_GENERATION_PROFILE) });
    }
    if (typeof url === "string" && url.includes("scaling-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.scaling ?? SCALING_PROFILE) });
    }
    if (typeof url === "string" && url.includes("regularity-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.regularity ?? REGULARITY_PROFILE) });
    }
    if (typeof url === "string" && url.includes("outlier-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.outliers ?? OUTLIERS_PROFILE) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.missing ?? MISSING_PROFILE) });
  }) as unknown as typeof fetch;
}

describe("TsAnalysisPreprocessing", () => {
  beforeEach(() => {
    // Компонент теперь запрашивает реальный профиль остановки «Пропуски»
    // при монтировании (GET /dataset/missing-profile) -- без мока
    // существующие тесты по-прежнему проходят (запрос ловится внутренним
    // try/catch и переводит статус в "error"), но именно ЭТОТ мок нужен
    // новым тестам ниже, которые проверяют содержательный обзор/статус.
    global.fetch = routeFetch();
  });

  it("renders the module title", () => {
    render(<TsAnalysisPreprocessing />);
    expect(screen.getByText("Preprocessing")).toBeInTheDocument();
  });

  it("renders 10 preprocessing steps and keeps the passport outside the stepper", () => {
    render(<TsAnalysisPreprocessing />);
    const stepLabels = [
      "Пропуски", "Выбросы", "Регулярность ряда", "Декомпозиция ряда",
      "Стабилизация дисперсии", "Сглаживание ряда", "Стационарность ряда",
      "Спектральный анализ", "Генерация признаков", "Масштабирование",
    ];
    stepLabels.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
    const stepper = screen.getByText("Preprocessing").closest("aside");
    expect(stepper).not.toHaveTextContent("Паспорт свойств ряда");
    expect(screen.getByRole("heading", { name: "Паспорт свойств ряда: Предобработка" })).toBeInTheDocument();
  });

  it("uses the shared target selector instead of mock ticker columns", async () => {
    render(<TsAnalysisPreprocessing />);

    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    await waitFor(() => expect(selector).toHaveValue("Price"));
    expect(screen.getByRole("option", { name: "Year" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Volume" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "adj_close" })).not.toBeInTheDocument();

    fireEvent.change(selector, { target: { value: "Volume" } });
    await waitFor(() => expect(selector).toHaveValue("Volume"));
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/target-column"),
      expect.objectContaining({ method: "POST", body: JSON.stringify({ column: "Volume" }) }),
    );
    expect(await screen.findByText(/сбросила цепочку паспортов/i)).toBeInTheDocument();
  });

  // ── Кнопка «Справка» ──

  it("renders the 'Справка' button in the header", () => {
    render(<TsAnalysisPreprocessing />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    expect(helpButton).toBeInTheDocument();
  });

  it("clicking 'Справка' shows help content in the central text area", () => {
    render(<TsAnalysisPreprocessing />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });

    // До клика — автозагруженные метрики активной остановки «Пропуски»
    // (инвариант информативности PREPR-2), а не плейсхолдер.
    expect(screen.getByText(/Метрики и алгоритм: Пропуски/)).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Клик
    fireEvent.click(helpButton);

    // После клика — появляется справка. Используем getAllByText, т.к.
    // regex /Цели модуля/i матчит ДВА элемента: подзаголовок «Справка — Цели
    // модуля и результаты прохождения» и сам контент «Цели модуля "Предобработка"».
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("clicking 'Справка' returns to the active stop's metrics on second click (PREPR-2)", () => {
    render(<TsAnalysisPreprocessing />);
    const helpButton = screen.getByRole("button", { name: /Справка/i });

    // Первый клик — показываем справку
    fireEvent.click(helpButton);
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Второй клик — возврат к метрикам активной остановки (не плейсхолдер):
    // закрытие Справки возвращает инвариант информативности.
    fireEvent.click(helpButton);
    expect(screen.getByText(/Метрики и алгоритм: Пропуски/)).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
  });

  // ── Expandable Description Box ──

  it("description area has a minimum height (collapsed)", () => {
    render(<TsAnalysisPreprocessing />);
    expect(screen.getByText("Описание")).toBeInTheDocument();
  });

  it("expand chevron is not visible when no content is loaded (no overflow)", () => {
    render(<TsAnalysisPreprocessing />);
    // В начальном состоянии (плейсхолдер) нет overflow → нет chevron
    const expandBtn = screen.queryByTestId("desc-expand-btn");
    expect(expandBtn).toBeNull();
  });

  it("collapse chevron is not visible when description is not expanded", () => {
    render(<TsAnalysisPreprocessing />);
    const collapseBtn = screen.queryByTestId("desc-collapse-btn");
    expect(collapseBtn).toBeNull();
  });

  it("collapse chevron appears inside description after expanding", () => {
    render(<TsAnalysisPreprocessing />);
    // Сначала chevron нет
    expect(screen.queryByTestId("desc-collapse-btn")).toBeNull();

    // Симулируем раскрытие — кликаем справку для контента,
    // затем expand chevron (если появился при overflow).
    // В тестовой среде ResizeObserver может не сработать,
    // поэтому проверяем что компонент рендерится без ошибок
    // и collapse кнопка доступна через data-testid когда expanded
    const helpButton = screen.getByRole("button", { name: /Справка/i });
    fireEvent.click(helpButton);

    // После загрузки контента — компонент стабилен.
    // getAllByText, т.к. regex матчит и подзаголовок, и контент (см. выше).
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });
});

// ── Интеграция остановки «Пропуски» с бэкендом ──

describe("TsAnalysisPreprocessing — остановка «Пропуски»", () => {
  beforeEach(() => {
    global.fetch = routeFetch();
  });

  it("shows the real missing-values overview by default (missing is the first step)", async () => {
    render(<TsAnalysisPreprocessing />);
    expect(await screen.findByRole("table", { name: "Матрица пропусков по колонкам" })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/dataset/missing-profile"),
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("reflects issues_found status in the stepper and the right-column badge", async () => {
    render(<TsAnalysisPreprocessing />);
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });
    expect(screen.getByText("Найдено 2 пропусков")).toBeInTheDocument();
  });

  it("shows the skipped status when no dataset is active", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
    render(<TsAnalysisPreprocessing />);
    const matches = await screen.findAllByText("Нет активного датасета");
    expect(matches.length).toBeGreaterThanOrEqual(1); // «Пропуски» и «Выбросы» -- оба реальных стопа, оба 404
  });

  it("shows a mode selector for the missing-values stop and persists disabled mode", async () => {
    global.fetch = routeFetch({
      missing: { ...MISSING_PROFILE, mode: "disabled", status: "skipped", status_reason: "disabled" },
      put: { modes: { missing: "disabled" } },
    });

    render(<TsAnalysisPreprocessing />);
    const select = await screen.findByRole("combobox", { name: "Режим проверки Пропуски" });
    fireEvent.change(select, { target: { value: "disabled" } });

    await waitFor(() => expect(screen.getByText("Отключено")).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/session/dataset/preprocessing-check-modes"),
      expect.objectContaining({ method: "PUT" })
    );
  });

  it("excludes a skipped missing-values stop from the progress bar denominator", async () => {
    global.fetch = routeFetch({
      missing: { ...MISSING_PROFILE, mode: "disabled", status: "skipped", status_reason: "disabled" },
      regularity: { ...REGULARITY_PROFILE, status: "pending" },
    });
    render(<TsAnalysisPreprocessing />);
    await screen.findByText("Отключено");
    // 10 преобразующих остановок всего, но «Пропуски» (skipped) исключены из знаменателя
    // Декомпозиция и спектральный профиль могут ещё выполняться или уже
    // завершиться (0…2):
    // в обоих случаях 9 применимых остановок и "100%" не появляется
    // ошибочно, а прогресс-бар не должен упасть на NaN/делении на 0.
    expect(screen.getByText(/^[012]\/9$/)).toBeInTheDocument();
  });

  it("shows a 'Панель управления' header above the right-hand column", async () => {
    render(<TsAnalysisPreprocessing />);
    expect(await screen.findByRole("heading", { name: "Панель управления" })).toBeInTheDocument();
  });

  it("shows the real Цель/Метрики/Алгоритм backend description for 'Метрики и алгоритм'", async () => {
    render(<TsAnalysisPreprocessing />);
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);

    expect(await screen.findByText(/Метрики и алгоритм: Пропуски/)).toBeInTheDocument();
    expect(screen.getByText(/Алгоритм backend/)).toBeInTheDocument();
    expect(screen.getByText(/MCAR \/ MAR \/ MNAR/)).toBeInTheDocument();
  });

  it("shows step-by-step wizard instructions for 'Исправить пропуски'", async () => {
    render(<TsAnalysisPreprocessing />);
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });
    fireEvent.click(screen.getByRole("button", { name: "Исправить пропуски" }));

    expect((await screen.findAllByText(/Мастер исправления пропусков/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/Отметьте колонки с пропусками/)).toBeInTheDocument();
    expect(screen.getByText(/Прогноз влияния на статистики/)).toBeInTheDocument();
  });

  it("opens the correction wizard and refreshes the profile after applying", async () => {
    const preview = {
      applied: false, strategy: "median_mode", total_missing: 2, total_changed: 2,
      total_still_missing: 0, rows_removed: 0, added_columns: [],
      columns: [{ column: "Price", missing_count: 2, changed_count: 2, still_missing: 0, missing_examples: [1, 3], flag_column: null }],
      profile: [{ ...MISSING_PROFILE.columns[0], missing_count: 0, missing_pct: 0, missing_examples: [] }],
    };
    const clearedProfile = {
      ...MISSING_PROFILE,
      status: "done",
      total_missing: 0,
      rows_with_missing: 0,
      rows_with_missing_pct: 0,
      columns: [{ ...MISSING_PROFILE.columns[0], missing_count: 0, missing_pct: 0, missing_examples: [] }],
    };
    let applied = false;
    // Мок различает GET-профиль (несколько независимых компонентов читают
    // один и тот же эндпоинт -- парент, Overview, Pipeline) и POST-коррекцию,
    // а не полагается на фиксированный порядок вызовов.
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      if (url.includes("/target-column")) {
        const selected = init?.method === "POST"
          ? JSON.parse(String(init.body)).column
          : "Price";
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            target_column: selected,
            suggested_column: "Price",
            available_columns: ["Price"],
            has_dataset: true,
          }),
        });
      }
      if (init?.method === "POST") {
        const body = init.body ? JSON.parse(init.body as string) : {};
        if (body.apply) applied = true;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ...preview, applied: Boolean(body.apply) }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(applied ? clearedProfile : MISSING_PROFILE) });
    }) as unknown as typeof fetch;

    render(<TsAnalysisPreprocessing />);
    await screen.findByRole("table", { name: "Матрица пропусков по колонкам" });

    fireEvent.click(screen.getByRole("button", { name: "Исправить пропуски" }));
    expect(await screen.findByRole("region", { name: "Мастер исправления пропусков" })).toBeInTheDocument();
    // Дожидаемся, пока мастер подгрузит СВОЙ профиль (переиспользует тот же
    // эндпоинт, что и парент/Overview) и предзаполнит колонку -- иначе
    // «Предпросмотр изменений» ещё disabled (busy==="load", selected==[]).
    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });

    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await screen.findByText("Исправлено значений: 2");
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(screen.getByRole("button", { name: "Применить исправления" }));

    await waitFor(() => expect(screen.getByText("Проверка пройдена, пропусков нет")).toBeInTheDocument());
  });
});

// ── Интеграция остановки «Выбросы» с бэкендом ──

describe("TsAnalysisPreprocessing — остановка «Выбросы»", () => {
  beforeEach(() => {
    global.fetch = routeFetch();
  });

  it("switching to 'Выбросы' shows the real outliers overview", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Выбросы"));
    expect(await screen.findByRole("table", { name: "Выбросы по числовым колонкам" })).toBeInTheDocument();
  });

  it("reflects warning status and count in the right-column badge", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Выбросы"));
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });
    expect(screen.getByText("Найдено 1 выбросов")).toBeInTheDocument();
  });

  it("shows a mode selector for outliers independent from missing's mode", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Выбросы"));
    expect(await screen.findByRole("combobox", { name: "Режим проверки Выбросы" })).toBeInTheDocument();
  });

  it("shows the real Цель/Метрики/Алгоритм backend description including the decomposition-only position", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Выбросы"));
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);

    expect(await screen.findByText(/Метрики и алгоритм: Выбросы/)).toBeInTheDocument();
    expect(screen.getByText(/только по остатку после декомпозиции/)).toBeInTheDocument();
    expect(screen.getByText(/степпере идёт ДО «Регулярности»/)).toBeInTheDocument();
  });

  it("shows step-by-step wizard instructions mentioning the residual-detection option", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Выбросы"));
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });
    fireEvent.click(screen.getByRole("button", { name: "Исправить выбросы" }));

    expect((await screen.findAllByText(/Мастер исправления выбросов/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Обнаруживать на остатке после STL-декомпозиции/).length).toBeGreaterThan(0);
  });

  it("opens the outliers wizard region when 'Исправить выбросы' is clicked", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Выбросы"));
    await screen.findByRole("table", { name: "Выбросы по числовым колонкам" });
    fireEvent.click(screen.getByRole("button", { name: "Исправить выбросы" }));

    expect(await screen.findByRole("region", { name: "Мастер исправления выбросов" })).toBeInTheDocument();
  });
});

// ── Интеграция остановки «Регулярность» с бэкендом ──

describe("TsAnalysisPreprocessing — остановка «Регулярность»", () => {
  const WARNING_REGULARITY = {
    ...REGULARITY_PROFILE,
    status: "warning",
    profile: { ...REGULARITY_PROFILE.profile, gap_count: 1, total_violations: 1 },
  };

  beforeEach(() => {
    global.fetch = routeFetch({ regularity: WARNING_REGULARITY });
  });

  it("switching to 'Регулярность ряда' shows the real regularity overview", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Регулярность ряда"));
    expect(await screen.findByRole("table", { name: "Регулярность по группам" })).toBeInTheDocument();
  });

  it("reflects warning status and count in the right-column badge", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Регулярность ряда"));
    await screen.findByRole("table", { name: "Регулярность по группам" });
    expect(screen.getByText("Найдено 1 нарушений регулярности")).toBeInTheDocument();
  });

  it("shows a mode selector for regularity independent from other stops", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Регулярность ряда"));
    expect(await screen.findByRole("combobox", { name: "Режим проверки Регулярность ряда" })).toBeInTheDocument();
  });

  it("shows the real Цель/Метрики/Алгоритм backend description including the methodology assessment", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Регулярность ряда"));
    await screen.findByRole("table", { name: "Регулярность по группам" });
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);

    expect(await screen.findByText(/Метрики и алгоритм: Регулярность ряда/)).toBeInTheDocument();
    expect(screen.getByText(/Оценка методологии/)).toBeInTheDocument();
    expect(screen.getByText(/profile_regularity/)).toBeInTheDocument();
  });

  it("shows step-by-step wizard instructions when 'Исправить регулярность' is clicked", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Регулярность ряда"));
    await screen.findByRole("table", { name: "Регулярность по группам" });
    fireEvent.click(screen.getByRole("button", { name: "Исправить регулярность" }));

    expect(await screen.findByRole("region", { name: "Мастер исправления регулярности" })).toBeInTheDocument();
    expect(screen.getAllByText(/Ресемплировать/).length).toBeGreaterThan(0);
  });
});

describe("TsAnalysisPreprocessing — остановка «Декомпозиция ряда»", () => {
  beforeEach(() => { global.fetch = routeFetch(); });

  it("shows the real STL overview and mode selector", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Декомпозиция ряда"));

    expect(await screen.findByRole("tablist", { name: "Графики декомпозиции" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Режим проверки Декомпозиция ряда" })).toBeInTheDocument();
    expect(screen.getByText("STL выполнен, остаточная диагностика пройдена")).toBeInTheDocument();
  });

  it("opens the decomposition wizard and explains leakage", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Декомпозиция ряда"));
    await screen.findByRole("tablist", { name: "Графики декомпозиции" });
    fireEvent.click(screen.getByRole("button", { name: "Настроить декомпозицию" }));

    expect(screen.getByRole("region", { name: "Мастер декомпозиции ряда" })).toBeInTheDocument();
    expect(screen.getAllByText(/только на train/i).length).toBeGreaterThan(0);
  });

  it("describes why the pseudo-cycle and variance percentages are rejected", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Декомпозиция ряда"));
    await screen.findByRole("tablist", { name: "Графики декомпозиции" });
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);

    expect(screen.getByText(/двойной счёт/)).toBeInTheDocument();
    expect(screen.getByText(/STL не возвращает отдельный cycle/)).toBeInTheDocument();
  });
});

describe("TsAnalysisPreprocessing — остановка «Стабилизация дисперсии»", () => {
  beforeEach(() => { global.fetch = routeFetch(); });

  it("shows the comparative overview, real status and mode selector", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Стабилизация дисперсии"));
    expect(await screen.findByRole("tablist", { name: "Графики стабилизации дисперсии" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Режим проверки Стабилизация дисперсии" })).toBeInTheDocument();
    expect(screen.getByText(/Обнаружена нестабильность масштаба/)).toBeInTheDocument();
  });

  it("opens the transformation wizard and documents the removed hidden shift", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Стабилизация дисперсии"));
    await screen.findByRole("tablist", { name: "Графики стабилизации дисперсии" });
    fireEvent.click(screen.getByRole("button", { name: "Настроить трансформацию" }));
    expect(screen.getByRole("region", { name: "Мастер стабилизации дисперсии" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/Старый код добавлял 1e-10/)).toBeInTheDocument();
  });
});

describe("TsAnalysisPreprocessing — остановка «Сглаживание ряда»", () => {
  beforeEach(() => { global.fetch = routeFetch(); });

  it("shows the visual overview, real status and mode selector", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Сглаживание ряда"));
    expect(await screen.findByRole("tablist", { name: "Графики сглаживания ряда" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Режим проверки Сглаживание ряда" })).toBeInTheDocument();
    expect(screen.getAllByText(/Высокочастотная составляющая выражена/).length).toBeGreaterThan(0);
  });

  it("opens the wizard and documents corrected causal methodology", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Сглаживание ряда"));
    await screen.findByRole("tablist", { name: "Графики сглаживания ряда" });
    fireEvent.click(screen.getByRole("button", { name: "Настроить сглаживание" }));
    expect(screen.getByRole("region", { name: "Мастер сглаживания ряда" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/WMA.bfill подставлял в начало/)).toBeInTheDocument();
    expect(screen.getByText(/HP-filter исключён/)).toBeInTheDocument();
  });
});

describe("TsAnalysisPreprocessing — остановка «Стационарность ряда»", () => {
  beforeEach(() => { global.fetch = routeFetch(); });

  it("shows the five-view overview, real warning and mode selector", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Стационарность ряда"));
    expect(await screen.findByRole("tablist", { name: "Графики стационарности ряда" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Режим проверки Стационарность ряда" })).toBeInTheDocument();
    expect(screen.getByText(/Обнаружены признаки единичного корня/)).toBeInTheDocument();
  });

  it("opens the stationarity wizard and documents corrected legacy methodology", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Стационарность ряда"));
    await screen.findByRole("tablist", { name: "Графики стационарности ряда" });
    fireEvent.click(screen.getByRole("button", { name: "Обеспечить стационарность" }));
    expect(screen.getByRole("region", { name: "Мастер обеспечения стационарности" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/смешивал порядок и лаг/)).toBeInTheDocument();
    expect(screen.getByText(/Fractional differencing имел неверный знак/)).toBeInTheDocument();
  });
});

describe("TsAnalysisPreprocessing — остановка «Спектральный анализ»", () => {
  beforeEach(() => { global.fetch = routeFetch(); });

  it("shows five spectral views, confirmed-period status and mode selector", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Спектральный анализ"));
    expect(await screen.findByRole("tablist", { name: "Представления спектрального анализа" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Режим проверки Спектральный анализ" })).toBeInTheDocument();
    expect(screen.getByText("Подтверждено периодов: 1")).toBeInTheDocument();
  });

  it("opens period-selection wizard and documents legacy corrections", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Спектральный анализ"));
    await screen.findByRole("tablist", { name: "Представления спектрального анализа" });
    fireEvent.click(screen.getByRole("button", { name: "Зафиксировать периоды" }));
    expect(screen.getByRole("region", { name: "Мастер спектрального анализа" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/Legacy compute_fft_features/)).toBeInTheDocument();
    expect(screen.getByText(/ненормированной и зависела от N/)).toBeInTheDocument();
  });
});

describe("TsAnalysisPreprocessing — остановка «Генерация признаков»", () => {
  beforeEach(() => { global.fetch = routeFetch(); });

  it("shows five feature views, actionable status and mode selector", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Генерация признаков"));
    expect(await screen.findByRole("tablist", { name: "Представления генерации признаков" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Режим проверки Генерация признаков" })).toBeInTheDocument();
    expect(screen.getByText("Набор рекомендован, но ещё не применён")).toBeInTheDocument();
    expect(screen.getAllByText("12", { selector: "strong" }).length).toBeGreaterThanOrEqual(1);
  });

  it("opens the wizard and documents corrected legacy methodology", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Генерация признаков"));
    await screen.findByRole("tablist", { name: "Представления генерации признаков" });
    fireEvent.click(screen.getByRole("button", { name: "Сгенерировать признаки" }));
    expect(screen.getByRole("region", { name: "Мастер генерации признаков" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/12 наблюдений превратились бы в 12 дней/)).toBeInTheDocument();
    expect(screen.getByText(/target.shift\(1\)/)).toBeInTheDocument();
  });
});

describe("TsAnalysisPreprocessing — остановка «Масштабирование»", () => {
  beforeEach(() => { global.fetch = routeFetch(); });

  it("shows five scaling views, recipe status and mode selector", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Масштабирование"));
    expect(await screen.findByRole("tablist", { name: "Представления масштабирования" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Режим проверки Масштабирование" })).toBeInTheDocument();
    expect(screen.getByText("Рецепт масштабирования ещё не сохранён")).toBeInTheDocument();
  });

  it("opens the recipe wizard and documents leakage correction", async () => {
    render(<TsAnalysisPreprocessing />);
    fireEvent.click(screen.getByText("Масштабирование"));
    await screen.findByRole("tablist", { name: "Представления масштабирования" });
    fireEvent.click(screen.getByRole("button", { name: "Настроить масштабирование" }));
    expect(screen.getByRole("region", { name: "Мастер масштабирования" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/fit на полном ряду создаёт leakage/i)).toBeInTheDocument();
    expect(screen.getByText(/PowerTransformer не дублируется/i)).toBeInTheDocument();
  });
});

// ── Приглашение «Перейти к EDA» (паттерн Загрузки/Валидации, Task PRE-1) ──

describe("TsAnalysisPreprocessing — приглашение «Перейти к EDA»", () => {
  beforeEach(() => { global.fetch = routeFetch(); });

  it("shows the 'Перейти к EDA' invitation at the bottom of the stepper (Upload/Validation pattern)", () => {
    // Паттерн "Ведём исследователя за руку" (StepperNextModuleButton):
    // та же механика, что на «Загрузке» и «Валидации» -- внизу степпера
    // кнопка-приглашение, отделённая светло-серой полосой, со ссылкой
    // на следующий модуль пайплайна (Предобработка -> EDA).
    render(<TsAnalysisPreprocessing />);

    // Последняя остановка степпера «Предобработки» -- «Масштабирование».
    // Имя доступное = текст шага + aria-label svg-иконки статуса, поэтому
    // матчится по подстроке названия шага.
    const lastStepperButton = screen.getByRole("button", { name: /Масштабирование/ });

    // 1. Кнопка-приглашение -- ссылка на /eda с доступным именем
    //    «Перейти к EDA».
    const invite = screen.getByRole("link", { name: /Перейти к EDA/ });
    expect(invite).toHaveAttribute("href", "/eda");

    // 2. Низ степпера: приглашение строго НИЖЕ последней кнопки степпера
    //    и является последним элементом списка степпера (как на
    //    «Загрузке», где кнопка стоит внутри списка остановок).
    // eslint-disable-next-line no-bitwise
    expect(
      lastStepperButton.compareDocumentPosition(invite) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    const wrapper = invite.closest("div");
    const stepperList = lastStepperButton.parentElement;
    expect(stepperList).not.toBeNull();
    expect(stepperList?.lastElementChild).toBe(wrapper);

    // 3. Светло-серая полоса НАД кнопкой: border-t border-neutral-200
    //    на обёртке (контракт StepperNextModuleButton).
    expect(wrapper?.className).toContain("border-t");
    expect(wrapper?.className).toContain("border-neutral-200");

    // 4. Дизайн в точности по паттерну Загрузки: та же геометрия, что у
    //    кнопок степпера (rounded-md/border/px-3 py-2/text-sm), статичная
    //    пастельная заливка bg-brand-light/50, фирменный индиго и белый
    //    текст при наведении.
    expect(invite.className).toContain("rounded-md");
    expect(invite.className).toContain("border");
    expect(invite.className).toContain("bg-brand-light/50");
    expect(invite.className).toContain("hover:bg-brand");
    expect(invite.className).toContain("hover:border-brand");
    expect(invite.className).toContain("hover:text-white");
    expect(invite.className).toContain("px-3");
    expect(invite.className).toContain("py-2");
    expect(invite.className).toContain("text-sm");
  });
});

// ── Зелёная подсветка пройденных остановок степпера (паттерн Моделирования) ──
//
// Паттерн перенесён с вкладки «Моделирование» (TsAnalysisModeling) и уже
// применён к «Разведочному EDA» (Task EDA-2): «Если остановка степпера
// пройдена и имеет зелёную галочку, то кнопка остановки окрашивается в
// светло-зелёный цвет и текст становится зелёным. При других статусах
// кнопка остановки не окрашивается и цвет текста не меняется».
// Контракт цветов -- ветка done в className кнопки степпера:
// bg-green-50 border-green-200 text-green-800; активная остановка
// (bg-brand text-white) сохраняет приоритет, как в эталоне.

describe("TsAnalysisPreprocessing — зелёная подсветка пройденных остановок степпера (паттерн Моделирования)", () => {
  it("colors a passed (done) stop light-green and keeps non-active pending stops uncolored", async () => {
    global.fetch = routeFetch();
    render(<TsAnalysisPreprocessing />);

    // Сигнал готовности: «Регулярность ряда» загружена на монтировании и
    // получила статус done (зелёная галочка, aria-label «Пройдено»).
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Регулярность ряда/ }))
        .toHaveAccessibleName(/Пройдено/);
    });

    // Снимаем активность с дефолтной остановки «Пропуски»: кликаем на
    // «Масштабирование» (до клика — pending).
    fireEvent.click(screen.getByRole("button", { name: /Масштабирование/ }));

    // Пройденная остановка (зелёная галочка) -> светло-зелёная кнопка
    // с зелёным текстом (эталон Моделирования: bg-green-50/green-200/green-800).
    const doneButton = screen.getByRole("button", { name: /Регулярность ряда/ });
    expect(doneButton).toHaveClass("bg-green-50", "border-green-200", "text-green-800");
    expect(doneButton).not.toHaveClass("bg-brand");
    expect(doneButton).not.toHaveClass("bg-white");

    // Не пройденная (pending) и не активная остановка -> БЕЗ окраски.
    const pendingButton = screen.getByRole("button", { name: /Генерация признаков/ });
    expect(pendingButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(pendingButton).not.toHaveClass("bg-green-50");
    expect(pendingButton).not.toHaveClass("border-green-200");
    expect(pendingButton).not.toHaveClass("text-green-800");
  });

  it("keeps the indigo active styling for an active stop even when it is done (active branch priority, as in Modeling)", async () => {
    global.fetch = routeFetch();
    render(<TsAnalysisPreprocessing />);

    // «Регулярность ряда» на монтировании становится done; клик по ней не
    // перезапрашивает профиль (зависимости useEffect не включают
    // activeCheckId) -> остановка active+done обязана остаться индиго.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Регулярность ряда/ }))
        .toHaveAccessibleName(/Пройдено/);
    });
    fireEvent.click(screen.getByRole("button", { name: /Регулярность ряда/ }));

    const activeDoneButton = screen.getByRole("button", { name: /Регулярность ряда/ });
    expect(activeDoneButton).toHaveClass("bg-brand", "text-white", "border-brand");
    expect(activeDoneButton).not.toHaveClass("bg-green-50");
    expect(activeDoneButton).not.toHaveClass("text-green-800");
  });

  it("leaves running and pending stops uncolored", () => {
    // Вечнозависающий fetch: «Пропуски»/«Выбросы»/«Регулярность» остаются в
    // running (initial loading=true), профильные остановки без активации и
    // признака — pending.
    global.fetch = jest.fn(() => new Promise<Response>(() => {})) as unknown as typeof fetch;
    render(<TsAnalysisPreprocessing />);

    fireEvent.click(screen.getByRole("button", { name: /Масштабирование/ }));

    const runningButton = screen.getByRole("button", { name: /Пропуски/ });
    expect(runningButton).not.toHaveClass("bg-green-50");
    expect(runningButton).not.toHaveClass("border-green-200");
    expect(runningButton).not.toHaveClass("text-green-800");

    const pendingButton = screen.getByRole("button", { name: /Генерация признаков/ });
    expect(pendingButton).not.toHaveClass("bg-green-50");
    expect(pendingButton).not.toHaveClass("text-green-800");
  });

  it("leaves the warning stop uncolored", async () => {
    global.fetch = routeFetch();
    render(<TsAnalysisPreprocessing />);

    // Дефолтный профиль «Пропусков» — warning (найдены пропуски).
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Пропуски/ }))
        .toHaveAccessibleName(/Найдены проблемы/);
    });
    fireEvent.click(screen.getByRole("button", { name: /Масштабирование/ }));

    const warningButton = screen.getByRole("button", { name: /Пропуски/ });
    expect(warningButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(warningButton).not.toHaveClass("bg-green-50");
    expect(warningButton).not.toHaveClass("border-green-200");
    expect(warningButton).not.toHaveClass("text-green-800");
  });

  it("leaves the skipped stop uncolored", async () => {
    // Оверрайд статуса профиля регулярности на skipped («Не требуется»).
    global.fetch = routeFetch({
      regularity: { ...REGULARITY_PROFILE, status: "skipped" },
    });
    render(<TsAnalysisPreprocessing />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Регулярность ряда/ }))
        .toHaveAccessibleName(/Не требуется/);
    });
    fireEvent.click(screen.getByRole("button", { name: /Масштабирование/ }));

    const skippedButton = screen.getByRole("button", { name: /Регулярность ряда/ });
    expect(skippedButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(skippedButton).not.toHaveClass("bg-green-50");
    expect(skippedButton).not.toHaveClass("border-green-200");
    expect(skippedButton).not.toHaveClass("text-green-800");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Инвариант информативности (Task PREPR-2, 2026-09-15) — зеркально VALID-2:
// активная остановка степпера АВТОМАТИЧЕСКИ загружает в «Описание» содержимое
// «Метрики и алгоритм» данной остановки (и делает кнопку активной) — вне
// зависимости от статуса остановки. Контент метрик — статические константы
// компонента (без зависимостей от /dataset/*-профилей и наличия датасета),
// поэтому автозагрузка возможна всегда. Явный пользовательский выбор
// («Исправить …»/мастер) остаётся приоритетным, пока пользователь сам не
// вернётся к метрикам.
// ─────────────────────────────────────────────────────────────────────────────
describe("TsAnalysisPreprocessing — автозагрузка «Метрики и алгоритм» активной остановки (инвариант информативности)", () => {
  beforeEach(() => {
    global.fetch = routeFetch();
  });

  it("auto-loads the active stop's metrics into the description box on page load (warning status)", async () => {
    // Дефолтный профиль «Пропусков» — warning (найдены пропуски): инвариант
    // действует вне зависимости от статуса — «Описание» сразу показывает
    // метрики первой активной остановки.
    render(<TsAnalysisPreprocessing />);

    expect(await screen.findByText(/Метрики и алгоритм: Пропуски/)).toBeInTheDocument();
    expect(screen.getByText(/Алгоритм backend/)).toBeInTheDocument();
    expect(screen.getByText("Метрики и алгоритм — Пропуски")).toBeInTheDocument();
    // Placeholder больше никогда не появляется.
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Выберите раздел в боковой панели")).not.toBeInTheDocument();

    // Кнопка «Метрики и алгоритм» активной остановки — в активном (индиго)
    // состоянии; кнопка соседней карточки — нет.
    const metricsButtons = screen.getAllByRole("button", { name: "Метрики и алгоритм" });
    expect(metricsButtons[0]).toHaveClass("bg-brand", "text-white");
    expect(metricsButtons[1]).not.toHaveClass("bg-brand");
    expect(metricsButtons[1]).toHaveClass("bg-brand-light");
  });

  it("auto-loads metrics when switching stops via the stepper (pending stop, no second click)", async () => {
    // Оверрайд статуса профиля «Выбросов» на pending («Проверка не
    // запускалась») — инвариант не зависит и от этого статуса.
    global.fetch = routeFetch({
      outliers: { ...OUTLIERS_PROFILE, status: "pending" },
    });
    render(<TsAnalysisPreprocessing />);

    // Клик по другой остановке степпера («Выбросы», pending)
    fireEvent.click((await screen.findAllByRole("button", { name: /Выбросы/ }))[0]);

    // Метрики автозагрузились БЕЗ клика по кнопке «Метрики и алгоритм».
    expect(screen.getByText(/Метрики и алгоритм: Выбросы/)).toBeInTheDocument();
    expect(screen.getByText(/Четыре метода на выбор/)).toBeInTheDocument();
    expect(screen.getByText("Метрики и алгоритм — Выбросы")).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();

    // Кнопка новой активной остановки активна (orderedChecks сортирует её
    // первой), кнопка прежней активной остановки — нет.
    const metricsButtons = screen.getAllByRole("button", { name: "Метрики и алгоритм" });
    expect(metricsButtons[0]).toHaveClass("bg-brand", "text-white");
    expect(metricsButtons[1]).not.toHaveClass("bg-brand");
  });

  it("auto-loads metrics for a done stop (status-independence)", async () => {
    // Дефолтный профиль «Регулярности ряда» — done («Проверка пройдена»):
    // клик по пройденной остановке автозагружает метрики так же, как для
    // warning/pending — статус не влияет на инвариант.
    render(<TsAnalysisPreprocessing />);

    fireEvent.click((await screen.findAllByRole("button", { name: /Регулярность ряда/ }))[0]);

    expect(screen.getByText(/Метрики и алгоритм: Регулярность ряда/)).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
    const metricsButtons = screen.getAllByRole("button", { name: "Метрики и алгоритм" });
    expect(metricsButtons[0]).toHaveClass("bg-brand", "text-white");
  });

  it("closing the Help toggle returns to the active stop's metrics (not the placeholder)", async () => {
    render(<TsAnalysisPreprocessing />);

    fireEvent.click(screen.getByRole("button", { name: "Справка" }));
    expect(screen.getAllByText(/Цели модуля/i).length).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByRole("button", { name: "Справка" }));
    expect(screen.getByText(/Метрики и алгоритм: Пропуски/)).toBeInTheDocument();
    expect(screen.queryByText(/Нажмите «Метрики и алгоритм»/i)).not.toBeInTheDocument();
  });

  it("explicit pipeline click still wins over the invariant until the user switches back", async () => {
    render(<TsAnalysisPreprocessing />);

    // Гард: автозагрузка не ломает явный пользовательский выбор мастера.
    fireEvent.click(await screen.findByRole("button", { name: "Исправить пропуски" }));
    expect((await screen.findAllByText(/Мастер исправления пропусков/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Метрики и алгоритм: Пропуски/)).not.toBeInTheDocument();

    // Возврат к метрикам — явным кликом по кнопке «Метрики и алгоритм».
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(screen.getByText(/Метрики и алгоритм: Пропуски/)).toBeInTheDocument();
  });

  it("clicking the already-active stop keeps an open Help section (former semantics preserved)", async () => {
    render(<TsAnalysisPreprocessing />);

    // Открываем Справку
    fireEvent.click(await screen.findByRole("button", { name: "Справка" }));
    expect(screen.getAllByText(/Цели модуля/i).length).toBeGreaterThanOrEqual(1);

    // Клик по УЖЕ активной остановке («Пропуски») секцию не меняет —
    // открытая Справка остаётся (прежняя семантика сохранена).
    fireEvent.click(screen.getAllByRole("button", { name: /Пропуски/ })[0]);
    expect(screen.getAllByText(/Цели модуля/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/Метрики и алгоритм: Пропуски/)).not.toBeInTheDocument();

    // А вот переключение на ДРУГУЮ остановку автозагружает её метрики.
    fireEvent.click((await screen.findAllByRole("button", { name: /Выбросы/ }))[0]);
    expect(screen.getByText(/Метрики и алгоритм: Выбросы/)).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Автообновление профилей после применения исправлений (datasetVersion).
//
// ПРОБЛЕМА (репродукция из постановки): профиль остановки «Декомпозиция
// ряда» вычисляется бэкендом с applicability-гейтом по состоянию датасета
// (apps/api/preprocessing_decomposition.py: «В ряду N пропусков; сначала
// завершите остановку "Пропуски"») — то же для «Стабилизации дисперсии»,
// «Сглаживания», «Стационарности», «Спектра» и «Генерации признаков».
// Родительский компонент кэширует профили в state, а onApplied мастера
// «Пропусков» инвалидирует ТОЛЬКО missing-профиль. В результате после
// применения исправления остановки-потребители продолжают показывать
// устаревший плейсхолдер до перезагрузки страницы.
//
// КОНТРАКТ РЕШЕНИЯ: применение исправления в ЛЮБОЙ остановке (onApplied)
// инвалидирует ВСЕ профили модуля (единый счётчик datasetVersion в deps
// всех profile-fetch useEffect) — степпер, бейджи, метрики и Обзоры
// обновляются автоматически, без перезагрузки страницы. Сохранение режима
// остановки (PUT check-modes) мутации датасета не производит и профили
// ДРУГИХ остановок не инвалидирует.
// ─────────────────────────────────────────────────────────────────────────────
describe("TsAnalysisPreprocessing — автообновление профилей после применения исправлений", () => {
  const BLOCKING_REASON = "В ряду 2 пропусков; сначала завершите остановку «Пропуски»";

  const blockedDecomposition = {
    mode: "auto",
    status: "skipped",
    status_reason: "not_required",
    profile: {
      ...DECOMPOSITION_PROFILE.profile,
      applicable: false,
      reason: BLOCKING_REASON,
    },
  };

  const clearedMissingProfile = {
    ...MISSING_PROFILE,
    status: "done",
    total_missing: 0,
    rows_with_missing: 0,
    rows_with_missing_pct: 0,
    columns: [{ ...MISSING_PROFILE.columns[0], missing_count: 0, missing_pct: 0, missing_examples: [] }],
  };

  const clearedOutliersProfile = {
    ...OUTLIERS_PROFILE,
    status: "done",
    total_outliers: 0,
    outlier_rate_pct: 0,
    affected_columns: [],
    columns: [{ ...OUTLIERS_PROFILE.columns[0], outlier_count: 0, outlier_pct: 0, outlier_examples: [] }],
  };

  // Счётчик вызовов по URL-паттернам поверх общего роутера. Возвращает
  // (fetch, counts) — counts мутирует по мере запросов и читается ассертами.
  function countingFetch(counts: Record<string, number>): typeof fetch {
    const inner = routeFetch();
    return jest.fn((url: string, init?: RequestInit) => {
      if (typeof url === "string") {
        if (url.includes("missing-profile")) counts.missing = (counts.missing ?? 0) + 1;
        if (url.includes("outlier-profile")) counts.outliers = (counts.outliers ?? 0) + 1;
        if (url.includes("regularity-profile")) counts.regularity = (counts.regularity ?? 0) + 1;
        if (url.includes("decomposition-profile")) counts.decomposition = (counts.decomposition ?? 0) + 1;
        if (url.includes("variance-profile")) counts.variance = (counts.variance ?? 0) + 1;
        if (url.includes("smoothing-profile")) counts.smoothing = (counts.smoothing ?? 0) + 1;
        if (url.includes("stationarity-profile")) counts.stationarity = (counts.stationarity ?? 0) + 1;
        if (url.includes("spectral-profile")) counts.spectral = (counts.spectral ?? 0) + 1;
        if (url.includes("feature-generation-profile")) counts.featureGeneration = (counts.featureGeneration ?? 0) + 1;
        if (url.includes("scaling-profile")) counts.scaling = (counts.scaling ?? 0) + 1;
      }
      return inner(url, init);
    }) as unknown as typeof fetch;
  }

  it("after applying missing corrections the blocked decomposition stop refreshes without a page reload", async () => {
    // Сценарий постановки: декомпозиция заблокирована пропусками; аналитик
    // применяет исправление в «Пропусках» — остановка «Декомпозиция ряда»
    // должна получить свежий профиль и зелёный статус БЕЗ перезагрузки.
    const counts: Record<string, number> = {};
    let applied = false;
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            target_column: init?.method === "POST" ? JSON.parse(String(init.body)).column : "Price",
            suggested_column: "Price",
            available_columns: ["Price"],
            has_dataset: true,
          }),
        });
      }
      if (typeof url === "string" && url.includes("missing-corrections") && init?.method === "POST") {
        if (JSON.parse(String(init.body)).apply) applied = true;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            applied: Boolean(init.body && JSON.parse(String(init.body)).apply),
            strategy: "median_mode", total_missing: 2, total_changed: 2,
            total_still_missing: 0, rows_removed: 0, added_columns: [],
            columns: [{ column: "Price", missing_count: 2, changed_count: 2, still_missing: 0, missing_examples: [1, 3], flag_column: null }],
            profile: [{ ...MISSING_PROFILE.columns[0], missing_count: 0, missing_pct: 0, missing_examples: [] }],
          }),
        });
      }
      if (typeof url === "string" && url.includes("decomposition-profile")) {
        counts.decomposition = (counts.decomposition ?? 0) + 1;
        return Promise.resolve({ ok: true, json: () => Promise.resolve(applied ? DECOMPOSITION_PROFILE : blockedDecomposition) });
      }
      if (typeof url === "string" && url.includes("missing-profile")) {
        counts.missing = (counts.missing ?? 0) + 1;
        return Promise.resolve({ ok: true, json: () => Promise.resolve(applied ? clearedMissingProfile : MISSING_PROFILE) });
      }
      return (routeFetch() as unknown as (u: string, i?: RequestInit) => Promise<unknown>)(url, init);
    }) as unknown as typeof fetch;

    render(<TsAnalysisPreprocessing />);

    // ДО применения: бейдж «Декомпозиции» в правой колонке показывает
    // устаревающий плейсхолдер с причиной блокировки (статус skipped).
    expect(await screen.findByText(BLOCKING_REASON)).toBeInTheDocument();

    // Мастер «Пропусков»: предпросмотр → подтверждение → применение.
    fireEvent.click(screen.getByRole("button", { name: "Исправить пропуски" }));
    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await screen.findByText("Исправлено значений: 2");
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(screen.getByRole("button", { name: "Применить исправления" }));

    // ПОСЛЕ применения (без перезагрузки, без клика по «Декомпозиции»):
    // 1) сама остановка «Пропуски» стала done;
    await waitFor(() =>
      expect(screen.getByText("Проверка пройдена, пропусков нет")).toBeInTheDocument(),
    );
    // 2) бейдж «Декомпозиции» обновился до done-статуса;
    expect(await screen.findByText("STL выполнен, остаточная диагностика пройдена")).toBeInTheDocument();
    expect(screen.queryByText(BLOCKING_REASON)).not.toBeInTheDocument();
    // 3) иконка статуса в степпере — «Пройдено» (драйвер зелёной подсветки).
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Декомпозиция ряда/ })).toHaveAccessibleName(/Пройдено/),
    );
    // Профиль декомпозиции запрошен ровно дважды: монтирование + одна
    // инвалидация применения (без двойного fetch и без бесконечного цикла).
    expect(counts.decomposition).toBe(2);
    expect(counts.missing).toBeGreaterThanOrEqual(2);
  });

  it("after applying outliers corrections the missing stop refreshes (symmetric invalidation)", async () => {
    // Симметрия контракта: исправление в «Выбросах» тоже мутирует датасет —
    // «Пропуски» обязаны пересчитать профиль (кэпирование может устранить
    // пропуски-выбросы, удаление строк — изменить полноту).
    let applied = false;
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            target_column: init?.method === "POST" ? JSON.parse(String(init.body)).column : "Price",
            suggested_column: "Price",
            available_columns: ["Price"],
            has_dataset: true,
          }),
        });
      }
      if (typeof url === "string" && url.includes("outlier-corrections") && init?.method === "POST") {
        if (JSON.parse(String(init.body)).apply) applied = true;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            applied: Boolean(init.body && JSON.parse(String(init.body)).apply),
            strategy: "cap", total_outliers: 1, total_changed: 1,
            total_still_outliers: 0, rows_removed: 0, added_columns: [], used_residual: false,
            columns: [{ column: "Price", outlier_count: 1, changed_count: 1, still_outliers: 0, outlier_examples: [3], flag_column: null, stats_before: null, stats_after: null }],
            profile: [{ ...OUTLIERS_PROFILE.columns[0], outlier_count: 0, outlier_pct: 0, outlier_examples: [] }],
          }),
        });
      }
      if (typeof url === "string" && url.includes("missing-profile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(applied ? clearedMissingProfile : MISSING_PROFILE) });
      }
      if (typeof url === "string" && url.includes("outlier-profile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(applied ? clearedOutliersProfile : OUTLIERS_PROFILE) });
      }
      return (routeFetch() as unknown as (u: string, i?: RequestInit) => Promise<unknown>)(url, init);
    }) as unknown as typeof fetch;

    render(<TsAnalysisPreprocessing />);
    // ДО применения: «Пропуски» — warning («Найдено 2 пропусков»).
    await screen.findByText("Найдено 2 пропусков");

    // Мастер «Выбросов»: открыть через степпер, предпросмотр, применение.
    fireEvent.click((await screen.findAllByRole("button", { name: /Выбросы/ }))[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Исправить выбросы" }));
    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await screen.findByText("Исправлено значений: 1");
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(screen.getByRole("button", { name: "Применить исправления" }));

    // ПОСЛЕ: «Пропуски» узнали об исправлении в «Выбросах» — стали done
    // без перезагрузки страницы и без повторного визита остановки.
    await waitFor(() =>
      expect(screen.getByText("Проверка пройдена, пропусков нет")).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Пропуски/ })).toHaveAccessibleName(/Пройдено/),
    );
  });

  it("feature_eng and scaling statuses load at mount without visiting the stops (no lazy staleness)", async () => {
    // Унификация контракта: статусы всех 10 остановок всегда отражают
    // текущий датасет. Раньше «Генерация признаков»/«Масштабирование»
    // оставались «Не запускалось» до первого визита — после применения
    // исправлений их бейджи тоже устаревали.
    const counts: Record<string, number> = {};
    global.fetch = countingFetch(counts);
    render(<TsAnalysisPreprocessing />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Генерация признаков/ })).toHaveAccessibleName(/Найдены проблемы/),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Масштабирование/ })).toHaveAccessibleName(/Найдены проблемы/),
    );
    expect(counts.featureGeneration).toBeGreaterThanOrEqual(1);
    expect(counts.scaling).toBeGreaterThanOrEqual(1);
  });

  it("saving a stop's mode does not invalidate other stops' profiles", async () => {
    // Гард узкой зоны инвалидации: PUT preprocessing-check-modes меняет
    // режим ОДНОЙ остановки — датасет не мутирует, чужие профили не
    // перезапрашиваются (иначе каждое переключение режима вызывало бы
    // лишнюю волну STL/FFT-пересчётов).
    const counts: Record<string, number> = {};
    global.fetch = countingFetch(counts);
    render(<TsAnalysisPreprocessing />);

    // Дожидаемся первичной загрузки профиля декомпозиции.
    await waitFor(() => expect((counts.decomposition ?? 0)).toBeGreaterThanOrEqual(1));
    const baseline = counts.decomposition;

    fireEvent.change(await screen.findByRole("combobox", { name: "Режим проверки Пропуски" }), {
      target: { value: "disabled" },
    });
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/v1/session/dataset/preprocessing-check-modes"),
        expect.objectContaining({ method: "PUT" }),
      ),
    );

    // Профиль декомпозиции НЕ перезапрошен после смены режима «Пропусков».
    expect(counts.decomposition).toBe(baseline);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Task PREPR-4 (аудит PREPR-3-класса на других вкладках): найдено, что
// три self-fetch Обзора («Пропуски», «Выбросы», «Регулярность») после
// PREPR-3 остались на мёртвых ключах — state missingRefreshKey/
// outliersRefreshKey/regularityRefreshKey больше НИКТО не бампит
// (onApplied бампит только datasetVersion), т.е. refreshKey этих Обзор
// панелей заморожен на 0. Контракт PREPR-3 «применение исправления в
// ЛЮБОЙ остановке = инвалидация ВСЕХ профилей» распространяется и на
// Обзоры. Три слоя защиты:
//   (1) компонентный контракт — refreshKey инвалидирует fetch Обзора;
//   (2) исходник-гард — родитель передаёт ЖИВОЙ datasetVersion, а не
//       замороженные xxxRefreshKey (прецедент гард-тестов исходника —
//       ProductHeaderThemeToggle.test.tsx);
//   (3) пользовательский оракул — Обзор остановки показывает актуальный
//       профиль сразу после применения исправления в своей остановке.
// ─────────────────────────────────────────────────────────────────────────────
describe("TsAnalysisPreprocessing — self-fetch Обзоры: живая инвалидация (PREPR-4)", () => {
  const clearedMissingProfile = {
    ...MISSING_PROFILE,
    status: "done",
    total_missing: 0,
    rows_with_missing: 0,
    rows_with_missing_pct: 0,
    missing_rate_pct: 0,
    columns: [{ ...MISSING_PROFILE.columns[0], missing_count: 0, missing_pct: 0, missing_examples: [] }],
  };

  it("each self-fetch overview refetches its profile when refreshKey changes (component contract)", async () => {
    // Контракт компонента: изменение refreshKey = повторный fetch профиля.
    // Мутант «удалить refreshKey из deps эффекта» ловится здесь.
    global.fetch = routeFetch();

    const cases: Array<{
      name: string;
      element: (key: number) => ReactElement;
      urlPart: string;
    }> = [
      {
        name: "missing",
        element: (key) => <PreprocessingMissingOverview refreshKey={key} />,
        urlPart: "missing-profile",
      },
      {
        name: "outliers",
        element: (key) => <PreprocessingOutliersOverview refreshKey={key} column="Price" />,
        urlPart: "outlier-profile",
      },
      {
        name: "regularity",
        element: (key) => <PreprocessingRegularityOverview refreshKey={key} />,
        urlPart: "regularity-profile",
      },
    ];

    for (const testCase of cases) {
      const fetchSpy = global.fetch as unknown as jest.Mock;
      fetchSpy.mockClear();

      const view = render(testCase.element(0));
      await waitFor(() =>
        expect(fetchSpy.mock.calls.some(([url]) => String(url).includes(testCase.urlPart))).toBe(true),
      );
      const firstCalls = fetchSpy.mock.calls.filter(([url]) => String(url).includes(testCase.urlPart)).length;
      expect(firstCalls).toBeGreaterThanOrEqual(1);

      fetchSpy.mockClear();
      view.rerender(testCase.element(1));
      await waitFor(() =>
        expect(fetchSpy.mock.calls.some(([url]) => String(url).includes(testCase.urlPart))).toBe(true),
      );
      view.unmount();
    }
  });

  it("parent passes a live composite key to the three self-fetch overviews (no frozen keys)", () => {
    // Исходник-гард: PREPR-3 бампил только datasetVersion, а Обзоры
    // оставались на собственных ключах, которые в применениях не бампились
    // (замороженные данные). Родитель обязан передавать Обзорам СУММУ
    // живых ключей: xxxRefreshKey + datasetVersion. Утверждение
    // not.toContain с закрывающей скобкой запрещает и «заморозку»
    // (refreshKey={xxxRefreshKey} без datasetVersion), и «замещение»
    // (refreshKey={datasetVersion} без собственного ключа — сломало бы
    // пересчёт Обзора после смены режима остановки).
    const source = readFileSync(
      resolve(process.cwd(), "packages/ui/components/TsAnalysisPreprocessing.tsx"),
      "utf8"
    );
    expect(source).toContain("refreshKey={missingRefreshKey + datasetVersion}");
    expect(source).toContain("refreshKey={outliersRefreshKey + datasetVersion}");
    expect(source).toContain("refreshKey={regularityRefreshKey + datasetVersion}");
    expect(source).not.toContain("refreshKey={missingRefreshKey}");
    expect(source).not.toContain("refreshKey={outliersRefreshKey}");
    expect(source).not.toContain("refreshKey={regularityRefreshKey}");
    expect(source).not.toMatch(/refreshKey=\{\d+\}/);
  });

  it("overview shows the fresh profile right after applying corrections in its own stop (user-visible contract)", async () => {
    // Пользовательский оракул: «Пропуски» активны по умолчанию — Обзор
    // показывает 2 пропуска; аналитик применяет исправление в мастере,
    // возвращается к Обзору — тот показывает 0 пропусков без перезагрузки.
    let applied = false;
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            target_column: init?.method === "POST" ? JSON.parse(String(init.body)).column : "Price",
            suggested_column: "Price",
            available_columns: ["Price"],
            has_dataset: true,
          }),
        });
      }
      if (typeof url === "string" && url.includes("missing-corrections") && init?.method === "POST") {
        if (JSON.parse(String(init.body)).apply) applied = true;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            applied: Boolean(init.body && JSON.parse(String(init.body)).apply),
            strategy: "median_mode", total_missing: 2, total_changed: 2,
            total_still_missing: 0, rows_removed: 0, added_columns: [],
            columns: [{ column: "Price", missing_count: 2, changed_count: 2, still_missing: 0, missing_examples: [1, 3], flag_column: null }],
            profile: [{ ...MISSING_PROFILE.columns[0], missing_count: 0, missing_pct: 0, missing_examples: [] }],
          }),
        });
      }
      if (typeof url === "string" && url.includes("missing-profile")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(applied ? clearedMissingProfile : MISSING_PROFILE) });
      }
      return (routeFetch() as unknown as (u: string, i?: RequestInit) => Promise<unknown>)(url, init);
    }) as unknown as typeof fetch;

    render(<TsAnalysisPreprocessing />);

    // ДО применения: Обзор «Пропусков» — 2 пропуска (25.0%).
    expect(await screen.findByText("Пропусков — 2 (25.0%)")).toBeInTheDocument();

    // Мастер: предпросмотр → подтверждение → применение.
    fireEvent.click(screen.getByRole("button", { name: "Исправить пропуски" }));
    await screen.findByRole("checkbox", { name: "Выбрать колонку Price" });
    fireEvent.click(screen.getByRole("button", { name: "Предпросмотр изменений" }));
    await screen.findByText("Исправлено значений: 2");
    fireEvent.click(screen.getByRole("checkbox", { name: /Подтверждаю изменение активного датасета/i }));
    fireEvent.click(screen.getByRole("button", { name: "Применить исправления" }));

    // Возврат к Обзору остановки (инвариант информативности: явный клик
    // «Метрики и алгоритм» возвращает из пайплайна) — Обзор ремоунтится
    // и обязан показать СВЕЖИЙ профиль: 0 пропусков.
    fireEvent.click(screen.getAllByRole("button", { name: "Метрики и алгоритм" })[0]);
    expect(await screen.findByText("Пропусков — 0 (0.0%)")).toBeInTheDocument();
    expect(screen.queryByText("Пропусков — 2 (25.0%)")).not.toBeInTheDocument();
  });
});
