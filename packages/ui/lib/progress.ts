// packages/ui/lib/progress.ts
//
// Данные блок-схемы и трассы панели «Прогресс» (Task PROGR-4,
// spec_progress.md §2-§4, §6.2, §12 п.10; Расхождение №1 -- Task
// PROGR-10).
//
// РЕЕСТР УЗЛОВ. Источник истины -- app/core/pipeline_graph.py::STAGE_NODES
// (50 узлов, 6 стадий). Общего рантайма Python/TS у платформы нет
// (§12 п.2 решён общим JSON для EDA и -- с PROGR-13-A1 -- для остановок
// «Загрузки»: id stage upload живут здесь текстово, sync-тест
// tests/api/test_progress_panel.py читает живой исходник этого файла,
// паттерн test_eda_tsx_imports_shared_json / CERTIFIED_IDS; метки
// остановок -- из того же общего JSON, копии строк нет). Менять id
// независимо от графа нельзя -- sync-тест упадёт первым.
//
// СТАТУСЫ УЗЛОВ (§3) -- ГОТОВОЕ СОСТОЯНИЕ ОТ БЭКЕНДА (PROGR-10,
// Расхождение №1). Вывод статуса из фактов решений живёт НА БЭКЕНДЕ --
// единый движок app/core/node_status.py для трёх потребителей (панель,
// Наставник, admin-аналитика); GET /v1/progress/trace отдаёт
// node_statuses (карта "stage/node_id" -> статус) и stages (свёртка
// §12 п.10 + счётчики). Фронтенд рендерит, не вычисляет: до PROGR-10
// здесь жила локальная копия движка (карта «тип события -> статус»,
// деривация статусов, порт свёртки, слияние прогнозной трассы и
// свод стадии) -- расползание с бэкендом было тихим по построению.
//
// ОСТАВШИЕСЯ КОНТРАКТЫ: FOLD_*-константы и FoldVisualState -- контракт
// значений fold ответа; stageStateText -- сборка человекочитаемой
// подписи карточки §6.2 из ГОТОВЫХ счётчиков (текст -- UI-
// ответственность, вычисление -- бэкенд).
//
// ПРОГНОЗИРОВАНИЕ. Слой 1 (PROGR-3) forecasting-событий не содержит
// (они живут в ForecastRun.trace -- унификация хранения PROGR-5):
// СЕРВЕР сам сливает их с слоем 1 в /trace (канонизация 3-польной
// записи, хронологическая сортировка) -- второй опрос панелью
// /v1/session/modeling/forecast и клиентское слияние удалены
// (минус один запрос и минус одна гонка).

import edaChecksJson from "../../../shared/pipeline_nodes/eda_checks.json";
import uploadStopsJson from "../../../shared/pipeline_nodes/upload_stops.json";
import { STAGE_DEFS } from "./stages";

// ── §2: стадии и узлы (копия графа, sync-тест страхует) ─────────────

export const PROGRESS_STAGE_NODES: Record<string, readonly string[]> = {
  // Ключи в кавычках -- формат страхован sync-тестом (regex-парсер
  // живого исходника; не реорганизовывать без теста).
  // PROGR-13-A1: 5 остановок -- тот же реестр, что у модуля
  // TsAnalysisUpload и графа бэкенда (общий JSON upload_stops.json);
  // порядок = порядок объектов JSON = порядок остановок степпера.
  // PROGR-13-B: legacy "structure_confirmed" старого корпуса
  // нормализуется на бэкенде (LEGACY_NODE_IDS).
  "upload": [
    "overview", "chart", "distribution", "structure", "quality",
  ],
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
// EDA и Загрузка -- label из общего JSON; Моделирование --
// PIPELINE_STAGES из modeling.ts; Прогнозирование -- формулировки §4.1.

const NODE_LABELS: Record<string, Record<string, string>> = {
  // PROGR-13-A5: метки остановок «Загрузки» -- из общего JSON §12 п.2
  // (тот же источник, что у STOPS модуля и графа бэкенда).
  upload: Object.fromEntries(
    (uploadStopsJson.nodes as ReadonlyArray<{ id: string; label: string }>).map(
      (n) => [n.id, n.label],
    ),
  ),
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

// ── Готовое состояние панели (PROGR-10, зеркало StageStateOut) ──────

// Значения fold -- КОНТРАКТ ответа /trace (каноническая свёртка
// §12 п.10 вычисляется бэкендом, fold_status_values); константы
// остаются для типизации и FOLD_BG-мэппинга рендера.
export const FOLD_PASSED = "passed";
export const FOLD_ATTENTION = "attention";
export const FOLD_NOT_STARTED = "not_started";

export type FoldVisualState = "passed" | "attention" | "not_started";

/** Зеркало StageStateOut (apps/api/routers/progress.py): готовая
 * свёртка стадии + счётчики единого движка. */
export interface StageStateInfo {
  stage: string;
  fold: FoldVisualState;
  done_count: number;
  warning_nodes: number;
  total_nodes: number;
}

// ── Полное состояние узла §3 (PROGR-11, зеркало NodeStateOut) ─────

/** Зеркало NodeStateOut (apps/api/routers/progress.py) / PipelineNodeState
 * (app/core/pipeline_graph.py §3): полный узел панели. До PROGR-11 поля
 * status_reason/mode/summary_count/last_touched_at объявлялись в
 * датаклассе, но до UI не доезжали (/trace отдавал только статус из
 * событий) -- расхождение закрыто: бэкенд (единый движок
 * app/core/node_status.py::derive_pipeline_node_states) отдаёт ГОТОВЫЕ
 * поля, фронтенд рендерит, не вычисляет. */
export interface NodeStateInfo {
  stage: string;
  node_id: string;
  status: string;
  /** Человекочитаемая причина статуса (факт последнего события решения). */
  status_reason: string | null;
  /** Эффективный режим проверки (auto/enabled/disabled) -- только
   * Валидация/Предобработка; вне них null. */
  mode: string | null;
  /** ts последнего события узла. */
  last_touched_at: string | null;
  /** Число правого бейджа узла (§3, напр. total_missing); факта нет -- null. */
  summary_count: number | null;
}

/** Ключ узла -- тот же формат, что у node_statuses ответа /trace. */
export function nodeStateKey(stage: string, nodeId: string): string {
  return `${stage}/${nodeId}`;
}

/** Карта "stage/node_id" -> полное состояние (для рендера по узлам).
 * Пустой/отсутствующий ответ -- пустая карта: старый бэкенд деградирует
 * к прежнему рендеру (N-3, аддитивность). */
export function nodeStateMap(
  nodes: NodeStateInfo[],
): Record<string, NodeStateInfo> {
  const map: Record<string, NodeStateInfo> = {};
  for (const node of nodes) {
    map[nodeStateKey(node.stage, node.node_id)] = node;
  }
  return map;
}

// Метки режимов проверки §3 (текст -- UI-ответственность; значения --
// контракт NODE_MODE_VALUES бэкенда). Неизвестное значение -- как есть.
const NODE_MODE_LABELS: Record<string, string> = {
  auto: "авто",
  enabled: "вкл",
  disabled: "выкл",
};

export function nodeModeLabel(mode: string): string {
  return NODE_MODE_LABELS[mode] ?? mode;
}

/** Подпись карточки стадии §6.2 из ГОТОВЫХ счётчиков ответа: «1/10,
 * найдены проблемы» / «1/11, в работе» / «1/1, пройдено» / «не начато».
 * Текст -- UI-ответственность; вычисление fold/счётчиков -- бэкенд. */
export function stageStateText(stage: StageStateInfo): string {
  if (stage.fold === FOLD_NOT_STARTED) return "не начато";
  if (stage.fold === FOLD_PASSED) {
    return `${stage.done_count}/${stage.total_nodes}, пройдено`;
  }
  return `${stage.done_count}/${stage.total_nodes}, ${
    stage.warning_nodes > 0 ? "найдены проблемы" : "в работе"
  }`;
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
 * (legacy-трасса, канонизируемые события ForecastRun.trace -- сервер не
 * выдумывает идентификаторы) пропускаются: чекпоинт -- ссылка на
 * ИДЕНТИФИЦИРОВАННОЕ событие, бэкенд отклонил бы ссылку без id (404). */
export function lastCheckpointableEvent(events: TraceEventInfo[]): TraceEventInfo | null {
  const chronological = sortEventsChronologically(events);
  for (let i = chronological.length - 1; i >= 0; i -= 1) {
    const event = chronological[i];
    if (event.event_id) return event;
  }
  return null;
}

/** Хронологический порядок §6.2 (старые раньше новых); события с
 * нечитаемым ts -- в конец, взаимный порядок сохраняется. Ответ /trace
 * уже отсортирован сервером (PROGR-10); функция остаётся для
 * независимых источников (полоса действий) и как контракт порядка. */
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
