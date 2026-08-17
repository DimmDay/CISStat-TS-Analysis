// packages/ui/components/NavigatorHero.tsx
//
// Верхняя часть главной страницы "Навигатор" в обоих apps/* (standalone и
// embedded). Чисто презентационный компонент:
//   - H1 "Анализ временных рядов — от файла до прогноза"
//   - ряд из 6 числовых бейджей (соответствуют 6 этапам пайплайна 1:1)
//   - 2 полубейджа на 1/2 ширины каждый: «Для кого» и «Для чего»
//     (тексты утверждены тимлидом, см. lib/navigator-stops.ts)
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
      <h1 className="font-sans text-3xl font-semibold text-neutral-900">
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

      {/* ── 5–6. Два полубейджа на 1/2 ширины: «Для кого» и «Для чего» ──
          Замечание тимлида #1: убрать дублирование с верхней парой
          текстовых плашек — оставить только эти карточки с фоном,
          добавив в каждую заголовок «Для кого» / «Для чего». */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Полубейдж «Для кого» */}
        <div className="flex flex-col gap-1.5 rounded-lg border border-brand/20 bg-brand-light/40 px-4 py-3.5">
          <div className="flex items-center gap-2">
            <Check size={16} className="shrink-0 text-green-700" aria-hidden="true" />
            <span className="text-xs font-semibold uppercase tracking-wide text-neutral-600">
              {AUDIENCE_LABEL}
            </span>
          </div>
          <p className="text-sm text-neutral-700 leading-relaxed">{AUDIENCE_TEXT}</p>
        </div>

        {/* Полубейдж «Для чего» */}
        <div className="flex flex-col gap-1.5 rounded-lg border border-brand/20 bg-brand-light/40 px-4 py-3.5">
          <div className="flex items-center gap-2">
            <Check size={16} className="shrink-0 text-green-700" aria-hidden="true" />
            <span className="text-xs font-semibold uppercase tracking-wide text-neutral-600">
              {PURPOSE_LABEL}
            </span>
          </div>
          <p className="text-sm text-neutral-700 leading-relaxed">{PURPOSE_TEXT}</p>
        </div>
      </div>
    </div>
  );
}
