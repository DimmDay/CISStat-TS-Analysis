"use client";

// packages/ui/components/ExpandableChartPanel.tsx
//
// Обёртка ОДНОГО визуального блока «Обзора», раскрываемая до размера всего
// окна Обзора (Task 97, Этап 1; спецификация — spec_max_graf_fix.md §4.2).
//
// Контракт позиционирования (правка A): корневой контейнер Обзора ОБЯЗАН
// иметь класс relative, иначе absolute inset-0 раскрывшейся панели
// зацепится за позиционированного предка выше Обзора. Требование
// проверяет контрактный тест ExpandableChartCoverage.test.ts; на
// 63b1d7d класс relative есть лишь у 2 из 54 файлов семейства, поэтому
// он добавляется каждому адаптируемому Обзору в его же PR (Этапы 2–4).
//
// Контракт скролла (правка C): пока какой-либо график Обзора раскрыт,
// корень Обзора переключается с overflow-y-auto на overflow-hidden
// (см. интеграционный паттерн в spec_max_graf_fix.md §4.4) — иначе
// absolute inset-0 в скроллимом контейнере привязывается к padding-box
// всего содержимого и раскрытая панель уходит из видимой области.
//
// Фон раскрытой панели — bg-white (правка B): токен --card-bg в проекте
// не существует. Вместо утилиты cn(...) — шаблонные строки (правка E):
// cn в packages/ui отсутствует, весь существующий код использует
// шаблонные строки.
//
// Recharts-график внутри НЕ меняется: ResponsiveContainer height="100%"
// сам подхватывает размер раскрывшегося контейнера (отработанный паттерн
// Task 89). Дозагрузка detail_level=expanded подключается на Этапе 3
// через useChartDetailData + onExpandChange (spec_max_graf_fix.md §6.3).

import { useEffect, type ReactNode } from "react";
import { useExpandableChartActions, useExpandableChartState } from "../hooks/useExpandableChart";
import { ChartExpandToggle } from "./ChartExpandToggle";

export type ExpandableChartPanelProps = {
  /** Уникален и стабилен в пределах одного Обзора. */
  chartId: string;
  /** Опциональный заголовок: показывается в tooltip бейджа. */
  title?: string;
  className?: string;
  /** Сам вложенный график (Recharts и т.п.) — не изменяется. */
  children: ReactNode;
  /** Сигнал «панель стала раскрыта/свёрнута» — триггер дозагрузки §6.3. */
  onExpandChange?: (expanded: boolean) => void;
};

export function ExpandableChartPanel({
  chartId,
  title,
  className,
  children,
  onExpandChange,
}: ExpandableChartPanelProps) {
  const { expandedChartId } = useExpandableChartState();
  const { toggle } = useExpandableChartActions();
  const isExpanded = expandedChartId === chartId;

  useEffect(() => {
    onExpandChange?.(isExpanded);
  }, [isExpanded, onExpandChange]);

  // Esc закрывает раскрытый график (п.5 сценария, §3)
  useEffect(() => {
    if (!isExpanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") toggle(chartId);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isExpanded, toggle, chartId]);

  return (
    <div
      className={`${
        isExpanded
          ? "absolute inset-0 z-20 flex flex-col bg-white"
          : "flex min-h-0 flex-1 flex-col"
      } ${className ?? ""}`}
    >
      <ChartExpandToggle expanded={isExpanded} onClick={() => toggle(chartId)} title={title} />
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}
