"use client";

// packages/ui/components/StatusIcon.tsx
//
// Иконки статуса проверки -- тонкие векторные Lucide (без раскрашенного
// фона), как требует единая стиль-система портала. Цвет наследуется от
// currentColor -- родительский элемент задаёт text-* класс.

import { CheckCircle, AlertTriangle, Circle, CircleMinus, type LucideIcon } from "lucide-react";

export type CheckStatus = "done" | "warning" | "pending" | "skipped";

const STATUS_ICON: Record<CheckStatus, LucideIcon> = {
  done: CheckCircle,
  warning: AlertTriangle,
  pending: Circle,
  skipped: CircleMinus,
};

const STATUS_COLOR: Record<CheckStatus, string> = {
  done: "text-green-600",
  warning: "text-amber-600",
  pending: "text-neutral-400",
  skipped: "text-neutral-400",
};

export function StatusIcon({
  status,
  size = 16,
  className = "",
}: {
  status: CheckStatus;
  size?: number;
  className?: string;
}) {
  const Icon = STATUS_ICON[status];
  return <Icon size={size} aria-hidden="true" className={`${STATUS_COLOR[status]} ${className}`} />;
}

export { STATUS_ICON };
