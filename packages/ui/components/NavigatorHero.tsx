"use client";

// packages/ui/components/NavigatorHero.tsx
//
// Верхняя часть страницы «Навигатор» в обоих apps/* (standalone и embedded).
// Презентационный компонент с локальной интерактивностью:
//   - H1 «Ключевые этапы исследования временного ряда»
//   - 6 chevron-стрелок в ряд (светло-серый фон, зелёная цифра)
//   - Под каждой стрелкой — заголовок (пронумерованный) + поддерживающий текст
//   - 2 раскрывающихся полубейджа «Для кого» / «Для чего» (Task 21)
//   - декоративный разделитель
//
// a11y-контракт:
//   - Chevron-ряд — aria-label="Этапы анализа", цифры aria-hidden
//   - Текстовые блоки — semantic <p>, видны всем
//   - CollapsibleHalfBadge триггеры — <button> с aria-expanded/aria-controls

import { useState } from "react";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import {
  NAVIGATOR_BADGES,
  AUDIENCE_LABEL,
  AUDIENCE_TEXT,
  PURPOSE_LABEL,
  PURPOSE_TEXT,
} from "../lib/navigator-stops";

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
  const [audienceOpen, setAudienceOpen] = useState(false);
  const [purposeOpen, setPurposeOpen] = useState(false);

  return (
    <div className="space-y-6">
      {/* ── 1. Заголовок ── */}
      <h1 className="font-sans text-2xl font-normal tracking-tight text-[#1e3a8a]">
        Ключевые этапы исследования временного ряда
      </h1>

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
              className="pt-1 text-sm font-semibold text-neutral-800"
            >
              {b.num}. {b.label}
            </p>
          )),
          ...NAVIGATOR_BADGES.map((b) => (
            <p
              key={`sub-${b.num}`}
              className="text-xs text-neutral-500 leading-relaxed"
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

      {/* ── 5. Декоративный разделитель ── */}
      <div className="h-px w-full bg-neutral-200" aria-hidden="true" />
    </div>
  );
}
