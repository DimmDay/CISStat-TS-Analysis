// packages/ui/components/upload-panel-decomposition-after-transform.test.tsx
//
// UPLOAD-RECOMP-2-DECOMP (2026-10-20): сценарий работы ДЕКОМПОЗИЦИИ на
// остановке «График» после изменения панельного датасета панельными
// микросервисами («Фильтр сущности» / «Агрегация по времени»).
//
// Маршрут аналитика (спека spec_upload_recompose_2026-10-20.md §3.3:
// "Панель превращается в обычный временной ряд -- открываются декомпозиция,
// ACF/PACF, классические модели и прогноз"):
//   1. Панель загружена; на «Графике» аналитик пробует декомпозицию --
//      честный отказ (панельные дубли дат);
//   2. «Структура» -> микросервис -> «Подтвердить структуру данных»;
//   3. Возврат на «График» -> «Считать декомпозицию» заново --
//      декомпозиция ОБЯЗАНА считаться на преобразованном ряде
//      (датасет уже не панельный).
//
// Оракулы -- на СВОИХ данных (дизъюнкт с upload-panel-chart-refresh.test.tsx:
// файл decomp-after-transform.csv, колонки month/city/revenue, панель
// 2 сущности x 36 дат; ответы /dataset/decomposition* ПО СЧЁТЧИКУ вызовов:
// 1-й вызов -- честный панельный отказ, 2-й и далее -- applicable=true
// с НОВЫМИ долями дисперсии 55/25/8/12).

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

// ── СВОЙ корпус: панель 2 сущности (alpha/beta) x 36 дат ─────────────────

const N_DATES = 36;

function makePoints(count: number, value: number): Array<{ x: string; y: number }> {
  return Array.from({ length: count }, (_, i) => ({ x: `2024-01-${String((i % 28) + 1).padStart(2, "0")}T00:00:00`, y: value + i }));
}

const panelUploadResponse = {
  dataset_id: "decomp-after-transform-1",
  name: "decomp-after-transform.csv",
  rows: N_DATES * 2,
  columns: 3,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["month", "city", "revenue"],
      ["2024-01-01", "alpha", "10"],
      ["2024-01-01", "beta", "60"],
    ],
    tail: [["2024-02-05", "beta", "95"]],
  },
  columns_info: [
    { name: "month", dtype: "object", type_icon: "datetime", non_null: 72, nulls: 0, unique: 36 },
    { name: "city", dtype: "object", type_icon: "categorical", non_null: 72, nulls: 0, unique: 2 },
    { name: "revenue", dtype: "int64", type_icon: "numeric", non_null: 72, nulls: 0, unique: 72 },
  ],
  quality: {
    cols_with_missing: 0,
    cols_with_outliers: 0,
    rows_total: 72,
    duplicates: 0,
    missing_cols: [],
    outlier_cols: [],
  },
};

const univariateUploadResponse = {
  ...panelUploadResponse,
  rows: N_DATES,
  columns: 2, // агрегация: city удалена; фильтр: колонки те же, строк 36
  columns_info: [
    { name: "month", dtype: "object", type_icon: "datetime", non_null: 36, nulls: 0, unique: 36 },
    { name: "revenue", dtype: "int64", type_icon: "numeric", non_null: 36, nulls: 0, unique: 36 },
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
  n_rows_before: 72,
  n_rows_after: null,
  n_dates: null,
  date_min: null,
  date_max: null,
  frequency: null,
};

const entityFilterPreviewAlpha = {
  ...entityFilterOptions,
  value: "alpha",
  n_rows_after: 36,
  n_dates: 36,
  date_min: "2024-01-01",
  date_max: "2024-02-05",
  frequency: "D — ежедневная",
};

const entityFilterApplied = { ...entityFilterPreviewAlpha, applied: true, available_values: ["alpha"] };

const aggPreview = {
  applied: false,
  date_col: "month",
  func: "mean",
  n_rows_before: 72,
  n_rows_after: 36,
  n_dates: 36,
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
      non_null_count: 72,
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
    ...makePoints(N_DATES, 10),
    ...makePoints(N_DATES, 60),
  ],
  sampled: false,
  sampling_method: null,
  original_count: 72,
  was_resorted: false,
};

const transformedTimeseries = {
  ...panelTimeseries,
  points: makePoints(N_DATES, 35),
  original_count: 36,
};

// ── ЧЕСТНЫЕ ответы декомпозиции по счётчику вызовов ──────────────────────
// 1-й вызов: датасет ещё панельный -- бэкенд обязан отказать (реальный
// текст гейта панельных дублей, apps/api/decomposition_data.py).
// 2-й и далее: датасет преобразован -- applicable=true с НОВЫМИ долями
// (55/25/8/12 -- уникальные маркеры содержимого второго ответа).

const panelRefusalReason =
  "На одну дату приходится несколько значений (72 строк, 36 уникальных дат) -- похоже на панельные данные (несколько сущностей на одну дату). Декомпозиция требует одного значения на дату; агрегация по сущностям здесь не выполняется.";

const panelDecompositionResponse = {
  applicable: false,
  reason: panelRefusalReason,
  frequency: null,
  frequency_label: null,
  period_used: null,
  n_points: 0,
  method: null,
  trend_pct: null,
  seasonal_pct: null,
  cyclical_pct: null,
  resid_pct: null,
};

const transformedDecompositionResponse = {
  applicable: true,
  reason: null,
  frequency: "D",
  frequency_label: "месячная (годовая сезонность)",
  period_used: 12,
  n_points: 36,
  method: "STL",
  trend_pct: 55,
  seasonal_pct: 25,
  cyclical_pct: 8,
  resid_pct: 12,
};

const panelDecompositionSeriesResponse = {
  applicable: false,
  reason: panelRefusalReason,
  method: null,
  sampled: false,
  sampling_method: null,
  original_count: 0,
  points: [],
};

const transformedDecompositionSeriesResponse = {
  applicable: true,
  reason: null,
  method: "STL",
  sampled: false,
  sampling_method: null,
  original_count: 36,
  points: makePoints(N_DATES, 1).map((p, i) => ({ x: p.x, trend: 1 + i, seasonal: 2, cyclical: 0, resid: 0.5 })),
};

// ── Мок: выборки данных по счётчику вызовов (панель -> преобразованный) ──

function decompMock(detectionSequence: unknown[]) {
  let detectionCall = 0;
  let timeseriesCalls = 0;
  let decompositionCalls = 0;
  let decompositionSeriesCalls = 0;
  const decompositionUrls: string[] = [];
  const decompositionSeriesUrls: string[] = [];
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
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ date_column: "month", has_dataset: true }) });
    }
    if (typeof url === "string" && url.includes("/dataset/timeseries")) {
      timeseriesCalls += 1;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(timeseriesCalls === 1 ? panelTimeseries : transformedTimeseries),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/distribution")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }
    if (typeof url === "string" && url.includes("/dataset/decomposition-series")) {
      decompositionSeriesCalls += 1;
      decompositionSeriesUrls.push(url);
      // 1-й вызов -- панель (честный отказ); 2-й и далее -- преобразованный ряд.
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve(decompositionSeriesCalls === 1 ? panelDecompositionSeriesResponse : transformedDecompositionSeriesResponse),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/decomposition")) {
      decompositionCalls += 1;
      decompositionUrls.push(url);
      // 1-й вызов -- панель (честный отказ); 2-й и далее -- применимо.
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(decompositionCalls === 1 ? panelDecompositionResponse : transformedDecompositionResponse),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/rows")) {
      const total = detectionCall >= 2 ? 36 : 72;
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
  return { decompositionUrls, decompositionSeriesUrls };
}

// ── Маршрут аналитика ─────────────────────────────────────────────────────

async function renderPanelDataset(detectionSequence: unknown[] = [panelDetection, univariateDetection]) {
  const mocks = decompMock(detectionSequence);
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropFiles(screen.getByTestId("dropzone-input"), [
    new File(["a,b\n1,2"], "decomp-after-transform.csv", { type: "text/csv" }),
  ]);
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

// ── Сценарий 1: фильтр сущности -> декомпозиция открывается ──────────────

describe("UPLOAD-RECOMP-2-DECOMP: сценарий 1 -- «Фильтр сущности», декомпозиция на «Графике»", () => {
  it("после apply фильтра сущности декомпозиция считается на преобразованном ряде (applicable=true)", async () => {
    const { decompositionUrls, decompositionSeriesUrls } = await renderPanelDataset();

    // Шаг 1: на панели аналитик пробует декомпозицию -- честный отказ.
    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    const computeButton = await waitFor(() => screen.getByRole("button", { name: "Считать декомпозицию" }));
    fireEvent.click(computeButton);
    await waitFor(() => expect(screen.getByText(/Декомпозиция неприменима:/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/похоже на панельные данные/)).toBeInTheDocument());

    // Шаг 2: «Структура» -> «Фильтр сущности» -> подтверждение.
    await applyEntityFilterAndConfirm();

    // Шаг 3: возврат на «График» -> «Считать декомпозицию» заново --
    // датасет уже не панельный, декомпозиция ОБЯЗАНА считаться.
    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    const recomputeButton = await waitFor(() => screen.getByRole("button", { name: "Считать декомпозицию" }));
    fireEvent.click(recomputeButton);

    // Оракул применимости: бейджи НОВОГО содержимого (уникальные 55/25/8/12)
    // и честный футер STL с частотой преобразованного ряда.
    await waitFor(() => expect(screen.getByText("55%")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("25%")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("12%")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/STL · частота: месячная \(годовая сезонность\) · 36 точек/)).toBeInTheDocument());

    // Оракул выборки: пара /dataset/decomposition + /dataset/decomposition-series
    // запрошена повторно с теми же column/date_column (датасет тот же, содержимое новое).
    expect(decompositionUrls.length).toBeGreaterThanOrEqual(2);
    expect(decompositionUrls[1]).toContain("column=revenue");
    expect(decompositionUrls[1]).toContain("date_column=month");
    expect(decompositionSeriesUrls.length).toBeGreaterThanOrEqual(2);
    expect(decompositionSeriesUrls[1]).toContain("column=revenue");
    expect(decompositionSeriesUrls[1]).toContain("date_column=month");
  });
});

// ── Сценарий 2: агрегация по времени -> декомпозиция открывается ─────────

describe("UPLOAD-RECOMP-2-DECOMP: сценарий 2 -- «Агрегация по времени», декомпозиция на «Графике»", () => {
  it("после apply агрегации декомпозиция считается на агрегированном ряде (applicable=true)", async () => {
    await renderPanelDataset();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    const computeButton = await waitFor(() => screen.getByRole("button", { name: "Считать декомпозицию" }));
    fireEvent.click(computeButton);
    await waitFor(() => expect(screen.getByText(/похоже на панельные данные/)).toBeInTheDocument());

    await applyAggregateAndConfirm();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    const recomputeButton = await waitFor(() => screen.getByRole("button", { name: "Считать декомпозицию" }));
    fireEvent.click(recomputeButton);

    await waitFor(() => expect(screen.getByText("55%")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/STL · частота: месячная \(годовая сезонность\) · 36 точек/)).toBeInTheDocument());
  });
});
