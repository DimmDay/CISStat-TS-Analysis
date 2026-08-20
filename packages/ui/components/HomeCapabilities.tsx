"use client";

// packages/ui/components/HomeCapabilities.tsx
//
// Вторая секция главной страницы (/) в standalone-режиме.

import {
  CAPABILITIES_TITLE,
  CAPABILITIES_SUBTITLE,
  CAPABILITY_STATS,
  CAPABILITIES,
} from "../lib/capabilities";

function StatCell({ value, label }: { value: string; label: string }) {
  return (
    <div className="bg-neutral-100 px-4 py-4 text-center">
      <dd className="text-xl font-semibold text-brand leading-none tracking-tight">
        {value}
      </dd>
      <dt className="mt-1.5 text-[11px] font-medium uppercase tracking-wide text-neutral-500 leading-tight">
        {label}
      </dt>
    </div>
  );
}

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
    <div className="group flex items-start gap-4 rounded-xl border border-brand/30 bg-brand-light/30 p-6 transition-colors hover:border-brand/60 hover:bg-brand-light/60">
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

export function HomeCapabilities() {
  return (
    <section
      aria-labelledby="capabilities-heading"
      className="space-y-8 pt-4"
    >
      <dl
        className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-neutral-200 rounded-xl overflow-hidden border border-neutral-200"
        aria-label="Метрики платформы"
      >
        {CAPABILITY_STATS.map((stat) => (
          <StatCell key={stat.label} value={stat.value} label={stat.label} />
        ))}
      </dl>

      <div>
        <h2
          id="capabilities-heading"
          className="font-sans text-2xl font-semibold tracking-tight text-[#1e3a8a]"
        >
          {CAPABILITIES_TITLE}
        </h2>
        <p className="mt-2 text-sm text-neutral-500">
          {CAPABILITIES_SUBTITLE}
        </p>
      </div>

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

      <div className="h-px w-full bg-neutral-200" aria-hidden="true" />
    </section>
  );
}
