// packages/ui/components/HomeWavesBackground.tsx
//
// Декоративный фон главной страницы standalone. Источник истины —
// авторский файл CISStat_TS_Analysis_background_wave_1600x1600.svg
// (1600×1600): вся геометрия и палитра (rect-подложка с диагональным
// градиентом + 4 полупрозрачные "ленты" + 2 тонких белых штриха-акцента
// поверх них) перенесены в JSX БЕЗ приближений -- в отличие от предыдущей
// версии этого компонента, которая реконструировала форму волн по
// скриншоту-макету (K-means по пикселям), здесь есть оригинальный файл,
// поэтому реконструкция не нужна: path d="..." и цвета взяты из SVG
// дословно.
//
// Единственное сознательное отличие от исходного файла -- id
// градиентов (`bg`, `w1`, `w2`, `w3`, `low` в источнике) переименованы с
// префиксом `cisstat-home-`. SVG id глобальны для всего DOM-документа;
// голые id вроде "bg"/"w1" почти гарантированно столкнутся с другим
// инлайн-SVG где-то ещё на странице (на платформе их уже много --
// иконки, графики Recharts, декоративные примитивы), что привело бы к
// непредсказуемому наложению градиентов. На видимый результат это не
// влияет -- цвета, offset'ы и opacity скопированы точно.
//
// Инлайн SVG, не растровое изображение и не canvas: фон полностью
// статичен, инлайн SVG не тяжелее растра для такого размера и не
// требует JS-исполнения в рантайме.
//
// Абсолютно спозиционирован внутри relative-обёртки страницы,
// decorative (aria-hidden, pointer-events-none), не участвует в потоке
// документа и не перехватывает клики.

export function HomeWavesBackground() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden rounded-2xl"
    >
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 1600 1600"
        preserveAspectRatio="none"
        fill="none"
      >
        <defs>
          <linearGradient id="cisstat-home-bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#F8FCFF" />
            <stop offset=".5" stopColor="#EFF6FD" />
            <stop offset="1" stopColor="#E9EEFF" />
          </linearGradient>
          <linearGradient id="cisstat-home-w1">
            <stop stopColor="#DCEBFA" stopOpacity=".72" />
            <stop offset=".55" stopColor="#D4E3FA" stopOpacity=".82" />
            <stop offset="1" stopColor="#D8E0FA" stopOpacity=".68" />
          </linearGradient>
          <linearGradient id="cisstat-home-w2">
            <stop stopColor="#D9E9FA" stopOpacity=".52" />
            <stop offset=".55" stopColor="#C8DDF7" stopOpacity=".64" />
            <stop offset="1" stopColor="#C7D5F7" stopOpacity=".48" />
          </linearGradient>
          <linearGradient id="cisstat-home-w3">
            <stop stopColor="#E7F2FC" stopOpacity=".72" />
            <stop offset=".5" stopColor="#D6E7FA" stopOpacity=".62" />
            <stop offset="1" stopColor="#D9E2FC" stopOpacity=".72" />
          </linearGradient>
          <linearGradient id="cisstat-home-low" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#D7E8FA" stopOpacity=".55" />
            <stop offset="1" stopColor="#D2DBFA" stopOpacity=".68" />
          </linearGradient>
        </defs>

        {/* Диагональная подложка -- rect на весь холст */}
        <rect width="1600" height="1600" fill="url(#cisstat-home-bg)" />

        {/* Лента 1 + сопровождающий белый штрих-акцент */}
        <path
          d="M0 500C220 430 430 450 650 565C860 675 1010 785 1200 780C1370 775 1500 700 1600 640V980C1430 1005 1260 1015 1080 960C850 890 700 730 505 680C310 630 145 650 0 710Z"
          fill="url(#cisstat-home-w1)"
        />
        <path
          d="M0 520C220 450 430 450 650 560C880 675 1035 820 1235 835C1380 846 1505 815 1600 790"
          fill="none"
          stroke="#FFF"
          strokeOpacity=".82"
          strokeWidth="3"
        />

        {/* Лента 2 */}
        <path
          d="M0 760C210 710 420 700 625 745C850 795 1010 930 1185 950C1360 970 1490 900 1600 850V1080C1430 1130 1260 1135 1070 1080C875 1023 730 900 530 850C330 800 150 825 0 875Z"
          fill="url(#cisstat-home-w2)"
        />

        {/* Лента 3 + сопровождающий белый штрих-акцент */}
        <path
          d="M0 1185C220 1115 405 1085 600 1005C825 915 1010 770 1195 650C1360 542 1490 500 1600 470V720C1460 760 1330 810 1190 895C1010 1005 820 1175 615 1285C390 1405 195 1450 0 1490Z"
          fill="url(#cisstat-home-w3)"
        />
        <path
          d="M0 1495C205 1438 390 1390 610 1270C825 1152 1005 1000 1190 885C1350 786 1475 735 1600 705"
          fill="none"
          stroke="#FFF"
          strokeOpacity=".75"
          strokeWidth="3"
        />

        {/* Нижняя лента (low) + сопровождающий белый штрих-акцент */}
        <path
          d="M0 1040C230 1000 400 1020 585 1080C780 1144 910 1260 1100 1305C1290 1350 1450 1290 1600 1210V1600H0Z"
          fill="url(#cisstat-home-low)"
          opacity=".46"
        />
        <path
          d="M0 1040C230 1000 400 1020 585 1080C780 1144 910 1260 1100 1305C1290 1350 1450 1290 1600 1210"
          fill="none"
          stroke="#FFF"
          strokeOpacity=".38"
          strokeWidth="2"
        />
      </svg>
    </div>
  );
}
