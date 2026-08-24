// apps/standalone/app/navigator/page.tsx
//
// Страница «Навигатор» — бывшая главная (/), переезжает сюда.
// Содержит:
//   - NavigatorHero (H1 + 6 бейджей + Для кого/Для чего + черта)
//   - H2 «Детальная навигация по функционалу платформы» (Task 31, 2026-08-21)
//     — заголовок второй секции, отцентрован, вставлен между чертой
//     NavigatorHero и «Маршрутом исследования» TsAnalysisNavigator.
//   - TsAnalysisNavigator (Маршрут исследования: степпер + этапы + описание + обзор).
//
// Task 31: H1 первой секции (в NavigatorHero) и H2 второй секции — оба
// отцентрованы (text-center), одинаковый стиль шрифта (font-sans text-2xl
// font-normal tracking-tight text-[#1e3a8a]).

import { NavigatorHero, TsAnalysisNavigator } from "@cisstat/ui";

export default function NavigatorPage() {
  return (
    <>
      <NavigatorHero />
      {/* ── Заголовок второй секции (Task 31) ──
          Тот же стиль шрифта, что у H1 в NavigatorHero, плюс text-center.
          mt-8 — отступ от серой черты; mb-4 — компактный отступ до
          «Маршрут исследования» (TsAnalysisNavigator имеет mt-8 сверху). */}
      <h2 className="font-sans text-2xl font-normal tracking-tight text-[#1e3a8a] text-center mt-8 mb-4">
        Детальная навигация по функционалу платформы
      </h2>
      <TsAnalysisNavigator />
    </>
  );
}
