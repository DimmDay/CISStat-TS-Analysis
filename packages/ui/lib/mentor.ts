// packages/ui/lib/mentor.ts
//
// Клиентский слой «Наставника v1» (Task PROGR-6, spec_progress.md §7).
// Бэкенд -- правило-движок app/core/mentor_rules.py (без LLM):
//
//   GET  /v1/progress/runs/{run_id}/mentor/next-step  (§7.1 «Следующий
//        шаг» + history-предупреждения on_demand_with_history §7.2)
//   POST /v1/progress/mentor/sanity-check             (§7.2 -- ВЕСЬ
//        список предупреждений над preview-исходом Мастера)
//
// §7.2 дословно: «frontend строит CorrectionOutcomeSummary из уже
// полученного preview-ответа конкретного Мастера -- маппинг тривиален,
// разный набор полей у Missing/Outliers/Regularity сводится к общим
// именам на клиенте перед отправкой». Здесь -- этот маппинг
// (buildCorrectionOutcomeSummary) и выбор колонки статистик для правила
// over_aggressive (worstStdStats): бэкенд принимает ОДНУ пару
// stats_before/stats_after, а у Мастеров она по-колоночная.
//
// Все запросы -- best-effort (паттерн панели PROGR-4): сбой сети/слоя
// не роняет Мастер или панель; sanity-предупреждения вспомогательны.

import { progressApiUrl } from "./apiClient";

// ── Контракты ответов (зеркало pydantic-схем progress.py) ───────────

export interface SanityWarningInfo {
  rule_id: string;
  severity: string; // "info" | "warning"
  message: string;
  suggested_action?: string | null;
}

export interface MentorRecommendationInfo {
  rule_id: string;
  stage: string;
  message: string;
  recommended_action?: string | null;
}

export interface MentorNodeFact {
  node_id: string;
  status: string;
}

export interface MentorPhaseSummaryInfo {
  stage: string;
  total_nodes: number;
  done_count: number;
  warning_nodes: number;
  nodes: MentorNodeFact[];
}

export interface MentorNextStepInfo {
  run_id: string;
  run_status: string;
  last_active_stage: string;
  phase_text: string;
  summary: MentorPhaseSummaryInfo;
  recommendation: MentorRecommendationInfo | null;
  history_warnings: SanityWarningInfo[];
}

// ── §7.2: нормализованный preview-исход Мастера ──────────────────────

export interface CorrectionOutcomeSummaryInput {
  stage: string;
  nodeId: string;
  strategy: string;
  method?: string | null;
  affectedBefore: number;
  changed: number;
  stillAffected: number;
  rowsBefore: number;
  rowsAfter: number;
  /** Агрегированная пара статистик «до/после» (worstStdStats) -- для
   * правила over_aggressive; без неё правило честно молчит (§7.2). */
  statsBefore?: Record<string, number | null> | null;
  statsAfter?: Record<string, number | null> | null;
}

/** Переупаковка camelCase-полей клиента в snake_case-тело бэкенда.
 * Не новые вычисления -- только общие имена (§7.2 дословно). */
export function buildCorrectionOutcomeSummary(
  input: CorrectionOutcomeSummaryInput,
): Record<string, unknown> {
  return {
    stage: input.stage,
    node_id: input.nodeId,
    strategy: input.strategy,
    method: input.method ?? null,
    affected_count_before: input.affectedBefore,
    changed_count: input.changed,
    still_affected_count: input.stillAffected,
    rows_before: input.rowsBefore,
    rows_after: input.rowsAfter,
    stats_before: input.statsBefore ?? null,
    stats_after: input.statsAfter ?? null,
  };
}

// ── Выбор колонки статистик для over_aggressive ─────────────────────

export interface ColumnStatsLike {
  stats_before?: { std?: number | null; mean?: number | null; median?: number | null } | null;
  stats_after?: { std?: number | null; mean?: number | null; median?: number | null } | null;
}

/** Из по-колоночных статистик preview-ответа -- пара с НАИБОЛЬШИМ
 * падением std (минимальное отношение after/before). Правило
 * over_aggressive ловит переглаживание; «худшая» колонка -- честный
 * кандидат, а не подмена фактов. Колонки без валидной пары (нечисловая
 * колонка, std_before=0/null) пропускаются. */
export function worstStdStats(
  columns: ReadonlyArray<ColumnStatsLike>,
): { statsBefore: Record<string, number | null>; statsAfter: Record<string, number | null> } | null {
  let worst: { before: Record<string, number | null>; after: Record<string, number | null>; ratio: number } | null = null;
  for (const column of columns ?? []) {
    const before = column?.stats_before;
    const after = column?.stats_after;
    const stdBefore = before?.std;
    const stdAfter = after?.std;
    if (typeof stdBefore !== "number" || !Number.isFinite(stdBefore)) continue;
    if (typeof stdAfter !== "number" || !Number.isFinite(stdAfter)) continue;
    if (stdBefore <= 0) continue;
    const ratio = stdAfter / stdBefore;
    if (worst === null || ratio < worst.ratio) {
      worst = {
        before: { ...before, std: stdBefore },
        after: { ...after, std: stdAfter },
        ratio,
      };
    }
  }
  if (worst === null) return null;
  return { statsBefore: worst.before, statsAfter: worst.after };
}

// ── Запросы (best-effort) ────────────────────────────────────────────

/** §7.2 sanity-check: предупреждения над кнопкой «Применить исправления».
 * Любой сбой (сеть/4xx/5xx/битый JSON) -- пустой список, не ошибка:
 * Мастер обязан работать и без Наставника (предупреждения вспомогательны,
 * §12 п.8 -- сигнал, не принуждение). */
export async function fetchSanityWarnings(
  summary: Record<string, unknown>,
): Promise<SanityWarningInfo[]> {
  try {
    const response = await fetch(progressApiUrl("/mentor/sanity-check"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(summary),
    });
    if (!response.ok) return [];
    const data = await response.json();
    return Array.isArray(data?.warnings) ? (data.warnings as SanityWarningInfo[]) : [];
  } catch {
    return [];
  }
}

/** §7.1 «Следующий шаг» для панели Наставника. null при любом сбое --
 * панель показывает честное «Наставник недоступен» (best-effort). */
export async function fetchMentorNextStep(
  runId: string,
): Promise<MentorNextStepInfo | null> {
  try {
    const response = await fetch(
      progressApiUrl(`/runs/${runId}/mentor/next-step`),
      { credentials: "include" },
    );
    if (!response.ok) return null;
    return (await response.json()) as MentorNextStepInfo;
  } catch {
    return null;
  }
}
