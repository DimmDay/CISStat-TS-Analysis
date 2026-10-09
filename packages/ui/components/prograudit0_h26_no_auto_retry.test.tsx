// packages/ui/components/prograudit0_h26_no_auto_retry.test.tsx
//
// AUDIT-0 (plan_progress_audit.md §4, действие 2) -- НАБЛЮДЕНИЕ H26.
// Гипотеза: при неизменном snapshot один отказ доставки UI останется без
// автоматического повтора (основание: ref сбрасывается, зависимости
// effect не меняются -- TsAnalysisEDA.tsx:1046-1091, тот же контур
// TsAnalysisValidation.tsx:410-442).
//
// ⚠️ Это наблюдательный пин ТЕКУЩЕГО (дефектного) поведения -- НЕ
// acceptance-тест. После AUDIT-2B (восстановимая доставка: report_id,
// ограниченный retry с backoff) файл обязан быть заменён/обновлён как
// versioned-обновление контракта (Донастройка_2 п.3), не как правка под
// реализацию. Мокирует только свои URL; реальная сеть недоступна в jest.

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TsAnalysisEDA } from "./TsAnalysisEDA";

let mockActiveDataset: { datasetId?: string; name: string; rows: number; sizeLabel: string } | null = {
  datasetId: "D-AUDIT0-H26",
  name: "h26.csv",
  rows: 40,
  sizeLabel: "1 KB",
};

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ activeDataset: mockActiveDataset }),
}));

const ALL_IDS = [
  "descriptive", "correlation", "ih_analysis", "seasonality", "stationarity",
  "distribution", "structural", "feature_select", "validation_strategy", "model_matrix",
];

const edaPosts: Record<string, string>[] = [];
let traceGets = 0;

function jsonOk(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

function makeRouter(opts: { traceStatus: number; traceNodeStatuses: Record<string, string> }) {
  return function router(input: RequestInfo | URL, init?: RequestInit) {
    const url = String(input);
    if (url.includes("/v1/progress/trace")) {
      traceGets += 1;
      if (opts.traceStatus !== 200) {
        return Promise.resolve({ ok: false, status: opts.traceStatus, json: () => Promise.resolve({}) });
      }
      return jsonOk({ run_id: "RUN-H26", node_statuses: opts.traceNodeStatuses, events: [] });
    }
    if (url.includes("/v1/progress/eda-checks")) {
      edaPosts.push(JSON.parse(String(init?.body)).checks as Record<string, string>);
      return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
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
    // Прочие эндпоинты (паспорт, остальные профили) -- не нужны сценарию:
    // pending-promise, как дефолтный beforeEach существующих тестов.
    return new Promise(() => {});
  };
}

describe("AUDIT-0 H26 (наблюдение): отказ доставки без изменения snapshot не повторяется", () => {
  beforeEach(() => {
    edaPosts.length = 0;
    traceGets = 0;
    mockActiveDataset = { datasetId: "D-AUDIT0-H26", name: "h26.csv", rows: 40, sizeLabel: "1 KB" };
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter({ traceStatus: 200, traceNodeStatuses: {} })(input, init)) as jest.Mock;
  });

  it("H26: один POST после 500; без изменения snapshot повторов нет; смена snapshot возобновляет контур", async () => {
    render(<TsAnalysisEDA />);

    // Seed /trace 200 c пустыми node_statuses -> viewed={descriptive}
    // (активная остановка, статус done по stats) -> POST #1 -> 500.
    await waitFor(() => expect(edaPosts.length).toBe(1), { timeout: 4000 });
    expect(edaPosts[0]["descriptive"]).toBe("done");
    expect(edaPosts[0]["correlation"]).toBe("pending");

    // Без изменения snapshot: несколько макро/микро-тактов -- повторов НЕТ.
    await new Promise((r) => setTimeout(r, 120));
    expect(edaPosts.length).toBe(1);

    // Смена snapshot (просмотр второй остановки): контур возобновляется --
    // маркер был сброшен неудачей, отчёт повторяется с НОВЫМ снапшотом.
    fireEvent.click(screen.getByRole("button", { name: /Корреляция \(ACF\/PACF\)/ }));
    await waitFor(() => expect(edaPosts.length).toBe(2), { timeout: 4000 });
    expect(edaPosts[1]["descriptive"]).toBe("done");
    expect(edaPosts[1]["correlation"]).toBe("done");
    // Seed /trace за весь сценарий -- один (перезапусков seed нет).
    expect(traceGets).toBe(1);
  });
});
