"use client";

// packages/ui/components/StatusIcon.tsx
//
// Иконки статуса проверки -- тонкие векторные Lucide (без раскрашенного
// фона), как требует единая стиль-система портала. Цвет наследуется от
// currentColor -- родительский элемент задаёт text-* класс.
//
// Объединено из двух параллельных расширений:
// -- Task 47 (модуль «Валидация»): режимы auto/enabled/disabled ->
//    добавили нейтральный "skipped" (не применимо ИЛИ отключено аналитиком
//    -- разбор конкретной причины передаётся отдельно через statusReason
//    у потребителя, не через отдельный статус иконки).
// -- Остановка «Пропуски» (модуль «Предобработка»): добавили "running" и
//    "error" -- сетевой жизненный цикл запроса (нет прямого аналога в
//    Validation, где загрузка/ошибка выражались отдельными булевыми
//    флагами в JSX, а не значением CheckStatus).
// Итоговый набор -- объединение обоих, без потери значений; done/warning/
// pending сохраняют прежний смысл у всех существующих потребителей.
import { CheckCircle, AlertTriangle, Circle, CircleMinus, Loader2, XCircle, type LucideIcon } from "lucide-react";

export type CheckStatus = "done" | "warning" | "pending" | "skipped" | "running" | "error";

const STATUS_ICON: Record<CheckStatus, LucideIcon> = {
  done: CheckCircle,
  warning: AlertTriangle,
  pending: Circle,
  skipped: CircleMinus,
  running: Loader2,
  error: XCircle,
};

const STATUS_COLOR: Record<CheckStatus, string> = {
  done: "text-green-600",
  warning: "text-amber-600",
  pending: "text-neutral-400",
  skipped: "text-neutral-400",
  running: "text-brand",
  error: "text-red-600",
};

// Человекочитаемые подписи для aria-label -- нужны там, где иконка стоит
// без сопроводительного текста (например, степпер слева).
export const STATUS_LABEL: Record<CheckStatus, string> = {
  done: "Пройдено",
  warning: "Найдены проблемы",
  pending: "Не запускалось",
  skipped: "Не требуется",
  running: "Выполняется",
  error: "Ошибка",
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
  const spin = status === "running" ? "animate-spin" : "";
  return (
    <Icon
      size={size}
      role="img"
      aria-label={STATUS_LABEL[status]}
      className={`${STATUS_COLOR[status]} ${spin} ${className}`}
    />
  );
}

export { STATUS_ICON };
