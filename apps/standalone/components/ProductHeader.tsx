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
//
// Задача «кегль бренда = высота логотипа»: логотип — бокс h-7 (28px,
// object-contain заполняет по высоте). Кегль бренда поднят с text-[15px]
// до text-[28px] — высота шрифта равна высоте логотипа. Увеличение
// пропорциональное: шрифт (Inter по наследованию) и цвет (text-brand)
// не менялись. tracking-tight (-0.025em) — чуть уменьшенное
// межбуквенное расстояние. leading-none — строковый бокс 28px: шапка по
// вертикали остаётся обусловленной элементами h-7, текстовый блок равен
// высоте логотипа.
//
// BRND-2 (2026-09-24, следом за правкой тимлида font-bold→font-semibold
// в c7d8344): (1) начертание бренда — normal (font-normal; <strong>
// сохранён как семантический акцент, визуальный вес задаёт класс).
// (2) Логотип и бренд обёрнуты в одну ссылку на главную standalone
// https://ts-standalone.vercel.app/ — клик по любому из них ведёт на
// главную. Ссылка — обычный <a> с явным URL по постановке (не next/link:
// абсолютный внешний адрес, клиентская навигация не требуется);
// aria-label даёт ссылке внятное имя и убирает дублирование alt логотипа
// и текста бренда при чтении скринридером. Геометрия (flex items-center
// gap-2) перенесена с прежнего div на <a> без изменений.
//
// UI-HOME-HEADER-1 (2026-10-15): (1) пункты меню («Обучение» — замена
// «Продукт» с href /education — страница «Обучение и база знаний» EDU-1;
// маршрута /product в standalone нет, «Документация API», «Тарифы»,
// «Личный кабинет» без изменений) перемещены ВПРАВО — в правый контейнер
// перед «РУС / ENG», с отступом меню от «РУС / ENG» (mr-5 меню + gap-5
// контейнера = 40px — крупнее внутри-менюного шага 24px и правого 20px).
// (2) Слева, после бренда, с отступом gap-6 левой группы — некликабельный
// слоган «Цифровая научно-исследовательская лаборатория»: обычный span
// (не ссылка/кнопка, вне ссылки бренда), кегль/вес/трекинг как у бренда
// (text-[20px] leading-none font-normal tracking-tight), серый токен
// text-neutral-600 (светлая #525252; тёмная ревизия #B5B8C1 подставляется
// платформенным контрактом DKT «имена классов не меняются — меняются
// значения», dark:-ветвлений нет), whitespace-nowrap.
// (3) Весь текст меню выровнен по нижней границе «CISStat TS Analysis»:
// выравниваются БАЗОВЫЕ линии текстов (типографская «нижняя граница»
// строки для кеглей разного размера; замер живой страницы до задачи,
// Range API, 1600px: нижняя граница текста бренда 36px, «Продукт»
// 31.9px, «РУС / ENG» 31.25px — меню висело на ~4px выше). Конструкция:
// ряд и группы СОХРАНЯЮТ items-center (позиции логотипа, бренда и иконок
// не меняются — байт-в-байт к живой странице до задачи), а мелкие тексты
// получают документированный метрический сдвиг relative top-[2.4px]:
// при items-center базовая линия текста кегля s сидит на
// 14px + 0.364×s от верха 28px ряда (0.364 = (asc−desc)/2 метрик Inter;
// Inter зафиксирован next/font — метрики стабильны), поэтому разница
// базовых линий бренда (20px) и меню (13.5/13px) = 0.364×Δкегля ≈ 2.4px
// и НЕ устранима выбором line-height. items-baseline (браузерное
// выравнивание базовых линий) был реализован и отвергнут верификацией:
// флекс-линия правого контейнера вырастала до 28px (аватар h-7),
// self-end притапливал иконки на 6px в нижний паддинг шапки (аватар
// 16..44 вместо 10..38) — позиция иконок дороже. Итог: базовые линии
// бренда, слогана, меню и «РУС / ENG» совпадают с точностью 0.04–0.15px
// (браузерный замер dev-сервера), иконки/логотип/бренд — без сдвигов,
// высота шапки 48px сохранена. Структурные пины —
// product-header-nav-slogan.test.tsx.

import Link from "next/link";
import Image from "next/image";
import { Moon, Sun, User } from "lucide-react";
import { useTheme } from "@cisstat/ui";

const NAV_ITEMS = [
  // UI-HOME-HEADER-1: «Продукт» → «Обучение»; href /education —
  // существующая страница «Обучение и база знаний» (EDU-1, второй бейдж
  // главной). Маршрута /product в standalone не существует.
  { label: "Обучение", href: "/education" },
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
      {/* UI-HOME-HEADER-1: ряд items-center СОХРАНЁН — логотип, бренд и
          иконки не сдвигаются; нижнее выравнивание текстов — метрический
          сдвиг top-[2.4px] на мелких текстах (см. шапку файла). */}
      <div className="max-w-[1600px] mx-auto px-6 flex items-center justify-between py-2.5">
        <div className="flex items-center gap-6">
          <a
            href="https://ts-standalone.vercel.app/"
            aria-label="CISStat TS Analysis — на главную"
            className="flex items-center gap-2"
          >
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
            <strong className="text-[20px] leading-none font-normal tracking-tight text-brand">CISStat TS Analysis</strong>
          </a>
          {/* Некликабельный слоган (UI-HOME-HEADER-1): обычный span вне
              ссылки бренда; кегль/вес как у бренда, серый токен
              text-neutral-600 (тёмная ревизия — платформенным контрактом
              DKT, без dark:-ветвлений). */}
          <span className="text-[20px] leading-none font-normal tracking-tight text-neutral-600 whitespace-nowrap">
            Цифровая научно-исследовательская лаборатория
          </span>
        </div>
        <div className="flex items-center gap-5 text-[13px] text-neutral-600">
          {/* Меню перемещено вправо (UI-HOME-HEADER-1): перед «РУС / ENG»,
              отступ mr-5 + gap-5 контейнера = 40px. top-[2.4px] — метрический
              сдвиг базовой линии к базовой линии бренда (см. шапку файла). */}
          <nav className="relative top-[2.4px] flex items-center gap-6 text-[13.5px] mr-5">
            {NAV_ITEMS.map((item) => (
              <Link key={item.href} href={item.href} className="text-neutral-600 hover:text-neutral-900">
                {item.label}
              </Link>
            ))}
          </nav>
          <button type="button" className="relative top-[2.4px] text-neutral-500 hover:text-neutral-900">РУС / ENG</button>
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
