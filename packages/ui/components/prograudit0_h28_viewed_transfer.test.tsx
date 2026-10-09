// packages/ui/components/prograudit0_h28_viewed_transfer.test.tsx
//
// AUDIT-0 (plan_progress_audit.md §4, действие 2) -- НАБЛЮДЕНИЕ H28.
// Гипотеза: при смене цели (или in-place коррекции) UI переносит
// EDA-просмотры прежних данных. Основание: сброс вселенной фактов keyed
// ТОЛЬКО по datasetKey (TsAnalysisEDA.tsx:1000-1005, :1045 -- deps
// [datasetKey]); target/revision в ключе не участвуют.
//
// ⚠️ Это наблюдательный пин ТЕКУЩЕГО (дефектного) поведения -- НЕ
// acceptance-тест. После AUDIT-3 (контекст цели/ревизии в keyed-сбросе)
// файл обязан быть заменён/обновлён как versioned-обновление контракта
// (Донастройка_2 п.3). Мокирует только свои URL; реальная сеть в jest
// недоступна.

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TsAnalysisEDA } from "./TsAnalysisEDA";

let mockActiveDataset: { datasetId?: string; name: string; rows: number; sizeLabel: string } | null = {
  datasetId: "D-AUDIT0-H28",
  name: "h28.csv",
  rows: 40,
  sizeLabel: "1 KB",
};

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ activeDataset: mockActiveDataset }),
}));

const edaPosts: Record<string, string>[] = [];
let traceGets = 0;

function jsonOk(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

function makeRouter() {
  return function router(input: RequestInfo | URL, init?: RequestInit) {
    const url = String(input);
    if (url.includes("/v1/progress/trace")) {
      traceGets += 1;
      return jsonOk({ run_id: "RUN-H28", node_statuses: {}, events: [] });
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
    return new Promise(() => {});
  };
}

describe("AUDIT-0 H28 (наблюдение): смена цели при том же datasetKey переносит просмотры", () => {
  beforeEach(() => {
    edaPosts.length = 0;
    traceGets = 0;
    mockActiveDataset = { datasetId: "D-AUDIT0-H28", name: "h28.csv", rows: 40, sizeLabel: "1 KB" };
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter()(input, init)) as jest.Mock;
  });

  it("H28: viewed переносится через смену цели; повторного seed нет", async () => {
    render(<TsAnalysisEDA />);

    // Seed (один GET /trace) -> descriptive (активная, done) -> POST #1.
    await waitFor(() => expect(edaPosts.length).toBe(1), { timeout: 4000 });
    expect(edaPosts[0]["descriptive"]).toBe("done");
    expect(traceGets).toBe(1);

    // Смена цели Price -> Volume при НЕИЗМЕННОМ datasetId (datasetKey
    // константeн) -- POST /target-column, перезагрузка данных признака.
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" });
    fireEvent.change(selector, { target: { value: "Volume" } });
    await waitFor(() => expect(selector).toHaveValue("Volume"), { timeout: 4000 });

    // Reset-эффект keyed по datasetKey НЕ сработал: повторного seed нет.
    await new Promise((r) => setTimeout(r, 150));
    expect(traceGets).toBe(1);
    expect(edaPosts.length).toBe(1);

    // Просмотр второй остановки уже В НОВОМ целевом контексте -> POST #2:
    // карта несёт descriptive=done из ПРЕЖНЕЙ вселенной (просмотр
    // перенесён) + correlation=done новой.
    fireEvent.click(screen.getByRole("button", { name: /Корреляция \(ACF\/PACF\)/ }));
    await waitFor(() => expect(edaPosts.length).toBe(2), { timeout: 4000 });
    expect(edaPosts[1]["descriptive"]).toBe("done");
    expect(edaPosts[1]["correlation"]).toBe("done");
  });
});
