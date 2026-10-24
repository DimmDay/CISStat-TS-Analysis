// packages/ui/components/adminLogs-dashboard.test.tsx
//
// DOCLOG-7 (спека §14.2, §15, AC10/AC17): панель «Администрирование →
// Журналы» -- три вкладки (Технические события / Аудит доступа /
// Доставка и документы), whitelist-фильтры (БЕЗ произвольного SQL/regex
// от браузера), cursor pagination, live tail с честной паузой и счётчиком
// пропусков, диагностический пакет с явным перечнем исключений, гранты
// поддержки с TTL/отзывом. Ключ живёт ТОЛЬКО в стейте (паттерн
// AdminProgressDashboard), 401/403 -- различимые честные состояния.
//
// Оракулы на СВОИХ данных: клиенты lib/adminLogs мокаются; корпус
// дизъюнктен серверным репо-сюитам (tests/api).

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

type AccessResult = { ok: true; status: number; data: adminLogs.LogAccessInfo };
type TelemetryResult = { ok: true; status: number; data: adminLogs.LogsPage<adminLogs.TelemetryLogRecord> };
type GrantsResult = { ok: true; status: number; data: { grants: adminLogs.GrantRecord[] } };

const ADMIN_ACCESS: AccessResult = {
  ok: true as const,
  status: 200,
  data: {
    principal: { subject_id: "subj-d7aaaaaaaaaaaaaa", role: "admin" },
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

const TELEMETRY_PAGE: TelemetryResult = {
  ok: true as const,
  status: 200,
  data: {
    records: [
      {
        event_id: "ev-d7-1",
        event_name: "api.request",
        occurred_at: "2026-10-24T12:00:00+00:00",
        severity_text: "info",
        outcome: "success",
        service: "cisstat-api",
        service_version: "1.0.0",
        request_id: "req-d7-1",
        run_id: "RUN-D7A00001",
        tenant_id: "tenant-d7core",
        error_code: null,
        retry_attempt: null,
        message_template: "событие d7",
      },
    ],
    next_cursor: "d7cursor",
    meta: {
      stream: "telemetry",
      count: 1,
      limit: 50,
      retention_horizon_days: 30,
      effective_scope: "unrestricted",
    },
  },
};

const GRANTS_PAGE: GrantsResult = {
  ok: true as const,
  status: 200,
  data: {
    grants: [
      {
        grant_id: "d7grant-1",
        ticket: "d7-ticket-42",
        purpose: "разбор инцидента",
        subject_id: "subj-d7bbbbbbbbbbbbbb",
        tenant_id: "tenant-d7core",
        run_id: null,
        scopes: ["logs.read"],
        created_by: "subj-d7aaaaaaaaaaaaaa",
        created_at: "2026-10-24T10:00:00+00:00",
        expires_at: "2026-10-25T10:00:00+00:00",
        revoked_at: null,
      },
    ],
  },
};

function typeKeyAndSubmit() {
  const keyInput = screen.getByLabelText("API-ключ администратора");
  fireEvent.change(keyInput, { target: { value: "d7-admin-key-1111" } });
  fireEvent.click(screen.getByRole("button", { name: "Открыть журналы" }));
}

describe("AdminLogsDashboard (DOCLOG-7)", () => {
  beforeEach(() => {
    jest.resetAllMocks();
    localStorage.clear();
  });

  it("401 -- честное состояние неверного ключа", async () => {
    mocked.fetchLogAccess.mockResolvedValue({ ok: false, status: 401 });
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    expect(
      await screen.findByText(/Неверный API-ключ/i)
    ).toBeInTheDocument();
  });

  it("403 -- различимое состояние не-админа", async () => {
    mocked.fetchLogAccess.mockResolvedValue({ ok: false, status: 403 });
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    expect(await screen.findByText(/недостаточно прав/i)).toBeInTheDocument();
  });

  it("три вкладки + открытая вкладка загружает поток", async () => {
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS);
    mocked.fetchTelemetryLogs.mockResolvedValue(TELEMETRY_PAGE);
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    expect(
      await screen.findByRole("tab", { name: "Технические события" })
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Аудит доступа" })).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Доставка и документы" })
    ).toBeInTheDocument();
    await waitFor(() => expect(mocked.fetchTelemetryLogs).toHaveBeenCalled());
    expect(await screen.findByText("api.request")).toBeInTheDocument();
  });

  it("whitelist-фильтры: нет свободного SQL/regex ввода", async () => {
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS);
    mocked.fetchTelemetryLogs.mockResolvedValue(TELEMETRY_PAGE);
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    await screen.findByRole("tab", { name: "Технические события" });
    // Ни одного многострочного поля произвольного ввода (§14.2).
    expect(document.querySelector("textarea")).toBeNull();
    // Фильтры -- ограниченные inputs (точные метки: грантовская
    // "Run ID гранта" не должна перехватывать матчер).
    expect(screen.getByLabelText("Request ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Run ID")).toBeInTheDocument();
  });

  it("cursor pagination -- кнопка следующей страницы передаёт курсор", async () => {
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS);
    mocked.fetchTelemetryLogs.mockResolvedValue(TELEMETRY_PAGE);
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    const next = await screen.findByRole("button", { name: "Следующая страница" });
    fireEvent.click(next);
    await waitFor(() =>
      expect(mocked.fetchTelemetryLogs).toHaveBeenLastCalledWith(
        expect.anything(),
        expect.objectContaining({ cursor: "d7cursor" })
      )
    );
  });

  it("live tail пауза показывает счётчик пропусков", async () => {
    jest.useFakeTimers();
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS);
    mocked.fetchTelemetryLogs.mockResolvedValue(TELEMETRY_PAGE);
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    const toggle = await screen.findByRole("checkbox", { name: /Live tail/i });
    fireEvent.click(toggle); // выключить -> пауза
    await screen.findByText(/Пауза: пропущено обновлений: 0/i);
    jest.advanceTimersByTime(11000);
    expect(await screen.findByText(/Пауза: пропущено обновлений: 2/i)).toBeInTheDocument();
    jest.useRealTimers();
  });

  it("диагностический пакет: кнопка + честный перечень исключений", async () => {
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS);
    mocked.fetchTelemetryLogs.mockResolvedValue(TELEMETRY_PAGE);
    mocked.exportDiagnosticBundle.mockResolvedValue({
      ok: true,
      status: 200,
      blob: new Blob(["PK"], { type: "application/zip" }),
      filename: "diagnostic-d7.zip",
    } as never);
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    const button = await screen.findByRole("button", {
      name: /Создать диагностический пакет/i,
    });
    expect(
      screen.getByText(/не включает источники, строки данных, cookies или env values/i)
    ).toBeInTheDocument();
    fireEvent.click(button);
    await waitFor(() => expect(mocked.exportDiagnosticBundle).toHaveBeenCalled());
  });

  it("гранты: список + создание + отзыв", async () => {
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS);
    mocked.fetchTelemetryLogs.mockResolvedValue(TELEMETRY_PAGE);
    mocked.fetchGrants.mockResolvedValue(GRANTS_PAGE);
    mocked.createGrant.mockResolvedValue({
      ok: true,
      status: 201,
      data: { grant_id: "d7grant-2" },
    });
    mocked.revokeGrant.mockResolvedValue({ ok: true, status: 200, data: { grant_id: "d7grant-1" } });
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    await screen.findByText("d7-ticket-42");
    // Создание: TTL ограничен селектом (whitelist), не свободным числом.
    fireEvent.change(screen.getByLabelText("Ticket"), {
      target: { value: "d7-ticket-43" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Выдать грант/i }));
    await waitFor(() => expect(mocked.createGrant).toHaveBeenCalled());
    fireEvent.click(screen.getAllByRole("button", { name: /Отозвать/i })[0]);
    await waitFor(() => expect(mocked.revokeGrant).toHaveBeenCalled());
  });

  it("ключ не попадает в localStorage/sessionStorage", async () => {
    mocked.fetchLogAccess.mockResolvedValue(ADMIN_ACCESS);
    mocked.fetchTelemetryLogs.mockResolvedValue(TELEMETRY_PAGE);
    render(<AdminLogsDashboard />);
    typeKeyAndSubmit();
    await screen.findByRole("tab", { name: "Технические события" });
    expect(localStorage.getItem("cisstat_admin_key")).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });
});
