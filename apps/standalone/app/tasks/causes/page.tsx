// apps/standalone/app/tasks/causes/page.tsx
//
// Вертикальный срез задачи «Причины» (XAI) — v2 первого среза задач
// (spec_tasks_ia_addendum_v1_1.md §10/§10.1). Плейсхолдер §7 заменён
// живой страницей паттерна C (§11.2): методы → факторы → деталь.
// Сессия — AppShellProvider в layout.tsx (общая с хабом).
import { TasksCauses } from "@cisstat/ui";

export default function Page() {
  return <TasksCauses />;
}
