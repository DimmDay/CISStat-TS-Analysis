// apps/standalone/app/navigator/page.tsx
//
// Страница «Знакомство с платформой». Общая композиция живёт в @cisstat/ui,
// чтобы standalone и embedded использовали одинаковые секции и якоря.
//
// NavigatorWavesBackground + HomeFooter — декоративный фон и футер ТОЛЬКО
// standalone, подключены на уровне страницы по паттерну главной
// (apps/standalone/app/page.tsx): shared-композиция PlatformIntroduction
// не затронута, embedded не менялся.
//
// -mt-6 pt-6: <main> в layout.tsx задаёт py-6 — фон NavigatorWavesBackground
// (absolute inset-0 этой обёртки) без компенсации начинался бы НИЖЕ
// верхнего меню (ModuleNav), оставляя незакрашенный зазор в py-6 над
// заголовком. -mt-6 сдвигает саму обёртку (и вместе с ней abs-фон)
// вверх ровно на величину padding-top <main>, вплотную к меню;
// компенсирующий pt-6 на той же обёртке возвращает содержимое ровно на
// прежнюю позицию — видимый эффект: фон доходит до меню, содержимое не
// сдвигается ни на пиксель. Значения -mt-6/pt-6 — один и тот же токен
// шкалы Tailwind (1.5rem), поэтому компенсация точная, не приближённая.
// Фоновая коробка — rounded-2xl (скруглённые углы по паттерну главной);
// isolate удерживает -z-10 фона внутри обёртки.
//
// Футер — последний элемент потока контента; фон #CAD7F7 — дефолт
// HomeFooter (тот же, что на главной — «в полном соответствии с главной
// страницей»); углы rounded-2xl по паттерну фоновой коробки.

import { NavigatorWavesBackground, PlatformIntroduction, HomeFooter } from "@cisstat/ui";

export default function NavigatorPage() {
  return (
    <div className="relative isolate -mt-6 pt-6">
      <NavigatorWavesBackground />
      <div className="relative space-y-12">
        <PlatformIntroduction />
        <HomeFooter />
      </div>
    </div>
  );
}
