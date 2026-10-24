// packages/ui/lib/monitoring.ts
//
// DOCLOG-8 (спека §6 D12, §12.2/§12.3, AC15/AC17): клиент API контура
// мониторинга /v1/documentation/runs/{run_id}/monitoring/* -- списки
// frozen сверок (actual-vs-forecast) и деталя сверок. Паритет
// lib/documentation.ts: дискриминированные результаты
// { ok: true, data } | { ok: false, status } -- UI честно рендерит
// негативные состояния (forbidden/offline/409), не бросая исключения в
// слой компонентов; credentials: include (cookie-сессия -- субъект-
// суррогат DOCLOG-0); данные сверок -- frozen result сервера (§19:
// пересмотр факта не переписывает старую сверку).

import { documentationApiUrl } from "./documentation";

// ── Типы контракта (apps/api/routers/monitoring.py) ─────────────────

export interface MonitoringAlignment {
  key: string;
  matured_count: number;
  excluded_count: number;
  excluded_labels: string[];
  out_of_horizon_count: number;
  out_of_horizon_labels: string[];
}

export interface MonitoringPair {
  step: number | null;
  date: string;
  forecast_value: number;
  actual_value: number;
  signed_error: number;
  absolute_error: number;
  /** AC12: фактический ноль -- ape неопределена: null + reason. */
  ape: number | null;
  ape_undefined_reason: string | null;
  interval_hit: boolean | null;
}

export interface MonitoringAggregates {
  mae: number | null;
  mae_reason: string | null;
  mean_signed_error: number | null;
  mean_signed_error_reason: string | null;
  mape: number | null;
  mape_reason: string | null;
  mape_zero_periods: string[];
  mase: number | null;
  mase_reason: string | null;
  interval_hits: number;
  interval_coverage: number | null;
  interval_coverage_reason: string | null;
}

export interface MonitoringThreshold {
  metric: string;
  operator: string;
  value: number;
  label: string;
  status: "exceeded" | "within" | "not_evaluable";
  reason: string | null;
}

export interface MonitoringResult {
  schema_version: string;
  forecast_origin: {
    horizon: number | null;
    alpha: number | null;
    point_count: number;
  };
  alignment: MonitoringAlignment;
  pairs: MonitoringPair[];
  aggregates: MonitoringAggregates;
  threshold: MonitoringThreshold | null;
  /** §6.1: решение -- отдельная запись человека, всегда null. */
  decision_action: null;
}

export interface ComparisonSummary {
  comparison_id: string;
  run_id: string;
  forecast_artifact_id: string;
  forecast_sha256: string;
  actual_batch_id: string;
  target_name: string;
  entity_id: string | null;
  units_check: "as_is" | "converted" | "unknown";
  units_note: string;
  status: string;
  matured_count: number;
  excluded_count: number;
  out_of_horizon_count: number;
  created_at: string;
}

export interface ComparisonDetail extends ComparisonSummary {
  result: MonitoringResult;
}

export type ComparisonListResult =
  | { ok: true; status: number; data: { items: ComparisonSummary[]; total: number } }
  | { ok: false; status: number };

export type ComparisonDetailResult =
  | { ok: true; status: number; data: ComparisonDetail }
  | { ok: false; status: number };

// ── Клиенты (один fetch -- один дискриминированный результат) ────────

type OkResult<T> = { ok: true; status: number; data: T };
type ErrResult = { ok: false; status: number };

async function parseResult<T>(response: Response): Promise<OkResult<T> | ErrResult> {
  if (!response.ok) {
    const err: ErrResult = { ok: false, status: response.status };
    return err;
  }
  try {
    const data = (await response.json()) as T;
    const ok: OkResult<T> = { ok: true, status: response.status, data };
    return ok;
  } catch {
    const err: ErrResult = { ok: false, status: response.status };
    return err;
  }
}

/** GET /runs/{run_id}/monitoring/comparisons -- frozen сверки run. */
export async function listRunComparisons(
  runId: string,
): Promise<ComparisonListResult> {
  try {
    const response = await fetch(
      documentationApiUrl(`/runs/${encodeURIComponent(runId)}/monitoring/comparisons`),
      { credentials: "include" },
    );
    return await parseResult(response);
  } catch {
    return { ok: false, status: 0 };
  }
}

/** GET /runs/{run_id}/monitoring/comparisons/{id} -- frozen результат. */
export async function getComparison(
  runId: string,
  comparisonId: string,
): Promise<ComparisonDetailResult> {
  try {
    const response = await fetch(
      documentationApiUrl(
        `/runs/${encodeURIComponent(runId)}/monitoring/comparisons/${encodeURIComponent(comparisonId)}`,
      ),
      { credentials: "include" },
    );
    return await parseResult(response);
  } catch {
    return { ok: false, status: 0 };
  }
}
