// packages/ui/context/AppShellContext.test.tsx
//
// PROGR-AUDIT-C (plan_progress_audit.md §6, GREEN карточки: «API отдаёт
// устойчивый контекст, UI его получает»; гидратация UI -- точка карточки).
//
// Приёмка: провайдер гидратирует contextId/dataRevision ИЗ ОТВЕТА СЕРВЕРА
// (/v1/session/current) -- клиент контекст не вычисляет и счётчик версий
// не ведёт (план §1: «Новый контекст не создавать догадками фронтенда»).
// Отсутствие полей (старый бэкенд / нет активного датасета) -- честный
// null, не догадка. Мокируется только свой URL; реальная сеть недоступна
// в jest.

import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { AppShellProvider, useAppShell } from "./AppShellContext";

let mockCurrentBody: Record<string, unknown> = {};
let currentGets = 0;

jest.mock("../lib/apiClient", () => ({
  sessionApiUrl: (path: string) => `http://test/api/v1/session${path}`,
}));

function jsonOk(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

function Probe() {
  const { contextId, dataRevision, targetColumn } = useAppShell();
  return (
    <div>
      <span data-testid="context-id">{contextId === undefined ? "undef" : (contextId ?? "null")}</span>
      <span data-testid="data-revision">
        {dataRevision === undefined ? "undef" : String(dataRevision)}
      </span>
      <span data-testid="target-column">{targetColumn ?? "null"}</span>
    </div>
  );
}

describe("AppShellContext: гидратация серверного контекста расчёта (AUDIT-C)", () => {
  beforeEach(() => {
    currentGets = 0;
    global.fetch = jest.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/v1/session/current")) {
        currentGets += 1;
        return jsonOk(mockCurrentBody);
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    }) as jest.Mock;
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  function renderProbe() {
    return render(
      <AppShellProvider>
        <Probe />
      </AppShellProvider>,
    );
  }

  it("гидратирует contextId/dataRevision из ответа сервера", async () => {
    mockCurrentBody = {
      has_active_dataset: true,
      dataset: { dataset_id: "D-C", name: "data.csv", rows: 4, columns: 2, size_label: "1 KB" },
      stages: { upload: "done" },
      last_active_stage: "upload",
      target_column: "rain",
      context_id: "ctx-abcdef0123456789",
      data_revision: 2,
      updated_at: "2026-10-10T00:00:00+00:00",
    };
    renderProbe();
    await waitFor(() => expect(currentGets).toBeGreaterThan(0));
    await waitFor(() =>
      expect(screen.getByTestId("context-id").textContent).toBe("ctx-abcdef0123456789"),
    );
    expect(screen.getByTestId("data-revision").textContent).toBe("2");
    expect(screen.getByTestId("target-column").textContent).toBe("rain");
  });

  it("отсутствие полей (старый бэкенд) -- честный null, не догадка", async () => {
    mockCurrentBody = {
      has_active_dataset: true,
      dataset: { dataset_id: "D-C", name: "data.csv", rows: 4, columns: 2, size_label: "1 KB" },
      stages: { upload: "done" },
      last_active_stage: "upload",
      target_column: "rain",
      updated_at: "2026-10-10T00:00:00+00:00",
    };
    renderProbe();
    await waitFor(() => expect(currentGets).toBeGreaterThan(0));
    await waitFor(() =>
      expect(screen.getByTestId("context-id").textContent).toBe("null"),
    );
    expect(screen.getByTestId("data-revision").textContent).toBe("null");
  });

  it("нет активного датасета -- контекст null (контекст существует только у запуска)", async () => {
    mockCurrentBody = {
      has_active_dataset: false,
      dataset: null,
      stages: {},
      last_active_stage: null,
      target_column: null,
      context_id: null,
      data_revision: 0,
      updated_at: "2026-10-10T00:00:00+00:00",
    };
    renderProbe();
    await waitFor(() => expect(currentGets).toBeGreaterThan(0));
    await waitFor(() =>
      expect(screen.getByTestId("context-id").textContent).toBe("null"),
    );
  });
});
