// packages/ui/components/NavigatorHero.tsx
//
// Верхняя часть главной страницы "Навигатор" в обоих apps/* (standalone и
// embedded). Чисто презентационный компонент:
//   - H1 "Анализ временных рядов — от файла до прогноза"
//   - ряд из 6 числовых бейджей (соответствуют 6 этапам пайплайна 1:1)
//   - ряд "Для кого:" + светло-серая декоративная полоса-разделитель +
//     "Для чего:" + светло-серая декоративная полоса-разделитель
//   - 2 текстовых бейджа на 1/2 ширины каждый (audience + purpose тексты
//     утверждены тимлидом, см. lib/navigator-stops.ts)
//
// Не содержит интерактивности — все данные берутся из lib/navigator-stops.ts.

import { Check } from "lucide-react";
import {
  NAVIGATOR_BADGES,
  AUDIENCE_LABEL,
  AUDIENCE_TEXT,
  PURPOSE_LABEL,
  PURPOSE_TEXT,
} from "../lib/navigator-stops";

export function NavigatorHero() {
  return (
    <div className="space-y-6">
      {/* ── 3. Заголовок ── */}
      <h1 className="text-3xl font-semibold text-neutral-900">
        Анализ временных рядов — от файла до прогноза
      </h1>

      {/* ── 4. Ряд из 6 числовых бейджей ── */}
      <ol
        className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3"
        aria-label="Этапы анализа"
      >
        {NAVIGATOR_BADGES.map((badge) => (
          <li
            key={badge.num}
            className="flex items-start gap-3 rounded-lg border border-neutral-200 bg-white px-3.5 py-3"
          >
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-green-50 text-green-700 text-sm font-semibold"
              aria-hidden="true"
            >
              {badge.num}
            </span>
            <span className="text-sm text-neutral-700 leading-snug">{badge.label}</span>
          </li>
        ))}
      </ol>

      {/* ── 5. Ряд "Для кого" + "Для чего" с декоративными разделителями ── */}
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* Левая половина — Для кого */}
          <div className="md:pr-5">
            <div className="inline-block rounded bg-neutral-100 px-2.5 py-1 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-neutral-600">
                {AUDIENCE_LABEL}
              </span>
            </div>
            <p className="text-sm text-neutral-700 leading-relaxed">{AUDIENCE_TEXT}</p>
          </div>

          {/* Декоративная серая полоса-разделитель (видна на md+) */}
          <div className="hidden md:block absolute" aria-hidden="true" />

          {/* Правая половина — Для чего */}
          <div className="md:pl-5 md:border-l border-neutral-200">
            <div className="inline-block rounded bg-neutral-100 px-2.5 py-1 mb-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-neutral-600">
                {PURPOSE_LABEL}
              </span>
            </div>
            <p className="text-sm text-neutral-700 leading-relaxed">{PURPOSE_TEXT}</p>
          </div>
        </div>
      </div>

      {/* ── 6. Два полубейджа на 1/2 ширины ──
          На макете это карточки с галочкой (Check) перед текстом.
          Тексты совпадают с теми, что были в ряду "Для кого/Для чего",
          но визуально оформлены как самостоятельные бейджи-карточки —
          для акцента на аудитории и назначении отдельным блоком. */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="flex items-start gap-3 rounded-lg border border-brand/20 bg-brand-light/40 px-4 py-3.5">
          <Check size={18} className="mt-0.5 shrink-0 text-green-700" aria-hidden="true" />
          <p className="text-sm text-neutral-700 leading-relaxed">{AUDIENCE_TEXT}</p>
        </div>
        <div className="flex items-start gap-3 rounded-lg border border-brand/20 bg-brand-light/40 px-4 py-3.5">
          <Check size={18} className="mt-0.5 shrink-0 text-green-700" aria-hidden="true" />
          <p className="text-sm text-neutral-700 leading-relaxed">{PURPOSE_TEXT}</p>
        </div>
      </div>
    </div>
  );
}
