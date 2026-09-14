"use client";

// packages/ui/components/ForecastHistoryList.tsx
//
// Детальный список прогнозов внутри модуля (spec_forecasting2.md §8):
// микро-уровень (параметры, метрики, выбор для сравнения), дополняет
// будущую панель «Прогресс» (макро-уровень), не дублирует её.

import type { ForecastRun } from "../lib/forecasting";

export function ForecastHistoryList({
  forecasts,
  activeForecastId,
  selectedForCompare,
  onSelect,
  onToggleCompare,
}: {
  forecasts: ForecastRun[];
  activeForecastId: string | null;
  selectedForCompare: string[];
  onSelect: (forecastId: string) => void;
  onToggleCompare: (forecastId: string) => void;
}) {
  if (forecasts.length === 0) {
    return (
      <p className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2 text-[11px] text-neutral-500" data-testid="forecast-history-empty">
        Прогнозов пока нет. Постройте первый прогноз по Model Card.
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-1.5" data-testid="forecast-history">
      {forecasts.map((run) => {
        const isActive = run.forecast_id === activeForecastId;
        const isChecked = selectedForCompare.includes(run.forecast_id);
        return (
          <li
            key={run.forecast_id}
            className={`rounded border px-2.5 py-2 text-[11px] ${
              isActive ? "border-brand bg-brand-light/50" : "border-neutral-200 bg-white"
            }`}
            data-testid="forecast-history-item"
          >
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => onSelect(run.forecast_id)}
                className="flex-1 text-left font-medium text-neutral-800 hover:text-brand"
                aria-current={isActive ? "true" : undefined}
              >
                {run.model_name}
                <span className="block text-[10px] font-normal text-neutral-500">
                  H={run.horizon} · α={run.alpha_effective} · {run.ci_method}
                </span>
              </button>
              <label className="flex shrink-0 items-center gap-1 text-[10px] text-neutral-500">
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => onToggleCompare(run.forecast_id)}
                  aria-label={`Выбрать прогноз ${run.model_name} для сравнения`}
                  data-testid={`compare-check-${run.forecast_id}`}
                />
                сравнить
              </label>
            </div>
            {run.warnings.length > 0 && (
              <p className="mt-1 border-t border-amber-100 pt-1 text-[10px] text-amber-700" data-testid="history-item-warning">
                {run.warnings[0]}
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
