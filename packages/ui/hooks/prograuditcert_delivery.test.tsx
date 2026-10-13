import { renderHook, waitFor } from "@testing-library/react";
import { useProgressMapDelivery } from "./useProgressMapDelivery";

const map = { missing: "done", data_types: "warning" };
const response = (body: unknown, status = 200) => Promise.resolve({ ok: status === 200, status, json: async () => body });

afterEach(() => jest.restoreAllMocks());

it("CERT receipt: 200 without receipt never claims durable delivery", async () => {
  global.fetch = jest.fn((url) => String(url).includes("/trace")
    ? response({ run_id: "CERT-UI", context_id: "ctx-cert-ui" })
    : response({ mode: "v2", reported: 2 })) as jest.Mock;
  const { result } = renderHook(() => useProgressMapDelivery({ endpoint: "/validation-checks", bodyKey: "checks", map }));
  await waitFor(() => expect(result.current.status).toBe("accepted_legacy"));
  expect(result.current.delivered).toBe(false);
});

it("CERT H26: lost response retries the exact envelope and receives prior receipt", async () => {
  const posts: Record<string, unknown>[] = [];
  const ledger = new Map<string, object>();
  global.fetch = jest.fn((url, init) => {
    if (String(url).includes("/trace")) return response({ run_id: "CERT-UI", context_id: "ctx-cert-ui" });
    const body = JSON.parse(String(init?.body));
    posts.push(body);
    const id = String(body.report_id);
    if (!ledger.has(id)) ledger.set(id, { run_id: body.run_id, context_id: body.context_id, accepted_event_ids: ["cert-ui-1", "cert-ui-2"], committed_watermark: 2 });
    if (posts.length === 1) return Promise.reject(new Error("lost response after commit"));
    return response({ mode: "v2", receipt: ledger.get(id), deduplicated: true });
  }) as jest.Mock;
  const { result } = renderHook(() => useProgressMapDelivery({ endpoint: "/validation-checks", bodyKey: "checks", map, retryDelaysMs: [5] }));
  await waitFor(() => expect(result.current.delivered).toBe(true));
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual(posts[0]);
  expect(ledger.size).toBe(1);
  expect(result.current.attempts).toBe(2);
});

it("CERT stale context: refresh creates a new report id without rebinding the old body", async () => {
  const posts: Record<string, unknown>[] = [];
  let reads = 0;
  global.fetch = jest.fn((url, init) => {
    if (String(url).includes("/trace")) return response({ run_id: "CERT-UI", context_id: ++reads === 1 ? "ctx-before" : "ctx-after" });
    const body = JSON.parse(String(init?.body));
    posts.push(body);
    return posts.length === 1 ? response({ detail: "stale_context: changed" }, 409)
      : response({ mode: "v2", receipt: { committed_watermark: 3 } });
  }) as jest.Mock;
  const { result } = renderHook(() => useProgressMapDelivery({ endpoint: "/validation-checks", bodyKey: "checks", map }));
  await waitFor(() => expect(result.current.delivered).toBe(true));
  expect(posts).toHaveLength(2);
  expect(posts[0].context_id).toBe("ctx-before");
  expect(posts[1].context_id).toBe("ctx-after");
  expect(posts[0].report_id).not.toBe(posts[1].report_id);
  expect(posts[0].checks).toEqual(posts[1].checks);
});
