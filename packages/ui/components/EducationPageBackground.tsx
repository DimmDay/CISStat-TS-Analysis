// packages/ui/components/EducationPageBackground.tsx
//
// Фоновая коробка страницы «Обучение и база знаний» /education
// (постановка тимлида 2026-09-21): сплошной фон #EFF6FD по паттерну
// главной страницы. Отрицательная верхняя граница (-mt-6) и контентная
// компенсация (pt-6) живут на обёртке страницы
// (apps/standalone/app/education/page.tsx), здесь — сама коробка.
//
// Цвет — токен --wave-home-2 палитры волн главной, а не литерал:
//   :root = #EFF6FD — байт-точно значение постановки (токен уже жил в
//   globals.css и пин-таблице chartVars.ts как средний стоп градиента
//   волн главной);
//   .dark = #17212C — сертифицированная тёмная ревизия (DKT-CERT):
//   коробка конвертируется в тёмную тему по практике DKT-5 («футер
//   тоже конвертируем») без заведения нового токена — на тёмной
//   странице не всплывает ярким светлым пятном.
// Governance: quoted-hex в графовых/фоновых компонентах запрещён
// (DKT-3), произвольные цветовые классы требуют .dark-ревизии в
// globals.css (DKT-2R) — var() соблюдает оба инварианта.
//
// По паттерну HomeWavesBackground / NavigatorWavesBackground: absolute
// inset-0 внутри relative-обёртки страницы, decorative (aria-hidden,
// pointer-events-none), -z-10 позади контента, углы rounded-2xl.
// Сплошной цвет вместо волн — постановка Education: волны остаются
// визуальным кодом главной и /navigator.
//
// Standalone-only: подключается на уровне страницы /education; embedded
// маршрут и хаб EducationKnowledgeBase не использует — shared-композиция
// не затронута (прецедент фона/футера /navigator).

export function EducationPageBackground() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden rounded-2xl"
      style={{ backgroundColor: "var(--wave-home-2)" }}
    />
  );
}
