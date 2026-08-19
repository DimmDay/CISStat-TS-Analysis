"use client";

// packages/ui/components/ModuleNav.tsx
//
// Навигация между модулями анализа (О платформе → Загрузка → Валидация →
// Предобработка → EDA → Моделирование → Прогнозирование → Задачи) --
// аналог верхних вкладок (st.tabs) в Streamlit-версии.
//
// «О платформе» ведёт на «/» (Task 25). Hover-аккордеон с 5 ссылками
// из HOME_ROUTES. JS-based hover (onMouseEnter/Leave).
// Справа — "Логи событий".
// Один общий компонент -- используется в standalone и embedded.
//
// Общий для embedded и standalone -- пути одинаковые в обоих приложениях.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useCallback } from "react";
import { ChevronDown, ScrollText } from "lucide-react";
import { useAppShell } from "../context/AppShellContext";
import { EventsLogDrawer } from "./EventsLogDrawer";
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

// ── Компонент ──────────────────────────────────────────────────

export function ModuleNav() {
  const pathname = usePathname();
  const { log } = useAppShell();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // «О платформе» активна, если pathname === "/" ИЛИ pathname совпадает
  // с одним из href подменю.
  const isPlatformActive =
    pathname === "/" ||
    PLATFORM_SUBMENU.some((r) => pathname === r.href);

  // JS-based hover: onMouseEnter/Leave на wrapper (включает триггер + панель).
  // При открытом дропдауне — overflow-visible на родительском flex,
  // чтобы absolute-панель не обрезалась.
  const handleDropdownEnter = useCallback(() => setDropdownOpen(true), []);
  const handleDropdownLeave = useCallback(() => setDropdownOpen(false), []);

  return (
    <>
      <nav
        aria-label="Навигация по модулям анализа"
        className="border-b border-neutral-200 bg-white"
      >
        <div className="max-w-[1600px] mx-auto px-6 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1 overflow-visible">
            {/* ── «О платформе» с hover-аккордеоном ── */}
            <div
              className="relative"
              onMouseEnter={handleDropdownEnter}
              onMouseLeave={handleDropdownLeave}
            >
              <Link
                href="/"
                aria-haspopup="menu"
                aria-expanded={dropdownOpen}
                className={`whitespace-nowrap inline-flex items-center gap-1.5 px-4 py-3 text-sm border-b-2 transition-colors ${
                  isPlatformActive
                    ? "border-brand text-brand font-medium"
                    : "border-transparent text-neutral-600 hover:text-neutral-900 hover:border-neutral-300"
                }`}
              >
                О платформе
                <ChevronDown
                  size={14}
                  aria-hidden="true"
                  className={`transition-transform ${dropdownOpen ? "rotate-180" : ""}`}
                />
              </Link>

              {/* Панель — видна только при dropdownOpen (JS-state). */}
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

            {/* ── Остальные модули ── */}
            {MODULES.map((mod) => {
              const isActive =
                pathname === mod.href || pathname.startsWith(mod.href + "/");
              return (
                <Link
                  key={mod.href}
                  href={mod.href}
                  className={`whitespace-nowrap inline-flex items-center gap-1.5 px-4 py-3 text-sm border-b-2 transition-colors ${
                    isActive
                      ? "border-brand text-brand font-medium"
                      : "border-transparent text-neutral-600 hover:text-neutral-900 hover:border-neutral-300"
                  }`}
                >
                  {mod.label}
                </Link>
              );
            })}
          </div>

          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="relative shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded text-sm text-neutral-600 hover:text-neutral-900 hover:bg-neutral-50 transition-colors"
            aria-label="Логи событий"
          >
            <ScrollText size={14} aria-hidden="true" />
            <span className="hidden sm:inline">Логи событий</span>
            {log.length > 0 && (
              <span className="rounded-full bg-brand text-white text-[9px] px-1.5 py-0.5 leading-none">
                {log.length}
              </span>
            )}
          </button>
        </div>
      </nav>

      <EventsLogDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
}
