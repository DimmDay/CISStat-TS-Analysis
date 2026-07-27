"use client";

// packages/ui/components/EventsLogDrawer.tsx
//
// Выдвижная панель лога событий -- открывается по клику на колокольчик
// в DatasetContextBar, не занимает место постоянно (решение по фидбэку:
// "лог как выдвижная панель по клику, а не постоянный блок").

import { useAppShell } from "../context/AppShellContext";

const LEVEL_COLOR: Record<string, string> = {
  INFO: "text-blue-600",
  WARNING: "text-amber-600",
  ERROR: "text-red-600",
};

export function EventsLogDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { log, clearLog } = useAppShell();

  return (
    <>
      {/* Затемнение фона -- закрывает панель по клику вне неё */}
      {open && (
        <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} aria-hidden />
      )}

      <aside
        className={`fixed top-0 right-0 h-full w-80 bg-white shadow-xl z-50 transform transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-200">
          <h3 className="font-semibold">Лог событий</h3>
          <button onClick={onClose} aria-label="Закрыть" className="text-neutral-500 hover:text-neutral-900">
            ✕
          </button>
        </div>

        <div className="overflow-y-auto h-[calc(100%-96px)] feed-scroll">
          {log.length === 0 ? (
            <p className="p-4 text-sm text-neutral-500">Событий пока нет.</p>
          ) : (
            <ul className="divide-y divide-neutral-100">
              {log.map((entry) => (
                <li key={entry.id} className="px-4 py-2 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-neutral-400">{entry.time}</span>
                    <span className={`text-xs font-medium ${LEVEL_COLOR[entry.level]}`}>{entry.level}</span>
                  </div>
                  <p className="text-neutral-700">{entry.message}</p>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="border-t border-neutral-200 px-4 py-3">
          <button
            onClick={clearLog}
            className="text-sm text-neutral-500 hover:text-neutral-900 w-full text-left"
          >
            Очистить лог
          </button>
        </div>
      </aside>
    </>
  );
}
