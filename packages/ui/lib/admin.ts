// packages/ui/lib/admin.ts
//
// Клиентский слой Admin-панели мониторинга «Прогресса» (Task PROGR-8,
// spec_progress.md §10 + §9). Бэкенд:
//
//   GET /v1/progress/admin/overview?days=&top=
//        -- агрегаты §10 по корпусу (запуски по статусам за период,
//           время по стадиям, топ warning/error-узлов, частоты правил
//           §7.1, частоты sanity §7.2 по правилу/узлу, предпочтения
//           Прогнозирования §9);
//   GET /v1/progress/admin/case-bank/candidates
//        -- отбор кандидатов банка кейсов (§9, алгоритмическая
//           эвристика; суммаризация трассы -- офлайн-джоба вне сервиса).
//
// §10 дословно: «admin-эндпоинты должны требовать API-ключ с ролью
// ADMIN, а не cookie -- админ заходит другим путём, чем обычный
// аналитик». Здесь -- заголовок X-API-Key (ключ вводится в панели,
// живёт только в стейте компонента); credentials НЕ включаются --
// cookie-сессия аналитика к админ-эндпоинтам отношения не имеет.
//
// Результат различает 401 (неверный ключ) и 403 (не ADMIN) -- панель
// показывает разные подсказки; прочие сбои -- тот же канал честной
// недоступности (best-effort, паттерн mentor.ts).

import { progressApiUrl } from "./apiClient";

// ── Контракты ответов (зеркало pydantic-схем progress.py) ───────────

export interface StageSpanStatInfo {
  stage: string;
  runs_with_stage: number;
  mean_minutes: number;
  median_minutes: number;
}

export interface NodeProblemInfo {
  stage: string;
  node_id: string;
  status: string;
  count: number;
}

export interface RuleFrequencyInfo {
  rule_id: string;
  stage: string;
  count: number;
}

export interface SanityNodeFrequencyInfo {
  stage: string;
  node_id: string;
  count: number;
}

export interface ValueFrequencyInfo {
  value: string;
  count: number;
}

export interface AdminOverviewInfo {
  generated_at: string;
  period_days: number;
  runs_total_all_time: number;
  runs_total_in_period: number;
  runs_by_status: Record<string, number>;
  stage_time: StageSpanStatInfo[];
  top_problem_nodes: NodeProblemInfo[];
  next_step_frequency: RuleFrequencyInfo[];
  sanity_by_rule: RuleFrequencyInfo[];
  sanity_by_node: SanityNodeFrequencyInfo[];
  forecasting_model_frequency: ValueFrequencyInfo[];
  forecasting_horizon_frequency: ValueFrequencyInfo[];
  forecasting_alpha_frequency: ValueFrequencyInfo[];
}

export interface CaseBankCandidateInfo {
  run_id: string;
  status: string;
  dataset_name: string;
  created_at: string;
  backtest_mape: number;
  warning_nodes: number;
  sanity_warnings: number;
}

export interface CaseBankResponseInfo {
  candidates: CaseBankCandidateInfo[];
  total_completed: number;
  criteria: Record<string, number>;
}

// ── Результат: различимая недоступность (401/403/прочее) ────────────

// ПЛОСКАЯ форма (не дискриминированное объединение): jest.tsconfig
// собирает тесты с strict=false (strictNullChecks off) -- TS 6 не
// сужает такие объединения по булеву дискриминанту (подтверждено
// редPROGR-8). ok=false → status осмыслен (401/403/0-сеть/503...);
// ok=true → data заполнен, status 200.
export interface AdminResult<T> {
  ok: boolean;
  status: number;
  data: T | null;
}

export interface AdminOverviewParams {
  days?: number;
  top?: number;
}

export interface CaseBankParams {
  maxBacktestMape?: number;
  maxWarningNodes?: number;
  maxSanityWarnings?: number;
}

function adminFetch<T>(url: string, apiKey: string): Promise<AdminResult<T>> {
  return fetch(url, { headers: { "X-API-Key": apiKey } })
    .then(async (response) => {
      if (!response.ok) {
        return { ok: false, status: response.status, data: null };
      }
      const data = (await response.json()) as T;
      return { ok: true, status: response.status, data };
    })
    .catch(() => ({ ok: false, status: 0, data: null }));
}

export function fetchAdminOverview(
  apiKey: string,
  params: AdminOverviewParams = {},
): Promise<AdminResult<AdminOverviewInfo>> {
  const query = new URLSearchParams();
  query.set("days", String(params.days ?? 30));
  query.set("top", String(params.top ?? 10));
  return adminFetch<AdminOverviewInfo>(
    progressApiUrl(`/admin/overview?${query.toString()}`),
    apiKey,
  );
}

export function fetchCaseBankCandidates(
  apiKey: string,
  params: CaseBankParams = {},
): Promise<AdminResult<CaseBankResponseInfo>> {
  const query = new URLSearchParams();
  if (params.maxBacktestMape !== undefined) {
    query.set("max_backtest_mape", String(params.maxBacktestMape));
  }
  if (params.maxWarningNodes !== undefined) {
    query.set("max_warning_nodes", String(params.maxWarningNodes));
  }
  if (params.maxSanityWarnings !== undefined) {
    query.set("max_sanity_warnings", String(params.maxSanityWarnings));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return adminFetch<CaseBankResponseInfo>(
    progressApiUrl(`/admin/case-bank/candidates${suffix}`),
    apiKey,
  );
}
