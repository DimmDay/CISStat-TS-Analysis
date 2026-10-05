// packages/ui/components/TsAnalysisUpload.test.tsx
//
// Обновлено под редизайн вкладки «Загрузка» на общий 3-колоночный
// паттерн платформы (степпер слева / Описание+Обзор по центру /
// управление справа) -- см. шапку TsAnalysisUpload.tsx. По умолчанию
// после загрузки активна остановка "Превью датасета"; тесты на "Распределение"/
// "Структура"/"Качество" сначала кликают по соответствующей кнопке
// степпера.

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisUpload } from "./TsAnalysisUpload";
import { AppShellProvider } from "../context/AppShellContext";
import { progressApiUrl } from "../lib/apiClient";
import { toast } from "sonner";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

// Polyfill: ResizeObserver не определён в jsdom, но нужен Recharts
// ResponsiveContainer (DistributionCharts) -- тот же паттерн, что и в
// TsAnalysisModeling.test.tsx.
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// react-dropzone проверяет dataTransfer.items/types, не только files --
// без этого внутренний фильтр падает на "Array.prototype.some called on
// null or undefined".
function dropFiles(input: Element, files: File[]) {
  fireEvent.drop(input, {
    dataTransfer: {
      files,
      items: files.map((file) => ({ kind: "file", type: file.type, getAsFile: () => file })),
      types: ["Files"],
    },
  });
}

const okUploadResponse = {
  dataset_id: "123",
  name: "test.csv",
  rows: 10,
  columns: 2,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["date", "value"],
      ["2023-01-01", "10"],
      ["2023-01-02", "20"],
    ],
    tail: [["2023-01-09", "90"], ["2023-01-10", "100"]],
  },
  columns_info: [
    { name: "date", dtype: "object", type_icon: "datetime", non_null: 10, nulls: 0, unique: 10 },
    { name: "value", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
  ],
  quality: {
    cols_with_missing: 1,
    cols_with_outliers: 0,
    rows_total: 10,
    duplicates: 0,
    missing_cols: ["value"],
    outlier_cols: [],
  },
};

const okStatsResponse = {
  columns: [
    {
      name: "value",
      non_null_count: 10,
      stats: {
        mean: 55.5,
        median: 54,
        std: 30.1,
        skewness: 0.1,
        kurtosis: -1.2,
        q1: 32.5,
        q3: 77.5,
        iqr: 45,
        distribution_hint: "Близко к нормальному",
      },
    },
  ],
  min_non_null_for_stats: 2,
};

// Реалистичный ответ GET /dataset/distribution (apps/api/chart_data.py) --
// без него ScatterDistributionChart/HistogramDistributionChart раньше
// падали на data.scatter===undefined (generic-фолбэк ниже отдаёт {}).
const okDistributionResponse = {
  column: "value",
  non_null_count: 10,
  min: 10,
  max: 100,
  scatter: Array.from({ length: 10 }, (_, i) => ({ x: i, y: 10 + i * 10 })),
  scatter_sampled: false,
  scatter_sampling_method: null,
  scatter_original_count: 10,
  histogram: [
    { x0: 10, x1: 55, count: 5 },
    { x0: 55, x1: 100, count: 5 },
  ],
  kde: Array.from({ length: 5 }, (_, i) => ({ x: 10 + i * 20, y: 0.01 * (i + 1) })),
};

// Ответ GET /dataset/structure-detection по умолчанию (см. ветку ниже):
// date уверенно детектирована, группирующей колонки нет -- легитимный
// "(нет)" с confidence 0% (односерийный/однорядный датасет).
const defaultStructureDetection = {
  date_col: { selected: "date", confidence: 95, candidates: [{ name: "date", score: 0.95 }, { name: "value", score: 0.0 }] },
  entity_col: { selected: "(нет)", confidence: 0, candidates: [{ name: "date", score: 0.0 }, { name: "value", score: 0.0 }] },
};

// Сценарий структуры для PROGR-14-A: выбранные значения и raw confidence
// авто-детекта (confidence -- статическая оценка бэкенда, НЕ
// пересчитывается при ручном onChange, 2026-08-14).
interface DetectionScenario {
  dateCol: { selected: string; confidence: number };
  entityCol: { selected: string; confidence: number };
}

function detectionPayload(scenario: DetectionScenario) {
  return {
    date_col: {
      selected: scenario.dateCol.selected,
      confidence: scenario.dateCol.confidence,
      candidates: scenario.dateCol.selected.startsWith("(") ? [] : [{ name: scenario.dateCol.selected, score: scenario.dateCol.confidence / 100 }],
    },
    entity_col: {
      selected: scenario.entityCol.selected,
      confidence: scenario.entityCol.confidence,
      candidates: scenario.entityCol.selected.startsWith("(") ? [] : [{ name: scenario.entityCol.selected, score: scenario.entityCol.confidence / 100 }],
    },
  };
}

// AppShellProvider гидрируется с /v1/session/current при монтировании,
// а после успешного upload компонент сам запрашивает /dataset/stats --
// мокаем обе ручки; конкретные тесты переопределяют /upload под свой сценарий.
// detectionOverride (PROGR-14-A) -- свой сценарий structure-detection.
// stopsOkSequence (PROGR-15-A) -- сценарии приёма POST отчёта остановок:
// каждый вызов берёт следующее значение, последнее повторяется (пустой
// список/не задан -- всегда ok). Ветка "upload-stops" объявлена ДО ветки
// "/upload": подстрока "/upload" ловит и "upload-stops", и именно эта
// коллизия маскировала URL-дефект PROGR-15-A (мок обслуживал мусорный URL).
function mockFetchSequence(
  uploadResult: unknown,
  uploadOk = true,
  detectionOverride?: DetectionScenario,
  stopsOkSequence?: boolean[],
) {
  let stopsCallsMade = 0;
  global.fetch = jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            has_active_dataset: false,
            dataset: null,
            stages: {},
            last_active_stage: null,
            updated_at: null,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/target-column")) {
      // GET и POST -- одинаковый ответ достаточен для теста: значение
      // уже выбрано (value), useTargetColumn не должен пытаться
      // авто-POST-ить suggested_column поверх реального выбора.
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            target_column: "value",
            suggested_column: "value",
            available_columns: ["value"],
            has_dataset: true,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
      // Реальный контентный скоринг с бэкенда (2026-08-14, заменил
      // клиентскую эвристику buildDetectionFromColumns) -- окружение
      // теста мокает как раз то, что раньше вычислялось синхронно
      // на клиенте: date-колонка "date" (datetime dtype в okUploadResponse).
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(detectionOverride ? detectionPayload(detectionOverride) : defaultStructureDetection),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/stats")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(okStatsResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/distribution")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(okDistributionResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/panel-balance")) {
      // В тестовых моках нет реальной группирующей колонки -- фиксируем
      // ответ явно, чтобы не зависеть от generic-фолбэка ниже.
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ balanced: false, n_entities: 0, n_distinct_date_sets: 0 }) });
    }
    if (typeof url === "string" && url.includes("upload-stops")) {
      const ok = stopsOkSequence && stopsOkSequence.length > 0
        ? stopsOkSequence[Math.min(stopsCallsMade, stopsOkSequence.length - 1)]
        : true;
      stopsCallsMade += 1;
      return Promise.resolve({ ok, json: () => Promise.resolve({ reported: 5, run_id: null }) });
    }
    if (typeof url === "string" && url.includes("/upload")) {
      return Promise.resolve({ ok: uploadOk, json: () => Promise.resolve(uploadResult) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as jest.Mock;
}

describe("TsAnalysisUpload", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchSequence(okUploadResponse);
  });

  it("should render the upload dropzone before any file is uploaded", () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );
    expect(screen.getByText(/Источник данных/)).toBeInTheDocument();
    expect(screen.getByText(/Перетащите файл сюда/)).toBeInTheDocument();
  });

  it("shows 4 demo datasets below the dropzone; forecast monitor is FIRST (задача 2026-09-16)", () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );
    expect(screen.getByTestId("demo-dataset-forecast_monitor_n150")).toBeInTheDocument();
    expect(screen.getByTestId("demo-dataset-retail_revenue")).toBeInTheDocument();
    expect(screen.getByTestId("demo-dataset-energy_consumption")).toBeInTheDocument();
    expect(screen.getByTestId("demo-dataset-finance_ohlcv")).toBeInTheDocument();

    // Порядок: forecast monitor -- ПЕРВАЯ карточка демо-ряда.
    const demoCards = screen.getAllByTestId(/^demo-dataset-/);
    expect(demoCards[0]).toBe(screen.getByTestId("demo-dataset-forecast_monitor_n150"));

    // Univariate TS теперь у двух датасетов (forecast monitor + retail),
    // panel/multivariate -- по одному.
    expect(screen.getAllByText("Univariate TS")).toHaveLength(2);
    expect(screen.getByText("Panel Data — Balanced")).toBeInTheDocument();
    expect(screen.getByText("Multivariate TS")).toBeInTheDocument();
  });

  it("clicking the forecast monitor demo card uploads forecast_monitor_synthetic_n150.csv through the real doUpload pipeline", async () => {
    mockFetchSequence(okUploadResponse);

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    fireEvent.click(screen.getByTestId("demo-dataset-forecast_monitor_n150"));

    // Тот же индикатор загрузки и та же итоговая карточка, что и при
    // обычной drag-and-drop загрузке -- demo-режим не имитация.
    await waitFor(() => {
      expect(screen.getByText(/test\.csv/)).toBeInTheDocument();
    });

    // Файл, ушедший в POST /upload -- именно forecast_monitor_synthetic_n150.csv.
    const uploadCall = (global.fetch as jest.Mock).mock.calls.find(
      ([url]) => typeof url === "string" && url.includes("/upload")
    );
    expect(uploadCall).toBeTruthy();
    const body = uploadCall![1].body as FormData;
    const sentFile = body.get("file") as File;
    expect(sentFile).toBeTruthy();
    expect(sentFile.name).toBe("forecast_monitor_synthetic_n150.csv");
  });

  it("clicking a demo dataset card uploads it through the real doUpload pipeline", async () => {
    mockFetchSequence(okUploadResponse);

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    fireEvent.click(screen.getByTestId("demo-dataset-retail_revenue"));

    // Тот же индикатор загрузки и та же итоговая карточка, что и при
    // обычной drag-and-drop загрузке -- demo-режим не имитация, а
    // реальный doUpload(file) с сгенерированным CSV.
    await waitFor(() => {
      expect(screen.getByText(/test\.csv/)).toBeInTheDocument();
    });
  });

  it("should show uploaded file name in the success summary", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    const file = new File(["a,b\n1,2"], "test.csv", { type: "text/csv" });
    dropFiles(screen.getByTestId("dropzone-input"), [file]);

    await waitFor(() => {
      expect(screen.getByText("test.csv")).toBeInTheDocument();
    });
  });

  it("should show the 3-column layout with stepper stops after upload (default: Обзор)", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => {
      // Степпер: все 4 остановки (labels — см. STOPS в TsAnalysisUpload.tsx)
      expect(screen.getByText("Превью датасета")).toBeInTheDocument();
      expect(screen.getByText("Распределение")).toBeInTheDocument();
      expect(screen.getByText("Структура")).toBeInTheDocument();
      expect(screen.getByText("Качество")).toBeInTheDocument();
      // По умолчанию активна первая остановка -- превью-таблица видна сразу
      expect(screen.getByText("date")).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Паспорт свойств ряда: Загрузка" })).toBeInTheDocument();
    });
  });

  it("should show real descriptive statistics on the Распределение stop", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("Распределение")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Распределение"));

    await waitFor(() => {
      expect(screen.getByText("Близко к нормальному")).toBeInTheDocument();
      expect(screen.getByText("55,5")).toBeInTheDocument(); // toLocaleString("ru-RU") -> запятая
    });
  });

  it("should render real Recharts charts (not placeholders) on the Распределение stop", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("Распределение")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Распределение"));

    await waitFor(() => {
      // Плейсхолдер-тексты (см. историю: "[ x=index, y=... ]" и т.п.) не
      // должны присутствовать -- реальные графики их заменили.
      expect(screen.queryByText(/\[ x=index/)).not.toBeInTheDocument();
      expect(screen.queryByText(/nbins=30/)).not.toBeInTheDocument();
      expect(screen.queryByText(/KDE curve/)).not.toBeInTheDocument();
    });
  });

  it("should show structure detection and structural class on the Структура stop", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("Структура")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Структура"));

    await waitFor(() => {
      expect(screen.getByText("Колонка даты")).toBeInTheDocument();
      expect(screen.getByText("Группирующая колонка")).toBeInTheDocument();
      expect(screen.getByText("Структурный класс данных")).toBeInTheDocument();
    });
  });

  it("should show the structural class decision schema (visual reference) on the Структура stop", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("Структура")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Структура"));

    await waitFor(() => {
      // Заголовок и хотя бы несколько правил дерева решений реально в DOM
      expect(screen.getByText("Определение структуры данных")).toBeInTheDocument();
      expect(screen.getByText("Нет даты И нет группировки")).toBeInTheDocument();
      expect(screen.getByText("Cross-Sectional")).toBeInTheDocument();
      expect(screen.getByText("Balanced")).toBeInTheDocument();
      expect(screen.getByText("Unbalanced")).toBeInTheDocument();
      expect(screen.getByText("Spatio-Temporal")).toBeInTheDocument();
      expect(screen.getByText("Event Time Series")).toBeInTheDocument();
    });
  });

  it("should show quality teaser with a one-line summary on the Качество stop", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("Качество")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Качество"));

    await waitFor(() => {
      expect(screen.getByText(/см\. Валидация/)).toBeInTheDocument();
    });
  });

  it("should show the «Перейти к валидации» invitation button at the bottom of the stepper regardless of the active stop", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("Качество")).toBeInTheDocument());

    // Паттерн "Ведём исследователя за руку": кнопка внизу степпера видна
    // сразу после загрузки (остановка по умолчанию "Превью датасета"),
    // не только на последней остановке "Качество".
    const invite = screen.getByRole("link", { name: /Перейти к валидации/ });
    expect(invite).toHaveAttribute("href", "/validation");
  });

  it("should show a technical parse-warning banner when the backend reports one", async () => {
    mockFetchSequence({ ...okUploadResponse, parse_warnings: ["Возможна проблема с кодировкой файла — обнаружены нечитаемые символы (�)"] });

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);

    await waitFor(() => {
      expect(screen.getByText(/проблема с кодировкой/)).toBeInTheDocument();
    });
  });

  it("should reject files > 4MB", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );
    dropFiles(screen.getByTestId("dropzone-input"), [new File([new ArrayBuffer(5 * 1024 * 1024)], "large.csv", { type: "text/csv" })]);
    await waitFor(() => {
      expect(screen.getByText(/Файл слишком большой/)).toBeInTheDocument();
    });
  });

  it("should reject unsupported file formats", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );
    dropFiles(screen.getByTestId("dropzone-input"), [new File(["plain text"], "test.txt", { type: "text/plain" })]);
    await waitFor(() => {
      expect(screen.getByText(/Неподдерживаемый формат/)).toBeInTheDocument();
    });
  });

  it("should show error toast on upload failure (FastAPI {detail: ...} shape)", async () => {
    mockFetchSequence({ detail: "Ошибка сервера" }, false);

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Ошибка сервера"));
    });
  });

  it("should show a readable message (not [object Object]) on FastAPI 422 structured validation errors", async () => {
    // Регрессия: require_api_key на /v1/public/* отдаёт 422 с detail в
    // виде массива {loc,msg,type}, а не строкой -- раньше это превращалось
    // в "[object Object]" (см. чат: реальный баг на проде).
    mockFetchSequence(
      { detail: [{ loc: ["header", "x-api-key"], msg: "field required", type: "value_error.missing" }] },
      false
    );

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("field required"));
      expect(toast.error).not.toHaveBeenCalledWith(expect.stringContaining("[object Object]"));
    });
  });

  // ── useTargetColumn: единый "исследуемый признак" (2026-08-14) ──
  // Регрессия на реальный баг: FAO-датасет (Country/Year/Price) показывал
  // Year в селекторе вместо Price при возврате на вкладку.

  it("auto-selects suggested_column (not first-in-dataframe) when target_column is not yet set, and shows the auto-selected hint", async () => {
    const targetColumnCalls: string[] = [];
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
        });
      }
      if (typeof url === "string" && url.includes("/target-column")) {
        targetColumnCalls.push(init?.method ?? "GET");
        if (init?.method === "POST") {
          // Сервер подтверждает: suggested_column ("Price") зафиксирован как target_column
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ target_column: "Price", suggested_column: "Price", available_columns: ["Year", "Price"], has_dataset: true }),
          });
        }
        // GET: ровно баговый кейс -- Year идёт первым в датафрейме, но
        // suggested_column честно рекомендует Price (исключая date/year-имена)
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: null, suggested_column: "Price", available_columns: ["Year", "Price"], has_dataset: true }),
        });
      }
      if (typeof url === "string" && url.includes("/upload")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ...okUploadResponse,
              columns_info: [
                { name: "Year", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
                { name: "Price", dtype: "float64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );
    dropFiles(screen.getByTestId("dropzone-input"), [new File(["Year,Price\n2020,65.9"], "fao.csv", { type: "text/csv" })]);

    await waitFor(() => {
      // НЕ Year (первая числовая по порядку) -- Price (suggested_column)
      expect(screen.getByDisplayValue("Price")).toBeInTheDocument();
    });
    expect(screen.getByTestId("auto-selected-hint")).toBeInTheDocument();
    expect(targetColumnCalls).toContain("POST"); // авто-выбор реально ПЕРСИСТИТСЯ, не только отображается
  });

  it("shows a warning toast when a previously selected column is reset by uploading a new dataset", async () => {
    let uploadCount = 0;
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
        });
      }
      if (typeof url === "string" && url.includes("/target-column")) {
        if (init?.method === "POST") {
          const body = JSON.parse((init.body as string) ?? "{}");
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ target_column: body.column, suggested_column: body.column, available_columns: ["Volume"], has_dataset: true }),
          });
        }
        // До первой загрузки -- нет датасета вообще.
        if (uploadCount === 0) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ target_column: null, suggested_column: null, available_columns: [], has_dataset: false }),
          });
        }
        // После первой загрузки -- Price уже выбран (реалистично: POST
        // уже случился при первой загрузке, GET отражает сохранённое состояние).
        if (uploadCount === 1) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ target_column: "Price", suggested_column: "Price", available_columns: ["Year", "Price"], has_dataset: true }),
          });
        }
        // После второй загрузки (другой датасет) -- backend сбросил
        // target_column (Price отсутствует в новом файле).
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: null, suggested_column: "Volume", available_columns: ["Volume"], has_dataset: true }),
        });
      }
      if (typeof url === "string" && url.includes("/upload")) {
        uploadCount += 1;
        const columnsInfo =
          uploadCount === 1
            ? [
                { name: "Year", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
                { name: "Price", dtype: "float64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
              ]
            : [{ name: "Volume", dtype: "float64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 }];
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ ...okUploadResponse, name: `dataset-${uploadCount}.csv`, columns_info: columnsInfo }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    // Первая загрузка -- Price устанавливается
    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a"], "fao.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByDisplayValue("Price")).toBeInTheDocument());

    // Dropzone скрыт после успешной загрузки (3-колоночный layout результата) --
    // "Сменить файл" возвращает к форме загрузки (handleReset).
    fireEvent.click(screen.getAllByText("Сменить файл")[0]);
    await waitFor(() => expect(screen.getByTestId("dropzone-input")).toBeInTheDocument());

    // Вторая загрузка -- другой датасет, Price отсутствует
    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a"], "other.csv", { type: "text/csv" })]);

    await waitFor(() => {
      expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining("Price"));
    });
  });

  // ── Остановка «График» (2026-08-14) ──

  it("shows the Chart stop between Превью and Распределение with a real line chart when date column is confident", async () => {
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
        });
      }
      if (typeof url === "string" && url.includes("/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: "value", suggested_column: "value", available_columns: ["value"], has_dataset: true }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              date_col: { selected: "date", confidence: 95, candidates: [{ name: "date", score: 0.95 }] },
              entity_col: { selected: "(нет)", confidence: 0, candidates: [] },
            }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/timeseries")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              column: "value",
              date_column: "date",
              points: [
                { x: "2023-01-01T00:00:00", y: 10 },
                { x: "2023-01-02T00:00:00", y: 20 },
              ],
              sampled: false,
              sampling_method: null,
              original_count: 2,
              was_resorted: false,
            }),
        });
      }
      if (typeof url === "string" && url.includes("/upload")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(okUploadResponse) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["date,value\n2023-01-01,10"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("График")).toBeInTheDocument());

    // "График" стоит между "Превью датасета" и "Распределение" в степпере
    const stepperButtons = screen.getAllByRole("button").map((b) => b.textContent);
    const chartIdx = stepperButtons.findIndex((t) => t?.includes("График"));
    const overviewIdx = stepperButtons.findIndex((t) => t?.includes("Превью датасета"));
    const distributionIdx = stepperButtons.findIndex((t) => t?.includes("Распределение"));
    expect(chartIdx).toBeGreaterThan(overviewIdx);
    expect(chartIdx).toBeLessThan(distributionIdx);

    fireEvent.click(screen.getByText("График"));

    await waitFor(() => {
      expect(screen.getByText(/2 точек/)).toBeInTheDocument();
    });
    // Плейсхолдер "нет уверенной даты" НЕ должен показываться -- date
    // колонка в okUploadResponse имеет type_icon="datetime" (confidence=80)
    expect(screen.queryByText(/Дата не определена уверенно/)).not.toBeInTheDocument();
  });

  it("shows 'no confident date' message instead of chart when no datetime column detected", async () => {
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
        });
      }
      if (typeof url === "string" && url.includes("/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: "value", suggested_column: "value", available_columns: ["value"], has_dataset: true }),
        });
      }
      if (typeof url === "string" && url.includes("/upload")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ...okUploadResponse,
              // Ни одной datetime-колонки -- низкая уверенность (25)
              columns_info: [
                { name: "a", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
                { name: "value", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,value\n1,10"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("График")).toBeInTheDocument());
    fireEvent.click(screen.getByText("График"));

    await waitFor(() => {
      expect(screen.getByText(/Дата не определена уверенно/)).toBeInTheDocument();
    });
  });

  it("decomposition is lazy: computed only after clicking 'Считать декомпозицию', shows honest applicable=false state", async () => {
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
        });
      }
      if (typeof url === "string" && url.includes("/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: "value", suggested_column: "value", available_columns: ["value"], has_dataset: true }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              date_col: { selected: "date", confidence: 95, candidates: [{ name: "date", score: 0.95 }] },
              entity_col: { selected: "(нет)", confidence: 0, candidates: [] },
            }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/timeseries")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ column: "value", date_column: "date", points: [{ x: "2023-01-01T00:00:00", y: 1 }], sampled: false, sampling_method: null, original_count: 1, was_resorted: false }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/decomposition")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              applicable: false,
              reason: "Частота данных (YS-JAN) не поддерживает внутрипериодную сезонность",
              frequency: "YS-JAN",
              frequency_label: null,
              period_used: null,
              n_points: 0,
              method: null,
              trend_pct: null,
              seasonal_pct: null,
              cyclical_pct: null,
              resid_pct: null,
            }),
        });
      }
      if (typeof url === "string" && url.includes("/upload")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(okUploadResponse) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["date,value\n2023-01-01,10"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("График")).toBeInTheDocument());
    fireEvent.click(screen.getByText("График"));

    // До клика -- кнопка есть, бейджей нет (ленивый расчёт)
    const computeBtn = await screen.findByText("Считать декомпозицию");
    expect(screen.queryByText("Тренд")).not.toBeInTheDocument();

    fireEvent.click(computeBtn);

    await waitFor(() => {
      expect(screen.getByText(/Декомпозиция неприменима/)).toBeInTheDocument();
      expect(screen.getByText(/внутрипериодную сезонность/)).toBeInTheDocument();
    });
  });

// Общий мок для тестов, где декомпозиция реально применима (STL,
// оба эндпоинта -- бейджи и график компонент -- возвращают согласованные
// applicable=true данные на 24 месячных точках). Вынесен в helper,
// т.к. используется несколькими тестами (применимая декомпозиция +
// чекбоксы выбора компонент).
function mockApplicableDecompositionFetch() {
  global.fetch = jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
      });
    }
    if (typeof url === "string" && url.includes("/target-column")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ target_column: "value", suggested_column: "value", available_columns: ["value"], has_dataset: true }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            date_col: { selected: "date", confidence: 95, candidates: [{ name: "date", score: 0.95 }] },
            entity_col: { selected: "(нет)", confidence: 0, candidates: [] },
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/timeseries")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            column: "value", date_column: "date",
            points: [{ x: "2018-01-01T00:00:00", y: 1 }, { x: "2018-02-01T00:00:00", y: 2 }],
            sampled: false, sampling_method: null, original_count: 2, was_resorted: false,
          }),
      });
    }
    // ВАЖНО: /dataset/decomposition-series -- более специфичный путь,
    // должен проверяться ПЕРЕД /dataset/decomposition (иначе includes()
    // ложно поймает series-запрос в ветку бейджей).
    if (typeof url === "string" && url.includes("/dataset/decomposition-series")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            applicable: true,
            reason: null,
            method: "STL",
            sampled: false,
            sampling_method: null,
            original_count: 24,
            points: [
              { x: "2018-01-01T00:00:00", trend: 100.1, seasonal: -0.5, cyclical: 0.0, resid: 0.2 },
              { x: "2018-02-01T00:00:00", trend: 100.6, seasonal: 1.2, cyclical: 0.1, resid: -0.1 },
            ],
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/decomposition")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            applicable: true,
            reason: null,
            frequency: "MS",
            frequency_label: "месячная (годовая сезонность)",
            period_used: 12,
            n_points: 24,
            method: "STL",
            trend_pct: 46.5,
            seasonal_pct: 46.8,
            cyclical_pct: 5.9,
            resid_pct: 0.8,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/upload")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(okUploadResponse) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as unknown as typeof fetch;
}

  it("clicking 'Считать декомпозицию' shows the additional decomposed-series chart with legend (Тренд/Сезонность/Цикличность/Остаток), original chart untouched", async () => {
    mockApplicableDecompositionFetch();

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["date,value\n2023-01-01,10"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("График")).toBeInTheDocument());
    fireEvent.click(screen.getByText("График"));

    // Исходный линейный график ("2 точек") должен присутствовать И ДО,
    // И ПОСЛЕ клика по декомпозиции -- "исходный график остаётся как есть".
    await waitFor(() => expect(screen.getByText(/2 точек/)).toBeInTheDocument());

    const computeBtn = await screen.findByText("Считать декомпозицию");
    fireEvent.click(computeBtn);

    // Бейджи (уже было) + НОВЫЙ график компонент под ними. "Тренд" теперь
    // легитимно встречается 2 раза (бейдж + подпись чекбокса выбора
    // компонент, без эмодзи-разметки после правки 2026-08-19) --
    // getAllByText, не getByText.
    await waitFor(() => {
      expect(screen.getAllByText("Тренд").length).toBeGreaterThanOrEqual(1);
    });
    // Recharts Legend/оси -- внутренний SVG, зависящий от реального layout
    // контейнера (ResponsiveContainer получает 0x0 в jsdom, см. warning
    // "width(0) and height(0)" -- та же особенность окружения, что и у
    // остальных Recharts-графиков в этом наборе). Проверяем то, что
    // рендерится независимо от layout -- подпись графика (обычный <p>,
    // не SVG) и наличие контейнера графика в DOM.
    expect(screen.getByText(/Цикличность — оценочная эвристика/)).toBeInTheDocument();

    // Исходный график ("2 точек" в его подписи) И новый график компонент
    // (тоже "2 точек" в его подписи, я замокал 2 точки series) -- оба
    // на месте одновременно, исходный график НЕ пропал.
    expect(screen.getAllByText(/2 точек/).length).toBe(2);
  });

  it("component visibility checkboxes default to Trend+Seasonal ON, Cyclical+Residual OFF (same as legacy Streamlit)", async () => {
    mockApplicableDecompositionFetch();

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["date,value\n2023-01-01,10"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("График")).toBeInTheDocument());
    fireEvent.click(screen.getByText("График"));

    const computeBtn = await screen.findByText("Считать декомпозицию");
    fireEvent.click(computeBtn);

    await waitFor(() => expect(screen.getByTestId("decomposition-toggle-trend")).toBeInTheDocument());

    expect(screen.getByTestId("decomposition-toggle-trend")).toBeChecked();
    expect(screen.getByTestId("decomposition-toggle-seasonal")).toBeChecked();
    expect(screen.getByTestId("decomposition-toggle-cyclical")).not.toBeChecked();
    expect(screen.getByTestId("decomposition-toggle-resid")).not.toBeChecked();
  });

  it("unchecking a component checkbox toggles it (user controls which components to compare)", async () => {
    mockApplicableDecompositionFetch();

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["date,value\n2023-01-01,10"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("График")).toBeInTheDocument());
    fireEvent.click(screen.getByText("График"));
    fireEvent.click(await screen.findByText("Считать декомпозицию"));

    const trendToggle = await screen.findByTestId("decomposition-toggle-trend");
    const cyclicalToggle = screen.getByTestId("decomposition-toggle-cyclical");

    expect(trendToggle).toBeChecked();
    fireEvent.click(trendToggle);
    expect(trendToggle).not.toBeChecked();

    expect(cyclicalToggle).not.toBeChecked();
    fireEvent.click(cyclicalToggle);
    expect(cyclicalToggle).toBeChecked();
  });

  it("real FAO-style dataset (Country/Year/Price): Year is auto-detected as date, chart works WITHOUT manual correction on Структура", async () => {
    // Регресс на реальный сценарий из чата: раньше Country/Price
    // получали абсурдные score (0.90/0.50) от позиционной клиентской
    // эвристики, Year не определялся уверенно вообще, и даже после
    // ручной коррекции на «Структуре» остановка «График» не менялась
    // (баг confidence, не пересчитываемого при onChange). Оба бага
    // исправлены -- этот тест проверяет, что теперь ничего чинить
    // руками не нужно: реальный backend-скоринг сразу даёт Year.
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
        });
      }
      if (typeof url === "string" && url.includes("/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: "Price", suggested_column: "Price", available_columns: ["Year", "Price"], has_dataset: true }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
        // Реальный контентный скоринг с бэкенда (app/data/detectors.py::
        // score_all_columns_as_date) -- Country/Price честно 0.0, Year высокий.
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              date_col: {
                selected: "Year",
                confidence: 100,
                candidates: [
                  { name: "Year", score: 1.0 },
                  { name: "Country", score: 0.0 },
                  { name: "Price", score: 0.0 },
                ],
              },
              entity_col: {
                selected: "Country",
                confidence: 100,
                candidates: [
                  { name: "Country", score: 1.0 },
                  { name: "Price", score: 0.0 },
                ],
              },
            }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/timeseries")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              column: "Price", date_column: "Year",
              points: [{ x: "1994-01-01T00:00:00", y: 65.9 }, { x: "1995-01-01T00:00:00", y: 70.1 }],
              sampled: false, sampling_method: null, original_count: 2, was_resorted: false,
            }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/panel-balance")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ balanced: true, n_entities: 3, n_distinct_date_sets: 1 }) });
      }
      if (typeof url === "string" && url.includes("/upload")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ...okUploadResponse,
              columns_info: [
                { name: "Country", dtype: "object", type_icon: "categorical", non_null: 30, nulls: 0, unique: 3 },
                { name: "Year", dtype: "int64", type_icon: "numeric", non_null: 30, nulls: 0, unique: 30 },
                { name: "Price", dtype: "float64", type_icon: "numeric", non_null: 30, nulls: 0, unique: 30 },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    dropFiles(screen.getByTestId("dropzone-input"), [new File(["Country,Year,Price\nRU,1994,65.9"], "fao.csv", { type: "text/csv" })]);

    // Остановка «Структура»: НЕ Country (0.90 в старом баге), НЕ Price
    // (0.50) -- Year с высокой уверенностью, без единого ручного клика.
    await waitFor(() => expect(screen.getByText("Структура")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Структура"));
    await waitFor(() => {
      expect(screen.getByDisplayValue("Year")).toBeInTheDocument();
    });

    // Остановка «График»: работает СРАЗУ, без захода на «Структуру» и
    // ручной коррекции (старый баг: confidence не обновлялся при onChange,
    // "ничего не меняется" после ручного выбора Year).
    fireEvent.click(screen.getByText("График"));
    await waitFor(() => {
      expect(screen.queryByText(/Дата не определена уверенно/)).not.toBeInTheDocument();
      expect(screen.getByText(/2 точек/)).toBeInTheDocument();
    });
  });

  it("shows real frequency from backend on Структура (not hardcoded 'D — ежедневная')", async () => {
    // Регресс на реальный баг: годовой FAO-датасет показывал
    // "D — ежедневная" (захардкоженная заглушка на фронте, убрана
    // 2026-08-14) вместо реальной "Y — годовая".
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/session/current")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null }),
        });
      }
      if (typeof url === "string" && url.includes("/target-column")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: "Price", suggested_column: "Price", available_columns: ["Year", "Price"], has_dataset: true }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              date_col: { selected: "Year", confidence: 100, candidates: [{ name: "Year", score: 1.0 }] },
              entity_col: { selected: "(нет)", confidence: 0, candidates: [] },
              frequency: { selected: "Y — годовая (начало года)", code: "YS-JAN", confidence: 100 },
            }),
        });
      }
      if (typeof url === "string" && url.includes("/upload")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ...okUploadResponse,
              columns_info: [
                { name: "Year", dtype: "int64", type_icon: "numeric", non_null: 30, nulls: 0, unique: 30 },
                { name: "Price", dtype: "float64", type_icon: "numeric", non_null: 30, nulls: 0, unique: 30 },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );
    dropFiles(screen.getByTestId("dropzone-input"), [new File(["Year,Price\n1994,65.9"], "fao.csv", { type: "text/csv" })]);

    await waitFor(() => expect(screen.getByText("Структура")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Структура"));

    await waitFor(() => {
      expect(screen.getByDisplayValue(/Y — годовая/)).toBeInTheDocument();
    });
    expect(screen.queryByDisplayValue(/D — ежедневная/)).not.toBeInTheDocument();
  });
});

// ── Зелёная подсветка пройденных остановок степпера (паттерн Моделирования) ──
//
// Фоновый долг: паттерн перенесён с вкладки «Моделирование» (эталон,
// TsAnalysisModeling) и уже применён к «Разведочному EDA» (Task EDA-2),
// «Предобработке» (Task PREPR-1) и «Валидации» (Task VALID-1); «Загрузка»
// оставалась единственной вкладкой 3-колоночного паттерна без него.
// Контракт: «Если остановка степпера пройдена и имеет зелёную галочку
// (status === "done"), кнопка остановки окрашивается в светло-зелёный цвет
// и текст становится зелёным. При других статусах кнопка не окрашивается».
// Ветка done в className степпер-кнопки: bg-green-50 border-green-200
// text-green-800; активная остановка (bg-brand text-white) сохраняет
// приоритет индиго при любом её статусе -- как в эталоне.
//
// Специфика «Загрузки»: stopStatus выдаёт ровно три статуса -- done /
// warning / pending, поэтому гарды покрывают warning и pending
// (skipped/error/running на этой вкладке недостижимы). Кейсы ниже
// покрывают всю достижимую матрицу статус x активность.
//
// Статусы при стандартном моке okUploadResponse: «Превью датасета» --
// done и активна по умолчанию, «График»/«Распределение» -- done,
// «Структура» -- done (PROGR-14-A: «(нет)» группирующей колонки --
// уверенный факт решения «колонки нет», а не сомнительная догадка
// с confidence 0%), «Качество» -- warning (cols_with_missing = 1).

async function renderUploaded(uploadResult: unknown = okUploadResponse) {
  mockFetchSequence(uploadResult);
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
  await waitFor(() => expect(screen.getByText("Превью датасета")).toBeInTheDocument());
}

describe("TsAnalysisUpload — зелёная подсветка пройденных остановок степпера (паттерн Моделирования)", () => {
  it("colors a passed (done) stop light-green and keeps a warning neighbor uncolored", async () => {
    await renderUploaded();

    // Снимаем активность с дефолтной остановки «Превью датасета» (done):
    // кликаем на «Структуру» (done, PROGR-14-A: «(нет)» -- уверенный факт).
    fireEvent.click(screen.getByRole("button", { name: /^Структура/ }));

    // Пройденная остановка (зелёная галочка) -> светло-зелёная кнопка
    // с зелёным текстом (эталон Моделирования: bg-green-50/green-200/green-800).
    const doneButton = screen.getByRole("button", { name: /^График/ });
    expect(doneButton).toHaveClass("bg-green-50", "border-green-200", "text-green-800");
    expect(doneButton).not.toHaveClass("bg-brand");
    expect(doneButton).not.toHaveClass("bg-white");

    // Не пройденная (warning) и не активная остановка -> БЕЗ окраски.
    const warningButton = screen.getByRole("button", { name: /^Качество/ });
    expect(warningButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(warningButton).not.toHaveClass("bg-green-50");
    expect(warningButton).not.toHaveClass("border-green-200");
    expect(warningButton).not.toHaveClass("text-green-800");
  });

  it("keeps the indigo active styling for an active stop even when it is done (active branch priority, as in Modeling)", async () => {
    await renderUploaded();

    // «Превью датасета» активна по умолчанию и её статус done ->
    // приоритет индиго (как в эталоне Моделирования).
    const activeDoneButton = screen.getByRole("button", { name: /^Превью датасета/ });
    expect(activeDoneButton).toHaveClass("bg-brand", "text-white", "border-brand");
    expect(activeDoneButton).not.toHaveClass("bg-green-50");
    expect(activeDoneButton).not.toHaveClass("text-green-800");
  });

  it("leaves a non-active warning stop uncolored while done stops are highlighted", async () => {
    await renderUploaded();

    // Дефолтное состояние: «Качество» -- warning (не активна) -> белая;
    // контраст: «Распределение» (done, не активна) -- зелёная.
    const warningButton = screen.getByRole("button", { name: /^Качество/ });
    expect(warningButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(warningButton).not.toHaveClass("bg-green-50");
    expect(warningButton).not.toHaveClass("border-green-200");
    expect(warningButton).not.toHaveClass("text-green-800");

    const doneButton = screen.getByRole("button", { name: /^Распределение/ });
    expect(doneButton).toHaveClass("bg-green-50", "border-green-200", "text-green-800");
  });

  it("keeps the indigo active styling for an active warning stop (no green, no white)", async () => {
    await renderUploaded();

    // «Качество» -- warning, после клика активна: активная ветка
    // приоритетна при ЛЮБОМ статусе -- индиго, без зелёной окраски.
    fireEvent.click(screen.getByRole("button", { name: /^Качество/ }));

    const activeWarningButton = screen.getByRole("button", { name: /^Качество/ });
    expect(activeWarningButton).toHaveClass("bg-brand", "text-white", "border-brand");
    expect(activeWarningButton).not.toHaveClass("bg-green-50");
    expect(activeWarningButton).not.toHaveClass("bg-white");
  });

  it("leaves a pending stop uncolored (distribution without numeric columns)", async () => {
    // Датасет без числовых колонок: stopStatus(«Распределение») --
    // pending («Не запускалось»), подсветки быть НЕ должно.
    await renderUploaded({
      ...okUploadResponse,
      columns_info: [
        { name: "date", dtype: "object", type_icon: "datetime", non_null: 10, nulls: 0, unique: 10 },
      ],
    });

    const pendingButton = screen.getByRole("button", { name: /^Распределение/ });
    expect(pendingButton).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(pendingButton).not.toHaveClass("bg-green-50");
    expect(pendingButton).not.toHaveClass("border-green-200");
    expect(pendingButton).not.toHaveClass("text-green-800");
  });
});

// ── PROGR-14-A: статус «Структуры» -- из факта решения, не raw confidence ──
//
// Дефект (замечание тимлида): entity confidence = 0% для легитимного
// «(нет)» группирующей колонки у однорядного датасета -- зелёным
// остановке не быть никогда. Формула остановки читала raw confidence
// авто-детекта как «уверенность в выборе», но «(нет)»/«(не
// использовать)» -- РЕШАЮЩИЕ выборы («колонки нет»): у автодетекта здесь
// нечему быть «неуверенным», 0% описывает отсутствие скоринга, а не
// сомнение. Контракт: решение по колонке уверенное <=> выбран явный
// маркер отсутствия ЛИБО raw confidence >= 70 (последний сохраняет смысл
// честного предупреждения о сомнительном угадывании КОНКРЕТНОЙ колонки).
//
// Классы кнопок степпера: done -> bg-green-50/border-green-200/text-green-800,
// warning -> bg-white/border-neutral-200/text-neutral-800; активная
// остановка всегда индиго (приоритет активной ветки) -- поэтому статус
// утверждается с ЧУЖОЙ активной остановкой («Качество»).
describe("TsAnalysisUpload — PROGR-14-A: статус «Структуры» из факта решения, не raw confidence", () => {
  async function renderStructureStop(detection: DetectionScenario) {
    mockFetchSequence(okUploadResponse, true, detection);
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );
    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
    await waitFor(() => expect(screen.getByText("Превью датасета")).toBeInTheDocument());
    // Открываем остановку и ждём прихода detection (карточка с селекторами)
    // -- до этого «Структура» честно pending, классы ещё не устоялись.
    fireEvent.click(screen.getByText("Структура"));
    await waitFor(() => expect(screen.getByText("Группирующая колонка")).toBeInTheDocument());
  }

  it("«(нет)» у группирующей колонки однорядного датасета -- уверенный факт: остановка done (дефект замечания тимлида)", async () => {
    await renderStructureStop({
      dateCol: { selected: "date", confidence: 95 },
      entityCol: { selected: "(нет)", confidence: 0 },
    });

    fireEvent.click(screen.getByRole("button", { name: /^Качество/ }));

    const button = screen.getByRole("button", { name: /^Структура/ });
    expect(button).toHaveClass("bg-green-50", "border-green-200", "text-green-800");
    expect(button).not.toHaveClass("bg-brand");
    expect(button).not.toHaveClass("bg-white");
  });

  it("«(не использовать)» у даты + «(нет)» у группирующей (оба 0%) -- оба решения явные: done", async () => {
    await renderStructureStop({
      dateCol: { selected: "(не использовать)", confidence: 0 },
      entityCol: { selected: "(нет)", confidence: 0 },
    });

    fireEvent.click(screen.getByRole("button", { name: /^Качество/ }));

    const button = screen.getByRole("button", { name: /^Структура/ });
    expect(button).toHaveClass("bg-green-50", "border-green-200", "text-green-800");
    expect(button).not.toHaveClass("bg-white");
  });

  it("ручной выбор «(нет)» на остановке переводит статус в done при низком raw confidence авто-детекта", async () => {
    await renderStructureStop({
      dateCol: { selected: "date", confidence: 95 },
      entityCol: { selected: "Country", confidence: 25 },
    });

    // Решение пользователя -- факт; raw confidence авто-детекта при
    // onChange НЕ пересчитывается (2026-08-14), статус -- из решения.
    fireEvent.change(screen.getByDisplayValue("Country"), { target: { value: "(нет)" } });

    fireEvent.click(screen.getByRole("button", { name: /^Качество/ }));
    const button = screen.getByRole("button", { name: /^Структура/ });
    expect(button).toHaveClass("bg-green-50", "border-green-200", "text-green-800");
    expect(button).not.toHaveClass("bg-white");
  });

  it("guard: сомнительное угадывание КОНКРЕТНОЙ колонки (confidence<70) честно остаётся warning", async () => {
    await renderStructureStop({
      dateCol: { selected: "Year", confidence: 40 },
      entityCol: { selected: "(нет)", confidence: 0 },
    });

    fireEvent.click(screen.getByRole("button", { name: /^Качество/ }));
    const button = screen.getByRole("button", { name: /^Структура/ });
    expect(button).toHaveClass("bg-white", "border-neutral-200", "text-neutral-800");
    expect(button).not.toHaveClass("bg-green-50");
    expect(button).not.toHaveClass("border-green-200");
    expect(button).not.toHaveClass("text-green-800");
  });

  it("guard: уверенные конкретные выборы обеих колонок -- done (прежнее поведение сохранено)", async () => {
    await renderStructureStop({
      dateCol: { selected: "date", confidence: 95 },
      entityCol: { selected: "Country", confidence: 85 },
    });

    fireEvent.click(screen.getByRole("button", { name: /^Качество/ }));
    const button = screen.getByRole("button", { name: /^Структура/ });
    expect(button).toHaveClass("bg-green-50", "border-green-200", "text-green-800");
  });
});

// ── PROGR-15-A: отчёт остановок «Загрузки» доходит до бэкенда ──────────
//
// Дефект (расследование PROGR-15-REPRO, причина Г-1 подтверждена
// read-only проверками): postStops строил URL через
// sessionApiUrl("/v1/progress/upload-stops"), но sessionApiUrl добавляет
// префикс /v1/session САМ -- итоговый путь был
// /v1/session/v1/progress/upload-stops, гарантированный 404 на любом
// окружении. fetch резолвится и с HTTP-ошибкой: res.ok не проверялся,
// .catch ловил только сеть -- отчёт «успешно» не доходил до единого
// движка ни разу. Панель «Прогресс» оставалась с одними бэкенд-фактами
// (upload_completed/structure_confirmed): сценарий тимлида -- в модуле
// 4 зелёных остановки + жёлтое «Качество», на панели только «Превью» и
// «Структура».
//
// Почему тесты не ловили: ни одного URL-ассерта на upload-stops; мок-
// помощник матчит fetch по подстроке "/upload", под которую попадает и
// "upload-stops" -- мусорный URL обслуживался моком как легитимный
// (коллизия снята веткой "upload-stops" до ветки "/upload").
describe("TsAnalysisUpload — PROGR-15-A: URL-контракт отчёта остановок в «Прогресс»", () => {
  function stopsCalls(): Array<[string, RequestInit?]> {
    return (global.fetch as jest.Mock).mock.calls.filter(
      ([url]: unknown[]) => typeof url === "string" && url.includes("upload-stops"),
    ) as Array<[string, RequestInit?]>;
  }

  function renderAndUpload() {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );
    dropFiles(screen.getByTestId("dropzone-input"), [new File(["a,b\n1,2"], "test.csv", { type: "text/csv" })]);
    return waitFor(() => expect(screen.getByText("Превью датасета")).toBeInTheDocument());
  }

  it("отчёт уходит ровно на progressApiUrl(\"/upload-stops\") -- без двойного префикса /v1/session", async () => {
    mockFetchSequence(okUploadResponse);
    await renderAndUpload();

    await waitFor(() => expect(stopsCalls().length).toBeGreaterThan(0));

    for (const [url] of stopsCalls()) {
      expect(url).toBe(progressApiUrl("/upload-stops"));
      expect(url).not.toContain("/v1/session/");
    }
  });

  it("HTTP-неудача отчёта (!ok) не блокирует последующие: смена решения структуры репортит новый снапшот", async () => {
    // Первый отчёт принят с ошибкой (ok:false), дальнейшие -- успехом.
    // Сценарий структуры warning: сомнительное угадывание Country (25%).
    mockFetchSequence(
      okUploadResponse,
      true,
      {
        dateCol: { selected: "date", confidence: 95 },
        entityCol: { selected: "Country", confidence: 25 },
      },
      [false, true],
    );
    await renderAndUpload();

    // Штатные отчёты загрузки идут до user-действия (pending/warning-
    // снапшоты); первое отправление -- неудачное (ok:false).
    await waitFor(() => expect(stopsCalls().length).toBeGreaterThanOrEqual(1));

    // Открываем остановку «Структура» и меняем решение пользователя:
    // warning -> done -- новый снапшот, контур обязан повторить отчёт
    // несмотря на неудачу первого отправления.
    fireEvent.click(screen.getByText("Структура"));
    await waitFor(() => expect(screen.getByText("Группирующая колонка")).toBeInTheDocument());
    fireEvent.change(screen.getByDisplayValue("Country"), { target: { value: "(нет)" } });

    // Последний отчёт -- уже новый снапшот (structure=done в теле POST),
    // причём по правильному URL: неудача не «заморозила» контур.
    await waitFor(() => {
      const last = stopsCalls()[stopsCalls().length - 1];
      expect(String(last?.[1]?.body ?? "")).toContain('"structure":"done"');
    });
    expect(stopsCalls().length).toBeGreaterThanOrEqual(2);
    for (const [url] of stopsCalls()) {
      expect(url).toBe(progressApiUrl("/upload-stops"));
    }
  });
});
