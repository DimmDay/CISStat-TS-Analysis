// packages/ui/context/prograuditccert_context_oracle.test.tsx
//
// PROGR-AUDIT-C-CERT (2026-10-10) — независимый TS-оракул аудита задачи
// AUDIT-C (план §6 GREEN: «API отдаёт устойчивый контекст, UI его
// получает»). ДИЗЪЮНКТЕН jest-оракулу разработчика
// AppShellContext.test.tsx: СВОИ значения сервера и СВОИ углы:
//   * клиент СЛЕДУЕТ серверу при ре-гидратации (refreshSession):
//     смена контекста НА СЕРВЕРЕ (смена цели/ревизии) видна клиенту
//     после refetch — фронт не держит устаревший счётчик и не ведёт
//     свой (план §1);
//   * мусорные типы полей сервера -> честный null (data_revision
//     строкой «7» — не число, догадка не конвертируется);
//   * пустая строка context_id от старого бэкенда -> ... серверная
//     конвенция: null либо ctx-*; пустая строка НЕ является честным
//     контекстом — но ??-гидратация сохраняет её как есть: пин текущей
//     семантики (клиент не конвертирует значения сервера молча);
//   * данные ревизии 0 не превращаются в null (0 — честное число).
//
// Мокируется только sessionApiUrl; реальная сеть в jest недоступна.

import "@testing-library/jest-dom";
import { render, screen, waitFor, act } from "@testing-library/react";
import React from "react";
import { AppShellProvider, useAppShell } from "./AppShellContext";

let mockCurrentBody: Record<string, unknown> = {};
let currentGets = 0;

jest.mock("../lib/apiClient", () => ({
  sessionApiUrl: (path: string) => `http://cert/api/v1/session${path}`,
}));

function jsonOk(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

function Probe() {
  const { contextId, dataRevision, refreshSession } = useAppShell();
  return (
    <div>
      <span data-testid="ctx">{contextId === undefined ? "undef" : (contextId ?? "null")}</span>
      <span data-testid="rev">{dataRevision === undefined ? "undef" : (dataRevision ?? "null")}</span>
      <button onClick={() => refreshSession()}>refresh</button>
    </div>
  );
}

function renderProbe() {
  return render(
    <AppShellProvider>
      <Probe />
    </AppShellProvider>,
  );
}

function body(over: Record<string, unknown> = {}) {
  return {
    has_active_dataset: true,
    dataset: { dataset_id: "D-CERTC", name: "hydro_meteo.csv", rows: 72, columns: 3, size_label: "3 KB" },
    stages: { upload: "done" },
    last_active_stage: "upload",
    target_column: "humidity",
    context_id: "ctx-certcfeedface0000",
    data_revision: 0,
    updated_at: "2026-10-10T21:00:00+00:00",
    ...over,
  };
}

describe("PROGR-AUDIT-C-CERT: гидратация серверного контекста (свои углы)", () => {
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

  it("клиент следует серверу: ре-гидратация подхватывает НОВЫЙ контекст после мутации на сервере (свой счётчик не ведётся)", async () => {
    mockCurrentBody = body({ context_id: "ctx-certcaaaa00000001", data_revision: 0 });
    const view = renderProbe();
    await waitFor(() => expect(screen.getByTestId("ctx").textContent).toBe("ctx-certcaaaa00000001"));
    expect(screen.getByTestId("rev").textContent).toBe("0");

    // На сервере применена коррекция и сменена цель: /current отдаёт
    // НОВЫЕ значения. Клиент после refreshSession обязан показать ИХ,
    // а не свой прежний снимок.
    mockCurrentBody = body({
      context_id: "ctx-certcbbbb00000002",
      data_revision: 3,
      target_column: "pressure",
    });
    await act(async () => {
      screen.getByText("refresh").click();
    });
    await waitFor(() => expect(screen.getByTestId("ctx").textContent).toBe("ctx-certcbbbb00000002"));
    expect(screen.getByTestId("rev").textContent).toBe("3");
    expect(currentGets).toBe(2);
    view.unmount();
  });

  it("мусорные типы -> честный null: data_revision строкой не конвертируется в число-догадку", async () => {
    mockCurrentBody = body({ data_revision: "7" as unknown as number });
    renderProbe();
    await waitFor(() => expect(currentGets).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId("ctx").textContent).toBe("ctx-certcfeedface0000"));
    expect(screen.getByTestId("rev").textContent).toBe("null");
  });

  it("data_revision 0 — честное число (0 не превращается в null), отсутствие поля — null", async () => {
    mockCurrentBody = body({ data_revision: 0 });
    const view = renderProbe();
    await waitFor(() => expect(screen.getByTestId("rev").textContent).toBe("0"));
    // отсутствие поля (старый бэкенд) — честный null
    const { data_revision: _drop, ...withoutRev } = body();
    mockCurrentBody = withoutRev;
    await act(async () => {
      screen.getByText("refresh").click();
    });
    await waitFor(() => expect(screen.getByTestId("rev").textContent).toBe("null"));
    view.unmount();
  });
});
