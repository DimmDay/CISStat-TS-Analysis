// apps/embedded/app/navigator/page.tsx
//
// Страница «Навигатор» — бывшая главная (/), переезжает сюда.
// Содержит NavigatorHero (H1 + 6 бейджей + Для кого/Для чего) и
// TsAnalysisNavigator (Маршрут исследования: степпер + этапы + описание + обзор).

import { NavigatorHero, TsAnalysisNavigator } from "@cisstat/ui";

export default function NavigatorPage() {
  return (
    <>
      <NavigatorHero />
      <TsAnalysisNavigator />
    </>
  );
}