"use client";

// packages/ui/components/TaskCard.tsx
//
// Карточка задачи хаба «Задачи» (spec_tasks_ia.md §4). Визуальная DNA —
// RouteCard (бейдж-карточка главной страницы: rounded-xl, brand-рамка,
// круглая иконка, заголовок text-base, описание text-sm), дополненная
// тремя состояниями гейтинга:
//
//   available — кликабельная ссылка на /tasks/<id> (DNA RouteCard 1:1);
//   awaiting  — некликабельная карточка с amber-плашкой причины
//               («Станет доступна после этапа …»): пайплайн движется,
//               недостающий артефакт создаст обязательный этап;
//   blocked   — некликабельная карточка с нейтральной плашкой
//               («Начните с этапа Загрузка …»): сессия свежая.
//
// Некликабельные состояния сознательно НЕ ссылки: навигация на
// нереализуемую пока задачу — ложный аффорданс. a11y: роль group с
// aria-label, содержащим название задачи и причину.

import Link from "next/link";
import { Lock } from "lucide-react";
import type { TaskRoute, TaskGateState } from "../lib/task-stops";

export interface TaskCardProps {
  task: TaskRoute;
  state: TaskGateState;
  /** Человекочитаемая причина недоступности (null для available). */
  reason: string | null;
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

export function TaskCard({ task, state, reason }: TaskCardProps) {
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
