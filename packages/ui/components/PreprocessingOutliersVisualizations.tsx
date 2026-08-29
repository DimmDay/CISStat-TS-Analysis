"use client";

// packages/ui/components/PreprocessingOutliersVisualizations.tsx
//
// Графики Обзора остановки «Выбросы» -- переиспользуют backend
// (GET /dataset/outlier-line|histogram|density|boxplot, apps/api/routers/
// session.py), который в свою очередь переиспользует build_scatter_series/
// build_histogram/build_kde (apps/api/chart_data.py) -- те же функции,
// что уже отрисовывают распределение на вкладке «Загрузка»
// (packages/ui/components/DistributionCharts.tsx). Палитра и разметка
// карточки взяты оттуда же (BRAND #2E3192 -- официальный цвет
// Статкомитета СНГ), а не придуманы заново.

import { useEffect, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { sessionApiUrl } from "../lib/apiClient";

const BRAND = "#2E3192";
const AXIS_TICK_STYLE = { fontSize: 11, fill: "#737373" };

function fmt(n: number): string {
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

function ChartFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-[300px] border border-neutral-200 rounded bg-white px-1 pt-2 pb-1">
      <ResponsiveContainer width="100%" height="100%">
        {children as React.ReactElement}
      </ResponsiveContainer>
    </div>
  );
}

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить график (HTTP ${response.status})`;
}

function useOutlierChartFetch<T>(path: string | null): { data: T | null; loading: boolean; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!path) { setData(null); setLoading(false); setError(null); return; }
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl(path), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const json: T = await response.json();
        if (active) setData(json);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить график");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [path]);

  return { data, loading, error };
}

function ChartStatus({ loading, error }: { loading: boolean; error: string | null }) {
  if (loading) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-400">Загрузка графика…</div>;
  if (error) return <div role="alert" className="flex h-[300px] items-center justify-center px-8 text-center text-sm text-red-700">{error}</div>;
  return null;
}

// ── 1. Линейный (build_scatter_series, отрисован как соединённая линия) ──

interface LineResponse {
  points: { x: number; y: number }[];
  sampled: boolean;
  sampling_method: string | null;
  original_count: number;
}

export function OutlierLineChart({ column }: { column: string | null }) {
  const { data, loading, error } = useOutlierChartFetch<LineResponse>(
    column ? `/dataset/outlier-line?column=${encodeURIComponent(column)}` : null
  );
  if (!column) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-500">Выберите числовой признак.</div>;
  if (loading || error) return <ChartStatus loading={loading} error={error} />;
  if (!data || data.points.length === 0) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-500">Нет данных.</div>;

  return (
    <div>
      <ChartFrame>
        <LineChart data={data.points} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
          <CartesianGrid stroke="#F0F0F0" />
          <XAxis type="number" dataKey="x" tick={AXIS_TICK_STYLE} tickFormatter={fmt} name="Позиция" />
          <YAxis type="number" dataKey="y" tick={AXIS_TICK_STYLE} tickFormatter={fmt} width={48} />
          <Tooltip formatter={(value: number) => fmt(value)} labelFormatter={() => ""} />
          <Line type="linear" dataKey="y" stroke={BRAND} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ChartFrame>
      {data.sampled && (
        <p className="mt-1.5 text-[11px] text-neutral-500">
          Показано {data.points.length} из {data.original_count} точек (сэмплинг LTTB, экстремумы и выбросы сохранены).
        </p>
      )}
    </div>
  );
}

// ── 2. Гистограмма (build_histogram) с границами метода ──

interface HistogramResponse {
  bins: { x0: number; x1: number; count: number }[];
  bounds: { lower: number; upper: number } | null;
}

export function OutlierHistogramChart({ column, method }: { column: string | null; method: string }) {
  const { data, loading, error } = useOutlierChartFetch<HistogramResponse>(
    column ? `/dataset/outlier-histogram?column=${encodeURIComponent(column)}&method=${method}` : null
  );
  if (!column) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-500">Выберите числовой признак.</div>;
  if (loading || error) return <ChartStatus loading={loading} error={error} />;
  if (!data || data.bins.length === 0) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-500">Нет данных.</div>;

  const chartData = data.bins.map((b) => ({ ...b, mid: (b.x0 + b.x1) / 2 }));
  return (
    <div>
      <ChartFrame>
        <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
          <CartesianGrid stroke="#F0F0F0" vertical={false} />
          <XAxis dataKey="mid" type="number" domain={["dataMin", "dataMax"]} tick={AXIS_TICK_STYLE} tickFormatter={fmt} />
          <YAxis tick={AXIS_TICK_STYLE} width={32} allowDecimals={false} />
          <Tooltip
            formatter={(value: number) => [String(value), "Частота"]}
            labelFormatter={(_, payload) => {
              const p = payload?.[0]?.payload as { x0: number; x1: number } | undefined;
              return p ? `${fmt(p.x0)} – ${fmt(p.x1)}` : "";
            }}
          />
          <Bar dataKey="count" fill={BRAND} radius={[1, 1, 0, 0]} isAnimationActive={false} />
          {data.bounds && (
            <>
              <ReferenceLine x={data.bounds.lower} stroke="#DC2626" strokeDasharray="4 3" />
              <ReferenceLine x={data.bounds.upper} stroke="#DC2626" strokeDasharray="4 3" />
            </>
          )}
        </BarChart>
      </ChartFrame>
      {data.bounds && (
        <p className="mt-1.5 text-[11px] text-neutral-500">
          Границы метода (пунктир): {fmt(data.bounds.lower)} … {fmt(data.bounds.upper)}
        </p>
      )}
    </div>
  );
}

// ── 3. Плотность (build_kde) ──

interface DensityResponse {
  points: { x: number; y: number }[] | null;
}

export function OutlierDensityChart({ column }: { column: string | null }) {
  const { data, loading, error } = useOutlierChartFetch<DensityResponse>(
    column ? `/dataset/outlier-density?column=${encodeURIComponent(column)}` : null
  );
  if (!column) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-500">Выберите числовой признак.</div>;
  if (loading || error) return <ChartStatus loading={loading} error={error} />;
  if (!data || !data.points) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-500">Плотность не определена (константный столбец или мало данных).</div>;

  return (
    <ChartFrame>
      <AreaChart data={data.points} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
        <defs>
          <linearGradient id="outlierKdeFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={BRAND} stopOpacity={0.35} />
            <stop offset="100%" stopColor={BRAND} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#F0F0F0" vertical={false} />
        <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} tick={AXIS_TICK_STYLE} tickFormatter={fmt} />
        <YAxis tick={AXIS_TICK_STYLE} width={32} tickFormatter={(v) => v.toFixed(2)} />
        <Tooltip formatter={(value: number) => value.toFixed(4)} labelFormatter={(x) => `x = ${fmt(Number(x))}`} />
        <Area type="monotone" dataKey="y" stroke={BRAND} strokeWidth={1.75} fill="url(#outlierKdeFill)" isAnimationActive={false} />
      </AreaChart>
    </ChartFrame>
  );
}

// ── 4. Boxplot «Выброс» vs «Норма» (outlier_boxplot_groups) ──

interface BoxplotGroup { count: number; min: number; q1: number; median: number; q3: number; max: number; mean: number }
interface BoxplotResponse { column: string; outliers: BoxplotGroup | null; normal: BoxplotGroup | null }

function BoxAndWhiskers({ label, group, color, domainMin, domainMax }: {
  label: string; group: BoxplotGroup | null; color: string; domainMin: number; domainMax: number;
}) {
  const width = 140;
  const scale = (v: number) => domainMax > domainMin ? ((v - domainMin) / (domainMax - domainMin)) * width : width / 2;
  return (
    <div className="flex-1 text-center">
      <p className="mb-1 text-xs font-medium text-neutral-700">{label}</p>
      {!group ? (
        <p className="text-xs text-neutral-400">Нет данных</p>
      ) : (
        <>
          <svg viewBox={`0 0 ${width} 60`} className="mx-auto block" width={width} height={60}>
            <line x1={scale(group.min)} x2={scale(group.max)} y1={30} y2={30} stroke="#a3a3a3" strokeWidth={1} />
            <rect x={scale(group.q1)} y={12} width={Math.max(2, scale(group.q3) - scale(group.q1))} height={36} fill={color} fillOpacity={0.35} stroke={color} />
            <line x1={scale(group.median)} x2={scale(group.median)} y1={12} y2={48} stroke={color} strokeWidth={2} />
            <line x1={scale(group.min)} x2={scale(group.min)} y1={20} y2={40} stroke="#a3a3a3" />
            <line x1={scale(group.max)} x2={scale(group.max)} y1={20} y2={40} stroke="#a3a3a3" />
          </svg>
          <p className="mt-1 text-[11px] text-neutral-500">n={group.count}, медиана={group.median.toFixed(2)}</p>
        </>
      )}
    </div>
  );
}

export function OutlierBoxplotChart({ column, method }: { column: string | null; method: string }) {
  const { data, loading, error } = useOutlierChartFetch<BoxplotResponse>(
    column ? `/dataset/outlier-boxplot?column=${encodeURIComponent(column)}&method=${method}` : null
  );
  if (!column) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-500">Выберите числовой признак.</div>;
  if (loading || error) return <ChartStatus loading={loading} error={error} />;
  if (!data) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-500">Нет данных.</div>;

  const domainMin = Math.min(data.outliers?.min ?? Infinity, data.normal?.min ?? Infinity);
  const domainMax = Math.max(data.outliers?.max ?? -Infinity, data.normal?.max ?? -Infinity);

  return (
    <div className="flex h-[300px] items-center justify-center gap-10 border border-neutral-200 rounded bg-white">
      <BoxAndWhiskers label="Выброс" group={data.outliers} color="#DC2626" domainMin={domainMin} domainMax={domainMax} />
      <BoxAndWhiskers label="Норма" group={data.normal} color={BRAND} domainMin={domainMin} domainMax={domainMax} />
    </div>
  );
}
