// packages/ui/lib/task-stops.ts
//
// Источник истины для хаба «Задачи» (/tasks) — реестр задач, решаемых
// на основе пайплайна, и контракт гейтинга по входу (spec_tasks_ia.md).
//
// IA-решение (spec_tasks_ia.md §3): пайплайн — конечная горизонталь
// (замороженные 6 этапов STAGE_DEFS/STAGES), задачи — открытая вертикаль,
// растущая внутри хаба /tasks. Верхнее меню не растёт с задачами.
//
// Зависимость от прогноза — НЕ глобальная (spec_tasks_ia.md §2):
// каждая задача декларирует собственный контракт входа — минимальный
// набор артефактов сессии. «Причины» и «Сценарии» работают от Model Card
// (модель + история), «Принятие решений» и «Мониторинг прогноза» —
// от ForecastRun.
//
// Живёт отдельно от home-stops.ts / navigator-stops.ts: эти данные
// описывают задачи поверх пайплайна, а не маршруты знакомства или этапы.

import type { LucideIcon } from "lucide-react";
import { GitBranch, SearchCheck, Scale, Radar } from "lucide-react";
import { STAGE_DEFS, StageStatus } from "./stages";

// ── Типы ──────────────────────────────────────────────────────

/** Артефакт сессии, требуемый задачей (порядок = порядок пайплайна). */
export type TaskArtifact = "validated" | "model_card" | "forecast_run";

/** Три состояния задачи в хабе (spec_tasks_ia.md §4). */
export type TaskGateState = "available" | "awaiting" | "blocked";

/** Указатель на этап пайплайна (цель микро-CTA awaiting-карточки, R5). */
export interface StagePointer {
  /** Ключ этапа (совпадает с STAGE_DEFS key). */
  key: string;
  /** Человекочитаемая метка этапа. */
  label: string;
  /** Маршрут этапа (STAGE_DEFS href). */
  href: string;
}

export interface TaskRoute {
  /** Стабильный идентификатор (маршрут /tasks/<id>, ключи React). */
  id: string;
  /** Короткий заголовок — название задачи. */
  title: string;
  /** Одна поясняющая строка — что пользователь получает. */
  description: string;
  /** Пиктограмма из lucide-react. */
  icon: LucideIcon;
  /** Куда ведёт клик (плейсхолдер до реализации задачи). */
  href: string;
  /** Контракт входа: артефакты, без которых исполнение невозможно. */
  requires: TaskArtifact[];
  /** Рекомендуемые (НЕ гейтящие) артефакты — подсказка хаба (spec §2, R2). */
  recommendedWith?: TaskArtifact[];
  /**
   * 2–3 буллета обещанного результата в дополнение к строке описания
   * (v1.1, spec_tasks_ia_addendum_v1_1.md §9.3). Формулировки — по
   * продукту («Вклад каждого фактора в прогноз»), не по механике
   * («использует SHAP»): обещание результата, а не перечисление методов.
   */
  outcomes?: string[];
}

// ── Реестр задач v1 (spec_tasks_ia.md §5) ──────────────────────

export const TASK_ROUTES: TaskRoute[] = [
  {
    id: "scenarios",
    title: "Сценарии",
    description: "what-if поверх модели: шоки и альтернативные траектории ряда",
    icon: GitBranch,
    href: "/tasks/scenarios",
    requires: ["model_card"],
    // spec_tasks_ia.md §2: forecast_run — рекомендуемый (не гейтящий)
    // артефакт: веер налагается на базовый прогноз. Подсказка хаба (R2).
    recommendedWith: ["forecast_run"],
    // v1.1 §9.3: обещанные результаты — по продукту, не по механике.
    outcomes: [
      "Сравнение сценариев на одном графике",
      "Альтернативные траектории ряда при изменении входа",
      "Оценка, как шок параметров меняет прогноз",
    ],
  },
  {
    id: "causes",
    title: "Причины",
    description: "драйверы и атрибуция: SHAP, IRF/FEVD, тест Грейнджера",
    icon: SearchCheck,
    href: "/tasks/causes",
    requires: ["model_card"],
    outcomes: [
      "Вклад каждого фактора в прогноз",
      "Причинные связи между рядами, а не только корреляции",
      "Понимание, почему модель предсказывает именно так",
    ],
  },
  {
    id: "decisions",
    title: "Принятие решений",
    description: "решения по прогнозным значениям: пороги, правила, iDSS",
    icon: Scale,
    href: "/tasks/decisions",
    requires: ["forecast_run"],
    outcomes: [
      "Конкретные рекомендации при выходе за пороги",
      "Проверка правил на прогнозных значениях",
      "Единая картина правил и их срабатываний",
    ],
  },
  {
    id: "monitoring",
    title: "Мониторинг прогноза",
    description: "факт против прогноза: дрифт, алерты, триггер переобучения",
    icon: Radar,
    href: "/tasks/monitoring",
    requires: ["forecast_run"],
    outcomes: [
      "Сравнение факта с прогнозом по мере поступления данных",
      "Сигналы о дрейфе и отклонениях",
      "Триггер своевременного переобучения модели",
    ],
  },
];

// ── Слой артефактов: этапы сессии -> артефакты ────────────────

/** Этап-владелец каждого артефакта (зеркало STAGE_DEFS; контракт 1:1). */
export const ARTIFACT_STAGE: Record<TaskArtifact, string> = {
  validated: "validation",
  model_card: "modeling",
  forecast_run: "forecasting",
};

/** Артефакты, существующие в сессии: этап-владелец дошёл до "done". */
export function artifactsFromStages(
  stages: Record<string, StageStatus>
): TaskArtifact[] {
  return (Object.keys(ARTIFACT_STAGE) as TaskArtifact[]).filter(
    (artifact) => stages[ARTIFACT_STAGE[artifact]] === "done"
  );
}

/** Пайплайн начат: хотя бы один из шести этапов дошёл до "done". */
export function pipelineStartedFromStages(
  stages: Record<string, StageStatus>
): boolean {
  return STAGE_DEFS.some((s) => stages[s.key] === "done");
}

// ── Гейтинг: три состояния (spec_tasks_ia.md §4) ──────────────

/** Порядок артефактов = порядок пайплайна (spec_tasks_ia.md §4). */
const PIPELINE_ORDER: TaskArtifact[] = [
  "validated",
  "model_card",
  "forecast_run",
];

/** Первый недостающий артефакт контракта в порядке пайплайна; null — всё есть. */
function firstMissingArtifact(
  requires: TaskArtifact[],
  artifacts: TaskArtifact[]
): TaskArtifact | null {
  const missing = requires.filter((r) => !artifacts.includes(r));
  if (missing.length === 0) return null;
  return (
    missing.sort(
      (a, b) => PIPELINE_ORDER.indexOf(a) - PIPELINE_ORDER.indexOf(b)
    )[0] ?? null
  );
}

/**
 * available — весь контракт входа satisfied;
 * awaiting   — контракт не satisfied, но пайплайн уже начат
 *              (недостающие артефакты создадут обязательные этапы);
 * blocked    — контракт не satisfied, сессия свежая (нечего ждать).
 */
export function deriveTaskGateState(
  requires: TaskArtifact[],
  artifacts: TaskArtifact[],
  pipelineStarted: boolean
): TaskGateState {
  const satisfied = requires.every((r) => artifacts.includes(r));
  if (satisfied) return "available";
  return pipelineStarted ? "awaiting" : "blocked";
}

/**
 * Куда идти за недостающим артефактом (awaiting): этап-владелец ПЕРВОГО
 * недостающего артефакта в порядке пайплайна — общий источник истины для
 * текста причины (taskGateReason) и цели микро-CTA (R5). null — вне awaiting.
 */
export function awaitStageInfo(
  requires: TaskArtifact[],
  artifacts: TaskArtifact[],
  pipelineStarted: boolean
): StagePointer | null {
  if (
    deriveTaskGateState(requires, artifacts, pipelineStarted) !== "awaiting"
  ) {
    return null;
  }
  const firstMissing = firstMissingArtifact(requires, artifacts);
  if (!firstMissing) return null;
  const stage = STAGE_DEFS.find((s) => s.key === ARTIFACT_STAGE[firstMissing]);
  return stage ? { key: stage.key, label: stage.label, href: stage.href } : null;
}

/**
 * СИММЕТРИЧНЫЙ указатель микро-CTA (follow-up R5, заказ тимлида): куда
 * идти, чтобы приблизить задачу к доступности — единый источник истины
 * для обеих некликабельных состояний.
 *   awaiting  — этап-владелец первого недостающего артефакта
 *               (делегирует awaitStageInfo);
 *   blocked   — этап «Загрузка» (вход в пайплайн: пока датасета нет,
 *               последующие этапы нереализуемы, потому причина и говорит
 *               «Начните с этапа Загрузка» — CTA ведёт туда же, а НЕ на
 *               владельца недостающего артефакта);
 *   available — null (CTA не нужен).
 */
export function ctaStageInfo(
  requires: TaskArtifact[],
  artifacts: TaskArtifact[],
  pipelineStarted: boolean
): StagePointer | null {
  const state = deriveTaskGateState(requires, artifacts, pipelineStarted);
  if (state === "available") return null;
  if (state === "blocked") {
    const upload = STAGE_DEFS.find((s) => s.key === "upload");
    return upload
      ? { key: upload.key, label: upload.label, href: upload.href }
      : null;
  }
  return awaitStageInfo(requires, artifacts, pipelineStarted);
}

/**
 * Человекочитаемая причина недоступности (для плашки на карточке и
 * aria-label). null — для available.
 */
export function taskGateReason(
  requires: TaskArtifact[],
  artifacts: TaskArtifact[],
  pipelineStarted: boolean
): string | null {
  const state = deriveTaskGateState(requires, artifacts, pipelineStarted);
  if (state === "available") return null;

  if (state === "blocked") {
    return "Начните с этапа Загрузка — задачи работают поверх артефактов пайплайна";
  }

  // awaiting: первый недостающий артефакт в порядке пайплайна (см. R5).
  const stage = awaitStageInfo(requires, artifacts, pipelineStarted);
  if (stage) {
    return `Станет доступна после этапа ${stage.label}`;
  }
  const firstMissing = firstMissingArtifact(requires, artifacts);
  return `Станет доступна после этапа ${
    firstMissing ? ARTIFACT_STAGE[firstMissing] : "?"
  }`;
}

/**
 * Подсказка о рекомендуемом (НЕ гейтящем) артефакте (spec_tasks_ia.md §2,
 * R2 сертификации IA-1): «Рекомендуется также этап {Label}». null — когда
 * подсказывать нечего (рекомендации пусты или уже выполнены).
 */
export function taskRecommendedHint(
  recommended: TaskArtifact[],
  artifacts: TaskArtifact[]
): string | null {
  const firstMissing = firstMissingArtifact(recommended, artifacts);
  if (!firstMissing) return null;
  const stage = STAGE_DEFS.find((s) => s.key === ARTIFACT_STAGE[firstMissing]);
  return `Рекомендуется также этап ${stage?.label ?? firstMissing}`;
}
