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
// пересчитываются по мере прохождения пайплайна аналитиком. PREPR-4:
// провайдер живёт в layout.tsx и НЕ ремоунтится при клиентской
// навигации, а гидратируется только при F5 и после upload — без явной
// пересинхронизации при монтировании хаба карточки показывали
// устаревший гейтинг (этапы, пройденные в других вкладках, не
// отражались до перезагрузки страницы; та же природа бага, что чинил
// PREPR-3 в «Предобработке»). Монтирование вкладки = refreshSession:
// сервер — источник истины о stages (AppShellContext контракта).
//
// Рост задач (spec_tasks_ia.md §6): новая задача = запись в TASK_ROUTES
// + плейсхолдер-маршрут. Сетка, меню и STAGES не меняются.
//
// v1.1 (spec_tasks_ia_addendum_v1_1.md §9.2): между шапкой и сеткой —
// лента артефактов сессии (TaskArtifactRibbon): аналитик видит реально
// вычисленные факты (датасет, Model Card, прогноз), а не шаг назад в
// информативности после содержательных окон шести этапов. Лента рисует
// только существующие артефакты; свежая сессия — ленты нет вовсе.

import { useEffect } from "react";
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
import { TaskArtifactRibbon } from "./TaskArtifactRibbon";

export function TasksHub() {
  const { stages, refreshSession } = useAppShell();
  const safeStages = stages ?? {};
  const artifacts = artifactsFromStages(safeStages);
  const pipelineStarted = pipelineStartedFromStages(safeStages);

  // PREPR-4: монтирование вкладки = пересинхронизация с сервером.
  // Провайдер (layout) не ремоунтится при клиентской навигации — без
  // этого эффекта stages приходят из контекста с момента F5/upload и
  // карточки показывают устаревший гейтинг до перезагрузки страницы.
  // refreshSession стабилен (useCallback) — эффект выполняется один раз
  // на монтирование, без циклов.
  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

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

      {/* ── Лента артефактов сессии (v1.1 §9.2) ──
          Рисуется ТОЛЬКО из реально существующих артефактов; свежая
          сессия — лента не рендерится вовсе (честная маркировка).
          Чипы без ссылок: счётчики ссылок контракта §4 не меняются. */}
      <TaskArtifactRibbon />

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
