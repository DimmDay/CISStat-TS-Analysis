import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DocumentationWorkspace } from "../../packages/ui/components/DocumentationWorkspace";
import * as api from "../../packages/ui/lib/documentation";

jest.mock("../../packages/ui/lib/documentation", () => ({
  listDocuments: jest.fn(), createDraft: jest.fn(), getRevision: jest.fn(),
  getLifecycle: jest.fn(), cancelJob: jest.fn(), getJob: jest.fn(),
  requestRendition: jest.fn(), requestApproval: jest.fn(), decideApproval: jest.fn(),
  publishRevision: jest.fn(), retractRevision: jest.fn(), getRevisionDiff: jest.fn(),
  renditionContentUrl: (id: string) => `/content/${id}`,
}));
jest.mock("../../packages/ui/components/MonitoringComparisonPanel", () => ({ MonitoringComparisonPanel: () => null }));
jest.mock("../../packages/ui/components/Doclog9ProfileControls", () => ({ Doclog9ProfileControls: () => null }));

beforeEach(() => { jest.clearAllMocks(); });

it("AC17: a first source document can be created after choosing D02 in an empty run", async () => {
  (api.listDocuments as jest.Mock).mockResolvedValue({ ok: true, data: { documents: [] } });
  render(<DocumentationWorkspace runId="RUN-AUDIT-FIRST" />);
  await waitFor(() => expect(api.listDocuments).toHaveBeenCalledWith("RUN-AUDIT-FIRST"));
  await waitFor(() => expect(screen.getByTestId("doclog4-status")).toHaveTextContent(/нет|пока/i));
  fireEvent.click(screen.getByTestId("doclog4-kind-D02"));
  expect(screen.getByRole("button", { name: "Создать черновик" })).toBeEnabled();
});

it("AC17: a deep link kind must not disable first-document creation after the empty list arrives", async () => {
  (api.listDocuments as jest.Mock).mockResolvedValue({ ok: true, data: { documents: [] } });
  render(<DocumentationWorkspace runId="RUN-AUDIT-DEEP" initialKind="D03" />);
  await waitFor(() => expect(screen.getByTestId("doclog4-status")).toHaveTextContent(/нет|пока/i));
  expect(screen.getByRole("button", { name: "Создать черновик" })).toBeEnabled();
});

it("control: existing document metadata makes creation reachable", async () => {
  (api.listDocuments as jest.Mock).mockResolvedValue({ ok: true, data: { documents: [{
    document_id: "doc-audit-control", run_id: "RUN-AUDIT-CONTROL", kind_code: "D02",
    title: "Паспорт источника", revisions: [],
  }] } });
  render(<DocumentationWorkspace runId="RUN-AUDIT-CONTROL" initialKind="D02" />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Создать черновик" })).toBeEnabled());
});

it("AC17: a failed create request is visible to the analyst", async () => {
  (api.listDocuments as jest.Mock).mockResolvedValue({ ok: true, data: { documents: [{
    document_id: "doc-audit-error", run_id: "RUN-AUDIT-ERROR", kind_code: "D02",
    title: "Паспорт источника", revisions: [],
  }] } });
  (api.createDraft as jest.Mock).mockResolvedValue({ ok: false, status: 503 });
  render(<DocumentationWorkspace runId="RUN-AUDIT-ERROR" initialKind="D02" />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Создать черновик" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Создать черновик" }));
  await waitFor(() => expect(api.createDraft).toHaveBeenCalled());
  expect(screen.getByRole("alert")).toHaveTextContent(/недоступ|ошиб|не выполн/i);
});
