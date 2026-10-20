// packages/ui/components/upload-panel-chart-refresh.cert-oracles.test.tsx
//
// UPLOAD-RECOMP-2-CERT (2026-10-20): ОРАКУЛЫ НА СВОИХ ДАННЫХ (канал
// oracle) -- поведенческий контур модуля «Загрузка» на ЖИВОМ компоненте
// (TsAnalysisUpload), корпус дизъюнктен upload-panel-chart-refresh.test.tsx
// (их: chart-refresh.csv month/city/revenue 2x4) и TsAnalysisUpload.test.tsx:
//
//   * файл kuban-trade.csv, dataset_id cert-recomp-kuban-1, колонки
//     day/warehouse/sales, панель 2 склада (wh1/wh2) x 5 дат = 10 строк;
//   * выборки данных по СЧЁТЧИКУ вызовов: 1-й вызов -- панель (10 точек,
//     y=100..109), 2-й и далее -- преобразованный ряд (5 точек, mean-агрегат
//     y=205..213 -- честная ручная арифметика (200+2i+210+2i)/2 = 205+2i);
//   * маркеры -- честные тексты модуля: футер графика «10 точек»/«5 точек»,
//     бейдж сэмплинга распределения, футер «Весь датасет»;
//   * ОРАКУЛ СВЯЗКИ ФАКТОВ (UPLOAD-RECOMP-2a): тело POST /date-column --
//     ровно {column: "day", confirmed: true} (запись ТОЛЬКО POST-тел);
//   * ОРАКУЛ БЕЙДЖА: пассивный бейдж «Ряд не трансформируем» присутствует
//     до преобразования и исчезает после (данные уже не панель).
//
// Функция канала мутационной кампании: убивает M06–M14 (см.
// scripts/cert_recomp2/mutations.py) -- детектирует до-фиксное поведение
// FIX/RECOMP-2a (эквивалент RED на родителе серии).

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

// ── СВОЙ корпус: панель 2 склада (wh1/wh2) x 5 дат ───────────────────────

const panelUploadResponse = {
  dataset_id: "cert-recomp-kuban-1",
  name: "kuban-trade.csv",
  rows: 10,
  columns: 3,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["day", "warehouse", "sales"],
      ["2024-03-01", "wh1", "100"],
      ["2024-03-01", "wh2", "210"],
    ],
    tail: [["2024-03-05", "wh2", "218"]],
  },
  columns_info: [
    { name: "day", dtype: "object", type_icon: "datetime", non_null: 10, nulls: 0, unique: 5 },
    { name: "warehouse", dtype: "object", type_icon: "categorical", non_null: 10, nulls: 0, unique: 2 },
    { name: "sales", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
  ],
  quality: {
    cols_with_missing: 0,
    cols_with_outliers: 0,
    rows_total: 10,
    duplicates: 0,
    missing_cols: [],
    outlier_cols: [],
  },
};

const univariateUploadResponse = {
  ...panelUploadResponse,
  rows: 5,
  columns: 2,
  columns_info: [
    { name: "day", dtype: "object", type_icon: "datetime", non_null: 5, nulls: 0, unique: 5 },
    { name: "sales", dtype: "int64", type_icon: "numeric", non_null: 5, nulls: 0, unique: 5 },
  ],
};

const panelDetection = {
  date_col: { selected: "day", confidence: 96, candidates: [{ name: "day", score: 0.96 }] },
  entity_col: { selected: "warehouse", confidence: 92, candidates: [{ name: "warehouse", score: 0.92 }] },
};

const univariateDetection = {
  date_col: { selected: "day", confidence: 96, candidates: [{ name: "day", score: 0.96 }] },
  entity_col: { selected: "(нет)", confidence: 0, candidates: [{ name: "sales", score: 0.0 }] },
};

const entityFilterOptions = {
  applied: false,
  entity_col: "warehouse",
  value: null,
  available_values: ["wh1", "wh2"],
  n_rows_before: 10,
  n_rows_after: null,
  n_dates: null,
  date_min: null,
  date_max: null,
  frequency: null,
};

const entityFilterPreviewWh1 = {
  ...entityFilterOptions,
  value: "wh1",
  n_rows_after: 5,
  n_dates: 5,
  date_min: "2024-03-01",
  date_max: "2024-03-05",
  frequency: "D — ежедневная",
};

const entityFilterApplied = { ...entityFilterPreviewWh1, applied: true, available_values: ["wh1"] };

const aggPreview = {
  applied: false,
  date_col: "day",
  func: "mean",
  n_rows_before: 10,
  n_rows_after: 5,
  n_dates: 5,
  n_dates_skipped: 0,
  dropped_columns: ["warehouse"],
  numeric_columns: ["sales"],
  first_kept_columns: [],
};

const aggApplied = { ...aggPreview, applied: true };

const okStatsResponse = {
  columns: [
    {
      name: "sales",
      non_null_count: 10,
      stats: {
        mean: 155,
        median: 155,
        std: 5,
        skewness: 0,
        kurtosis: 0,
        q1: 150,
        q3: 160,
        iqr: 10,
        distribution_hint: "Близко к нормальному",
      },
    },
  ],
  min_non_null_for_stats: 2,
};

const panelTimeseries = {
  column: "sales",
  date_column: "day",
  points: [
    { x: "2024-03-01T00:00:00", y: 100 },
    { x: "2024-03-01T00:00:00", y: 210 },
    { x: "2024-03-02T00:00:00", y: 101 },
    { x: "2024-03-02T00:00:00", y: 211 },
    { x: "2024-03-03T00:00:00", y: 102 },
    { x: "2024-03-03T00:00:00", y: 212 },
    { x: "2024-03-04T00:00:00", y: 103 },
    { x: "2024-03-04T00:00:00", y: 213 },
    { x: "2024-03-05T00:00:00", y: 104 },
    { x: "2024-03-05T00:00:00", y: 214 },
  ],
  sampled: false,
  sampling_method: null,
  original_count: 10,
  was_resorted: false,
};

// mean-агрегат своей арифметики: (100+2i + 210+2i)/2 = 155+2i... для
// i=0..4 база панельных значений 100+2i / 210+2i -- mean = 155+2i.
const transformedTimeseries = {
  ...panelTimeseries,
  points: [0, 1, 2, 3, 4].map((i) => ({ x: `2024-03-0${i + 1}T00:00:00`, y: 205 + 2 * i })),
  original_count: 5,
};

const panelDistribution = {
  column: "sales",
  non_null_count: 10,
  min: 100,
  max: 214,
  scatter: panelTimeseries.points,
  scatter_sampled: true,
  scatter_sampling_method: "lttb",
  scatter_original_count: 10,
  histogram: [],
  kde: [],
};

const transformedDistribution = {
  ...panelDistribution,
  non_null_count: 5,
  scatter: transformedTimeseries.points,
  scatter_original_count: 5,
};

const decompositionResponse = {
  applicable: true,
  reason: null,
  frequency: "D",
  frequency_label: "Дневная",
  period_used: 2,
  n_points: 10,
  method: "STL",
  trend_pct: 55,
  seasonal_pct: 15,
  cyclical_pct: 5,
  resid_pct: 25,
};

const decompositionSeriesResponse = {
  applicable: true,
  reason: null,
  method: "STL",
  sampled: false,
  sampling_method: null,
  original_count: 10,
  points: panelTimeseries.points.map((p, i) => ({ x: p.x, trend: 1, seasonal: 2, cyclical: 0, resid: 0.5 * i })),
};

// ── Мок: выборки по счётчику вызовов (панель -> преобразованный ряд) ─────

function certMock(detectionSequence: unknown[]) {
  let detectionCall = 0;
  let timeseriesCalls = 0;
  let distributionCalls = 0;
  let rowsCalls = 0;
  let stopsReports = 0;
  const dateColumnBodies: Record<string, unknown>[] = [];
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
      if (body.value) return Promise.resolve({ ok: true, json: () => Promise.resolve(entityFilterPreviewWh1) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve(entityFilterOptions) });
    }
    if (typeof url === "string" && url.includes("/dataset/panel-aggregate")) {
      const body = JSON.parse(String(init?.body ?? "{}"));
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body.apply ? aggApplied : aggPreview) });
    }
    if (typeof url === "string" && url.includes("/date-column")) {
      // Пин СВЯЗКИ ФАКТОВ (UPLOAD-RECOMP-2a): записываем ТОЛЬКО POST-тела
      // (GET-профиль детекции идёт без тела -- в запись не попадает).
      if (init?.body) dateColumnBodies.push(JSON.parse(String(init.body)));
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ date_column: "day", has_dataset: true }) });
    }
    if (typeof url === "string" && url.includes("/dataset/timeseries")) {
      timeseriesCalls += 1;
      timeseriesUrls.push(url);
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
      const total = detectionCall >= 2 ? 5 : 10;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ columns: ["day", "warehouse", "sales"], rows: [], offset: 0, limit: 200, total_rows: total, returned: 0, has_more: false }),
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
      stopsReports += 1;
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
  return { timeseriesUrls, distributionUrls, rowsUrls, dateColumnBodies, getStopsReports: () => stopsReports };
}

async function renderKubanPanel(detectionSequence: unknown[] = [panelDetection, univariateDetection]) {
  const mocks = certMock(detectionSequence);
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "kuban-trade.csv", { type: "text/csv" })]);
  await waitFor(() => expect(screen.getByText("Превью датасета")).toBeInTheDocument());
  return mocks;
}

async function applyEntityFilterWh1AndConfirm() {
  fireEvent.click(screen.getByRole("button", { name: /^Структура/ }));
  await waitFor(() => expect(screen.getByTestId("panel-paths-block")).toBeInTheDocument());
  // Бейдж-альтернатива (пассивная) -- на месте до преобразования.
  expect(screen.getByTestId("panel-badge")).toBeInTheDocument();
  const select = await waitFor(() => screen.getByTestId("panel-entity-select"));
  fireEvent.change(select, { target: { value: "wh1" } });
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

describe("UPLOAD-RECOMP-2-CERT: сценарий 1 -- «Фильтр сущности» на своих данных", () => {
  it("после apply+подтверждения «График» показывает преобразованный ряд; POST-тело -- {column: day, confirmed: true}", async () => {
    const mocks = await renderKubanPanel();
    const { timeseriesUrls, dateColumnBodies } = mocks;
    // Счётчик доставок карты остановок ДО подтверждения (стартовый отчёт
    // после загрузки датасета).
    const stopsBefore = mocks.getStopsReports();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    await waitFor(() => expect(screen.getByText("10 точек")).toBeInTheDocument());

    await applyEntityFilterWh1AndConfirm();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    await waitFor(() => expect(screen.getByText("5 точек")).toBeInTheDocument());

    expect(timeseriesUrls.length).toBeGreaterThanOrEqual(2);
    expect(timeseriesUrls[0]).toContain("column=sales");
    expect(timeseriesUrls[0]).toContain("date_column=day");
    expect(timeseriesUrls[1]).toContain("column=sales");
    expect(timeseriesUrls[1]).toContain("date_column=day");

    // Связка двух фактов: бэкенд получил ЯВНОЕ подтверждение аналитика.
    expect(dateColumnBodies.length).toBeGreaterThanOrEqual(1);
    expect(dateColumnBodies[0]).toEqual({ column: "day", confirmed: true });

    // ЗЕРКАЛЬНЫЙ РЕ-ПОСТ (спека §3.1, R6): после подтверждения карта
    // остановок обязана быть доставлена в панель «Прогресс» заново --
    // панель остаётся зеркалом модуля (хронология решает).
    await waitFor(() => expect(mocks.getStopsReports()).toBeGreaterThan(stopsBefore));
  });
});

describe("UPLOAD-RECOMP-2-CERT: сценарий 2 -- «Агрегация по времени» на своих данных", () => {
  it("после apply агрегации mean и подтверждения «График» показывает агрегат (5 точек)", async () => {
    const { timeseriesUrls } = await renderKubanPanel();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    await waitFor(() => expect(screen.getByText("10 точек")).toBeInTheDocument());

    await applyAggregateAndConfirm();

    fireEvent.click(screen.getByRole("button", { name: /^График/ }));
    await waitFor(() => expect(screen.getByText("5 точек")).toBeInTheDocument());

    expect(timeseriesUrls.length).toBeGreaterThanOrEqual(2);
    expect(timeseriesUrls[1]).toContain("column=sales");
    expect(timeseriesUrls[1]).toContain("date_column=day");
  });
});

describe("UPLOAD-RECOMP-2-CERT: остальные поверхности данных и бейдж", () => {
  it("«Распределение» после apply -- преобразованный датасет (ре-фетч /dataset/distribution)", async () => {
    const { distributionUrls } = await renderKubanPanel();

    fireEvent.click(screen.getByRole("button", { name: /^Распределение/ }));
    await waitFor(() => expect(screen.getByText(/Показано 10 из 10 точек/)).toBeInTheDocument());

    await applyEntityFilterWh1AndConfirm();

    fireEvent.click(screen.getByRole("button", { name: /^Распределение/ }));
    await waitFor(() => expect(screen.getByText(/Показано 5 из 5 точек/)).toBeInTheDocument());

    expect(distributionUrls.length).toBeGreaterThanOrEqual(2);
  });

  it("«Весь датасет» после apply -- кэш панельных страниц сброшен (ре-фетч /dataset/rows)", async () => {
    const { rowsUrls } = await renderKubanPanel();

    fireEvent.click(screen.getByText("Весь датасет"));
    await waitFor(() => expect(screen.getByText(/из 10$/)).toBeInTheDocument());

    await applyEntityFilterWh1AndConfirm();

    fireEvent.click(screen.getByRole("button", { name: /^Превью датасета/ }));
    fireEvent.click(screen.getByText("Весь датасет"));
    await waitFor(() => expect(screen.getByText(/из 5$/)).toBeInTheDocument());

    expect(rowsUrls.length).toBeGreaterThanOrEqual(2);
  });

  it("бейдж «Ряд не трансформируем» исчезает после преобразования (данные уже не панель)", async () => {
    await renderKubanPanel();

    fireEvent.click(screen.getByRole("button", { name: /^Структура/ }));
    await waitFor(() => expect(screen.getByTestId("panel-badge")).toBeInTheDocument());
    expect(screen.getByTestId("panel-badge").textContent).toContain("Ряд не трансформируем");

    // Выбор пути через агрегацию -- панель сведена к ряду.
    const applyButton = await waitFor(() => screen.getByTestId("panel-agg-apply"));
    await waitFor(() => expect(applyButton).not.toBeDisabled());
    fireEvent.click(applyButton);
    await waitFor(() => expect(screen.getAllByText("Univariate TS").length).toBeGreaterThan(0));

    // Бейдж обязан исчезнуть: блок трёх путей больше не рендерится.
    await waitFor(() => expect(screen.queryByTestId("panel-badge")).not.toBeInTheDocument());
  });
});
