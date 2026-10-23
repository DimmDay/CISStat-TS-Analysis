// packages/ui/components/DocumentationWavesBackground.tsx
//
// Декоративный фон страницы «Документы исследования» (/documentation)
// standalone — точечная UI-правка следом за DOCLOG-4. Постановка тимлида:
// «Фон страницы "Документы" = фон страницы "О платформе" (усеченный по
// высоте вариант, отрежь сверху)».
//
// Источник истины — ТОТ ЖЕ авторский файл, что у домашнего фона
// (CISStat_TS_Analysis_background_wave_1600x1600.svg): вся геометрия и
// палитра взяты из HomeWavesBackground БЕЗ приближений — d-строки всех
// path и цвета байт-в-байт равны домашнему компоненту (гард-дифф в
// DocumentationWavesBackground.test.tsx). Палитра — те же токены
// --wave-home-* (globals.css, с тёмной ревизией) — фон визуально тот же,
// что на «О платформе», в обеих темах.
//
// ЕДИНСТВЕННОЕ содержательное отличие — УСЕЧЕНИЕ ПО ВЫСОТЕ СВЕРХУ:
// viewBox="0 800 1600 800" вместо "0 0 1600 1600". Страница «Документы»
// много короче главной; при preserveAspectRatio="none" полный холст
// сплющился бы в низкую коробку и волны потеряли бы высоту. Кроп
// верхней (наиболее пустой) половины композиции оставляет богатый
// волнами нижний срез, который растягивается в коробку страницы с
// визуальной плотностью, близкой к главной (800 единиц среза ≈
// соотношение высоты коробки «Документов» к коробке главной при
// десктопном вьюпорте). Диагональная градиентная подложка непрерывна —
// rect покрывает весь исходный холст, виден его нижний диапазон.
//
// Второе отличие — служебное, по прецеденту HomeWavesBackground/
// NavigatorWavesBackground: id градиентов переименованы с префиксом
// `cisstat-docs-`. SVG id глобальны для DOM-документа; голые id ("bg",
// "w1"...) сталкиваются с другими инлайн-SVG платформы. На видимый
// результат не влияет — цвета/offset'ы/opacity скопированы точно.
//
// Подключается на уровне страницы (apps/standalone/app/documentation/
// page.tsx) по паттерну главной: обёртка relative isolate -mt-6 pt-6,
// фон — первым ребёнком, позади контента. Инлайн SVG, не растр и не
// canvas: фон полностью статичен, без JS-исполнения в рантайме. Только
// standalone — в embedded пользователь уже внутри портала (прецедент
// фона главной). Абсолютно спозиционирован внутри relative-обёртки,
// decorative (aria-hidden, pointer-events-none), не участвует в потоке
// документа и не перехватывает клики.

export function DocumentationWavesBackground() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden rounded-2xl"
    >
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 800 1600 800"
        preserveAspectRatio="none"
        fill="none"
      >
        <defs>
          <linearGradient id="cisstat-docs-bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--wave-home-1)" />
            <stop offset=".5" stopColor="var(--wave-home-2)" />
            <stop offset="1" stopColor="var(--wave-home-3)" />
          </linearGradient>
          <linearGradient id="cisstat-docs-w1">
            <stop stopColor="var(--wave-home-4)" stopOpacity=".72" />
            <stop offset=".55" stopColor="var(--wave-home-5)" stopOpacity=".82" />
            <stop offset="1" stopColor="var(--wave-home-6)" stopOpacity=".68" />
          </linearGradient>
          <linearGradient id="cisstat-docs-w2">
            <stop stopColor="var(--wave-home-7)" stopOpacity=".52" />
            <stop offset=".55" stopColor="var(--wave-home-8)" stopOpacity=".64" />
            <stop offset="1" stopColor="var(--wave-home-9)" stopOpacity=".48" />
          </linearGradient>
          <linearGradient id="cisstat-docs-w3">
            <stop stopColor="var(--wave-home-10)" stopOpacity=".72" />
            <stop offset=".5" stopColor="var(--wave-home-11)" stopOpacity=".62" />
            <stop offset="1" stopColor="var(--wave-home-12)" stopOpacity=".72" />
          </linearGradient>
          <linearGradient id="cisstat-docs-low" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="var(--wave-home-13)" stopOpacity=".55" />
            <stop offset="1" stopColor="var(--wave-home-14)" stopOpacity=".68" />
          </linearGradient>
        </defs>

        {/* Диагональная подложка -- rect на весь холст (виден нижний диапазон) */}
        <rect width="1600" height="1600" fill="url(#cisstat-docs-bg)" />

        {/* Лента 1 + сопровождающий белый штрих-акцент (нижний край в кадре) */}
        <path
          d="M0 500C220 430 430 450 650 565C860 675 1010 785 1200 780C1370 775 1500 700 1600 640V980C1430 1005 1260 1015 1080 960C850 890 700 730 505 680C310 630 145 650 0 710Z"
          fill="url(#cisstat-docs-w1)"
        />
        <path
          d="M0 520C220 450 430 450 650 560C880 675 1035 820 1235 835C1380 846 1505 815 1600 790"
          fill="none"
          stroke="var(--wave-home-stroke)"
          strokeOpacity=".82"
          strokeWidth="3"
        />

        {/* Лента 2 */}
        <path
          d="M0 760C210 710 420 700 625 745C850 795 1010 930 1185 950C1360 970 1490 900 1600 850V1080C1430 1130 1260 1135 1070 1080C875 1023 730 900 530 850C330 800 150 825 0 875Z"
          fill="url(#cisstat-docs-w2)"
        />

        {/* Лента 3 + сопровождающий белый штрих-акцент */}
        <path
          d="M0 1185C220 1115 405 1085 600 1005C825 915 1010 770 1195 650C1360 542 1490 500 1600 470V720C1460 760 1330 810 1190 895C1010 1005 820 1175 615 1285C390 1405 195 1450 0 1490Z"
          fill="url(#cisstat-docs-w3)"
        />
        <path
          d="M0 1495C205 1438 390 1390 610 1270C825 1152 1005 1000 1190 885C1350 786 1475 735 1600 705"
          fill="none"
          stroke="var(--wave-home-stroke)"
          strokeOpacity=".75"
          strokeWidth="3"
        />

        {/* Нижняя лента (low) + сопровождающий белый штрих-акцент */}
        <path
          d="M0 1040C230 1000 400 1020 585 1080C780 1144 910 1260 1100 1305C1290 1350 1450 1290 1600 1210V1600H0Z"
          fill="url(#cisstat-docs-low)"
          opacity=".46"
        />
        <path
          d="M0 1040C230 1000 400 1020 585 1080C780 1144 910 1260 1100 1305C1290 1350 1450 1290 1600 1210"
          fill="none"
          stroke="var(--wave-home-stroke)"
          strokeOpacity=".38"
          strokeWidth="2"
        />
      </svg>
    </div>
  );
}
