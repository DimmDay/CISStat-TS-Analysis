"use client";

// packages/ui/components/DecompositionBadges.tsx
//
// Бейджи декомпозиции под графиком остановки «График» -- "уровень шума
// в данных" на старте анализа (согласовано с тимлидом 2026-08-14).
//
// Данные -- GET /v1/session/dataset/decomposition (apps/api/decomposition_data.py),
// триггерится ПО КНОПКЕ (не авто) -- STL на statsmodels не мгновенная.
//
// applicable=false -- ЧЕСТНЫЙ отказ (найдено на реальных данных: STL не
// падает даже на семантически бессмысленном period -- годовые данные с
// period=12 по умолчанию дают "сезонность" из чистого шума). Для годовых/
// панельных/слишком коротких рядов бейджи явно объясняют reason, а не
// показывают 0% или фейковые цифры.

export interface DecompositionData {
  applicable: boolean;
  reason: string | null;
  frequency: string | null;
  frequency_label: string | null;
  period_used: number | null;
  n_points: number;
  method: string | null;
  trend_pct: number | null;
  seasonal_pct: number | null;
  cyclical_pct: number | null;
  resid_pct: number | null;
}

function Badge({ label, value, tone, hint }: { label: string; value: string; tone: string; hint?: string }) {
  return (
    <div className={`rounded-lg border px-3 py-2.5 ${tone}`} title={hint}>
      <p className="text-[11px] text-neutral-500">{label}</p>
      <p className="text-lg font-semibold font-mono">{value}</p>
    </div>
  );
}

export function DecompositionBadges({
  data,
  loading,
  onCompute,
  hasComputed,
}: {
  data: DecompositionData | null;
  loading: boolean;
  onCompute: () => void;
  hasComputed: boolean;
}) {
  if (!hasComputed) {
    return (
      <div className="rounded-lg border border-dashed border-neutral-300 px-4 py-4 text-center">
        <p className="text-xs text-neutral-500 mb-2">
          Разложение ряда на Тренд / Сезонность / Цикличность / Остаток -- индикатор уровня шума в данных.
          Расчёт (STL) может занять несколько секунд.
        </p>
        <button
          onClick={onCompute}
          disabled={loading}
          className="text-sm px-4 py-1.5 rounded border border-brand text-brand hover:bg-brand-light disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "Считаем…" : "Считать декомпозицию"}
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="rounded-lg border border-neutral-200 px-4 py-4 text-center text-sm text-neutral-500">
        Считаем декомпозицию…
      </div>
    );
  }

  if (!data || !data.applicable) {
    return (
      <div className="rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-3">
        <p className="text-sm text-neutral-600">
          Декомпозиция неприменима: {data?.reason ?? "неизвестная причина"}
        </p>
        <button onClick={onCompute} className="text-xs text-brand mt-2 underline">
          Пересчитать
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="grid grid-cols-4 gap-2">
        <Badge label="Тренд" value={`${data.trend_pct}%`} tone="border-neutral-200 bg-white" />
        <Badge label="Сезонность" value={`${data.seasonal_pct}%`} tone="border-neutral-200 bg-white" />
        <Badge
          label="Цикличность"
          value={`${data.cyclical_pct}%`}
          tone="border-neutral-200 bg-white"
          hint="Оценочная эвристика (тренд минус его скользящее среднее), не строгий метод STL"
        />
        <Badge
          label="Остаток (шум)"
          value={`${data.resid_pct}%`}
          tone={data.resid_pct !== null && data.resid_pct > 50 ? "border-amber-300 bg-amber-50" : "border-neutral-200 bg-white"}
        />
      </div>
      <p className="text-[11px] text-neutral-500 mt-1.5">
        {data.method} · частота: {data.frequency_label} · {data.n_points} точек · доли дисперсии, ≈100% суммарно
      </p>
    </div>
  );
}
