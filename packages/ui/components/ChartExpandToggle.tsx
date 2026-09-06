"use client";

// packages/ui/components/ChartExpandToggle.tsx
//
// Иконка-бейдж «развернуть/свернуть график» (Task 97, Этап 1;
// спецификация — spec_max_graf_fix.md §4.3).
//
// Стиль — фактический стиль круглых бейджей проекта (правка B):
// rounded-full bg-neutral-100, hover:bg-neutral-200, focus-visible ринг
// ring-neutral-400 — как у переключателей представлений Обзоров
// (см. PreprocessingSpectralOverview.tsx). CSS-переменные --badge-*
// из v1 спеки не используются — таких токенов в проекте нет.
//
// Доступность: aria-label меняется по состоянию; aria-expanded отражает
// состояние раскрытия (правка I); активация Enter/Space — нативное
// поведение <button>; Esc обрабатывается в ExpandableChartPanel.
//
// Иконки — lucide-react (уже в зависимостях packages/ui): Maximize2/
// Minimize2 — семантически однозначная симметричная пара «эту же иконку
// раскрывает и схлопывает», без ассоциаций с «крестиком закрытия».

import { Maximize2, Minimize2 } from "lucide-react";

export type ChartExpandToggleProps = {
  expanded: boolean;
  onClick: () => void;
  title?: string;
};

export const CHART_EXPAND_LABEL_COLLAPSED = "Развернуть график до размера окна Обзора";
export const CHART_EXPAND_LABEL_EXPANDED = "Свернуть график";

export function ChartExpandToggle({ expanded, onClick, title }: ChartExpandToggleProps) {
  const label = expanded ? CHART_EXPAND_LABEL_EXPANDED : CHART_EXPAND_LABEL_COLLAPSED;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-expanded={expanded}
      title={title ?? label}
      className={
        "absolute right-2 top-2 z-30 flex h-7 w-7 items-center justify-center " +
        "rounded-full bg-neutral-100 text-neutral-600 hover:bg-neutral-200 " +
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 " +
        "transition-colors"
      }
    >
      {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
    </button>
  );
}
