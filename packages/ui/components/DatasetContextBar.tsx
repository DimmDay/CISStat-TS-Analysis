"use client";

// packages/ui/components/DatasetContextBar.tsx
//
// Лёгкая, глобальная строка контекста -- НЕ полноразмерная боковая
// панель. Показывает, какой датасет сейчас активен (нужно на любой
// странице), и ссылку «Логи событий» для лога (открывает
// выдвижную панель по клику, не занимает место постоянно).

import { useState } from "react";
import Link from "next/link";
import { useAppShell } from "../context/AppShellContext";
import { EventsLogDrawer } from "./EventsLogDrawer";

export function DatasetContextBar() {
  const { activeDataset, log } = useAppShell();
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <>
      <div className="flex items-center justify-between border-b border-neutral-100 bg-neutral-50 px-6 py-2 text-sm">
        <div className="flex items-center gap-2 text-neutral-600">
          {activeDataset ? (
            <>
              <span className="font-medium text-neutral-900">📄 {activeDataset.name}</span>
              <span className="text-neutral-400">·</span>
              <span>{activeDataset.rows.toLocaleString("ru-RU")} строк</span>
              <span className="text-neutral-400">·</span>
              <span>{activeDataset.sizeLabel}</span>
              <Link href="/data/upload" className="ml-2 text-brand hover:underline">
                Изменить
              </Link>
            </>
          ) : (
            <Link href="/data/upload" className="text-brand hover:underline">
              Загрузить датасет →
            </Link>
          )}
        </div>

        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          className="relative flex items-center gap-1 text-brand hover:underline font-normal"
          aria-label="Логи событий"
        >
          Логи событий
          {log.length > 0 && (
            <span className="rounded-full bg-brand text-white text-[9px] px-1.5 py-0.5 leading-none">
              {log.length}
            </span>
          )}
        </button>
      </div>

      <EventsLogDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
}
