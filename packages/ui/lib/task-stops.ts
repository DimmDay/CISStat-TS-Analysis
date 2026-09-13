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
  },
  {
    id: "causes",
    title: "Причины",
    description: "драйверы и атрибуция: SHAP, IRF/FEVD, тест Грейнджера",
    icon: SearchCheck,
    href: "/tasks/causes",
    requires: ["model_card"],
  },
  {
    id: "decisions",
    title: "Принятие решений",
    description: "решения по прогнозным значениям: пороги, правила, iDSS",
    icon: Scale,
    href: "/tasks/decisions",
    requires: ["forecast_run"],
  },
  {
    id: "monitoring",
    title: "Мониторинг прогноза",
    description: "факт против прогноза: дрифт, алерты, триггер переобучения",
    icon: Radar,
    href: "/tasks/monitoring",
    requires: ["forecast_run"],
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

  // awaiting: первый недостающий артефакт в порядке пайплайна.
  const order: TaskArtifact[] = ["validated", "model_card", "forecast_run"];
  const firstMissing = requires
    .filter((r) => !artifacts.includes(r))
    .sort((a, b) => order.indexOf(a) - order.indexOf(b))[0];
  const stageKey = ARTIFACT_STAGE[firstMissing];
  const stage = STAGE_DEFS.find((s) => s.key === stageKey);
  return `Станет доступна после этапа ${stage?.label ?? stageKey}`;
}
