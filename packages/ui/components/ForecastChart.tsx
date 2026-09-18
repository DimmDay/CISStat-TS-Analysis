"use client";

// packages/ui/components/ForecastChart.tsx
//
// График прогноза (spec_forecasting2.md §5.3): факт (историческая часть) +
// линия прогноза (продолжение той же оси) + закрашенная область интервала +
// маркеры точек прогноза; аномальные точки (§5.8) -- красные.
// Стек -- recharts ComposedChart, тот же, что BacktestOofChart/TimeSeriesLineChart.

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ForecastPoint, ForecastRun } from "../lib/forecasting";

const TICK = { fontSize: 10, fill: "var(--chart-axis-text)" };

interface Row {
  x: string;
  actual: number | null;
  forecast: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  anomalous_value: number | null;
}

export function buildRows(run: ForecastRun): Row[] {
  const labels = run.history?.labels ?? [];
  const values = run.history?.values ?? [];
  const rows: Row[] = labels.map((label, index) => ({
    x: label,
    actual: values[index] ?? null,
    forecast: null,
    ci_lower: null,
    ci_upper: null,
    anomalous_value: null,
  }));
  const points = run.points ?? [];
  if (points.length === 0) return rows;
  // Мост: последняя фактическая точка соединяется с первой прогнозной
  // (прогноз -- продолжение той же линии, §5.3).
  const lastIndex = rows.length - 1;
  if (lastIndex >= 0) {
    rows[lastIndex].forecast = values[lastIndex] ?? null;
  }
  points.forEach((point: ForecastPoint) => {
    rows.push({
      x: point.date,
      actual: null,
      forecast: point.value,
      ci_lower: point.ci_lower,
      ci_upper: point.ci_upper,
      anomalous_value: point.is_anomalous ? point.value : null,
    });
  });
  return rows;
}

export function ForecastChart({ run }: { run: ForecastRun }) {
  const rows = buildRows(run);
  const points = run.points ?? [];
  if (points.length === 0) {
    return (
      <div className="flex h-[180px] items-center justify-center rounded border border-neutral-200 bg-neutral-50 text-xs text-neutral-500">
        Прогнозные точки отсутствуют
      </div>
    );
  }
  const forecastStart = rows.length - points.length;

  return (
    <div>
      <div
        role="img"
        aria-label={`Прогноз ${run.model_name}: факт, прогноз и интервал на ${run.horizon} шагов`}
        className="h-[468px] rounded border border-neutral-200 bg-white px-1 pb-1 pt-2"
        data-testid="forecast-chart"
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 2, left: -12 }}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis dataKey="x" tick={TICK} minTickGap={36} />
            <YAxis tick={TICK} width={58} domain={["auto", "auto"]} />
            <Tooltip
              labelFormatter={(label) => String(label)}
              formatter={(value: number, name: string) => {
                const labels: Record<string, string> = {
                  actual: "Факт",
                  forecast: "Прогноз",
                  ci_lower: "Нижняя граница",
                  ci_upper: "Верхняя граница",
                  anomalous_value: "Аномалия",
                };
                return [Number(value).toFixed(4), labels[name] ?? name];
              }}
            />
            {forecastStart > 0 && (
              <ReferenceLine
                x={rows[forecastStart]?.x}
                stroke="var(--chart-reference)"
                strokeDasharray="4 3"
                label={{ value: "прогноз →", position: "insideTopRight", fontSize: 10, fill: "var(--chart-axis-text)" }}
              />
            )}
            <Area
              type="monotone"
              dataKey="ci_upper"
              stroke="none"
              fill="var(--chart-brand)"
              fillOpacity={0.10}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="ci_lower"
              stroke="none"
              fill="var(--chart-surface)"
              fillOpacity={0.9}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="actual"
              name="actual"
              stroke="var(--chart-axis)"
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="forecast"
              name="forecast"
              stroke="var(--chart-brand)"
              strokeWidth={2}
              strokeDasharray="5 3"
              dot={{ r: 2.5, fill: "var(--chart-brand)" }}
              isAnimationActive={false}
            />
            <Scatter
              dataKey="anomalous_value"
              name="anomalous_value"
              shape="circle"
              fill="var(--status-error)"
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1.5 text-[11px] text-neutral-500">
        Чёрный — факт · синий пунктир — прогноз · лента — интервал ({Math.round((1 - run.alpha_effective) * 100)}%,{" "}
        {run.ci_method}) · красные точки — аномалии прогноза · {run.horizon} шагов
      </p>
    </div>
  );
}
