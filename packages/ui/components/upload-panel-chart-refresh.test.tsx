// packages/ui/components/upload-panel-chart-refresh.test.tsx
//
// Фикс-задача UPLOAD-RECOMP-2-FIX (2026-10-20): после apply панельного
// микросервиса («Фильтр сущности» / «Агрегация по времени») данные
// остановок «График», «Распределение», декомпозиции и вкладки
// «Весь датасет» оставались СТАРЫМИ (панельными): эффекты выборки
// /dataset/timeseries, /dataset/distribution и кэш страниц
// /dataset/rows не подписаны на transformEpoch -- единственный
// ре-фетч после apply делали статистика (/dataset/stats) и превью
// (/dataset). Сценарий тимлида: панель -> «Структура» -> путь через
// микросервис -> «Подтвердить структуру данных» -> возврат на
// «График» -- график обновлённого датасета НЕ изменился.
//
// Поведенческие оракулы на СВОИХ данных (дизъюнкт с
// upload-panel-transforms.test.tsx и TsAnalysisUpload.test.tsx):
// файл chart-refresh.csv, колонки month/city/revenue,
// dataset_id chart-refresh-1, панель 2 сущности x 4 даты;
// ответы /dataset/timeseries и /dataset/distribution -- ПО СЧЁТЧИКУ
// вызовов (1-й вызов -- панель 8 точек, 2-й и далее -- преобразованный
// ряд 4 точки): футер графика обязан показать «4 точек».

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisUpload } from "./TsAnalysisUpload";
import { AppShellProvider } from "../context/AppShellContext";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

function dropFiles(input: Element, files: File[]) {
  fireEvent.drop(input, {
    dataTransfer: {
      files,
      items: files.map((file) => ({ kind: "file", type: file.type, getAsFile: () => file })),
      types: ["Files"],
    },
  });
}

// ── СВОЙ корпус: панель 2 сущности (alpha/beta) x 4 даты ────────────────

const panelUploadResponse = {
  dataset_id: "chart-refresh-1",
  name: "chart-refresh.csv",
  rows: 8,
  columns: 3,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["month", "city", "revenue"],
      ["2024-01-01", "alpha", "10"],
      ["2024-01-01", "beta", "60"],
    ],
    tail: [["2024-01-04", "beta", "63"]],
  },
  columns_info: [
    { name: "month", dtype: "object", type_icon: "datetime", non_null: 8, nulls: 0, unique: 4 },
    { name: "city", dtype: "object", type_icon: "categorical", non_null: 8, nulls: 0, unique: 2 },
    { name: "revenue", dtype: "int64", type_icon: "numeric", non_null: 8, nulls: 0, unique: 8 },
  ],
  quality: {
    cols_with_missing: 0,
    cols_with_outliers: 0,
    rows_total: 8,
    duplicates: 0,
    missing_cols: [],
    outlier_cols: [],
  },
};

const univariateUploadResponse = {
  ...panelUploadResponse,
  rows: 4,
  columns: 2, // агрегация: city удалена; фильтр: колонки те же, строк 4
  columns_info: [
    { name: "month", dtype: "object", type_icon: "datetime", non_null: 4, nulls: 0, unique: 4 },
    { name: "revenue", dtype: "int64", type_icon: "numeric", non_null: 4, nulls: 0, unique: 4 },
  ],
};

const panelDetection = {
  date_col: { selected: "month", confidence: 95, candidates: [{ name: "month", score: 0.95 }] },
  entity_col: { selected: "city", confidence: 90, candidates: [{ name: "city", score: 0.9 }] },
};

const univariateDetection = {
  date_col: { selected: "month", confidence: 95, candidates: [{ name: "month", score: 0.95 }] },
  entity_col: { selected: "(нет)", confidence: 0, candidates: [{ name: "revenue", score: 0.0 }] },
};

const entityFilterOptions = {
  applied: false,
  entity_col: "city",
  value: null,
  available_values: ["alpha", "beta"],
  n_rows_before: 8,
  n_rows_after: null,
  n_dates: null,
  date_min: null,
  date_max: null,
  frequency: null,
};

const entityFilterPreviewAlpha = {
  ...entityFilterOptions,
  value: "alpha",
  n_rows_after: 4,
  n_dates: 4,
  date_min: "2024-01-01",
  date_max: "2024-01-04",
  frequency: "D — ежедневная",
};

const entityFilterApplied = { ...entityFilterPreviewAlpha, applied: true, available_values: ["alpha"] };

const aggPreview = {
  applied: false,
  date_col: "month",
  func: "mean",
  n_rows_before: 8,
  n_rows_after: 4,
  n_dates: 4,
  n_dates_skipped: 0,
  dropped_columns: ["city"],
  numeric_columns: ["revenue"],
  first_kept_columns: [],
};

const aggApplied = { ...aggPreview, applied: true };

const okStatsResponse = {
  columns: [
    {
      name: "revenue",
      non_null_count: 8,
      stats: {
        mean: 36,
        median: 36,
        std: 2,
        skewness: 0,
        kurtosis: 0,
        q1: 34,
        q3: 38,
        iqr: 4,
        distribution_hint: "Близко к нормальному",
      },
    },
  ],
  min_non_null_for_stats: 2,
};

const panelTimeseries = {
  column: "revenue",
  date_column: "month",
  points: [
    { x: "2024-01-01T00:00:00", y: 10 },
    { x: "2024-01-01T00:00:00", y: 60 },
    { x: "2024-01-02T00:00:00", y: 11 },
    { x: "2024-01-02T00:00:00", y: 61 },
    { x: "2024-01-03T00:00:00", y: 12 },
    { x: "2024-01-03T00:00:00", y: 62 },
    { x: "2024-01-04T00:00:00", y: 13 },
    { x: "2024-01-04T00:00:00", y: 63 },
  ],
  sampled: false,
  sampling_method: null,
  original_count: 8,
  was_resorted: false,
};

const transformedTimeseries = {
  ...panelTimeseries,
  points: [
    { x: "2024-01-01T00:00:00", y: 35 },
    { x: "2024-01-02T00:00:00", y: 36 },
    { x: "2024-01-03T00:00:00", y: 37 },
    { x: "2024-01-04T00:00:00", y: 38 },
  ],
  original_count: 4,
};

const panelDistribution = {
  column: "revenue",
  non_null_count: 8,
  min: 10,
  max: 63,
  scatter: panelTimeseries.points,
  // sampled=true -- бейдж сэмплинга рендерится и служит честным
  // маркером содержимого ответа (число точек в тексте).
  scatter_sampled: true,
  scatter_sampling_method: "lttb",
  scatter_original_count: 8,
  histogram: [],
  kde: [],
};

const transformedDistribution = {
  ...panelDistribution,
  non_null_count: 4,
  scatter: transformedTimeseries.points,
  scatter_original_count: 4,
};

const decompositionResponse = {
  applicable: true,
  reason: null,
  frequency: "D",
  frequency_label: "Дневная",
  period_used: 2,
  n_points: 8,
  method: "STL",
  trend_pct: 40,
  seasonal_pct: 30,
  cyclical_pct: 10,
  resid_pct: 20,
};

const decompositionSeriesResponse = {
  applicable: true,
  reason: null,
  method: "STL",
  sampled: false,
  sampling_method: null,
  original_count: 8,
  points: panelTimeseries.points.map((p, i) => ({ x: p.x, trend: 1, seasonal: 2, cyclical: 0, resid: 0.5 * i })),
};

// ── Мок: выборки данных по счётчику вызовов (панель -> преобразованный) ──

function refreshMock(detectionSequence: unknown[]) {
  let detectionCall = 0;
  let timeseriesCalls = 0;
  let distributionCalls = 0;
  let rowsCalls = 0;
  const dateColumnBodies: unknown[] = [];
  const timeseriesUrls: string[] = [];
  const distributionUrls: string[] = [];
  const rowsUrls: string[] = [];
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
      });
    }
    if (typeof url === "string" && url.endsWith("/session/dataset")) {
      // Ре-фетч превью после apply: dataset_id тот же, содержимое новое.
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(detectionCall >= 2 ? univariateUploadResponse : panelUploadResponse),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
      const payload = detectionSequence[Math.min(detectionCall, detectionSequence.length - 1)];
      detectionCall += 1;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    }
    if (typeof url === "string" && url.includes("/dataset/entity-filter")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      if (body.apply) return Promise.resolve({ ok: true, json: () => Promise.resolve(entityFilterApplied) });
      if (body.value) return Promise.resolve({ ok: true, json: () => Promise.resolve(entityFilterPreviewAlpha) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve(entityFilterOptions) });
    }
    if (typeof url === "string" && url.includes("/dataset/panel-aggregate")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body.apply ? aggApplied : aggPreview) });
    }
    if (typeof url === "string" && url.includes("/date-column")) {
      dateColumnBodies.push(JSON.parse(String(init?.body ?? "{}")));
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ date_column: "month", has_dataset: true }) });
    }
    if (typeof url === "string" && url.includes("/dataset/timeseries")) {
      timeseriesCalls += 1;
      timeseriesUrls.push(url);
      // 1-й вызов -- панельное содержимое; 2-й и далее -- преобразованное.
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(timeseriesCalls === 1 ? panelTimeseries : transformedTimeseries),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/distribution")) {
      distributionCalls += 1;
      distributionUrls.push(url);
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(distributionCalls === 1 ? panelDistribution : transformedDistribution),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/decomposition-series")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(decompositionSeriesResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/decomposition")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(decompositionResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/rows")) {
      rowsCalls += 1;
      rowsUrls.push(url);
      const total = detectionCall >= 2 ? 4 : 8;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ columns: ["month", "city", "revenue"], rows: [], offset: 0, limit: 200, total_rows: total, returned: 0, has_more: false }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/stats")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(okStatsResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/panel-balance")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ balanced: true, n_entities: 2, n_distinct_date_sets: 1 }) });
    }
    if (typeof url === "string" && url.includes("/target-column")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ target_column: "revenue", suggested_column: "revenue", available_columns: ["revenue"], has_dataset: true }),
      });
    }
    if (typeof url === "string" && url.includes("upload-stops")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reported: 5, run_id: null }) });
    }
    if (typeof url === "string" && url.includes("/trace")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ nodes: [] }) });
    }
    if (typeof url === "string" && url.includes("/upload")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(panelUploadResponse) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as jest.Mock;
  return { timeseriesUrls, distributionUrls, rowsUrls, dateColumnBodies };
}

// ── Сценарий тимлида: панель -> «Структура» -> микросервис ->
//    «Подтвердить структуру данных» -> возврат на «График» ──────────────

async function renderPanelDataset(detectionSequence: unknown[] = [panelDetection, univariateDetection]) {
  const mocks = refreshMock(detectionSequence);
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "chart-refresh.csv", { type: "text/csv" })]);
  await waitFor(() => expect(screen.getByText("Превью датасета")).toBeInTheDocument());
  return mocks;
}

async function applyEntityFilterAndConfirm() {
  fireEvent.click(screen.getByRole("button", { name: /^Структура/ }));
  await waitFor(() => expect(screen.getByTestId("panel-paths-block")).toBeInTheDocument());
  const select = await waitFor(() => screen.getByTestId("panel-entity-select"));
  fireEvent.change(select, { target: { value: "alpha" } });
  const applyButton = await waitFor(() => screen.getByTestId("panel-entity-apply"));
  await waitFor(() => expect(applyButton).not.toBeDisabled());
  fireEvent.click(applyButton);
  await waitFor(() => expect(screen.getAllByText("Univariate TS").length).toBeGreaterThan(0));
  // «Подтвердить структуру данных» -- связка двух фактов (UPLOAD-RECOMP-2a).
  const confirmButton = await waitFor(() => screen.getByTestId("confirm-structure-button"));
  fireEvent.click(confirmButton);
  await waitFor(() => expect(screen.getByTestId("structure-confirmed-note")).toBeInTheDocument());
}

async function applyAggregateAndConfirm() {
  fireEvent.click(screen.getByRole("button", { name: /^Структура/ }));
  await waitFor(() => expect(screen.getByTestId("panel-paths-block")).toBeInTheDocument());
  const applyButton = await waitFor(() => screen.getByTestId("panel-agg-apply"));
  await waitFor(() => expect(applyButton).not.toBeDisabled());
  fireEvent.click(applyButton);
  await waitFor(() => expect(screen.getAllByText("Univariate TS").length).toBeGreaterThan(0));
  const confirmButton = await waitFor(() => screen.getByTestId("confirm-structure-button"));
  fireEvent.click(confirmButton);
  await waitFor(() => expect(screen.getByTestId("structure-confirmed-note")).toBeInTheDocument());
}

describe("UPLOAD-RECOMP-2-FIX: сценарий 1 -- «Фильтр сущности», остановка «График»", () => {
  it("после apply и подтверждения структуры график показывает преобразованный ряд (ре-фетч /dataset/timeseries)", async () => {
    const { timeseriesUrls } = await renderPanelDataset();

    // Аналитик знакомится с графиком ПАНЕЛИ (8 точек обеих сущностей).
    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    await waitFor(() => expect(screen.getByText("8 точек")).toBeInTheDocument());

    // «Структура»: путь через «Фильтр сущности» + подтверждение структуры.
    await applyEntityFilterAndConfirm();

    // Возврат на «График»: график обязан показать ОБНОВЛЁННЫЙ датасет
    // (4 точки преобразованного одномерного ряда).
    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    await waitFor(() => expect(screen.getByText("4 точек")).toBeInTheDocument());

    // Оракул выборки: /dataset/timeseries запрошен повторно ПОСЛЕ apply
    // (те же column/date_column -- содержимое датасета изменилось).
    expect(timeseriesUrls.length).toBeGreaterThanOrEqual(2);
    expect(timeseriesUrls[0]).toContain("column=revenue");
    expect(timeseriesUrls[0]).toContain("date_column=month");
    expect(timeseriesUrls[1]).toContain("column=revenue");
    expect(timeseriesUrls[1]).toContain("date_column=month");
  });
});

describe("UPLOAD-RECOMP-2-FIX: сценарий 2 -- «Агрегация по времени», остановка «График»", () => {
  it("после apply агрегации и подтверждения структуры график показывает агрегированный ряд (ре-фетч /dataset/timeseries)", async () => {
    const { timeseriesUrls } = await renderPanelDataset();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    await waitFor(() => expect(screen.getByText("8 точек")).toBeInTheDocument());

    // «Структура»: путь через «Агрегацию по времени» + подтверждение.
    await applyAggregateAndConfirm();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    await waitFor(() => expect(screen.getByText("4 точек")).toBeInTheDocument());

    expect(timeseriesUrls.length).toBeGreaterThanOrEqual(2);
    expect(timeseriesUrls[1]).toContain("column=revenue");
    expect(timeseriesUrls[1]).toContain("date_column=month");
  });
});

describe("UPLOAD-RECOMP-2-FIX: тот же класс дефекта -- остальные поверхности данных модуля", () => {
  it("«Распределение» после apply показывает преобразованный датасет (ре-фетч /dataset/distribution)", async () => {
    const { distributionUrls } = await renderPanelDataset();

    fireEvent.click(screen.getByRole("button", { name: /^Распределение/ }));
    await waitFor(() => expect(screen.getByText(/Показано 8 из 8 точек/)).toBeInTheDocument());

    await applyEntityFilterAndConfirm();

    fireEvent.click(screen.getByRole("button", { name: /^Распределение/ }));
    await waitFor(() => expect(screen.getByText(/Показано 4 из 4 точек/)).toBeInTheDocument());

    expect(distributionUrls.length).toBeGreaterThanOrEqual(2);
  });

  it("декомпозиция после apply сброшена -- старый результат панели не «залипает»", async () => {
    await renderPanelDataset();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    // Ленивый расчёт: результат появляется по кнопке.
    const computeButton = await waitFor(() => screen.getByRole("button", { name: "Считать декомпозицию" }));
    fireEvent.click(computeButton);
    // Бейдж результата панели (уникальное значение тренда 40%).
    await waitFor(() => expect(screen.getByText("40%")).toBeInTheDocument());

    await applyEntityFilterAndConfirm();

    // Возврат на «График»: старый результат панели обязан быть сброшен
    // (ленивый пересчёт по решению тимлида -- кнопка «Считать» заново).
    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Считать декомпозицию" })).toBeInTheDocument());
  });

  it("вкладка «Весь датасет» после apply не показывает кэш панельных страниц (ре-фетч /dataset/rows)", async () => {
    const { rowsUrls } = await renderPanelDataset();

    // Вкладка «Весь датасет» на «Превью датасета» -- страницы панели.
    fireEvent.click(screen.getByText("Весь датасет"));
    await waitFor(() => expect(screen.getByText(/из 8$/)).toBeInTheDocument());

    await applyEntityFilterAndConfirm();

    // Возврат на «Превью датасета» -> «Весь датасет»: кэш старого
    // содержимого обязан быть сброшен (dataset_id не меняется,
    // transformEpoch -- да).
    fireEvent.click(screen.getByRole("button", { name: /^Превью датасета/ }));
    fireEvent.click(screen.getByText("Весь датасет"));
    await waitFor(() => expect(screen.getByText(/из 4$/)).toBeInTheDocument());

    expect(rowsUrls.length).toBeGreaterThanOrEqual(2);
  });
});
