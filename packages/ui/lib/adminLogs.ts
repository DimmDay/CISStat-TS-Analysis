import { apiFetch } from "./browserTransport";
// packages/ui/lib/adminLogs.ts
//
// DOCLOG-7 (спека §14.2, §15): клиент API журналов /v1/logs. Миграция
// AUTH-07: доступ -- named-сессия администратора (cookie через first-party
// /api-прокси, AUTH-06); X-API-Key из браузера НЕ отправляется
// (программный канал ключей сохранён на сервере до AUTH-10, но
// браузерная поверхность его больше не использует -- §15.1 «API-key не
// переносится в URL/storage/UI»). Типы -- контракты роутера
// apps/api/routers/logs.py. Роль/scopes/grants решает СЕРВЕР
// (resolve_effective_log_access); клиент возвращает дискриминированный
// результат { ok: true, data } | { ok: false, status } -- UI честно
// рендерит негативные состояния §12.3/AC17, не бросая исключения в
// компоненты.

import { getApiBase } from "./apiClient";

/** База /v1/logs (тот же first-party /api-прокси в проде). */
export function adminLogsApiUrl(path: string): string {
  return `${getApiBase()}/v1/logs${path}`;
}

// ── Типы контракта (§14.2 строки журнала; §15 доступ) ───────────────

export interface LogAccessInfo {
  principal: {
    subject_id: string | null;
    role: string | null;
  };
  access: {
    telemetry: boolean;
    audit: boolean;
    delivery: boolean;
    export: boolean;
    grants_management: boolean;
    scope: "unrestricted" | { tenants?: string[]; runs?: string[] };
  };
}

export interface TelemetryLogRecord {
  event_id: string;
  event_name: string;
  occurred_at: string;
  severity_text: string;
  message_template?: string | null;
  service?: string | null;
  service_version?: string | null;
  request_id?: string | null;
  operation_id?: string | null;
  research_run_id?: string | null;
  tenant_id?: string | null;
  outcome?: string | null;
  error_code?: string | null;
  duration_ms?: number | null;
  retry_attempt?: number | null;
  attributes?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface AuditLogRecord {
  audit_id: string;
  occurred_at: string;
  actor_subject: string | null;
  actor_via: string | null;
  tenant_id: string | null;
  action: string;
  decision: string;
  resource_kind: string | null;
  resource_id: string | null;
  policy_basis: string | null;
  request_id: string | null;
  run_id: string | null;
  details?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface DeliveryLogRecord {
  job_id: string;
  run_id: string;
  tenant_id: string | null;
  snapshot_id: string;
  format: string;
  redaction_profile: string;
  state: string;
  error_code: string | null;
  attempt: number;
  created_at: string;
  updated_at: string;
  document_id: string | null;
  kind_code: string | null;
  [key: string]: unknown;
}

export interface LogsMeta {
  stream: string;
  count: number;
  limit: number;
  window?: { from: string; to: string };
  order?: string;
  effective_scope: "unrestricted" | { tenants?: string[]; runs?: string[] };
  retention_horizon_days: number | null;
  retention_note?: string;
}

export interface LogsPage<T> {
  records: T[];
  next_cursor: string | null;
  meta: LogsMeta;
}

export interface GrantRecord {
  grant_id: string;
  ticket: string;
  purpose: string;
  subject_id: string;
  tenant_id: string;
  run_id: string | null;
  scopes: string[];
  created_by: string;
  created_at: string;
  expires_at: string;
  revoked_at?: string | null;
  revoked_by?: string | null;
  revoke_reason?: string;
}

export type ApiResult<T> = { ok: true; status: number; data: T } | { ok: false; status: number };

// ── Запрос (named-сессия; POST-команды -- через apiFetch с CSRF-retry) ─

async function requestJson<T>(
  url: string,
  init?: RequestInit,
): Promise<ApiResult<T>> {
  try {
    const response = await apiFetch(url, init);
    if (!response.ok) {
      return { ok: false, status: response.status };
    }
    const data = (await response.json()) as T;
    return { ok: true, status: response.status, data };
  } catch {
    return { ok: false, status: 0 }; // offline/сеть -- честное состояние
  }
}

// ── Доступ (GET /access) ─────────────────────────────────────────────

export async function fetchLogAccess(): Promise<ApiResult<LogAccessInfo>> {
  return requestJson<LogAccessInfo>(adminLogsApiUrl("/access"));
}

// ── Потоки (query-параметры -- whitelist роутера) ────────────────────

export interface TelemetryQuery {
  from?: string;
  to?: string;
  severity?: string;
  outcome?: string;
  event_name?: string;
  request_id?: string;
  run_id?: string;
  tenant_id?: string;
  cursor?: string;
  limit?: number;
}

export interface AuditQuery {
  from?: string;
  to?: string;
  action?: string;
  decision?: string;
  actor_subject?: string;
  request_id?: string;
  run_id?: string;
  tenant_id?: string;
  cursor?: string;
  limit?: number;
}

export interface DeliveryQuery {
  from?: string;
  to?: string;
  state?: string;
  format?: string;
  run_id?: string;
  tenant_id?: string;
  cursor?: string;
  limit?: number;
}

function toSearchParams(query: object): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query as Record<string, unknown>)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  return params;
}

export async function fetchTelemetryLogs(
  query: TelemetryQuery,
): Promise<ApiResult<LogsPage<TelemetryLogRecord>>> {
  const qs = toSearchParams(query).toString();
  return requestJson(adminLogsApiUrl(`/telemetry${qs ? `?${qs}` : ""}`));
}

export async function fetchAuditLogs(
  query: AuditQuery,
): Promise<ApiResult<LogsPage<AuditLogRecord>>> {
  const qs = toSearchParams(query).toString();
  return requestJson(adminLogsApiUrl(`/audit${qs ? `?${qs}` : ""}`));
}

export async function fetchDeliveryLogs(
  query: DeliveryQuery,
): Promise<ApiResult<LogsPage<DeliveryLogRecord>>> {
  const qs = toSearchParams(query).toString();
  return requestJson(adminLogsApiUrl(`/delivery${qs ? `?${qs}` : ""}`));
}

// ── Гранты (§14.2/§15) ───────────────────────────────────────────────

export interface GrantCreateInput {
  ticket: string;
  purpose: string;
  subject_id: string;
  tenant_id: string;
  run_id?: string | null;
  scopes: string[];
  ttl_hours: number;
}

export async function fetchGrants(): Promise<ApiResult<{ grants: GrantRecord[] }>> {
  return requestJson(adminLogsApiUrl("/grants"));
}

export async function createGrant(
  input: GrantCreateInput,
): Promise<ApiResult<{ grant_id: string }>> {
  return requestJson(adminLogsApiUrl("/grants"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function revokeGrant(
  grantId: string,
  reason: string,
): Promise<ApiResult<{ grant_id: string }>> {
  return requestJson(adminLogsApiUrl(`/grants/${encodeURIComponent(grantId)}/revoke`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

// ── Диагностический пакет (§14.2, AC10/AC19) ─────────────────────────

export interface BundleResult {
  ok: true;
  status: number;
  blob: Blob;
  filename: string;
}

export async function exportDiagnosticBundle(
  body: { from: string; to: string; streams?: string[] },
): Promise<BundleResult | { ok: false; status: number }> {
  try {
    const response = await apiFetch(adminLogsApiUrl("/export"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      return { ok: false, status: response.status };
    }
    const disposition = response.headers.get("content-disposition") ?? "";
    const match = /filename="?([^";]+)"?/.exec(disposition);
    return {
      ok: true,
      status: response.status,
      blob: await response.blob(),
      filename: match?.[1] ?? "diagnostic-bundle.zip",
    };
  } catch {
    return { ok: false, status: 0 };
  }
}
