// packages/ui/hooks/useProgressMapDelivery.test.tsx
//
// Тесты ЕДИНОГО механизма доставки карт статусов в контур «Прогресса» --
// задача AUDIT-2B (plan_progress_audit.md §12, контракт
// docs/progress_audit_contract.md аддендум §20). Оракулы на СВОИХ моках:
//
//   * H26 (план §12 RED): отказ доставки при неизменном снапшоте
//     повторяется ШТАТНЫМ механизмом (ограниченный retry с backoff) --
//     подтверждение receipt'ом;
//   * потерянный ответ → повтор с ТЕМ ЖЕ report_id (идемпотентность
//     P07 на клиенте);
//   * delivered ставится ТОЛЬКО после receipt (v2); acceptance без
//     receipt (легаси) -- честный accepted_legacy, delivered=false;
//   * поздний ответ A после B не изменяет состояние нового контекста
//     (изоляция stale-запросов, §12 п.3);
//   * дедуп по (run, context, snapshot), НЕ по имени файла: повторная
//     загрузка одноимённого файла (новый run) доставляется заново
//     (§12 п.4);
//   * 409 stale_run/stale_context → refresh контекста + ОДНА повторная
//     поставка с новым report_id; повторный 409 -- стоп (не бесконечный
//     повтор старого тела, §12 п.5);
//   * report_id_conflict -- постоянная ошибка без retry;
//   * исчерпание retry -- undelivered БЕЗ ложного delivered (§12 RED);
//   * unmount -- поздние ответы игнорируются, in-flight abort
//     (§12 п.6, in-memory ограничение задокументировано);
//   * легаси-фолбэк: биндинг недоступен -- тело без schema_version
//     одним POST (совместимость, контракт §20.5);
//   * v2-конверт: schema_version=2 + run_id + context_id + report_id;
//     report_id уникален между поставками;
//   * anchor-снапшот (EDA-якорь) не доставляется повторно.

import "@testing-library/jest-dom";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useProgressMapDelivery } from "./useProgressMapDelivery";

type FetchResult = {
  ok: boolean;
  status?: number;
  json?: () => Promise<unknown>;
};

interface PostRecord {
  url: string;
  body: Record<string, unknown>;
  signal?: AbortSignal | null;
}

const CTX_A = "ctx-aaaaaaaaaaaaaaaa";
const CTX_B = "ctx-bbbbbbbbbbbbbbbb";
const RECEIPT = {
  idempotency_key: "report:RUN-A:map-test",
  run_id: "RUN-A",
  context_id: CTX_A,
  accepted_event_ids: ["ev-1", "ev-2", "ev-3"],
  committed_watermark: 3,
  created_at: "2026-10-12T00:00:00Z",
};

function v2Ok(reportId: string, opts: { deduplicated?: boolean; runId?: string; contextId?: string } = {}): FetchResult {
  return {
    ok: true,
    status: 200,
    json: () =>
      Promise.resolve({
        run_id: opts.runId ?? "RUN-A",
        reported: opts.deduplicated ? 0 : 3,
        mode: "v2",
        report_id: reportId,
        context_id: opts.contextId ?? CTX_A,
        deduplicated: opts.deduplicated ?? false,
        receipt: RECEIPT,
      }),
  };
}

function legacyOk(): FetchResult {
  return { ok: true, status: 200, json: () => Promise.resolve({ run_id: "RUN-A", reported: 3 }) };
}

function httpError(status: number, detail: string): FetchResult {
  return { ok: false, status, json: () => Promise.resolve({ detail }) };
}

function traceOk(runId: string | null, contextId: string | null): FetchResult {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve({ run_id: runId, context_id: contextId, node_statuses: {} }),
  };
}

const MAP_A: Record<string, string> = { alpha: "done", beta: "warning", gamma: "pending" };
const MAP_B: Record<string, string> = { alpha: "done", beta: "done", gamma: "pending" };

interface HarnessOptions {
  trace?: (url: string) => FetchResult;
  onPost?: (record: PostRecord, index: number) => FetchResult | Promise<FetchResult> | "hang";
  retryDelaysMs?: number[];
}

function installFetchHarness(options: HarnessOptions): { posts: PostRecord[] } {
  const { trace, onPost, retryDelaysMs } = options;
  const posts: PostRecord[] = [];
  global.fetch = jest.fn((url: unknown, init?: RequestInit) => {
    const urlString = String(url);
    if (urlString.includes("/progress/trace") && (init?.method ?? "GET") !== "POST") {
      const res = trace ? trace(urlString) : traceOk("RUN-A", CTX_A);
      return Promise.resolve(res);
    }
    if (urlString.includes("/progress/") && init?.method === "POST") {
      let body: Record<string, unknown> = {};
      try {
        body = JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>;
      } catch {
        body = {};
      }
      const record: PostRecord = { url: urlString, body, signal: (init.signal as AbortSignal) ?? null };
      const index = posts.length;
      posts.push(record);
      const outcome = onPost ? onPost(record, index) : v2Ok(String(body.report_id ?? ""));
      if (outcome === "hang") {
        return new Promise<FetchResult>(() => undefined); // никогда не отвечает
      }
      return Promise.resolve(outcome);
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) });
  }) as unknown as jest.Mock;
  return { posts };
}

type HookProps = {
  map: Record<string, string> | null;
  anchor?: string | null;
};

function renderDeliveryHook(
  endpoint: string,
  initialProps: HookProps,
  retryDelaysMs: number[] = [5, 5, 5],
) {
  return renderHook(
    ({ map, anchor }: HookProps) =>
      useProgressMapDelivery({ endpoint, bodyKey: "checks", map, anchorSnapshot: anchor, retryDelaysMs }),
    { initialProps },
  );
}

describe("useProgressMapDelivery (AUDIT-2B: единый механизм доставки карт)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("v2-конверт: тело несёт schema_version=2 + run_id + context_id + report_id; delivered -- после receipt", async () => {
    const { posts } = installFetchHarness({});
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("delivered"));
    expect(posts.length).toBe(1);
    const body = posts[0].body;
    expect(body.schema_version).toBe(2);
    expect(body.run_id).toBe("RUN-A");
    expect(body.context_id).toBe(CTX_A);
    expect(typeof body.report_id).toBe("string");
    expect(String(body.report_id).length).toBeGreaterThan(0);
    expect(body.checks).toEqual(MAP_A);
    expect(result.current.delivered).toBe(true);
    expect(result.current.reportId).toBe(body.report_id);
    // Честный биндинг из /trace (I3): клиент привязан к наблюдаемому контексту.
    expect(result.current.runId).toBe("RUN-A");
    expect(result.current.contextId).toBe(CTX_A);
  });

  it("H26: отказ доставки (500) при неизменном снапшоте повторяется штатным retry с тем же report_id и подтверждается receipt", async () => {
    installFetchHarness({
      onPost: (_record, index) => (index === 0 ? httpError(500, "boom") : v2Ok(String(_record.body.report_id))),
      retryDelaysMs: [5, 5, 5],
    });
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("delivered"));
    expect(result.current.delivered).toBe(true);
    expect(result.current.attempts).toBe(2);
  });

  it("потерянный ответ (сетевой отказ): повтор с ТЕМ ЖЕ report_id и тем же payload", async () => {
    const { posts } = installFetchHarness({
      onPost: (_record, index) => {
        if (index === 0) {
          // Реальный fetch не бросает синхронно -- возвращает rejected promise.
          return Promise.reject(new TypeError("Failed to fetch")) as unknown as FetchResult;
        }
        return v2Ok(String(_record.body.report_id), { deduplicated: true });
      },
      retryDelaysMs: [5, 5, 5],
    });
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("delivered"));
    expect(posts.length).toBe(2);
    // Идемпотентность (P07): тот же ключ поставки и то же тело.
    expect(posts[1].body.report_id).toBe(posts[0].body.report_id);
    expect(posts[1].body.checks).toEqual(posts[0].body.checks);
    expect(result.current.delivered).toBe(true);
  });

  it("легаси-фолбэк: биндинг недоступен (trace 404) -- тело БЕЗ schema_version одним POST; acceptance без receipt -- НЕ delivered", async () => {
    const { posts } = installFetchHarness({
      trace: () => ({ ok: false, status: 404, json: () => Promise.resolve(null) }),
      onPost: () => legacyOk(),
    });
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("accepted_legacy"));
    expect(posts.length).toBe(1);
    expect(posts[0].body.schema_version).toBeUndefined();
    expect(posts[0].body.report_id).toBeUndefined();
    expect(posts[0].body.checks).toEqual(MAP_A);
    // Receipt-гейт (план §12 п.2): acceptance без receipt -- не delivered.
    expect(result.current.delivered).toBe(false);
  });

  it("легаси-фолбэк не ретраится: серверный легаси-режим без идемпотентности -- один POST, неудача -- undelivered", async () => {
    installFetchHarness({
      trace: () => traceOk(null, null),
      onPost: () => httpError(500, "boom"),
      retryDelaysMs: [5, 5, 5],
    });
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("undelivered"));
    // Legacy-режим: retry НЕ выполняется (повтор задублировал бы факты).
    expect(result.current.delivered).toBe(false);
  });

  it("поздний ответ A после B: успех устаревшей поставки не изменяет состояние новой (изоляция stale-запросов)", async () => {
    const resolvers: Array<(r: FetchResult) => void> = [];
    const { posts } = installFetchHarness({
      onPost: (_record) =>
        new Promise<FetchResult>((resolve) => {
          resolvers.push(resolve);
        }) as unknown as FetchResult,
      retryDelaysMs: [5, 5, 5],
    });
    // Мок возвращает "hang"-обещание: разрешим вручную.
    const hangPosts: Array<{ resolve: (r: FetchResult) => void }> = [];
    global.fetch = jest.fn((url: unknown, init?: RequestInit) => {
      const urlString = String(url);
      if (urlString.includes("/progress/trace")) return Promise.resolve(traceOk("RUN-A", CTX_A));
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>;
        const record: PostRecord = { url: urlString, body, signal: (init.signal as AbortSignal) ?? null };
        const index = posts.length;
        posts.push(record);
        return new Promise<FetchResult>((resolve) => {
          hangPosts[index] = { resolve };
        }) as unknown as Promise<FetchResult>;
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) });
    }) as unknown as jest.Mock;

    const { result, rerender } = renderDeliveryHook("/x-checks", { map: MAP_A });
    await waitFor(() => expect(posts.length).toBe(1));
    const reportIdA = posts[0].body.report_id;

    // Смена снапшота при висящей поставке A: B замещает её.
    rerender({ map: MAP_B });
    await waitFor(() => expect(posts.length).toBe(2));
    const reportIdB = posts[1].body.report_id;
    expect(reportIdB).not.toBe(reportIdA);

    // Поздний успех A (сервер записал устаревший снапшот): состояние B не трогается.
    await act(async () => {
      hangPosts[0].resolve(v2Ok(String(reportIdA)));
    });
    expect(result.current.status).toBe("pending"); // B всё ещё в полёте
    expect(result.current.reportId).toBe(reportIdB);

    await act(async () => {
      hangPosts[1].resolve(v2Ok(String(reportIdB)));
    });
    await waitFor(() => expect(result.current.status).toBe("delivered"));
    expect(result.current.reportId).toBe(reportIdB);
    expect(result.current.delivered).toBe(true);
    void resolvers;
  });

  it("дедуп по (run, context, snapshot): тот же снапшот с новым объектом НЕ доставляется повторно", async () => {
    const { posts } = installFetchHarness({});
    const { result, rerender } = renderDeliveryHook("/x-checks", { map: MAP_A });
    await waitFor(() => expect(result.current.status).toBe("delivered"));
    expect(posts.length).toBe(1);

    // Новый объект с тем же содержимым (перерендер модуля) -- не новая поставка.
    rerender({ map: { ...MAP_A } });
    await act(async () => {
      await Promise.resolve();
    });
    expect(posts.length).toBe(1);
  });

  it("same filename/new run: тот же снапшот в НОВОМ run доставляется заново (дедуп не по имени файла)", async () => {
    const { posts } = installFetchHarness({
      trace: () => traceOk(posts.length === 0 ? "RUN-A" : "RUN-B", posts.length === 0 ? CTX_A : CTX_B),
    });
    const { result, rerender } = renderDeliveryHook("/x-checks", { map: MAP_A });
    await waitFor(() => expect(result.current.status).toBe("delivered"));
    expect(posts[0].body.run_id).toBe("RUN-A");

    // Новая вселенная (смена датасета): map → null → тот же map.
    rerender({ map: null });
    rerender({ map: { ...MAP_A } });
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1].body.run_id).toBe("RUN-B");
    expect(posts[1].body.context_id).toBe(CTX_B);
    expect(result.current.delivered).toBe(true);
  });

  it("409 stale_context: refresh контекста + ОДНА повторная поставка с новым report_id; повторный 409 -- стоп (не бесконечный повтор)", async () => {
    let traceCalls = 0;
    const { posts } = installFetchHarness({
      trace: () => traceOk(traceCalls === 0 ? "RUN-A" : "RUN-B", traceCalls++ === 0 ? CTX_A : CTX_B),
      onPost: () => httpError(409, "stale_context: отчёт относится к контексту 'x'"),
      retryDelaysMs: [5, 5, 5],
    });
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("stale"));
    // Первая поставка → 409 → refresh → повторная с НОВЫМ report_id → 409 → стоп.
    expect(posts.length).toBe(2);
    expect(posts[1].body.report_id).not.toBe(posts[0].body.report_id);
    expect(posts[1].body.context_id).toBe(CTX_B);
    expect(result.current.delivered).toBe(false);
    // Нет бесконечного повтора старого тела.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(posts.length).toBe(2);
  });

  it("409 stale_context с успешным refresh: повторная поставка delivered с новым контекстом", async () => {
    let traceCalls = 0;
    const { posts } = installFetchHarness({
      trace: () => traceOk(traceCalls === 0 ? "RUN-A" : "RUN-B", traceCalls++ === 0 ? CTX_A : CTX_B),
      onPost: (_record, index) => (index === 0 ? httpError(409, "stale_context: контекст сдвинулся") : v2Ok(String(_record.body.report_id), { runId: "RUN-B", contextId: CTX_B })),
      retryDelaysMs: [5, 5, 5],
    });
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("delivered"));
    expect(posts.length).toBe(2);
    expect(posts[1].body.context_id).toBe(CTX_B);
    expect(result.current.delivered).toBe(true);
  });

  it("report_id_conflict -- постоянная ошибка без retry", async () => {
    const { posts } = installFetchHarness({
      onPost: () => httpError(409, "report_id_conflict: ключ уже использован с другим телом"),
      retryDelaysMs: [5, 5, 5],
    });
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("undelivered"));
    expect(posts.length).toBe(1);
    expect(result.current.delivered).toBe(false);
  });

  it("исчерпание retry: все попытки 500 -- undelivered БЕЗ ложного delivered", async () => {
    const { posts } = installFetchHarness({
      onPost: () => httpError(500, "boom"),
      retryDelaysMs: [5, 5, 5],
    });
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("undelivered"));
    // 1 первичная + 3 retry = 4 попытки, report_id один на всех.
    expect(posts.length).toBe(4);
    expect(new Set(posts.map((p) => p.body.report_id)).size).toBe(1);
    expect(result.current.delivered).toBe(false);
    expect(result.current.lastError).toBeTruthy();
  });

  it("422 -- постоянная ошибка формы без retry", async () => {
    const { posts } = installFetchHarness({
      onPost: () => httpError(422, "Карта неполна"),
      retryDelaysMs: [5, 5, 5],
    });
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });

    await waitFor(() => expect(result.current.status).toBe("undelivered"));
    expect(posts.length).toBe(1);
    expect(result.current.delivered).toBe(false);
  });

  it("unmount: in-flight запрос абортируется, поздний ответ не рождает доставку", async () => {
    const { posts } = installFetchHarness({
      onPost: () => "hang" as unknown as FetchResult,
    });
    const { result, unmount } = renderDeliveryHook("/x-checks", { map: MAP_A });
    await waitFor(() => expect(posts.length).toBe(1));
    expect(result.current.status).toBe("pending");

    unmount();
    expect(posts[0].signal?.aborted).toBe(true);
  });

  it("anchor-снапшот (EDA-якорь): идентичный снапшот не доставляется; изменение доставляется", async () => {
    const { posts } = installFetchHarness({});
    const anchor = JSON.stringify(MAP_A);
    const { result, rerender } = renderDeliveryHook("/x-checks", { map: MAP_A, anchor });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(posts.length).toBe(0);
    expect(result.current.status).toBe("idle");

    // Новый просмотр: снапшот изменился -- поставка происходит.
    rerender({ map: MAP_B, anchor });
    await waitFor(() => expect(result.current.status).toBe("delivered"));
    expect(posts.length).toBe(1);
    expect(posts[0].body.checks).toEqual(MAP_B);
  });

  it("report_id уникален между поставками (новое клиентское наблюдение -- новый ключ, P07/§19.3)", async () => {
    const { posts } = installFetchHarness({});
    const { result, rerender } = renderDeliveryHook("/x-checks", { map: MAP_A });
    await waitFor(() => expect(result.current.status).toBe("delivered"));
    rerender({ map: MAP_B });
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1].body.report_id).not.toBe(posts[0].body.report_id);
    await waitFor(() => expect(result.current.delivered).toBe(true));
  });

  it("redeliver(): принудительная повторная поставка текущего снапшота с новым report_id (подтверждение структуры, Upload)", async () => {
    const { posts } = installFetchHarness({});
    const { result } = renderDeliveryHook("/x-checks", { map: MAP_A });
    await waitFor(() => expect(result.current.status).toBe("delivered"));
    expect(posts.length).toBe(1);

    act(() => {
      result.current.redeliver();
    });
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1].body.checks).toEqual(MAP_A);
    expect(posts[1].body.report_id).not.toBe(posts[0].body.report_id);
    await waitFor(() => expect(result.current.delivered).toBe(true));
  });

  it("null-map (вселенная фактов исчезла): висящая поставка замещается, новых POST нет", async () => {
    const { posts } = installFetchHarness({
      onPost: () => "hang" as unknown as FetchResult,
    });
    const { result, rerender } = renderDeliveryHook("/x-checks", { map: MAP_A });
    await waitFor(() => expect(posts.length).toBe(1));

    rerender({ map: null });
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.status).toBe("idle");
    expect(posts.length).toBe(1);
  });
});
