"use client";

// packages/ui/components/MonitoringComparisonPanel.tsx
//
// DOCLOG-8 (спека §6 D12: «Таблица actual-vs-forecast и график», §12.3
// состояния, AC15/AC17): панель сверки прогноза с фактом в
// DocumentationWorkspace для D12 -- таблица frozen пар
// (Дата/Прогноз/Факт/Ошибка/|Ошибка|/APE/Интервал), агрегаты
// (MAE/bias/MAPE/MASE/покрытие) с ЧЕСТНЫМИ null+reason (AC12: не 0 и
// не «pass»), порог-факт, явная строка незрелых горизонтов (§6.1: не
// нулевая ошибка). Данные -- frozen результат сервера; панель ничего
// не пересчитывает (§19.1). Состояния §12.3: loading/empty/forbidden/
// offline; цвет НЕ единственный носитель статуса (текст).

import { useEffect, useState } from "react";
import {
  getComparison,
  listRunComparisons,
  type ComparisonDetail,
  type MonitoringPair,
} from "../lib/monitoring";

const THRESHOLD_STATUS_LABELS: Record<string, string> = {
  exceeded: "порог превышен",
  within: "в норме",
  not_evaluable: "порог не вычислим",
};

const METRIC_LABELS: Record<string, string> = {
  mae: "MAE",
  mape: "MAPE",
  bias_abs: "|bias|",
  mase: "MASE",
};

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (!Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs !== 0 && (abs >= 1e6 || abs < 1e-4)) {
    return value.toExponential(3);
  }
  return value.toFixed(4).replace(/\.?0+$/, "");
}

function IntervalBadge({ pair }: { pair: MonitoringPair }) {
  if (pair.interval_hit === null) {
    return <span className="text-neutral-500" title="границы интервала отсутствуют в прогнозе">—</span>;
  }
  const label = pair.interval_hit ? "попадание" : "промах";
  return (
    <span className={pair.interval_hit ? "" : "font-medium"}>
      {label}
    </span>
  );
}

export function MonitoringComparisonPanel({ runId }: { runId: string | null | undefined }) {
  const [phase, setPhase] = useState<"loading" | "ready" | "empty" | "forbidden" | "error">("loading");
  const [detail, setDetail] = useState<ComparisonDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Array<{ comparison_id: string; created_at: string; matured_count: number; excluded_count: number; units_check: string }>>([]);

  useEffect(() => {
    let cancelled = false;
    if (!runId) {
      setPhase("empty");
      return () => {
        cancelled = true;
      };
    }
    setPhase("loading");
    (async () => {
      const listed = await listRunComparisons(runId);
      if (cancelled) return;
      if (!listed.ok) {
        setPhase(listed.status === 403 ? "forbidden" : "error");
        return;
      }
      if (listed.data.items.length === 0) {
        setPhase("empty");
        return;
      }
      setSummaries(
        listed.data.items.map((item) => ({
          comparison_id: item.comparison_id,
          created_at: item.created_at,
          matured_count: item.matured_count,
          excluded_count: item.excluded_count,
          units_check: item.units_check,
        })),
      );
      const firstId = listed.data.items[0].comparison_id;
      setSelectedId(firstId);
      const loaded = await getComparison(runId, firstId);
      if (cancelled) return;
      if (!loaded.ok) {
        setPhase(loaded.status === 403 ? "forbidden" : "error");
        return;
      }
      setDetail(loaded.data);
      setPhase("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  async function switchComparison(id: string) {
    if (!runId) return;
    setPhase("loading");
    const loaded = await getComparison(runId, id);
    if (!loaded.ok) {
      setPhase(loaded.status === 403 ? "forbidden" : "error");
      return;
    }
    setSelectedId(id);
    setDetail(loaded.data);
    setPhase("ready");
  }

  if (!runId) {
    return (
      <p data-testid="d12-no-run" className="text-sm text-neutral-600 dark:text-neutral-300">
        Сверки прогноза с фактом доступны в контексте исследования (run не выбран).
      </p>
    );
  }

  if (phase === "loading") {
    return (
      <p data-testid="d12-loading" role="status" className="text-sm text-neutral-600 dark:text-neutral-300">
        Загрузка сверок…
      </p>
    );
  }
  if (phase === "forbidden") {
    return (
      <p data-testid="d12-forbidden" role="alert" className="text-sm text-neutral-700 dark:text-neutral-200">
        Доступ запрещён — сверка прогноза с фактом недоступна вашему субъекту.
      </p>
    );
  }
  if (phase === "error") {
    return (
      <p data-testid="d12-error" role="alert" className="text-sm text-neutral-700 dark:text-neutral-200">
        Сервис мониторинга недоступен — повторите попытку позже.
      </p>
    );
  }
  if (phase === "empty" || !detail) {
    return (
      <p data-testid="d12-empty" className="text-sm text-neutral-600 dark:text-neutral-300">
        Сверки прогноза с фактом не зарегистрированы — мониторинг появляется по поступлении фактической версии (§6 D12); выпуск прогноза не переписывается.
      </p>
    );
  }

  const { result } = detail;
  const aggregates = result.aggregates;
  const alignment = result.alignment;
  const threshold = result.threshold;

  return (
    <section
      data-testid="d12-panel"
      aria-label="Сверка прогноза с фактом"
      className="flex flex-col gap-2"
    >
      {summaries.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-neutral-600 dark:text-neutral-300">Сверки:</span>
          {summaries.map((item) => (
            <button
              key={item.comparison_id}
              type="button"
              aria-pressed={selectedId === item.comparison_id}
              onClick={() => switchComparison(item.comparison_id)}
              className="max-w-[16rem] truncate rounded-full border border-neutral-200 px-2 py-0.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-700"
              title={item.comparison_id}
            >
              {item.comparison_id.slice(0, 14)}… ({item.matured_count}/{item.matured_count + item.excluded_count})
            </button>
          ))}
        </div>
      )}

      {/* Незрелые горизонты -- ЯВНО (§6.1: не нулевая ошибка, AC15). */}
      <p data-testid="d12-excluded" className="text-xs text-neutral-600 dark:text-neutral-300">
        Зрелых горизонтов: {alignment.matured_count} из {alignment.matured_count + alignment.excluded_count};
        исключено незрелых (ошибка не назначается): {alignment.excluded_count}
        {alignment.excluded_labels.length > 0 && (
          <> — {alignment.excluded_labels.join(", ")}</>
        )}
        {alignment.out_of_horizon_count > 0 && (
          <>; фактов вне горизонта прогноза: {alignment.out_of_horizon_count}</>
        )}
        ; единицы: {detail.units_check}
      </p>

      {/* Таблица actual-vs-forecast из frozen result (без пересчёта). */}
      <div className="overflow-x-auto">
        <table
          data-testid="d12-comparison-table"
          className="w-full min-w-[34rem] border-collapse text-xs"
        >
          <caption className="sr-only">
            Таблица сверки прогноза с фактом по зрелым горизонтам
          </caption>
          <thead>
            <tr className="border-b border-neutral-300 text-left dark:border-neutral-700">
              <th scope="col" className="py-1 pr-2 font-medium">Дата</th>
              <th scope="col" className="py-1 pr-2 font-medium">Прогноз</th>
              <th scope="col" className="py-1 pr-2 font-medium">Факт</th>
              <th scope="col" className="py-1 pr-2 font-medium">Ошибка</th>
              <th scope="col" className="py-1 pr-2 font-medium">|Ошибка|</th>
              <th scope="col" className="py-1 pr-2 font-medium">APE</th>
              <th scope="col" className="py-1 font-medium">Интервал</th>
            </tr>
          </thead>
          <tbody>
            {result.pairs.map((pair) => (
              <tr
                key={`${pair.step ?? pair.date}-${pair.date}`}
                className="border-b border-neutral-200 dark:border-neutral-800"
              >
                <td className="py-1 pr-2">{pair.date}</td>
                <td className="py-1 pr-2">{formatNumber(pair.forecast_value)}</td>
                <td className="py-1 pr-2">{formatNumber(pair.actual_value)}</td>
                <td className="py-1 pr-2">{formatNumber(pair.signed_error)}</td>
                <td className="py-1 pr-2">{formatNumber(pair.absolute_error)}</td>
                <td className="py-1 pr-2">
                  {pair.ape === null ? (
                    <span title={pair.ape_undefined_reason ?? "не определено"}>
                      — ({pair.ape_undefined_reason ?? "не определено"})
                    </span>
                  ) : (
                    formatNumber(pair.ape)
                  )}
                </td>
                <td className="py-1">
                  <IntervalBadge pair={pair} />
                </td>
              </tr>
            ))}
            {result.pairs.length === 0 && (
              <tr>
                <td colSpan={7} className="py-2 text-neutral-600 dark:text-neutral-300">
                  Зрелых горизонтов нет — факты за периоды прогноза не поступали.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Агрегаты: честные null + reason (AC12), не 0 и не «pass». */}
      <div
        data-testid="d12-aggregates"
        className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-700 dark:text-neutral-200"
      >
        <span>
          MAE: {aggregates.mae === null ? `— (${aggregates.mae_reason})` : formatNumber(aggregates.mae)}
        </span>
        <span>
          Bias: {aggregates.mean_signed_error === null
            ? `— (${aggregates.mean_signed_error_reason})`
            : formatNumber(aggregates.mean_signed_error)}
        </span>
        <span>
          MAPE: {aggregates.mape === null
            ? `— (${aggregates.mape_reason})`
            : formatNumber(aggregates.mape)}
        </span>
        <span>
          MASE: {aggregates.mase === null
            ? `— (${aggregates.mase_reason ?? "требуется training-scale"})`
            : formatNumber(aggregates.mase)}
        </span>
        <span>
          Покрытие интервала: {aggregates.interval_coverage === null
            ? `— (${aggregates.interval_coverage_reason})`
            : `${aggregates.interval_hits}/${alignment.matured_count} (${formatNumber(aggregates.interval_coverage)})`}
        </span>
        {threshold && (
          <span data-testid="d12-threshold">
            Порог {METRIC_LABELS[threshold.metric] ?? threshold.metric} {threshold.operator}{" "}
            {formatNumber(threshold.value)}: {THRESHOLD_STATUS_LABELS[threshold.status] ?? threshold.status}
            {threshold.status === "not_evaluable" && threshold.reason
              ? ` (${threshold.reason})`
              : ""}
          </span>
        )}
        <span>Решение человека: — (отдельное действие; автопереобучение из порога не следует)</span>
      </div>
    </section>
  );
}
