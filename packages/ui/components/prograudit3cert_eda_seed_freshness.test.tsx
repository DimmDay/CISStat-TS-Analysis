// packages/ui/components/prograudit3cert_eda_seed_freshness.test.tsx
//
// PROGR-AUDIT-3-CERT — оракулы сертификатора UI-стороны на СВОИХ данных
// (объект аудита: реализация AUDIT-3 «EDA: показ, запрос и свежесть»,
// main@493e5b6; контракт v1.1-3A §21.4/21.5; план §13).
//
// НЕ копия оракула исполнителя (prograudit3_eda_seed_freshness.test.tsx:
// сценарии S1–S5, датасет D-AUDIT3, столбцы Year/Price/Volume). Свой
// корпус: датасет D3-CERT-E9F2 «cert3_weekly.csv», столбцы
// Week/Flow/Stock, свои сценарные узлы и ПОРЯДКИ просмотров, а также
// пути, исполнителем не покрытые:
//   C1: current-only seed (stale/unknown не сеются) + ЧЕСТНАЯ
//       немедленная доставка при расхождении якоря (свой ракурс:
//       seed {correlation} ≠ снапшот авто-просмотра descriptive).
//   C2: отказ seed (503) удерживает отчёт; клик-ретрай при отказе
//       снова удерживает; ВОССТАНОВЛЕНИЕ (trace стал 200, fresh
//       сессия) -- ретрай по новому просмотру доставляет ОБЪЕДИНЁННЫЙ
//       снапшот seed+локальные просмотры (§21.4 «успех -- отчёт
//       объединённым снапшотом») -- путь, в оракуле исполнителя
//       отсутствует (его S2 -- только удержание).
//   C3: деградация проекции (projection_complete=false при НЕпустом
//       теле с done-фактами) -- session_tail историю не выдаёт:
//       удержание и после клик-ретрая.
//   C4: H28 -- смена цели Flow->Stock при том же datasetId: свой
//       порядок просмотров (seasonality -> correlation -> смена);
//       перенос просмотров устранён.
//   C5: якорь переживает успешный seed (контроль PROGR-18) + новый
//       просмотр доставляется с сеяным done.
//   C6: легаси-фолбэк (нет поля nodes -- плоский node_statuses, N-3)
//       + гейт гонки первого seed'а: /trace на монтировании -- ровно
//       seed(1) + биндинг первой поставки(1) = 2 (U-мутант снятия
//       hasDataset-гейта дал бы преждевременный второй seed).
//   C7 (волна 2 эволюции оракулов -- убийца SURVIVED-мутанта U7):
//       легаси-фолбэк (биндинг недоступен) + ИДЕНТИЧНЫЙ снапшот при
//       смене цели: смена universeKey обязана РАЗДИТИТЬ дедуп (§21.5
//       «дедуп прежней вселенной не подавляет новую» -- повторная
//       доставка того же тела); мутант «universeKey без цели» держит
//       дедуп -- повторная поставка подавлена.
//
// Мок только своих URL; сеть в jest недоступна.

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TsAnalysisEDA } from "./TsAnalysisEDA";

let mockActiveDataset: {
  datasetId?: string;
  name: string;
  rows: number;
  sizeLabel: string;
} | null = {
  datasetId: "D3-CERT-E9F2",
  name: "cert3_weekly.csv",
  rows: 64,
  sizeLabel: "2 KB",
};

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ activeDataset: mockActiveDataset }),
}));

const edaPosts: Record<string, string>[] = [];
let traceGets = 0;

// режимы /trace: "ok" (свежая сессия), "fail" (500), "degraded"
// (projection_complete=false -- session_tail), "seeded" (полная
// проекция с узлами)
type TraceMode =
  | "ok"
  | "fail"
  | "degraded"
  | { kind: "seeded"; nodes: Array<Record<string, unknown>>; flat?: Record<string, string> };

let traceMode: TraceMode = "ok";

function jsonOk(body: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  });
}

function traceBody(mode: TraceMode): Record<string, unknown> {
  if (mode === "degraded") {
    // session_tail: слой 2 недоступен -- тело НЕпустое (история есть,
    // но неполная): projection_complete=false, done-факты присутствуют.
    return {
      run_id: "RUN-C3CERT-UI",
      context_id: "c3c-ui-0000000000001",
      events: [],
      projection_complete: false,
      node_statuses: { "eda/descriptive": "done", "eda/correlation": "done" },
      nodes: [edaNode("descriptive", "done", "current"), edaNode("correlation", "done", "current")],
    };
  }
  if (typeof mode === "string") {
    return {
      run_id: "RUN-C3CERT-UI",
      context_id: "c3c-ui-0000000000001",
      events: [],
      projection_complete: true,
      node_statuses: {},
    };
  }
  return {
    run_id: "RUN-C3CERT-UI",
    context_id: "c3c-ui-0000000000001",
    events: [],
    projection_complete: true,
    node_statuses: mode.flat ?? {},
    nodes: mode.nodes,
  };
}

function makeRouter() {
  return function router(input: RequestInfo | URL, init?: RequestInit) {
    const url = String(input);
    if (url.includes("/v1/progress/trace")) {
      traceGets += 1;
      if (traceMode === "fail") {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
      }
      return jsonOk(traceBody(traceMode));
    }
    if (url.includes("/v1/progress/eda-checks")) {
      edaPosts.push(JSON.parse(String(init?.body)).checks as Record<string, string>);
      return jsonOk({ received: 10, deduplicated: false });
    }
    if (url.includes("/target-column")) {
      const selected =
        init?.method === "POST" ? JSON.parse(String(init.body)).column : "Flow";
      return jsonOk({
        target_column: selected,
        suggested_column: "Flow",
        target_column_source: selected === "Flow" ? "auto" : "user",
        available_columns: ["Week", "Flow", "Stock"],
        has_dataset: true,
      });
    }
    if (url.includes("/dataset/passport/status")) {
      const emptyPoint = { captured: false, captured_at: null, is_stale: null, fingerprint: null, history_count: 0 };
      return jsonOk({
        has_dataset: true, target_column: "Flow", date_column: "Week", series_ready: true, reason: null,
        current_fingerprint: "c3cert-fp",
        start: { ...emptyPoint, captured: true, is_stale: false, fingerprint: "c3cert-fp", history_count: 1 },
        validation: emptyPoint, exit: emptyPoint,
        modeling_entry: { ...emptyPoint, checkpoint_id: null, snapshot_id: null, source_stage: null, reused_snapshot: null },
      });
    }
    if (url.includes("/date-column")) {
      return jsonOk({ date_column: "Week", suggested_column: "Week", candidates: [{ name: "Week", score: 1 }], has_dataset: true, passport_history_reset: false });
    }
    if (url.includes("/dataset/stats")) {
      return jsonOk({
        min_non_null_for_stats: 2,
        columns: [
          { name: "Week", non_null_count: 6, stats: { mean: 2020.1, median: 2020, std: 1.4, skewness: 0, kurtosis: -1.2, q1: 2019, q3: 2021, iqr: 2, distribution_hint: "Равномерное" } },
          { name: "Flow", non_null_count: 6, stats: { mean: 31, median: 31, std: 9.9, skewness: 0, kurtosis: -1.2, q1: 24, q3: 38, iqr: 14, distribution_hint: "Близко к нормальному" } },
          { name: "Stock", non_null_count: 6, stats: { mean: 310, median: 310, std: 99, skewness: 0, kurtosis: -1.2, q1: 240, q3: 380, iqr: 140, distribution_hint: "Близко к нормальному" } },
        ],
      });
    }
    if (url.includes("/dataset/eda-correlation")) {
      return jsonOk({ column: "Flow", applicable: true, reason: null, n_observations: 64, missing_count: 0, requested_max_lags: 32, max_lag: 16, alpha: 0.05, order_source: "time_column", order_column: "Week", order_warning: null, frequency: "W", acf: [{ lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false }, { lag: 1, value: 0.66, confidence_lower: -0.2, confidence_upper: 0.2, significant: true }], pacf: [{ lag: 0, value: 1, confidence_lower: -0.2, confidence_upper: 0.2, significant: false }, { lag: 1, value: 0.61, confidence_lower: -0.2, confidence_upper: 0.2, significant: true }], significant_acf_lags: [1], significant_pacf_lags: [1], ljung_box_lag: 10, ljung_box_pvalue: 0.03, is_white_noise: false, suggested_p: 1, suggested_q: 1 });
    }
    if (url.includes("/dataset/eda-seasonality")) {
      return jsonOk({ column: "Flow", applicable: true, reason: null, n_observations: 64, missing_count: 0, min_cycles: 3, max_candidates: 5, max_period: 30, detrend: "linear", window: "hann", order_source: "time_column", order_column: "Week", order_warning: null, frequency: "W", spectral_entropy: 0.3, dominant_period: 4, dominant_strength: 0.7, confirmed_periods: 1, recommendations: [], fft: [{ frequency: 0.25, period: 4, amplitude: 2.5, power: null, is_peak: true }], periodogram: [{ frequency: 0.25, period: 4, amplitude: null, power: 6.25, is_peak: true }], candidates: [{ rank: 1, period: 4, period_rounded: 4, frequency: 0.25, amplitude: 2.5, power: 6.25, power_share: 80, prominence: 4.0, spectral_snr: 25, autocorrelation: 0.8, seasonal_strength: 0.7, cycles: 16, confirmed: true, calendar_hint: null, harmonic_of: null }], phase_period: 4 });
    }
    return new Promise(() => {});
  };
}

function edaNode(nodeId: string, status: string, validity?: string | null) {
  return { stage: "eda", node_id: nodeId, status, validity };
}

async function settle(ms = 300) {
  await new Promise((r) => setTimeout(r, ms));
}

function waitForPosts(count: number): Promise<void> {
  return waitFor(() => expect(edaPosts.length).toBe(count), { timeout: 30000 });
}

// Бюджеты асинхронности (конвенция явного пина prograudit0_h26_no_auto_retry):
// внутренние ожидания оракулов -- findAllByRole/findByRole/waitForPosts
// с timeout: 30000 (до двух последовательных на тест) + рендер TsAnalysisEDA
// (recharts); per-test потолок 90000мс. Причина: среда запуска с 2 vCPU,
// джест-воркер контендится с хостом -- наблюдаемая деградация сюиты до 3.5×
// между прогонами (5.1с → 18.2с), поставка POST может прийти позже короткого
// бюджета; потолки покрывают деградацию с запасом (~×60 к норме ~0.5с)
// и флак при ней устранён (Fix, 2026-10-14). Семантика оракулов НЕ меняется
// («доставка обязана прийти в пределах бюджета», не «ждём сколько попало»);
// цена -- медленный фейл при РЕАЛЬНОЙ регрессии доставки (до 30с/тест).
describe("PROGR-AUDIT-3-CERT: EDA seed/full projection, удержание, вселенная по цели", () => {
  beforeEach(() => {
    edaPosts.length = 0;
    traceGets = 0;
    traceMode = "ok";
    mockActiveDataset = {
      datasetId: "D3-CERT-E9F2",
      name: "cert3_weekly.csv",
      rows: 64,
      sizeLabel: "2 KB",
    };
  });

  it("C1: сеются только current-done; stale/unknown не воскрешаются; расхождение якоря -- честная немедленная доставка", async () => {
    traceMode = {
      kind: "seeded",
      nodes: [
        edaNode("correlation", "done", "current"),
        edaNode("seasonality", "done", "stale"),
        edaNode("descriptive", "done", "unknown"),
      ],
      flat: {
        "eda/correlation": "done",
        "eda/seasonality": "done",
        "eda/descriptive": "done",
      },
    };
    global.fetch = jest.fn(makeRouter()) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findAllByRole("button", { name: /Сезонность и периодичность/ }, { timeout: 30000 });
    // Seed {correlation}; авто-просмотр активной descriptive (unknown --
    // НЕ сеется) даёт снапшот {correlation, descriptive} != якорь --
    // честная немедленная доставка.
    await waitForPosts(1);
    expect(edaPosts[0]["correlation"]).toBe("done");
    expect(edaPosts[0]["descriptive"]).toBe("done");
    expect(edaPosts[0]["seasonality"]).toBe("pending");

    // Повторный показ сеяного correlation -- снапшот не меняется,
    // дедуп: новой поставки нет.
    fireEvent.click(screen.getByRole("button", { name: /Корреляция \(ACF\/PACF\)/ }));
    await settle(300);
    expect(edaPosts.length).toBe(1);
  }, 90000);

  it("C2: отказ seed удерживает; клик-ретрай при отказе снова удерживает; восстановление -- объединённый снапшот", async () => {
    traceMode = "fail";
    global.fetch = jest.fn(makeRouter()) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findAllByRole("button", { name: /Сезонность и периодичность/ }, { timeout: 30000 });
    await settle(300);
    // Активная descriptive просмотрена локально, seed не получен --
    // разрушительная карта НЕ отправляется (H27/§21.4).
    expect(edaPosts.length).toBe(0);

    // Новый просмотр -> ретрай (снова 500) -> продолжение удержания.
    fireEvent.click(screen.getByRole("button", { name: /Сезонность и периодичность/ }));
    await settle(400);
    expect(edaPosts.length).toBe(0);

    // ВОССТАНОВЛЕНИЕ: /trace стал 200 (fresh сессия); следующий новый
    // просмотр -- ретрай успехом, отчёт -- ОБЪЕДИНЁННЫЙ снапшот
    // (seed пустой + все локальные просмотры), без понижений.
    traceMode = "ok";
    fireEvent.click(screen.getByRole("button", { name: /Корреляция \(ACF\/PACF\)/ }));
    await waitForPosts(1);
    expect(edaPosts[0]["descriptive"]).toBe("done");
    expect(edaPosts[0]["seasonality"]).toBe("done");
    expect(edaPosts[0]["correlation"]).toBe("done");
    expect(edaPosts[0]["ih_analysis"]).toBe("pending");
  }, 90000);

  it("C3: деградация проекции (session_tail, тело с done-фактами) удерживает отчёт и после клик-ретрая", async () => {
    traceMode = "degraded";
    global.fetch = jest.fn(makeRouter()) as jest.Mock;
    // Деградированное тело НЕПУСТОЕ: сеяться из него нельзя -- история
    // не выдаётся (план §13: «пустой set» не.mean разрушительную карту).
    render(<TsAnalysisEDA />);
    await screen.findAllByRole("button", { name: /Сезонность и периодичность/ }, { timeout: 30000 });
    await settle(300);
    expect(edaPosts.length).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: /Сезонность и периодичность/ }));
    await settle(400);
    expect(edaPosts.length).toBe(0);
  }, 90000);

  it("C4: H28 -- смена цели Flow->Stock при том же datasetId: новая вселенная, просмотры не переносятся", async () => {
    global.fetch = jest.fn(makeRouter()) as jest.Mock;
    render(<TsAnalysisEDA />);
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" }, { timeout: 30000 });
    await waitForPosts(1);
    expect(edaPosts[0]["descriptive"]).toBe("done");

    fireEvent.click(screen.getByRole("button", { name: /Сезонность и периодичность/ }));
    await waitForPosts(2);
    expect(edaPosts[1]["seasonality"]).toBe("done");

    // Смена цели при неизменном datasetId: сброс + re-seed (новая
    // применимость, §21.5); активная seasonality -- честный НОВЫЙ
    // просмотр новой вселенной; descriptive -- только прежней.
    fireEvent.change(selector, { target: { value: "Stock" } });
    await screen.findByDisplayValue("Stock", {}, { timeout: 30000 });
    await waitForPosts(3);
    expect(edaPosts[2]["seasonality"]).toBe("done");
    expect(edaPosts[2]["descriptive"]).toBe("pending");
    // Свежий биндинг новой вселенной (I3, §21.5): смена цели меняет
    // universeKey -- хук обязан ПЕРЕБИНДИТЬСЯ. Счётчик /trace:
    // seed(1) + биндинг первой поставки(1) + re-seed при смене
    // вселенной(1) + ребот биндинга новой вселенной(1) = 4. Мутант
    // «universeKey без цели» дал бы 3 (кэш прежней вселенной).
    await settle(300);
    expect(traceGets).toBe(4);
  }, 90000);

  it("C5: якорь переживает успешный seed (нет повторной поставки); новый просмотр доставляется с сеяным done", async () => {
    traceMode = { kind: "seeded", nodes: [edaNode("descriptive", "done", "current")] };
    global.fetch = jest.fn(makeRouter()) as jest.Mock;
    render(<TsAnalysisEDA />);
    await screen.findAllByRole("button", { name: /Сезонность и периодичность/ }, { timeout: 30000 });
    await settle(300);
    // Seed == снапшот активной descriptive -- отчёта нет (уже записано,
    // якорь PROGR-18).
    expect(edaPosts.length).toBe(0);

    // Новый просмотр -- карта несёт сеяный descriptive=done (current)
    // и честный новый seasonality=done.
    fireEvent.click(screen.getByRole("button", { name: /Сезонность и периодичность/ }));
    await waitForPosts(1);
    expect(edaPosts[0]["descriptive"]).toBe("done");
    expect(edaPosts[0]["seasonality"]).toBe("done");
  }, 90000);

  it("C6: легаси-фолбэк (плоский node_statuses) + гейт гонки первого seed'а (ровно seed+биндинг /trace)", async () => {
    // Старый бэкенд: поля nodes НЕТ; сеется плоский node_statuses (N-3).
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const promise = makeRouter()(input, init);
      return promise;
    }) as jest.Mock;
    // traceMode "ok" без nodes -- форма легаси (плоский словарь пуст).
    render(<TsAnalysisEDA />);
    await screen.findAllByRole("button", { name: /Сезонность и периодичность/ }, { timeout: 30000 });
    await waitForPosts(1);
    // Bootstrap свежей сессии работает: авто-просмотр descriptive
    // доставлен.
    expect(edaPosts[0]["descriptive"]).toBe("done");
    // Гейт гонки первого seed'а: /trace -- ровно seed(1) + биндинг
    // первой поставки(1). Снятие hasDataset-гейта дало бы
    // преждевременный второй seed (3).
    expect(traceGets).toBe(2);
  }, 90000);

  it("C7: легаси-дедуп делится сменой цели -- идентичный снапшот новой вселенной доставляется заново", async () => {
    // /trace: вызов 1 = seed (200, fresh); вызовы-биндинги -- 500
    // (биндинг недоступен -- легаси-фолбэк §20.5); вызов 3 = re-seed
    // при смене вселенной (200); чётные -- биндинги (500). Свой
    // счётчик вызовов в харнессе сертификатора.
    let traceCalls = 0;
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/v1/progress/trace")) {
        traceCalls += 1;
        if (traceCalls % 2 === 0) {
          return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
        }
        return jsonOk({
          run_id: "RUN-C3CERT-UI",
          context_id: "c3c-ui-0000000000001",
          events: [],
          projection_complete: true,
          node_statuses: {},
        });
      }
      return makeRouter()(input, init);
    }) as jest.Mock;
    render(<TsAnalysisEDA />);
    const selector = await screen.findByRole("combobox", { name: "Исследуемый признак:" }, { timeout: 30000 });
    // POST#1 (легаси-фолбэк): seed(1)=200 -- состоялся; авто-просмотр
    // descriptive; биндинг(2)=500 -- доставка легаси одним POST.
    await waitForPosts(1);
    expect(edaPosts[0]["descriptive"]).toBe("done");

    // Смена цели: сброс + re-seed(3)=200; активная descriptive
    // перезапрошена -- честный НОВЫЙ просмотр НОВОЙ вселенной;
    // снапшот {descriptive} ИДЕНТИЧЕН прежней поставке. Смена
    // universeKey делит дедуп -- POST#2 обязана состояться.
    fireEvent.change(selector, { target: { value: "Stock" } });
    await screen.findByDisplayValue("Stock", {}, { timeout: 30000 });
    await waitForPosts(2);
    expect(edaPosts[1]["descriptive"]).toBe("done");
  }, 90000);
});
