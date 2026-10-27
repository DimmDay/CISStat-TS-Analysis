"use client";

// packages/ui/components/AdminLogsDashboard.tsx
//
// DOCLOG-7 (спека §14.2, §15, AC10/AC11/AC17): область
// «Администрирование → Журналы» -- РЯДОМ с агрегатами «Прогресса»
// (AdminProgressDashboard), не вместо них.
//
// Три вкладки §14.2: «Технические события» (telemetry), «Аудит доступа»
// (security audit), «Доставка и документы» (documents/jobs).
//
// Ключ -- паттерн AdminProgressDashboard: вводится в панели, живёт
// ТОЛЬКО в стейте (перезагрузка -- повторный ввод), НЕ попадает в
// localStorage/sessionStorage/URL и уходит только в заголовке X-API-Key.
//
// §14.2 дословно:
//  * «Без произвольного SQL/регулярных выражений от браузера к
//    backend; whitelist фильтров и лимиты запроса» -- только
//    ограниченные inputs/selects, никаких textarea/свободных выражений;
//  * cursor pagination («Следующая страница» по next_cursor);
//  * «Live tail приостанавливается и показывает число пропусков» --
//    пауза не скачивает историю, счётчик пропущенных тиков честный;
//  * «Кнопка „Создать диагностический пакет"» -- redacted JSONL+manifest,
//    с явным перечнем исключений (пакет «без данных»);
//  * гранты поддержки -- ticket/purpose, TTL-селект из whitelist,
//    отзыв с причиной; все действия учитываются на бекенде.
//
// AC17: пустые/загрузка/401/403/оффлайн/5xx -- различимые честные
// состояния; клавиатура/labels/aria для всех контролов.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createGrant,
  exportDiagnosticBundle,
  fetchAuditLogs,
  fetchDeliveryLogs,
  fetchGrants,
  fetchLogAccess,
  fetchTelemetryLogs,
  revokeGrant,
  type AuditLogRecord,
  type DeliveryLogRecord,
  type GrantRecord,
  type LogAccessInfo,
  type LogsPage,
  type TelemetryLogRecord,
} from "../lib/adminLogs";

type TabKey = "telemetry" | "audit" | "delivery";

const TABS: ReadonlyArray<{ key: TabKey; label: string }> = [
  { key: "telemetry", label: "Технические события" },
  { key: "audit", label: "Аудит доступа" },
  { key: "delivery", label: "Доставка и документы" },
];

const SEVERITY_OPTIONS = ["INFO", "WARN", "ERROR", "DEBUG"] as const;
const OUTCOME_OPTIONS = ["success", "denied", "error"] as const;
const DECISION_OPTIONS = ["allowed", "denied"] as const;
const JOB_STATE_OPTIONS = ["queued", "rendering", "ready", "failed", "cancelled"] as const;
const GRANT_SCOPE_OPTIONS = ["logs.read", "audit.read", "logs.export"] as const;
// TTL -- whitelist-селект (§14.2: ограничение по времени; максимум 168h).
const TTL_OPTIONS = [4, 24, 72, 168] as const;

function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19) + " UTC";
}

function scopeText(scope: LogAccessInfo["access"]["scope"]): string {
  if (scope === "unrestricted") return "весь каталог";
  const tenants = scope.tenants?.length ? scope.tenants.join(", ") : "—";
  const runs = scope.runs?.length ? scope.runs.join(", ") : "—";
  return `tenants: ${tenants}; runs: ${runs}`;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-700 dark:bg-neutral-900">
      <h3 className="text-sm font-semibold text-neutral-800 dark:text-neutral-100">{title}</h3>
      <div className="mt-2 text-sm text-neutral-700 dark:text-neutral-300">{children}</div>
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-neutral-600 dark:text-neutral-400">
      <span>{label}</span>
      {children}
    </label>
  );
}

const inputClass =
  "rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm text-neutral-900 outline-none focus:border-neutral-500 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100";

interface FilterState {
  request_id: string;
  run_id: string;
  tenant_id: string;
  severity: string;
  outcome: string;
  event_name: string;
  action: string;
  decision: string;
  state: string;
  format: string;
}

const EMPTY_FILTERS: FilterState = {
  request_id: "",
  run_id: "",
  tenant_id: "",
  severity: "",
  outcome: "",
  event_name: "",
  action: "",
  decision: "",
  state: "",
  format: "",
};

function filtersForTab(tab: TabKey, filters: FilterState): Record<string, string> {
  if (tab === "telemetry") {
    return {
      request_id: filters.request_id,
      run_id: filters.run_id,
      tenant_id: filters.tenant_id,
      severity: filters.severity,
      outcome: filters.outcome,
      event_name: filters.event_name,
    };
  }
  if (tab === "audit") {
    return {
      request_id: filters.request_id,
      run_id: filters.run_id,
      tenant_id: filters.tenant_id,
      action: filters.action,
      decision: filters.decision,
    };
  }
  return {
    run_id: filters.run_id,
    tenant_id: filters.tenant_id,
    state: filters.state,
    format: filters.format,
  };
}

export function AdminLogsDashboard() {
  // Ключ -- ТОЛЬКО в стейте (§15.1/паттерн AdminProgressDashboard).
  const [keyInput, setKeyInput] = useState("");
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [access, setAccess] = useState<LogAccessInfo | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const [tab, setTab] = useState<TabKey>("telemetry");
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);

  const [telemetryPage, setTelemetryPage] = useState<LogsPage<TelemetryLogRecord> | null>(null);
  const [auditPage, setAuditPage] = useState<LogsPage<AuditLogRecord> | null>(null);
  const [deliveryPage, setDeliveryPage] = useState<LogsPage<DeliveryLogRecord> | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);

  const [liveTail, setLiveTail] = useState(true);
  const [skippedTicks, setSkippedTicks] = useState(0);
  const [loading, setLoading] = useState(false);

  const [grants, setGrants] = useState<GrantRecord[] | null>(null);
  const [grantTicket, setGrantTicket] = useState("");
  const [grantPurpose, setGrantPurpose] = useState("");
  const [grantSubject, setGrantSubject] = useState("");
  const [grantTenant, setGrantTenant] = useState("");
  const [grantRun, setGrantRun] = useState("");
  const [grantTtl, setGrantTtl] = useState<number>(24);
  const [grantScopes, setGrantScopes] = useState<string[]>(["logs.read"]);
  const [revokeReason, setRevokeReason] = useState("");
  const [grantMessage, setGrantMessage] = useState<string | null>(null);

  const [bundleBusy, setBundleBusy] = useState(false);
  const [bundleMessage, setBundleMessage] = useState<string | null>(null);

  const liveTailRef = useRef(liveTail);
  liveTailRef.current = liveTail;

  const loadStream = useCallback(
    async (which: TabKey, key: string, cursor?: string, append = false, filterOverride?: FilterState) => {
      setLoading(true);
      setStreamError(null);
      // H29-UIH (2026-10-27): filterOverride -- пресет «Причины отказов
      // доступа»: применяет фиксированные whitelist-значения синхронно с
      // перечитыванием (setFilters асинхронен -- замыкание не увидело бы).
      const base = filtersForTab(which, filterOverride ?? filters);
      const query = { ...base, limit: 50, cursor };
      let result;
      if (which === "telemetry") {
        result = await fetchTelemetryLogs(key, query);
        if (result.ok)
          setTelemetryPage(
            append
              ? (mergePage(telemetryPage, result.data) as LogsPage<TelemetryLogRecord>)
              : result.data,
          );
      } else if (which === "audit") {
        result = await fetchAuditLogs(key, query);
        if (result.ok)
          setAuditPage(
            append
              ? (mergePage(auditPage, result.data) as LogsPage<AuditLogRecord>)
              : result.data,
          );
      } else {
        result = await fetchDeliveryLogs(key, query);
        if (result.ok)
          setDeliveryPage(
            append
              ? (mergePage(deliveryPage, result.data) as LogsPage<DeliveryLogRecord>)
              : result.data,
          );
      }
      if (!result) {
        setStreamError(streamErrorText(0));
      } else if (!result.ok) {
        setStreamError(streamErrorText(result.status));
      }
      setLoading(false);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [filters, telemetryPage, auditPage, deliveryPage],
  );

  const refreshGrants = useCallback(async (key: string) => {
    const result = await fetchGrants(key);
    if (!result) return; // честная деградация: список грантов недоступен
    if (result.ok) setGrants(result.data.grants);
  }, []);

  const handleOpen = useCallback(async () => {
    setOpenError(null);
    const key = keyInput;
    if (!key.trim()) {
      setOpenError("Введите API-ключ.");
      return;
    }
    const result = await fetchLogAccess(key);
    if (!result.ok) {
      setOpenError(accessErrorText(result.status));
      return;
    }
    setApiKey(key);
    setAccess(result.data);
  }, [keyInput]);

  // Первая загрузка открытой вкладки + грантов.
  useEffect(() => {
    if (!apiKey || !access) return;
    void loadStream(tab, apiKey);
    if (access.access.grants_management) {
      void refreshGrants(apiKey);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, access, tab]);

  // Live tail (§14.2): тик 5с; на паузе -- счётчик пропусков, без
  // скачивания истории; включён -- тихое обновление открытой вкладки.
  useEffect(() => {
    if (!apiKey) return;
    const id = setInterval(() => {
      if (!liveTailRef.current) {
        setSkippedTicks((n) => n + 1);
        return;
      }
      void loadStream(tab, apiKey);
    }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, tab, loadStream]);

  const handleBundle = useCallback(async () => {
    if (!apiKey) return;
    setBundleBusy(true);
    setBundleMessage(null);
    const to = new Date();
    const from = new Date(to.getTime() - 24 * 3600 * 1000);
    const result = await exportDiagnosticBundle(apiKey, {
      from: from.toISOString(),
      to: to.toISOString(),
    });
    if (result.ok) {
      if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
        const url = URL.createObjectURL(result.blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = result.filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
      }
      setBundleMessage(`Пакет сформирован: ${result.filename}`);
    } else {
      setBundleMessage(accessErrorText(result.status));
    }
    setBundleBusy(false);
  }, [apiKey]);

  const handleCreateGrant = useCallback(async () => {
    if (!apiKey) return;
    setGrantMessage(null);
    const result = await createGrant(apiKey, {
      ticket: grantTicket,
      purpose: grantPurpose,
      subject_id: grantSubject,
      tenant_id: grantTenant,
      run_id: grantRun || null,
      scopes: grantScopes,
      ttl_hours: grantTtl,
    });
    if (result.ok) {
      setGrantMessage("Грант выдан.");
      setGrantTicket("");
      setGrantPurpose("");
      setGrantSubject("");
      setGrantRun("");
      void refreshGrants(apiKey);
    } else {
      setGrantMessage(grantErrorText(result.status));
    }
  }, [apiKey, grantTicket, grantPurpose, grantSubject, grantTenant, grantRun, grantScopes, grantTtl, refreshGrants]);

  const handleRevoke = useCallback(
    async (grantId: string) => {
      if (!apiKey) return;
      setGrantMessage(null);
      const result = await revokeGrant(apiKey, grantId, revokeReason);
      if (result.ok) {
        setGrantMessage("Грант отозван.");
        setRevokeReason("");
        void refreshGrants(apiKey);
      } else {
        setGrantMessage(grantErrorText(result.status));
      }
    },
    [apiKey, revokeReason, refreshGrants],
  );

  // ── Гейт: ввод ключа ──────────────────────────────────────────────
  if (!apiKey || !access) {
    return (
      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-700 dark:bg-neutral-900">
        <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">
          Администрирование → Журналы
        </h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          Журналы и поддержка (DOCLOG-7, §14.2): технические события, аудит
          доступа, доставка и документы. Ключ живёт только в стейте вкладки
          и не сохраняется.
        </p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
          <Field label="API-ключ администратора">
            <input
              type="password"
              className={inputClass}
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              autoComplete="off"
            />
          </Field>
          <button
            type="button"
            onClick={handleOpen}
            className="rounded bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900"
          >
            Открыть журналы
          </button>
        </div>
        {openError && (
          <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
            {openError}
          </p>
        )}
      </div>
    );
  }

  const activePage =
    tab === "telemetry" ? telemetryPage : tab === "audit" ? auditPage : deliveryPage;

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">
          Администрирование → Журналы
        </h2>
        <p className="text-xs text-neutral-500 dark:text-neutral-400">
          Субъект: <span className="font-mono">{access.principal.subject_id ?? "—"}</span> · роль:{" "}
          {access.principal.role ?? "—"} · область: {scopeText(access.access.scope)}
        </p>
      </header>

      {/* Вкладки §14.2 */}
      <div role="tablist" aria-label="Потоки журналов" className="flex flex-wrap gap-2">
        {TABS.map((item) => (
          <button
            key={item.key}
            role="tab"
            type="button"
            aria-selected={tab === item.key}
            onClick={() => setTab(item.key)}
            className={
              tab === item.key
                ? "rounded-t border-x border-t border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-900 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100"
                : "rounded-t border border-neutral-200 px-3 py-1.5 text-sm text-neutral-600 hover:text-neutral-900 dark:border-neutral-700 dark:text-neutral-400"
            }
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* Whitelist-фильтры (§14.2: БЕЗ произвольного SQL/regex) */}
      <Section title="Фильтры (whitelist, без произвольных выражений)">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Request ID">
            <input
              aria-label="Request ID"
              className={inputClass}
              value={filters.request_id}
              onChange={(e) => setFilters({ ...filters, request_id: e.target.value })}
            />
          </Field>
          <Field label="Run ID">
            <input
              aria-label="Run ID"
              className={inputClass}
              value={filters.run_id}
              onChange={(e) => setFilters({ ...filters, run_id: e.target.value })}
            />
          </Field>
          <Field label="Tenant ID">
            <input
              aria-label="Tenant ID"
              className={inputClass}
              value={filters.tenant_id}
              onChange={(e) => setFilters({ ...filters, tenant_id: e.target.value })}
            />
          </Field>
          {tab === "telemetry" && (
            <>
              <Field label="Severity">
                <select
                  aria-label="Severity"
                  className={inputClass}
                  value={filters.severity}
                  onChange={(e) => setFilters({ ...filters, severity: e.target.value })}
                >
                  <option value="">любой</option>
                  {SEVERITY_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </Field>
              <Field label="Outcome">
                <select
                  aria-label="Outcome"
                  className={inputClass}
                  value={filters.outcome}
                  onChange={(e) => setFilters({ ...filters, outcome: e.target.value })}
                >
                  <option value="">любой</option>
                  {OUTCOME_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </Field>
            </>
          )}
          {tab === "audit" && (
            <>
              <Field label="Действие (action)">
                <input
                  aria-label="Действие (action)"
                  className={inputClass}
                  value={filters.action}
                  onChange={(e) => setFilters({ ...filters, action: e.target.value })}
                />
              </Field>
              <Field label="Решение (decision)">
                <select
                  aria-label="Решение (decision)"
                  className={inputClass}
                  value={filters.decision}
                  onChange={(e) => setFilters({ ...filters, decision: e.target.value })}
                >
                  <option value="">любое</option>
                  {DECISION_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </Field>
            </>
          )}
          {tab === "delivery" && (
            <>
              <Field label="Состояние job">
                <select
                  aria-label="Состояние job"
                  className={inputClass}
                  value={filters.state}
                  onChange={(e) => setFilters({ ...filters, state: e.target.value })}
                >
                  <option value="">любое</option>
                  {JOB_STATE_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </Field>
              <Field label="Формат">
                <input
                  aria-label="Формат"
                  className={inputClass}
                  value={filters.format}
                  onChange={(e) => setFilters({ ...filters, format: e.target.value })}
                />
              </Field>
            </>
          )}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {/* H29-UIH (2026-10-27): пресет «Причины отказов доступа» --
              разбор инцидента по фактической причине (reason_code по run)
              в один клик: фиксированные whitelist-значения (§14.2: без
              произвольного SQL/regex от браузера), затем перечитывание. */}
          {tab === "audit" && (
            <button
              type="button"
              onClick={() => {
                const preset: FilterState = {
                  ...EMPTY_FILTERS,
                  action: "run_access_denied",
                  decision: "denied",
                };
                setFilters(preset);
                if (apiKey) void loadStream("audit", apiKey, undefined, false, preset);
              }}
              className="rounded border border-brand px-3 py-1.5 text-sm text-brand hover:bg-brand-light/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:text-brand-bright"
            >
              Причины отказов доступа
            </button>
          )}
          <button
            type="button"
            onClick={() => apiKey && void loadStream(tab, apiKey)}
            className="rounded border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-50 dark:border-neutral-600 dark:hover:bg-neutral-800"
          >
            Обновить
          </button>
          <label className="flex items-center gap-2 text-sm text-neutral-700 dark:text-neutral-300">
            <input
              type="checkbox"
              checked={liveTail}
              onChange={(e) => {
                setLiveTail(e.target.checked);
                if (e.target.checked) setSkippedTicks(0);
              }}
            />
            Live tail
          </label>
          {!liveTail && (
            <span className="text-xs text-amber-700 dark:text-amber-400">
              Пауза: пропущено обновлений: {skippedTicks}
            </span>
          )}
          {loading && <span className="text-xs text-neutral-500">Загрузка…</span>}
        </div>
      </Section>

      {streamError && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {streamError}
        </p>
      )}

      {/* Строки журнала §14.2 */}
      <Section title={TABS.find((t) => t.key === tab)?.label ?? ""}>
        {activePage === null ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">Загрузка…</p>
        ) : activePage.records.length === 0 ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            Пока нет записей в выбранном окне/фильтрах.
          </p>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-neutral-500 dark:text-neutral-400">
                <tr>
                  <th className="py-1 pr-2">Время (UTC)</th>
                  <th className="py-1 pr-2">{tab === "telemetry" ? "Severity/событие" : tab === "audit" ? "Действие" : "Job/состояние"}</th>
                  <th className="py-1 pr-2">Outcome</th>
                  <th className="py-1 pr-2">Ошибка</th>
                  <th className="py-1 pr-2">Correlation</th>
                </tr>
              </thead>
              <tbody>
                {tab === "telemetry" &&
                  telemetryPage?.records.map((record) => (
                    <LogRow
                      key={record.event_id}
                      time={formatUtc(record.occurred_at)}
                      main={record.event_name}
                      message={`${record.severity_text}${record.message_template ? ` · ${record.message_template}` : ""}`}
                      outcome={record.outcome ?? "—"}
                      error={record.error_code ?? undefined}
                      correlation={record.request_id ?? undefined}
                      detail={record}
                      retry={record.retry_attempt ?? undefined}
                    />
                  ))}
                {tab === "audit" &&
                  auditPage?.records.map((record) => {
                    // H29-UIH (2026-10-27): причина отказа (reason_code из
                    // details, записывает record_run_access_decision) видна
                    // в строке СРАЗУ -- инцидент «у меня запрещён»
                    // разбирается по фактической причине, а не по догадкам
                    // (вскрытие detail -- опционально).
                    const reasonCode =
                      typeof (record.details ?? {})?.reason_code === "string"
                        ? (record.details as { reason_code: string }).reason_code
                        : null;
                    return (
                      <LogRow
                        key={record.audit_id}
                        time={formatUtc(record.occurred_at)}
                        main={record.action}
                        message={`${record.decision}${reasonCode ? ` · причина: ${reasonCode}` : ""}${record.policy_basis ? ` · ${record.policy_basis}` : ""}`}
                        outcome={record.decision}
                        correlation={record.request_id ?? undefined}
                        detail={record}
                      />
                    );
                  })}
                {tab === "delivery" &&
                  deliveryPage?.records.map((record) => (
                    <LogRow
                      key={record.job_id}
                      time={formatUtc(record.created_at)}
                      main={record.job_id}
                      message={`${record.state} · ${record.format}${record.kind_code ? ` · ${record.kind_code}` : ""}`}
                      outcome={record.state}
                      error={record.error_code ?? undefined}
                      correlation={record.run_id}
                      detail={record}
                      retry={record.attempt}
                    />
                  ))}
              </tbody>
            </table>
          </div>
        )}
        {activePage?.next_cursor && (
          <button
            type="button"
            onClick={() => apiKey && void loadStream(tab, apiKey, activePage.next_cursor ?? undefined, true)}
            className="mt-2 rounded border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-50 dark:border-neutral-600 dark:hover:bg-neutral-800"
          >
            Следующая страница
          </button>
        )}
        {activePage?.meta.retention_note && (
          <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{activePage.meta.retention_note}</p>
        )}
      </Section>

      {/* Диагностический пакет (§14.2, AC10/AC19) */}
      <Section title="Диагностический пакет">
        <p className="text-xs text-neutral-600 dark:text-neutral-400">
          Redacted JSONL + manifest за последние 24 часа. Пакет «без данных»:
          не включает источники, строки данных, cookies или env values.
        </p>
        <button
          type="button"
          disabled={bundleBusy || !access.access.export}
          onClick={handleBundle}
          className="mt-2 rounded bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {bundleBusy ? "Формирование…" : "Создать диагностический пакет"}
        </button>
        {!access.access.export && (
          <p className="mt-1 text-xs text-neutral-500">Нет права logs.export.</p>
        )}
        {bundleMessage && <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-300">{bundleMessage}</p>}
      </Section>

      {/* Гранты поддержки (§14.2/§15) */}
      {access.access.grants_management && (
        <Section title="Гранты поддержки">
          <div className="max-h-64 overflow-y-auto">
            {grants === null ? (
              <p className="text-sm text-neutral-500">Загрузка…</p>
            ) : grants.length === 0 ? (
              <p className="text-sm text-neutral-500">Активных грантов нет.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {grants.map((grant) => (
                  <li
                    key={grant.grant_id}
                    className="rounded border border-neutral-200 p-2 text-xs dark:border-neutral-700"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold">{grant.ticket}</span>
                      <button
                        type="button"
                        onClick={() => void handleRevoke(grant.grant_id)}
                        className="rounded border border-red-300 px-2 py-1 text-red-700 hover:bg-red-50 dark:border-red-700 dark:text-red-400"
                      >
                        Отозвать
                      </button>
                    </div>
                    <div className="mt-1 text-neutral-600 dark:text-neutral-400">
                      {grant.subject_id} · {grant.tenant_id}
                      {grant.run_id ? ` · ${grant.run_id}` : ""} · {grant.scopes.join(", ")}
                    </div>
                    <div className="text-neutral-500">
                      до {formatUtc(grant.expires_at)}
                      {grant.revoked_at ? ` · отозван ${formatUtc(grant.revoked_at)}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Ticket">
              <input aria-label="Ticket" className={inputClass} value={grantTicket} onChange={(e) => setGrantTicket(e.target.value)} />
            </Field>
            <Field label="Purpose">
              <input aria-label="Purpose" className={inputClass} value={grantPurpose} onChange={(e) => setGrantPurpose(e.target.value)} />
            </Field>
            <Field label="Subject ID получателя">
              <input aria-label="Subject ID получателя" className={inputClass} value={grantSubject} onChange={(e) => setGrantSubject(e.target.value)} />
            </Field>
            <Field label="Tenant ID">
              <input aria-label="Tenant ID гранта" className={inputClass} value={grantTenant} onChange={(e) => setGrantTenant(e.target.value)} />
            </Field>
            <Field label="Run ID (необязательно)">
              <input aria-label="Run ID гранта" className={inputClass} value={grantRun} onChange={(e) => setGrantRun(e.target.value)} />
            </Field>
            <Field label="TTL (часы, максимум 168)">
              <select
                aria-label="TTL (часы)"
                className={inputClass}
                value={grantTtl}
                onChange={(e) => setGrantTtl(Number(e.target.value))}
              >
                {TTL_OPTIONS.map((h) => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </Field>
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-xs text-neutral-700 dark:text-neutral-300">
            {GRANT_SCOPE_OPTIONS.map((scope) => (
              <label key={scope} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={grantScopes.includes(scope)}
                  onChange={(e) =>
                    setGrantScopes((prev) =>
                      e.target.checked ? [...prev, scope] : prev.filter((s) => s !== scope),
                    )
                  }
                />
                {scope}
              </label>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <Field label="Причина отзыва">
              <input aria-label="Причина отзыва" className={inputClass} value={revokeReason} onChange={(e) => setRevokeReason(e.target.value)} />
            </Field>
            <button
              type="button"
              onClick={() => void handleCreateGrant()}
              className="rounded bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900"
            >
              Выдать грант
            </button>
          </div>
          {grantMessage && <p className="mt-2 text-sm text-neutral-700 dark:text-neutral-300">{grantMessage}</p>}
        </Section>
      )}
    </div>
  );
}

function LogRow({
  time,
  main,
  message,
  outcome,
  error,
  correlation,
  detail,
  retry,
}: {
  time: string;
  main: string;
  message?: string;
  outcome: string;
  error?: string;
  correlation?: string;
  detail: Record<string, unknown>;
  retry?: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className="border-t border-neutral-100 dark:border-neutral-800">
        <td className="py-1 pr-2 font-mono text-neutral-600 dark:text-neutral-400">{time}</td>
        <td className="py-1 pr-2 text-neutral-900 dark:text-neutral-100">
          {main}
          {message ? <span className="block text-neutral-500 dark:text-neutral-400">{message}</span> : null}
        </td>
        <td className="py-1 pr-2">{outcome}</td>
        <td className="py-1 pr-2">{error ?? "—"}</td>
        <td className="py-1 pr-2 font-mono">
          {correlation ?? "—"}
          {retry !== undefined && retry > 0 ? ` · повтор ${retry}` : ""}
        </td>
      </tr>
      <tr className="border-t border-neutral-100 dark:border-neutral-800">
        <td colSpan={5} className="py-1">
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="text-xs text-neutral-500 underline hover:text-neutral-800 dark:hover:text-neutral-200"
          >
            {open ? "Скрыть деталь" : "Деталь записи"}
          </button>
          {open && (
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-neutral-50 p-2 text-[11px] text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
              {JSON.stringify(detail, null, 2)}
            </pre>
          )}
        </td>
      </tr>
    </>
  );
}

type AnyLogsPage =
  | LogsPage<TelemetryLogRecord>
  | LogsPage<AuditLogRecord>
  | LogsPage<DeliveryLogRecord>;

function mergePage(prev: AnyLogsPage | null, next: AnyLogsPage): AnyLogsPage {
  if (!prev) return next;
  return {
    records: [...prev.records, ...next.records],
    next_cursor: next.next_cursor,
    meta: next.meta,
  } as AnyLogsPage;
}

function accessErrorText(status: number): string {
  if (status === 401) return "Неверный API-ключ. Введите действующий ключ администратора.";
  if (status === 403) return "Недостаточно прав: журналы доступны ADMIN-роли и грантам поддержки (§15).";
  if (status === 0) return "Сервис недоступен (сеть/offline). Повторите позже.";
  return `Ошибка ${status}: повторите позже или обратитесь к администратору.`;
}

function streamErrorText(status: number): string {
  if (status === 401) return accessErrorText(401);
  if (status === 403) return "Недостаточно прав на этот поток (scope/grant, §15).";
  if (status === 422) return "Фильтры вне whitelist или окно больше допустимого (§14.2).";
  if (status === 503) return "Durable-слой журналов недоступен (503). Повторите позже.";
  if (status === 0) return "Сервис недоступен (сеть/offline).";
  return `Ошибка ${status}.`;
}

function grantErrorText(status: number): string {
  if (status === 403) return "Нет права support.grant (§15).";
  if (status === 404) return "Грант не найден.";
  if (status === 422) return "Некорректный грант: ticket/subject/tenant/TTL/scopes (whitelist).";
  if (status === 503) return "Обязательный audit недоступен -- действие отклонено (AC11).";
  if (status === 0) return "Сервис недоступен (сеть/offline).";
  return `Ошибка ${status}.`;
}
