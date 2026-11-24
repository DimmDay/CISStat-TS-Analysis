// packages/ui/components/DocumentationWorkspace.pgv15.test.tsx
//
// PGV-15: интеграция фильтра семейств в «Документы исследования».
// Оракулы: default «Документы» сохраняет прежний D01-D12 поток;
// переключение на паспорта/визуализации монтирует печатные панели и
// скрывает D-каталог (D02 не смешивается с P01); без run -- честный
// no-run печатных семейств.

import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { DocumentationWorkspace } from "./DocumentationWorkspace";

jest.mock("../lib/documentation", () => ({
  listDocuments: jest.fn().mockResolvedValue({ ok: true, status: 200, data: { run_id: "RUN-1", documents: [] } }),
  createDraft: jest.fn(),
  getRevision: jest.fn(),
  requestRendition: jest.fn(),
  getJob: jest.fn(),
  cancelJob: jest.fn(),
  renditionContentUrl: (id: string) => `/v1/documentation/renditions/${id}/content`,
  revisionPreviewUrl: (id: string) => `/v1/documentation/revisions/${id}/preview`,
  resolveCurrentRun: jest.fn().mockResolvedValue({ ok: true, status: 200, data: { run_id: "RUN-1" } }),
}));

jest.mock("./PassportDocumentsPanel", () => ({
  PassportDocumentsPanel: () => (
    <div data-testid="pgv15-passports-panel-mock">passports panel</div>
  ),
}));

jest.mock("./PrintDocumentsPanel", () => ({
  PrintDocumentsPanel: () => (
    <div data-testid="pgv15-print-documents-mock">print documents</div>
  ),
}));

jest.mock("./MonitoringComparisonPanel", () => ({
  MonitoringComparisonPanel: () => <div>monitoring</div>,
}));

describe("DocumentationWorkspace — фильтр семейств (PGV-15)", () => {
  it("три семейства с aria-pressed; default «Документы» активен", () => {
    render(<DocumentationWorkspace runId="RUN-1" />);
    expect(screen.getByTestId("pgv15-family-documents")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("pgv15-family-passports")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("pgv15-family-visuals")).toHaveAttribute("aria-pressed", "false");
  });

  it("default «Документы»: прежний D-каталог видим, печатные панели не смонтированы", () => {
    render(<DocumentationWorkspace runId="RUN-1" />);
    expect(screen.getByTestId("doclog4-kind-list")).toBeInTheDocument();
    expect(screen.queryByTestId("pgv15-family-pane")).toBeNull();
    expect(screen.queryByTestId("pgv15-passports-panel-mock")).toBeNull();
  });

  it("«Паспорта свойств»: печатная панель смонтирована, D-каталог скрыт (D02 не смешивается)", () => {
    render(<DocumentationWorkspace runId="RUN-1" />);
    fireEvent.click(screen.getByTestId("pgv15-family-passports"));
    expect(screen.getByTestId("pgv15-family-pane")).toBeInTheDocument();
    expect(screen.getByTestId("pgv15-passports-panel-mock")).toBeInTheDocument();
    expect(screen.queryByTestId("doclog4-kind-list")).toBeNull();
    expect(screen.queryByTestId("doclog4-version-list")).toBeNull();
    expect(screen.queryByTestId("doclog4-preview-pane")).toBeNull();
  });

  it("«Визуализации»: честная подпись Пути A + панель печатных документов", () => {
    render(<DocumentationWorkspace runId="RUN-1" />);
    fireEvent.click(screen.getByTestId("pgv15-family-visuals"));
    expect(screen.getByText(/Экспорт создаётся действием «Скачать PNG»/)).toBeInTheDocument();
    expect(screen.getByTestId("pgv15-print-documents-mock")).toBeInTheDocument();
  });

  it("без run печатные семейства дают честный no-run", () => {
    render(<DocumentationWorkspace runId={null} />);
    fireEvent.click(screen.getByTestId("pgv15-family-passports"));
    expect(screen.getByTestId("pgv15-family-no-run")).toBeInTheDocument();
  });

  it("возврат в «Документы»: прежний поток D01-D12 восстановлен", () => {
    render(<DocumentationWorkspace runId="RUN-1" />);
    fireEvent.click(screen.getByTestId("pgv15-family-visuals"));
    expect(screen.queryByTestId("doclog4-kind-list")).toBeNull();
    fireEvent.click(screen.getByTestId("pgv15-family-documents"));
    expect(screen.getByTestId("doclog4-kind-list")).toBeInTheDocument();
  });
});
