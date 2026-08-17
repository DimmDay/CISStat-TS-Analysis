"use client";

// packages/ui/components/ModuleNav.tsx
//
// Навигация между модулями анализа (Навигатор → Загрузка → Валидация →
// Предобработка → EDA → Моделирование → Прогнозирование → Задачи) --
// аналог верхних вкладок (st.tabs) в Streamlit-версии.
//
// ИЗМЕНЕНИЕ (по решению тимлида): "Навигатор" добавлен первым пунктом --
// ведёт на "/" (sessions-aware Home / путеводитель, см.
// EmbeddedHome.tsx и StandaloneHome.tsx). Справа добавлены "Логи
// событий" -- перенесены сюда из DatasetContextBar.tsx (компонент
// удалён: строка "Загрузить датасет" потеряла актуальность теперь,
// когда Home сама показывает "Рабочий стол"/онбординг). Один общий
// компонент -- поэтому "Логи событий" отражаются одинаково и в
// standalone, и в embedded, без дублирования кода.
//
// Общий для embedded и standalone -- пути одинаковые в обоих приложениях.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Compass, ScrollText } from "lucide-react";
import { useAppShell } from "../context/AppShellContext";
import { EventsLogDrawer } from "./EventsLogDrawer";

interface ModuleLink {
  label: string;
  href: string;
  icon?: typeof Compass;
}

const MODULES: ModuleLink[] = [
  { label: "Навигатор", href: "/", icon: Compass },
  { label: "Загрузка", href: "/upload" },
  { label: "Валидация", href: "/validation" },
  { label: "Предобработка", href: "/preprocessing" },
  { label: "Разведочный EDA", href: "/eda" },
  { label: "Моделирование", href: "/modeling" },
  { label: "Прогнозирование", href: "/forecasting" },
  { label: "Задачи", href: "/tasks" },
];

export function ModuleNav() {
  const pathname = usePathname();
  const { log } = useAppShell();
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <>
      <nav
        aria-label="Навигация по модулям анализа"
        className="border-b border-neutral-200 bg-white"
      >
        <div className="max-w-[1600px] mx-auto px-6 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1 overflow-x-auto">
            {MODULES.map((mod) => {
              // "Навигатор" (/) активен только на самой главной, иначе
              // "/" — префикс всех путей и подсветит вкладку постоянно.
              const isActive =
                mod.href === "/" ? pathname === "/" : pathname === mod.href || pathname.startsWith(mod.href + "/");
              const Icon = mod.icon;
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
                  {Icon && <Icon size={14} aria-hidden="true" />}
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
