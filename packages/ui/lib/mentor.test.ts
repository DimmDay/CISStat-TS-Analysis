// packages/ui/lib/mentor.test.ts
//
// Тесты клиентского слоя Наставника (Task PROGR-6, spec_progress.md §7):
// маппинг preview-ответа Мастера в CorrectionOutcomeSummary (§7.2 --
// «разный набор полей у Missing/Outliers/Regularity сводится к общим
// именам на клиенте»), выбор «худшей» колонки статистик
// (worstStdStats -- для over_aggressive), best-effort запросов.

import "@testing-library/jest-dom";
import {
  buildCorrectionOutcomeSummary,
  fetchMentorNextStep,
  fetchSanityWarnings,
  worstStdStats,
} from "./mentor";
import { progressApiUrl } from "./apiClient";

describe("buildCorrectionOutcomeSummary", () => {
  it("переупаковка Missing-полей в snake_case-тело §7.2", () => {
    const body = buildCorrectionOutcomeSummary({
      stage: "preprocessing",
      nodeId: "missing",
      strategy: "median_mode",
      affectedBefore: 10,
      changed: 8,
      stillAffected: 2,
      rowsBefore: 100,
      rowsAfter: 95,
      statsBefore: { mean: 5, std: 2, median: 5 },
      statsAfter: { mean: 5, std: 1.9, median: 5 },
    });
    expect(body).toEqual({
      stage: "preprocessing",
      node_id: "missing",
      strategy: "median_mode",
      method: null,
      affected_count_before: 10,
      changed_count: 8,
      still_affected_count: 2,
      rows_before: 100,
      rows_after: 95,
      stats_before: { mean: 5, std: 2, median: 5 },
      stats_after: { mean: 5, std: 1.9, median: 5 },
    });
  });

  it("method прокидывается (Выбросы), без статистик -- null (Регулярность)", () => {
    const body = buildCorrectionOutcomeSummary({
      stage: "preprocessing",
      nodeId: "regularity",
      strategy: "resample",
      method: null,
      affectedBefore: 4,
      changed: 4,
      stillAffected: 0,
      rowsBefore: 50,
      rowsAfter: 52,
    });
    expect(body.method).toBeNull();
    expect(body.stats_before).toBeNull();
    expect(body.stats_after).toBeNull();
  });
});

describe("worstStdStats", () => {
  it("выбирает колонку с наибольшим падением std (худший кандидат)", () => {
    const worst = worstStdStats([
      {
        stats_before: { mean: 10, std: 5, median: 10 },
        stats_after: { mean: 10, std: 4.9, median: 10 },
      },
      {
        stats_before: { mean: 3, std: 2, median: 3 },
        stats_after: { mean: 3, std: 0.2, median: 3 }, // 0.1 -- худшее
      },
    ]);
    expect(worst?.statsBefore.std).toBe(2);
    expect(worst?.statsAfter.std).toBe(0.2);
  });

  it("колонки без валидной пары std пропускаются", () => {
    const worst = worstStdStats([
      { stats_before: null, stats_after: null }, // нечисловая колонка
      { stats_before: { std: 0 }, stats_after: { std: 0 } }, // нулевой std
      { stats_before: { std: 1 }, stats_after: null },
    ]);
    expect(worst).toBeNull();
  });

  it("пустой preview -- null (правило over_aggressive честно молчит)", () => {
    expect(worstStdStats([])).toBeNull();
  });
});

describe("fetchSanityWarnings", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("POST на /v1/progress/mentor/sanity-check с cookie и телом §7.2", async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          warnings: [
            { rule_id: "no_effect", severity: "warning", message: "…", suggested_action: "…" },
          ],
        }),
    });
    global.fetch = fetchMock as jest.Mock;
    const warnings = await fetchSanityWarnings({ stage: "preprocessing", node_id: "missing" });
    expect(fetchMock.mock.calls[0][0]).toBe(progressApiUrl("/mentor/sanity-check"));
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(String(init.body))).toEqual({
      stage: "preprocessing",
      node_id: "missing",
    });
    expect(warnings).toHaveLength(1);
    expect(warnings[0].rule_id).toBe("no_effect");
  });

  it("сбой сети/HTTP -- пустой список, не исключение (best-effort)", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network down")) as jest.Mock;
    expect(await fetchSanityWarnings({})).toEqual([]);

    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: () => Promise.resolve({ detail: "слой недоступен" }),
    }) as jest.Mock;
    expect(await fetchSanityWarnings({})).toEqual([]);
  });
});

describe("fetchMentorNextStep", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("GET run-scoped next-step, ответ отдаётся как есть", async () => {
    const payload = {
      run_id: "RUN-AAA00001",
      run_status: "active",
      last_active_stage: "preprocessing",
      phase_text: "…",
      summary: { stage: "preprocessing", total_nodes: 10, done_count: 1, warning_nodes: 1, nodes: [] },
      recommendation: {
        rule_id: "regularity_before_decomposition",
        stage: "preprocessing",
        message: "…",
        recommended_action: "preprocessing.regularity",
      },
      history_warnings: [],
    };
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload),
    });
    global.fetch = fetchMock as jest.Mock;
    const data = await fetchMentorNextStep("RUN-AAA00001");
    expect(fetchMock.mock.calls[0][0]).toBe(
      progressApiUrl("/runs/RUN-AAA00001/mentor/next-step"),
    );
    expect(data?.recommendation?.rule_id).toBe("regularity_before_decomposition");
  });

  it("сбой сети/404/503 -- null, панель показывает недоступность", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("down")) as jest.Mock;
    expect(await fetchMentorNextStep("RUN-X")).toBeNull();

    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 }) as jest.Mock;
    expect(await fetchMentorNextStep("RUN-X")).toBeNull();
  });
});
