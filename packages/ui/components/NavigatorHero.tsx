"use client";

// packages/ui/components/NavigatorHero.tsx
//
// Верхняя часть главной страницы "Навигатор" в обоих apps/* (standalone и
// embedded). Презентационный компонент с локальной интерактивностью:
//   - H1 "Анализ временных рядов — от файла до прогноза"
//   - ряд из 6 числовых бейджей (соответствуют 6 этапам пайплайна 1:1)
//   - 2 полубейджа на 1/2 ширины каждый: «Для кого» и «Для чего» —
//     РАСКРЫВАЮЩИЕСЯ по типу селектора (Task 21):
//       • закрытое состояние (по умолчанию): виден только заголовок + чеврон ↓
//       • клик по триггеру → под заголовком раскрывается текст, чеврон ↑
//       • состояния двух бейджей НЕЗАВИСИМЫ (не accordion)
//   - декоративный разделитель после hero-секции (отделяет от Путеводителя)
//
// a11y-контракт:
//   - Триггер — <button> с aria-expanded (false/true) и aria-controls
//     (указывает на id текстовой панели).
//   - Текстовая панель получает id, совпадающий с aria-controls триггера.
//   - Иконка чеврона имеет role="img" и aria-label для скринридеров.

import { useState } from "react";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import {
  NAVIGATOR_BADGES,
  AUDIENCE_LABEL,
  AUDIENCE_TEXT,
  PURPOSE_LABEL,
  PURPOSE_TEXT,
} from "../lib/navigator-stops";

// ── Вспомогательный компонент: раскрывающийся полубейдж ──────────────
//
// Вынесен, чтобы не плодить копию разметки для двух экземпляров (урок
// MIGRATION_ARCHITECTURE.md §2.1 — «одна копия каждой фичи»).
// Контролируемое состояние (isOpen/onToggle) живёт в родителе — это даёт
// независимость двух бейджей (родитель хранит 2 отдельных useState).

interface CollapsibleHalfBadgeProps {
  /** Заголовок бейджа (например, "Для кого:"). Виден ВСЕГДА. */
  label: string;
  /** Текст, который раскрывается при клике. */
  text: string;
  /** Текущее состояние: true = раскрыт, false = свёрнут. */
  isOpen: boolean;
  /** Колбэк переключения состояния. */
  onToggle: () => void;
}

function CollapsibleHalfBadge({
  label,
  text,
  isOpen,
  onToggle,
}: CollapsibleHalfBadgeProps) {
  // Стабильный id для aria-controls — генерируется из label, чтобы
  // совпадать между рендерами (React не должен пересоздавать id).
  // Используем transliteration-agnostic sanitize: только буквы/цифры/дефис.
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
  // Независимые состояния двух полубейджей (не accordion: можно открыть
  // оба, можно закрыть оба, поведение каждого не зависит от другого).
  // По умолчанию оба СВОРНУТЫ — «по типу селектора»: закрыто, пока не
  // кликнули (требование Task 21).
  const [audienceOpen, setAudienceOpen] = useState(false);
  const [purposeOpen, setPurposeOpen] = useState(false);

  return (
    <div className="space-y-6">
      {/* ── 3. Заголовок ── */}
      <h1 className="font-sans text-2xl font-semibold tracking-tight text-[#1e3a8a]">
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
            <span className="text-sm text-neutral-700 leading-snug">
              {badge.label}
            </span>
          </li>
        ))}
      </ol>

      {/* ── 5–6. Два раскрывающихся полубейджа на 1/2 ширины ──
          Task 21: полубейджи делаем раскрывающимися по типу селектора —
          закрытое состояние показывает только заголовок «ДЛЯ КОГО» /
          «ДЛЯ ЧЕГО» + чеврон справа, клик по триггеру раскрывает текст. */}
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

      {/* ── 7. Декоративный разделитель ──
          Тонкая светло-серая черта на всю ширину контейнера, отделяет
          hero-секцию (заголовок + бейджи + Для кого/Для чего) от
          функционального блока «Путеводитель» ниже. space-y-6 на корневом
          контейнере уже даёт вертикальный отступ сверху (24px), поэтому
          дополнительных my-* не добавляем — иначе отступ задвоится. */}
      <div className="h-px w-full bg-neutral-200" aria-hidden="true" />
    </div>
  );
}
