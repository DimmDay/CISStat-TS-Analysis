// packages/ui/components/VisualExportButton.p10cert.test.tsx
//
// Независимая сертификация PGV-10 (сертификатор, корпус p10cert):
// оракулы кнопки «Скачать PNG» на СВОИХ данных -- локальный отказ без
// POST, честные причины, accessible-название, body-контракт.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const requestVisualExportMock = jest.fn();
const resolveCurrentRunMock = jest.fn();

jest.mock("../lib/visualExports", () => ({
  requestVisualExport: (...args: unknown[]) => requestVisualExportMock(...args),
  resolveCurrentRunForExport: () => resolveCurrentRunMock(),
  visualExportErrorText:
    jest.requireActual("../lib/visualExports").visualExportErrorText,
}));

import { VisualExportButton, VisualExportChartScope } from "./VisualExportButton";
import { serializeChartSvgSafe } from "../lib/serializeChartSvg";

const VIEW = "preprocessing.missing.overview";

beforeEach(() => {
  requestVisualExportMock.mockReset();
  resolveCurrentRunMock.mockReset();
  resolveCurrentRunMock.mockResolvedValue({
    ok: true,
    status: 200,
    data: { run_id: "RUN-P10CERT-U1", context_id: "ctx-p10cert-u1" },
  });
});

describe("p10cert VisualExportButton", () => {
  it("U6 queued: POST body несёт view_id/run/expected_context, показывается job", async () => {
    requestVisualExportMock.mockResolvedValue({
      ok: true,
      status: 202,
      data: {
        run_id: "RUN-P10CERT-U1",
        view_id: VIEW,
        job: { job_id: "djob-p10cert-u1", state: "queued", format: "png", attempt: 1 },
        status_url: "/v1/documentation/jobs/djob-p10cert-u1",
        print_revision_id: "dprev-p10cert",
        document_id: "doc-p10cert",
        print_kind: "V01",
        profile_id: "figure-landscape",
      },
    });
    render(<VisualExportButton viewId={VIEW} label="Пропуски: профиль" />);
    fireEvent.click(screen.getByTestId(`visual-export-${VIEW}`));
    await waitFor(() =>
      expect(screen.getByTestId(`visual-export-status-${VIEW}`).textContent).toContain(
        "djob-p10cert-u1",
      ),
    );
    expect(requestVisualExportMock).toHaveBeenCalledWith(
      expect.objectContaining({
        runId: "RUN-P10CERT-U1",
        viewId: VIEW,
        expectedContextId: "ctx-p10cert-u1",
      }),
    );
  });

  it("U7 chart-кнопка без геометрии -- локальный отказ ДО POST (не первый SVG)", async () => {
    render(
      <VisualExportButton
        viewId={VIEW}
        label="x"
        getScreenSvg={() => null}
      />,
    );
    fireEvent.click(screen.getByTestId(`visual-export-${VIEW}`));
    await waitFor(() =>
      expect(screen.getByTestId(`visual-export-error-${VIEW}`).textContent).toContain(
        "геометрия",
      ),
    );
    expect(requestVisualExportMock).not.toHaveBeenCalled();
  });

  it("U8 409 context_changed -- человеческая причина смены данных", async () => {
    requestVisualExportMock.mockResolvedValue({
      ok: false,
      status: 409,
      error: { code: "context_changed", message: "context изменился" },
    });
    render(<VisualExportButton viewId={VIEW} label="x" />);
    fireEvent.click(screen.getByTestId(`visual-export-${VIEW}`));
    await waitFor(() =>
      expect(screen.getByTestId(`visual-export-error-${VIEW}`).textContent).toContain(
        "Данные изменились после показа",
      ),
    );
  });

  it("U9 uniform-404 -- честная фраза среды без дисклоужения", async () => {
    requestVisualExportMock.mockResolvedValue({
      ok: false,
      status: 404,
      error: { code: "not_found", message: "Экспорт недоступен" },
    });
    render(<VisualExportButton viewId={VIEW} label="x" />);
    fireEvent.click(screen.getByTestId(`visual-export-${VIEW}`));
    await waitFor(() =>
      expect(screen.getByTestId(`visual-export-error-${VIEW}`).textContent).toContain(
        "Исследование недоступно в этой среде",
      ),
    );
  });

  it("U10 offline (status null) -- сетевая причина", async () => {
    resolveCurrentRunMock.mockResolvedValue({ ok: false, status: null });
    render(<VisualExportButton viewId={VIEW} label="x" />);
    fireEvent.click(screen.getByTestId(`visual-export-${VIEW}`));
    await waitFor(() =>
      expect(screen.getByTestId(`visual-export-error-${VIEW}`).textContent).toContain(
        "Сеть недоступна",
      ),
    );
    expect(requestVisualExportMock).not.toHaveBeenCalled();
  });

  it("U11 disabled+причина и aria-label честны", () => {
    render(
      <VisualExportButton
        viewId={VIEW}
        label="Пропуски: профиль"
        disabled
        disabledReason="Результат не зафиксирован"
      />,
    );
    const btn = screen.getByTestId(`visual-export-${VIEW}`) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("aria-label")).toContain("Скачать PNG");
    expect(
      screen.getByTestId(`visual-export-disabled-reason-${VIEW}`).textContent,
    ).toContain("не зафиксирован");
  });

  it("U12 VisualExportChartScope сериализует СВОЙ узел (не первый SVG документа)", () => {
    document.body.innerHTML =
      "<svg data-cert='foreign'><rect data-marker='FOREIGN'/></svg>" +
      "<div id='host'></div>";
    const { container } = render(
      <VisualExportChartScope viewId={VIEW} label="Пропуски">
        <svg data-cert="mine">
          <rect data-marker="MINE" />
        </svg>
      </VisualExportChartScope>,
      { container: document.getElementById("host") as HTMLElement },
    );
    const scope = container.querySelector(
      `[data-testid="export-chart-scope-${VIEW}"]`,
    ) as HTMLElement;
    expect(scope).toBeTruthy();
    // Внутри scope кнопка с getScreenSvg -- сериализация даёт МОЙ svg.
    const own = serializeChartSvgSafe(() => scope.querySelector("div"));
    expect(own).toContain("MINE");
    expect(own).not.toContain("FOREIGN");
  });
});
