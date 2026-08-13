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
import { toast } from "sonner";

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

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

// AppShellProvider гидрируется с /v1/session/current при монтировании,
// а после успешного upload компонент сам запрашивает /dataset/stats --
// мокаем обе ручки; конкретные тесты переопределяют /upload под свой сценарий.
function mockFetchSequence(uploadResult: unknown, uploadOk = true) {
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
    if (typeof url === "string" && url.includes("/dataset/stats")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(okStatsResponse) });
    }
    if (typeof url === "string" && url.includes("/dataset/panel-balance")) {
      // В тестовых моках нет реальной группирующей колонки -- фиксируем
      // ответ явно, чтобы не зависеть от generic-фолбэка ниже.
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ balanced: false, n_entities: 0, n_distinct_date_sets: 0 }) });
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
});
