"use client";

// packages/ui/components/NavigatorHero.tsx
//
// Верхняя часть страницы «Знакомство с платформой» в обоих apps/*.
// Содержит:
//   - H1 и три якорные карточки разделов в стиле главной страницы
//   - интерактивный трёхколоночный навигатор прикладных задач
//   - секцию «Ключевые этапы исследования ряда»:
//       * ряд 1 — БЕГУЩАЯ СТРОКА шеврон-стрелок (задача NAVSTG-1,
//         2026-09-17): паттерн marquee главной страницы (HomeCapabilities,
//         M-02) — вьюпорт overflow-hidden, трек w-max из двух одинаковых
//         групп по 14 стрелок, сдвиг -50% = ровно одна группа (бесшовный
//         цикл), скорость 90s linear infinite, пауза на hover,
//         motion-reduce отключает анимацию. НАПРАВЛЕНИЕ — слева направо
//         (animate-marquee-reverse: translateX(-50%) -> 0 — зеркальный
//         keyframe к marquee главной). Дизайн стрелки по стандарту
//         главной marquee: рамка — фирменный индиго #2E3192, фон —
//         прозрачный (SVG-полигон fill="none" + stroke + векторный
//         эффект постоянной толщины; CSS-border поверх clip-path
//         обрезался бы по диагоналям стрелки, сплошная заливка
//         нарушила бы прозрачность над волновым фоном страницы).
//         NAVSTG-2 (2026-09-17, точечная правка): (а) ширина стрелки —
//         строго по формуле ШИРИНА СТРАНИЦЫ / 6 = ШИРИНА ОДНОЙ СТРЕЛКИ:
//         вьюпорт объявлен CSS-контейнером ([container-type:inline-size]
//         — произвольное свойство Tailwind, ядро 3.4 не содержит
//         containerType-плагина), стрелка — w-[calc(100cqw/6)];
//         (б) рамка тоньше: stroke-width 2 -> 1 (1px = толщина border
//         бейджей главной marquee).
//       * слой выше трека — цифры нумерации в зелёных кружках:
//         СТАТИЧНЫ (absolute-оверлей поверх движущейся строки,
//         pointer-events-none — hover-пауза трека работает сквозь них);
//         геометрия кружков прежняя (h-7 w-7 rounded-full bg-green-50
//         text-green-700, Task 26).
//       * ряд 2 — заголовки + описания этапов: поля 24px (px-6 —
//         паттерн первой секции и главной страницы, Task w/n/NAVBG-2);
//         высоты блоков натуральные — grid-строки выравнивают их
//         автоматически (stretch), фиксированные высоты не вводились.
//       * ряд 3 — «Для кого» / «Для чего»: переведены из формата
//         селектора (CollapsibleHalfBadge, Task 21: кнопка/aria-expanded/
//         раскрывающийся текст) в формат СТАТИЧНОГО бейджа — текст всегда
//         виден, интерактивных элементов нет; визуальная DNA карточки
//         сохранена (rounded-lg, border-brand/20, bg-brand-light/40,
//         зелёная галочка); поля 24px (px-6).
//   - индиго-разделители над заголовками содержательных разделов
//     (токен brand #2E3192 — паттерн главной страницы, Task NAVIG-1)
//
// a11y-контракт:
//   - Обёртка этапов — aria-label="Этапы анализа", цифры aria-hidden
//   - Текстовые блоки — semantic <p>, видны всем
//   - Дублирующая группа marquee — aria-hidden="true"; стрелки —
//     чистая декорация (aria-hidden на каждой)
//   - Статичные бейджи — semantic текст без кнопок/aria-expanded

import { Check } from "lucide-react";
import {
  NAVIGATOR_BADGES,
  NAVIGATOR_SECTION_ROUTES,
  AUDIENCE_LABEL,
  AUDIENCE_TEXT,
  PURPOSE_LABEL,
  PURPOSE_TEXT,
} from "../lib/navigator-stops";
import { RouteCard } from "./RouteCard";
import { AppliedTasksNavigator } from "./AppliedTasksNavigator";

// ── Chevron-стрелка бегущей строки (NAVSTG-1) ────────────────────
//
// Чистая декорация: контурная стрелка (SVG-полигон) на прозрачном фоне.
// Геометрия — прежний шестиугольник со срезом 14 ед. (INDENT_PX Task 26),
// полигон утоплен на 3 ед. от краёв viewBox: половина обводки (1px,
// non-scaling-stroke) не срезается границами SVG при любом растяжении
// preserveAspectRatio="none".
//
// ШИРИНА — формула NAVSTG-2: ШИРИНА СТРАНИЦЫ / 6 = ШИРИНА ОДНОЙ
// СТРЕЛКИ. Источник истины — вьюпорт marquee (full-bleed, его ширина
// = ширине страницы): он объявлен CSS-контейнером — произвольное
// свойство Tailwind [container-type:inline-size] (ядерной утилиты
// @container в TW 3.4 нет — плагин container-queries не подключён),
// поэтому 100cqw внутри трека = ширина
// страницы, а w-[calc(100cqw/6)] — ровно её шестая часть. На странице
// всегда видно ровно 6 стрелок, статичный оверлей цифр (grid-cols-6)
// даёт одну цифру точно по центру каждой стрелки. Процентная ширина
// внутри трека w-max не разрешается (циклическая зависимость),
// vw включает полосу прокрутки — потому именно контейнерные единицы.
// Стрелки стыкуются в цепочку (flex без gap) — как прежний
// бесшовный grid-ряд.

const CHEVRON_ARROW_CLASS =
  "h-11 w-[calc(100cqw/6)] shrink-0";

function ChevronArrowMarquee() {
  return (
    <div className={CHEVRON_ARROW_CLASS} aria-hidden="true">
      <svg
        className="h-full w-full"
        viewBox="0 0 280 44"
        preserveAspectRatio="none"
        focusable="false"
        aria-hidden="true"
      >
        <polygon
          points="3,3 263,3 277,22 263,41 3,41 17,22"
          fill="none"
          stroke="var(--chart-brand)"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}

// ── Группа стрелок внутри marquee-трека ──────────────────────────
//
// 14 стрелок на группу — как 14 бейджей главной marquee: NAVSTG-2 —
// стрелка = страница/6, значит группа = 14/6 ≈ 2.33 ширины страницы
// и ВСЕГДА шире любого вьюпорта — бесшовность стыка при
// translateX(-50%) не зависит от ширины экрана. Flex без gap —
// стрелки соединяются визуально.

const CHEVRON_MARQUEE_GROUP_SIZE = 14;

function ChevronMarqueeGroup({ clone = false }: { clone?: boolean }) {
  return (
    <div
      className="flex"
      data-testid={clone ? "chevron-group-clone" : "chevron-group-real"}
      aria-hidden={clone || undefined}
    >
      {Array.from({ length: CHEVRON_MARQUEE_GROUP_SIZE }, (_, i) => (
        <ChevronArrowMarquee key={i} />
      ))}
    </div>
  );
}

// ── Вспомогательный компонент: статичный полубейдж (NAVSTG-1) ────────
//
// Прежний CollapsibleHalfBadge (Task 21) — селектор: кнопка-триггер,
// aria-expanded/aria-controls, текст скрывается. Постановка: формат
// селектора → формат статичного бейджа. Контент всегда виден, интерактив
// устранён; визуальная DNA карточки (рамка, фон, галочка, типографика
// заголовка) сохранена 1:1 со старым раскрытым состоянием.

interface StaticHalfBadgeProps {
  label: string;
  text: string;
  testId: string;
}

function StaticHalfBadge({ label, text, testId }: StaticHalfBadgeProps) {
  return (
    <div
      data-testid={testId}
      className="rounded-lg border border-brand/20 bg-brand-light/40 px-4 py-3.5"
    >
      <div className="flex items-center gap-2">
        <Check
          size={16}
          className="shrink-0 text-green-700"
          aria-hidden="true"
        />
        <span className="text-xs font-semibold uppercase tracking-wide text-neutral-600">
          {label}
        </span>
      </div>
      <p className="mt-2 text-sm text-neutral-700 leading-relaxed">{text}</p>
    </div>
  );
}

// ── Основной компонент ───────────────────────────────────────────────

export function NavigatorHero() {
  return (
    <div className="space-y-12">
      <header className="space-y-10">
        <div className="text-center">
          <h1 className="font-sans text-2xl font-semibold tracking-tight text-[#1e3a8a] text-center">
            Знакомство с платформой
          </h1>
          <p className="mt-3 text-lg text-[#1e3a8a]">
            выберите раздел для быстрого погружения • отраслевые задачи • логика исследования • устройство платформы
          </p>
        </div>

        {/* Боковые поля 24px сетки бейджей (паттерн главной страницы,
            Task w/n: px-6 — собственные поля от границ фоновой коробки;
            карточки соразмерно ужимаются, равенство по ширине/высоте —
            механикой Grid: fr-колонки + row stretch). */}
        <nav
          className="grid grid-cols-1 md:grid-cols-3 gap-5 px-6"
          aria-label="Разделы знакомства с платформой"
        >
          {NAVIGATOR_SECTION_ROUTES.map((route) => (
            <RouteCard key={route.href} {...route} />
          ))}
        </nav>
      </header>

      <section
        id="applied-tasks"
        aria-labelledby="applied-tasks-title"
        className="scroll-mt-24"
      >
        <div className="w-full border-t border-brand py-4">
          <h2
            id="applied-tasks-title"
            className="font-sans text-2xl font-normal tracking-tight text-[#1e3a8a] text-center"
          >
            Примеры прикладных задач
          </h2>
        </div>
        <AppliedTasksNavigator />
      </section>

      <section
        id="research-stages"
        aria-labelledby="research-stages-title"
        className="scroll-mt-24 space-y-6"
      >
        <div className="w-full border-t border-brand pt-4">
          <h2
            id="research-stages-title"
            className="font-sans text-2xl font-normal tracking-tight text-[#1e3a8a] text-center"
          >
            Ключевые этапы исследования ряда
          </h2>
        </div>

      {/* ── Этапы исследования: бегущая строка + статичные цифры ──
          NAVSTG-1 (2026-09-17). Слой 1 (нижний) — движущаяся строка
          шеврон-стрелок слева направо (animate-marquee-reverse,
          90s linear — стандарт marquee главной; full-bleed, как
          бегущая строка главной). Слой 2 (верхний) — СТАТИЧНЫЕ цифры
          нумерации в зелёных кружках: absolute-оверлей над треком,
          pointer-events-none (hover-пауза трека работает сквозь цифры).
          Ряд 2 — заголовки/описания этапов (px-6, паттерн первой
          секции). Строки grid выравнивают высоты текстовых блоков
          автоматически — фиксированные высоты не требуются. */}
      <div aria-label="Этапы анализа" className="space-y-2">
        {/* Слой 1: движущаяся строка шеврон-стрелок (чистая декорация,
            aria-hidden на каждой стрелке; клон-группа — aria-hidden).
            Позиционный контейнер relative — система координат
            абсолютного оверлея цифр. [container-type:inline-size]
            (NAVSTG-2): вьюпорт — CSS-контейнер, его ширина = ширина
            страницы; источник единиц cqw для формулы
            «страница / 6 = стрелка». */}
        <div className="relative">
          <div
            className="[container-type:inline-size] relative overflow-hidden"
            data-testid="chevron-marquee-viewport"
          >
            <div
              className="flex w-max animate-marquee-reverse hover:[animation-play-state:paused] motion-reduce:animate-none"
              data-testid="chevron-marquee-track"
            >
              <ChevronMarqueeGroup />
              <ChevronMarqueeGroup clone />
            </div>
          </div>

          {/* Слой 2: СТАТИЧНЫЕ цифры нумерации (не анимируются — НЕ
              внутри трека; pointer-events-none — не перехватывают
              hover; grid-cols-6 — равномерно на всю ширину страницы,
              по одному кружку на этап). */}
          <div
            className="pointer-events-none absolute inset-0 grid grid-cols-6"
            data-testid="stage-numbers-overlay"
            aria-hidden="true"
          >
            {NAVIGATOR_BADGES.map((b) => (
              <div key={`num-${b.num}`} className="flex items-center justify-center">
                <span
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-green-50 text-green-700 text-sm font-semibold"
                  aria-hidden="true"
                >
                  {b.num}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Ряд 2: заголовки + описания этапов. Сетка прежней адаптивной
            геометрии (2/3/6 колонок) + px-6 — поля 24px по паттерну
            первой секции / главной страницы (Task w/n, NAVBG-2);
            стрелки из сетки убраны — ряд полностью статичен. */}
        <div
          className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-y-2 px-6"
          data-testid="stages-text-grid"
        >
          {NAVIGATOR_BADGES.map((b) => (
            <p
              key={`title-${b.num}`}
              className="w-full text-center pt-1 text-sm font-semibold text-neutral-800"
            >
              {b.label}
            </p>
          ))}
          {NAVIGATOR_BADGES.map((b) => (
            <p
              key={`sub-${b.num}`}
              className="px-2.5 text-xs text-neutral-500 leading-relaxed"
            >
              {b.subtitle}
            </p>
          ))}
        </div>
      </div>

      {/* ── Ряд 3: «Для кого» / «Для чего» — статичные бейджи (NAVSTG-1):
          прежний формат селектора (CollapsibleHalfBadge) заменён на
          статичный бейдж с всегда видимым текстом; px-6 — поля 24px
          по паттерну главной страницы. */}
      <div
        className="grid grid-cols-1 md:grid-cols-2 gap-3 px-6"
        data-testid="audience-purpose-grid"
      >
        <StaticHalfBadge
          label={AUDIENCE_LABEL}
          text={AUDIENCE_TEXT}
          testId="badge-audience"
        />
        <StaticHalfBadge
          label={PURPOSE_LABEL}
          text={PURPOSE_TEXT}
          testId="badge-purpose"
        />
      </div>

      </section>
    </div>
  );
}
