// UI reproduction using recorded real HTTP responses, not fabricated statuses.
import { fireEvent, render, screen } from "@testing-library/react";
import fs from "fs";
import path from "path";

jest.mock("../../packages/ui/lib/visualExports", () => ({
  ...jest.requireActual("../../packages/ui/lib/visualExports"),
  requestVisualExport: jest.fn(),
  resolveCurrentRunForExport: jest.fn(),
}));

import { VisualExportButton } from "../../packages/ui/components/VisualExportButton";
import { requestVisualExport, resolveCurrentRunForExport } from "../../packages/ui/lib/visualExports";

it("renders both reported alerts across reopening with actual native HTTP evidence", async () => {
  const report = JSON.parse(fs.readFileSync(path.join(__dirname, "protocols/native-report.json"), "utf8"));
  expect(report.reproduced).toBe(true);
  jest.mocked(resolveCurrentRunForExport).mockResolvedValue({
    ok: true, status: 200, data: { run_id: "RUN-DIAG0001", context_id: "ctx-diagnostic" },
  });
  for (const step of report.steps.slice(0, 2)) {
    jest.mocked(requestVisualExport).mockResolvedValueOnce({
      ok: false, status: step.status, error: { code: step.body.code, message: step.body.message },
    });
    const view = render(<VisualExportButton viewId="upload.overview.tech_table" />);
    fireEvent.click(screen.getByTestId("visual-export-upload.overview.tech_table"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(step.status === 409
      ? "Зафиксированный результат недоступен — откройте представление заново и повторите."
      : "Экспорт временно недоступен — повторите позднее.");
    view.unmount();
  }
});
