"use client";

// packages/ui/components/HomeCapabilities.tsx
//
// Вторая секция главной страницы (/) в standalone-режиме —
// информационная. Расположена ПОД HomeHero (см. apps/standalone/app/page.tsx).
//
// Содержит:
//   - Block A — 4 stat-бейджа в ряд НАД заголовком секции. Каждый бейдж —
//               отдельная карточка со своей рамкой и скруглением (Task 29,
//               2026-08-21: раньше был «слитый монолит» с 1px-линиями
//               между ячейками через gap-px + bg-neutral-200 на родителе).
//               Светло-серый фон, уменьшенный шрифт.
//   - Заголовок H2 + поддерживающий текст.
//   - Block B — сетка 3×2 из 6 capability-карточек: ключевые
//               возможности и принципы платформы.
//
// Чисто презентационный, без состояния. Данные — в lib/capabilities.ts.
// Не подключается в embedded — там пользователь уже внутри портала.
//
// Правка 2 от 2026-08-20: фон Block A затемнён (bg-neutral-50 →
// bg-neutral-100); шрифт H2 приведён к H1 (font-normal → font-semibold);
// под Block B добавлена светло-серая черта (h-px w-full bg-neutral-200).
//
// Правка 3 (Task 29) от 2026-08-21: Block A переделан из «слитого монолита»
// (один общий <dl> с border + rounded-xl + overflow-hidden, ячейки прижаты
// через gap-px) в 4 отдельных бейджа — каждый StatCell имеет собственную
// рамку border-neutral-200 и скругление rounded-xl, между ними gap-3.
// Семантика <dl>/<dt>/<dd> сохранена (a11y).
//
// Правка 4 (Task 30) от 2026-08-21: между Block A и H2 добавлена
// светло-серая черта на всю ширину страницы (h-px w-full bg-neutral-200);
// H2 уменьшен (text-2xl → text-xl) с сохранением font-semibold, цвет шрифта
// изменён с брендового тёмно-синего (#1e3a8a) на серый (text-neutral-700);
// убран hover-эффект с CapabilityCard в Block B (раньше рамка темнела до
// brand/30, фон уходил в brand-light/30, иконка переходила в bg-brand).
// Теперь Block B — полностью статичные карточки.
//
// a11y-контракт:
//   - <section aria-labelledby="capabilities-heading"> оборачивает всё
//   - Stat-счётчики — semantic <dl>/<dt>/<dd>
//   - Иконки карточек — aria-hidden="true"

import {
  CAPABILITIES_TITLE,
  CAPABILITIES_SUBTITLE,
  CAPABILITY_STATS,
  CAPABILITIES,
} from "../lib/capabilities";

// ── Block A: Stat-бейдж ──────────────────────────────────────
//
// Отдельный бейдж-карточка: собственная рамка border-neutral-200,
// скругление rounded-xl, светло-серый фон bg-neutral-100, уменьшенный
// шрифт (text-xl вместо text-3xl). На мобильных — 2 колонки, на sm+ — 4.
// Между бейджами — gap-3 (раньше был gap-px с общей рамкой).

function StatCell({ value, label }: { value: string; label: string }) {
  return (
    <div className="bg-neutral-100 px-4 py-4 text-center rounded-xl border border-neutral-200">
      <dd className="text-xl font-semibold text-brand leading-none tracking-tight">
        {value}
      </dd>
      <dt className="mt-1.5 text-[11px] font-medium uppercase tracking-wide text-neutral-500 leading-tight">
        {label}
      </dt>
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
      {/* ── Block A: 4 stat-бейджа НАД заголовком секции ──
          Task 29 (2026-08-21): 4 отдельных бейджа вместо слитого монолита.
          Каждый StatCell — самостоятельная карточка со своей рамкой
          и скруглением. <dl> без общей рамки, только grid + gap-3. */}
      <dl
        className="grid grid-cols-2 sm:grid-cols-4 gap-3"
        aria-label="Метрики платформы"
      >
        {CAPABILITY_STATS.map((stat) => (
          <StatCell key={stat.label} value={stat.value} label={stat.label} />
        ))}
      </dl>

      {/* ── Декоративная светло-серая черта между Block A и заголовком ──
          Task 30 (2026-08-21): разделяет 4 stat-бейджа и H2 визуально. */}
      <div className="h-px w-full bg-neutral-200" aria-hidden="true" />

      {/* ── Заголовок секции ──
          Task 30 (2026-08-21): text-2xl → text-xl, font-semibold сохранён,
          цвет brand[#1e3a8a] → text-neutral-700 (серый). */}
      <div>
        <h2
          id="capabilities-heading"
          className="font-sans text-xl font-semibold tracking-tight text-neutral-500"
        >
          {CAPABILITIES_TITLE}
        </h2>
        <p className="mt-2 text-sm text-neutral-500">
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
