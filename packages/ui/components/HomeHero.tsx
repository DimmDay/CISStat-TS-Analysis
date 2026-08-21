"use client";

// packages/ui/components/HomeHero.tsx
//
// Hero-секция новой главной страницы (/) — исследовательская карта.
// Чисто презентационный, без состояния.
//
// Содержит:
//   - H1 «Анализ временных рядов — от файла до прогноза»
//   - Поддерживающий текст тонким серым шрифтом
//   - Сетку 3×2 из 6 карточек-маршрутов (HOME_ROUTES)

import Link from "next/link";
import { HOME_ROUTES } from "../lib/home-stops";

// ── Одноячеистая карточка маршрута ─────────────────────────────

function RouteCard({
  title,
  description,
  icon: Icon,
  href,
}: (typeof HOME_ROUTES)[number]) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-4 rounded-xl border border-brand/60 bg-brand-light/60 p-6 transition-colors hover:border-brand/90 hover:bg-brand-light/90"
    >
      {/* Иконка в брендовом кружке */}
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
        <p className="mt-1 text-sm text-neutral-500 leading-relaxed">
          {description}
        </p>
      </div>
    </Link>
  );
}

// ── Основной компонент ─────────────────────────────────────────

export function HomeHero() {
  return (
    <div className="space-y-10">
      {/* ── Заголовок + поддерживающий текст ── */}
      <div className="text-center">
        <h1 className="font-sans text-2xl font-semibold tracking-tight text-[#1e3a8a]">
          Анализ временных рядов — от файла до прогноза
        </h1>
        <p className="mt-3 text-lg text-[#1e3a8a]">
          пространство для • исследования • обучения • проверки гипотез • аргументированных выводов • принятия решений
        </p>
      </div>

      {/* ── Исследовательская карта: сетка 3×2 ── */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5"
        role="list"
        aria-label="Маршруты"
      >
        {HOME_ROUTES.map((route) => (
          <RouteCard key={route.title} {...route} />
        ))}
      </div>
    </div>
  );
}