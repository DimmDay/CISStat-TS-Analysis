"use client";

// packages/ui/components/ModuleNav.tsx
//
// Навигация между модулями анализа (О платформе → Загрузка → Валидация →
// Предобработка → EDA → Моделирование → Прогнозирование → Задачи) --
// аналог верхних вкладок (st.tabs) в Streamlit-версии.
//
// «О платформе» ведёт на «/» (Task 25). Hover-аккордеон с 5 ссылками
// из HOME_ROUTES. JS-based hover (onMouseEnter/Leave).
// Справа — кнопка-триггер «Прогресс» (PROGR-4, аддендум §4.1; заменила
// «Логи событий» в том же слоте, EventsLogDrawer удалён §6.1).
// Один общий компонент -- используется в standalone и embedded.
//
// Общий для embedded и standalone -- пути одинаковые в обоих приложениях.
//
// Task w/n — реформатинг классических вкладок (подчёркнутые ссылки с
// border-b-2) в кликабельные бейджи-«таблетки» по образцу localnav
// apple.com/apple-intelligence ("Overview"/"iOS"/"macOS"):
//   - pill rounded-full; неактивный — светлая нейтральная заливка
//     (Apple: rgba(232,232,237,.5) → neutral-100), hover — темнее;
//   - активный — сплошная заливка фирменным индиго (bg-brand) и белый
//     текст (у Apple активный бейдж — тёмная заливка);
//   - ЕДИНСТВЕННОЕ отличие от образца по постановке тимлида: все
//     бейджи одинаковы по высоте и ширине, ширина каждого равна ширине
//     МАКСИМАЛЬНОГО бейджа. CSS-механика: inline-grid +
//     grid-auto-flow:column + grid-auto-columns:1fr — при
//     max-content-ширине контейнера fr-колонки выравниваются по самой
//     широкой (эмпирика проба на реальном Chromium: 5 бейджей разного
//     текста → ровно одинаковые 155.2×35px). Высота — единая h-9
//     (36px, как 36px localnav Apple) на каждом бейдже.
//   - Аккордеон «О платформе» (Task 25, 5 ссылок HOME_ROUTES)
//     СОХРАНЁН без изменений — реформатинг, не удаление функциональности;
//     панель absolute не участвует в расчёте ширин колонок (out of flow),
//     overflow-visible на строке бейджей сохраняет её видимой.
//
// Точечная правка (следом за Task w/n) — убрана горизонтальная линия под
// меню: border-b border-neutral-200 на <nav> удалён, остался только
// белый фон. Шапка ProductHeader над меню правится так же (симметрично),
// чтобы над/под строкой бейджей не было разделителей. Геометрия бейджей,
// аккордеон и «Логи событий» не затронуты.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useCallback } from "react";
import { ChevronDown, Workflow } from "lucide-react";
import { ProgressDrawer } from "./ProgressDrawer";
import { HOME_ROUTES } from "../lib/home-stops";

// ── Подменю «О платформе»: 5 из 6 HOME_ROUTES (без «Приступить к анализу») ──

const PLATFORM_SUBMENU = HOME_ROUTES.slice(0, 5);

// ── Типы ──────────────────────────────────────────────────────

interface ModuleLink {
  label: string;
  href: string;
}

const MODULES: ModuleLink[] = [
  { label: "Загрузка", href: "/upload" },
  { label: "Валидация", href: "/validation" },
  { label: "Предобработка", href: "/preprocessing" },
  { label: "Разведочный EDA", href: "/eda" },
  { label: "Моделирование", href: "/modeling" },
  { label: "Прогнозирование", href: "/forecasting" },
  { label: "Задачи", href: "/tasks" },
];

// ── Классы бейджа ──────────────────────────────────────────────
// Единая геометрия: h-9 (36px, равная высота), rounded-full (pill),
// whitespace-nowrap (ширина колонки задаёт самый длинный заголовок,
// а не перенос), justify-center (текст центрируется в равной ширине).
// Адаптив: <lg — компактный px-3/text-[13px], lg+ — px-4/text-sm.

const BADGE_BASE =
  "inline-flex h-9 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-3 text-[13px] transition-colors lg:px-4 lg:text-sm";

const badgeClassName = (active: boolean) =>
  active
    ? `${BADGE_BASE} bg-brand font-medium text-white`
    : `${BADGE_BASE} bg-neutral-100 text-neutral-700 hover:bg-neutral-200 hover:text-neutral-900`;

// ── Кнопка-триггер «Прогресс» (PROGR-4, аддендум §4.1) ─────────────
// Тот же слот справа, где была «Логи событий» (буквально заменяет её,
// не добавляется рядом). Форма -- овал по общему паттерну бейджей
// (BADGE_BASE): rounded-full, h-9, whitespace-nowrap, px-4/text-sm на
// широких экранах, px-3/text-[13px] на узких. Неактивная: белый фон,
// ТОНКАЯ (1px) фирменная рамка, индиго-текст. Активная: заливка
// индиго, белый ПОЛУЖИРНЫЙ текст -- font-semibold, а не font-medium
// активных модульных бейджей: осознанное отличие по прямому указанию
// тимлида (аддендум §4.1), не ошибка копирования паттерна.
// Доступность: aria-expanded/aria-controls на id панели, focus-visible
// ring. Иконка -- Workflow (тот же слот, что был ScrollText).

const PROGRESS_TRIGGER_BASE = `${BADGE_BASE} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1`;

// ── Компонент ──────────────────────────────────────────────────

export function ModuleNav() {
  const pathname = usePathname();
  const [progressOpen, setProgressOpen] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // «О платформе» активна, если pathname === "/" ИЛИ pathname совпадает
  // с одним из href подменю.
  const isPlatformActive =
    pathname === "/" ||
    PLATFORM_SUBMENU.some((r) => pathname === r.href);

  // JS-based hover: onMouseEnter/Leave на wrapper (включает триггер + панель).
  // Строка бейджей держит overflow-visible, чтобы absolute-панель
  // аккордеона не обрезалась.
  const handleDropdownEnter = useCallback(() => setDropdownOpen(true), []);
  const handleDropdownLeave = useCallback(() => setDropdownOpen(false), []);

  return (
    <>
      <nav
        aria-label="Навигация по модулям анализа"
        className="bg-white"
      >
        <div className="max-w-[1600px] mx-auto px-6 flex items-center justify-between gap-2 py-2.5">
          {/* ── Строка бейджей: равные ширины ПО МАКСИМАЛЬНОМУ бейджу ──
              inline-grid + grid-flow-col + auto-cols-fr: fr-колонки при
              max-content-ширине контейнера выравниваются по самой
              широкой (см. шапку файла) */}
          <div className="inline-grid grid-flow-col auto-cols-fr items-stretch gap-2 overflow-visible">
            {/* ── Бейдж «О платформе» с hover-аккордеоном ── */}
            <div
              className="relative"
              onMouseEnter={handleDropdownEnter}
              onMouseLeave={handleDropdownLeave}
            >
              <Link
                href="/"
                aria-haspopup="menu"
                aria-expanded={dropdownOpen}
                className={`${badgeClassName(isPlatformActive)} w-full`}
              >
                О платформе
                <ChevronDown
                  size={14}
                  aria-hidden="true"
                  className={`transition-transform ${dropdownOpen ? "rotate-180" : ""}`}
                />
              </Link>

              {/* Панель — видна только при dropdownOpen (JS-state).
                  Absolute → out of flow, ширину колонок не меняет. */}
              <div
                role="menu"
                aria-label="О платформе"
                className={`absolute top-full left-0 z-50 pt-1 transition-all duration-150 ${
                  dropdownOpen
                    ? "visible opacity-100"
                    : "invisible opacity-0"
                }`}
              >
                <div className="bg-white rounded-lg border border-neutral-200 shadow-lg py-1 min-w-[220px]">
                  {PLATFORM_SUBMENU.map((route) => {
                    const isActive = pathname === route.href;
                    return (
                      <Link
                        key={route.href + route.title}
                        href={route.href}
                        role="menuitem"
                        className={`block px-4 py-2 text-sm transition-colors ${
                          isActive
                            ? "text-brand bg-brand-light/50 font-medium"
                            : "text-neutral-700 hover:bg-neutral-50 hover:text-neutral-900"
                        }`}
                      >
                        {route.title}
                      </Link>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* ── Бейджи остальных модулей ── */}
            {MODULES.map((mod) => {
              const isActive =
                pathname === mod.href || pathname.startsWith(mod.href + "/");
              return (
                <Link
                  key={mod.href}
                  href={mod.href}
                  aria-current={isActive ? "page" : undefined}
                  className={badgeClassName(isActive)}
                >
                  {mod.label}
                </Link>
              );
            })}
          </div>

          <button
            type="button"
            onClick={() => setProgressOpen((previous) => !previous)}
            aria-expanded={progressOpen}
            aria-controls="progress-drawer"
            className={
              progressOpen
                ? `${PROGRESS_TRIGGER_BASE} bg-brand font-semibold text-white`
                : `${PROGRESS_TRIGGER_BASE} bg-white border border-brand text-brand hover:bg-brand-light/40`
            }
          >
            <Workflow size={14} aria-hidden="true" />
            <span className="hidden sm:inline">Прогресс</span>
          </button>
        </div>
      </nav>

      <ProgressDrawer open={progressOpen} onClose={() => setProgressOpen(false)} />
    </>
  );
}
