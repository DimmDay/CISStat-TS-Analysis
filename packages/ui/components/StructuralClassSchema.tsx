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
// UPLOAD-RECOMP-2 (2026-10-20), пункт (б) + дополнение тимлида: схема
// переписана с блочного списка на КОМПАКТНУЮ ТАБЛИЦУ:
//   | Признаки (условие) | Класс | Определение | Решаемые задачи |
//   * «Определение» -- русскоязычные определения классов из ЕДИНОГО
//     источника RU_DEFINITION (structuralClass.ts);
//   * «Решаемые задачи» (дополнение постановки) -- перечень задач,
//     решаемых платформой на данных класса, из единого источника
//     RU_TASKS (структура схемы и подсветка сохранены; высота блока
//     сокращена: text-xs, строки py-1.5).
//
// Статична по структуре (сами правила не меняются), но подсветка --
// динамическая, реагирует на реальный результат classifyStructure().

import { Check } from "lucide-react";
import type { StructuralClass } from "../lib/structuralClass";
import { RU_DEFINITION, RU_TASKS } from "../lib/structuralClass";

interface Rule {
  ids: StructuralClass[]; // строка подсвечивается, если activeClassId входит в этот список
  condition: string;
  result: string;
  // Представитель строки для чтения RU_DEFINITION/RU_TASKS (единый
  // источник): для панели без уточнения -- panel_unknown.
  ruRef: StructuralClass;
  sub?: { id: StructuralClass; condition: string; result: string }[];
}

const RULES: Rule[] = [
  { ids: ["cross_sectional"], condition: "Нет даты И нет группировки", result: "Cross-Sectional", ruRef: "cross_sectional" },
  { ids: ["univariate_ts"], condition: "Есть дата, ОДНА числовая колонка, нет группировки", result: "Univariate TS", ruRef: "univariate_ts" },
  { ids: ["multivariate_ts"], condition: "Есть дата, МНОГО числовых колонок, нет группировки", result: "Multivariate TS", ruRef: "multivariate_ts" },
  {
    ids: ["panel_balanced", "panel_unbalanced", "panel_unknown"],
    condition: "Есть дата И есть группирующая колонка",
    result: "Panel Data",
    ruRef: "panel_unknown",
    sub: [
      { id: "panel_balanced", condition: "у всех групп одинаковый набор дат", result: "Balanced" },
      { id: "panel_unbalanced", condition: "иначе", result: "Unbalanced" },
    ],
  },
  { ids: ["spatio_temporal"], condition: "Есть колонки координат (lat/long) + дата", result: "Spatio-Temporal", ruRef: "spatio_temporal" },
  { ids: ["hierarchical"], condition: "Обнаружена вложенная иерархия (страна → регион → …)", result: "Hierarchical", ruRef: "hierarchical" },
  {
    ids: ["event_ts"],
    condition: "Timestamp + категориальная «событие»/«действие», нерегулярный шаг, нет содержательных числовых рядов",
    result: "Event Time Series",
    ruRef: "event_ts",
  },
];

function TasksCell({ tasks }: { tasks: readonly string[] }) {
  return (
    <ul className="list-disc pl-3.5 space-y-0.5 marker:text-neutral-300" data-testid="row-tasks">
      {tasks.map((task) => (
        <li key={task} className="text-neutral-600">
          {task}
        </li>
      ))}
    </ul>
  );
}

function RuleRow({
  active,
  condition,
  result,
  ruRef,
  indent,
}: {
  active: boolean;
  condition: string;
  result: string;
  ruRef: StructuralClass;
  indent?: boolean;
}) {
  return (
    <tr
      data-testid="structural-class-row"
      data-sub={indent ? "true" : undefined}
      className={`align-top transition-colors ${active ? "bg-brand-light" : ""} ${indent ? "border-l-2 border-dashed border-neutral-200" : "border-t border-neutral-100"}`}
    >
      <td className={`px-3 py-1.5 ${active ? "text-neutral-900 font-medium" : "text-neutral-600"}`}>
        <div className="flex items-start gap-1.5">
          {active && <Check size={14} className="text-brand shrink-0 mt-0.5" aria-hidden="true" />}
          <span>{condition}</span>
        </div>
      </td>
      <td className="px-3 py-1.5">
        <span
          className={`inline-block rounded px-2 py-0.5 text-xs font-semibold ${
            active ? "bg-brand text-white" : "bg-neutral-100 text-neutral-600"
          }`}
        >
          {result}
        </span>
      </td>
      <td className={`px-3 py-1.5 ${active ? "text-neutral-800" : "text-neutral-600"}`}>{RU_DEFINITION[ruRef]}</td>
      <td className="px-3 py-1.5">
        <TasksCell tasks={RU_TASKS[ruRef]} />
      </td>
    </tr>
  );
}

export function StructuralClassSchema({ activeClassId }: { activeClassId: StructuralClass | null }) {
  const rows: React.ReactNode[] = [];
  for (const rule of RULES) {
    const isActive = !!activeClassId && rule.ids.includes(activeClassId);
    rows.push(
      <RuleRow
        key={rule.result}
        active={isActive && !rule.sub}
        condition={rule.condition}
        result={rule.result}
        ruRef={rule.ruRef}
      />,
    );
    if (rule.sub) {
      for (const s of rule.sub) {
        rows.push(
          <RuleRow key={s.id} active={activeClassId === s.id} condition={s.condition} result={s.result} ruRef={s.id} indent />,
        );
      }
    }
  }

  return (
    <div className="border border-neutral-200 rounded-lg p-4 bg-white">
      <h4 className="text-sm font-semibold text-neutral-800 mb-1">Определение структуры данных</h4>
      <p className="text-xs text-neutral-500 mb-3">
        Справочная схема — как платформа относит датасет к одному из классов. Совпадение с вашим датасетом подсвечено.
      </p>
      <table className="w-full text-xs" data-testid="structural-class-table">
        <thead>
          <tr className="text-left text-neutral-500" data-testid="structural-class-table-header">
            <th className="px-3 py-1.5 font-medium w-[34%]">Признаки (условие)</th>
            <th className="px-3 py-1.5 font-medium">Класс</th>
            <th className="px-3 py-1.5 font-medium w-[22%]">Определение</th>
            <th className="px-3 py-1.5 font-medium w-[32%]">Решаемые задачи</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  );
}
