"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { MissingProfileItem } from "./PreprocessingMissingOverview";

// ── Общее: загрузка + состояния ──

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить визуализацию (HTTP ${response.status})`;
}

function useJsonFetch<T>(path: string | null): { data: T | null; loading: boolean; error: string | null } {
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
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить визуализацию");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [path]);

  return { data, loading, error };
}

function ChartStatus({ loading, error }: { loading: boolean; error: string | null }) {
  if (loading) return <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-neutral-400">Загрузка графика…</div>;
  if (error) return <div role="alert" className="flex min-h-0 flex-1 items-center justify-center px-8 text-center text-sm text-red-700">{error}</div>;
  return null;
}

// ── 1. Матрица пропусков (перенос px.imshow(df.isnull().T) из app.py) ──

interface MatrixBin {
  bin_index: number;
  row_start: number;
  row_end: number;
  row_count: number;
  missing_share: Record<string, number>;
}
interface MatrixResponse {
  columns: string[];
  bins: MatrixBin[];
  rows_per_bin: number;
  total_rows: number;
}

// Линейная интерполяция между "заполнено" (синий, как в легаси) и
// "пропуск" (красный) по доле пропуска в бине -- та же пара цветов, что
// px.imshow(color_continuous_scale=['#2563EB', '#FCA5A5']) в app.py.
function shareColor(share: number): string {
  const from = [37, 99, 235];   // #2563EB
  const to = [239, 68, 68];     // красный (чуть насыщеннее легаси #FCA5A5 для читаемости на белом фоне)
  const mix = from.map((c, i) => Math.round(c + (to[i] - c) * share));
  return `rgb(${mix.join(",")})`;
}

export function MissingMatrixChart() {
  const { data, loading, error } = useJsonFetch<MatrixResponse>("/dataset/missing-matrix");
  if (loading || error) return <ChartStatus loading={loading} error={error} />;
  if (!data || data.bins.length === 0) {
    return <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-neutral-500">Нет данных для матрицы пропусков.</div>;
  }

  const rowHeight = 22;
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <p className="mb-2 text-xs text-neutral-500">
        Каждый столбец матрицы — блок из ~{data.rows_per_bin} строк ({data.total_rows} всего); цвет — доля пропусков в блоке (синий → нет пропусков, красный → пропуски).
      </p>
      <div className="overflow-x-auto">
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${data.bins.length}, minmax(3px, 1fr))` }}>
          {data.columns.map((column) => (
            <div key={column} style={{ display: "contents" }}>
              {data.bins.map((bin) => (
                <div
                  key={`${column}-${bin.bin_index}`}
                  title={`${column}: строки ${bin.row_start}–${bin.row_end}, пропуск ${(bin.missing_share[column] * 100).toFixed(0)}%`}
                  style={{ height: rowHeight, backgroundColor: shareColor(bin.missing_share[column] ?? 0) }}
                />
              ))}
            </div>
          ))}
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-neutral-400">
          <span>строка {data.bins[0].row_start}</span>
          <span>строка {data.bins[data.bins.length - 1].row_end}</span>
        </div>
      </div>
      <div className="mt-3 space-y-1 text-xs text-neutral-600">
        {data.columns.map((column) => <p key={column}>{column}</p>)}
      </div>
    </div>
  );
}

// ── 2. Тепловая карта корреляции (df.isnull().astype(int).corr()) ──

interface CorrelationResponse {
  columns: string[];
  matrix: (number | null)[][];
}

// Диагональная (расходящаяся) шкала RdBu_r: -1 -> синий, 0 -> белый, +1 -> красный.
function correlationColor(value: number | null): string {
  if (value === null) return "#e5e5e5";
  const t = Math.max(-1, Math.min(1, value));
  if (t >= 0) {
    const g = Math.round(255 - t * 130);
    return `rgb(255,${g},${g})`;
  }
  const g = Math.round(255 + t * 130);
  return `rgb(${g},${g},255)`;
}

export function MissingCorrelationChart() {
  const { data, loading, error } = useJsonFetch<CorrelationResponse>("/dataset/missing-correlation");
  if (loading || error) return <ChartStatus loading={loading} error={error} />;
  if (!data || data.columns.length < 2) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-8 text-center text-sm text-neutral-500">
        Нужно минимум две колонки с пропусками (и с вариативностью — не 0% и не 100%), чтобы оценить корреляцию.
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <p className="mb-2 text-xs text-neutral-500">
        Корреляция индикаторов пропуска между колонками. Значение близкое к +1 — пропуски в этих колонках почти всегда происходят одновременно (одно совместное событие, а не два независимых).
      </p>
      <div className="overflow-x-auto">
        <table aria-label="Корреляция пропусков между колонками" className="border-collapse text-xs">
          <thead>
            <tr>
              <th />
              {data.columns.map((c) => <th key={c} className="p-1 text-neutral-500">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.columns.map((rowCol, i) => (
              <tr key={rowCol}>
                <th className="p-1 text-right text-neutral-500">{rowCol}</th>
                {data.columns.map((colCol, j) => {
                  const value = data.matrix[i][j];
                  return (
                    <td
                      key={colCol}
                      title={`${rowCol} × ${colCol}: ${value === null ? "н/д" : value.toFixed(2)}`}
                      className="h-10 w-10 text-center font-mono"
                      style={{ backgroundColor: correlationColor(value) }}
                    >
                      {value === null ? "—" : value.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── 3. Сравнение распределений / Boxplot ──

interface DistributionGroup { count: number; min: number; q1: number; median: number; q3: number; max: number; mean: number }
interface DistributionResponse {
  value_column: string;
  indicator_column: string;
  with_missing: DistributionGroup | null;
  without_missing: DistributionGroup | null;
}

function BoxAndWhiskers({ label, group, color, domainMin, domainMax }: {
  label: string; group: DistributionGroup | null; color: string; domainMin: number; domainMax: number;
}) {
  const width = 120;
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

export function MissingBoxplotChart({ columns }: { columns: MissingProfileItem[] }) {
  const numericColumns = columns.filter((c) => c.semantic === "numeric").map((c) => c.column);
  const [valueColumn, setValueColumn] = useState(numericColumns[0] ?? "");
  const [indicatorColumn, setIndicatorColumn] = useState(columns.find((c) => c.column !== numericColumns[0])?.column ?? "");
  const otherColumns = columns.map((c) => c.column).filter((c) => c !== valueColumn);

  const path = valueColumn && indicatorColumn
    ? `/dataset/missing-distribution?value_column=${encodeURIComponent(valueColumn)}&indicator_column=${encodeURIComponent(indicatorColumn)}`
    : null;
  const { data, loading, error } = useJsonFetch<DistributionResponse>(path);

  if (numericColumns.length === 0) {
    return <div className="flex min-h-0 flex-1 items-center justify-center px-8 text-center text-sm text-neutral-500">В датасете нет числовых колонок для сравнения распределений.</div>;
  }

  const domainMin = Math.min(data?.with_missing?.min ?? Infinity, data?.without_missing?.min ?? Infinity);
  const domainMax = Math.max(data?.with_missing?.max ?? -Infinity, data?.without_missing?.max ?? -Infinity);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <p className="mb-3 text-xs text-neutral-500">
        Сравнивает распределение числовой колонки в строках, где пропущен «индикатор». Заметная разница — сигнал, что пропуск не полностью случаен (MAR/MNAR) и заполнение медианой/средним может сместить оценки.
      </p>
      <div className="flex flex-wrap gap-3 text-xs">
        <label>
          Числовая колонка
          <select
            aria-label="Числовая колонка для сравнения"
            value={valueColumn}
            onChange={(e) => setValueColumn(e.target.value)}
            className="mt-1 block rounded border border-neutral-300 px-2 py-1"
          >
            {numericColumns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label>
          Колонка-индикатор
          <select
            aria-label="Колонка-индикатор пропуска"
            value={indicatorColumn}
            onChange={(e) => setIndicatorColumn(e.target.value)}
            className="mt-1 block rounded border border-neutral-300 px-2 py-1"
          >
            {otherColumns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>

      {loading && <div className="mt-4 text-sm text-neutral-400">Загрузка…</div>}
      {error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}
      {data && !loading && !error && (
        <div className="mt-4 flex gap-6">
          <BoxAndWhiskers label={`С пропуском в «${indicatorColumn}»`} group={data.with_missing} color="#ef4444" domainMin={domainMin} domainMax={domainMax} />
          <BoxAndWhiskers label={`Без пропуска в «${indicatorColumn}»`} group={data.without_missing} color="#94a3b8" domainMin={domainMin} domainMax={domainMax} />
        </div>
      )}
    </div>
  );
}
