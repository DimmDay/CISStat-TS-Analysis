"use client";

// packages/ui/components/HomeCapabilities.tsx
//
// Вторая секция главной страницы (/) в standalone-режиме —
// информационная. Расположена ПОД HomeHero (см. apps/standalone/app/page.tsx).
//
// Содержит:
//   - Block A — 4 stat-счётчика в ряд НАД заголовком секции. Светло-серый
//               фон, уменьшенный шрифт — служит визуальным якорем до
//               того, как пользователь вчитывается в заголовок.
//   - Заголовок H2 + поддерживающий текст.
//   - Block B — сетка 3×2 из 6 capability-карточек: ключевые
//               возможности и принципы платформы.
//
// Чисто презентационный, без состояния. Данные — в lib/capabilities.ts,
// чтобы переиспользовать в будущем (например, в marketing-landings или
// в /about). Не подключается в embedded — там пользователь уже внутри
// портала, маркетинговый контекст не нужен (решение тимлида 2026-08-20).
//
// Правка от 2026-08-20: убраны section tag (моноширинный лейбл над H2)
// и Block C (manifesto-цитата). Block A перенесён над заголовком секции,
// шрифт счётчиков уменьшен (text-3xl → text-xl), фон сделан светло-серым
// (bg-white → bg-neutral-50, ячейки — bg-neutral-50 вместо bg-white,
// граница остаётся neutral-200).
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

// ── Block A: Stat-счётчик ─────────────────────────────────────
//
// Карточка счётчика: значение + короткая подпись. Светло-серый фон,
// уменьшенный шрифт (text-xl вместо text-3xl). Разделители между
// ячейками — через gap-px + bg-neutral-200 на родителе grid.
// На мобильных — 2 колонки, на sm+ — 4.

function StatCell({ value, label }: { value: string; label: string }) {
  return (
    <div className="bg-neutral-50 px-4 py-4 text-center">
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
      {/* ── Block A: 4 stat-счётчика НАД заголовком секции ── */}
      <dl
        className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-neutral-200 rounded-xl overflow-hidden border border-neutral-200"
        aria-label="Метрики платформы"
      >
        {CAPABILITY_STATS.map((stat) => (
          <StatCell key={stat.label} value={stat.value} label={stat.label} />
        ))}
      </dl>

      {/* ── Заголовок секции ── */}
      <div>
        <h2
          id="capabilities-heading"
          className="font-sans text-2xl font-normal tracking-tight text-[#1e3a8a]"
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
    </section>
  );
}
