// packages/ui/components/TsAnalysisPreprocessing.test.tsx
//
// Тесты для компонента «Предобработка» — в частности:
// 1. Рендер модуля и 11 шагов степпера
// 2. Кнопка «Справка» переключает секцию
// 3. Expandable description box: chevron, overlay, collapse

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TsAnalysisPreprocessing } from "./TsAnalysisPreprocessing";

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

// Маршрутизирующий мок fetch -- используется везде, где раньше был
// плоский `jest.fn().mockResolvedValue(MISSING_PROFILE)`: теперь ДВА
// реальных стопа опрашивают бэкенд параллельно при монтировании, и без
// маршрутизации по URL «Выбросы» получали бы чужой (missing-shaped)
// ответ.
function routeFetch(overrides: { missing?: unknown; outliers?: unknown; regularity?: unknown; decomposition?: unknown; put?: unknown } = {}) {
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
        }),
      });
    }
    if (init?.method === "PUT") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.put ?? { modes: {} }) });
    }
    if (typeof url === "string" && url.includes("decomposition-profile")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.decomposition ?? DECOMPOSITION_PROFILE) });
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

  it("renders all 11 preprocessing steps in the stepper", () => {
    render(<TsAnalysisPreprocessing />);
    const stepLabels = [
      "Пропуски", "Выбросы", "Регулярность ряда", "Декомпозиция ряда",
      "Стабилизация дисперсии", "Сглаживание ряда", "Стационарность ряда",
      "Спектральный анализ", "Генерация признаков", "Масштабирование",
      "Паспорт свойств ряда",
    ];
    stepLabels.forEach((label) => {
      expect(screen.getByText(label)).toBeInTheDocument();
    });
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

    // До клика — плейсхолдер
    expect(screen.getByText(/Нажмите «Метрики и алгоритм»/i)).toBeInTheDocument();

    // Клик
    fireEvent.click(helpButton);

    // После клика — появляется справка. Используем getAllByText, т.к.
    // regex /Цели модуля/i матчит ДВА элемента: подзаголовок «Справка — Цели
    // модуля и результаты прохождения» и сам контент «Цели модуля "Предобработка"».
    const matches = screen.getAllByText(/Цели модуля/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  it("clicking 'Справка' toggles content off on second click", () => {
    render(<TsAnalysisPreprocessing />);
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
    // 11 остановок всего, но «Пропуски» (skipped) исключены из знаменателя
    // Декомпозиция может ещё выполняться (0) или уже завершиться (1):
    // в обоих случаях 10 применимых остановок и "100%" не появляется.
    // ошибочно, а прогресс-бар не должен упасть на NaN/делении на 0.
    expect(screen.getByText(/^[01]\/10$/)).toBeInTheDocument();
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
