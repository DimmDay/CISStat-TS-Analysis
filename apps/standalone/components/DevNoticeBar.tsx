"use client";

// apps/standalone/components/DevNoticeBar.tsx
//
// Task UI-DEVNOTICE-1 (2026-11-09), вариант A постановки тимлида:
// dismissible-полоса «Платформа в активной разработке» над ProductHeader
// (точка вставки — apps/standalone/app/layout.tsx, все страницы
// standalone одной вставкой). Чип «β» у бренда — соседний файл
// ProductHeader.tsx (тот же Task ID).
//
// Дизайн-гвардейлы постановки: одна строка ≤80 символов, 13px,
// НЕЙТРАЛЬНЫЕ токены (bg-white/text-neutral-600 — это информация, а не
// алерт: без warning-жёлтого и без произвольных цветов, инвентарь
// произвольных классов heading-indigo-calibration не пополняется);
// без анимаций; контент не блокируется; закрытие — НАВСЕГДА, выбор
// помнится в localStorage (паттерн ключа темы «cisstat-theme»).
//
// ГИДРАЦИЯ: до монтирования компонент рендерит null (SSR-вывод пуст,
// пин — DevNoticeBar.test.tsx). Стратегия «скрыто до доказанного
// показа»: закрывшие пользователи не видят ни мигания, ни сдвига макета
// на каждой загрузке; впервые открывшие получают полосу сразу после
// гидратации. Обратная стратегия (SSR-рендер + скрытие в эффекте) давала
// бы сдвиг макета у каждого вернувшегося пользователя.
//
// A11Y: role="status" — семантика статусного уведомления (не alert —
// полоса информационная, не требует немедленного внимания); имя кнопки
// закрытия — «Скрыть уведомление», иконка aria-hidden.
//
// ЯЗЫК: html lang="ru", переключатель «РУС / ENG» в шапке статичен
// (i18n-контекста в standalone нет) — рендерится RU-строка; ENG-строка
// закреплена константой как контракт будущего переключателя (пин в
// DevNoticeBar.test.tsx). Обе строки утверждены тимлидом в постановке.

import { useEffect, useState } from "react";
import { X } from "lucide-react";

export const DEV_NOTICE_TEXTS = {
  ru: "Платформа в активной разработке — данные и функциональность могут меняться",
  eng: "Under active development — data and features may change",
} as const;

// Ключ выбора «не показывать» — то же пространство имён, что cisstat-theme.
export const DEV_NOTICE_DISMISS_KEY = "cisstat-dev-notice-dismissed";

export function DevNoticeBar() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(DEV_NOTICE_DISMISS_KEY) !== "1") {
        setVisible(true);
      }
    } catch {
      // localStorage недоступен (приватный режим/политики) — показываем
      // полосу: недоступность хранилища не должна скрывать уведомление.
      setVisible(true);
    }
  }, []);

  if (!visible) return null;

  const dismiss = () => {
    try {
      window.localStorage.setItem(DEV_NOTICE_DISMISS_KEY, "1");
    } catch {
      // Не блокируем UI: при недоступном хранилище полоса закроется
      // только до перезагрузки страницы — приемлемая деградация.
    }
    setVisible(false);
  };

  return (
    <div data-testid="dev-notice-bar" role="status" className="bg-white">
      {/* Геометрия повторяет шапку: max-w-[1600px] px-6 — текст полосы
          выровнен с брендом/меню; py-1.5 — строка ~32px, шапка не «трёхэтажится». */}
      <div className="relative max-w-[1600px] mx-auto px-6 py-1.5 text-center">
        <p className="text-[13px] leading-5 text-neutral-600">
          {DEV_NOTICE_TEXTS.ru}
        </p>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Скрыть уведомление"
          className="absolute right-6 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-neutral-900"
        >
          <X size={14} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
