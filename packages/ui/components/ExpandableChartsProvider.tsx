"use client";

// packages/ui/components/ExpandableChartsProvider.tsx
//
// Провайдер состояния раскрытия графиков одного «Обзора» (Task 97, Этап 1;
// спецификация — spec_max_graf_fix.md §4.1).
//
// Монтируется ОДИН РАЗ на каждый компонент-Обзор, оборачивая его содержимое.
// Инвариант single-expand: не более одного раскрытого графика на Обзор.
//
// Сброс состояния при смене контекста (смена датасета/target, переключение
// вкладки представления, размонтирование Обзора) выполняется потребителем
// через collapse() по эффектам инвалидации, уже принятым для профилей
// (Task 90+), — подключение выполняется на Этапах 2–4 роллаута.
//
// Схема split-контекстов (правка H): actions стабильны по ссылке (useMemo),
// state-значение — новый объект при каждой смене. См. useExpandableChart.ts.

import { useMemo, useState, type PropsWithChildren } from "react";
import {
  ExpandableChartsActionsContext,
  ExpandableChartsStateContext,
} from "../hooks/useExpandableChart";

export function ExpandableChartsProvider({ children }: PropsWithChildren) {
  const [expandedChartId, setExpandedChartId] = useState<string | null>(null);

  const actions = useMemo(
    () => ({
      expand: (id: string) => setExpandedChartId(id),
      collapse: () => setExpandedChartId(null),
      toggle: (id: string) => setExpandedChartId((prev) => (prev === id ? null : id)),
    }),
    []
  );

  return (
    <ExpandableChartsActionsContext.Provider value={actions}>
      <ExpandableChartsStateContext.Provider value={{ expandedChartId }}>
        {children}
      </ExpandableChartsStateContext.Provider>
    </ExpandableChartsActionsContext.Provider>
  );
}
