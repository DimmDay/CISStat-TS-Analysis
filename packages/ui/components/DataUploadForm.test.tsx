// packages/ui/components/DataUploadForm.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { DataUploadForm } from "./DataUploadForm";
import { AppShellProvider } from "../context/AppShellContext";
import { toast } from "sonner";

// Mock fetch
global.fetch = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
      dataset_id: "123",
      name: "test.csv",
      rows: 10,
      columns: 2,
      preview: {
        head: [["date", "value"], ["2023-01-01", "10"], ["2023-01-02", "20"]],
        tail: [["2023-01-09", "90"], ["2023-01-10", "100"]],
      },
    }),
  })
) as jest.Mock;

describe("DataUploadForm", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("should render upload form", () => {
    render(
      <AppShellProvider>
        <DataUploadForm />
      </AppShellProvider>
    );
    expect(screen.getByText(/Загрузка данных/)).toBeInTheDocument();
    expect(screen.getByText(/Перетащите файл сюда/)).toBeInTheDocument();
  });

  it("should show file name after selection", async () => {
    render(
      <AppShellProvider>
        <DataUploadForm />
      </AppShellProvider>
    );

    const file = new File(["a,b\n1,2"], "test.csv", { type: "text/csv" });
    const input = screen.getByTestId("dropzone-input");

    fireEvent.drop(input, {
      dataTransfer: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByText(/Выбран: test.csv/)).toBeInTheDocument();
    });
  });

  it("should show preview after successful upload", async () => {
    render(
      <AppShellProvider>
        <DataUploadForm />
      </AppShellProvider>
    );

    const file = new File(["date,value\n2023-01-01,10\n2023-01-02,20"], "test.csv", {
      type: "text/csv",
    });
    const input = screen.getByTestId("dropzone-input");

    fireEvent.drop(input, {
      dataTransfer: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByText(/Предпросмотр данных/)).toBeInTheDocument();
      expect(screen.getByText("date")).toBeInTheDocument();
      expect(screen.getByText("value")).toBeInTheDocument();
    });
  });

  it("should reject files > 50MB", async () => {
    const largeFile = new File([new ArrayBuffer(51 * 1024 * 1024)], "large.csv", {
      type: "text/csv",
    });
    render(
      <AppShellProvider>
        <DataUploadForm />
      </AppShellProvider>
    );

    const input = screen.getByTestId("dropzone-input");
    fireEvent.drop(input, {
      dataTransfer: { files: [largeFile] },
    });

    await waitFor(() => {
      expect(screen.getByText(/Файл слишком большой/)).toBeInTheDocument();
    });
  });

  it("should reject unsupported file formats", async () => {
    const txtFile = new File(["plain text"], "test.txt", {
      type: "text/plain",
    });
    render(
      <AppShellProvider>
        <DataUploadForm />
      </AppShellProvider>
    );

    const input = screen.getByTestId("dropzone-input");
    fireEvent.drop(input, {
      dataTransfer: { files: [txtFile] },
    });

    await waitFor(() => {
      expect(screen.getByText(/Неподдерживаемый формат/)).toBeInTheDocument();
    });
  });

  it("should show error toast on upload failure", async () => {
    // Mock fetch с ошибкой
    global.fetch = jest.fn(() =>
      Promise.resolve({
        ok: false,
        json: () => Promise.resolve({ detail: "Ошибка сервера" }),
      })
    ) as jest.Mock;

    render(
      <AppShellProvider>
        <DataUploadForm />
      </AppShellProvider>
    );

    const file = new File(["a,b\n1,2"], "test.csv", { type: "text/csv" });
    const input = screen.getByTestId("dropzone-input");

    fireEvent.drop(input, {
      dataTransfer: { files: [file] },
    });

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("Ошибка сервера")
      );
    });
  });
});