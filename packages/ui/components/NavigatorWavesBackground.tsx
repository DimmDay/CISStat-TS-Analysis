// packages/ui/components/NavigatorWavesBackground.tsx
//
// Декоративный фон страницы «Знакомство с платформой» (/navigator)
// standalone. Источник истины — авторский файл
// CISStat_TS_Analysis_wave_background_3200x1600.svg (холст 1600×3200,
// вертикальная композиция под длинную страницу): вся геометрия и
// палитра (rect-подложка с диагональным градиентом + 4 полупрозрачные
// «ленты» + нижняя мягкая ширма + 3 тонких белых штриха-акцента)
// перенесены в JSX БЕЗ приближений — path d="...", цвета, offset'ы,
// stop-opacity, stroke-width и opacity скопированы из SVG дословно.
// Программная сверка переноса с источником —
// scripts/task_navbg_verify_transfer.py; тест-гард точных d-строк —
// NavigatorWavesBackground.test.tsx.
//
// Два сознательных презентационных отличия от исходного файла — оба по
// прецеденту HomeWavesBackground:
//   1) id градиентов (`bg`, `waveA`...`lower` в источнике) переименованы
//      с префиксом `cisstat-nav-`. SVG id глобальны для всего
//      DOM-документа; голые id вроде "bg" почти гарантированно
//      столкнутся с другим инлайн-SVG на странице (на платформе их
//      много — иконки, графики Recharts, фон главной), что привело бы
//      к непредсказуемому наложению градиентов. На видимый результат
//      не влияет — цвета/offset'ы/opacity скопированы точно.
//   2) preserveAspectRatio="none" вместо "xMidYMid slice" источника:
//      фон абсолютно спозиционирован (absolute inset-0) и обязан
//      заполнять фактическую коробку страницы целиком — мягкие волны
//      допускают растяжение, а slice обрезал бы композицию по краям.
//      Паттерн тот же, что у HomeWavesBackground (ViewBox 1600×1600,
//      растянутый на коробку главной).
//
// Подключается на уровне страницы (apps/standalone/app/navigator/page.tsx)
// по паттерну главной: обёртка relative isolate -mt-6 pt-6, фон — первым
// ребёнком, позади контента. Инлайн SVG, не растр и не canvas: фон
// полностью статичен, без JS-исполнения в рантайме. Только standalone —
// в embedded пользователь уже внутри портала (прецедент фона главной).
//
// Абсолютно спозиционирован внутри relative-обёртки страницы,
// decorative (aria-hidden, pointer-events-none), не участвует в потоке
// документа и не перехватывает клики.

export function NavigatorWavesBackground() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden rounded-2xl"
    >
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 1600 3200"
        preserveAspectRatio="none"
        fill="none"
      >
        <defs>
          <linearGradient id="cisstat-nav-bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--wave-nav-1)" />
            <stop offset="0.48" stopColor="var(--wave-nav-2)" />
            <stop offset="1" stopColor="var(--wave-nav-3)" />
          </linearGradient>
          <linearGradient id="cisstat-nav-waveA" x1="0" y1="0" x2="1" y2="0.2">
            <stop offset="0" stopColor="var(--wave-nav-4)" stopOpacity=".68" />
            <stop offset=".48" stopColor="var(--wave-nav-5)" stopOpacity=".76" />
            <stop offset="1" stopColor="var(--wave-nav-6)" stopOpacity=".62" />
          </linearGradient>
          <linearGradient id="cisstat-nav-waveB" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="var(--wave-nav-7)" stopOpacity=".48" />
            <stop offset=".52" stopColor="var(--wave-nav-8)" stopOpacity=".66" />
            <stop offset="1" stopColor="var(--wave-nav-9)" stopOpacity=".54" />
          </linearGradient>
          <linearGradient id="cisstat-nav-waveC" x1="0" y1="0" x2="1" y2="0.2">
            <stop offset="0" stopColor="var(--wave-nav-10)" stopOpacity=".72" />
            <stop offset=".5" stopColor="var(--wave-nav-11)" stopOpacity=".64" />
            <stop offset="1" stopColor="var(--wave-nav-12)" stopOpacity=".72" />
          </linearGradient>
          <linearGradient id="cisstat-nav-waveD" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="var(--wave-nav-13)" stopOpacity=".42" />
            <stop offset=".5" stopColor="var(--wave-nav-14)" stopOpacity=".58" />
            <stop offset="1" stopColor="var(--wave-nav-15)" stopOpacity=".48" />
          </linearGradient>
          <linearGradient id="cisstat-nav-lower" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--wave-nav-16)" stopOpacity=".52" />
            <stop offset="1" stopColor="var(--wave-nav-17)" stopOpacity=".62" />
          </linearGradient>
        </defs>

        {/* Базовая пастельная подложка -- rect на весь холст */}
        <rect width="1600" height="3200" fill="url(#cisstat-nav-bg)" />

        {/* Верхняя диагональная лента + сопровождающий белый штрих-акцент */}
        <path
          d="M0 1050 C210 930 390 920 590 1030 C790 1140 900 1260 1060 1160 C1250 1040 1400 820 1600 760 L1600 1450 C1390 1500 1210 1430 1040 1320 C870 1210 750 1110 580 1060 C380 1000 190 1050 0 1150 Z"
          fill="url(#cisstat-nav-waveA)"
        />
        <path
          d="M0 1050 C210 930 390 920 590 1030 C790 1140 900 1260 1060 1160 C1250 1040 1400 820 1600 760"
          fill="none"
          stroke="var(--wave-nav-18)"
          strokeOpacity=".80"
          strokeWidth="3"
        />

        {/* Центральная пересекающая лента */}
        <path
          d="M0 1420 C230 1300 420 1270 620 1330 C850 1400 1010 1530 1190 1510 C1350 1492 1470 1410 1600 1370 L1600 1770 C1410 1810 1240 1850 1060 1780 C850 1700 720 1510 540 1460 C350 1410 170 1450 0 1540 Z"
          fill="url(#cisstat-nav-waveB)"
        />

        {/* Длинная восходящая полупрозрачная лента */}
        <path
          d="M0 1750 C230 1660 430 1580 620 1470 C830 1345 990 1180 1160 1030 C1320 890 1450 810 1600 760 L1600 1160 C1450 1210 1310 1300 1160 1430 C970 1590 810 1770 600 1880 C390 1990 190 2020 0 2090 Z"
          fill="url(#cisstat-nav-waveC)"
        />
        {/* Тонкий диагональный штрих-акцент */}
        <path
          d="M0 2090 C190 2020 390 1990 600 1880 C810 1770 970 1590 1160 1430 C1310 1300 1450 1210 1600 1160"
          fill="none"
          stroke="var(--wave-nav-19)"
          strokeOpacity=".68"
          strokeWidth="3"
        />

        {/* Нижняя группа волн + сопровождающий белый штрих-акцент */}
        <path
          d="M0 2210 C220 2100 420 2110 620 2210 C800 2300 930 2460 1100 2440 C1280 2418 1430 2240 1600 2160 L1600 2600 C1430 2690 1260 2750 1080 2700 C870 2640 760 2470 570 2390 C370 2310 180 2340 0 2430 Z"
          fill="url(#cisstat-nav-waveD)"
        />
        <path
          d="M0 2210 C220 2100 420 2110 620 2210 C800 2300 930 2460 1100 2440 C1280 2418 1430 2240 1600 2160"
          fill="none"
          stroke="var(--wave-nav-20)"
          strokeOpacity=".78"
          strokeWidth="3"
        />

        {/* Мягкая вторичная нижняя лента */}
        <path
          d="M0 2460 C210 2380 420 2390 600 2460 C790 2535 910 2680 1090 2700 C1280 2720 1450 2630 1600 2530 L1600 2890 C1430 2980 1260 3010 1070 2940 C870 2870 720 2730 530 2670 C340 2610 160 2650 0 2730 Z"
          fill="url(#cisstat-nav-waveC)"
          opacity=".58"
        />

        {/* Финальная широкая нижняя ширма */}
        <path
          d="M0 2770 C250 2670 450 2680 650 2760 C850 2840 980 2990 1160 3020 C1320 3045 1470 2970 1600 2890 L1600 3200 L0 3200 Z"
          fill="url(#cisstat-nav-lower)"
          opacity=".52"
        />
      </svg>
    </div>
  );
}
