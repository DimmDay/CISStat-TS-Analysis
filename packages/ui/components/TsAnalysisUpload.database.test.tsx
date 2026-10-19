import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TsAnalysisUpload } from "./TsAnalysisUpload";

const mockSetActiveDataset = jest.fn();
const mockRefresh = jest.fn(async () => {});
const mockRefetchTarget = jest.fn();
jest.mock("../context/AppShellContext", () => ({ useAppShell: () => ({
  activeDataset: null, setActiveDataset: mockSetActiveDataset, refreshSession: mockRefresh,
}) }));
jest.mock("../hooks/useTargetColumn", () => ({ useTargetColumn: () => ({
  targetColumn: null, suggestedColumn: null, wasAutoSelected: false, columnResetNotice: null,
  dismissColumnResetNotice: jest.fn(), passportResetNotice: null, setColumn: jest.fn(), refetch: mockRefetchTarget,
}) }));

it("database load enters the existing preview, shell, refresh and progress pipeline", async () => {
  const data = { dataset_id: "db-integration", name: "audit.sqlite", rows: 12, columns: 1,
    preview: { head: [["value"], ["721"]], tail: [["754"]] },
    columns_info: [{ name: "value", dtype: "float64", type_icon: "numeric", non_null: 12, nulls: 0, unique: 12 }],
    quality: { cols_with_missing: 0, cols_with_outliers: 0, rows_total: 12, duplicates: 0, missing_cols: [], outlier_cols: [] },
    size_label: "1 KB", parse_warnings: [] };
  const posts: string[] = [];
  global.fetch = jest.fn((url, init) => {
    const address = String(url);
    if (init?.method === "POST") posts.push(address);
    const body = address.includes("/upload/db/load") ? data
      : address.includes("/structure-detection") ? { date_col: { selected: "(не использовать)", confidence: 0, candidates: [] }, entity_col: { selected: "(нет)", confidence: 0, candidates: [] } }
      : address.endsWith("/trace") ? { run_id: "run-db", context_id: "ctx-db" }
      : { columns: [] };
    return Promise.resolve({ ok: true, status: 200, json: async () => body });
  }) as jest.Mock;
  render(<TsAnalysisUpload />);
  fireEvent.click(screen.getByRole("radio", { name: "База данных (SQL)" }));
  fireEvent.change(screen.getByLabelText("Тип БД"), { target: { value: "sqlite" } });
  fireEvent.change(screen.getByLabelText("Путь к файлу"), { target: { value: "/data/audit.sqlite" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить из БД" }));
  await waitFor(() => expect(mockSetActiveDataset).toHaveBeenCalledWith(expect.objectContaining({ datasetId: "db-integration", name: "audit.sqlite", rows: 12 })));
  await waitFor(() => expect(screen.getByText("721")).toBeInTheDocument());
  expect(mockRefresh).toHaveBeenCalled();
  expect(mockRefetchTarget).toHaveBeenCalled();
  await waitFor(() => expect(posts.some(p => p.endsWith("/progress/upload-stops"))).toBe(true));
  expect(posts.filter(p => p.endsWith("/upload/db/load"))).toHaveLength(1);
});
