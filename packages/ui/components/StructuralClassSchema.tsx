// packages/ui/components/StructuralClassSchema.tsx
//
// Визуальная справочная схема "ОПРЕДЕЛЕНИЕ СТРУКТУРЫ ДАННЫХ" -- дерево
// решений, по которому платформа относит датасет к одному из 9 классов
// (packages/ui/lib/structuralClass.ts). Показывается на остановке
// «Структура» вкладки «Загрузка» -- справочная информация для аналитика,
// объясняющая логику алгоритма (по просьбе тимлида в чате), не просто
// декоративная картинка: строка, совпадающая с текущим датасетом,
// подсвечивается через activeClassId.
//
// Статична по структуре (сами правила не меняются), но подсветка --
// динамическая, реагирует на реальный результат classifyStructure().

import { Check } from "lucide-react";
import type { StructuralClass } from "../lib/structuralClass";

interface Rule {
  ids: StructuralClass[]; // строка подсвечивается, если activeClassId входит в этот список
  condition: string;
  result: string;
  sub?: { id: StructuralClass; condition: string; result: string }[];
}

const RULES: Rule[] = [
  { ids: ["cross_sectional"], condition: "Нет даты И нет группировки", result: "Cross-Sectional" },
  { ids: ["univariate_ts"], condition: "Есть дата, ОДНА числовая колонка, нет группировки", result: "Univariate TS" },
  { ids: ["multivariate_ts"], condition: "Есть дата, МНОГО числовых колонок, нет группировки", result: "Multivariate TS" },
  {
    ids: ["panel_balanced", "panel_unbalanced", "panel_unknown"],
    condition: "Есть дата И есть группирующая колонка",
    result: "Panel Data",
    sub: [
      { id: "panel_balanced", condition: "у всех групп одинаковый набор дат", result: "Balanced" },
      { id: "panel_unbalanced", condition: "иначе", result: "Unbalanced" },
    ],
  },
  { ids: ["spatio_temporal"], condition: "Есть колонки координат (lat/long) + дата", result: "Spatio-Temporal" },
  { ids: ["hierarchical"], condition: "Обнаружена вложенная иерархия (страна → регион → …)", result: "Hierarchical" },
  {
    ids: ["event_ts"],
    condition: "Timestamp + категориальная «событие»/«действие», нерегулярный шаг, нет содержательных числовых рядов",
    result: "Event Time Series",
  },
];

function RuleRow({ active, condition, result, indent }: { active: boolean; condition: string; result: string; indent?: boolean }) {
  return (
    <div
      className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
        active ? "bg-brand-light border border-brand/40" : "border border-transparent"
      } ${indent ? "ml-6" : ""}`}
    >
      {active && <Check size={14} className="text-brand shrink-0" aria-hidden="true" />}
      <span className={`flex-1 min-w-0 ${active ? "text-neutral-900 font-medium" : "text-neutral-600"}`}>{condition}</span>
      <span className="text-neutral-300 shrink-0">→</span>
      <span
        className={`shrink-0 rounded px-2 py-0.5 text-xs font-semibold ${
          active ? "bg-brand text-white" : "bg-neutral-100 text-neutral-600"
        }`}
      >
        {result}
      </span>
    </div>
  );
}

export function StructuralClassSchema({ activeClassId }: { activeClassId: StructuralClass | null }) {
  return (
    <div className="border border-neutral-200 rounded-lg p-4 bg-white">
      <h4 className="text-sm font-semibold text-neutral-800 mb-1">Определение структуры данных</h4>
      <p className="text-xs text-neutral-500 mb-3">
        Справочная схема — как платформа относит датасет к одному из классов. Совпадение с вашим датасетом подсвечено.
      </p>
      <div className="flex flex-col gap-1">
        {RULES.map((rule) => {
          const isActive = !!activeClassId && rule.ids.includes(activeClassId);
          return (
            <div key={rule.result}>
              <RuleRow active={isActive && !rule.sub} condition={rule.condition} result={rule.result} />
              {rule.sub && (
                <div className="flex flex-col gap-1 mt-1 border-l-2 border-dashed border-neutral-200 ml-3">
                  {rule.sub.map((s) => (
                    <RuleRow key={s.id} active={activeClassId === s.id} condition={s.condition} result={s.result} indent />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
