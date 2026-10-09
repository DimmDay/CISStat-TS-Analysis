// packages/ui/components/progr25dcert_toast_oracle.test.tsx
//
// PROGR-25-D-CERT: фронт-оракул аудитора на СВОИХ данных (сертификация
// задачи D). Независимая проверка честной развилки toast сброса признака
// (TsAnalysisUpload.tsx, эффект columnResetNotice) на своих строках:
//   предыдущий признак: «AirTemp» (≠ Price/Volume существующего repo-теста,
//                                     ≠ Sale/Region пина задачи D)
//   рекомендация:       «Pressure»
// Обе ветки -- ТОЧНОЕ посимвольное равенство + инверсная проверка
// not.toHaveBeenCalledWith (противоположная ветка НЕ выдаётся):
//   ветка рекомендации: «...— рекомендация: «Pressure»»
//   ветка без нее:      «...— выберите новый признак»
// Оракул обязан падать на любом искажении текста любой ветки (канал убийства
// мутанта DC-7 сертификации PROGR-25-D-CERT).

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
  dataset_id: "dcert-1",
  name: "dcert.csv",
  rows: 10,
  columns: 2,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["day", "airtemp"],
      ["2025-03-01", "10"],
      ["2025-03-02", "20"],
    ],
    tail: [["2025-03-09", "90"], ["2025-03-10", "100"]],
  },
  columns_info: [
    { name: "day", dtype: "object", type_icon: "datetime", non_null: 10, nulls: 0, unique: 10 },
    { name: "AirTemp", dtype: "float64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
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

// Точная ветка рекомендации: после второй загрузки AirTemp пропал, бэкенд
// рекомендует Pressure (suggested_column="Pressure").
const HONEST_RECOMMENDATION_TEXT =
  "Признак «AirTemp» недоступен в новом датасете — рекомендация: «Pressure»";
// Точная ветка без рекомендации: suggested_column=null.
const HONEST_CHOOSE_TEXT =
  "Признак «AirTemp» недоступен в новом датасете — выберите новый признак";

interface ResetScenario {
  suggestedOnReset: string | null;
  expectedText: string;
}

async function runResetScenario({ suggestedOnReset, expectedText }: ResetScenario) {
  let uploadCount = 0;
  let targetFetchCount = 0;
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
          json: () => Promise.resolve({ target_column: body.column, suggested_column: body.column, available_columns: [body.column], has_dataset: true }),
        });
      }
      targetFetchCount += 1;
      // Монтирование: датасета нет вообще.
      if (targetFetchCount === 1) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: null, suggested_column: null, available_columns: [], has_dataset: false }),
        });
      }
      // После первой загрузки: AirTemp зафиксирован АВТОМАТИЧЕСКИ
      // (реалистичный путь PROGR-25-A: бэкенд сам фиксирует единственного
      // кандидата; источник -- auto).
      if (targetFetchCount === 2) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: "AirTemp", suggested_column: "AirTemp", target_column_source: "auto", available_columns: ["day", "AirTemp"], has_dataset: true }),
        });
      }
      // После второй загрузки (другой датасет): бэкенд сбросил target
      // (AirTemp отсутствует), рекомендация -- по контексту сценария.
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ target_column: null, suggested_column: suggestedOnReset, target_column_source: null, available_columns: ["Pressure"], has_dataset: true }),
      });
    }
    if (typeof url === "string" && url.includes("/upload")) {
      uploadCount += 1;
      const columnsInfo =
        uploadCount === 1
          ? [
              { name: "day", dtype: "object", type_icon: "datetime", non_null: 10, nulls: 0, unique: 10 },
              { name: "AirTemp", dtype: "float64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
            ]
          : [{ name: "Pressure", dtype: "float64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 }];
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ...okUploadResponse, name: `dcert-dataset-${uploadCount}.csv`, columns_info: columnsInfo }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as unknown as typeof fetch;

  render(
    <AppShellProvider>
      <TsAnalysisUpload />
    </AppShellProvider>
  );

  // Первая загрузка -- AirTemp зафиксирован и отображается селектором.
  dropFiles(screen.getByTestId("dropzone-input"), [new File(["a"], "weather.csv", { type: "text/csv" })]);
  await waitFor(() => expect(screen.getByDisplayValue("AirTemp")).toBeInTheDocument());

  // «Сменить файл» возвращает к форме загрузки (handleReset).
  fireEvent.click(screen.getAllByText("Сменить файл")[0]);
  await waitFor(() => expect(screen.getByTestId("dropzone-input")).toBeInTheDocument());

  // Вторая загрузка -- другой датасет, AirTemp отсутствует: сброс с
  // уведомлением, текст ОБЯЗАН совпасть ПОСИМВОЛЬНО.
  dropFiles(screen.getByTestId("dropzone-input"), [new File(["a"], "pressure.csv", { type: "text/csv" })]);

  await waitFor(() => {
    expect(toast.warning).toHaveBeenCalledWith(expectedText);
  });
  // Инверсная ветка НЕ использована: при наличии рекомендации текст
  // «выберите новый признак» не выдаётся, и наоборот (честная развилка).
  const opposite =
    expectedText === HONEST_RECOMMENDATION_TEXT ? HONEST_CHOOSE_TEXT : HONEST_RECOMMENDATION_TEXT;
  expect(toast.warning).not.toHaveBeenCalledWith(opposite);
}

describe("PROGR-25-D-CERT фронт-оракул: честный текст toast сброса (свои данные AirTemp/Pressure)", () => {
  beforeEach(() => {
    (toast.warning as jest.Mock).mockClear();
    (toast.success as jest.Mock).mockClear();
    (toast.error as jest.Mock).mockClear();
  });

  it("рекомендация есть -- точный текст «— рекомендация: «Pressure»»", async () => {
    await runResetScenario({ suggestedOnReset: "Pressure", expectedText: HONEST_RECOMMENDATION_TEXT });
  });

  it("рекомендации нет -- точный текст «— выберите новый признак»", async () => {
    await runResetScenario({ suggestedOnReset: null, expectedText: HONEST_CHOOSE_TEXT });
  });
});
