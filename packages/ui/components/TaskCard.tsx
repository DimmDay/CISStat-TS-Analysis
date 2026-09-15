"use client";

// packages/ui/components/TaskCard.tsx
//
// Карточка задачи хаба «Задачи» (spec_tasks_ia.md §4). Визуальная DNA —
// RouteCard (бейдж-карточка главной страницы: rounded-xl, brand-рамка,
// круглая иконка, заголовок text-base, описание text-sm), дополненная
// тремя состояниями гейтинга:
//
//   available — кликабельная ссылка на /tasks/<id> (DNA RouteCard 1:1);
//               опционально — плашка-призрак «Рекомендуется также этап …»
//               для рекомендуемых (НЕ гейтящих) артефактов (R2);
//   awaiting  — некликабельная карточка с amber-плашкой причины
//               («Станет доступна после этапа …»): пайплайн движется,
//               недостающий артефакт создаст обязательный этап; плюс
//               микро-CTA «Перейти к этапу …» на этап-владелец (R5);
//   blocked   — некликабельная карточка с нейтральной плашкой
//               («Начните с этапа Загрузка …»): сессия свежая.
//
// Некликабельные состояния сознательно НЕ ссылки на задачу: навигация на
// нереализуемую пока задачу — ложный аффорданс. Микро-CTA (R5) этому
// не противоречит: он ведёт на РЕАЛИЗОВАННЫЙ этап пайплайна и помечен
// явно. a11y: роль group с aria-label, содержащим название задачи и
// причину.

import Link from "next/link";
import { ArrowRight, Lock, Sparkles } from "lucide-react";
import type {
  StagePointer,
  TaskGateState,
  TaskRoute,
} from "../lib/task-stops";

export interface TaskCardProps {
  task: TaskRoute;
  state: TaskGateState;
  /** Человекочитаемая причина недоступности (null для available). */
  reason: string | null;
  /** Подсказка «рекомендуемый, не гейтящий» артефакт (R2; available). */
  recommendedHint?: string | null;
  /** Этап-владелец недостающего артефакта — цель микро-CTA (R5; awaiting). */
  awaitStage?: StagePointer | null;
}

// ── Классы состояния ───────────────────────────────────────────
// available наследует RouteCard: рамка/фон brand, hover-усиление.
// awaiting — amber-тон (токен уже в обиходе платформы: валидация дублей).
// blocked — нейтральный серый.

const SHELL_BY_STATE: Record<TaskGateState, string> = {
  available:
    "border-brand/60 bg-brand-light/60 hover:border-brand/90 hover:bg-brand-light/90",
  awaiting: "border-amber-300 bg-amber-50/60",
  blocked: "border-neutral-200 bg-white",
};

const ICON_BY_STATE: Record<TaskGateState, string> = {
  available:
    "bg-brand-light text-brand group-hover:bg-brand group-hover:text-white",
  awaiting: "bg-amber-100 text-amber-700",
  blocked: "bg-neutral-100 text-neutral-400",
};

const CHIP_BY_STATE: Record<TaskGateState, string> = {
  available: "",
  awaiting: "bg-amber-100/80 text-amber-700",
  blocked: "bg-neutral-100 text-neutral-500",
};

export function TaskCard({
  task,
  state,
  reason,
  recommendedHint,
  awaitStage,
}: TaskCardProps) {
  const Icon = task.icon;
  const available = state === "available";

  const body = (
    <>
      <span
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-colors ${ICON_BY_STATE[state]}`}
        aria-hidden="true"
      >
        <Icon size={20} />
      </span>
      <span className="min-w-0">
        <span
          className={`block text-base font-semibold leading-snug ${
            available ? "text-neutral-900" : "text-neutral-800"
          }`}
        >
          {task.title}
        </span>
        <span className="mt-1 block text-sm text-neutral-500 leading-relaxed">
          {task.description}
        </span>
        {!available && reason && (
          <span
            className={`mt-2 inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${CHIP_BY_STATE[state]}`}
          >
            <Lock size={12} aria-hidden="true" />
            {reason}
          </span>
        )}
        {available && recommendedHint && (
          // Плашка-призрак (R2): рекомендуемый артефакт ещё не создан.
          // НЕ гейтит и НЕ блокирует клик — это совет, не турникет.
          <span
            className="mt-2 inline-flex items-center gap-1 rounded-full border border-dashed border-brand/40 bg-white/70 px-2.5 py-0.5 text-xs font-medium text-brand"
          >
            <Sparkles size={12} aria-hidden="true" />
            {recommendedHint}
          </span>
        )}
        {state === "awaiting" && awaitStage && (
          // Микро-CTA (R5): продолжение паттерна цепочки PRE-1/EDA-1/
          // MODEL-1 внутри хаба — причина сообщает этап, CTA даёт движение.
          <Link
            href={awaitStage.href}
            className="mt-2 flex w-fit items-center gap-1 rounded-sm text-xs font-semibold text-brand hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 focus-visible:ring-offset-2"
          >
            Перейти к этапу {awaitStage.label}
            <ArrowRight size={12} aria-hidden="true" />
          </Link>
        )}
      </span>
    </>
  );

  if (available) {
    return (
      <Link
        href={task.href}
        className={`group flex items-start gap-4 rounded-xl border p-6 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 focus-visible:ring-offset-2 ${SHELL_BY_STATE[state]}`}
      >
        {body}
      </Link>
    );
  }

  return (
    <div
      role="group"
      aria-label={`Задача «${task.title}» недоступна: ${reason ?? ""}`}
      className={`flex items-start gap-4 rounded-xl border p-6 ${SHELL_BY_STATE[state]}`}
    >
      {body}
    </div>
  );
}
