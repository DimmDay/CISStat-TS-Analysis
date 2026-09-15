"use client";

// packages/ui/components/TasksHub.tsx
//
// Хаб «Задачи» (/tasks) — открытая вертикаль задач поверх пайплайна
// (spec_tasks_ia.md §3-4). Заменяет ModulePlaceholder: реестр TASK_ROUTES
// рендерится сеткой карточек (DNA HomeHero/RouteCard), состояние каждой
// задачи выводится из сессии по контракту входа.
//
// Источник сессии — useAppShell().stages (гидратация GET
// /v1/session/current в AppShellProvider): хаб ЖИВОЙ — состояния
// пересчитываются по мере прохождения пайплайна аналитиком, без
// дополнительного бэкенда.
//
// Рост задач (spec_tasks_ia.md §6): новая задача = запись в TASK_ROUTES
// + плейсхолдер-маршрут. Сетка, меню и STAGES не меняются.

import { useAppShell } from "../context/AppShellContext";
import {
  TASK_ROUTES,
  artifactsFromStages,
  pipelineStartedFromStages,
  deriveTaskGateState,
  taskGateReason,
  ctaStageInfo,
  taskRecommendedHint,
} from "../lib/task-stops";
import { TaskCard } from "./TaskCard";

export function TasksHub() {
  const { stages } = useAppShell();
  const safeStages = stages ?? {};
  const artifacts = artifactsFromStages(safeStages);
  const pipelineStarted = pipelineStartedFromStages(safeStages);

  return (
    <div className="space-y-10">
      {/* ── Заголовок + поддерживающий текст ── */}
      <div className="text-center">
        <h1 className="font-sans text-2xl font-semibold tracking-tight text-[#1e3a8a]">
          Задачи
        </h1>
        <p className="mt-3 text-lg text-[#1e3a8a]">
          задачи поверх пайплайна • сценарии • причины • решения • мониторинг
        </p>
      </div>

      {/* ── Сетка карточек задач: гейтинг по контракту входа ──
          Классы сетки идентичны Block B HomeCapabilities / Hero
          HomeHero — единая геометрия карточек платформы. */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 px-6"
        role="list"
        aria-label="Задачи на основе прогноза"
      >
        {TASK_ROUTES.map((task) => {
          const state = deriveTaskGateState(
            task.requires,
            artifacts,
            pipelineStarted
          );
          const reason = taskGateReason(
            task.requires,
            artifacts,
            pipelineStarted
          );
          // R2: подсказка о рекомендуемом (не гейтящем) артефакте.
          const recommendedHint = taskRecommendedHint(
            task.recommendedWith ?? [],
            artifacts
          );
          // R5 + симметрия (follow-up): этап — цель микро-CTA для ОБОИХ
          // некликабельных состояний (awaiting — этап-владелец недостающего
          // артефакта; blocked — вход в пайплайн «Загрузка»). null для available.
          const ctaStage = ctaStageInfo(
            task.requires,
            artifacts,
            pipelineStarted
          );
          return (
            <div role="listitem" key={task.id}>
              <TaskCard
                task={task}
                state={state}
                reason={reason}
                recommendedHint={recommendedHint}
                ctaStage={ctaStage}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
