"use client";

// packages/ui/components/HomeCapabilities.tsx
//
// Вторая секция главной страницы (/) в standalone-режиме —
// информационная. Расположена ПОД HomeHero (см. apps/standalone/app/page.tsx).
//
// Содержит:
//   - Block A — marquee-лента из 14 stat-бейджей (Задача M-02,
//               2026-09-12: 4 исходных + 10 новых маркетинговых тезисов,
//               фактура верифицирована по коду main @ 23ca75b).
//               Лента бесшовно движется справа налево с низкой скоростью
//               (animate-marquee: 90s linear infinite, translateX 0 → -50%),
//               все бейджи движутся синхронно — анимация одна на трек.
//               На ширине страницы видно ~5 бейджей (фиксированная ширина
//               w-[clamp(180px,18vw,300px)]), высота бейджа унифицирована:
//               подпись — ровно 2 строки (h-7 + line-clamp-2).
//               Пауза на hover; prefers-reduced-motion отключает анимацию
//               (см. packages/ui/globals.css).
//               Бесшовность: лента дублируется в aria-hidden-копию,
//               сдвиг -50% = ровно одна группа (включая завершающий gap).
//               Прозрачный фон бейджа, текст — фирменный индиго
//               text-brand (правка 6), компактный паддинг (px-3 py-3).
//   - Заголовок H2 + поддерживающий текст.
//   - Block B — сетка 3×2 из 6 capability-карточек: ключевые
//               возможности и принципы платформы.
//
// Чисто презентационный, без состояния. Данные — в lib/capabilities.ts.
// Не подключается в embedded — там пользователь уже внутри портала.
//
// История правок:
//   - Правка 2 от 2026-08-20: фон Block A затемнён (bg-neutral-50 →
//     bg-neutral-100); шрифт H2 приведён к H1 (font-normal → font-semibold);
//     под Block B добавлена светло-серая черта (h-px w-full bg-neutral-200).
//   - Правка 3 (Task 29) от 2026-08-21: Block A переделан из «слитого
//     монолита» в 4 отдельных бейджа с собственной рамкой/скруглением.
//   - Правка 4 (Task 30) от 2026-08-21: черта между Block A и H2; H2
//     text-xl/text-neutral-600; Block B — полностью статичные карточки.
//   - Правка 5 (M-02) от 2026-09-12: Block A — marquee из 14 бейджей;
//     сетка grid-cols-2/sm:grid-cols-4 заменена на бегущую строку.
//   - Правка 6 (Task w/n) от 2026-09-12: точечная правка бейджей
//     marquee — фон прозрачный (bg-neutral-100 → bg-transparent) и
//     подпись в фирменном индиго text-brand (было text-neutral-500),
//     т.е. весь текст бейджа — единый цвет цифры (#2E3192). Рамка,
//     скругление, паддинг, ширина, анимация и Block B НЕ тронуты.
//   - Правка 7 (Task w/n) от 2026-09-12: продолжение точечной правки —
//     рамка бейджа marquee — фирменный индиго (border-neutral-200 →
//     border-brand, тот же токен #2E3192); полоса-разделитель ПОД
//     бегущей строкой (между marquee и H2) — фирменный индиго
//     (bg-neutral-200 → bg-brand). Нижняя полоса (после Block B),
//     Block B, анимация, геометрия бейджа НЕ тронуты.
//
// a11y-контракт:
//   - <section aria-labelledby="capabilities-heading"> оборачивает всё
//   - Stat-счётчики — semantic <dl>/<dt>/<dd>; aria-label="Метрики платформы"
//   - Дублирующая группа ленты — aria-hidden="true" (скринридер читает
//     каждый тезис ровно один раз)
//   - Иконки карточек — aria-hidden="true"
//   - Анимация уважает prefers-reduced-motion (CSS в packages/ui/globals.css)

import {
  CAPABILITIES_TITLE,
  CAPABILITIES_SUBTITLE,
  CAPABILITY_STATS,
  CAPABILITIES,
  type CapabilityStat,
} from "../lib/capabilities";

// ── Block A: Stat-бейдж marquee-ленты ────────────────────────
//
// Компактная карточка: фиксированная ширина w-[clamp(180px,18vw,300px)]
// (~5 бейджей на ширину контейнера max-w-[1600px]), собственная рамка
// border-brand (фирменный индиго #2E3192, правка 7), скругление
// rounded-xl, ПРОЗРАЧНЫЙ фон bg-transparent (сквозь бейдж виден фон
// страницы), компактный паддинг px-3/py-3. Весь текст бейджа —
// фирменный индиго text-brand: и значение (dd), и подпись (dt).
// Подпись — ровно 2 строки у ВСЕХ бейджей: h-7 (28px = 2×leading-tight
// от text-[11px]) + line-clamp-2 (страховка от переполнения на узких
// вьюпортах).

function StatCell({ value, label }: { value: string; label: string }) {
  return (
    <div className="w-[clamp(180px,18vw,300px)] shrink-0 bg-transparent px-3 py-3 text-center rounded-xl border border-brand">
      <dd className="text-xl font-semibold text-brand leading-none tracking-tight">
        {value}
      </dd>
      <dt className="mt-1.5 h-7 text-[11px] font-medium uppercase tracking-wide text-brand leading-tight line-clamp-2">
        {label}
      </dt>
    </div>
  );
}

// ── Block A: группа бейджей внутри marquee-трека ─────────────
//
// Два идентичных экземпляра: реальный (читается скринридером) и клон
// (aria-hidden, обеспечивает бесшовный стык при translateX(-50%)).
// pr-3 на группе — завершающий gap стыка, равный межбейджевому gap-3.

function MarqueeGroup({
  stats,
  clone = false,
}: {
  stats: CapabilityStat[];
  clone?: boolean;
}) {
  return (
    <div
      className="flex gap-3 pr-3"
      data-testid={clone ? "marquee-group-clone" : "marquee-group-real"}
      aria-hidden={clone || undefined}
    >
      {stats.map((stat) => (
        <StatCell key={`${stat.value}-${stat.label}`} value={stat.value} label={stat.label} />
      ))}
    </div>
  );
}

// ── Block B: Capability-карточка ─────────────────────────────
//
// По образцу RouteCard в HomeHero.tsx — иконка в брендовом кружке +
// заголовок + описание. Task 30 (2026-08-21): hover-эффект убран —
// карточка полностью статичная (раньше рамка темнела до brand/30,
// фон уходил в brand-light/30, иконка переходила в bg-brand text-white).

function CapabilityCard({
  title,
  description,
  icon: Icon,
}: {
  title: string;
  description: string;
  icon: (typeof CAPABILITIES)[number]["icon"];
}) {
  return (
    <div className="flex items-start gap-4 rounded-xl border border-neutral-200 bg-white p-6">
      <span
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand-light text-brand"
        aria-hidden="true"
      >
        <Icon size={20} />
      </span>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-neutral-900 leading-snug">
          {title}
        </h3>
        <p className="mt-1.5 text-sm text-neutral-500 leading-relaxed">
          {description}
        </p>
      </div>
    </div>
  );
}

// ── Основной компонент ────────────────────────────────────────

export function HomeCapabilities() {
  return (
    <section
      aria-labelledby="capabilities-heading"
      className="space-y-8 pt-4"
    >
      {/* ── Block A: marquee из 14 stat-бейджей НАД заголовком секции ──
          Задача M-02 (2026-09-12): сетка grid-cols-2/sm:grid-cols-4
          заменена на бегущую строку. Вьюпорт обрезает трек (overflow-hidden),
          трек (dl, w-max) целиком анимируется одним transform — все бейджи
          движутся синхронно и равномерно справа налево (90s linear).
          Пауза на hover; при prefers-reduced-motion анимация отключается
          CSS-правилом в packages/ui/globals.css (лента остаётся читаемой,
          вьюпорт переключается на ручную горизонтальную прокрутку). */}
      <div className="marquee-viewport relative overflow-hidden">
        <dl
          className="flex w-max gap-3 animate-marquee hover:[animation-play-state:paused] motion-reduce:animate-none"
          aria-label="Метрики платформы"
        >
          <MarqueeGroup stats={CAPABILITY_STATS} />
          <MarqueeGroup stats={CAPABILITY_STATS} clone />
        </dl>
      </div>

      {/* ── Декоративная черта между Block A и заголовком ──
          Task 30 (2026-08-21): разделяет marquee-ленту и H2 визуально.
          Правка 7 (2026-09-12): цвет — фирменный индиго (bg-brand);
          это полоса именно ПОД бегущей строкой (нижняя полоса после
          Block B остаётся нейтральной). */}
      <div className="h-px w-full bg-brand" aria-hidden="true" />

      {/* ── Заголовок секции ──
          Task 30 (2026-08-21): text-2xl → text-xl, font-semibold сохранён,
          цвет brand[#1e3a8a] → text-neutral-700 (серый). */}
      <div className="text-center">
        <h2
          id="capabilities-heading"
          className="font-sans text-xl font-semibold tracking-tight text-neutral-600"
        >
          {CAPABILITIES_TITLE}
        </h2>
        <p className="mt-2 text-base text-neutral-500">
          {CAPABILITIES_SUBTITLE}
        </p>
      </div>

      {/* ── Block B: 6 capability-карточек (сетка 3×2) ──
          Task w/n (2026-09-12): px-6 — собственные боковые поля сетки
          24px слева/справа от границ страницы; карточки соразмерно
          ужимаются (504px -> 488px при ширине страницы 1600px). Классы
          сетки идентичны сетке маршрутов HomeHero — равный размер
          бейджей обеих секций (прижат кросс-тестом). Бегущая строка
          (Block A) НЕ тронута — остаётся full-bleed. */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 px-6"
        role="list"
        aria-label="Ключевые возможности платформы"
      >
        {CAPABILITIES.map((cap) => (
          <div role="listitem" key={cap.title}>
            <CapabilityCard
              title={cap.title}
              description={cap.description}
              icon={cap.icon}
            />
          </div>
        ))}
      </div>

      {/* ── Декоративная светло-серая черта на ширину страницы ── */}
      <div className="h-px w-full bg-neutral-200" aria-hidden="true" />
    </section>
  );
}
