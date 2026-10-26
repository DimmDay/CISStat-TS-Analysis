// scripts/doclogrecheckfixcert/documentation-client-cert.test.tsx
//
// Собственный сертификационный оракул C01 (standalone-клиент): страница
// «Документы» без ?run= резолвит ТЕКУЩЕЕ исследование через
// resolveCurrentRun и передаёт его в Workspace; отсутствие run --
// честный null (no-run-фаза); на время резолва -- статус «Определение…».

import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { DocumentationClient } from "../../apps/standalone/app/documentation/documentation-client";

jest.mock("@cisstat/ui", () => ({
  DocumentationWorkspace: (props: {
    runId: string | null;
    initialKind: string | null;
  }) => (
    <div
      data-testid="cert-workspace"
      data-run={props.runId === null ? "null" : props.runId}
      data-kind={props.initialKind ?? ""}
    />
  ),
  resolveCurrentRun: jest.fn(),
}));

import { resolveCurrentRun } from "@cisstat/ui";

describe("DOCLOG-E2E-RECHECK-1-FIX: DocumentationClient (C01)", () => {
  beforeEach(() => jest.clearAllMocks());

  it("CC1: без ?run= текущий run резолвится и передаётся Workspace", async () => {
    (resolveCurrentRun as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-RCFCERT-CC1" },
    });
    render(<DocumentationClient initialRunId={null} initialKind={null} />);
    // фаза резолва честная (не пустой реестр)
    expect(screen.getByRole("status")).toHaveTextContent(
      /Определение текущего исследования/i,
    );
    await waitFor(() =>
      expect(screen.getByTestId("cert-workspace")).toHaveAttribute(
        "data-run",
        "RUN-RCFCERT-CC1",
      ),
    );
  });

  it("CC1: нет текущего run -- Workspace получает null (no-run, не empty)", async () => {
    (resolveCurrentRun as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: null },
    });
    render(<DocumentationClient initialRunId={null} initialKind={null} />);
    await waitFor(() =>
      expect(screen.getByTestId("cert-workspace")).toHaveAttribute(
        "data-run",
        "null",
      ),
    );
  });

  it("CC1: URL ?run= приоритетен -- резолв не вызывается", async () => {
    render(
      <DocumentationClient
        initialRunId="RUN-RCFCERT-URL"
        initialKind="D02"
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("cert-workspace")).toHaveAttribute(
        "data-run",
        "RUN-RCFCERT-URL",
      ),
    );
    expect(screen.getByTestId("cert-workspace")).toHaveAttribute(
      "data-kind",
      "D02",
    );
    expect(resolveCurrentRun).not.toHaveBeenCalled();
  });

  it("CC1: отказ резолва -- Workspace получает null (не фабрикация)", async () => {
    (resolveCurrentRun as jest.Mock).mockResolvedValue({
      ok: false,
      status: 503,
    });
    render(<DocumentationClient initialRunId={null} initialKind={null} />);
    await waitFor(() =>
      expect(screen.getByTestId("cert-workspace")).toHaveAttribute(
        "data-run",
        "null",
      ),
    );
  });
});
