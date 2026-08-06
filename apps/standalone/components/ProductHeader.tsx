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

import Link from "next/link";
import { User } from "lucide-react";

const NAV_ITEMS = [
  { label: "Продукт", href: "/product" },
  { label: "Документация API", href: "/docs" },
  { label: "Тарифы", href: "/pricing" },
  { label: "Личный кабинет", href: "/dashboard" },
];

export function ProductHeader() {
  return (
    <div className="border-b border-neutral-200 bg-white">
      <div className="max-w-[1600px] mx-auto px-6 flex items-center justify-between py-2.5">
        <div className="flex items-center gap-6">
          <span className="font-semibold text-brand">CISStat TS Analysis</span>
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
