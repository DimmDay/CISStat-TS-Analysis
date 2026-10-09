// packages/ui/components/progr25d_toast_pin.test.tsx
//
// PROGR-25-D: repo-пин TB-8 (находка F1 сертификации PROGR-25-B-CERT).
// Существующий repo-тест toast сброса (TsAnalysisUpload.test.tsx «shows
// a warning toast...») пинит текст только как stringContaining("Price")
// -- ему удовлетворяют ОБЕ ветки честной развилки, поэтому мутант TB-8
// (нечестный текст: рекомендация всегда сообщается как «выберите новый
// признак») ПЕРЕЖИЛ repo-канал и был убит только сертификационным
// оракулом. Этот файл закрывает гэп: ТОЧНЫЙ текст обеих веток развилки
// TsAnalysisUpload.tsx (эффект columnResetNotice):
//   ветка рекомендации:  «...— рекомендация: «X»»
//   ветка без нее:       «...— выберите новый признак»
// Данные СВОИ (Sale/Region), не копируют Price/Volume существующего
// теста. Убивает TB-8 и его инверсию («always-рекомендация»).

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
  dataset_id: "123",
  name: "test.csv",
  rows: 10,
  columns: 2,
  size_label: "0.01 MB",
  parse_warnings: [] as string[],
  preview: {
    head: [
      ["month", "sale"],
      ["2023-01-01", "10"],
      ["2023-01-02", "20"],
    ],
    tail: [["2023-01-09", "90"], ["2023-01-10", "100"]],
  },
  columns_info: [
    { name: "month", dtype: "object", type_icon: "datetime", non_null: 10, nulls: 0, unique: 10 },
    { name: "sale", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
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

// Точная ветка рекомендации: после второй загрузки sale пропал, бэкенд
// рекомендует Region (suggested_column="Region").
const HONEST_RECOMMENDATION_TEXT =
  "Признак «Sale» недоступен в новом датасете — рекомендация: «Region»";
// Точная ветка без рекомендации: suggested_column=null.
const HONEST_CHOOSE_TEXT =
  "Признак «Sale» недоступен в новом датасете — выберите новый признак";

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
      // После первой загрузки: sale зафиксирован АВТОМАТИЧЕСКИ
      // (реалистичный путь PROGR-25-A: бэкенд сам фиксирует
      // единственного кандидата; источник -- auto).
      if (targetFetchCount === 2) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ target_column: "Sale", suggested_column: "Sale", target_column_source: "auto", available_columns: ["month", "Sale"], has_dataset: true }),
        });
      }
      // После второй загрузки (другой датасет): бэкенд сбросил target
      // (sale отсутствует), рекомендация -- по контексту сценария.
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ target_column: null, suggested_column: suggestedOnReset, target_column_source: null, available_columns: ["Region"], has_dataset: true }),
      });
    }
    if (typeof url === "string" && url.includes("/upload")) {
      uploadCount += 1;
      const columnsInfo =
        uploadCount === 1
          ? [
              { name: "month", dtype: "object", type_icon: "datetime", non_null: 10, nulls: 0, unique: 10 },
              { name: "Sale", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
            ]
          : [{ name: "Region", dtype: "object", type_icon: "categorical", non_null: 10, nulls: 0, unique: 3 }];
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

  // Первая загрузка -- Sale зафиксирован и отображается селектором.
  dropFiles(screen.getByTestId("dropzone-input"), [new File(["a"], "sales.csv", { type: "text/csv" })]);
  await waitFor(() => expect(screen.getByDisplayValue("Sale")).toBeInTheDocument());

  // «Сменить файл» возвращает к форме загрузки (handleReset,
  // dropzone скрыт 3-колоночным результатом после загрузки).
  fireEvent.click(screen.getAllByText("Сменить файл")[0]);
  await waitFor(() => expect(screen.getByTestId("dropzone-input")).toBeInTheDocument());

  // Вторая загрузка -- другой датасет, Sale отсутствует: сброс с
  // уведомлением, текст ОБЯЗАН совпасть ПОСИМВОЛЬНО (пин TB-8).
  dropFiles(screen.getByTestId("dropzone-input"), [new File(["a"], "regions.csv", { type: "text/csv" })]);

  await waitFor(() => {
    expect(toast.warning).toHaveBeenCalledWith(expectedText);
  });
  // Инверсная ветка НЕ использована: при наличии рекомендации текст
  // «выберите новый признак» не выдаётся, и наоборот (честная развилка).
  const opposite =
    expectedText === HONEST_RECOMMENDATION_TEXT ? HONEST_CHOOSE_TEXT : HONEST_RECOMMENDATION_TEXT;
  expect(toast.warning).not.toHaveBeenCalledWith(opposite);
}

describe("PROGR-25-D repo-пин TB-8: честный текст toast сброса (точная развилка)", () => {
  beforeEach(() => {
    (toast.warning as jest.Mock).mockClear();
    (toast.success as jest.Mock).mockClear();
    (toast.error as jest.Mock).mockClear();
  });

  it("рекомендация есть -- точный текст «— рекомендация: «Region»» (убивает TB-8)", async () => {
    await runResetScenario({ suggestedOnReset: "Region", expectedText: HONEST_RECOMMENDATION_TEXT });
  });

  it("рекомендации нет -- точный текст «— выберите новый признак» (убивает инверсию)", async () => {
    await runResetScenario({ suggestedOnReset: null, expectedText: HONEST_CHOOSE_TEXT });
  });
});
