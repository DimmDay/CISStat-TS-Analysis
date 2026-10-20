// packages/ui/components/upload-panel-paths-categorical-dates.test.tsx
//
// UPLOAD-RECOMP-2-DECOMP (2026-10-20): интеграционный сценарий тимлида
// «декомпозиция на остановке „График" после изменения панельного датасета»
// на РЕАЛЬНОМ профиле columns_info (отличие от upload-panel-transforms /
// upload-panel-chart-refresh, где месяц помечен type_icon="datetime").
//
// Живой API (проверено curl /v1/session/dataset на воспроизведённой
// сессии standalone@3001 + api@8000) отдаёт для CSV со строковыми датами:
//   month -> type_icon "categorical" (36), region -> "categorical" (2),
//   sales -> "numeric".
// С таким профилем эвристика иерархии строила цепочку region -> month
// (кардинальность 2 -> 36 проходит порог 1.5x) и classifyStructure
// возвращал Hierarchical РАНЬШЕ ветки Panel Data:
//   - блок «Панельные данные: три пути исследования» не рендерился
//     (isPanelClass=false) -> «Фильтр сущности»/«Агрегация по времени»
//     недоступны -> панель невозможно свести к одному ряду;
//   - декомпозиция на «Графике» оставалась недоступной (честный отказ
//     бэкенда по панельным дублям дат) -- сценарий тимлида воспроизведён
//     в реальном браузере до фикса.
//
// Маршрут оракула (полный путь аналитика):
//   1. Панель загружена (реальный профиль колонок, месяц categorical);
//   2. «Структура»: блок трёх путей ВИДЕН, класс Panel Data;
//   3. «Фильтр сущности» (alpha) -> «Применить» -> класс Univariate TS
//      -> «Подтвердить структуру данных»;
//   4. Возврат на «График» -> «Считать декомпозицию» -> бейджи
//      applicable=true с НОВЫМИ долями дисперсии (путь к декомпозиции
//      открыт: датасет уже не панельный);
//   5. Тот же маршрут через «Агрегацию по времени» (mean).

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

// ── СВОЙ корпус: панель 2 сущности (alpha/beta) x 36 дат, месяц categorical ──

const N_DATES = 36;

function makePoints(count: number, value: number): Array<{ x: string; y: number }> {
  return Array.from({ length: count }, (_, i) => ({
    x: `2024-01-${String((i % 28) + 1).padStart(2, "0")}T00:00:00`,
    y: value + i,
  }));
}

const panelUploadResponse = {
  dataset_id: "decomp-cat-dates-1",
  name: "decomp-cat-dates.csv",
  rows: N_DATES * 2,
  columns: 3,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["month", "region", "sales"],
      ["2022-01-01", "alpha", "100"],
      ["2022-01-01", "beta", "300"],
    ],
    tail: [["2024-12-01", "beta", "480"]],
  },
  // РЕАЛЬНЫЙ профиль живого API: строковые даты CSV -- "categorical".
  columns_info: [
    { name: "month", dtype: "object", type_icon: "categorical", non_null: 72, nulls: 0, unique: 36 },
    { name: "region", dtype: "object", type_icon: "categorical", non_null: 72, nulls: 0, unique: 2 },
    { name: "sales", dtype: "float64", type_icon: "numeric", non_null: 72, nulls: 0, unique: 60 },
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

// После apply фильтра сущности: строки отфильтрованы, даты остаются
// строками (categorical, unique=36); после агрегации: месяц datetime64.
const filteredUploadResponse = {
  ...panelUploadResponse,
  rows: N_DATES,
  columns_info: [
    { name: "month", dtype: "object", type_icon: "categorical", non_null: 36, nulls: 0, unique: 36 },
    { name: "region", dtype: "object", type_icon: "categorical", non_null: 36, nulls: 0, unique: 1 },
    { name: "sales", dtype: "float64", type_icon: "numeric", non_null: 36, nulls: 0, unique: 36 },
  ],
};

const aggregatedUploadResponse = {
  ...panelUploadResponse,
  rows: N_DATES,
  columns: 2,
  columns_info: [
    { name: "month", dtype: "datetime64[ns]", type_icon: "datetime", non_null: 36, nulls: 0, unique: 36 },
    { name: "sales", dtype: "float64", type_icon: "numeric", non_null: 36, nulls: 0, unique: 36 },
  ],
};

const panelDetection = {
  date_col: { selected: "month", confidence: 100, candidates: [{ name: "month", score: 1.0 }] },
  entity_col: { selected: "region", confidence: 100, candidates: [{ name: "region", score: 1.0 }] },
  frequency: { selected: "MS — месячная (начало месяца)", code: "MS", confidence: 100 },
};

const univariateDetection = {
  date_col: { selected: "month", confidence: 100, candidates: [{ name: "month", score: 1.0 }] },
  entity_col: { selected: "(нет)", confidence: 0, candidates: [{ name: "sales", score: 0.0 }] },
  frequency: { selected: "MS — месячная (начало месяца)", code: "MS", confidence: 100 },
};

const entityFilterOptions = {
  applied: false,
  entity_col: "region",
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
  date_min: "2022-01-01",
  date_max: "2024-12-01",
  frequency: "MS — месячная (начало месяца)",
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
  dropped_columns: ["region"],
  numeric_columns: ["sales"],
  first_kept_columns: [],
};

const aggApplied = { ...aggPreview, applied: true };

const okStatsResponse = {
  columns: [
    {
      name: "sales",
      non_null_count: 72,
      stats: { mean: 296, median: 296, std: 114, skewness: 0, kurtosis: 0, q1: 200, q3: 400, iqr: 200, distribution_hint: "Близко к нормальному" },
    },
  ],
  min_non_null_for_stats: 2,
};

const panelTimeseries = {
  column: "sales",
  date_column: "month",
  points: [...makePoints(N_DATES, 100), ...makePoints(N_DATES, 300)],
  sampled: false,
  sampling_method: null,
  original_count: 72,
  was_resorted: false,
};

const transformedTimeseries = {
  ...panelTimeseries,
  points: makePoints(N_DATES, 200),
  original_count: 36,
};

const panelDecompositionResponse = {
  applicable: false,
  reason:
    "На одну дату приходится несколько значений (72 строк, 36 уникальных дат) -- похоже на панельные данные (несколько сущностей на одну дату). Декомпозиция требует одного значения на дату; агрегация по сущностям здесь не выполняется.",
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
  frequency: "MS",
  frequency_label: "месячная (годовая сезонность)",
  period_used: 12,
  n_points: 36,
  method: "STL",
  trend_pct: 61,
  seasonal_pct: 27,
  cyclical_pct: 4,
  resid_pct: 8,
};

const panelDecompositionSeriesResponse = {
  applicable: false,
  reason: panelDecompositionResponse.reason,
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

function categoricalDatesMock(detectionSequence: unknown[], datasetSequence: unknown[]) {
  let detectionCall = 0;
  let datasetCall = 0;
  let decompositionCalls = 0;
  let decompositionSeriesCalls = 0;
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
      });
    }
    if (typeof url === "string" && url.endsWith("/session/dataset")) {
      const payload = datasetSequence[Math.min(datasetCall, datasetSequence.length - 1)];
      datasetCall += 1;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
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
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(detectionCall >= 2 ? transformedTimeseries : panelTimeseries),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/distribution")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }
    if (typeof url === "string" && url.includes("/dataset/decomposition-series")) {
      decompositionSeriesCalls += 1;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(decompositionSeriesCalls === 1 ? panelDecompositionSeriesResponse : transformedDecompositionSeriesResponse),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/decomposition")) {
      decompositionCalls += 1;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(decompositionCalls === 1 ? panelDecompositionResponse : transformedDecompositionResponse),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/rows")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ columns: ["month", "region", "sales"], rows: [], offset: 0, limit: 200, total_rows: 72, returned: 0, has_more: false }),
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
        json: () => Promise.resolve({ target_column: "sales", suggested_column: "sales", available_columns: ["sales"], has_dataset: true }),
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
}

async function renderCategoricalDatesPanel(datasetSequence: unknown[] = [panelUploadResponse, filteredUploadResponse]) {
  categoricalDatesMock([panelDetection, univariateDetection], datasetSequence);
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropFiles(screen.getByTestId("dropzone-input"), [
    new File(["a,b\n1,2"], "decomp-cat-dates.csv", { type: "text/csv" }),
  ]);
  await waitFor(() => expect(screen.getByText("Превью датасета")).toBeInTheDocument());
}

async function applyEntityFilterAndConfirm() {
  fireEvent.click(screen.getByRole("button", { name: /^Структура/ }));
  // РЕД-ОРАКУЛ дефекта: блок панельных путей обязан появиться на панели
  // со СТРОЧНЫМИ датами (до фикса -- класс Hierarchical, блока нет).
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

describe("UPLOAD-RECOMP-2-DECOMP: панельные микросервисы на панели со строчными датами (реальный профиль API)", () => {
  it("сценарий 1: блок путей виден -> «Фильтр сущности» -> декомпозиция считается на преобразованном ряде", async () => {
    await renderCategoricalDatesPanel();

    // Шаг 1: на панели декомпозиция честно отказывает (панельные дубли).
    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    const computeButton = await waitFor(() => screen.getByRole("button", { name: "Считать декомпозицию" }));
    fireEvent.click(computeButton);
    await waitFor(() => expect(screen.getByText(/похоже на панельные данные/)).toBeInTheDocument());

    // Шаг 2: «Структура» -- панельный класс и блок трёх путей ВИДНЫ
    // (до фикса: Hierarchical, блока нет -- путь к декомпозиции заблокирован).
    await applyEntityFilterAndConfirm();

    // Шаг 3: возврат на «График» -> «Считать декомпозицию» -- датасет уже
    // не панельный, декомпозиция ОБЯЗАНА считаться (applicable=true).
    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    const recomputeButton = await waitFor(() => screen.getByRole("button", { name: "Считать декомпозицию" }));
    fireEvent.click(recomputeButton);
    await waitFor(() => expect(screen.getByText("61%")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/STL · частота: месячная \(годовая сезонность\) · 36 точек/)).toBeInTheDocument());
  });

  it("сценарий 2: тот же маршрут через «Агрегацию по времени» -- декомпозиция считается на агрегированном ряде", async () => {
    await renderCategoricalDatesPanel([panelUploadResponse, aggregatedUploadResponse]);

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    const computeButton = await waitFor(() => screen.getByRole("button", { name: "Считать декомпозицию" }));
    fireEvent.click(computeButton);
    await waitFor(() => expect(screen.getByText(/похоже на панельные данные/)).toBeInTheDocument());

    await applyAggregateAndConfirm();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    const recomputeButton = await waitFor(() => screen.getByRole("button", { name: "Считать декомпозицию" }));
    fireEvent.click(recomputeButton);
    await waitFor(() => expect(screen.getByText("61%")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/STL · частота: месячная \(годовая сезонность\) · 36 точек/)).toBeInTheDocument());
  });
});
