"use client";

// packages/ui/hooks/useExpandableChart.ts
//
// Контексты и хуки фичи раскрытия/схлопывания вложенных графиков «Обзора»
// (Task 97, Этап 1; спецификация — spec_max_graf_fix.md в корне репозитория).
//
// Контекст-провайдер инстанцируется ОДИН РАЗ на каждый компонент-Обзор
// (не глобально) — раскрытие в одном Обзоре не влияет на состояние другого.
//
// Правка H (v2): контекст разделён на state- и actions-части.
//   • state-контекст ({ expandedChartId }) — новое значение объектного
//     литерала при каждой смене состояния: перерендериваются только
//     потребители состояния;
//   • actions-контекст — стабильные по ссылке функции (useMemo в
//     ExpandableChartsProvider): кнопки/эффекты, использующие только
//     действия, не перерендериваются при смене раскрытого графика.
// Для 20+ Обзоров с тяжёлыми Recharts-поддеревьями это исключает лавину
// лишних ре-рендеров при каждом expand/collapse.
//
// Инвариант single-expand: в каждый момент раскрыт не более одного графика
// в пределах одного Обзора (expand(id2) при раскрытом id1 неявно схлопывает
// id1); z-index-стек не требуется (см. spec_max_graf_fix.md §4.1, §5.2).

import { createContext, useContext } from "react";

export type ExpandableChartsState = {
  expandedChartId: string | null;
};

export type ExpandableChartsActions = {
  expand: (id: string) => void;
  collapse: () => void;
  toggle: (id: string) => void;
};

export const ExpandableChartsStateContext = createContext<ExpandableChartsState | null>(null);

export const ExpandableChartsActionsContext = createContext<ExpandableChartsActions | null>(null);

export function useExpandableChartState(): ExpandableChartsState {
  const ctx = useContext(ExpandableChartsStateContext);
  if (!ctx) {
    throw new Error("ExpandableChartsProvider is missing above this component");
  }
  return ctx;
}

export function useExpandableChartActions(): ExpandableChartsActions {
  const ctx = useContext(ExpandableChartsActionsContext);
  if (!ctx) {
    throw new Error("ExpandableChartsProvider is missing above this component");
  }
  return ctx;
}
