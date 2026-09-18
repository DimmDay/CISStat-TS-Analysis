"use client";

// apps/standalone/components/ProductHeader.tsx
//
// ⚠️ ЗАГЛУШКА -- шапка для самодостаточного продукта (внешние покупатели).
// Использует те же цвета/шрифт из @cisstat/ui (единая идентичность), но
// СВОЙ набор разделов -- внешнему клиенту не нужны "Форум"/"Мероприятия"
// комитета, ему нужны Docs/Pricing/Dashboard/вход.
//
// Заменить на финальный вариант, когда решите: логотип тот же, что у
// портала, или отдельный суб-бренд ("CISStat TS Analysis" как отдельный
// продукт под общим брендом)?
//
// Task 119/120: логотип обслуживается из public-каталога standalone-приложения,
// название семантически и визуально усилено до bold.
//
// Точечная правка (следом за Task w/n) — убрана горизонтальная линия под
// шапкой: border-b border-neutral-200 на корневом div удалён, остался
// только белый фон. ModuleNav под шапкой правится симметрично, чтобы
// между шапкой, строкой бейджей и контентом не было разделителей.
// Содержимое шапки (логотип, навигация, РУС/ENG, кабинет) не затронуто.
//
// Task DKT-1 (spec_dark_theme.md §4.6): переключатель темы СПРАВА, рядом
// с «РУС / ENG» — между ним и кнопкой кабинета (непосредственное
// соседство по постановке). Одна иконка, меняющаяся состоянием: Moon в
// светлой теме («включить тёмную»), Sun в тёмной («включить светлую»);
// lucide-react size={14}, паттерн соседа — text-neutral-500
// hover:text-neutral-900 (в тёмной теме те же классы — их значения
// токенизированы). Доступность: aria-label по состоянию, aria-pressed.

import Link from "next/link";
import Image from "next/image";
import { Moon, Sun, User } from "lucide-react";
import { useTheme } from "@cisstat/ui";

const NAV_ITEMS = [
  { label: "Продукт", href: "/product" },
  { label: "Документация API", href: "/docs" },
  { label: "Тарифы", href: "/pricing" },
  { label: "Личный кабинет", href: "/dashboard" },
];

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  const Icon = isDark ? Sun : Moon;
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? "Включить светлую тему" : "Включить тёмную тему"}
      aria-pressed={isDark}
      className="text-neutral-500 hover:text-neutral-900"
    >
      <Icon size={14} aria-hidden="true" />
    </button>
  );
}

export function ProductHeader() {
  return (
    <div className="bg-white">
      <div className="max-w-[1600px] mx-auto px-6 flex items-center justify-between py-2.5">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <div className="relative h-7 w-7 shrink-0">
              <Image
                src="/logo_TS.png"
                alt="CISStat TS Analysis"
                fill
                sizes="28px"
                className="object-contain"
                priority
              />
            </div>
            <strong className="text-[15px] font-bold text-brand">CISStat TS Analysis</strong>
          </div>
          <nav className="flex items-center gap-6 text-[13.5px]">
            {NAV_ITEMS.map((item) => (
              <Link key={item.href} href={item.href} className="text-neutral-600 hover:text-neutral-900">
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-5 text-[13px] text-neutral-600">
          <button type="button" className="text-neutral-500 hover:text-neutral-900">РУС / ENG</button>
          <ThemeToggle />
          <button
            type="button"
            aria-label="Личный кабинет"
            className="flex h-7 w-7 items-center justify-center rounded-full bg-neutral-200 hover:bg-neutral-300"
          >
            <User size={14} aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}
