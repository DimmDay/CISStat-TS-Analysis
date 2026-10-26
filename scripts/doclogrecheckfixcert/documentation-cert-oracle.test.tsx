// scripts/doclogrecheckfixcert/documentation-cert-oracle.test.tsx
//
// Собственный сертификационный оракул DOCLOG-E2E-RECHECK-1-FIX (UI-слой,
// база 9401fa5). Дополняет packages/ui/components/
// documentation-recheck-fix.test.tsx:
//
//   OC1 -- resolveCurrentRun (C01-новинка fix-коммита): честное
//          разрешение текущего run из единого источника /v1/progress/
//          trace; отсутствие run -- { ok: true, run_id: null }, а не
//          ошибка; отказ сети -- { ok: false }.
//   OC2 -- createErrorText (C07-новинка fix-коммита): честные тексты
//          отказа по статусам, null -- недоступность сервиса.

import "@testing-library/jest-dom";

jest.mock("../../packages/ui/lib/apiClient", () => ({
  getApiBase: () => "",
}));

import {
  resolveCurrentRun,
} from "../../packages/ui/lib/documentation";
import { createErrorText } from "../../packages/ui/components/DocumentationWorkspace";

describe("DOCLOG-E2E-RECHECK-1-FIX: certifier oracle (lib layer)", () => {
  const realFetch = global.fetch;

  afterEach(() => {
    global.fetch = realFetch;
    jest.restoreAllMocks();
  });

  it("OC1: resolveCurrentRun возвращает run_id из /v1/progress/trace", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ run_id: "RUN-RCFCERT-UI", context_id: "ctx-x" }),
    }) as unknown as typeof fetch;
    const result = await resolveCurrentRun();
    expect(result.ok).toBe(true);
    expect(result.data?.run_id).toBe("RUN-RCFCERT-UI");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/v1/progress/trace"),
      expect.anything(),
    );
  });

  it("OC1: отсутствие run -- честный null, не ошибка", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ run_id: null }),
    }) as unknown as typeof fetch;
    const result = await resolveCurrentRun();
    expect(result.ok).toBe(true);
    expect(result.data?.run_id).toBeNull();
  });

  it("OC1: отказ сети -- ok:false без фабрикации run", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({}),
    }) as unknown as typeof fetch;
    const result = await resolveCurrentRun();
    expect(result.ok).toBe(false);
    expect(result.status).toBe(503);
  });

  it("OC2: createErrorText покрывает 403/404/409/422/503 и null", () => {
    expect(createErrorText(null)).toMatch(/недоступ/i);
    expect(createErrorText(403)).toMatch(/субъект/i);
    expect(createErrorText(404)).toMatch(/не найдено|недоступно/i);
    expect(createErrorText(409)).toMatch(/409/);
    expect(createErrorText(422)).toMatch(/422/);
    expect(createErrorText(503)).toMatch(/503/);
    expect(createErrorText(500)).toMatch(/500/);
  });
});
