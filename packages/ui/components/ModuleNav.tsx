"use client";

// packages/ui/components/ModuleNav.tsx
//
// Навигация между модулями анализа (Загрузка → Валидация → Предобработка →
// EDA → Моделирование → Прогнозирование → Задачи) -- аналог верхних вкладок
// (st.tabs) в Streamlit-версии. Без этого компонента переключиться между
// модулями можно было только вручную вводя URL -- реальный пробел,
// обнаруженный по вопросу "как из Моделирования попасть в Предобработку".
//
// Общий для embedded и standalone -- пути одинаковые в обоих приложениях
// (см. README про то, что оба app используют общий /preprocessing и т.д.,
// а не /analytics/... vs /dashboard/... как было раньше).

import Link from "next/link";
import { usePathname } from "next/navigation";

const MODULES = [
  { label: "Загрузка", href: "/data/upload" },
  { label: "Валидация", href: "/validation" },
  { label: "Предобработка", href: "/preprocessing" },
  { label: "Разведочный EDA", href: "/eda" },
  { label: "Моделирование", href: "/modeling" },
  { label: "Прогнозирование", href: "/forecasting" },
  { label: "Задачи", href: "/tasks" },
];

export function ModuleNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Навигация по модулям анализа"
      className="flex items-center gap-1 border-b border-neutral-200 bg-white px-6 overflow-x-auto"
    >
      {MODULES.map((mod) => {
        const isActive = pathname === mod.href || pathname.startsWith(mod.href + "/");
        return (
          <Link
            key={mod.href}
            href={mod.href}
            className={`whitespace-nowrap px-4 py-3 text-sm border-b-2 transition-colors ${
              isActive
                ? "border-brand text-brand font-medium"
                : "border-transparent text-neutral-600 hover:text-neutral-900 hover:border-neutral-300"
            }`}
          >
            {mod.label}
          </Link>
        );
      })}
    </nav>
  );
}
