// packages/ui/lib/modeling.ts
//
// TypeScript-зеркало схем из apps/api/schemas.py (DataProfileRequest,
// ModelCandidate, CandidatesRequest, CandidatesResponse, CandidatesStatistics).
//
// Поддерживайте это в синхронизации с apps/api/schemas.py вручную, либо
// (лучше) сгенерируйте оба файла из единой OpenAPI-схемы FastAPI.

// ── Профиль данных ──────────────────────────────────────────────

export interface DataProfile {
  n_observations: number;
  n_series: number;
  n_exogenous: number;
  is_regular: boolean;
  frequency: string;
  has_seasonality: boolean;
  seasonal_periods: number[];
  is_stationary_or_diffable: boolean;
  is_cointegrated: boolean;
  has_negative_values: boolean;
  has_volatility_clustering: boolean;
  domain: string;
  missing_ratio: number;
  outlier_ratio: number;
  has_holidays: boolean;
  gpu_available: boolean;
  feature_engineering_applied: boolean;
}

// ── Уровни применимости ─────────────────────────────────────────

export type ApplicabilityLevel =
  | "RECOMMENDED"
  | "CONDITIONALLY_APPLICABLE"
  | "NOT_RECOMMENDED"
  | "NOT_APPLICABLE";

export const APPLICABILITY_RANK: Record<ApplicabilityLevel, number> = {
  RECOMMENDED: 1,
  CONDITIONALLY_APPLICABLE: 2,
  NOT_RECOMMENDED: 3,
  NOT_APPLICABLE: 4,
};

export const APPLICABILITY_LABEL: Record<ApplicabilityLevel, string> = {
  RECOMMENDED: "Рекомендована",
  CONDITIONALLY_APPLICABLE: "Условно применима",
  NOT_RECOMMENDED: "Не рекомендуется",
  NOT_APPLICABLE: "Неприменима",
};

// Цвета для бейджей (Tailwind-классы)
export const APPLICABILITY_BADGE: Record<
  ApplicabilityLevel,
  { bg: string; text: string; border: string }
> = {
  RECOMMENDED: {
    bg: "bg-green-50",
    text: "text-green-700",
    border: "border-green-200",
  },
  CONDITIONALLY_APPLICABLE: {
    bg: "bg-amber-50",
    text: "text-amber-700",
    border: "border-amber-200",
  },
  NOT_RECOMMENDED: {
    bg: "bg-red-50",
    text: "text-red-700",
    border: "border-red-200",
  },
  NOT_APPLICABLE: {
    bg: "bg-neutral-100",
    text: "text-neutral-500",
    border: "border-neutral-200",
  },
};

// ── Кандидат моделирования ──────────────────────────────────────

export interface ModelCandidate {
  model_id: string;
  model_name: string;
  family_id: string;
  level: ApplicabilityLevel;
  rule_id: string | null;
  message: string;
  rank: number;
}

// ── Запрос / Ответ ──────────────────────────────────────────────

export interface CandidatesRequest {
  profile: DataProfile;
  min_level?: string;
}

export interface CandidatesStatistics {
  total_candidates: number;
  by_level: Record<string, number>;
  total_models_in_spec: number;
}

export interface CandidatesResponse {
  candidates: ModelCandidate[];
  statistics: CandidatesStatistics;
  spec_version: string;
}

// ── Семейства моделей (для UI-группировки) ─────────────────────

export interface ModelFamily {
  id: string;
  name: string;
}

export const MODEL_FAMILIES: ModelFamily[] = [
  { id: "baselines", name: "Базовые модели" },
  { id: "exponential_smoothing", name: "Эксп. сглаживание" },
  { id: "arima", name: "ARIMA" },
  { id: "multivariate", name: "Многомерные" },
  { id: "volatility", name: "Волатильность" },
  { id: "structural", name: "Структурные" },
  { id: "tree_ml", name: "Деревья и бустинг" },
  { id: "neural", name: "Нейросетевые" },
];

// ── Предметные области ──────────────────────────────────────────

export const DOMAINS = [
  { value: "financial", label: "Финансовая" },
  { value: "macro", label: "Макроэкономика" },
  { value: "price", label: "Цены" },
  { value: "other", label: "Другое" },
] as const;

export const FREQUENCIES = [
  { value: "D", label: "Дневная" },
  { value: "W", label: "Недельная" },
  { value: "M", label: "Месячная" },
  { value: "Q", label: "Квартальная" },
  { value: "Y", label: "Годовая" },
] as const;

// ── Стадии пайплайна моделирования ─────────────────────────────

export interface PipelineStage {
  id: string;
  label: string;
  status: "done" | "active" | "pending";
}

export const PIPELINE_STAGES: PipelineStage[] = [
  { id: "problem_definition", label: "Определение задачи", status: "done" },
  { id: "data_structure", label: "Структура данных", status: "done" },
  { id: "constraint_mapping", label: "Ограничения", status: "done" },
  { id: "candidate_generation", label: "Пул кандидатов", status: "active" },
  { id: "baseline_estimation", label: "Baseline", status: "pending" },
  { id: "backtest", label: "Бэктест", status: "pending" },
  { id: "tuning", label: "Тюнинг", status: "pending" },
  { id: "diagnostics", label: "Диагностика", status: "pending" },
  { id: "comparison", label: "Сравнение", status: "pending" },
  { id: "selection", label: "Выбор модели", status: "pending" },
  { id: "model_card", label: "Model Card", status: "pending" },
];

// ── Бэктест ────────────────────────────────────────────────────

export interface BacktestRequest {
  model_id: string;
  profile: DataProfile;
  train_ratio?: number; // default 0.8, range [0.5, 0.95]
}

export interface BacktestMetrics {
  mae: number;
  rmse: number;
  mape: number; // в процентах
  mase: number;
  weighted_score: number; // 0–1, ниже = лучше
}

export interface BacktestResponse {
  model_id: string;
  model_name: string;
  family_id: string;
  metrics: BacktestMetrics;
  n_train: number;
  n_test: number;
  train_ratio: number;
  duration_ms: number;
  /**
   * Phase 0.5: источник ряда для бэктеста.
   * "session" — реальный ряд из session.dataframe[target_column].
   * "synthetic" — fallback на синтетический ряд из профиля.
   * Опционально для backward-compat со старым /v1/models/backtest (без bridge).
   */
  data_source?: "session" | "synthetic";
}

export type TraceabilityStatus = "done" | "warning" | "skipped" | "pending";

export interface ModelingTraceNode {
  group: "validation" | "preprocessing" | "eda";
  source_id: string;
  label: string;
  source_endpoint: string;
  modeling_inputs: string[];
  modeling_stages: string[];
  status: TraceabilityStatus;
  evidence: string;
  blocking: boolean;
}

export interface ModelingContext {
  ready: boolean;
  data_source: "session";
  fingerprint: string;
  checkpoint: {
    checkpoint_id: string;
    snapshot_id: string;
    stage: "modeling_entry";
    source_stage: string;
    confirmed_at: string;
  };
  profile: DataProfile;
  passport: Record<string, unknown>;
  validation_strategy: Record<string, unknown> & {
    horizon: number;
    n_splits: number;
  };
  model_matrix: Record<string, unknown>;
  runnable_shortlist: string[];
  traceability: {
    nodes: ModelingTraceNode[];
    summary: Record<TraceabilityStatus | "total" | "blocking", number>;
  };
}

// ── target_column (Phase 0.5 мост Upload → Backtest) ───────────
//
// Серверная схема: apps/api/schemas.py → TargetColumnRequest / TargetColumnResponse.
// Эндпоинты: GET/POST /v1/session/target-column (без auth, cookie-based).

export interface TargetColumnRequest {
  column: string;
}

export interface TargetColumnResponse {
  target_column: string | null;
  suggested_column: string | null;
  available_columns: string[];
  has_dataset: boolean;
  passport_history_reset?: boolean;
}

// Веса ранжирования (из modeling.yaml)
export const BACKTEST_WEIGHTS = {
  mae: 0.35,
  rmse: 0.25,
  mape: 0.20,
  mase: 0.20,
} as const;

// ── Дефолтный профиль данных ───────────────────────────────────

export const DEFAULT_PROFILE: DataProfile = {
  n_observations: 120,
  n_series: 1,
  n_exogenous: 0,
  is_regular: true,
  frequency: "M",
  has_seasonality: true,
  seasonal_periods: [12],
  is_stationary_or_diffable: true,
  is_cointegrated: false,
  has_negative_values: false,
  has_volatility_clustering: false,
  domain: "macro",
  missing_ratio: 0.0,
  outlier_ratio: 0.0,
  has_holidays: false,
  gpu_available: false,
  feature_engineering_applied: false,
};
