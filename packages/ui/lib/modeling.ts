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
  platform_status: "ready" | "catalog_only";
  available_actions: Array<"backtest" | "tune" | "diagnostics">;
  blocking_reason: string | null;
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
  runnable_candidates: number;
  catalog_only_candidates: number;
  blocked_candidates: number;
}

export interface CandidatesResponse {
  candidates: ModelCandidate[];
  catalog: ModelCandidate[];
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
  mape: number | null; // в процентах; null при отсутствии ненулевых фактов
  mase: number | null;
  smape?: number | null;
  rmsse?: number | null;
  mape_valid_points?: number;
  weighted_score: number | null; // вычисляется только внутри общего comparison cohort
}

export interface BacktestPredictionPoint {
  fold: number;
  horizon_step: number;
  index: number;
  label: string | null;
  actual: number;
  predicted: number;
  residual: number;
}

export interface BacktestFoldResult {
  fold: number;
  status: "success" | "failed";
  train_start: number;
  train_end: number;
  test_start: number;
  test_end: number;
  gap: number;
  n_train: number;
  n_test: number;
  train_start_label?: string | null;
  train_end_label?: string | null;
  test_start_label?: string | null;
  test_end_label?: string | null;
  metrics: BacktestMetrics | null;
  predictions: BacktestPredictionPoint[];
  duration_ms: number;
  error?: string | null;
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
  status?: "success" | "partial";
  strategy?: "single" | "expanding" | "sliding";
  cohort_id?: string | null;
  horizon?: number;
  n_folds?: number;
  gap?: number;
  folds?: BacktestFoldResult[];
  oof_predictions?: BacktestPredictionPoint[];
  warnings?: string[];
  preprocessing?: {
    fit_policy: "none" | "per_train_fold";
    source_column: string;
    target_column: string;
    evaluation_scale: string;
    transformations?: string[];
    target_scaling?: string | null;
    inverse_transform_applied?: boolean;
  };
  run_id?: string | null;
  params?: Record<string, unknown>;
  params_source?: "model_default" | "tuning" | "request";
  parameter_signature?: string | null;
  tuning_id?: string | null;
  oof_signature?: string | null;
}

export interface TuningFoldPlan {
  fold: number;
  train_start: number;
  train_end: number;
  test_start: number;
  test_end: number;
  gap: number;
}

export interface SessionTuningResponse {
  model_id: string;
  best_params: Record<string, unknown>;
  best_metrics: BacktestMetrics;
  strategy: "single" | "expanding" | "sliding";
  cohort_id: string;
  folds: TuningFoldPlan[];
  preprocessing: NonNullable<BacktestResponse["preprocessing"]>;
  warnings: string[];
  tuning_id?: string | null;
  parameter_signature?: string | null;
  promoted_backtest?: BacktestResponse | null;
}

export interface ComparisonDiagnosticsSummary {
  overall_status: "pass" | "warning" | "fail";
  passed: string[];
  warnings: string[];
  failed: string[];
  not_applicable: string[];
  diagnostics_signature: string;
}

export interface ComparisonFoldStability {
  metric: "rmse";
  fold_values: number[];
  mean: number;
  std: number;
  coefficient_of_variation: number | null;
  fold_ranks: number[];
  mean_rank: number;
  rank_std: number;
  top1_rate: number;
}

export interface ComparisonRankingItem {
  rank: number;
  model_id: string;
  model_name: string;
  family_id: string;
  applicability_level: ApplicabilityLevel;
  metrics: BacktestMetrics;
  backtest_run_id: string;
  params_source: "model_default" | "tuning" | "request";
  parameter_signature: string;
  tuning_id: string | null;
  oof_signature: string;
  normalized_metrics: Record<string, number>;
  weighted_score: number;
  baseline_eligible: boolean;
  baseline_note: string;
  diagnostics: ComparisonDiagnosticsSummary;
  fold_stability: ComparisonFoldStability;
}

export interface ModelingComparisonResponse {
  comparison_id: string;
  comparison_signature: string;
  fingerprint: string;
  cohort_id: string;
  ranking_policy: "forecast_metrics_only_diagnostics_separate";
  diagnostics_policy: "current_oof_report_required_not_scored";
  normalization: "min_max_within_comparable_pool";
  metric_weights: Record<string, number>;
  ranking: ComparisonRankingItem[];
  error_correlation: {
    model_ids: string[];
    n_points: number;
    values: Array<Array<number | null>>;
    unavailable_pairs: string[];
  };
  warnings: string[];
}

export type EnsembleEvaluationStatus = "not_eligible" | "tested_no_gain" | "recommended";

export interface ModelingSelectionAnalysis {
  selection_analysis_id: string;
  selection_signature: string;
  comparison_id: string;
  comparison_signature: string;
  cohort_id: string;
  policy: {
    version: string;
    primary_metric: "mae" | "rmse";
    max_member_relative_gap: number;
    max_error_correlation: number;
    min_oof_points: number;
    min_ensemble_relative_improvement: number;
    min_fold_win_rate: number;
    practical_tie_relative: number;
  };
  recommended_single: {
    model_id: string;
    primary_metric: "mae" | "rmse";
    primary_loss: number;
    practical_ties: string[];
    relative_improvement_vs_best_baseline: number;
  };
  best_baseline: {
    model_id: string;
    primary_metric: "mae" | "rmse";
    primary_loss: number;
  };
  ensemble: {
    status: EnsembleEvaluationStatus;
    strategy: "simple_average";
    member_ids: string[];
    weights: number[];
    error_correlation: number | null;
    relative_improvement_vs_best_single: number | null;
    relative_improvement_vs_best_baseline: number | null;
    fold_win_rate: number | null;
    backtest: BacktestResponse | null;
    diagnostics: ({ diagnostics_signature: string } & Record<string, unknown>) | null;
    reasons: string[];
  };
  recommended_candidate: {
    kind: "single" | "ensemble";
    model_id: string;
  };
  evaluation_contract: {
    source: "exact_aligned_selection_oof";
    estimate_status: "selection_oof_reused";
    independent_holdout: false;
    requires_acknowledgement: true;
  };
  warnings: string[];
}

export interface ModelingSelectionResult {
  selected_model_id: string;
  selected_kind: "single" | "ensemble";
  selection_analysis_id: string;
  selection_signature: string;
  primary_metric: "mae" | "rmse";
  primary_loss: number;
  best_baseline_loss: number;
  ensemble_status: EnsembleEvaluationStatus;
  ensemble_recommended: boolean;
  ensemble_members: string[];
  independent_holdout: false;
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
    strategy: "expanding" | "sliding" | "single";
    horizon: number;
    n_splits: number;
    gap: number;
    train_window: number;
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
