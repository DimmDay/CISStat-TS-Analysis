"use client";

// packages/ui/components/DistributionCharts.tsx
//
// Реальные графики остановки «Распределение» вкладки «Загрузка» --
// пункт 3 контракта (см. шапку TsAnalysisUpload.tsx), первая точка
// подключения Recharts на платформе (по решению тимлида 2026-08-14,
// начинаем с «Загрузки», масштабируем на остальные модули после
// одобрения визуального представления стейкхолдерами).
//
// Данные -- GET /v1/session/dataset/distribution (apps/api/chart_data.py):
//   - scatter: LTTB-сэмплированные точки выше ~3000 (min/max/выбросы
//     гарантированно сохранены сервером -- см. докстринг chart_data.py),
//     полный набор ниже порога.
//   - histogram/kde: ВСЕГДА по полному столбцу, не зависят от сэмплинга
//     scatter (иначе форма распределения была бы искажена).
//
// Палитра НЕ придумана заново -- взята из packages/ui/tailwind-preset.ts
// (brand #2E3192 / brand-light #E8EAF6, официальные цвета Статкомитета
// СНГ) -- институциональный аналитический продукт, один спокойный акцент,
// без новой цветовой темы поверх уже утверждённой.

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceDot,
  ResponsiveContainer,
  Scatter,
  ScatterChart as RechartsScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// ── Типы (зеркало DistributionChartResponse из apps/api/schemas.py) ──

export interface ScatterPoint {
  x: number;
  y: number;
}

export interface HistogramBin {
  x0: number;
  x1: number;
  count: number;
}

export interface KdePoint {
  x: number;
  y: number;
}

export interface DistributionChartData {
  column: string;
  non_null_count: number;
  min: number | null;
  max: number | null;
  scatter: ScatterPoint[];
  scatter_sampled: boolean;
  scatter_sampling_method: string | null;
  scatter_original_count: number;
  histogram: HistogramBin[];
  kde: KdePoint[] | null;
}

const BRAND = "#2E3192";
const BRAND_SOFT = "#E8EAF6";
const AXIS_TICK_STYLE = { fontSize: 11, fill: "#737373" }; // neutral-500

function fmtCompact(n: number): string {
  // Округление до целого без разделителя тысяч и без дробной части —
  // компактно для узких карточек оси (3 графика в ряд в Навигаторе).
  // Раньше было toLocaleString("ru-RU", { maximumFractionDigits: 1 }),
  // что давало "2 064,5" (с пробелом-разделителем и запятой) —
  // подписи сливались в узких карточках.
  return Math.round(n).toString();
}

// Общая обёртка карточки графика -- та же рамка/фон, что и в placeholder'е,
// который она заменяет (border-neutral-200, bg-neutral-50, h-[200px]).
function ChartFrame({
  children,
  className = "h-[200px]",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`${className} min-w-0 border border-neutral-200 rounded bg-white px-1 pt-2 pb-1`}>
      <ResponsiveContainer width="100%" height="100%">
        {children as React.ReactElement}
      </ResponsiveContainer>
    </div>
  );
}

function EmptyFrame({ label, className = "h-[200px]" }: { label: string; className?: string }) {
  return (
    <div className={`${className} min-w-0 border border-neutral-200 rounded flex items-center justify-center text-xs text-neutral-500 bg-neutral-50`}>
      {label}
    </div>
  );
}

// ── Точечный график (x = позиция в очищенном от NaN ряде, y = значение) ──

export function ScatterDistributionChart({ data, className }: { data: DistributionChartData | null; className?: string }) {
  // data.scatter может отсутствовать не только при data===null: неполный/
  // устаревший ответ (например, старый кэш или замоканный в тесте fetch без
  // этого поля) не должен ронять всю страницу -- деградируем до EmptyFrame.
  if (!data || !data.scatter || data.scatter.length === 0) return <EmptyFrame label="Нет данных" className={className} />;

  // Экстремумы уже гарантированно есть среди точек (сервер их сохраняет
  // поверх LTTB) -- находим их здесь же, чтобы визуально выделить, а не
  // запрашивать повторно.
  const minPoint = data.scatter.reduce((a, b) => (b.y < a.y ? b : a));
  const maxPoint = data.scatter.reduce((a, b) => (b.y > a.y ? b : a));

  return (
    <ChartFrame className={className}>
      <RechartsScatterChart margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="#F0F0F0" />
        <XAxis type="number" dataKey="x" tick={AXIS_TICK_STYLE} tickFormatter={fmtCompact} name="Позиция" />
        <YAxis type="number" dataKey="y" tick={AXIS_TICK_STYLE} tickFormatter={fmtCompact} width={48} />
        <Tooltip
          cursor={{ strokeDasharray: "3 3" }}
          formatter={(value: number) => fmtCompact(value)}
          labelFormatter={() => ""}
        />
        <Scatter data={data.scatter} fill={BRAND} fillOpacity={0.55} r={2.5} isAnimationActive={false} />
        <ReferenceDot x={minPoint.x} y={minPoint.y} r={4} fill="#DC2626" stroke="none" />
        <ReferenceDot x={maxPoint.x} y={maxPoint.y} r={4} fill="#DC2626" stroke="none" />
      </RechartsScatterChart>
    </ChartFrame>
  );
}

// ── Гистограмма ──

export function HistogramDistributionChart({ data, className }: { data: DistributionChartData | null; className?: string }) {
  if (!data || !data.histogram || data.histogram.length === 0) return <EmptyFrame label="Нет данных" className={className} />;

  const chartData = data.histogram.map((b) => ({
    ...b,
    // Подпись бина -- середина интервала, компактнее, чем "x0–x1" на узкой оси
    mid: (b.x0 + b.x1) / 2,
  }));

  return (
    <ChartFrame className={className}>
      <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="#F0F0F0" vertical={false} />
        <XAxis
          dataKey="mid"
          type="number"
          domain={["dataMin", "dataMax"]}
          tick={AXIS_TICK_STYLE}
          tickFormatter={fmtCompact}
        />
        <YAxis tick={AXIS_TICK_STYLE} width={32} allowDecimals={false} />
        <Tooltip
          formatter={(value: number) => [formatCount(value), "Частота"]}
          labelFormatter={(_, payload) => {
            const p = payload?.[0]?.payload as { x0: number; x1: number } | undefined;
            return p ? `${fmtCompact(p.x0)} – ${fmtCompact(p.x1)}` : "";
          }}
        />
        <Bar dataKey="count" fill={BRAND} radius={[1, 1, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ChartFrame>
  );
}

function formatCount(n: number): string {
  return `${n}`;
}

// ── KDE (кривая плотности) ──

export function KdeDistributionChart({ data, className }: { data: DistributionChartData | null; className?: string }) {
  if (!data || !data.kde) {
    return (
      <EmptyFrame
        label={data && data.non_null_count > 0 ? "KDE не определена (константный столбец)" : "Нет данных"}
        className={className}
      />
    );
  }

  return (
    <ChartFrame className={className}>
      <AreaChart data={data.kde} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="kdeFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={BRAND} stopOpacity={0.35} />
            <stop offset="100%" stopColor={BRAND} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#F0F0F0" vertical={false} />
        <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} tick={AXIS_TICK_STYLE} tickFormatter={fmtCompact} />
        <YAxis tick={AXIS_TICK_STYLE} width={32} tickFormatter={(v) => v.toFixed(4)} />
        <Tooltip formatter={(value: number) => value.toFixed(4)} labelFormatter={(x) => `x = ${fmtCompact(Number(x))}`} />
        <Area type="monotone" dataKey="y" stroke={BRAND} strokeWidth={1.75} fill="url(#kdeFill)" isAnimationActive={false} />
      </AreaChart>
    </ChartFrame>
  );
}

// ── Бейдж сэмплинга -- показываем стейкхолдерам ЧЕСТНО, что график
// прорежен, а не тихо (пункт "прозрачность" в договорённости с тимлидом) ──

export function SamplingBadge({ data }: { data: DistributionChartData | null }) {
  if (!data || !data.scatter_sampled) return null;
  return (
    <p className="text-[11px] text-neutral-500 mt-1.5">
      Показано {formatCount(data.scatter.length)} из {formatCount(data.scatter_original_count)} точек
      (сэмплинг LTTB, экстремумы и выбросы сохранены)
    </p>
  );
}

export { BRAND, BRAND_SOFT };
