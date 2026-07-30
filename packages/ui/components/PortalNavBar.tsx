"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { User } from "lucide-react";

const NAV_ITEMS = [
  { label: "Статистика", href: "/statistics" },
  { label: "Аналитика", href: "/analytics" },
  { label: "Метаданные", href: "/metadata" },
  { label: "Публикации", href: "/publications" },
  { label: "Мероприятия", href: "/events" },
  { label: "Форум", href: "/forum" },
  { label: "Проекты", href: "/projects" },
  { label: "О комитете", href: "/about" },
];

export function PortalNavBar() {
  const pathname = usePathname();

  return (
    <div className="flex items-center justify-between border-b border-neutral-200 bg-white px-5 py-2.5">
      <nav aria-label="Основная навигация" className="flex items-center gap-6 text-[13.5px]">
        {NAV_ITEMS.map((item, i) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <span key={item.href} className="relative">
              <Link
                href={item.href}
                className={isActive ? "font-medium text-neutral-900" : "text-neutral-600 hover:text-neutral-900"}
              >
                {item.label}
              </Link>             
            </span>
          );
        })}
      </nav>
      <div className="flex items-center gap-5 text-[13px] text-neutral-600">
        <button type="button" className="text-neutral-500 hover:text-neutral-900">
          РУС / ENG
        </button>
        <button
          type="button"
          aria-label="Личный кабинет"
          className="flex h-7 w-7 items-center justify-center rounded-full bg-neutral-200 hover:bg-neutral-300"
        >
          <User size={14} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
