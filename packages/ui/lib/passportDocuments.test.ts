// packages/ui/lib/passportDocuments.test.ts
//
// PGV-15: контракт клиента печатных семейств «Документов исследования».
// Оракулы: URL-формы маршрутов (паритет роутера), плоские коды ошибок
// §17/PGV-13, честная offline-семантика (§12.3), идемпотентная форма
// POST (mode/refs/checkpoint взаимоисключающи, single -- ровно один ref).

import {
  listPassportSources,
  listPrintDocuments,
  passportDocumentErrorText,
  requestPassportDocument,
  requestPrintRendition,
} from "./passportDocuments";

const fetchMock = jest.fn();
jest.mock("./browserTransport", () => ({
  apiFetch: (...args: unknown[]) => fetchMock(...args),
}));
jest.mock("./apiClient", () => ({
  getApiBase: () => "/api",
}));

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

beforeEach(() => {
  fetchMock.mockReset();
});

describe("passportDocuments — URL-формы маршрутов (паритет роутера PGV-13/15)", () => {
  it("listPassportSources: GET /runs/{run_id}/passport-sources", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { run_id: "RUN-1", snapshots: [], checkpoints: [] }),
    );
    const result = await listPassportSources("RUN-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/documentation/runs/RUN-1/passport-sources",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(result.ok).toBe(true);
    expect(result.data?.run_id).toBe("RUN-1");
  });

  it("listPrintDocuments: GET /runs/{run_id}/print-documents", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { run_id: "RUN-1", documents: [] }),
    );
    const result = await listPrintDocuments("RUN-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/documentation/runs/RUN-1/print-documents",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(result.ok).toBe(true);
  });

  it("requestPrintRendition: POST /print-revisions/{id}/renditions format=png", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(202, { job: { job_id: "djob-1", state: "queued" }, status_url: "/x" }),
    );
    const result = await requestPrintRendition("dprint-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/documentation/print-revisions/dprint-1/renditions",
      expect.objectContaining({ method: "POST" }),
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ format: "png" });
    expect(result.ok).toBe(true);
  });
});

describe("passportDocuments — форма POST passport-documents (§11/§13 критерий)", () => {
  it("set по чекпоинту: checkpoint_id без snapshot_refs (траектория, AC10)", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(202, { job: {} }));
    await requestPassportDocument({
      runId: "RUN-1",
      mode: "set",
      checkpointId: "pck-1",
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({ mode: "set", checkpoint_id: "pck-1" });
  });

  it("single по версии: ровно один snapshot_ref, checkpoint не передаётся", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(202, { job: {} }));
    await requestPassportDocument({
      runId: "RUN-1",
      mode: "single",
      snapshotRefs: ["rs-a"],
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({ mode: "single", snapshot_refs: ["rs-a"] });
  });

  it("compare по двум явным версиям: snapshot_refs без checkpoint (§11)", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(202, { job: {} }));
    await requestPassportDocument({
      runId: "RUN-1",
      mode: "compare",
      snapshotRefs: ["rs-a", "rs-b"],
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({ mode: "compare", snapshot_refs: ["rs-a", "rs-b"] });
  });
});

describe("passportDocuments — честные негативные состояния (§12.3)", () => {
  it("плоская ошибка {code,message} читается из тела ответа", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(409, { code: "comparison_incompatible", message: "не совпадают" }),
    );
    const result = await requestPassportDocument({
      runId: "RUN-1",
      mode: "compare",
      snapshotRefs: ["rs-a", "rs-b"],
    });
    expect(result.ok).toBe(false);
    expect(result.status).toBe(409);
    expect(result.error?.code).toBe("comparison_incompatible");
  });

  it("сеть недоступна -- status null (offline, не «нет документов»)", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network down"));
    const result = await listPassportSources("RUN-1");
    expect(result.ok).toBe(false);
    expect(result.status).toBeNull();
  });
});

describe("passportDocumentErrorText — человеческие фразы кодов", () => {
  it.each([
    [409, "source_unavailable", "недоступен"],
    [409, "comparison_incompatible", "несовместимы"],
    [422, "invalid_selection", "неполный"],
    [429, "quota_exceeded", "переполнена"],
    [404, "not_found", "недоступно"],
  ])("status %i code %s: содержит суть отказа", (status, code, needle) => {
    const text = passportDocumentErrorText(status, code);
    expect(text.toLowerCase()).toContain(needle);
  });

  it("status null: offline-фраза, не запрет", () => {
    const text = passportDocumentErrorText(null, null);
    expect(text).toContain("Сеть недоступна");
  });

  it("5xx без кода: временная недоступность сервиса", () => {
    expect(passportDocumentErrorText(503, null)).toContain("временно недоступен");
  });
});
