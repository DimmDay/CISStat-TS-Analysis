import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ResidualDiagnosticsPanel } from "./ResidualDiagnosticsPanel";

const mockFetch = jest.fn();
// @ts-ignore
window.fetch = mockFetch;

describe("ResidualDiagnosticsPanel", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("runs session-backed diagnostics and renders all four tests", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        model_id: "ets",
        target_column: "value",
        n_observations: 120,
        residuals_count: 120,
        alpha: 0.05,
        diagnostics: [
          { test: "ljung_box", applicable: true, applicable_if: "n_observations > lags", statistic: 2.1, p_value: 0.14, status: "pass" },
          { test: "jarque_bera", applicable: true, applicable_if: "n_observations >= 8", statistic: 4.2, p_value: 0.12, status: "pass" },
          { test: "arch_lm", applicable: true, applicable_if: "sufficient observations", statistic: 3.2, p_value: 0.08, status: "pass" },
          { test: "durbin_watson", applicable: true, applicable_if: "finite residuals", statistic: 1.91, p_value: null, status: "pass" },
        ],
      }),
    });

    render(<ResidualDiagnosticsPanel modelId="ets" />);
    fireEvent.click(screen.getByTestId("run-diagnostics-btn"));

    await waitFor(() => expect(screen.getByTestId("diagnostics-table")).toBeInTheDocument());
    expect(screen.getByText("Ljung–Box")).toBeInTheDocument();
    expect(screen.getByText("Jarque–Bera")).toBeInTheDocument();
    expect(screen.getByText("ARCH-LM")).toBeInTheDocument();
    expect(screen.getByText("Durbin–Watson")).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/internal/models/diagnostics"),
      expect.objectContaining({ method: "POST", credentials: "include" })
    );
  });

  it("renders N/A and reason for an inapplicable conditional test", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        model_id: "ets",
        target_column: "value",
        n_observations: 12,
        residuals_count: 12,
        alpha: 0.05,
        diagnostics: [
          { test: "arch_lm", applicable: false, applicable_if: "n_observations > arch_lags + 1", status: "warning", reason: "Not enough residuals for ARCH-LM" },
        ],
      }),
    });

    render(<ResidualDiagnosticsPanel modelId="ets" />);
    fireEvent.click(screen.getByTestId("run-diagnostics-btn"));

    await waitFor(() => expect(screen.getByText("N/A")).toBeInTheDocument());
    expect(screen.getByText("Not enough residuals for ARCH-LM")).toBeInTheDocument();
  });

  it("shows API error", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: "Target column is not selected" }),
    });

    render(<ResidualDiagnosticsPanel modelId="ets" />);
    fireEvent.click(screen.getByTestId("run-diagnostics-btn"));

    await waitFor(() => expect(screen.getByTestId("diagnostics-error")).toHaveTextContent("Target column is not selected"));
  });
});