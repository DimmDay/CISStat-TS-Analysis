"use client";

// packages/ui/components/MentorInlineWarning.tsx
//
// Инлайн-баннер предупреждений Наставника внутри Мастера остановки
// (Task PROGR-6, spec_progress.md §7.2/§12 п.8). Рендерится НАД кнопкой
// «Применить исправления» на шаге «Применение» после preview.
//
// §12 п.8 дословно: НЕ блокирует кнопку -- агрессивная коррекция иногда
// осознанный выбор эксперта; «делает предупреждение визуально заметным
// (цветной баннер с явной формулировкой „Продолжить всё равно"), а не
// тихой инлайн-подсказкой». Кнопка применения принадлежит Мастеру и
// этим компонентом не управляется -- блокировка физически невозможна.
//
// Список предупреждений -- ВЕСЬ список сработавших правил §7.2
// (проблемы независимы); «Продолжить всё равно» скрывает баннер до
// следующего preview (новый preview -- новая проверка).

import { useEffect, useState } from "react";
import type { SanityWarningInfo } from "../lib/mentor";

interface MentorInlineWarningProps {
  warnings: SanityWarningInfo[];
}

export function MentorInlineWarning({ warnings }: MentorInlineWarningProps) {
  const [dismissed, setDismissed] = useState(false);

  // Новый preview -> новый исход -> баннер снова виден (дисмиссы живут
  // только внутри одного preview-исхода).
  useEffect(() => {
    setDismissed(false);
  }, [warnings]);

  if (!warnings.length || dismissed) return null;

  return (
    <div
      role="alert"
      aria-label="Предупреждения Наставника"
      className="mt-3 rounded border border-amber-300 bg-amber-50 p-3"
    >
      <p className="text-xs font-semibold text-amber-800">Наставник: проверка предпросмотра</p>
      <ul className="mt-1.5 space-y-1.5">
        {warnings.map((warning) => (
          <li key={warning.rule_id} className="text-xs text-neutral-700">
            <span
              className={`mr-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${
                warning.severity === "warning"
                  ? "bg-amber-100 text-amber-800"
                  : "bg-neutral-100 text-neutral-600"
              }`}
            >
              {warning.severity === "warning" ? "предупреждение" : "замечание"}
            </span>
            {warning.message}
            {warning.suggested_action && (
              <span className="mt-0.5 block text-[11px] text-neutral-500">
                {warning.suggested_action}
              </span>
            )}
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="mt-2 text-xs font-medium text-amber-800 underline hover:text-amber-900"
      >
        Продолжить всё равно
      </button>
    </div>
  );
}
