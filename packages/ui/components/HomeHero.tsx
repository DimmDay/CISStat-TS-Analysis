"use client";

// packages/ui/components/HomeHero.tsx
//
// Hero-секция новой главной страницы (/) — исследовательская карта.
// Чисто презентационный, без состояния.
//
// Содержит:
//   - H1 «Анализ временных рядов — от файла до прогноза»
//   - Поддерживающий текст тонким серым шрифтом
//   - Сетку из 6 stat-бейджей «Анализ временных рядов…» (HERO_STATS,
//     Задача M-03, 2026-09-12 — между заголовком и картой маршрутов;
//     данные в lib/capabilities.ts, бейдж — общий StatBadge, сетка —
//     общая STAT_GRID_CLASS, как в нижней секции: размеры бейджей
//     секций совпадают по построению)
//   - Сетку 3×2 из 6 карточек-маршрутов (HOME_ROUTES)
//
// Отступ бейджей от границ страницы — 24px слева/справа (px-6
// контейнера <main> в apps/standalone/app/layout.tsx).

import { HOME_ROUTES } from "../lib/home-stops";
import { HERO_STATS, STAT_GRID_CLASS } from "../lib/capabilities";
import { StatBadge } from "./StatBadge";
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

      {/* ── 6 stat-бейджей «Анализ временных рядов…» (M-03) ──
          Семантика <dl>/<dt>/<dd>; сетка и бейджи — общие с нижней
          секцией (STAT_GRID_CLASS + StatBadge) — одинаковый размер. */}
      <dl
        className={STAT_GRID_CLASS}
        aria-label="Метрики анализа временных рядов"
      >
        {HERO_STATS.map((stat) => (
          <StatBadge
            key={`${stat.value}-${stat.label}`}
            value={stat.value}
            label={stat.label}
          />
        ))}
      </dl>

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
