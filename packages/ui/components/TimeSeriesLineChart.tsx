"use client";

// packages/ui/components/TimeSeriesLineChart.tsx
//
// Линейный график остановки «График» вкладки «Загрузка» -- между
// «Превью датасета» и «Распределение» (согласовано с тимлидом
// 2026-08-14: "знакомимся с датасетом, есть визуализация распределения,
// но нет визуала самого графика").
//
// Данные -- GET /v1/session/dataset/timeseries (apps/api/chart_data.py::
// build_timeseries_points): x = РЕАЛЬНАЯ дата (в отличие от scatter в
// «Распределении», где x = позиция в очищенном ряде), LTTB-сэмплинг с
// сохранением min/max/выбросов при больших датасетах.
//
// Палитра -- та же brand/brand-light, что и в DistributionCharts.tsx.

import { Line, LineChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const BRAND = "#2E3192";
const AXIS_TICK_STYLE = { fontSize: 11, fill: "#737373" };

export interface TimeSeriesPoint {
  x: string; // ISO-дата
  y: number;
}

export interface TimeSeriesChartData {
  column: string;
  date_column: string;
  points: TimeSeriesPoint[];
  sampled: boolean;
  sampling_method: string | null;
  original_count: number;
  was_resorted: boolean;
}

function formatDateTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // Короткий формат для оси -- полная дата в тултипе
  return d.toLocaleDateString("ru-RU", { year: "numeric", month: "short", day: "2-digit" });
}

function EmptyFrame({ label }: { label: string }) {
  return (
    <div className="h-[380px] rounded-lg bg-brand-light flex items-center justify-center text-sm text-neutral-500 px-8 text-center">
      {label}
    </div>
  );
}

export function TimeSeriesLineChart({ data, loading }: { data: TimeSeriesChartData | null; loading: boolean }) {
  if (loading) return <EmptyFrame label="Загрузка графика…" />;
  if (!data || data.points.length === 0) return <EmptyFrame label="Нет данных для построения графика" />;

  return (
    <div>
      <div className="h-[380px] border border-neutral-200 rounded-lg bg-white px-2 pt-4 pb-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data.points} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="#F0F0F0" vertical={false} />
            <XAxis dataKey="x" tick={AXIS_TICK_STYLE} tickFormatter={formatDateTick} minTickGap={40} />
            <YAxis tick={AXIS_TICK_STYLE} width={48} />
            <Tooltip
              labelFormatter={(x: string) => formatDateTick(x)}
              formatter={(value: number) => [value.toFixed(4), data.column]}
            />
            <Line
              type="monotone"
              dataKey="y"
              stroke={BRAND}
              strokeWidth={1.75}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-neutral-500 mt-1.5">
        {data.sampled
          ? `Показано ${data.points.length.toLocaleString("ru-RU")} из ${data.original_count.toLocaleString("ru-RU")} точек (сэмплировано, экстремумы сохранены)`
          : `${data.points.length.toLocaleString("ru-RU")} точек`}
        {data.was_resorted && " · исходный порядок строк был не хронологическим, отсортировано по дате"}
      </p>
    </div>
  );
}
