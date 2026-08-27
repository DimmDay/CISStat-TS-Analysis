"use client";

// packages/ui/components/NavigatorHero.tsx
//
// Верхняя часть страницы «Знакомство с платформой» в обоих apps/*.
// Содержит:
//   - H1 и три якорные карточки разделов в стиле главной страницы
//   - интерактивный трёхколоночный навигатор прикладных задач
//   - секцию «Ключевые этапы исследования ряда»
//   - 6 chevron-стрелок в ряд (светло-серый фон, зелёная цифра)
//   - под каждой стрелкой — заголовок + поддерживающий текст
//   - 2 раскрывающихся полубейджа «Для кого» / «Для чего» (Task 21)
//   - серые разделители над заголовками содержательных разделов
//
// a11y-контракт:
//   - Chevron-ряд — aria-label="Этапы анализа", цифры aria-hidden
//   - Текстовые блоки — semantic <p>, видны всем
//   - CollapsibleHalfBadge триггеры — <button> с aria-expanded/aria-controls

import { useState } from "react";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import {
  NAVIGATOR_BADGES,
  NAVIGATOR_SECTION_ROUTES,
  AUDIENCE_LABEL,
  AUDIENCE_TEXT,
  PURPOSE_LABEL,
  PURPOSE_TEXT,
} from "../lib/navigator-stops";
import { RouteCard } from "./RouteCard";
import { AppliedTasksNavigator } from "./AppliedTasksNavigator";

// ── Chevron-стрелка ──────────────────────────────────────────────
//
// Однослойный рендер: clip-path + bg-neutral-100 (светло-серый фон),
// зелёная цифра в кружочке внутри.
// Полигон: шестиугольная стрелка, указывающая вправо.
// Константа INDENT — размер среза слева/справа в пикселях.

const INDENT_PX = 14;

/** Clip-path polygon для стрелки. */
const arrowClip = `polygon(
  0 0,
  calc(100% - ${INDENT_PX}px) 0,
  100% 50%,
  calc(100% - ${INDENT_PX}px) 100%,
  0 100%,
  ${INDENT_PX}px 50%
)`;

function ChevronArrow({ num }: { num: number }) {
  return (
    <div
      className="relative h-11 flex-1 min-w-0 flex items-center justify-center bg-neutral-100"
      style={{ clipPath: arrowClip }}
      aria-hidden="true"
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-green-50 text-green-700 text-sm font-semibold">
        {num}
      </span>
    </div>
  );
}

// ── Вспомогательный компонент: раскрывающийся полубейдж ──────────────

interface CollapsibleHalfBadgeProps {
  label: string;
  text: string;
  isOpen: boolean;
  onToggle: () => void;
}

function CollapsibleHalfBadge({
  label,
  text,
  isOpen,
  onToggle,
}: CollapsibleHalfBadgeProps) {
  const panelId = `navigator-badge-${label
    .toLowerCase()
    .replace(/[^a-zа-я0-9]+/gi, "-")
    .replace(/^-+|-+$/g, "")}-panel`;

  return (
    <div className="flex flex-col rounded-lg border border-brand/20 bg-brand-light/40 overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-controls={panelId}
        className="flex items-center justify-between gap-2 px-4 py-3.5 w-full text-left transition-colors hover:bg-brand-light/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 rounded-lg"
      >
        <span className="flex items-center gap-2 min-w-0">
          <Check
            size={16}
            className="shrink-0 text-green-700"
            aria-hidden="true"
          />
          <span className="text-xs font-semibold uppercase tracking-wide text-neutral-600 truncate">
            {label}
          </span>
        </span>
        {isOpen ? (
          <ChevronUp
            size={16}
            className="shrink-0 text-neutral-500"
            aria-label="chevron up"
            role="img"
          />
        ) : (
          <ChevronDown
            size={16}
            className="shrink-0 text-neutral-500"
            aria-label="chevron down"
            role="img"
          />
        )}
      </button>
      {isOpen && (
        <p
          id={panelId}
          className="px-4 pb-3.5 text-sm text-neutral-700 leading-relaxed"
        >
          {text}
        </p>
      )}
    </div>
  );
}

// ── Основной компонент ───────────────────────────────────────────────

export function NavigatorHero() {
  const [audienceOpen, setAudienceOpen] = useState(true);
  const [purposeOpen, setPurposeOpen] = useState(true);

  return (
    <div className="space-y-12">
      <header className="space-y-10">
        <div className="text-center">
          <h1 className="font-sans text-2xl font-semibold tracking-tight text-[#1e3a8a] text-center">
            Знакомство с платформой
          </h1>
          <p className="mt-3 text-lg text-[#1e3a8a]">
            выберите раздел, чтобы быстро понять • задачи • логику исследования • устройство платформы
          </p>
        </div>

        <nav
          className="grid grid-cols-1 md:grid-cols-3 gap-5"
          aria-label="Разделы знакомства с платформой"
        >
          {NAVIGATOR_SECTION_ROUTES.map((route) => (
            <RouteCard key={route.href} {...route} />
          ))}
        </nav>
      </header>

      <section
        id="applied-tasks"
        aria-labelledby="applied-tasks-title"
        className="scroll-mt-24"
      >
        <div className="w-full border-t border-neutral-200 py-4">
          <h2
            id="applied-tasks-title"
            className="font-sans text-2xl font-normal tracking-tight text-[#1e3a8a] text-center"
          >
            Примеры прикладных задач
          </h2>
        </div>
        <AppliedTasksNavigator />
      </section>

      <section
        id="research-stages"
        aria-labelledby="research-stages-title"
        className="scroll-mt-24 space-y-6"
      >
        <div className="w-full border-t border-neutral-200 pt-4">
          <h2
            id="research-stages-title"
            className="font-sans text-2xl font-normal tracking-tight text-[#1e3a8a] text-center"
          >
            Ключевые этапы исследования ряда
          </h2>
        </div>

      {/* ── 2. Chevron-стрелки + текст (Task 26) ──
          Сетка 6 колонок × 3 строки:
            строка 1 — 6 chevron-стрелок,
            строка 2 — 6 заголовков,
            строка 3 — 6 поддерживающих текстов.
          На мобильных — 2 колонки, на sm — 3, на md — 6.
          Без горизонтального gap стрелки соединяются визуально. */}
      <div
        className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-y-2"
        aria-label="Этапы анализа"
      >
        {[
          ...NAVIGATOR_BADGES.map((b) => (
            <ChevronArrow key={`arrow-${b.num}`} num={b.num} />
          )),
          ...NAVIGATOR_BADGES.map((b) => (
            <p
              key={`title-${b.num}`}
              className="w-full text-center pt-1 text-sm font-semibold text-neutral-800"
            >
              {b.label}
            </p>
          )),
          ...NAVIGATOR_BADGES.map((b) => (
            <p
              key={`sub-${b.num}`}
              className="px-2.5 text-xs text-neutral-500 leading-relaxed"
            >
              {b.subtitle}
            </p>
          )),
        ]}
      </div>

      {/* ── 4. Два раскрывающихся полубейджа (Task 21, без изменений) ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <CollapsibleHalfBadge
          label={AUDIENCE_LABEL}
          text={AUDIENCE_TEXT}
          isOpen={audienceOpen}
          onToggle={() => setAudienceOpen((prev) => !prev)}
        />
        <CollapsibleHalfBadge
          label={PURPOSE_LABEL}
          text={PURPOSE_TEXT}
          isOpen={purposeOpen}
          onToggle={() => setPurposeOpen((prev) => !prev)}
        />
      </div>

      </section>
    </div>
  );
}
