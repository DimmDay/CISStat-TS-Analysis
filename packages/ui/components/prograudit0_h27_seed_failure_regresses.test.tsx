// packages/ui/components/prograudit0_h27_seed_failure_regresses.test.tsx
//
// AUDIT-0 (plan_progress_audit.md §4, действие 2) -- НАБЛЮДЕНИЕ H27.
// Гипотеза: отказ EDA seed может понизить уже просмотренные исследования.
// Основание: неуспешный GET /trace даёт пустой seed-set (best-effort,
// TsAnalysisEDA.tsx:1006-1045), следующая полная карта содержит pending
// для ранее done-проверок; бэкенд last-wins записывает регресс.
//
// ⚠️ Это наблюдательный пин ТЕКУЩЕГО (дефектного) поведения -- НЕ
// acceptance-тест. После AUDIT-3 (устойчивый seed/монотонность в своём
// контексте) файл обязан быть заменён/обновлён как versioned-обновление
// контракта (Донастройка_2 п.3). Мокирует только свои URL; реальная сеть
// в jest недоступна.

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TsAnalysisEDA } from "./TsAnalysisEDA";

let mockActiveDataset: { datasetId?: string; name: string; rows: number; sizeLabel: string } | null = {
  datasetId: "D-AUDIT0-H27",
  name: "h27.csv",
  rows: 40,
  sizeLabel: "1 KB",
};

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ activeDataset: mockActiveDataset }),
}));

const edaPosts: Record<string, string>[] = [];

function jsonOk(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

function makeRouter(opts: { traceStatus: number; seededDone: string[] }) {
  return function router(input: RequestInfo | URL, init?: RequestInit) {
    const url = String(input);
    if (url.includes("/v1/progress/trace")) {
      if (opts.traceStatus !== 200) {
        return Promise.resolve({ ok: false, status: opts.traceStatus, json: () => Promise.resolve({}) });
      }
      const node_statuses: Record<string, string> = {};
      opts.seededDone.forEach((id) => { node_statuses[`eda/${id}`] = "done"; });
      return jsonOk({ run_id: "RUN-H27", node_statuses, events: [] });
    }
    if (url.includes("/v1/progress/eda-checks")) {
      edaPosts.push(JSON.parse(String(init?.body)).checks as Record<string, string>);
      return jsonOk({ received: 10 });
    }
    if (url.includes("/target-column")) {
      const selected = init?.method === "POST" ? JSON.parse(String(init.body)).column : "Price";
      return jsonOk({ target_column: selected, suggested_column: "Price", target_column_source: "user", available_columns: ["Year", "Price", "Volume"], has_dataset: true });
    }
    if (url.includes("/dataset/passport/status")) {
      const emptyPoint = { captured: false, captured_at: null, is_stale: null, fingerprint: null, history_count: 0 };
      return jsonOk({
        has_dataset: true, target_column: "Price", date_column: "Date", series_ready: true, reason: null,
        current_fingerprint: "current",
        start: { ...emptyPoint, captured: true, is_stale: false, fingerprint: "current", history_count: 1 },
        validation: emptyPoint, exit: emptyPoint,
        modeling_entry: { ...emptyPoint, checkpoint_id: null, snapshot_id: null, source_stage: null, reused_snapshot: null },
      });
    }
    if (url.includes("/date-column")) {
      return jsonOk({ date_column: "Date", suggested_column: "Date", candidates: [{ name: "Date", score: 1 }], has_dataset: true, passport_history_reset: false });
    }
    if (url.includes("/dataset/stats")) {
      return jsonOk({
        min_non_null_for_stats: 2,
        columns: [
          { name: "Year", non_null_count: 4, stats: { mean: 2021.5, median: 2021.5, std: 1.29, skewness: 0, kurtosis: -1.2, q1: 2020.75, q3: 2022.25, iqr: 1.5, distribution_hint: "Близко к нормальному" } },
          { name: "Price", non_null_count: 4, stats: { mean: 25, median: 25, std: 12.91, skewness: 0, kurtosis: -1.2, q1: 17.5, q3: 32.5, iqr: 15, distribution_hint: "Близко к нормальному" } },
          { name: "Volume", non_null_count: 4, stats: { mean: 250, median: 250, std: 129.1, skewness: 0, kurtosis: -1.2, q1: 175, q3: 325, iqr: 150, distribution_hint: "Близко к нормальному" } },
        ],
      });
    }
    if (url.includes("/dataset/eda-correlation")) {
      return jsonOk({ column: "Price", applicable: true, reason: null, n_observations: 80, missing_count: 0, requested_max_lags: 40, max_lag: 20, alpha: 0.05, order_source: "time_column", order_column: "Date", order_warning: null, frequency: "D", acf: [{ lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false }, { lag: 1, value: 0.7, confidence_lower: -0.2, confidence_upper: 0.2, significant: true }], pacf: [{ lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false }, { lag: 1, value: 0.65, confidence_lower: -0.2, confidence_upper: 0.2, significant: true }], significant_acf_lags: [1], significant_pacf_lags: [1], ljung_box_lag: 10, ljung_box_pvalue: 0.002, is_white_noise: false, suggested_p: 1, suggested_q: 1 });
    }
    if (url.includes("/dataset/eda-seasonality")) {
      return jsonOk({ column: "Price", applicable: true, reason: null, n_observations: 240, missing_count: 0, min_cycles: 3, max_candidates: 5, max_period: 80, detrend: "linear", window: "hann", order_source: "time_column", order_column: "Date", order_warning: null, frequency: "D", spectral_entropy: 0.2, dominant_period: 12, dominant_strength: 0.84, confirmed_periods: 1, recommendations: [], fft: [{ frequency: 1 / 12, period: 12, amplitude: 3, power: null, is_peak: true }], periodogram: [{ frequency: 1 / 12, period: 12, amplitude: null, power: 4.5, is_peak: true }], candidates: [{ rank: 1, period: 12, period_rounded: 12, frequency: 1 / 12, amplitude: 3, power: 4.5, power_share: 75, prominence: 4.2, spectral_snr: 30, autocorrelation: 0.9, seasonal_strength: 0.84, cycles: 20, confirmed: true, calendar_hint: null, harmonic_of: null }], phase_period: 12 });
    }
    return new Promise(() => {});
  };
}

describe("AUDIT-0 H27 (наблюдение): отказ seed понижает уже просмотренные исследования", () => {
  beforeEach(() => {
    edaPosts.length = 0;
    mockActiveDataset = { datasetId: "D-AUDIT0-H27", name: "h27.csv", rows: 40, sizeLabel: "1 KB" };
  });

  it("H27: карта после сорвавшегося seed содержит pending для ранее done-проверок", async () => {
    // ── Фаза 1: seed 200 c прошлыми фактами descriptive+correlation.
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter({ traceStatus: 200, seededDone: ["descriptive", "correlation"] })(input, init)) as jest.Mock;
    const view = render(<TsAnalysisEDA />);

    // Якорь = {descriptive: done, correlation: done, остальные pending} --
    // отчёта после seed НЕТ (снапшот равен якорю).
    await waitFor(() => expect(
      screen.queryAllByRole("button", { name: /Сезонность и периодичность/ }).length,
    ).toBeGreaterThan(0), { timeout: 4000 });
    await new Promise((r) => setTimeout(r, 150));
    expect(edaPosts.length).toBe(0);

    // Открытие третьего исследования -> POST #1: backend теперь знает
    // descriptive+correlation+seasonality как done (приёмка факта).
    fireEvent.click(screen.getByRole("button", { name: /Сезонность и периодичность/ }));
    await waitFor(() => expect(edaPosts.length).toBe(1), { timeout: 4000 });
    expect(edaPosts[0]["descriptive"]).toBe("done");
    expect(edaPosts[0]["correlation"]).toBe("done");
    expect(edaPosts[0]["seasonality"]).toBe("done");

    // ── Фаза 2: перемонтирование; seed /trace -- 500 (best-effort даёт
    // пустое множество). Активная descriptive (done по stats) становится
    // единственным «просмотренным» -> POST #2.
    view.unmount();
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter({ traceStatus: 500, seededDone: [] })(input, init)) as jest.Mock;
    render(<TsAnalysisEDA />);
    await waitFor(() => expect(edaPosts.length).toBe(2), { timeout: 4000 });

    // Наблюдение H27: отправленная карта понижает correlation и
    // seasonality (были done в фазе 1 / в seed) до pending. Бэкенд
    // last-wins (PAYLOAD_STATUS) записал бы регресс -- P25 подтверждает
    // запись running на живом контуре.
    expect(edaPosts[1]["descriptive"]).toBe("done");
    expect(edaPosts[1]["correlation"]).toBe("pending");
    expect(edaPosts[1]["seasonality"]).toBe("pending");
  });
});
