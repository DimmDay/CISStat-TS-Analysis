// packages/ui/components/documentation-recheck-fix.test.tsx
//
// Repo-тесты DOCLOG-E2E-RECHECK-1-FIX (исправление находок повторного
// аудита docs/doclogcert_2026_10_26/certification.md):
//   C02 -- первый документ создаётся из пустого реестра; deep-link
//          initialKind не сбрасывается пустым списком;
//   C07 -- отказ создания черновика виден аналитику (role=alert),
//          повтор не теряет выбранный вид;
//   C01 -- отсутствие run -- честное no-run-состояние (не «пустой
//          реестр»);
//   C09 -- тяжёлые форматы (PDF/XLSX/Parquet/ZIP) доступны в общем
//          селекторе с честной подписью зависимости от worker'а.
//
// Namespace тестов дизъюнктен audit-корпусу (bootstrap.test.tsx).

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DocumentationWorkspace } from "./DocumentationWorkspace";
import * as api from "../lib/documentation";

jest.mock("../lib/documentation", () => ({
  listDocuments: jest.fn(),
  createDraft: jest.fn(),
  getRevision: jest.fn(),
  getLifecycle: jest.fn(),
  cancelJob: jest.fn(),
  getJob: jest.fn(),
  requestRendition: jest.fn(),
  requestApproval: jest.fn(),
  decideApproval: jest.fn(),
  publishRevision: jest.fn(),
  retractRevision: jest.fn(),
  getRevisionDiff: jest.fn(),
  resolveCurrentRun: jest.fn(),
  renditionContentUrl: (id: string) => `/content/${id}`,
  revisionPreviewUrl: (id: string) => `/preview/${id}`,
}));
jest.mock("./MonitoringComparisonPanel", () => ({
  MonitoringComparisonPanel: () => null,
}));
jest.mock("./Doclog9ProfileControls", () => ({
  Doclog9ProfileControls: () => null,
}));

describe("DOCLOG-E2E-RECHECK-1-FIX: DocumentationWorkspace", () => {
  beforeEach(() => jest.clearAllMocks());

  it("C02: кнопка создания активна на пустом реестре после выбора вида", async () => {
    (api.listDocuments as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-RECHECK-UI", documents: [] },
    });
    render(<DocumentationWorkspace runId="RUN-RECHECK-UI" />);
    await waitFor(() =>
      expect(api.listDocuments).toHaveBeenCalledWith("RUN-RECHECK-UI"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("doclog4-status")).toHaveTextContent(/пока/i),
    );
    fireEvent.click(screen.getByTestId("doclog4-kind-D02"));
    expect(screen.getByRole("button", { name: "Создать черновик" })).toBeEnabled();
  });

  it("C02: deep-link initialKind сохраняется пустым списком", async () => {
    (api.listDocuments as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-RECHECK-DEEP", documents: [] },
    });
    render(
      <DocumentationWorkspace runId="RUN-RECHECK-DEEP" initialKind="D03" />,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Создать черновик" })).toBeEnabled(),
    );
    // выбранный вид не сброшен: кнопка создания присутствует (activeKind=D03)
    expect(
      screen.getByRole("button", { name: "Создать черновик" }),
    ).toBeEnabled();
  });

  it("C07: отказ создания показывается alert'ом, вид сохраняется", async () => {
    (api.listDocuments as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        run_id: "RUN-RECHECK-ERR",
        documents: [
          {
            document_id: "doc-recheck-err",
            run_id: "RUN-RECHECK-ERR",
            kind_code: "D02",
            title: "Паспорт источника",
            revisions: [],
          },
        ],
      },
    });
    (api.createDraft as jest.Mock).mockResolvedValue({
      ok: false,
      status: 503,
    });
    render(<DocumentationWorkspace runId="RUN-RECHECK-ERR" initialKind="D02" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Создать черновик" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Создать черновик" }));
    await waitFor(() => expect(api.createDraft).toHaveBeenCalled());
    expect(screen.getByRole("alert")).toHaveTextContent(
      /недоступ|не выполн|503/i,
    );
    // повтор не теряет вид: кнопка снова доступна и кликабельна
    expect(screen.getByRole("button", { name: "Создать черновик" })).toBeEnabled();
  });

  it("C01: без run -- честное no-run-состояние, не «документов нет»", async () => {
    render(<DocumentationWorkspace runId={null} />);
    await waitFor(() =>
      expect(screen.getByTestId("doclog4-status")).toHaveTextContent(
        /Исследование не выбрано/i,
      ),
    );
    // это НЕ пустой реестр: подсказка на ?run=/Прогресс
    expect(screen.getByTestId("doclog4-status")).toHaveTextContent(
      /Прогресс|run=/,
    );
  });

  it("C09: тяжёлые форматы присутствуют в селекторе с подписью worker'а", async () => {
    (api.listDocuments as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        run_id: "RUN-RECHECK-FMT",
        documents: [
          {
            document_id: "doc-recheck-fmt",
            run_id: "RUN-RECHECK-FMT",
            kind_code: "D02",
            title: "Паспорт источника",
            revisions: [
              {
                revision_id: "rev-recheck-fmt",
                document_id: "doc-recheck-fmt",
                snapshot_id: "snap-recheck-fmt",
                run_id: "RUN-RECHECK-FMT",
                version_no: 1,
                created_by: null,
                created_at: "2026-10-26T00:00:00Z",
                completeness_status: "complete",
                lifecycle_state: "draft",
                renditions: [],
              },
            ],
          },
        ],
      },
    });
    (api.getRevision as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        revision: {
          revision_id: "rev-recheck-fmt",
          document_id: "doc-recheck-fmt",
          snapshot_id: "snap-recheck-fmt",
          run_id: "RUN-RECHECK-FMT",
          version_no: 1,
          created_by: null,
          created_at: "2026-10-26T00:00:00Z",
          completeness_status: "complete",
          lifecycle_state: "draft",
          renditions: [],
        },
        snapshot: {
          snapshot_id: "snap-recheck-fmt",
          captured_at: "2026-10-26T00:00:00Z",
          context_id: "ctx-recheck",
          data_revision: 1,
          completeness: { status: "complete", missing_refs: [], missing_mandatory: [] },
          reproducibility: { status: "ready", reasons: [] },
          sections: [],
        },
        renditions: [],
      },
    });
    (api.getLifecycle as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      data: { records: [] },
    });
    render(<DocumentationWorkspace runId="RUN-RECHECK-FMT" initialKind="D02" />);
    await waitFor(() =>
      expect(screen.getByText("Предпросмотр")).toBeInTheDocument(),
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "PDF" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "XLSX" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Parquet" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "ZIP" })).toBeInTheDocument();
    });
    // честная зависимость от worker'а (не мгновенный формат)
    expect(screen.getByText(/собираются worker/i)).toBeInTheDocument();
  });
});
