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

import { HOME_ROUTES } from "../lib/home-stops";
import { RouteCard } from "./RouteCard";

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
