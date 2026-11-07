// packages/ui/components/AdminGate.test.tsx
//
// AUTH-07 «Общая админка обеих оболочек» (spec_auth_architecture.md,
// строка 196): общий гейт доступа к админ-страницам ОБЕИХ оболочек.
// Оракул дословно: «Named ADMIN+MFA управляет реальными API
// standalone/embedded; analyst/OWNER получают отказ».
//
// Ключевые контракты:
//  * сессия проверяется через /api/v1/auth/me (named auth_session,
//    AUTH-04/05; MFA-принуждение -- серверная обязанность);
//  * не вошёл (401) -- ссылка на /login с return_to (локальный
//    allowlist safeReturnTo, AUTH-06);
//  * вошёл, но роль НЕ admin (internal_analyst; external_user с
//    membership_role=owner) -- различимый ОТКАЗ, дети НЕ рендерятся
//    (UI не заменяет серверную проверку -- она остаётся в api);
//  * admin -- дети рендерятся;
//  * сервис входа недоступен -- честное состояние + повторная проверка.
//
// Оракулы на СВОИХ данных: authMe мокается, компоненты дизъюнктны
// серверным репо-сюитам (tests/api).

import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AdminGate } from "./AdminGate";
import * as authClient from "../lib/authClient";

jest.mock("../lib/authClient", () => {
  const actual = jest.requireActual("../lib/authClient");
  return { ...actual, authMe: jest.fn() };
});
const mocked = authClient as jest.Mocked<typeof authClient>;

function session(
  role: "admin" | "internal_analyst" | "external_user",
  membership: "owner" | "member" = "member",
) {
  return {
    subject_id: "subj-g1aaaaaaaaaaaaaa",
    account_id: "acc-g1aaaaaaaaaaaaaa",
    tenant_id: "tenant-g1aaaaaaaaaaaa",
    membership_role: membership,
    role,
    auth_method: "auth_session" as const,
    auth_session_id: "sess-g1aaaaaaaaaaaaaa",
    auth_time: "2026-11-06T09:00:00+00:00",
    mfa_verified_at: "2026-11-06T09:00:01+00:00",
    // AUTH-08: admin permission is independent of this starter entitlement.
    account_plan: "starter" as const,
    account_type: "multi" as const,
    entitlement_version: 1,
    plan_expires_at: null,
    capabilities: {
      registry_version: "authz-registry/1" as const, capabilities_version: 2 as const,
      can_run_baseline_models: true, can_tune_models: false, can_train_custom_models: false,
      restricted_stage_ids: [],
      baseline_limits: { max_rows: 50000, max_folds: 5, max_horizon: 48, max_seasonal_period: 366, max_models: 3 },
      can_train_models: false, can_use_api: true, can_save_history: true, can_upload_own_data: true,
      max_dataset_rows: 50000, max_api_calls_per_month: 1000,
      max_analyses_total: null, trial_days: null, watermark_exports: false,
    },
  };
}

function Panel() {
  return <p data-testid="admin-content">Секретная админ-панель</p>;
}

describe("AdminGate (AUTH-07)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("admin -- дети рендерятся", async () => {
    mocked.authMe.mockResolvedValue(session("admin"));
    render(
      <AdminGate returnTo="/admin/progress">
        <Panel />
      </AdminGate>,
    );
    expect(await screen.findByTestId("admin-content")).toBeInTheDocument();
  });

  it("аноним -- ссылка на /login с локальным return_to, дети НЕ рендерятся", async () => {
    mocked.authMe.mockResolvedValue(null);
    render(
      <AdminGate returnTo="/admin/progress">
        <Panel />
      </AdminGate>,
    );
    const link = await screen.findByRole("link", { name: /войти как администратор/i });
    expect(link).toHaveAttribute(
      "href",
      "/login?return_to=" + encodeURIComponent("/admin/progress"),
    );
    expect(screen.queryByTestId("admin-content")).not.toBeInTheDocument();
  });

  it("internal_analyst -- различимый отказ, дети НЕ рендерятся", async () => {
    mocked.authMe.mockResolvedValue(session("internal_analyst"));
    render(
      <AdminGate>
        <Panel />
      </AdminGate>,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/администратор платформы/i);
    expect(screen.queryByTestId("admin-content")).not.toBeInTheDocument();
  });

  it("external_user с membership_role=owner (OWNER аккаунта) -- отказ", async () => {
    mocked.authMe.mockResolvedValue(session("external_user", "owner"));
    render(
      <AdminGate>
        <Panel />
      </AdminGate>,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/администратор платформы/i);
    expect(alert).toHaveTextContent(/владелец аккаунта/i);
    expect(screen.queryByTestId("admin-content")).not.toBeInTheDocument();
  });

  it("сервис входа недоступен -- честное состояние и повторная проверка", async () => {
    mocked.authMe
      .mockRejectedValueOnce(new authClient.AuthFailure(503, "auth_unavailable"))
      .mockResolvedValueOnce(session("admin"));
    render(
      <AdminGate>
        <Panel />
      </AdminGate>,
    );
    const retry = await screen.findByRole("button", { name: /проверить снова/i });
    expect(screen.queryByTestId("admin-content")).not.toBeInTheDocument();
    fireEvent.click(retry);
    await waitFor(() => {
      expect(screen.getByTestId("admin-content")).toBeInTheDocument();
    });
    // Повторная проверка состоялась (точное число вызовов не гейтится:
    // React 18 может дополнительно прогонять эффекты в act-окружении).
    expect(mocked.authMe.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("return_to вне allowlist не пробивается через пропсы (safeReturnTo)", async () => {
    mocked.authMe.mockResolvedValue(null);
    render(
      <AdminGate returnTo={"https://evil.example"}>
        <Panel />
      </AdminGate>,
    );
    const link = await screen.findByRole("link", { name: /войти как администратор/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("return_to=%2F"));
    expect(link.getAttribute("href")).not.toContain("evil");
  });
});
