// packages/ui/components/prograudit0_h28_viewed_transfer.test.tsx
//
// AUDIT-0 (plan_progress_audit.md §4, действие 2) -- НАБЛЮДЕНИЕ H28,
// VERSIONED-ОБНОВЛЕНИЕ AUDIT-3.
//
// Было (пин дефекта, до AUDIT-3): сброс вселенной фактов keyed ТОЛЬКО
// по datasetKey (deps [datasetKey]); target/revision в ключе не
// участвовали -- при смене цели при неизменном datasetId просмотры
// прежней целевой вселенной переносились в карту новой (H28).
//
// Стало (пин контракта AUDIT-3, план §13: «EDA достижения объединяются
// монотонно ВНУТРИ своего контекста; новая цель/ревизия не наследует
// current-viewed от старой»):
//   * ключ вселенной фактов = датасет + ЦЕЛЬ (context_id =
//     f(run, data#revision, target, temporal) -- смена цели сдвигает
//     контекст расчёта);
//   * смена цели -- сброс множества просмотров + re-seed полной
//     проекции (GET /trace);
//   * карта нового контекста НЕ переносит просмотры прежней цели.
//
// Мокирует только свои URL; реальная сеть в jest недоступна.

import "@testing-library/jest-dom";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
let delayTargetReply = false;

function jsonOk(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

function makeRouter() {
  return function router(input: RequestInfo | URL, init?: RequestInit) {
    const url = String(input);
    if (url.includes("/v1/progress/trace")) {
      traceGets += 1;
      return jsonOk({ run_id: "RUN-H28", context_id: "ctx-h280000000001", node_statuses: {}, events: [], projection_complete: true });
    }
    if (url.includes("/v1/progress/eda-checks")) {
      edaPosts.push(JSON.parse(String(init?.body)).checks as Record<string, string>);
      return jsonOk({ received: 10 });
    }
    if (url.includes("/target-column")) {
      const selected = init?.method === "POST" ? JSON.parse(String(init.body)).column : "Price";
      const body = { target_column: selected, suggested_column: "Price", target_column_source: "user", available_columns: ["Year", "Price", "Volume"], has_dataset: true };
      // Also exercise a real task boundary, not only Promise microtasks.
      if (delayTargetReply && init?.method === "POST") {
        return new Promise(resolve => setTimeout(() => resolve(jsonOk(body)), 0));
      }
      return jsonOk(body);
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
      return jsonOk({ column: "Volume", applicable: true, reason: null, n_observations: 80, missing_count: 0, requested_max_lags: 40, max_lag: 20, alpha: 0.05, order_source: "time_column", order_column: "Date", order_warning: null, frequency: "D", acf: [{ lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false }, { lag: 1, value: 0.7, confidence_lower: -0.2, confidence_upper: 0.2, significant: true }], pacf: [{ lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false }, { lag: 1, value: 0.65, confidence_lower: -0.2, confidence_upper: 0.2, significant: true }], significant_acf_lags: [1], significant_pacf_lags: [1], ljung_box_lag: 10, ljung_box_pvalue: 0.002, is_white_noise: false, suggested_p: 1, suggested_q: 1 });
    }
    return new Promise(() => {});
  };
}

describe("AUDIT-0 H28 (versioned AUDIT-3): смена цели -- новая вселенная фактов EDA", () => {
  beforeEach(() => {
    edaPosts.length = 0;
    traceGets = 0;
    mockActiveDataset = { datasetId: "D-AUDIT0-H28", name: "h28.csv", rows: 40, sizeLabel: "1 KB" };
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter()(input, init)) as jest.Mock;
  });

  it.each([false, true])("H28: просмотры прежней цели не переносятся в карту новой (сброс + re-seed); delayed=%s", async delayed => {
    delayTargetReply = delayed;
    render(<TsAnalysisEDA />);

    // Seed (GET /trace) -> descriptive (активная, done) -> POST #1:
    // поставка запрашивает биндинг (GET /trace, AUDIT-2B I3).
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" }, { timeout: 4000 });
    await waitFor(() => expect(edaPosts.length).toBe(1), { timeout: 4000 });
    expect(edaPosts[0]["descriptive"]).toBe("done");
    expect(edaPosts[0]["correlation"]).toBe("pending");

    // Просмотр корреляции в контексте цели Price -> POST #2.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Корреляция \(ACF\/PACF\)/ }));
    });
    await waitFor(() => expect(edaPosts.length).toBe(2), { timeout: 4000 });
    expect(edaPosts[1]["correlation"]).toBe("done");

    // Смена цели Price -> Volume при НЕИЗМЕННОМ datasetId (datasetKey
    // константен) -- POST /target-column.
    // setColumn awaits POST/json before applying the new universe.
    await act(async () => {
      fireEvent.change(selector, { target: { value: "Volume" } });
    });
    await waitFor(() => expect(selector).toHaveValue("Volume"), { timeout: 4000 });

    // Контракт AUDIT-3: смена цели -- НОВАЯ вселенная фактов -- сброс
    // множества просмотров + re-seed полной проекции (GET /trace #3+).
    await waitFor(() => {
      expect(traceGets).toBeGreaterThanOrEqual(3);
    }, { timeout: 4000 });

    // Активная correlation показана и в новом контексте -- честный
    // НОВЫЙ просмотр -> POST #3. Карта нового контекста НЕ переносит
    // просмотры прежней цели: correlation -- новый просмотр (done),
    // descriptive просмотрена ТОЛЬКО в прежней вселенной (pending).
    await waitFor(() => {
      expect(edaPosts).toHaveLength(3);
      expect(edaPosts[2]["correlation"]).toBe("done");
      expect(edaPosts[2]["descriptive"]).toBe("pending");
    }, { timeout: 4000 });
  });
});
