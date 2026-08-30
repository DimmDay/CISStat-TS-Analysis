"use client";

// packages/ui/components/PreprocessingRegularityVisualizations.tsx
//
// Два графика Обзора остановки «Регулярность» -- переиспользуют
// validation/regularity.py::regularity_intervals/regularity_timeline
// (GET /dataset/preprocessing/regularity-intervals|timeline,
// apps/api/routers/session.py). Палитра -- та же, что и у остальных
// визуализаций «Предобработки» (BRAND #2E3192, DistributionCharts.tsx).

import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { sessionApiUrl } from "../lib/apiClient";

const BRAND = "#2E3192";
const AXIS_TICK_STYLE = { fontSize: 11, fill: "#737373" };

const KIND_COLOR: Record<string, string> = {
  gap: "#DC2626",
  duplicate: "#D97706",
  sort_violation: "#7C3AED",
};
const KIND_LABEL: Record<string, string> = {
  gap: "Разрыв",
  duplicate: "Дубль",
  sort_violation: "Нарушение сортировки",
};

function fmtSeconds(seconds: number): string {
  const day = 86400;
  if (seconds >= 28 * day) return `${(seconds / (30 * day)).toFixed(1)} мес`;
  if (seconds >= day) return `${(seconds / day).toFixed(1)} дн`;
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)} ч`;
  return `${Math.round(seconds)} с`;
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

function useRegularityChartFetch<T>(path: string): { data: T | null; loading: boolean; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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

// ── Интервалы (гистограмма) ──

interface IntervalsResponse {
  group: string;
  bins: { x0: number; x1: number; count: number }[];
  modal_seconds: number | null;
  threshold_seconds: number | null;
}

export function RegularityIntervalsChart({ refreshKey = 0 }: { refreshKey?: number }) {
  const { data, loading, error } = useRegularityChartFetch<IntervalsResponse>(
    `/dataset/preprocessing/regularity-intervals?_r=${refreshKey}`
  );
  if (loading || error) return <ChartStatus loading={loading} error={error} />;
  if (!data || data.bins.length === 0) return <div className="flex h-[300px] items-center justify-center text-sm text-neutral-500">Недостаточно данных для гистограммы интервалов.</div>;

  const chartData = data.bins.map((b) => ({ ...b, mid: (b.x0 + b.x1) / 2 }));
  return (
    <div className="p-3">
      <p className="mb-2 text-xs text-neutral-500">
        Группа «{data.group}»: распределение интервалов между соседними наблюдениями. Красная линия — порог разрыва (модальный интервал × 1.5).
      </p>
      <div className="h-[300px] border border-neutral-200 rounded bg-white px-1 pt-2 pb-1">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
            <CartesianGrid stroke="#F0F0F0" vertical={false} />
            <XAxis dataKey="mid" type="number" domain={["dataMin", "dataMax"]} tick={AXIS_TICK_STYLE} tickFormatter={fmtSeconds} />
            <YAxis tick={AXIS_TICK_STYLE} width={32} allowDecimals={false} />
            <Tooltip
              formatter={(value: number) => [String(value), "Частота"]}
              labelFormatter={(_, payload) => {
                const p = payload?.[0]?.payload as { x0: number; x1: number } | undefined;
                return p ? `${fmtSeconds(p.x0)} – ${fmtSeconds(p.x1)}` : "";
              }}
            />
            <Bar dataKey="count" fill={BRAND} radius={[1, 1, 0, 0]} isAnimationActive={false} />
            {data.threshold_seconds !== null && (
              <ReferenceLine x={data.threshold_seconds} stroke="#DC2626" strokeDasharray="4 3" />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>
      {data.modal_seconds !== null && (
        <p className="mt-1.5 text-[11px] text-neutral-500">
          Модальный интервал: {fmtSeconds(data.modal_seconds)}. Порог разрыва: {fmtSeconds(data.threshold_seconds ?? 0)}.
        </p>
      )}
    </div>
  );
}

// ── Таймлайн (события вдоль оси дат) ──

interface TimelineEvent { date: string; kind: "gap" | "duplicate" | "sort_violation"; group: string }
interface TimelineResponse {
  date_column: string | null;
  entity_column: string | null;
  min_date: string | null;
  max_date: string | null;
  events: TimelineEvent[];
  truncated: boolean;
}

export function RegularityTimelineChart({ refreshKey = 0 }: { refreshKey?: number }) {
  const { data, loading, error } = useRegularityChartFetch<TimelineResponse>(
    `/dataset/preprocessing/regularity-timeline?_r=${refreshKey}`
  );
  if (loading || error) return <ChartStatus loading={loading} error={error} />;
  if (!data || data.events.length === 0) {
    return <div className="flex h-[300px] items-center justify-center text-sm text-green-700">Нарушений не найдено — событий для таймлайна нет.</div>;
  }

  const points = data.events.map((event, index) => ({
    x: new Date(event.date).getTime(),
    y: event.kind === "gap" ? 2 : event.kind === "duplicate" ? 1 : 0,
    kind: event.kind,
    date: event.date,
    key: index,
  }));

  return (
    <div className="p-3">
      <p className="mb-2 text-xs text-neutral-500">
        Расположение нарушений во времени{data.entity_column ? " (все сущности на одной оси)" : ""}. Кластер в одном периоде — разовый сбой источника; разброс по всему ряду — системная проблема.
      </p>
      <div className="h-[300px] border border-neutral-200 rounded bg-white px-1 pt-2 pb-1">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 20, right: 16, bottom: 0, left: -20 }}>
            <CartesianGrid stroke="#F0F0F0" />
            <XAxis
              dataKey="x" type="number" domain={["dataMin", "dataMax"]}
              tick={AXIS_TICK_STYLE} tickFormatter={(v) => new Date(v).toLocaleDateString("ru-RU")}
              name="Дата"
            />
            <YAxis
              dataKey="y" type="number" domain={[-0.5, 2.5]} ticks={[0, 1, 2]}
              tickFormatter={(v) => KIND_LABEL[{ 0: "sort_violation", 1: "duplicate", 2: "gap" }[v as 0 | 1 | 2]]}
              tick={AXIS_TICK_STYLE} width={110}
            />
            <ZAxis range={[60, 60]} />
            <Tooltip
              formatter={(_value, _name, entry) => {
                const point = entry?.payload as { kind: string; date: string } | undefined;
                return point ? [new Date(point.date).toLocaleString("ru-RU"), KIND_LABEL[point.kind]] : ["", ""];
              }}
            />
            {(["gap", "duplicate", "sort_violation"] as const).map((kind) => (
              <Scatter
                key={kind}
                data={points.filter((p) => p.kind === kind)}
                fill={KIND_COLOR[kind]}
                isAnimationActive={false}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      {data.truncated && (
        <p className="mt-1.5 text-[11px] text-amber-700">
          Показаны первые {data.events.length} событий — их больше, чем помещается на график.
        </p>
      )}
    </div>
  );
}
