// packages/ui/components/prograudit3_eda_seed_freshness.test.tsx
//
// AUDIT-3 (plan_progress_audit.md §13) -- оракулы UI-стороны: seed из
// ПОЛНОЙ проекции с watermark, контекстная свежесть seed-фактов и
// вселенная фактов по цели (H28).
//
//   S1: seed берёт ТОЛЬКО context-применимые (validity="current")
//       done-факты 13-полевого контракта /trace (AUDIT-5B); stale
//       (устаревшее) и unknown (легаси) не сеются -- карта не
//       воскрешает просмотры прежнего контекста (H28).
//   S2: отказ seed (GET /trace 500) УДЕРЖИВАЕТ отчёт -- разрушительная
//       пустая/все-pending карта поверх known history не отправляется
//       (H27, план §13: «Если seed не получен, не отправлять
//       разрушительную пустую карту»); новый просмотр -- ретрай seed.
//   S3: деградация проекции (projection_complete=false, session_tail)
//       -- хвост не выдаётся за полную историю -- отчёт удерживается.
//   S4: смена цели при том же datasetId -- НОВАЯ вселенная фактов
//       (H28): сброс + re-seed; просмотры прежней цели не переносятся.
//   S5: контроль якоря при remount (прежняя семантика PROGR-18
//       сохранена: отчёт только по НОВОМУ просмотру).
//
// Мокирует только свои URL; реальная сеть в jest недоступна.
// Свои сценарные данные (D-AUDIT3-*, c3-*), не копии пинов AUDIT-0.

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TsAnalysisEDA } from "./TsAnalysisEDA";

let mockActiveDataset: { datasetId?: string; name: string; rows: number; sizeLabel: string } | null = {
  datasetId: "D-AUDIT3",
  name: "audit3.csv",
  rows: 40,
  sizeLabel: "1 KB",
};

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ activeDataset: mockActiveDataset }),
}));

const edaPosts: Record<string, string>[] = [];

interface TraceOpts {
  status: number;
  projectionComplete?: boolean;
  nodes?: Array<{ stage: string; node_id: string; status: string; validity?: string | null }>;
  flatStatuses?: Record<string, string>;
}

function jsonOk(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

function makeRouter(opts: TraceOpts) {
  return function router(input: RequestInfo | URL, init?: RequestInit) {
    const url = String(input);
    if (url.includes("/v1/progress/trace")) {
      if (opts.status !== 200) {
        return Promise.resolve({ ok: false, status: opts.status, json: () => Promise.resolve({}) });
      }
      const body: Record<string, unknown> = {
        run_id: "RUN-AUDIT3",
        context_id: "ctx-audit300000001",
        events: [],
        projection_complete: opts.projectionComplete !== false,
        node_statuses: opts.flatStatuses ?? {},
      };
      if (opts.nodes) body.nodes = opts.nodes;
      return jsonOk(body);
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

function edaNode(nodeId: string, status: string, validity?: string | null) {
  return { stage: "eda", node_id: nodeId, status, validity };
}

async function settle(ms = 150) {
  await new Promise((r) => setTimeout(r, ms));
}

describe("AUDIT-3: EDA seed из полной проекции, свежесть и вселенная по цели", () => {
  beforeEach(() => {
    edaPosts.length = 0;
    mockActiveDataset = { datasetId: "D-AUDIT3", name: "audit3.csv", rows: 40, sizeLabel: "1 KB" };
  });

  it("S1: сеются только context-применимые (current) done-факты; stale/unknown не воскрешаются", async () => {
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter({
        status: 200,
        nodes: [
          edaNode("descriptive", "done", "current"),
          edaNode("correlation", "done", "stale"),
          edaNode("seasonality", "done", "unknown"),
        ],
        flatStatuses: {
          "eda/descriptive": "done",
          "eda/correlation": "done",
          "eda/seasonality": "done",
        },
      })(input, init)) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findAllByRole("button", { name: /Сезонность и периодичность/ }, { timeout: 4000 });
    await settle();
    // Якорь = только descriptive (current); активная descriptive
    // просмотрена заново -- снапшот равен якорю, отчёта нет.
    expect(edaPosts.length).toBe(0);

    // Новый просмотр: карта несёт descriptive=done (seed current),
    // correlation -- pending (stale НЕ сеется, не воскрешается),
    // seasonality -- done (честный НОВЫЙ просмотр).
    fireEvent.click(screen.getByRole("button", { name: /Сезонность и периодичность/ }));
    await waitForPosts(1);
    expect(edaPosts[0]["descriptive"]).toBe("done");
    expect(edaPosts[0]["correlation"]).toBe("pending");
    expect(edaPosts[0]["seasonality"]).toBe("done");
  });

  it("S2: отказ seed удерживает отчёт; новый просмотр ретраит seed", async () => {
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter({ status: 500 })(input, init)) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findAllByRole("button", { name: /Сезонность и периодичность/ }, { timeout: 4000 });
    await settle(250);
    // Активная descriptive просмотрена, но seed не получен -- отчёт
    // УДЕРЖИВАЕТСЯ (не разрушительная все-pending карта).
    expect(edaPosts.length).toBe(0);

    // Новый просмотр -- ретрай seed (опять 500) -- по-прежнему held.
    fireEvent.click(screen.getByRole("button", { name: /Сезонность и периодичность/ }));
    await settle(250);
    expect(edaPosts.length).toBe(0);
  });

  it("S3: деградация проекции (session_tail) удерживает отчёт", async () => {
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter({ status: 200, projectionComplete: false })(input, init)) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findAllByRole("button", { name: /Сезонность и периодичность/ }, { timeout: 4000 });
    await settle(250);
    expect(edaPosts.length).toBe(0);
  });

  it("S4: смена цели при том же datasetId -- новая вселенная: просмотры не переносятся", async () => {
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter({ status: 200 })(input, init)) as jest.Mock;
    render(<TsAnalysisEDA />);
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" }, { timeout: 4000 });
    await waitForPosts(1);
    // POST #1: descriptive просмотрена в контексте цели Price.
    expect(edaPosts[0]["descriptive"]).toBe("done");
    expect(edaPosts[0]["correlation"]).toBe("pending");

    fireEvent.click(screen.getByRole("button", { name: /Корреляция \(ACF\/PACF\)/ }));
    await waitForPosts(2);
    expect(edaPosts[1]["correlation"]).toBe("done");

    // Смена цели Price -> Volume при неизменном datasetId: сброс
    // множества просмотров + re-seed (новая применимость, H28).
    fireEvent.change(selector, { target: { value: "Volume" } });
    await screen.findByDisplayValue("Volume", {}, { timeout: 4000 });
    await settle(250);
    // Активная correlation (показана) -- честный просмотр НОВОГО
    // контекста; descriptive просмотрена только в ПРЕЖНЕЙ вселенной --
    // перенос просмотров устранён: в новой карте она pending.
    await waitForPosts(3);
    expect(edaPosts[2]["correlation"]).toBe("done");
    expect(edaPosts[2]["descriptive"]).toBe("pending");
  });

  it("S5: якорь переживает seed без новых просмотров (контроль PROGR-18)", async () => {
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      makeRouter({
        status: 200,
        nodes: [edaNode("descriptive", "done", "current")],
        flatStatuses: { "eda/descriptive": "done" },
      })(input, init)) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findAllByRole("button", { name: /Сезонность и периодичность/ }, { timeout: 4000 });
    await settle(250);
    // Seed == снапшот активной descriptive -- отчёта нет (уже записано).
    expect(edaPosts.length).toBe(0);
  });
});

function waitForPosts(count: number): Promise<void> {
  return waitFor(() => expect(edaPosts.length).toBe(count), { timeout: 4000 });
}
