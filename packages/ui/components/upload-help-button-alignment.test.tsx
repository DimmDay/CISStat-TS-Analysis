// packages/ui/components/upload-help-button-alignment.test.tsx
//
// Задача UI-UPLOAD-FULL-1 (2026-10-14, постановка тимлида), пункт 1:
// кнопка «Справка» у заголовка колонки «Загрузка» должна быть
// ОТЦЕНТРОВАНА ПО ПРАВОМУ КРАЮ колонки -- по паттерну вкладки
// «Валидация» (Data Quality -> Справка, TsAnalysisValidation.tsx).
//
// Паттерн «Валидации»: строка заголовка `flex items-center justify-between`
// -- заголовок прижат влево, кнопка «Справка» прижата к ПРАВОМУ краю
// колонки (w-60), вертикально отцентрована по строке заголовка.
//
// В «Загрузке» строка заголовка содержит три элемента
// [иконка, h2, кнопка] (UI-UPLOAD-HELP-1), поэтому прямой
// justify-between раскидал бы ВСЕ три элемента по ширине. Правый край
// достигается эквивалентной семантикой распределения: заголовок h2
// растягивается на всё свободное пространство (flex-1, min-w-0 -- та же
// защита от переполнения узкой колонки), кнопка shrink-0 остаётся
// последним элементом строки -- т.е. прижата к правому краю колонки,
// как в «Валидации». Вертикальная центровка -- items-center строки.
//
// jsdom не считает layout, поэтому инвариант «кнопка у правого края»
// пинится СТРУКТУРНО (установленная практика репозитория -- см.
// upload-column-headers-unified.test.tsx): (a) h2 -- flex-1 + min-w-0;
// (b) кнопка -- последний элемент строки заголовка; (c) кнопка shrink-0;
// (d) строка flex items-center (вертикальная центровка паттерна).
//
// Оракулы построены на СВОИХ данных (дизъюнкт с TsAnalysisUpload.test.tsx,
// upload-module-help.test.tsx, upload-column-headers-unified.test.tsx):
// свой файл help-align-check.csv, свои колонки obs_date/measure, свой
// dataset_id.

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

const alignUploadResponse = {
  dataset_id: "help-align-1",
  name: "help-align-check.csv",
  rows: 8,
  columns: 2,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["obs_date", "measure"],
      ["2026-03-01", "50"],
      ["2026-03-02", "55"],
    ],
    tail: [["2026-03-07", "61"], ["2026-03-08", "64"]],
  },
  columns_info: [
    { name: "obs_date", dtype: "object", type_icon: "datetime", non_null: 8, nulls: 0, unique: 8 },
    { name: "measure", dtype: "float64", type_icon: "numeric", non_null: 8, nulls: 0, unique: 8 },
  ],
  quality: {
    cols_with_missing: 0,
    cols_with_outliers: 0,
    rows_total: 8,
    duplicates: 0,
    missing_cols: [] as string[],
    outlier_cols: [] as string[],
  },
};

const alignStatsResponse = {
  columns: [
    {
      name: "measure",
      non_null_count: 8,
      stats: {
        mean: 57,
        median: 57,
        std: 4.5,
        skewness: 0.1,
        kurtosis: -1.2,
        q1: 54,
        q3: 60,
        iqr: 6,
        distribution_hint: "Близко к нормальному",
      },
    },
  ],
  min_non_null_for_stats: 2,
};

const alignDetection = {
  date_col: {
    selected: "obs_date",
    confidence: 91,
    candidates: [{ name: "obs_date", score: 0.91 }],
  },
  entity_col: {
    selected: "(нет)",
    confidence: 0,
    candidates: [{ name: "obs_date", score: 0.0 }],
  },
};

function mockAlignFetch() {
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
            target_column: "measure",
            suggested_column: "measure",
            available_columns: ["measure"],
            has_dataset: true,
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/structure-detection")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(alignDetection) });
    }
    if (typeof url === "string" && url.includes("/dataset/stats")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(alignStatsResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/distribution")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            column: "measure",
            non_null_count: 8,
            min: 50,
            max: 64,
            scatter: Array.from({ length: 8 }, (_, i) => ({ x: i, y: 50 + i * 2 })),
            scatter_sampled: false,
            scatter_sampling_method: null,
            scatter_original_count: 8,
            histogram: [
              { x0: 50, x1: 57, count: 4 },
              { x0: 57, x1: 64, count: 4 },
            ],
            kde: Array.from({ length: 4 }, (_, i) => ({ x: 50 + i * 5, y: 0.02 * (i + 1) })),
          }),
      });
    }
    if (typeof url === "string" && url.includes("/dataset/timeseries")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            column: "measure",
            date_column: "obs_date",
            points: Array.from({ length: 8 }, (_, i) => ({
              x: `2026-03-${String(i + 1).padStart(2, "0")}`,
              y: 50 + i * 2,
            })),
            sampled: false,
            sampling_method: null,
            original_count: 8,
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
      return Promise.resolve({ ok: true, json: () => Promise.resolve(alignUploadResponse) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as jest.Mock;
}

// ── Хелперы рендера ──────────────────────────────────────────────────

function dropAlignFile() {
  const file = new File(["obs_date,measure\n2026-03-01,50"], "help-align-check.csv", { type: "text/csv" });
  fireEvent.drop(screen.getByTestId("dropzone-input"), {
    dataTransfer: {
      files: [file],
      items: [{ kind: "file", type: file.type, getAsFile: () => file }],
      types: ["Files"],
    },
  });
}

async function renderUploaded() {
  mockAlignFetch();
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );
  dropAlignFile();
  await waitFor(() => {
    expect(screen.getByRole("heading", { name: "Загрузка", level: 2 })).toBeInTheDocument();
  });
}

// ── Оракулы ──────────────────────────────────────────────────────────

describe("Кнопка «Справка» заголовка «Загрузка» -- правый край колонки (паттерн «Валидации»)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("h2 «Загрузка» -- flex-1 + min-w-0: заголовок занимает всё свободное место строки, кнопка прижата к правому краю колонки", async () => {
    await renderUploaded();

    const hUpload = screen.getByRole("heading", { name: "Загрузка", level: 2 });
    // flex-1 -- эквивалент распределения justify-between из «Валидации»
    // для строки из трёх элементов [иконка, h2, кнопка].
    expect(hUpload.className).toContain("flex-1");
    // Защита узкой колонки сохранена (truncate не работает без min-w-0).
    expect(hUpload.className).toContain("min-w-0");
    expect(hUpload.className).toContain("truncate");
  });

  it("кнопка «Справка» -- последний элемент строки заголовка (правый край) и shrink-0", async () => {
    await renderUploaded();

    const hUpload = screen.getByRole("heading", { name: "Загрузка", level: 2 });
    const row = hUpload.parentElement!;
    // Состав строки: [иконка, h2, кнопка] -- кнопка последняя, т.е. у
    // правого края колонки (та же семантика, что «кнопка справа»
    // justify-between в «Валидации»).
    expect(row.children).toHaveLength(3);
    const last = row.children[2] as HTMLElement;
    expect(last.tagName).toBe("BUTTON");
    expect(last.textContent).toBe("Справка");
    // shrink-0: кнопка не сжимается -- правый край детерминирован.
    expect(last.className).toContain("shrink-0");
  });

  it("строка заголовка -- flex items-center (вертикальная центровка паттерна «Валидации»), gap-2 сохранён", async () => {
    await renderUploaded();

    const hUpload = screen.getByRole("heading", { name: "Загрузка", level: 2 });
    const row = hUpload.parentElement!;
    expect(row.className).toContain("flex");
    expect(row.className).toContain("items-center");
    expect(row.className).toContain("gap-2");
  });

  it("активное состояние кнопки (открытая Справка) не меняет выравнивание", async () => {
    await renderUploaded();

    const hUpload = screen.getByRole("heading", { name: "Загрузка", level: 2 });
    const row = hUpload.parentElement!;
    const btn = within(row).getByRole("button", { name: "Справка" });

    fireEvent.click(btn);
    // Кнопка в активном состоянии (индиго) -- и по-прежнему последний
    // элемент строки (правый край) с shrink-0.
    expect(btn.className).toContain("text-white");
    expect(row.children[row.children.length - 1]).toBe(btn);
    expect(btn.className).toContain("shrink-0");
    expect(hUpload.className).toContain("flex-1");
  });
});
