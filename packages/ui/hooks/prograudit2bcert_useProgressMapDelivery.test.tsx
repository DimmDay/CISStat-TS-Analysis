// packages/ui/hooks/prograudit2bcert_useProgressMapDelivery.test.tsx
//
// СЕРТИФИКАЦИОННЫЕ ОРАКУЛЫ задачи PROGR-AUDIT-2B (PROGR-AUDIT-2B-CERT,
// независимый аудит ЕДИНОГО механизма доставки карт useProgressMapDelivery).
// Сюит НЕ копирует repo-тесты задачи (useProgressMapDelivery.test.tsx):
// свой корпус данных, свой fetch-харнесс, свои последовательности ответов,
// свои run/context/report-идентификаторы.
//
// Свои данные (дизъюнкт с корпусом исполнителя alpha/beta/gamma и RUN-A):
//   карта остановок c2b-stop-1..4 со статусами ok/flaw (хук статус-агностен
//   -- значения проходят насквозь,.String() в канонизации);
//   run-ы RUN-C2B-A / RUN-C2B-B; контексты ctx-c2b1234567890abc /
//   ctx-c2b0987654321fed (канон ctx-<16hex>); receipt формата §19.4 со
//   своим idempotency_key и accepted_event_ids; retry-задержки [4,4,4].
//
// Контракты (план plan_progress_audit.md §12, контракт §20 v1.0-2B):
//   CERT-2B-F* -- форма: v2-конверт (schema_version=2+run+context+report_id),
//                 канонизация снапшота, кэш биндинга на вселенную, форма
//                 report_id, легаси-фолбэк без конверта;
//   CERT-2B-G* -- гейты: delivered ТОЛЬКО после 200+mode=v2+receipt (§20.3),
//                 acceptance без receipt -- честный accepted_legacy (§20.4);
//   CERT-2B-R* -- H26 штатным механизмом (§20.2): retry тем же report_id,
//                 потерянный ответ, исчерпание без ложного delivered,
//                 возобновление, постоянные ошибки без retry;
//   CERT-2B-L* -- легаси (§20.5): один POST без retry, acceptance в дедупе,
//                 смена вселенной переоткрывает доставку;
//   CERT-2B-S* -- изоляция stale (§20.5/§20.6): поздний ответ A после B,
//                 замещение с абортом, null-карта, unmount;
//   CERT-2B-C* -- 409 stale_run/stale_context: refresh + ОДНА повторная
//                 поставка с новым report_id, повторный 409 -- стоп (§20.5);
//                 report_id_conflict -- постоянная ошибка;
//   CERT-2B-D* -- дедуп по (run, context, снапшот) НЕ по имени файла (§20.3),
//                 EDA-якорь, redeliver().

import "@testing-library/jest-dom";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useProgressMapDelivery } from "./useProgressMapDelivery";

// ── СВОЙ корпус данных ────────────────────────────────────────────────

const RUN_A = "RUN-C2B-A";
const RUN_B = "RUN-C2B-B";
const CTX_A = "ctx-c2b1234567890abc";
const CTX_B = "ctx-c2b0987654321fed";

const C2B_RECEIPT_A = {
  idempotency_key: `report:${RUN_A}:c2b-report-1`,
  run_id: RUN_A,
  context_id: CTX_A,
  accepted_event_ids: ["c2b-ev-1", "c2b-ev-2"],
  committed_watermark: 2,
  created_at: "2026-10-12T12:00:00Z",
};

const MAP_1: Record<string, string> = {
  "c2b-stop-1": "ok",
  "c2b-stop-2": "flaw",
  "c2b-stop-3": "ok",
};
const MAP_2: Record<string, string> = {
  "c2b-stop-1": "ok",
  "c2b-stop-2": "ok",
  "c2b-stop-3": "ok",
};
const MAP_3: Record<string, string> = {
  "c2b-stop-1": "ok",
  "c2b-stop-2": "ok",
  "c2b-stop-3": "ok",
  "c2b-stop-4": "flaw",
};

// ── СВОЙ fetch-харнесс (собственная реализация, не копия исполнителя) ─

type C2bFetchResult = { ok: boolean; status: number; json: () => Promise<unknown> };
type C2bOutcome = C2bFetchResult | Promise<C2bFetchResult> | "c2b-hang" | "c2b-reject";

interface C2bPostRecord {
  url: string;
  body: Record<string, unknown>;
  signal: AbortSignal | null;
}

function c2bTraceOk(run: string, ctx: string): C2bFetchResult {
  return { ok: true, status: 200, json: () => Promise.resolve({ run_id: run, context_id: ctx }) };
}

function c2bTraceFail(): C2bFetchResult {
  return { ok: false, status: 404, json: () => Promise.resolve({ detail: "c2b-trace-miss" }) };
}

function c2bV2Ok(reportId: string, ctx = CTX_A): C2bFetchResult {
  return {
    ok: true,
    status: 200,
    json: () =>
      Promise.resolve({
        run_id: RUN_A,
        reported: 3,
        mode: "v2",
        report_id: reportId,
        context_id: ctx,
        deduplicated: false,
        receipt: { ...C2B_RECEIPT_A, context_id: ctx },
      }),
  };
}

function c2bLegacyOk(): C2bFetchResult {
  return { ok: true, status: 200, json: () => Promise.resolve({ run_id: RUN_A, reported: 3 }) };
}

function c2bErr(status: number, detail: string): C2bFetchResult {
  return { ok: false, status, json: () => Promise.resolve({ detail }) };
}

interface C2bHarness {
  posts: C2bPostRecord[];
  traceGets: string[];
}

function c2bInstallFetch(opts: {
  trace?: (url: string) => C2bFetchResult;
  onPost?: (record: C2bPostRecord, index: number) => C2bOutcome;
}): C2bHarness {
  const posts: C2bPostRecord[] = [];
  const traceGets: string[] = [];
  (globalThis as { fetch: unknown }).fetch = jest.fn((url: unknown, init?: RequestInit) => {
    const u = String(url);
    const isTraceGet = u.includes("/progress/trace") && (init?.method ?? "GET") !== "POST";
    if (isTraceGet) {
      traceGets.push(u);
      const res = opts.trace ? opts.trace(u) : c2bTraceOk(RUN_A, CTX_A);
      return Promise.resolve(res);
    }
    if (u.includes("/progress/") && init?.method === "POST") {
      let body: Record<string, unknown> = {};
      try {
        body = JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>;
      } catch {
        body = {};
      }
      const rec: C2bPostRecord = { url: u, body, signal: (init.signal as AbortSignal) ?? null };
      const idx = posts.length;
      posts.push(rec);
      const outcome = opts.onPost ? opts.onPost(rec, idx) : c2bV2Ok(String(body.report_id ?? ""));
      if (outcome === "c2b-hang") return new Promise<C2bFetchResult>(() => undefined);
      if (outcome === "c2b-reject") return Promise.reject(new Error("c2b-network-down"));
      return Promise.resolve(outcome);
    }
    return Promise.resolve(c2bErr(404, "c2b-no-route"));
  }) as unknown as jest.Mock;
  return { posts, traceGets };
}

// ── Свой рендер хука ──────────────────────────────────────────────────

interface C2bHookProps {
  map: Record<string, string> | null;
  universeKey?: string | null;
  anchor?: string | null;
}

function c2bRenderHook(initial: C2bHookProps, endpoint = "/c2b-checks") {
  return renderHook(
    ({ map, universeKey, anchor }: C2bHookProps) =>
      useProgressMapDelivery({
        endpoint,
        bodyKey: "checks",
        map,
        universeKey,
        anchorSnapshot: anchor,
        retryDelaysMs: [4, 4, 4],
      }),
    { initialProps: initial },
  );
}

beforeEach(() => {
  jest.clearAllMocks();
});

// ── FORM: форма v2-конверта, канонизация, кэш биндинга, report_id ─────

describe("CERT-2B-F: форма v2-конверта и биндинг (§20.1/§20.5)", () => {
  it("CERT-2B-F1: тело v2 несёт schema_version=2 + run_id + context_id + report_id из биндинга /trace; delivered после receipt; runId/contextId отражены", async () => {
    const h = c2bInstallFetch({});
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts.length).toBe(1);
    const body = h.posts[0].body;
    expect(body.schema_version).toBe(2);
    expect(body.run_id).toBe(RUN_A);
    expect(body.context_id).toBe(CTX_A);
    expect(typeof body.report_id).toBe("string");
    expect(String(body.report_id)).toMatch(/^map-/);
    expect(body.checks).toEqual(MAP_1);
    expect(result.current.reportId).toBe(body.report_id);
    expect(result.current.runId).toBe(RUN_A);
    expect(result.current.contextId).toBe(CTX_A);
    expect(result.current.status).toBe("delivered");
  });

  it("CERT-2B-F2: канонизация снапшота -- та же карта в другом порядке построения не рождает второй POST (дедуп устойчив к порядку)", async () => {
    const h = c2bInstallFetch({});
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    const reordered: Record<string, string> = {};
    for (const key of Object.keys(MAP_1).slice().reverse()) reordered[key] = MAP_1[key];
    rerender({ map: reordered, universeKey: "c2b-universe-1" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(h.posts.length).toBe(1);
    expect(result.current.delivered).toBe(true);
  });

  it("CERT-2B-F3: report_id формы map-* и <=200 символов; уникален между поставками (P07/§19.3 -- новое наблюдение = новый ключ)", async () => {
    const h = c2bInstallFetch({});
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    const firstId = String(h.posts[0].body.report_id);
    expect(firstId.startsWith("map-")).toBe(true);
    expect(firstId.length).toBeLessThanOrEqual(200);
    rerender({ map: MAP_3, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(h.posts.length).toBe(2));
    const secondId = String(h.posts[1].body.report_id);
    expect(secondId.startsWith("map-")).toBe(true);
    expect(secondId.length).toBeLessThanOrEqual(200);
    expect(secondId).not.toBe(firstId);
  });

  it("CERT-2B-F4: биндинг кэшируется на вселенную -- один GET /trace за всю жизнь поставки; смена вселенной перезапрашивает биндинг (I3, §20.5)", async () => {
    const h = c2bInstallFetch({});
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    rerender({ map: MAP_1, universeKey: "c2b-universe-1" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(h.traceGets.length).toBe(1);
    rerender({ map: MAP_1, universeKey: "c2b-universe-2" });
    await waitFor(() => expect(h.posts.length).toBe(2));
    expect(h.traceGets.length).toBe(2);
  });

  it("CERT-2B-F5: биндинг недоступен (trace 404) -- легаси-фолбэк: тело содержит ТОЛЬКО ключ карты, без schema_version/run/context/report_id", async () => {
    // Реалистичный сценарий старого бэкенда: trace 404, карта отвечает
    // 200 без mode/receipt (легаси-режим §19.5).
    const h = c2bInstallFetch({ trace: c2bTraceFail, onPost: () => c2bLegacyOk() });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.status).toBe("accepted_legacy"));
    expect(h.posts.length).toBe(1);
    expect(Object.keys(h.posts[0].body)).toEqual(["checks"]);
    expect(result.current.delivered).toBe(false);
    expect(result.current.runId).toBeNull();
    expect(result.current.contextId).toBeNull();
  });
});

// ── GATE: receipt-гейт delivered (§20.3/§20.4) ────────────────────────

describe("CERT-2B-G: receipt-гейт delivered (§20.3/§20.4)", () => {
  it("CERT-2B-G2: 200 без mode/receipt (легаси-приёмка сервера) -- accepted_legacy, delivered=false", async () => {
    const h = c2bInstallFetch({ onPost: () => c2bLegacyOk() });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.status).toBe("accepted_legacy"));
    expect(result.current.delivered).toBe(false);
    expect(h.posts.length).toBe(1);
  });

  it("CERT-2B-G3: 200 c mode=v2, но receipt:null -- receipt ОБЯЗАТЕЛЕН: accepted_legacy, delivered=false (§20.3)", async () => {
    const h = c2bInstallFetch({
      onPost: () => ({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            run_id: RUN_A,
            reported: 3,
            mode: "v2",
            report_id: "c2b-x",
            context_id: CTX_A,
            deduplicated: false,
            receipt: null,
          }),
      }),
    });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.status).toBe("accepted_legacy"));
    expect(result.current.delivered).toBe(false);
    expect(h.posts.length).toBe(1);
  });

  it("CERT-2B-G4: attempts считает попытки текущей поставки: 4x500 -- attempts=4, ни одного delivered (§20.2)", async () => {
    const h = c2bInstallFetch({ onPost: () => c2bErr(500, "c2b-boom") });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.attempts).toBe(4));
    expect(h.posts.length).toBe(4);
    expect(result.current.status).toBe("undelivered");
    expect(result.current.delivered).toBe(false);
  });
});

// ── RETRY: H26 штатным механизмом (§20.2) ─────────────────────────────

describe("CERT-2B-R: ограниченный retry с backoff -- H26 (§20.2)", () => {
  it("CERT-2B-R1: 500 -> retry ТОТ ЖЕ report_id и байт-в-байт тот же payload -> успех -- delivered (H26 закрыт штатно)", async () => {
    const h = c2bInstallFetch({
      onPost: (rec, idx) => (idx < 2 ? c2bErr(500, "c2b-transient") : c2bV2Ok(String(rec.body.report_id ?? ""))),
    });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts.length).toBe(3);
    const id0 = String(h.posts[0].body.report_id);
    const id1 = String(h.posts[1].body.report_id);
    const id2 = String(h.posts[2].body.report_id);
    expect(id1).toBe(id0);
    expect(id2).toBe(id0);
    expect(JSON.stringify(h.posts[0].body)).toBe(JSON.stringify(h.posts[1].body));
    expect(JSON.stringify(h.posts[0].body)).toBe(JSON.stringify(h.posts[2].body));
    expect(result.current.reportId).toBe(id0);
  });

  it("CERT-2B-R2: потерянный ответ (rejected promise) -> повтор с ТЕМ ЖЕ report_id и payload (идемпотентность P07 на клиенте)", async () => {
    const h = c2bInstallFetch({
      onPost: (rec, idx) => (idx === 0 ? "c2b-reject" : c2bV2Ok(String(rec.body.report_id ?? ""))),
    });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts.length).toBe(2);
    expect(String(h.posts[1].body.report_id)).toBe(String(h.posts[0].body.report_id));
    expect(JSON.stringify(h.posts[1].body)).toBe(JSON.stringify(h.posts[0].body));
  });

  it("CERT-2B-R3: исчерпание retry (все попытки 500) -- undelivered БЕЗ ложного delivered, ровно 4 попытки", async () => {
    const h = c2bInstallFetch({ onPost: () => c2bErr(500, "c2b-boom") });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.status).toBe("undelivered"));
    expect(h.posts.length).toBe(4);
    expect(result.current.delivered).toBe(false);
    expect(result.current.lastError).toContain("c2b-boom");
  });

  it("CERT-2B-R4: после исчерпания смена снапшота возобновляет доставку с НОВЫМ report_id (обратная сторона H26)", async () => {
    const h = c2bInstallFetch({
      onPost: (rec, idx) => (idx < 4 ? c2bErr(500, "c2b-boom") : c2bV2Ok(String(rec.body.report_id ?? ""))),
    });
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.status).toBe("undelivered"));
    expect(h.posts.length).toBe(4);
    const exhaustedId = String(h.posts[3].body.report_id);
    rerender({ map: MAP_2, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts.length).toBe(5);
    const newId = String(h.posts[4].body.report_id);
    expect(newId).not.toBe(exhaustedId);
  });

  it.each([400, 404, 422])(
    "CERT-2B-R5: постоянная ошибка HTTP %i -- ровно один POST, без retry (§20.2)",
    async (status) => {
      const h = c2bInstallFetch({ onPost: () => c2bErr(status, "c2b-permanent") });
      const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
      await waitFor(() => expect(result.current.status).toBe("undelivered"));
      expect(h.posts.length).toBe(1);
      expect(result.current.delivered).toBe(false);
    },
  );
});

// ── LEGACY: фолбэк и его границы (§20.4/§20.5) ────────────────────────

describe("CERT-2B-L: легаси-фолбэк (§20.4/§20.5)", () => {
  it("CERT-2B-L1: легаси без биндинга НЕ ретраится: 500 -- ровно один POST, undelivered (серверный легаси без идемпотентности)", async () => {
    const h = c2bInstallFetch({ trace: c2bTraceFail, onPost: () => c2bErr(500, "c2b-legacy-boom") });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.status).toBe("undelivered"));
    expect(h.posts.length).toBe(1);
    expect(Object.keys(h.posts[0].body)).toEqual(["checks"]);
    expect(result.current.delivered).toBe(false);
  });

  it("CERT-2B-L2: легаси-acceptance засчитывается в дедуп: тот же снапшот после accepted_legacy -- новых POST нет (§20.4)", async () => {
    const h = c2bInstallFetch({ trace: c2bTraceFail, onPost: () => c2bLegacyOk() });
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.status).toBe("accepted_legacy"));
    rerender({ map: { ...MAP_1 }, universeKey: "c2b-universe-1" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(h.posts.length).toBe(1);
    expect(result.current.status).toBe("accepted_legacy");
  });

  it("CERT-2B-L3: смена вселенной в легаси (universeKey) -- тот же снапшот доставляется заново как новое наблюдение, биндинг перезапрошен (§20.3)", async () => {
    const h = c2bInstallFetch({ trace: c2bTraceFail, onPost: () => c2bLegacyOk() });
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.status).toBe("accepted_legacy"));
    rerender({ map: MAP_1, universeKey: "c2b-universe-2" });
    await waitFor(() => expect(h.posts.length).toBe(2));
    expect(Object.keys(h.posts[1].body)).toEqual(["checks"]);
    expect(h.traceGets.length).toBe(2);
    expect(result.current.status).toBe("accepted_legacy");
  });
});

// ── STALE: изоляция поздних ответов (§20.5/§20.6) ─────────────────────

describe("CERT-2B-S: изоляция stale-ответов (§20.5/§20.6)", () => {
  it("CERT-2B-S1: поздний успех A после старта B: ответ A состояние новой вселенной не меняет; delivered -- только от B с report_id B", async () => {
    const resolvers: Array<((r: C2bFetchResult) => void) | null> = [null, null];
    const h = c2bInstallFetch({
      onPost: (_rec, idx) =>
        idx < 2
          ? new Promise<C2bFetchResult>((resolve) => {
              resolvers[idx] = resolve;
            })
          : c2bV2Ok("c2b-never"),
    });
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(h.posts.length).toBe(1));
    const idA = String(h.posts[0].body.report_id);
    rerender({ map: MAP_2, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(h.posts.length).toBe(2));
    const idB = String(h.posts[1].body.report_id);
    expect(idB).not.toBe(idA);
    // Поздний успех устаревшей поставки A -- состояние B не трогает.
    act(() => {
      resolvers[0]?.(c2bV2Ok(idA));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(result.current.delivered).toBe(false);
    expect(result.current.reportId).not.toBe(idA);
    // Успех текущей поставки B -- delivered.
    act(() => {
      resolvers[1]?.(c2bV2Ok(idB));
    });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(result.current.reportId).toBe(idB);
    expect(h.posts.length).toBe(2);
  });

  it("CERT-2B-S2: замещение in-flight поставки (смена снапшота): прежний запрос абортирован, его сетевой отказ не переводит состояние в undelivered", async () => {
    const h = c2bInstallFetch({
      onPost: (rec, idx) =>
        idx === 0 ? new Promise<C2bFetchResult>(() => undefined) : c2bV2Ok(String(rec.body.report_id ?? "")),
    });
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(h.posts.length).toBe(1));
    rerender({ map: MAP_2, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    // Первый запрос был замещён -- сигнал аборта выставлен (AbortController §20.5).
    expect(h.posts[0].signal?.aborted).toBe(true);
    expect(h.posts[1].signal?.aborted).toBe(false);
    expect(h.posts.length).toBe(2);
  });

  it("CERT-2B-S3: null-карта (вселенная закрыта): висящая поставка замещается (abort), новых POST нет; восстановление карты -- новая поставка с новым report_id", async () => {
    const holder: { resolve?: (r: C2bFetchResult) => void } = {};
    const h = c2bInstallFetch({
      onPost: (rec, idx) =>
        idx === 0
          ? new Promise<C2bFetchResult>((resolve) => {
              holder.resolve = resolve;
            })
          : c2bV2Ok(String(rec.body.report_id ?? "")),
    });
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(h.posts.length).toBe(1));
    const idA = String(h.posts[0].body.report_id);
    rerender({ map: null, universeKey: "c2b-universe-1" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 15));
    });
    expect(h.posts[0].signal?.aborted).toBe(true);
    expect(result.current.status).toBe("idle");
    // Поздний ответ замещённой поставки -- ничего не меняет.
    act(() => {
      holder.resolve?.(c2bV2Ok(idA));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 15));
    });
    expect(h.posts.length).toBe(1);
    expect(result.current.delivered).toBe(false);
    // Восстановление карты -- новое наблюдение.
    rerender({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts.length).toBe(2);
    expect(String(h.posts[1].body.report_id)).not.toBe(idA);
  });

  it("CERT-2B-S4: unmount: in-flight абортирован (§20.6); поздний ответ после unmount не рождает новых POST", async () => {
    const holder: { resolve?: (r: C2bFetchResult) => void } = {};
    const h = c2bInstallFetch({
      onPost: () =>
        new Promise<C2bFetchResult>((resolve) => {
          holder.resolve = resolve;
        }),
    });
    const { result, unmount } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(h.posts.length).toBe(1));
    const idA = String(h.posts[0].body.report_id);
    unmount();
    expect(h.posts[0].signal?.aborted).toBe(true);
    act(() => {
      holder.resolve?.(c2bV2Ok(idA));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(h.posts.length).toBe(1);
    expect(result.current.delivered).toBe(false);
  });
});

// ── 409: refresh + ОДНА повторная поставка (§20.5) ────────────────────

describe("CERT-2B-C: 409 stale -- refresh контекста, не бесконечный повтор (§20.5)", () => {
  it("CERT-2B-C1: 409 stale_context -> refresh (второй GET /trace) + ОДНА повторная поставка с НОВЫМ report_id; повторный 409 -- стоп", async () => {
    const h = c2bInstallFetch({ onPost: () => c2bErr(409, "stale_context: контекст изменился (c2b)") });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(h.posts.length).toBe(2));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(h.traceGets.length).toBe(2);
    expect(h.posts.length).toBe(2);
    const id1 = String(h.posts[0].body.report_id);
    const id2 = String(h.posts[1].body.report_id);
    expect(id2).not.toBe(id1);
    expect(result.current.status).toBe("stale");
    expect(result.current.delivered).toBe(false);
    expect(result.current.lastError).toContain("stale_context");
  });

  it("CERT-2B-C2: 409 -> refresh вернул НОВЫЙ контекст -> повторная поставка несёт новый context_id -> delivered (c2b)", async () => {
    let traceCall = 0;
    const h = c2bInstallFetch({
      trace: () => {
        traceCall += 1;
        return traceCall === 1 ? c2bTraceOk(RUN_A, CTX_A) : c2bTraceOk(RUN_B, CTX_B);
      },
      onPost: (rec, idx) => (idx === 0 ? c2bErr(409, "stale_run: отчёт чужого запуска (c2b)") : c2bV2Ok(String(rec.body.report_id ?? ""), CTX_B)),
    });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts.length).toBe(2);
    expect(h.posts[1].body.run_id).toBe(RUN_B);
    expect(h.posts[1].body.context_id).toBe(CTX_B);
    expect(String(h.posts[1].body.report_id)).not.toBe(String(h.posts[0].body.report_id));
    expect(result.current.contextId).toBe(CTX_B);
  });

  it("CERT-2B-C3: 409 report_id_conflict -- постоянная ошибка: НЕ refresh (один GET), НЕ retry (один POST), undelivered", async () => {
    const h = c2bInstallFetch({ onPost: () => c2bErr(409, "report_id_conflict: ключ занят другим телом (c2b)") });
    const { result } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.status).toBe("undelivered"));
    expect(h.posts.length).toBe(1);
    expect(h.traceGets.length).toBe(1);
    expect(result.current.delivered).toBe(false);
  });
});

// ── DEDUP: (run, context, snapshot), якорь, redeliver (§20.3) ─────────

describe("CERT-2B-D: дедуп поставки (§20.3)", () => {
  it("CERT-2B-D1: тот же (run, context, снапшот) -- второй POST не пишется, delivered сохраняется", async () => {
    const h = c2bInstallFetch({});
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    rerender({ map: { "c2b-stop-3": "ok", "c2b-stop-1": "ok", "c2b-stop-2": "flaw" }, universeKey: "c2b-universe-1" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(h.posts.length).toBe(1);
    expect(result.current.delivered).toBe(true);
  });

  it("CERT-2B-D2: same filename/new run (map->null->map, тот же universeKey-файл, trace вернул НОВЫЙ run) -- доставляется заново (дедуп НЕ по имени файла)", async () => {
    let traceCall = 0;
    const h = c2bInstallFetch({
      trace: () => {
        traceCall += 1;
        return traceCall === 1 ? c2bTraceOk(RUN_A, CTX_A) : c2bTraceOk(RUN_B, CTX_B);
      },
    });
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-same-name.csv" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts[0].body.run_id).toBe(RUN_A);
    rerender({ map: null, universeKey: "c2b-same-name.csv" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 15));
    });
    rerender({ map: MAP_1, universeKey: "c2b-same-name.csv" });
    await waitFor(() => expect(h.posts.length).toBe(2));
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts[1].body.run_id).toBe(RUN_B);
    expect(h.posts[1].body.context_id).toBe(CTX_B);
  });

  it("CERT-2B-D3: EDA-якорь: снапшот, идентичный якорю, не доставляется (ни GET, ни POST); ушедший вперёд снапшот доставляется (PROGR-18 семантика)", async () => {
    const h = c2bInstallFetch({});
    const anchor = JSON.stringify(MAP_1);
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1", anchor });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(h.traceGets.length).toBe(0);
    expect(h.posts.length).toBe(0);
    expect(result.current.status).toBe("idle");
    rerender({ map: MAP_3, universeKey: "c2b-universe-1", anchor });
    await waitFor(() => expect(h.posts.length).toBe(1));
    expect(result.current.delivered).toBe(true);
  });

  it("CERT-2B-D4: redeliver() -- дедуп очищен: новый POST с НОВЫМ report_id и тем же payload (Upload: подтверждение структуры)", async () => {
    const h = c2bInstallFetch({});
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    const id1 = String(h.posts[0].body.report_id);
    act(() => {
      result.current.redeliver();
    });
    await waitFor(() => expect(h.posts.length).toBe(2));
    await waitFor(() => expect(result.current.delivered).toBe(true));
    const id2 = String(h.posts[1].body.report_id);
    expect(id2).not.toBe(id1);
    expect(JSON.stringify(h.posts[1].body.checks)).toBe(JSON.stringify(h.posts[0].body.checks));
  });

  it("CERT-2B-D5: записанный (run, context, snapshot) переживает null-цикл: map->null->map с ТЕМ ЖЕ биндингом -- повторной доставки НЕТ (путь подавления дедупа)", async () => {
    const h = c2bInstallFetch({ trace: () => c2bTraceOk(RUN_A, CTX_A) });
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-universe-1" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts.length).toBe(1);
    rerender({ map: null, universeKey: "c2b-universe-1" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 15));
    });
    rerender({ map: MAP_1, universeKey: "c2b-universe-1" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    // Биндинг перезапрошен (перезапуск вселенной), но ключ (run, context,
    // snapshot) уже записан -- дедуп подавляет повторную доставку
    // (наблюдаемо: НЕТ второго POST; delivered не переустанавливается.
    // Наблюдение сертификатора: статус остаётся "binding" -- последняя
    // фаза перед подавлением; вспомогательный контур, потребители
    // статуса доставки в продюсерах не читают -- замечание R акта).
    expect(h.traceGets.length).toBe(2);
    expect(h.posts.length).toBe(1);
    expect(result.current.delivered).toBe(false);
  });

  it("CERT-2B-D6: тот же context при НОВОМ run (null-цикл, биндинг RUN_B/CTX_A) -- доставляется заново: run_id входит в ключ дедупа (§20.3)", async () => {
    let traceCall = 0;
    const h = c2bInstallFetch({
      trace: () => {
        traceCall += 1;
        // Новый run (повторная загрузка), контекст не сдвинулся.
        return traceCall === 1 ? c2bTraceOk(RUN_A, CTX_A) : c2bTraceOk(RUN_B, CTX_A);
      },
    });
    const { result, rerender } = c2bRenderHook({ map: MAP_1, universeKey: "c2b-same-name.csv" });
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts[0].body.run_id).toBe(RUN_A);
    rerender({ map: null, universeKey: "c2b-same-name.csv" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 15));
    });
    rerender({ map: MAP_1, universeKey: "c2b-same-name.csv" });
    await waitFor(() => expect(h.posts.length).toBe(2));
    await waitFor(() => expect(result.current.delivered).toBe(true));
    expect(h.posts[1].body.run_id).toBe(RUN_B);
    expect(h.posts[1].body.context_id).toBe(CTX_A);
  });
});
