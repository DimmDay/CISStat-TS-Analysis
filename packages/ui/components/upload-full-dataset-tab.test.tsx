// packages/ui/components/upload-full-dataset-tab.test.tsx
//
// Задача UI-UPLOAD-FULL-1 (2026-10-14, постановка тимлида), пункт 2:
// окно «Обзор», остановка «Превью датасета» -- под 4 бейджами метрик
// есть вкладки. Добавляем третью вкладку просмотра ВСЕГО датасета:
//
//   1. Превью        -- как было (head/tail, не трогаем);
//   2. Типы колонок  -- как было (columns_info, не трогаем);
//   3. Весь датасет  -- НОВОЕ: аналитик прокручивает весь датасет от
//      начала до конца, справа работает ползунок (native scrollbar
//      контейнера охватывает ВСЕ строки: виртуализация по позиции
//      прокрутки, страницы строк догружаются с бэкенда
//      GET /v1/session/dataset/rows?offset=&limit=).
//
// Поведенческие оракулы на СВОИХ данных (дизъюнкт с TsAnalysisUpload
// .test.tsx / upload-module-help / upload-column-headers-unified /
// upload-help-button-alignment): свой файл full-scroll-check.csv, свои
// колонки tstamp/reading, свой dataset_id, свой корпус 550 строк в
// моке /dataset/rows (3 страницы по 200).

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisUpload } from "./TsAnalysisUpload";
import { AppShellProvider } from "../context/AppShellContext";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

// Polyfill: ResizeObserver нужен Recharts ResponsiveContainer.
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ── СВОЙ корпус данных (дизъюнкт с существующими тестами) ────────────

const FULL_TOTAL = 550;
const FULL_PAGE = 200;

// Детерминированный генератор строк корпуса: tstamp = i-й день от
// 2024-01-01, reading = 1000 + i. Прокрутка к строке i должна показать
// reading = String(1000 + i) -- честная сквозная проверка окна.
function isoDay(i: number): string {
  const ms = Date.UTC(2024, 0, 1) + i * 86400000;
  return new Date(ms).toISOString().slice(0, 10);
}

function rowsPage(url: string) {
  const u = new URL(url, "http://localhost");
  const offset = Number(u.searchParams.get("offset") ?? "0");
  const limit = Number(u.searchParams.get("limit") ?? String(FULL_PAGE));
  const rows = Array.from({ length: Math.max(0, Math.min(limit, FULL_TOTAL - offset)) }, (_, k) => {
    const i = offset + k;
    return [isoDay(i), String(1000 + i)];
  });
  return {
    columns: ["tstamp", "reading"],
    rows,
    offset,
    limit,
    total_rows: FULL_TOTAL,
    returned: rows.length,
    has_more: offset + rows.length < FULL_TOTAL,
  };
}

const fullUploadResponse = {
  dataset_id: "full-scroll-1",
  name: "full-scroll-check.csv",
  rows: FULL_TOTAL,
  columns: 2,
  size_label: "0.05 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["tstamp", "reading"],
      [isoDay(0), "1000"],
      [isoDay(1), "1001"],
    ],
    tail: [[isoDay(FULL_TOTAL - 2), String(1000 + FULL_TOTAL - 2)], [isoDay(FULL_TOTAL - 1), String(999 + FULL_TOTAL)]],
  },
  columns_info: [
    { name: "tstamp", dtype: "object", type_icon: "datetime", non_null: FULL_TOTAL, nulls: 0, unique: FULL_TOTAL },
    { name: "reading", dtype: "int64", type_icon: "numeric", non_null: FULL_TOTAL, nulls: 0, unique: FULL_TOTAL },
  ],
  quality: {
    cols_with_missing: 0,
    cols_with_outliers: 0,
    rows_total: FULL_TOTAL,
    duplicates: 0,
    missing_cols: [] as string[],
    outlier_cols: [] as string[],
  },
};

const fullStatsResponse = {
  columns: [
    {
      name: "reading",
      non_null_count: FULL_TOTAL,
      stats: {
        mean: 1274.5,
        median: 1274.5,
        std: 158.8,
        skewness: 0,
        kurtosis: -1.2,
        q1: 1137,
        q3: 1412,
        iqr: 275,
        distribution_hint: "Плосковершинное",
      },
    },
  ],
  min_non_null_for_stats: 2,
};

const fullDetection = {
  date_col: {
    selected: "tstamp",
    confidence: 93,
    candidates: [{ name: "tstamp", score: 0.93 }],
  },
  entity_col: {
    selected: "(нет)",
    confidence: 0,
    candidates: [{ name: "tstamp", score: 0.0 }],
  },
};

type FetchMock = jest.Mock;

/** Мок fetch; failRows -- «сломать» /dataset/rows (оракул ошибки+retry). */
function mockFullFetch(opts: { failRows?: boolean } = {}): FetchMock {
  const fn = jest.fn((url: string) => {
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
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            target_column: "reading",
            suggested_column: "reading",
            available_columns: ["reading"],
            has_dataset: true,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/rows")) {
      if (opts.failRows) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "boom" }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(url)) });
    }
    if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(fullDetection) });
    }
    if (typeof url === "string" && url.includes("/dataset/stats")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(fullStatsResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/distribution")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            column: "reading",
            non_null_count: FULL_TOTAL,
            min: 1000,
            max: 1549,
            scatter: Array.from({ length: 10 }, (_, i) => ({ x: i, y: 1000 + i * 5 })),
            scatter_sampled: false,
            scatter_sampling_method: null,
            scatter_original_count: FULL_TOTAL,
            histogram: [
              { x0: 1000, x1: 1275, count: 275 },
              { x0: 1275, x1: 1549, count: 275 },
            ],
            kde: Array.from({ length: 4 }, (_, i) => ({ x: 1000 + i * 180, y: 0.002 * (i + 1) })),
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/timeseries")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            column: "reading",
            date_column: "tstamp",
            points: Array.from({ length: 10 }, (_, i) => ({ x: isoDay(i * 50), y: 1000 + i * 50 })),
            sampled: true,
            sampling_method: "lttb",
            original_count: FULL_TOTAL,
            was_resorted: false,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/decomposition")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }
    if (typeof url === "string" && url.includes("/dataset/panel-balance")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ balanced: false, n_entities: 0, n_distinct_date_sets: 0 }),
      });
    }
    if (typeof url === "string" && url.includes("upload-stops")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reported: 5, run_id: null }) });
    }
    if (typeof url === "string" && url.includes("/upload")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(fullUploadResponse) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as FetchMock;
  global.fetch = fn as unknown as typeof fetch;
  return fn;
}

// ── Хелперы рендера ──────────────────────────────────────────────────

function dropFullFile() {
  const file = new File(["tstamp,reading\n2024-01-01,1000"], "full-scroll-check.csv", { type: "text/csv" });
  fireEvent.drop(screen.getByTestId("dropzone-input"), {
    dataTransfer: {
      files: [file],
      items: [{ kind: "file", type: file.type, getAsFile: () => file }],
      types: ["Files"],
    },
  });
}

async function renderUploaded(fetchMock?: FetchMock) {
  const fm = fetchMock ?? mockFullFetch();
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropFullFile();
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Загрузка", level: 2 })).toBeInTheDocument();
  });
  return fm;
}

function tabButton(name: string | RegExp): HTMLElement {
  return screen.getByRole("button", { name });
}

function openFullTab() {
  fireEvent.click(tabButton(/Весь датасет/));
}

function fullContainer(): HTMLElement {
  return screen.getByTestId("full-scroll-container");
}

/** Прокрутка контейнера «Весь датасет» к строке i (ROW_H = 32px). */
function scrollToRow(row: number) {
  const el = fullContainer();
  Object.defineProperty(el, "scrollTop", { value: row * 32, configurable: true });
  fireEvent.scroll(el);
}

function callsTo(mock: FetchMock, substr: string): string[] {
  return mock.mock.calls.map((c) => String(c[0])).filter((u) => u.includes(substr));
}

// ── Оракулы ──────────────────────────────────────────────────────────

describe("Вкладки остановки «Превью датасета» -- Превью / Типы колонок / Весь датасет", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("под 4 бейджами есть три вкладки, третья -- «Весь датасет»", async () => {
    await renderUploaded();

    // Точные имена вкладок (regex /Превью/ задел бы и кнопку степпера
    // «Превью датасета ...» левой колонки).
    expect(tabButton("Превью")).toBeInTheDocument();
    expect(tabButton("Типы колонок")).toBeInTheDocument();
    expect(tabButton("Весь датасет")).toBeInTheDocument();
  });

  it("дефолт -- вкладка «Превью» (head/tail), её поведение не изменилось", async () => {
    await renderUploaded();

    // Содержимое превью -- строки head корпуса (включая шапку колонок).
    expect(screen.getByText("tstamp")).toBeInTheDocument();
    expect(screen.getByText(String(1000 + FULL_TOTAL - 1))).toBeInTheDocument(); // последняя строка tail
    // Панель «Весь датасет» не показана до явного выбора вкладки.
    expect(screen.queryByTestId("full-scroll-container")).not.toBeInTheDocument();
  });

  it("вкладка «Типы колонок» не изменилась: таблица dtype/non-null/пропуски/уникальные", async () => {
    await renderUploaded();

    fireEvent.click(tabButton("Типы колонок"));
    expect(screen.getByText("int64")).toBeInTheDocument();
    expect(screen.getByText("Пропуски")).toBeInTheDocument();
    expect(screen.queryByTestId("full-scroll-container")).not.toBeInTheDocument();
  });
});

describe("Вкладка «Весь датасет» -- прокрутка всего датасета, ползунок справа", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("открытие вкладки: страница 0 с бэкенда (offset=0&limit=200), шапка колонок корпуса, первая строка, честный итог «из 550»", async () => {
    const fm = await renderUploaded();

    openFullTab();

    await waitFor(() => {
      expect(callsTo(fm, "/dataset/rows?offset=0").length).toBeGreaterThan(0);
    });
    // Параметры пагинации первой страницы.
    expect(callsTo(fm, "/dataset/rows?offset=0&limit=200").length).toBeGreaterThan(0);

    // Шапка -- колонки корпуса из ответа эндпоинта (обе: tstamp и reading).
    await waitFor(() => {
      expect(screen.getByTestId("full-scroll-container")).toBeInTheDocument();
    });
    const headerZone = screen.getByTestId("full-rows-header");
    expect(headerZone).toHaveTextContent("tstamp");
    expect(headerZone).toHaveTextContent("reading");

    // Первая строка корпуса видима (окно с начала).
    expect(screen.getByText("1000")).toBeInTheDocument();

    // Честный итог по ВСЕМУ датасету (не только по загруженной странице).
    expect(screen.getByTestId("full-rows-footer").textContent).toMatch(/из 550/);
  });

  it("прокрутка ползунком к строке 250 догружает страницу offset=200 и показывает её строки", async () => {
    const fm = await renderUploaded();

    openFullTab();
    await waitFor(() => {
      expect(screen.getByTestId("full-scroll-container")).toBeInTheDocument();
    });

    scrollToRow(250);
    await waitFor(() => {
      expect(callsTo(fm, "/dataset/rows?offset=200&limit=200").length).toBeGreaterThan(0);
    });

    // Строка 250 корпуса (reading = 1250) отрисована в окне прокрутки.
    await waitFor(() => {
      expect(screen.getByText("1250")).toBeInTheDocument();
    });
  });

  it("ползунок охватывает весь датасет: прокрутка к КОНЦУ (строка 549) показывает последнюю строку корпуса", async () => {
    const fm = await renderUploaded();

    openFullTab();
    await waitFor(() => {
      expect(screen.getByTestId("full-scroll-container")).toBeInTheDocument();
    });

    scrollToRow(549);
    await waitFor(() => {
      expect(screen.getByText(String(1000 + 549))).toBeInTheDocument();
    });
    // Высота прокручиваемого содержимого = шапка + ВСЕ строки корпуса:
    // 36 + 550*32 = 17636px -- ползунок размечен на весь датасет.
    const spacer = screen.getByTestId("full-rows-spacer");
    expect(spacer.style.height).toBe("17636px");
  });

  it("возврат на «Превью» и обратно НЕ перезапрашивает уже загруженные страницы (кэш страниц)", async () => {
    const fm = await renderUploaded();

    openFullTab();
    await waitFor(() => {
      expect(screen.getByTestId("full-scroll-container")).toBeInTheDocument();
    });
    const firstPageCalls = callsTo(fm, "/dataset/rows?offset=0&limit=200").length;
    expect(firstPageCalls).toBeGreaterThan(0);

    fireEvent.click(tabButton("Превью"));
    expect(screen.queryByTestId("full-scroll-container")).not.toBeInTheDocument();

    openFullTab();
    await waitFor(() => {
      expect(screen.getByTestId("full-scroll-container")).toBeInTheDocument();
    });
    expect(callsTo(fm, "/dataset/rows?offset=0&limit=200").length).toBe(firstPageCalls);
  });

  it("ошибка загрузки строк -- честный инлайн-статус с «Повторить»; повтор восстанавливает таблицу", async () => {
    const fm = await renderUploaded(mockFullFetch({ failRows: true }));

    openFullTab();
    await waitFor(() => {
      expect(screen.getByTestId("full-rows-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("full-rows-retry")).toBeInTheDocument();
    expect(screen.queryByTestId("full-scroll-container")).not.toBeInTheDocument();

    // «Чиним» бэкенд: убираем флаг ошибки и мокаем /dataset/rows заново,
    // остальные маршруты -- тот же фолбэк, что и в исходном моке.
    fm.mockImplementation(function retryable(url: string) {
      if (typeof url === "string" && url.includes("/dataset/rows")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(url)) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    fireEvent.click(screen.getByTestId("full-rows-retry"));
    await waitFor(() => {
      expect(screen.getByTestId("full-scroll-container")).toBeInTheDocument();
    });
    expect(screen.getByText("1000")).toBeInTheDocument();
  });
});
