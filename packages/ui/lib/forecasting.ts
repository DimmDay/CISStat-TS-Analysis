// packages/ui/lib/forecasting.ts
//
// Типы и API-хелперы этапа «Прогнозирование» (spec_forecasting2.md §6-§7).
// Контракты зеркалят apps/api/schemas.py::ForecastRunResponse и роуты
// /v1/session/modeling/forecast* 1:1 -- расхождение ловит typecheck.

import { getApiBase } from "./apiClient";

export type CiMethod =
  | "analytic"
  | "parametric_simulation"
  | "native_adapter"
  | "empirical_oof_quantile";

export type AlphaSource =
  | "requested"
  | "card_default"
  | "platform_default"
  | "adapter_fixed";

export interface ForecastPoint {
  step: number;
  date: string;
  value: number;
  ci_lower: number;
  ci_upper: number;
  is_anomalous: boolean;
}

export interface ForecastTraceEvent {
  event_type: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface ForecastRun {
  forecast_id: string;
  model_card_id: string;
  model_id: string;
  model_name: string;
  generated_at: string;
  horizon: number;
  alpha: number;
  alpha_effective: number;
  alpha_source: AlphaSource;
  ci_method: CiMethod;
  points: ForecastPoint[];
  history: {
    labels: string[];
    values: number[];
    source_column?: string;
  };
  expected_accuracy: Record<string, number | null>;
  prediction_interval_coverage: number | null;
  warnings: string[];
  trace_events: ForecastTraceEvent[];
  lineage: Record<string, unknown>;
  sensitivity: {
    computed_at: string;
    varied_axes: string[];
    combos: Array<{ params: Record<string, unknown>; points: Array<{ step: number; date: string; value: number }> }>;
    truncated?: boolean;
    warnings?: string[];
  } | null;
}

export interface CardSummary {
  card_id: string;
  model_id: string | null;
  model_name: string | null;
  selection_kind: string;
  horizon: number | null;
  fingerprint: string | null;
  created_at: string | null;
}

// Человекочитаемые подписи методов интервалов (прецедент FREQUENCY_LABELS).
export const CI_METHOD_LABELS: Record<CiMethod, string> = {
  analytic: "Аналитический (statsmodels)",
  parametric_simulation: "Параметрическая симуляция (Monte-Carlo)",
  native_adapter: "Нативные интервалы адаптера",
  empirical_oof_quantile: "Эмпирический (OOF-остатки бэктеста)",
};

export const ALPHA_SOURCE_LABELS: Record<AlphaSource, string> = {
  requested: "запрошенная",
  card_default: "из карты",
  platform_default: "по умолчанию (0.05)",
  adapter_fixed: "фиксированная адаптером",
};

function base(): string {
  return `${getApiBase()}/v1/session/modeling`;
}

async function parse<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail: unknown = null;
    try {
      detail = (await resp.json()).detail;
    } catch {
      detail = null;
    }
    const message =
      typeof detail === "string" ? detail : `HTTP ${resp.status}`;
    throw new Error(message);
  }
  return (await resp.json()) as T;
}

export async function fetchCardSummaries(): Promise<CardSummary[]> {
  const resp = await fetch(`${base()}/card`, { credentials: "include" });
  const body = await parse<{ cards: CardSummary[] }>(resp);
  return body.cards;
}

export async function fetchForecastHistory(): Promise<ForecastRun[]> {
  const resp = await fetch(`${base()}/forecast`, { credentials: "include" });
  const body = await parse<{ forecasts: ForecastRun[] }>(resp);
  return body.forecasts;
}

export async function generateForecast(payload: {
  model_card_id: string;
  horizon?: number | null;
  alpha?: number | null;
}): Promise<ForecastRun> {
  const resp = await fetch(`${base()}/forecast`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parse<ForecastRun>(resp);
}

export async function compareForecasts(forecastIds: string[]): Promise<ForecastRun[]> {
  const resp = await fetch(`${base()}/forecast/compare`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ forecast_ids: forecastIds }),
  });
  const body = await parse<{ forecasts: ForecastRun[] }>(resp);
  return body.forecasts;
}

export async function computeSensitivity(forecastId: string): Promise<ForecastRun> {
  const resp = await fetch(`${base()}/forecast/${forecastId}/sensitivity`, {
    method: "POST",
    credentials: "include",
  });
  return parse<ForecastRun>(resp);
}

export async function recordClientExport(forecastId: string, format: "png" | "pdf"): Promise<ForecastRun> {
  const resp = await fetch(`${base()}/forecast/${forecastId}/trace`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type: "forecast_exported", format }),
  });
  return parse<ForecastRun>(resp);
}

export function exportUrl(forecastId: string, format: "csv" | "json"): string {
  return `${base()}/forecast/${forecastId}/export.${format}`;
}
