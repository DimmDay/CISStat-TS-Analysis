// packages/ui/components/TsAnalysisUpload.test.tsx
//
// ПЕРЕНЕСЕНО из DataUploadForm.test.tsx (компонент поглощён --
// см. шапку TsAnalysisUpload.tsx). Тексты ассертов обновлены под новую
// вёрстку ("Превью датасета" вместо "Предпросмотр данных" и т.п.).
//
// ОБНОВЛЕНИЕ: на момент первой версии этого файла jest в репозитории не
// было (см. git-историю) -- тесты были написаны "на будущее" и не
// запускались. Команда параллельно подключила jest+ts-jest
// (jest.config.js в корне) -- этот файл реально прогнан против неё:
// добавлен импорт "@testing-library/jest-dom" (по конвенции проекта,
// см. TsAnalysisModeling.test.tsx -- setupFilesAfterEach не настроен,
// каждый файл подключает матчеры сам) и исправлен мок dataTransfer:
// react-dropzone читает event.dataTransfer.items/types внутри своего
// обработчика, одного files[] недостаточно для fireEvent.drop.

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TsAnalysisUpload } from "./TsAnalysisUpload";
import { AppShellProvider } from "../context/AppShellContext";
import { toast } from "sonner";

// sonner не мокается автоматически -- никто в репозитории пока этого не
// делал (первый тест, использующий toast). Без мока toast.error/success
// это реальные DOM-побочные эффекты библиотеки, не jest.fn().
jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
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
  preview: {
    head: [
      ["date", "value"],
      ["2023-01-01", "10"],
      ["2023-01-02", "20"],
    ],
    tail: [["2023-01-09", "90"], ["2023-01-10", "100"]],
  },
  columns_info: [
    { name: "date", dtype: "object", type_icon: "categorical", non_null: 10, nulls: 0, unique: 10 },
    { name: "value", dtype: "int64", type_icon: "numeric", non_null: 10, nulls: 0, unique: 10 },
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

// AppShellProvider гидрируется с /v1/session/current при монтировании --
// мокаем fetch на "пустую сессию" по умолчанию, конкретные тесты
// переопределяют мок под свой сценарий загрузки.
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

  it("should render upload form", () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );
    expect(screen.getByText(/Загрузка данных/)).toBeInTheDocument();
    expect(screen.getByText(/Перетащите файл сюда/)).toBeInTheDocument();
  });

  it("should show uploaded file name in the success summary", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    const file = new File(["a,b\n1,2"], "test.csv", { type: "text/csv" });
    const input = screen.getByTestId("dropzone-input");

    dropFiles(input, [file]);

    // Мок fetch разрешается почти мгновенно -- транзитное "Выбран:" можно
    // не успеть поймать, поэтому проверяем финальное состояние (карточка
    // "источник данных" после успешной загрузки содержит имя файла).
    await waitFor(() => {
      expect(screen.getByText("test.csv")).toBeInTheDocument();
    });
  });

  it("should show preview and quality teaser after successful upload", async () => {
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    const file = new File(["date,value\n2023-01-01,10\n2023-01-02,20"], "test.csv", { type: "text/csv" });
    const input = screen.getByTestId("dropzone-input");

    dropFiles(input, [file]);

    await waitFor(() => {
      expect(screen.getByText(/Превью датасета/)).toBeInTheDocument();
      expect(screen.getByText(/Предварительная оценка качества/)).toBeInTheDocument();
    });
  });

  it("should reject files > 50MB", async () => {
    const largeFile = new File([new ArrayBuffer(51 * 1024 * 1024)], "large.csv", { type: "text/csv" });
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    const input = screen.getByTestId("dropzone-input");
    dropFiles(input, [largeFile]);

    await waitFor(() => {
      expect(screen.getByText(/Файл слишком большой/)).toBeInTheDocument();
    });
  });

  it("should reject unsupported file formats", async () => {
    const txtFile = new File(["plain text"], "test.txt", { type: "text/plain" });
    render(
      <AppShellProvider>
        <TsAnalysisUpload />
      </AppShellProvider>
    );

    const input = screen.getByTestId("dropzone-input");
    dropFiles(input, [txtFile]);

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

    const file = new File(["a,b\n1,2"], "test.csv", { type: "text/csv" });
    const input = screen.getByTestId("dropzone-input");

    dropFiles(input, [file]);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Ошибка сервера"));
    });
  });
});
