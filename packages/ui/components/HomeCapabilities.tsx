"use client";

// packages/ui/components/HomeCapabilities.tsx
//
// Вторая секция главной страницы (/) в standalone-режиме —
// информационная. Расположена ПОД HomeHero (см. apps/standalone/app/page.tsx).
// Содержит три блока:
//
//   Block A — 4 stat-счётчика в ряд: масштаб продукта в 4 числах.
//   Block B — сетка 3×2 из 6 capability-карточек: ключевые
//             возможности и принципы платформы.
//   Block C — manifesto-цитата: эмоциональное закрытие секции,
//             связывающая её с утверждённым PURPOSE_TEXT.
//
// Чисто презентационный, без состояния. Данные — в lib/capabilities.ts,
// чтобы переиспользовать в будущем (например, в marketing-landings или
// в /about). Не подключается в embedded — там пользователь уже внутри
// портала, маркетинговый контекст не нужен (решение тимлида 2026-08-20).
//
// a11y-контракт:
//   - <section aria-labelledby="capabilities-heading"> оборачивает всё
//   - Stat-счётчики — semantic <dl>/<dt>/<dd> (термин-значение)
//   - Manifesto-цитата — <blockquote> с <cite> (визуально скрыт)
//   - Иконки — aria-hidden="true"

import {
  CAPABILITIES_TITLE,
  CAPABILITIES_SUBTITLE,
  CAPABILITIES_TAG,
  CAPABILITY_STATS,
  CAPABILITIES,
  MANIFESTO_HEADLINE,
  MANIFESTO_BODY,
} from "../lib/capabilities";

// ── Block A: Stat-счётчик ─────────────────────────────────────
//
// Карточка счётчика: крупная цифра + короткая подпись. Разделители
// между ячейками реализованы через border на родителе grid
// (gap-px + bg-neutral-200) — приём из Metriqa .counters, даёт
// тонкую сплошную линию вместо визуально тяжёлых borders у каждой
// ячейки. На мобильных — 2 колонки, на sm+ — 4.

function StatCell({ value, label }: { value: string; label: string }) {
  return (
    <div className="bg-white px-4 py-5 text-center">
      <dd className="text-3xl font-semibold text-brand leading-none tracking-tight">
        {value}
      </dd>
      <dt className="mt-2 text-[11px] font-medium uppercase tracking-wide text-neutral-500 leading-tight">
        {label}
      </dt>
    </div>
  );
}

// ── Block B: Capability-карточка ─────────────────────────────
//
// По образцу RouteCard в HomeHero.tsx — иконка в брендовом кружке +
// заголовок + описание. Hover-эффект: рамка темнеет до brand/30,
// фон уходит в brand-light/30. Та же логика, что в RouteCard, чтобы
// визуально связать две секции главной страницы.

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
    <div className="group flex items-start gap-4 rounded-xl border border-neutral-200 bg-white p-6 transition-colors hover:border-brand/30 hover:bg-brand-light/30">
      <span
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand-light text-brand transition-colors group-hover:bg-brand group-hover:text-white"
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
      {/* ── Заголовок секции ── */}
      <div>
        <p className="font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-brand">
          {CAPABILITIES_TAG}
        </p>
        <h2
          id="capabilities-heading"
          className="mt-3 font-sans text-2xl font-normal tracking-tight text-[#1e3a8a]"
        >
          {CAPABILITIES_TITLE}
        </h2>
        <p className="mt-2 text-sm text-neutral-500">
          {CAPABILITIES_SUBTITLE}
        </p>
      </div>

      {/* ── Block A: 4 stat-счётчика ── */}
      <dl
        className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-neutral-200 rounded-xl overflow-hidden border border-neutral-200"
        aria-label="Метрики платформы"
      >
        {CAPABILITY_STATS.map((stat) => (
          <StatCell key={stat.label} value={stat.value} label={stat.label} />
        ))}
      </dl>

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

      {/* ── Block C: Manifesto-цитата ── */}
      <blockquote className="relative border-t border-b border-neutral-200 py-8 text-center">
        <p className="text-lg font-medium text-neutral-900 leading-snug">
          {MANIFESTO_HEADLINE}
        </p>
        <p className="mt-3 text-sm text-neutral-500 leading-relaxed max-w-2xl mx-auto">
          {MANIFESTO_BODY}
        </p>
        <cite className="sr-only">CISStat TS Analysis</cite>
      </blockquote>
    </section>
  );
}
