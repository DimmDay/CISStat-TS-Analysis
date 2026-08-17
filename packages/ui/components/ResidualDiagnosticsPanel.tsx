"use client";

import { useCallback, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { Button } from "./Button";
import { getApiBase } from "../lib/apiClient";

export interface DiagnosticResult {
  test: string;
  applicable: boolean;
  applicable_if: string;
  statistic?: number | null;
  p_value?: number | null;
  status: "pass" | "warning" | "fail";
  reason?: string | null;
}

export interface ResidualDiagnosticsResponse {
  model_id: string;
  target_column: string;
  n_observations: number;
  residuals_count: number;
  alpha: number;
  diagnostics: DiagnosticResult[];
}

interface ResidualDiagnosticsPanelProps {
  modelId: string;
  params?: Record<string, unknown>;
  autoRun?: boolean;
}

const API_BASE = getApiBase();

const TEST_LABELS: Record<string, string> = {
  ljung_box: "Ljung–Box",
  jarque_bera: "Jarque–Bera",
  arch_lm: "ARCH-LM",
  durbin_watson: "Durbin–Watson",
};

const STATUS_LABELS = {
  pass: "PASS",
  warning: "WARNING",
  fail: "FAIL",
} as const;

function formatNumber(value?: number | null): string {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(4);
}

function statusClass(status: DiagnosticResult["status"]): string {
  if (status === "pass") return "text-green-700 bg-green-50 border-green-200";
  if (status === "warning") return "text-amber-700 bg-amber-50 border-amber-200";
  return "text-red-700 bg-red-50 border-red-200";
}

export function ResidualDiagnosticsPanel({
  modelId,
  params = {},
  autoRun = false,
}: ResidualDiagnosticsPanelProps) {
  const [result, setResult] = useState<ResidualDiagnosticsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runDiagnostics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/internal/models/diagnostics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ model_id: modelId, params }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
        throw new Error(detail);
      }
      setResult(body as ResidualDiagnosticsResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка диагностики остатков");
    } finally {
      setLoading(false);
    }
  }, [modelId, params]);

  if (autoRun && !result && !loading && !error) {
    void runDiagnostics();
  }

  return (
    <section className="mt-3 rounded-lg border border-neutral-200 bg-white p-3" data-testid="residual-diagnostics-panel">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h4 className="text-sm font-semibold text-neutral-800">Диагностика остатков</h4>
          <p className="text-[10px] text-neutral-500">Модель: {modelId}</p>
        </div>
        <Button
          onClick={() => void runDiagnostics()}
          disabled={loading}
          className="text-xs"
          data-testid="run-diagnostics-btn"
        >
          {loading ? (
            <span className="flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Расчёт…</span>
          ) : (
            <span className="flex items-center gap-1"><RefreshCw size={12} /> Запустить</span>
          )}
        </Button>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700" data-testid="diagnostics-error">
          {error}
        </div>
      )}

      {result && (
        <>
          <div className="grid grid-cols-3 gap-2 mb-3 text-[10px] text-neutral-500">
            <span>Ряд: <strong className="text-neutral-700">{result.target_column}</strong></span>
            <span>Наблюдений: <strong className="text-neutral-700">{result.n_observations}</strong></span>
            <span>Остатков: <strong className="text-neutral-700">{result.residuals_count}</strong></span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-[11px]" data-testid="diagnostics-table">
              <thead>
                <tr className="border-b border-neutral-200 text-left text-neutral-500">
                  <th className="py-1 pr-2">Тест</th>
                  <th className="py-1 pr-2">Статус</th>
                  <th className="py-1 pr-2">Statistic</th>
                  <th className="py-1 pr-2">p-value</th>
                  <th className="py-1">Применимость</th>
                </tr>
              </thead>
              <tbody>
                {result.diagnostics.map((item) => (
                  <tr key={item.test} className="border-b border-neutral-100 last:border-0">
                    <td className="py-2 pr-2 font-medium text-neutral-800">{TEST_LABELS[item.test] ?? item.test}</td>
                    <td className="py-2 pr-2">
                      <span className={`inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${statusClass(item.status)}`}>
                        {item.applicable ? STATUS_LABELS[item.status] : "N/A"}
                      </span>
                    </td>
                    <td className="py-2 pr-2 font-mono">{formatNumber(item.statistic)}</td>
                    <td className="py-2 pr-2 font-mono">{formatNumber(item.p_value)}</td>
                    <td className="py-2 text-neutral-500">
                      {item.applicable ? "Да" : item.reason ?? item.applicable_if}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
