"use client";

// packages/ui/components/ForecastAccuracyPanel.tsx
//
// «Ожидаемая точность (по результатам бэктеста)» -- spec_forecasting2.md §5.4.
// Методологическая оговорка ОБЯЗАТЕЛЬНА к отображению: для реального будущего
// прогноза метрики не вычисляются заново (у будущих точек нет фактов) --
// показываются ИСТОРИЧЕСКИЕ метрики той же модели с бэктеста. Формулировка
// «Точность этого прогноза» запрещена -- платформа не обещает недостижимое.

import type { ForecastRun } from "../lib/forecasting";

const METRIC_LABELS: Array<{ key: string; label: string; hint: string }> = [
  { key: "mae", label: "MAE", hint: "Средняя абсолютная ошибка бэктеста" },
  { key: "rmse", label: "RMSE", hint: "Корень средней квадратичной ошибки бэктеста" },
  { key: "mape", label: "MAPE", hint: "Процентная ошибка бэктеста (в %)" },
  { key: "mase", label: "MASE", hint: "Масштабированная ошибка относительно seasonal-naive (train-only scale)" },
  { key: "mse", label: "MSE", hint: "Квадрат RMSE (производное, не пересчитано)" },
];

function formatMetric(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return Number(value).toFixed(4);
}

export function ForecastAccuracyPanel({ run }: { run: ForecastRun }) {
  const accuracy = run.expected_accuracy ?? {};
  const coverage = run.prediction_interval_coverage;

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4" data-testid="forecast-accuracy-panel">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold text-neutral-800">Ожидаемая точность</h4>
        <span
          className="rounded bg-brand/10 px-2 py-0.5 text-[10px] font-medium text-brand"
          data-testid="accuracy-disclaimer"
        >
          по результатам бэктеста — не точность этого прогноза
        </span>
      </div>
      <p className="mb-3 text-[11px] text-neutral-500">
        У будущих точек нет фактических значений: ошибка реального прогноза станет
        известна только после наступления будущего. Ниже — историческая точность той
        же модели на скользящих фолдах бэктеста.
      </p>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5" data-testid="accuracy-grid">
        {METRIC_LABELS.map((metric) => (
          <div
            key={metric.key}
            className="rounded border border-neutral-100 bg-neutral-50 px-2.5 py-2"
            title={metric.hint}
          >
            <dt className="text-[10px] uppercase tracking-wide text-neutral-500">{metric.label}</dt>
            <dd className="text-sm font-semibold text-neutral-800" data-testid={`accuracy-${metric.key}`}>
              {formatMetric(accuracy[metric.key])}
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-neutral-600">
        <span>
          Метод интервала: <b data-testid="ci-method">{run.ci_method}</b>
        </span>
        <span>
          Фактическое покрытие интервала (OOF):{" "}
          <b data-testid="coverage">
            {coverage == null
              ? "— (недоступно для этого метода честно)"
              : `${(coverage * 100).toFixed(1)}%`}
          </b>
        </span>
      </div>
    </div>
  );
}
