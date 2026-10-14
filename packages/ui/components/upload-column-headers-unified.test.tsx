// packages/ui/components/upload-column-headers-unified.test.tsx
//
// Задача (2026-10-14, постановка тимлида): привести заголовки колонок
// 3-колоночного layout вкладки «Загрузка» (1. «Загрузка», 2. «Описание»,
// 3. «Файл» / «Зачем это здесь» / «Подтверждение» / «Что дальше») к единому
// виду:
//   1) размер шрифта -- как у заголовка «Загрузка» (text-lg, 18px);
//      до задачи «Описание»/«Файл» и переменные заголовки правой колонки
//      рендерились дефолтным text-base (16px) -- рассогласование 2px;
//   2) выравнивание заголовков по нижней горизонтали: строка заголовка --
//      первая ветка КАЖДОЙ колонки (никаких вертикальных офсетов вроде
//      pt-1 на левой колонке), высоты строк детерминированы одинаково
//      (text-lg line box 28px, items-center, иконка 16px) -- низы текстов
//      лежат на одной горизонтали;
//   3) структурный паттерн -- заголовки секции «Примеры прикладных задач»
//      страницы «Знакомство с платформой» (AppliedTasksNavigator): строка
//      flex items-center gap-2 + lucide-иконка (size 16, text-brand,
//      aria-hidden) + заголовок font-semibold text-neutral-800.
//
// UI-UPLOAD-HELP-1 (2026-10-14, постановка тимлида): в строку заголовка
// колонки «Загрузка» добавлена кнопка «Справка» (паттерн «Валидации»):
// строка левой колонки теперь [иконка, h2, кнопка]. Геометрия выравнивания
// не страдает: кнопка text-xs px-2 py-1 (line box 24px < 28px заголовка)
// с shrink-0 -- высота строки детерминирована line box заголовка text-lg
// (28px), низы заголовков трёх колонок остаются на одной горизонтали.
// Контракт кнопки пинится здесь (структурно) и поведенчески -- в
// upload-module-help.test.tsx.
//
// Оракулы построены на СВОИХ данных (дизъюнкт с TsAnalysisUpload.test.tsx):
// свой файл headers-unified-check.csv, свои колонки ts_idx/signal_num,
// свой dataset_id. Контракт пинится на уровне структурных классов --
// детерминированного источника геометрии (jsdom не считает layout:
// инвариант «низ на одной горизонтали» выражен структурой «строка --
// первая ветка колонки + одинаковый line box всех заголовков»).

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisUpload } from "./TsAnalysisUpload";
import { AppShellProvider } from "../context/AppShellContext";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

// Polyfill: ResizeObserver нужен Recharts ResponsiveContainer (тот же
// паттерн, что и в TsAnalysisUpload.test.tsx).
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// ── СВОЙ корпус данных (дизъюнкт с существующими тестами) ────────────

const hdrUploadResponse = {
  dataset_id: "hdr-check-1",
  name: "headers-unified-check.csv",
  rows: 12,
  columns: 2,
  size_label: "0.02 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["ts_idx", "signal_num"],
      ["2025-01-01", "7"],
      ["2025-01-02", "11"],
    ],
    tail: [["2025-01-11", "9"], ["2025-01-12", "14"]],
  },
  columns_info: [
    { name: "ts_idx", dtype: "object", type_icon: "datetime", non_null: 12, nulls: 0, unique: 12 },
    { name: "signal_num", dtype: "int64", type_icon: "numeric", non_null: 12, nulls: 0, unique: 12 },
  ],
  quality: {
    cols_with_missing: 0,
    cols_with_outliers: 0,
    rows_total: 12,
    duplicates: 0,
    missing_cols: [] as string[],
    outlier_cols: [] as string[],
  },
};

const hdrStatsResponse = {
  columns: [
    {
      name: "signal_num",
      non_null_count: 12,
      stats: {
        mean: 10.5,
        median: 10,
        std: 2.5,
        skewness: 0.2,
        kurtosis: -1.0,
        q1: 9,
        q3: 12,
        iqr: 3,
        distribution_hint: "Близко к нормальному",
      },
    },
  ],
  min_non_null_for_stats: 2,
};

const hdrDetection = {
  date_col: {
    selected: "ts_idx",
    confidence: 90,
    candidates: [{ name: "ts_idx", score: 0.9 }],
  },
  entity_col: {
    selected: "(нет)",
    confidence: 0,
    candidates: [{ name: "ts_idx", score: 0.0 }],
  },
};

function mockHdrFetch() {
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
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            target_column: "signal_num",
            suggested_column: "signal_num",
            available_columns: ["signal_num"],
            has_dataset: true,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(hdrDetection) });
    }
    if (typeof url === "string" && url.includes("/dataset/stats")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(hdrStatsResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/distribution")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            column: "signal_num",
            non_null_count: 12,
            min: 5,
            max: 16,
            scatter: Array.from({ length: 12 }, (_, i) => ({ x: i, y: 5 + i })),
            scatter_sampled: false,
            scatter_sampling_method: null,
            scatter_original_count: 12,
            histogram: [
              { x0: 5, x1: 10, count: 6 },
              { x0: 10, x1: 16, count: 6 },
            ],
            kde: Array.from({ length: 5 }, (_, i) => ({ x: 5 + i * 3, y: 0.02 * (i + 1) })),
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/timeseries")) {
      // Остановка «График» рендерит TimeSeriesLineChart -- без точек
      // компонент честно падает на data.points (своя форма ответа,
      // TimeSeriesChartData: points {x: ISO-дата, y: number}).
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            column: "signal_num",
            date_column: "ts_idx",
            points: Array.from({ length: 12 }, (_, i) => ({
              x: `2025-01-${String(i + 1).padStart(2, "0")}`,
              y: 5 + i,
            })),
            sampled: false,
            sampling_method: null,
            original_count: 12,
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
      return Promise.resolve({ ok: true, json: () => Promise.resolve(hdrUploadResponse) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as jest.Mock;
}

// ── Хелперы рендера и контракта ──────────────────────────────────────

function dropHdrFile() {
  const file = new File(["ts_idx,signal_num\n2025-01-01,7"], "headers-unified-check.csv", { type: "text/csv" });
  fireEvent.drop(screen.getByTestId("dropzone-input"), {
    dataTransfer: {
      files: [file],
      items: [{ kind: "file", type: file.type, getAsFile: () => file }],
      types: ["Files"],
    },
  });
}

async function renderUploaded() {
  mockHdrFetch();
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropHdrFile();
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Загрузка", level: 2 })).toBeInTheDocument();
  });
}

// Контракт единого вида заголовка колонки:
//   (a) типографика «Загрузка»: text-lg (18px) + font-semibold + neutral-800;
//   (b) строка-паттерн «Примеров прикладных задач»: flex items-center gap-2;
//   (c) иконка паттерна: aria-hidden svg с фирменным индиго (text-brand);
//   (d) состав строки: у колонок «Описание»/«Файл» и переменных заголовков
//       правой колонки -- ровно [иконка, заголовок]; у колонки «Загрузка»
//       (UI-UPLOAD-HELP-1) -- [иконка, заголовок, кнопка «Справка»]
//       (shrink-0, вне потока выравнивания: высота строки определяется
//       line box заголовка text-lg = 28px).
function expectUnifiedHeaderContract(header: HTMLElement, opts: { withHelpButton?: boolean } = {}) {
  // (a) Единый размер шрифта -- как у заголовка «Загрузка».
  expect(header.className).toContain("text-lg");
  expect(header.className).toContain("font-semibold");
  // Единый цвет заголовков -- фирменный neutral-800 («Загрузка» до задачи
  // был единственным rgb(38,38,38); остальные наследовали чёрный).
  expect(header.className).toContain("text-neutral-800");

  // (b) Паттерн AppliedTasksNavigator: строка flex items-center gap-2.
  const row = header.parentElement;
  expect(row).toBeTruthy();
  expect(row!.className).toContain("flex");
  expect(row!.className).toContain("items-center");
  expect(row!.className).toContain("gap-2");

  // (c) Иконка паттерна: aria-hidden, фирменный индиго.
  const icon = row!.querySelector("svg");
  expect(icon).toBeTruthy();
  expect(icon).toHaveAttribute("aria-hidden", "true");
  expect(icon!.getAttribute("class")).toContain("text-brand");

  // (d) Состав строки: иконка + заголовок (+ кнопка «Справка» только у
  // левой колонки -- UI-UPLOAD-HELP-1, паттерн «Валидации»).
  if (opts.withHelpButton) {
    expect(row!.children).toHaveLength(3);
    const helpButton = row!.children[2] as HTMLElement;
    expect(helpButton.tagName).toBe("BUTTON");
    expect(helpButton.textContent).toBe("Справка");
    // shrink-0: кнопка не сжимает заголовок и не меняет высоту строки.
    expect(helpButton.className).toContain("shrink-0");
  } else {
    expect(row!.children).toHaveLength(2);
  }
}

// Инвариант «низ заголовков на одной горизонтали» в структурной форме:
// строка заголовка -- первая ветка своей колонки (спуск по первым
// элементам-детям от корня колонки приводит ровно в неё). При одинаковой
// высоте строк ((d) выше) и старте всех колонок с одной y -- низы совпадают.
function expectHeaderRowAtColumnTop(header: HTMLElement) {
  const container = header.closest("aside, section");
  expect(container).toBeTruthy();
  const row = header.parentElement!;
  let node: Element = container!;
  while (node !== row) {
    const next = node.firstElementChild;
    expect(next).toBeTruthy();
    node = next!;
  }
  expect(node).toBe(row);
}

// ── Оракулы ──────────────────────────────────────────────────────────

describe("Заголовки колонок «Загрузки» -- единый вид (паттерн «Примеров прикладных задач»)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("стартовые заголовки трёх колонок («Загрузка», «Описание», «Файл») -- единая типографика text-lg и строка-паттерн с иконкой", async () => {
    await renderUploaded();

    const hUpload = screen.getByRole("heading", { name: "Загрузка", level: 2 });
    const hDesc = screen.getByRole("heading", { name: "Описание", level: 3 });
    const hFile = screen.getByRole("heading", { name: "Файл", level: 3 });

    expectUnifiedHeaderContract(hUpload, { withHelpButton: true });
    expectHeaderRowAtColumnTop(hUpload);
    for (const h of [hDesc, hFile]) {
      expectUnifiedHeaderContract(h);
      expectHeaderRowAtColumnTop(h);
    }

    // Заголовок «Загрузка» сохраняет защиту от переполнения узкой колонки.
    expect(hUpload.className).toContain("truncate");
  });

  it("переменные заголовки правой колонки («Зачем это здесь» ×2, «Подтверждение», «Что дальше») -- тот же контракт на каждой остановке", async () => {
    await renderUploaded();

    const leftAside = screen.getByRole("heading", { name: "Загрузка", level: 2 }).closest("aside")!;
    const stopsToHeaders: Array<[string, string]> = [
      ["График", "Зачем это здесь"],
      ["Распределение", "Зачем это здесь"],
      ["Структура", "Подтверждение"],
      ["Качество", "Что дальше"],
    ];

    for (const [stopLabel, headerName] of stopsToHeaders) {
      // Имя кнопки степпера = метка + статус иконки («График Пройдено»)
      // -- матчим от начала имени.
      fireEvent.click(within(leftAside).getByRole("button", { name: new RegExp(`^${stopLabel}`) }));
      const header = await screen.findByRole("heading", { name: headerName, level: 3 });
      expectUnifiedHeaderContract(header);
      expectHeaderRowAtColumnTop(header);
    }
  });

  it("выравнивание по нижней горизонтали: офсет pt-1 левой колонки убран, подпись «Проверка и структура датасета» сохранена под заголовком", async () => {
    await renderUploaded();

    const leftAside = screen.getByRole("heading", { name: "Загрузка", level: 2 }).closest("aside")!;
    // pt-1 сдвигал «Загрузку» на 4px вниз -- низ заголовка уходил с общей
    // горизонтали; контракт: вертикальных офсетов у колонки нет.
    expect(leftAside.className).not.toContain("pt-");

    // Подпись под заголовком левой колонки -- не заголовок, контракт её
    // не трогает (остаётся в колонке под строкой заголовка).
    expect(
      within(leftAside).getByText("Проверка и структура датасета")
    ).toBeInTheDocument();
  });
});
