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
//
// Постановка тимлида (2026-09-21): фон #EFF6FD и футер — по паттерну
// главной страницы (apps/standalone/app/page.tsx; прецедент подключения —
// /navigator, apps/standalone/app/navigator/page.tsx):
//
// -mt-6 pt-6: <main> в layout.tsx задаёт py-6 — фон EducationPageBackground
// (absolute inset-0 этой обёртки) без компенсации начинался бы НИЖЕ
// верхнего меню (ModuleNav), оставляя незакрашенный зазор в py-6 над
// заголовком. -mt-6 сдвигает саму обёртку (и вместе с ней abs-фон)
// вверх ровно на величину padding-top <main>, вплотную к меню;
// компенсирующий pt-6 на той же обёртке возвращает EducationKnowledgeBase
// и футер ровно на прежнюю позицию — видимый эффект: фон доходит до меню,
// содержимое не сдвигается ни на пиксель. Значения -mt-6/pt-6 — один и
// тот же токен шкалы Tailwind (1.5rem), поэтому компенсация точная, не
// приближённая. isolate удерживает -z-10 фона внутри обёртки.
//
// EducationPageBackground — сплошной фон #EFF6FD: токен --wave-home-2
// палитры волн главной (светлый #EFF6FD байт-точно; сертифицированная
// тёмная ревизия #17212C, DKT-CERT), углы rounded-2xl по паттерну
// фоновой коробки главной. Сплошной цвет вместо волн — постановка:
// волны остаются визуальным кодом главной и /navigator.
//
// HomeFooter — последний элемент потока контента; фон — тематический
// токен компонента (светлая #CAD7F7 — тот же, что на главной и
// /navigator; DKT-5: тёмная ревизия #171D2C), углы rounded-2xl.
//
// Страница standalone-only: embedded маршрут и хаб не использует,
// shared-композиция EducationKnowledgeBase не менялась.

import { EducationKnowledgeBase, EducationPageBackground, HomeFooter } from "@cisstat/ui";

export default function EducationPage() {
  return (
    <div className="relative isolate -mt-6 pt-6">
      <EducationPageBackground />
      <div className="relative space-y-12">
        <EducationKnowledgeBase />
        <HomeFooter />
      </div>
    </div>
  );
}
