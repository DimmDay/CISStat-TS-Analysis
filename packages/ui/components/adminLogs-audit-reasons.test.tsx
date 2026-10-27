// packages/ui/components/adminLogs-audit-reasons.test.tsx
//
// Task ID: DOCLOG-H29-UIHONEST-AUDITVIEW (2026-10-27) -- рекомендация
// «Наблюдаемость: админ-представление security-audit (reason_code по
// run)» из AUTH-SCENARIO-ANALYST-DOCS §6 (база a4277b9).
//
// Инцидент «у меня запрещён» разбирается по ФАКТИЧЕСКОЙ причине:
//   1. строки «Аудита доступа» показывают reason_code из details
//      (record_run_access_decision пишет {"reason_code": ...}) -- ранее
//      причина была спрятана в expandable-detail (или отсутствовала
//      вовсе на PG-бекенде, см. python-корпус);
//   2. пресет «Причины отказов доступа» на вкладке «Аудит доступа» --
//      в один клик ставит whitelist-фильтры action=run_access_denied +
//      decision=denied и перечитывает поток (БЕЗ произвольного
//      SQL/regex от браузера, §14.2 -- значения фиксированные).
//
// Оракулы на СВОИХ данных (d8-*); клиенты lib/adminLogs мокаются,
// корпус дизъюнктен серверным репо-сюитам (tests/api).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AdminLogsDashboard } from "./AdminLogsDashboard";
import * as adminLogs from "../lib/adminLogs";

jest.mock("../lib/adminLogs", () => {
  const actual = jest.requireActual("../lib/adminLogs");
  return {
    ...actual,
    fetchLogAccess: jest.fn(),
    fetchTelemetryLogs: jest.fn(),
    fetchAuditLogs: jest.fn(),
    fetchDeliveryLogs: jest.fn(),
    fetchGrants: jest.fn(),
    createGrant: jest.fn(),
    revokeGrant: jest.fn(),
    exportDiagnosticBundle: jest.fn(),
  };
});

const mocked = adminLogs as jest.Mocked<typeof adminLogs>;

const ADMIN_ACCESS = {
  ok: true as const,
  status: 200,
  data: {
    principal: { subject_id: "subj-d8aaaaaaaaaaaaaa", role: "admin" },
    access: {
      telemetry: true,
      audit: true,
      delivery: true,
      export: true,
      grants_management: true,
      scope: "unrestricted",
    },
  },
};

const DENIED_PAGE = {
  ok: true as const,
  status: 200,
  data: {
    records: [
      {
        audit_id: "d8-audit-1",
        occurred_at: "2026-10-27T09:00:00+00:00",
        actor_subject: "subj-d8bbbbbbbbbbbbbb",
        actor_via: "session_cookie",
        tenant_id: null,
        action: "run_access_denied",
        decision: "denied",
        resource_kind: "run",
        resource_id: "RUN-D8A00001",
        policy_basis: "R09 object authorization",
        request_id: "req-d8-1",
        run_id: "RUN-D8A00001",
        details: { reason_code: "foreign_session", action: "list_documents" },
      },
      {
        audit_id: "d8-audit-2",
        occurred_at: "2026-10-27T09:01:00+00:00",
        actor_subject: "anon-d8cccccccccccccc",
        actor_via: "anonymous",
        tenant_id: null,
        action: "run_access_denied",
        decision: "denied",
        resource_kind: "run",
        resource_id: "RUN-D8B00002",
        policy_basis: "R09 object authorization",
        request_id: "req-d8-2",
        run_id: "RUN-D8B00002",
        details: { reason_code: "anonymous", action: "list_documents" },
      },
    ],
    next_cursor: null,
    meta: {
      stream: "audit",
      count: 2,
      limit: 50,
      retention_horizon_days: 365,
      effective_scope: "unrestricted",
    },
  },
};

function typeKeyAndSubmit() {
  const keyInput = screen.getByLabelText("API-ключ администратора");
  fireEvent.change(keyInput, { target: { value: "d8-admin-key-1111" } });
  fireEvent.click(screen.getByRole("button", { name: "Открыть журналы" }));
}

// Начальная вкладка панели -- telemetry: при открытии она всегда
// загружается (эффект первой загрузки); сюита целит вкладку audit.
const EMPTY_TELEMETRY = {
  ok: true as const,
  status: 200,
  data: {
    records: [],
    next_cursor: null,
    meta: {
      stream: "telemetry",
      count: 0,
      limit: 50,
      retention_horizon_days: 30,
      effective_scope: "unrestricted",
    },
  },
};

beforeEach(() => {
  jest.resetAllMocks();
  localStorage.clear();
});

describe("AdminLogsDashboard — admin-вью audit-причин (H29/UIH)", () => {
  it("строки аудита показывают reason_code из details (причина отказа видна сразу)", async () => {
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS as never);
    mocked.fetchTelemetryLogs.mockResolvedValue(EMPTY_TELEMETRY as never);
    mocked.fetchAuditLogs.mockResolvedValue(DENIED_PAGE as never);
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    fireEvent.click(await screen.findByRole("tab", { name: "Аудит доступа" }));

    expect(await screen.findByText(/foreign_session/)).toBeInTheDocument();
    expect(screen.getByText(/anonymous/)).toBeInTheDocument();
  });

  it("пресет «Причины отказов доступа»: whitelist-фильтры run_access_denied+denied и перечитывание потока", async () => {
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS as never);
    mocked.fetchTelemetryLogs.mockResolvedValue(EMPTY_TELEMETRY as never);
    mocked.fetchAuditLogs.mockResolvedValue(DENIED_PAGE as never);
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    fireEvent.click(await screen.findByRole("tab", { name: "Аудит доступа" }));
    await screen.findByText(/foreign_session/);

    const preset = screen.getByRole("button", { name: "Причины отказов доступа" });
    fireEvent.click(preset);

    await waitFor(() => {
      expect(mocked.fetchAuditLogs).toHaveBeenLastCalledWith(
        expect.anything(),
        expect.objectContaining({
          action: "run_access_denied",
          decision: "denied",
        }),
      );
    });
    // Фильтры отражены в контролах (честное состояние whitelist-полей).
    expect(
      (screen.getByLabelText("Действие (action)") as HTMLInputElement).value,
    ).toBe("run_access_denied");
  });

  it("пресет отсутствует на других вкладках (scope честный)", async () => {
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS as never);
    mocked.fetchTelemetryLogs.mockResolvedValue({
      ok: true,
      status: 200,
      data: { records: [], next_cursor: null, meta: { stream: "telemetry", count: 0, limit: 50, retention_horizon_days: 30, effective_scope: "unrestricted" } },
    });
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    await screen.findByRole("tab", { name: "Технические события" });
    expect(
      screen.queryByRole("button", { name: "Причины отказов доступа" }),
    ).not.toBeInTheDocument();
  });
});
