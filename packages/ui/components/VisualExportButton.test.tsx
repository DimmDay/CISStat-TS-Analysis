// packages/ui/components/VisualExportButton.test.tsx
//
// PGV-10: оракулы общего действия «Скачать PNG» (§10.1): честные
// состояния idle/queued/error; run_id -- единый источник /trace;
// 409 context_changed и другие коды -- человеческая причина;
// disabled -- честная причина; screenSvg отсутствует у chart-view --
// локальный отказ до POST (не «первый SVG»).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const requestVisualExportMock = jest.fn();
const resolveCurrentRunMock = jest.fn();

jest.mock("../lib/visualExports", () => ({
  requestVisualExport: (...args: unknown[]) => requestVisualExportMock(...args),
  resolveCurrentRunForExport: () => resolveCurrentRunMock(),
  visualExportErrorText: jest.requireActual("../lib/visualExports").visualExportErrorText,
}));

import { VisualExportButton, VisualExportChartScope } from "./VisualExportButton";

beforeEach(() => {
  requestVisualExportMock.mockReset();
  resolveCurrentRunMock.mockReset();
});

describe("VisualExportButton (PGV-10)", () => {
  it("202: состояние queued с job_id и честным текстом «Документы исследования»", async () => {
    resolveCurrentRunMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-P10A01", context_id: "ctx-1" },
    });
    requestVisualExportMock.mockResolvedValue({
      ok: true,
      status: 202,
      data: {
        run_id: "RUN-P10A01",
        view_id: "upload.overview.tech_table",
        job: { job_id: "djob-77", state: "queued", format: "png", attempt: 1 },
        status_url: "/v1/documentation/jobs/djob-77",
        print_revision_id: "dprev-1",
        document_id: "doc-1",
        print_kind: "V01",
        profile_id: "figure-landscape",
      },
    });
    render(<VisualExportButton viewId="upload.overview.tech_table" label="Скачать PNG: типы колонок" />);
    fireEvent.click(screen.getByTestId("visual-export-upload.overview.tech_table"));
    await waitFor(() =>
      expect(screen.getByTestId("visual-export-status-upload.overview.tech_table")).toBeTruthy(),
    );
    expect(screen.getByRole("status").textContent).toContain("djob-77");
    expect(screen.getByRole("status").textContent).toContain("Документах исследования");
    expect(requestVisualExportMock).toHaveBeenCalledWith(
      expect.objectContaining({
        runId: "RUN-P10A01",
        viewId: "upload.overview.tech_table",
        expectedContextId: "ctx-1",
      }),
    );
  });

  it("409 context_changed -- человеческая причина, кнопка не остаётся в queued", async () => {
    resolveCurrentRunMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-P10A01", context_id: "ctx-old" },
    });
    requestVisualExportMock.mockResolvedValue({
      ok: false,
      status: 409,
      error: { code: "context_changed", message: "context изменился" },
    });
    render(<VisualExportButton viewId="upload.overview.tech_table" />);
    fireEvent.click(screen.getByTestId("visual-export-upload.overview.tech_table"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("обновите представление");
    expect(screen.getByTestId("visual-export-upload.overview.tech_table").getAttribute("data-export-state")).toBe("error");
  });

  it("сеть недоступна (status=null) -- честный offline", async () => {
    resolveCurrentRunMock.mockResolvedValue({ ok: false, status: null });
    render(<VisualExportButton viewId="upload.overview.tech_table" />);
    fireEvent.click(screen.getByTestId("visual-export-upload.overview.tech_table"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Сеть недоступна");
    expect(requestVisualExportMock).not.toHaveBeenCalled();
  });

  it("run отсутствует -- «Исследование не выбрано», POST не выполняется", async () => {
    resolveCurrentRunMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: null },
    });
    render(<VisualExportButton viewId="upload.overview.tech_table" />);
    fireEvent.click(screen.getByTestId("visual-export-upload.overview.tech_table"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Исследование не выбрано");
    expect(requestVisualExportMock).not.toHaveBeenCalled();
  });

  it("chart-view без сериализации -- локальный отказ до POST (не фабрикуется)", async () => {
    resolveCurrentRunMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-P10A01", context_id: "ctx-1" },
    });
    render(
      <VisualExportButton
        viewId="upload.chart.series"
        getScreenSvg={() => null}
      />,
    );
    fireEvent.click(screen.getByTestId("visual-export-upload.chart.series"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Печатная геометрия графика не приложена");
    expect(requestVisualExportMock).not.toHaveBeenCalled();
  });

  it("disabled с причиной -- причина видна, клик невозможен", () => {
    render(
      <VisualExportButton
        viewId="preprocessing.scaling.overview"
        disabled
        disabledReason="result_not_frozen -- откройте представление"
      />,
    );
    const button = screen.getByTestId("visual-export-preprocessing.scaling.overview");
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByTestId("visual-export-disabled-reason-preprocessing.scaling.overview").textContent,
    ).toContain("result_not_frozen");
  });

  it("aria-label несёт accessible название вида (§10.1)", () => {
    render(
      <VisualExportButton viewId="validation.ranges.overview" label="Скачать PNG: диапазоны" />,
    );
    expect(
      screen.getByLabelText("Скачать PNG: Скачать PNG: диапазоны") ?? screen.getByRole("button"),
    ).toBeTruthy();
  });
});

describe("VisualExportChartScope (PGV-10)", () => {
  it("кнопка внутри скоупа сериализует ref-контейнер (не первый SVG документа)", async () => {
    resolveCurrentRunMock.mockResolvedValue({
      ok: true,
      status: 200,
      data: { run_id: "RUN-P10A01", context_id: "ctx-1" },
    });
    requestVisualExportMock.mockResolvedValue({
      ok: true,
      status: 202,
      data: {
        job: { job_id: "djob-9", state: "queued", format: "png", attempt: 1 },
        status_url: "/v1/documentation/jobs/djob-9",
        print_revision_id: "dprev-9",
        document_id: "doc-9",
      },
    });
    render(
      <div>
        <svg id="document-first-svg" />
        <VisualExportChartScope viewId="upload.chart.series" label="ряд">
          <svg id="own-chart-svg" />
        </VisualExportChartScope>
      </div>,
    );
    fireEvent.click(screen.getByTestId("visual-export-upload.chart.series"));
    await waitFor(() => expect(requestVisualExportMock).toHaveBeenCalled());
    const call = requestVisualExportMock.mock.calls[0][0] as { screenSvg?: string };
    expect(call.screenSvg).toContain("own-chart-svg");
    expect(call.screenSvg).not.toContain("document-first-svg");
  });
});
