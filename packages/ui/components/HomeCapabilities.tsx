"use client";

// packages/ui/components/HomeCapabilities.tsx
//
// Вторая секция главной страницы (/) в standalone-режиме —
// информационная. Расположена ПОД HomeHero (см. apps/standalone/app/page.tsx).
//
// Содержит:
//   - Block A — статичная сетка из 6 stat-бейджей «Исследование данных…»
//               (Задача M-03, 2026-09-12: marquee-лента из 14 бейджей
//               (M-02) заменена сеткой по решению тимлида; данные —
//               CAPABILITY_STATS в lib/capabilities.ts, бейдж — общий
//               StatBadge, сетка — общая STAT_GRID_CLASS, как в верхней
//               секции: размеры бейджей секций совпадают по построению;
//               отступ от границ страницы — 24px слева/справа (px-6
//               контейнера <main>)).
//   - Заголовок H2 + поддерживающий текст.
//   - Block B — сетка 3×2 из 6 capability-карточек: ключевые
//               возможности и принципы платформы.
//
// Чисто презентационный, без состояния. Не подключается в embedded —
// там пользователь уже внутри портала.
//
// История правок:
//   - Правка 2 от 2026-08-20: фон Block A затемнён (bg-neutral-50 →
//     bg-neutral-100); шрифт H2 приведён к H1 (font-normal → font-semibold);
//     под Block B добавлена светло-серая черта (h-px w-full bg-neutral-200).
//   - Правка 3 (Task 29) от 2026-08-21: Block A переделан из «слитого
//     монолита» в 4 отдельных бейджа с собственной рамкой/скруглением.
//   - Правка 4 (Task 30) от 2026-08-21: черта между Block A и H2; H2
//     text-xl/text-neutral-600; Block B — полностью статичные карточки.
//   - Правка 5 (M-02) от 2026-09-12: Block A — marquee из 14 бейджей.
//   - Правка 6 (M-03) от 2026-09-12: Block A — статичная сетка 2/3/6
//     из 6 бейджей, общий StatBadge с hero-секцией; marquee-инфраструктура
//     (animate-marquee, вьюпорт, клон, reduced-motion CSS) удалена.
//
// a11y-контракт:
//   - <section aria-labelledby="capabilities-heading"> оборачивает всё
//   - Stat-счётчики — semantic <dl>/<dt>/<dd>; aria-label="Метрики платформы"
//   - Иконки карточек — aria-hidden="true"

import {
  CAPABILITIES_TITLE,
  CAPABILITIES_SUBTITLE,
  CAPABILITY_STATS,
  STAT_GRID_CLASS,
  CAPABILITIES,
} from "../lib/capabilities";
import { StatBadge } from "./StatBadge";

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
      {/* ── Block A: сетка из 6 stat-бейджей НАД заголовком секции ──
          M-03 (2026-09-12): статичная сетка 2/3/6 колонок вместо
          marquee-ленты. Сетка и бейджи — общие с верхней секцией
          (STAT_GRID_CLASS + StatBadge) — одинаковый размер. */}
      <dl
        className={STAT_GRID_CLASS}
        aria-label="Метрики платформы"
      >
        {CAPABILITY_STATS.map((stat) => (
          <StatBadge
            key={`${stat.value}-${stat.label}`}
            value={stat.value}
            label={stat.label}
          />
        ))}
      </dl>

      {/* ── Декоративная светло-серая черта между Block A и заголовком ──
          Task 30 (2026-08-21): разделяет stat-бейджи и H2 визуально. */}
      <div className="h-px w-full bg-neutral-200" aria-hidden="true" />

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

      {/* ── Block B: 6 capability-карточек (сетка 3×2) ── */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5"
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
