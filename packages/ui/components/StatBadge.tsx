"use client";

// packages/ui/components/StatBadge.tsx
//
// Общий stat-бейдж для сеток главной страницы (Задача M-03, 2026-09-12):
//   - верхняя секция (HomeHero) — «Анализ временных рядов…»
//   - нижняя секция (HomeCapabilities) — «Исследование данных…»
//
// Требование тимлида: размер бейджей секций должен быть одинаков.
// Единственность компонента гарантирует совпадение размеров по
// построению: фиксированная высота подписи (h-7 = 2 строки при
// text-[11px]/leading-tight + line-clamp-2 как страховка от
// переполнения), компактный паддинг px-3/py-3, собственные рамка
// border-neutral-200 и скругление rounded-xl, светло-серый фон
// bg-neutral-100. Ширину задаёт колонка сетки STAT_GRID_CLASS
// (2/3/6 колонок), поэтому в обеих секциях бейджи геометрически
// идентичны. Отступ от границ страницы — 24px (px-6 контейнера <main>).
//
// a11y: семантика <dl>/<dt>/<dd> родительской сетки сохраняется —
// компонент рендерит пару dd (значение) + dt (подпись).

export function StatBadge({ value, label }: { value: string; label: string }) {
  return (
    <div className="bg-neutral-100 px-3 py-3 text-center rounded-xl border border-neutral-200">
      <dd className="text-xl font-semibold text-brand leading-none tracking-tight">
        {value}
      </dd>
      <dt className="mt-1.5 h-7 text-[11px] font-medium uppercase tracking-wide text-neutral-500 leading-tight line-clamp-2">
        {label}
      </dt>
    </div>
  );
}
