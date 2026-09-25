// packages/ui/lib/progress.ts
//
// Данные блок-схемы и трассы панели «Прогресс» (Task PROGR-4,
// spec_progress.md §2-§4, §6.2, §12 п.10).
//
// РЕЕСТР УЗЛОВ. Источник истины -- app/core/pipeline_graph.py::STAGE_NODES
// (46 узлов, 6 стадий). Общего рантайма Python/TS у платформы нет
// (§12 п.2 решён общим JSON только для EDA), поэтому здесь -- копия id,
// связанная sync-тестом tests/api/test_progress_panel.py (читает живой
// исходник этого файла, паттерн test_eda_tsx_imports_shared_json /
// CERTIFIED_IDS). Менять id независимо от графа нельзя -- sync-тест
// упадёт первым.
//
// СТАТУСЫ УЗЛОВ (§3). Словарь статуса зависит от стадии: CheckStatus
// (StatusIcon.tsx) для проверочных upload/validation/preprocessing/eda,
// StageStatus (stages.ts) для процессных modeling/forecasting. Из трассы
// (§4.1 -- журнал решений, не статистика) выводятся только факты:
//   * терминальное событие решения -> done (применено/построено);
//   * correction_previewed -> warning («найдены проблемы»: preview
//     показывается ТОЛЬКО при найденных нарушениях -- решение ещё не
//     принято);
//   * profile_viewed -> running (узел исследуется);
//   * события уровня стадии (node_id=null: mode_changed,
//     target_column_changed, passport_captured) -- не про узел, в
//     статусы не попадают.
// Свёртка в 3 визуальных состояния карточки -- точный порт
// fold_status_values бэкенда (§12 п.10), застрахован зеркальной
// таблицей кейсов в progress.test.ts.
//
// ПРОГНОЗИРОВАНИЕ. Слой 1 (PROGR-3) forecasting-событий не содержит
// (they живут в ForecastRun.trace -- унификация хранения PROGR-5),
// поэтому панель досчитывает их из живого GET /v1/session/modeling/
// forecast (§3: статус Прогнозирования -- «по факту наличия ForecastRun/
// конкретных trace_events»); node_id = event_type -- 4 канонических
// типа §4.1 совпадают с узлами графа.

import edaChecksJson from "../../../shared/pipeline_nodes/eda_checks.json";
import { STAGE_DEFS } from "./stages";

// ── §2: стадии и узлы (копия графа, sync-тест страхует) ─────────────

export const PROGRESS_STAGE_NODES: Record<string, readonly string[]> = {
  // Ключи в кавычках -- формат страхован sync-тестом (regex-парсер
  // живого исходника; не реорганизовывать без теста).
  "upload": ["structure_confirmed"],
  "validation": [
    "data_types", "formats", "ranges", "consistency", "uniqueness",
    "inclusion", "referential", "text_quality", "regularity", "sufficiency",
  ],
  "preprocessing": [
    "missing", "outliers", "regularity", "decomposition", "variance_stab",
    "smoothing", "stationarity", "spectral", "feature_eng", "scaling",
  ],
  // EDA -- из общего JSON §12 п.2 (тот же источник, что у TsAnalysisEDA).
  "eda": (edaChecksJson.nodes as ReadonlyArray<{ id: string }>).map((n) => n.id),
  "modeling": [
    "problem_definition", "data_structure", "constraint_mapping",
    "candidate_generation", "baseline_estimation", "backtest", "tuning",
    "diagnostics", "comparison", "selection", "model_card",
  ],
  "forecasting": [
    "forecast_generated", "forecast_compared",
    "forecast_sensitivity_computed", "forecast_exported",
  ],
};

// ── Человекочитаемые метки узлов (раскрытие стадии, §6.2) ───────────
// Валидация/Предобработка -- те же подписи, что у степперов вкладок
// (TsAnalysisValidation.tsx CHECK_META / TsAnalysisPreprocessing.tsx);
// EDA -- label из общего JSON; Моделирование -- PIPELINE_STAGES из
// modeling.ts; Загрузка/Прогнозирование -- формулировки §2/§4.1.

const NODE_LABELS: Record<string, Record<string, string>> = {
  upload: { structure_confirmed: "Структура данных" },
  validation: {
    data_types: "Типы данных",
    formats: "Форматы и шаблоны",
    ranges: "Диапазоны значений",
    consistency: "Логика и хронология",
    uniqueness: "Уникальность",
    inclusion: "Принадлежность к набору",
    referential: "Ссылочная целостность",
    text_quality: "Целостность текста",
    regularity: "Равномерность шага",
    sufficiency: "Достаточность наблюдений",
  },
  preprocessing: {
    missing: "Пропуски",
    outliers: "Выбросы",
    regularity: "Регулярность ряда",
    decomposition: "Декомпозиция ряда",
    variance_stab: "Стабилизация дисперсии",
    smoothing: "Сглаживание ряда",
    stationarity: "Стационарность ряда",
    spectral: "Спектральный анализ",
    feature_eng: "Генерация признаков",
    scaling: "Масштабирование",
  },
  eda: Object.fromEntries(
    (edaChecksJson.nodes as ReadonlyArray<{ id: string; label: string }>).map(
      (n) => [n.id, n.label],
    ),
  ),
  modeling: {
    problem_definition: "Определение задачи",
    data_structure: "Структура данных",
    constraint_mapping: "Ограничения",
    candidate_generation: "Пул кандидатов",
    baseline_estimation: "Baseline",
    backtest: "Бэктест",
    tuning: "Тюнинг",
    diagnostics: "Диагностика",
    comparison: "Сравнение",
    selection: "Выбор модели",
    model_card: "Model Card",
  },
  forecasting: {
    forecast_generated: "Прогноз построен",
    forecast_compared: "Сравнение прогнозов",
    forecast_sensitivity_computed: "Анализ чувствительности",
    forecast_exported: "Экспорт прогноза",
  },
};

export function nodeLabel(stage: string, nodeId: string): string {
  return NODE_LABELS[stage]?.[nodeId] ?? nodeId;
}

export function isKnownNode(stage: string, nodeId: string): boolean {
  return (PROGRESS_STAGE_NODES[stage] ?? []).includes(nodeId);
}

// ── Событие трассы на фронтенде (канон §4.1, to_dict бэкенда) ───────

export interface TraceEventInfo {
  event_id?: string;
  run_id?: string;
  ts: string;
  stage: string;
  node_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  actor?: string;
}

// ── Вывод статусов узлов из фактов трассы (§4.1) ────────────────────

// Терминальные события решения/результата -> done. Для forecasting
// node_id == event_type (4 канонических типа §4.1 == узлы графа §2).
const PROGRESS_EVENT_STATUS: Record<string, string> = {
  upload_completed: "done",
  correction_applied: "done",
  correction_previewed: "warning",
  profile_viewed: "running",
  backtest_run: "done",
  tuning_trial_completed: "done",
  model_selected: "done",
  model_card_generated: "done",
  forecast_generated: "done",
  forecast_compared: "done",
  forecast_sensitivity_computed: "done",
  forecast_exported: "done",
};

/** Статус каждого узла по последнему его событию (хронология входа
 * сохраняется: позднее событие перезаписывает раннее -- previewed ->
 * applied = done). Ключ -- "stage/node_id" (id сознательно пересекаются
 * между стадиями: regularity/stationarity). События без node_id, без
 * известного маппинга или вне графа честно пропускаются: фантомных
 * узлов не возникает. */
export function deriveNodeStatuses(events: TraceEventInfo[]): Record<string, string> {
  const statuses: Record<string, string> = {};
  for (const event of events) {
    if (!event.node_id) continue;
    const status = PROGRESS_EVENT_STATUS[event.event_type];
    if (!status) continue;
    if (!isKnownNode(event.stage, event.node_id)) continue;
    statuses[`${event.stage}/${event.node_id}`] = status;
  }
  return statuses;
}

// ── Свёртка §12 п.10 (точный порт fold_status_values) ───────────────

export const FOLD_PASSED = "passed";
export const FOLD_ATTENTION = "attention";
export const FOLD_NOT_STARTED = "not_started";

export type FoldVisualState = "passed" | "attention" | "not_started";

const KNOWN_NODE_STATUSES: ReadonlySet<string> = new Set([
  // CheckStatus (StatusIcon.tsx)
  "done", "warning", "pending", "skipped", "running", "error",
  // StageStatus (stages.ts)
  "in_progress",
]);

const STARTED_BEYOND_DONE: ReadonlySet<string> = new Set(["running", "in_progress"]);

export function foldNodeStatuses(statuses: string[]): FoldVisualState {
  if (statuses.length === 0) return FOLD_NOT_STARTED;
  for (const status of statuses) {
    if (!KNOWN_NODE_STATUSES.has(status)) {
      throw new Error(
        `Неизвестный статус узла: ${status}; известные: done/warning/pending/skipped/running/error/in_progress`,
      );
    }
  }
  if (statuses.some((s) => s === "warning" || s === "error")) return FOLD_ATTENTION;
  if (statuses.every((s) => s === "done")) return FOLD_PASSED;
  if (
    statuses.some((s) => s === "done") &&
    statuses.every((s) => s === "done" || s === "skipped")
  ) {
    // skipped агрегатно не мешает пройденности, но не заменяет её.
    return FOLD_PASSED;
  }
  if (statuses.some((s) => s === "done" || STARTED_BEYOND_DONE.has(s))) {
    return FOLD_ATTENTION;
  }
  return FOLD_NOT_STARTED;
}

// ── Свод по стадии: свёртка + краткая подпись карточки (§6.2) ───────

export interface StageSummary {
  fold: FoldVisualState;
  /** «1/10, найдены проблемы» / «1/11, в работе» / «1/1, пройдено» / «не начато» */
  text: string;
  doneCount: number;
  total: number;
}

export function stageSummary(stage: string, statuses: Record<string, string>): StageSummary {
  const nodes = PROGRESS_STAGE_NODES[stage] ?? [];
  const nodeStatuses = nodes.map((n) => statuses[`${stage}/${n}`] ?? "pending");
  const doneCount = nodeStatuses.filter((s) => s === "done").length;
  const total = nodes.length;
  const fold = foldNodeStatuses(nodeStatuses);
  if (fold === FOLD_NOT_STARTED) return { fold, text: "не начато", doneCount, total };
  if (fold === FOLD_PASSED) return { fold, text: `${doneCount}/${total}, пройдено`, doneCount, total };
  const hasWarning = nodeStatuses.some((s) => s === "warning" || s === "error");
  return {
    fold,
    text: `${doneCount}/${total}, ${hasWarning ? "найдены проблемы" : "в работе"}`,
    doneCount,
    total,
  };
}

// ── Чекпоинты и статусы запуска (Task PROGR-5.1, §5-§5.2) ───────────────

// Статусы research_runs (§5: active/paused/completed/abandoned) --
// человекочитаемые метки бейджа полосы действий. Неизвестный статус
// возвращается как есть (честный текст, не маскировка).
const RUN_STATUS_LABELS: Record<string, string> = {
  active: "В работе",
  paused: "На паузе",
  completed: "Завершён",
  abandoned: "Брошен",
};

export function runStatusLabel(status: string): string {
  return RUN_STATUS_LABELS[status] ?? status;
}

/** Чекпоинт слоя 2 (§5.1): именованная ссылка на событие трассы
 * (паттерн PassportCheckpoint), ровно как отдаёт GET /v1/progress/runs/{id}. */
export interface CheckpointInfo {
  checkpoint_id: string;
  run_id: string;
  event_id: string;
  label: string;
  has_snapshot: boolean;
  created_at: string;
}

/** Последнее в хронологии событие с непустым event_id -- кандидат на якорь
 * нового чекпоинта («текущий момент» исследования). События без event_id
 * (legacy-трасса, слитые события ForecastRun.trace -- legacy 3-польный
 * контракт) пропускаются: чекпоинт -- ссылка на ИДЕНТИФИЦИРОВАННОЕ событие,
 * бэкенд отклонил бы ссылку без id (404). */
export function lastCheckpointableEvent(events: TraceEventInfo[]): TraceEventInfo | null {
  const chronological = sortEventsChronologically(events);
  for (let i = chronological.length - 1; i >= 0; i -= 1) {
    const event = chronological[i];
    if (event.event_id) return event;
  }
  return null;
}

// ── Слияние ForecastRun.trace (§3: прогнозирование по факту трассы) ──

export interface ForecastRunLike {
  forecast_id?: string;
  trace_events?: ReadonlyArray<{
    event_type: string;
    timestamp: string;
    payload?: Record<string, unknown>;
  }>;
}

/** Legacy 3-польный формат (event_type/timestamp/payload -- контракт
 * ForecastTraceEventSchema) -> канон §4.1 на фронтенде: ts = timestamp,
 * stage = "forecasting", node_id = event_type (4 типа совпадают с
 * узлами графа). Чужие типы пропускаются (fail-safe). */
export function collectForecastTraceEvents(forecasts: ReadonlyArray<ForecastRunLike>): TraceEventInfo[] {
  const events: TraceEventInfo[] = [];
  for (const run of forecasts ?? []) {
    for (const raw of run?.trace_events ?? []) {
      if (!isKnownNode("forecasting", raw.event_type)) continue;
      events.push({
        event_type: raw.event_type,
        ts: raw.timestamp,
        stage: "forecasting",
        node_id: raw.event_type,
        payload: raw.payload ?? {},
      });
    }
  }
  return events;
}

/** Хронологический порядок §6.2 (старые раньше новых); события с
 * нечитаемым ts -- в конец, взаимный порядок сохраняется. */
export function sortEventsChronologically(events: TraceEventInfo[]): TraceEventInfo[] {
  const time = (ts: string): number => {
    const parsed = new Date(ts).getTime();
    return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed;
  };
  return [...events].sort((a, b) => time(a.ts) - time(b.ts));
}

/** Метка стадии для рендера -- единый источник с навигацией (stages.ts),
 * чтобы карточки блок-схемы не разошлись с бейджами меню. */
export function stageLabel(stage: string): string {
  return STAGE_DEFS.find((s) => s.key === stage)?.label ?? stage;
}
