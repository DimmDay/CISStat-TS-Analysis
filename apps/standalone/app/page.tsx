// apps/standalone/app/page.tsx
//
// Главная страница standalone — две секции:
//   1. HomeHero — исследовательская карта (H1 + 6 маршрутов, Task 24)
//   2. HomeCapabilities — информационная секция «Возможности»
//      (Block A: 4 stat + Block B: 3×2 карточек + Block C: manifesto,
//      Task 27). Только в standalone — в embedded маркетинговый контекст
//      не нужен, пользователь уже внутри портала.
//
// HomeWavesBackground — декоративный фон (мягкие волны, источник —
// CISStat_TS_Analysis_background_wave_1600x1600.svg), тоже только
// standalone по той же причине.
//
// -mt-6 pt-6: <main> в layout.tsx задаёт py-6 -- фон HomeWavesBackground
// (absolute inset-0 этой обёртки) без компенсации начинался бы НИЖЕ
// верхнего меню (ModuleNav), оставляя незакрашенный зазор в py-6 над
// заголовком. -mt-6 сдвигает саму обёртку (и вместе с ней abs-фон)
// вверх ровно на величину padding-top <main>, вплотную к меню;
// компенсирующий pt-6 на той же обёртке возвращает HomeHero/
// HomeCapabilities ровно на прежнюю позицию -- видимый эффект: фон
// доходит до меню, содержимое не сдвигается ни на пиксель. Значения
// -mt-6/pt-6 -- один и тот же токен шкалы Tailwind (1.5rem), поэтому
// компенсация точная, не приближённая. Правка локальна для главной
// страницы -- <main>/layout.tsx не тронуты, остальные вкладки не
// затронуты.

import { HomeHero, HomeCapabilities, HomeWavesBackground, HomeFooter } from "@cisstat/ui";

export default function Page() {
  return (
    <div className="relative isolate -mt-6 pt-6">
      <HomeWavesBackground />
      <div className="relative space-y-12">
        <HomeHero />
        <HomeCapabilities />
        {/* Task w/n (2026-09-12): футер — последний элемент потока.
            Фон главной страницы #CAD7F7 — дефолт компонента (на других
            страницах будет свой цвет пропом). Углы rounded-2xl — по
            паттерну фоновой коробки (HomeWavesBackground). Черта между
            контентом и футером убрана (правка 8 в HomeCapabilities). */}
        <HomeFooter />
      </div>
    </div>
  );
}
