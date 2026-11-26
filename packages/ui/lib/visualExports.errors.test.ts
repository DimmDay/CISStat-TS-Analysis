import { parseExportErrorBody } from "./exportErrors";
import { requestVisualExport, visualExportErrorText } from "./visualExports";
import { requestPassportDocument, passportDocumentErrorText } from "./passportDocuments";

const fetchMock = jest.fn();
jest.mock("./browserTransport", () => ({ apiFetch: (...args: unknown[]) => fetchMock(...args) }));
jest.mock("./apiClient", () => ({ getApiBase: () => "/api" }));

beforeEach(() => fetchMock.mockReset());

test.each([
  { code: "worker_service_unavailable", message: "safe" },
  { detail: { code: "worker_service_unavailable", message: "safe" } },
  { error: { code: "worker_service_unavailable", message: "safe" } },
])("reads the actual authority error envelope %j", (body) => {
  expect(parseExportErrorBody(body)).toEqual({ code: "worker_service_unavailable", message: "safe" });
});

test("separates missing service configuration from a busy operation", () => {
  expect(visualExportErrorText(503, "worker_service_unavailable")).toContain("администратору");
  expect(visualExportErrorText(429, "concurrency_exceeded")).toContain("завершения");
  expect(visualExportErrorText(503, "unexpected_unknown")).toBe("Экспорт временно недоступен — повторите позднее.");
});

test("invalid envelopes cannot supply arbitrary code/message values", () => {
  for (const body of [null, [], {detail:"secret-like text"}, {code:42, message:{token:"never"}}]) {
    expect(parseExportErrorBody(body)).toEqual({code:null, message:null});
  }
});

test.each(["visual", "passport"])("%s client retains actual FastAPI authority details", async (kind) => {
  fetchMock.mockResolvedValueOnce({ok: false, status: 503,
    json: async () => ({detail: {code: "worker_service_unavailable", message: "safe"}})});
  const response = kind === "visual"
    ? await requestVisualExport({runId: "run-1", viewId: "upload.overview.tech_table"})
    : await requestPassportDocument({runId: "run-1", mode: "single", snapshotRefs: ["rs-1"]});
  expect(response).toMatchObject({ok: false, status: 503,
    error: {code: "worker_service_unavailable", message: "safe"}});
  expect(passportDocumentErrorText(response.status, response.error!.code)).toContain("администратору");
});
