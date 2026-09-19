// apps/standalone/app/education/page.tsx
//
// Страница «Обучение и база знаний» (/education) — второй бейдж первого
// ряда главной страницы (HOME_ROUTES[1], Task EDU-1). Включает Библиотеку
// для чтения и Словарь терминов; база знаний — единый источник истины
// по методологии для всей платформы (spec_education.md, Часть I).
//
// Композиция хаба живёт в @cisstat/ui (EducationKnowledgeBase), чтобы
// standalone и embedded использовали одинаковый контур базы знаний;
// маршрут — standalone-only, по паттерну хаба «Задачи»
// (apps/standalone/app/tasks/page.tsx): провайдеры уже в layout.tsx.

import { EducationKnowledgeBase } from "@cisstat/ui";

export default function EducationPage() {
  return <EducationKnowledgeBase />;
}
