// apps/standalone/app/tasks/page.tsx
//
// Хаб «Задачи» (spec_tasks_ia.md): плейсхолдер заменён живым хабом.
// Состояния задач выводятся из сессии (AppShellProvider в layout.tsx)
// по контракту входа каждой задачи.
import { TasksHub } from "@cisstat/ui";

export default function Page() {
  return <TasksHub />;
}
