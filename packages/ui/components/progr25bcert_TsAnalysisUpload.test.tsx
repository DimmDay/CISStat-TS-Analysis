// packages/ui/components/progr25bcert_TsAnalysisUpload.test.tsx
//
// СЕРТИФИКАЦИОННЫЕ ОРАКУЛЫ задачи PROGR-25-B (PROGR-25-B-CERT, независимый
// аудит селектора Загрузки). Сюит НЕ копирует repo-тесты задачи
// (TsAnalysisUpload.test.tsx): свои датасеты, свои сценарии, свои
// последовательности ответов.
//
// Ключевой приём независимости: свой upload-ответ несёт колонки
// ts (datetime) / price (numeric) / load (numeric) -- первая числовая
// ПО ПОРЯДКУ ДАТАФРЕЙМА это "price", а рекомендация бэкенда
// (suggested_column) -- "load". Селектор обязан показать "load":
// это отличает ОТОБРАЖЕНИЕ РЕКОМЕНДАЦИИ (PROGR-25-B) от старого
// фолбэка «первая числовая» и от персистенции (авто-POST снят, R1).
//
// Контракты (спека §4-B, план §2):
//   CERT-U1/U2 -- рекомендация отображается, НИ ОДНОГО POST (R1);
//   CERT-U3    -- бейдж авто-происхождения только при факте source=auto;
//   CERT-U4    -- честный текст toast о сбросе («рекомендация:», не
//                 «выбран» -- фиксации хук не делает);
//   CERT-U5    -- фиксация только ручная: change селектора -> POST
//                 {column}, бейджа нет.

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisUpload } from "./TsAnalysisUpload";
import { AppShellProvider } from "../context/AppShellContext";
import { toast } from "sonner";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

function dropCertFiles(input: Element, files: File[]) {
  fireEvent.drop(input, {
    dataTransfer: {
      files,
      items: files.map((file) => ({ kind: "file", type: file.type, getAsFile: () => file })),
      types: ["Files"],
    },
  });
}

// Свой upload-ответ аудитора: energy_consumption.csv, 336 строк,
// колонки ts/price/load (порядок задан намеренно: первая числовая --
// price, рекомендация бэкенда -- load).
const certUploadResponse = {
  dataset_id: "cert-b-001",
  name: "energy_consumption.csv",
  rows: 336,
  columns: 3,
  size_label: "34 КБ",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["ts", "price", "load"],
      ["2026-01-01 00:00", "112.4", "842.1"],
      ["2026-01-01 01:00", "108.9", "815.7"],
    ],
    tail: [["2026-01-14 23:00", "121.3", "903.4"]],
  },
  columns_info: [
    { name: "ts", dtype: "object", type_icon: "datetime", non_null: 336, nulls: 0, unique: 336 },
    { name: "price", dtype: "float64", type_icon: "numeric", non_null: 336, nulls: 0, unique: 310 },
    { name: "load", dtype: "int64", type_icon: "numeric", non_null: 336, nulls: 0, unique: 320 },
  ],
  quality: {
    cols_with_missing: 0,
    cols_with_outliers: 1,
    rows_total: 336,
    duplicates: 0,
    missing_cols: [],
    outlier_cols: ["load"],
  },
};

interface CertTargetAnswer {
  target_column: string | null;
  target_column_source?: string;
  suggested_column: string | null;
  available_columns: string[];
  has_dataset: boolean;
}

interface CertFetchSpec {
  getSequence: CertTargetAnswer[];
  sessionDatasetAfterUpload: boolean;
}

/** Свой мок-стенд аудитора для Upload: протоколирует вызовы /target-column
 * (url+method+body), переключает /session/current после upload, обслуживает
 * прочие ручки компонента минимально-достаточными заглушками. */
function certUploadFetch(spec: CertFetchSpec) {
  const targetCalls: Array<{ method: string; body: string | null }> = [];
  let getIdx = 0;
  let uploaded = false;
  global.fetch = jest.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? init.body : null;
    if (u.includes("/target-column")) {
      targetCalls.push({ method, body });
      if (method === "POST") {
        const column = JSON.parse(body ?? "{}").column;
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              target_column: column,
              target_column_source: "user",
              suggested_column: column,
              available_columns: ["ts", "price", "load"],
              has_dataset: true,
            }),
        });
      }
      const step = spec.getSequence[Math.min(getIdx, spec.getSequence.length - 1)];
      getIdx += 1;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(step) });
    }
    if (u.includes("/session/current")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve(
            uploaded && spec.sessionDatasetAfterUpload
              ? {
                  has_active_dataset: true,
                  dataset: { name: "energy_consumption.csv", rows: 336, size_label: "34 КБ" },
                  stages: {},
                  last_active_stage: "upload",
                  updated_at: "2026-10-08T08:00:00+00:00",
                }
              : { has_active_dataset: false, dataset: null, stages: {}, last_active_stage: null, updated_at: null },
          ),
      });
    }
    if (u.includes("/upload")) {
      uploaded = true;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(certUploadResponse) });
    }
    // Минимально-достаточные заглушки прочих ручек (свои URL-ветки).
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as unknown as typeof fetch;
  return targetCalls;
}

function mountUpload(): void {
  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>,
  );
}

const noTarget: CertTargetAnswer = {
  target_column: null,
  suggested_column: "load",
  available_columns: ["ts", "price", "load"],
  has_dataset: true,
};

describe("PROGR-25-B-CERT: селектор Загрузки (свои оракулы аудита)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("CERT-U1/U2: рекомендация load отображается (НЕ первая числовая price) и не персистится -- ни одного POST", async () => {
    const targetCalls = certUploadFetch({ getSequence: [noTarget], sessionDatasetAfterUpload: true });
    mountUpload();
    dropCertFiles(screen.getByTestId("dropzone-input"), [
      new File(["ts,price,load\n2026-01-01 00:00,112.4,842.1"], "energy_consumption.csv", { type: "text/csv" }),
    ]);

    await waitFor(() => {
      // РЕКОМЕНДАЦИЯ бэкенда, а не numericCols[0] ("price").
      expect(screen.getByDisplayValue("load")).toBeInTheDocument();
    });
    // R1: монтирование вкладки + рефетч после загрузки -- только GET.
    expect(targetCalls.length).toBeGreaterThan(0);
    expect(targetCalls.every((c) => c.method === "GET")).toBe(true);
    // Бейдж авто-происхождения не показан: ничего не зафиксировано.
    expect(screen.queryByTestId("auto-selected-hint")).toBeNull();
  });

  it("CERT-U3: бейдж «Выбрано автоматически» -- честный факт source: есть при auto, нет при user", async () => {
    // auto: бейдж есть.
    certUploadFetch({
      getSequence: [
        { target_column: "load", target_column_source: "auto", suggested_column: "load", available_columns: ["ts", "price", "load"], has_dataset: true },
      ],
      sessionDatasetAfterUpload: true,
    });
    mountUpload();
    dropCertFiles(screen.getByTestId("dropzone-input"), [
      new File(["ts,price,load\n2026-01-01 00:00,112.4,842.1"], "energy_consumption.csv", { type: "text/csv" }),
    ]);
    await waitFor(() => expect(screen.getByDisplayValue("load")).toBeInTheDocument());
    expect(screen.getByTestId("auto-selected-hint")).toHaveTextContent("Выбрано автоматически — можно изменить");
  });

  it("CERT-U3b: тот же сценарий при source=user -- бейджа нет", async () => {
    certUploadFetch({
      getSequence: [
        { target_column: "load", target_column_source: "user", suggested_column: "load", available_columns: ["ts", "price", "load"], has_dataset: true },
      ],
      sessionDatasetAfterUpload: true,
    });
    mountUpload();
    dropCertFiles(screen.getByTestId("dropzone-input"), [
      new File(["ts,price,load\n2026-01-01 00:00,112.4,842.1"], "energy_consumption.csv", { type: "text/csv" }),
    ]);
    await waitFor(() => expect(screen.getByDisplayValue("load")).toBeInTheDocument());
    expect(screen.queryByTestId("auto-selected-hint")).toBeNull();
  });

  it("CERT-U4: сброс после нового датасета -- честный toast с РЕКОМЕНДАЦИЕЙ, не с «выбран»", async () => {
    const targetCalls = certUploadFetch({
      getSequence: [
        // GET1 (маунт, до загрузки): ранее зафиксированный load (user).
        { target_column: "load", target_column_source: "user", suggested_column: "load", available_columns: ["ts", "price", "load"], has_dataset: true },
        // GET2 (после upload, смена datasetKey): бэкенд сбросил -- load
        // в новом датасете нет, рекомендация -- price.
        { target_column: null, suggested_column: "price", available_columns: ["ts", "price", "load"], has_dataset: true },
      ],
      sessionDatasetAfterUpload: true,
    });
    mountUpload();
    dropCertFiles(screen.getByTestId("dropzone-input"), [
      new File(["ts,price,load\n2026-01-01 00:00,112.4,842.1"], "energy_consumption.csv", { type: "text/csv" }),
    ]);

    await waitFor(() => {
      expect(toast.warning).toHaveBeenCalledWith(
        "Признак «load» недоступен в новом датасете — рекомендация: «price»",
      );
    });
    // Честность: хук ничего не фиксирует -- только GET-ы (R1).
    expect(targetCalls.every((c) => c.method === "GET")).toBe(true);
  });

  it("CERT-U5: фиксация только ручная: выбор price в селекторе -> POST {column:price}, бейджа нет", async () => {
    const targetCalls = certUploadFetch({ getSequence: [noTarget], sessionDatasetAfterUpload: true });
    mountUpload();
    dropCertFiles(screen.getByTestId("dropzone-input"), [
      new File(["ts,price,load\n2026-01-01 00:00,112.4,842.1"], "energy_consumption.csv", { type: "text/csv" }),
    ]);
    await waitFor(() => expect(screen.getByDisplayValue("load")).toBeInTheDocument());

    fireEvent.change(screen.getByDisplayValue("load"), { target: { value: "price" } });
    await waitFor(() => expect(screen.getByDisplayValue("price")).toBeInTheDocument());

    const post = targetCalls.find((c) => c.method === "POST");
    expect(post).toBeDefined();
    expect(JSON.parse(post!.body ?? "{}")).toEqual({ column: "price" });
    expect(screen.queryByTestId("auto-selected-hint")).toBeNull();
  });
});
