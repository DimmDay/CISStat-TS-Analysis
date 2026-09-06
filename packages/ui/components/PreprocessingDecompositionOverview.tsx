"use client";

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
// Task 97.2 (Этап 2, spec_max_graf_fix.md §4.4): интеграция раскрытия графиков.
// Корень Обзора: relative всегда (правка A), overflow переключается по
// expandedChartId (правка C); три графика STL обёрнуты в ExpandableChartPanel
// (вкладка «Диагностика» — метрики, без панели).
// Task 97.3 (Этап 3, spec_max_graf_fix.md §6.3): панель «Компоненты» при
// раскрытии дозагружает detail_level=expanded (полный ряд до
// EXPANDED_FULL_POINTS_THRESHOLD, далее LTTB до EXPANDED_TARGET_SAMPLED_POINTS);
// сезонный профиль и ACF имеют размер периода/лагов и дозагрузки не требуют
// (§6.3.6). Пока запрос летит, показывается компактный график + индикатор.
import { ExpandableChartPanel } from "./ExpandableChartPanel";
import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import { useExpandableChartState } from "../hooks/useExpandableChart";
import { useChartDetailData } from "../hooks/useChartDetailData";


export interface PreprocessingDecompositionPoint {
  x: string; observed: number; trend: number; seasonal: number; resid: number;
}

export interface PreprocessingDecompositionProfile {
  column: string; date_column: string | null; applicable: boolean; reason: string | null;
  method: "STL"; robust: boolean; frequency: string | null; period: number | null;
  n_points: number; sampled: boolean; original_count: number;
  trend_strength: number | null; seasonal_strength: number | null;
  residual_mean: number | null; residual_std: number | null;
  ljung_box_lag: number | null; ljung_box_pvalue: number | null;
  jarque_bera_pvalue: number | null;
  points: PreprocessingDecompositionPoint[];
  seasonal_pattern: { phase: number; label: string; value: number }[];
  residual_acf: { lag: number; value: number }[];
  warnings: string[]; recommendation: string; methodology_note: string;
}

export interface PreprocessingDecompositionProfileResponse {
  mode: "auto" | "enabled" | "disabled";
  status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null;
  profile: PreprocessingDecompositionProfile;
}

interface Props {
  profile: PreprocessingDecompositionProfile | null;
  loading: boolean;
  error: string | null;
  noDataset: boolean;
}

type View = "components" | "seasonal" | "acf" | "diagnostics";

const TABS: Array<{ id: View; label: string }> = [
  { id: "components", label: "Компоненты" },
  { id: "seasonal", label: "Сезонный профиль" },
  { id: "acf", label: "ACF остатка" },
  { id: "diagnostics", label: "Диагностика" },
];

const TICK = { fontSize: 10, fill: "#737373" };

function fmtDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("ru-RU", { year: "2-digit", month: "short" });
}

function ComponentsChart({ profile }: { profile: PreprocessingDecompositionProfile }) {
  return (
    <div role="img" aria-label="Компоненты STL" className="min-h-0 flex-1 p-3">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={profile.points} margin={{ top: 6, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="#F0F0F0" vertical={false} />
          <XAxis dataKey="x" tick={TICK} tickFormatter={fmtDate} minTickGap={34} />
          <YAxis tick={TICK} width={48} />
          <Tooltip labelFormatter={(value: string) => fmtDate(value)} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Line dataKey="observed" name="Наблюдение" stroke="#2E3192" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          <Line dataKey="trend" name="Тренд" stroke="#2563EB" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="seasonal" name="Сезонность" stroke="#16A34A" strokeWidth={1.2} dot={false} isAnimationActive={false} />
          <Line dataKey="resid" name="Остаток" stroke="#9CA3AF" strokeWidth={1} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function SeasonalChart({ profile }: { profile: PreprocessingDecompositionProfile }) {
  return (
    <div role="img" aria-label="Средний сезонный профиль STL" className="min-h-0 flex-1 p-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={profile.seasonal_pattern} margin={{ top: 6, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="#F0F0F0" vertical={false} />
          <XAxis dataKey="label" tick={TICK} />
          <YAxis tick={TICK} width={48} />
          <Tooltip formatter={(value: number) => [value.toFixed(4), "Сезонный эффект"]} />
          <ReferenceLine y={0} stroke="#A3A3A3" />
          <Bar dataKey="value" name="Сезонный эффект" fill="#2E3192" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ResidualAcfChart({ profile }: { profile: PreprocessingDecompositionProfile }) {
  const limit = profile.n_points > 0 ? 1.96 / Math.sqrt(profile.n_points) : 0;
  return (
    <div role="img" aria-label="ACF остатка STL" className="min-h-0 flex-1 p-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={profile.residual_acf} margin={{ top: 6, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="#F0F0F0" vertical={false} />
          <XAxis dataKey="lag" tick={TICK} />
          <YAxis domain={[-1, 1]} tick={TICK} width={48} />
          <Tooltip formatter={(value: number) => [value.toFixed(4), "ACF"]} />
          <ReferenceLine y={0} stroke="#737373" />
          <ReferenceLine y={limit} stroke="#DC2626" strokeDasharray="4 3" />
          <ReferenceLine y={-limit} stroke="#DC2626" strokeDasharray="4 3" />
          <Bar dataKey="value" name="ACF" fill="#737373" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return <div className="rounded border border-neutral-200 bg-neutral-50 p-3" title={hint}><p className="text-[10px] text-neutral-500">{label}</p><p className="mt-1 font-mono text-base font-semibold text-neutral-800">{value}</p><p className="mt-1 text-[9px] text-neutral-400">{hint}</p></div>;
}

function Diagnostics({ profile }: { profile: PreprocessingDecompositionProfile }) {
  const pct = (value: number | null) => value === null ? "—" : `${(100 * value).toFixed(1)}%`;
  const p = (value: number | null) => value === null ? "—" : value.toFixed(4);
  return <div className="min-h-0 flex-1 content-center grid gap-3 p-4 md:grid-cols-2">
    <MetricCard label="Сила тренда" value={pct(profile.trend_strength)} hint="0 — слабый, 1 — сильный" />
    <MetricCard label="Сила сезонности" value={pct(profile.seasonal_strength)} hint="Не доля суммарной дисперсии" />
    <MetricCard label={`Ljung–Box, lag ${profile.ljung_box_lag ?? "—"}`} value={`p = ${p(profile.ljung_box_pvalue)}`} hint="p < 0,05: в остатке есть автокорреляция" />
    <MetricCard label="Jarque–Bera" value={`p = ${p(profile.jarque_bera_pvalue)}`} hint="Нормальность нужна прежде всего для параметрических интервалов" />
  </div>;
}

export function PreprocessingDecompositionOverview(props: Props) {
  return (
    <ExpandableChartsProvider>
      <PreprocessingDecompositionOverviewInner {...props} />
    </ExpandableChartsProvider>
  );
}

function PreprocessingDecompositionOverviewInner({ profile, loading, error, noDataset }: Props) {
  const [view, setView] = useState<View>("components");
  const { expandedChartId } = useExpandableChartState();
  // Task 97.3 (§6.3): дозагрузка expanded только для панели «Компоненты» —
  // единственной с плотным рядом точек. Хук до ранних return'ов.
  // fingerprint не нужен: контейнер «Предобработки» инвалидирует профиль
  // по смене target-колонки (column входит в params и в ключ кэша).
  const componentsDetail = useChartDetailData<PreprocessingDecompositionProfile>({
    path: "/dataset/preprocessing/decomposition-profile",
    profileKey: "decomposition-components",
    params: { column: profile?.column },
    enabled: expandedChartId === "decomposition-components",
  });
  if (loading) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Выполняется робастная STL-декомпозиция…</div>;
  if (error) return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Загрузите датасет для декомпозиции.</div>;
  if (!profile) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Декомпозиция неприменима."}</div>;

  return <section className={`relative flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white feed-scroll ${expandedChartId ? "overflow-hidden" : "overflow-y-auto"}`}>
    <div className="shrink-0 border-b border-neutral-100 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><h4 className="text-sm font-semibold text-neutral-800">{profile.column}: {profile.method} · период {profile.period}</h4><p className="mt-1 text-[10px] text-neutral-500">{profile.date_column} · частота {profile.frequency} · {profile.n_points} наблюдений · robust={profile.robust ? "да" : "нет"}</p></div>
        <p className="text-[10px] text-neutral-500">Метод: <a className="text-brand underline" href="https://www.statsmodels.org/stable/generated/statsmodels.tsa.seasonal.STL.html" target="_blank" rel="noreferrer">statsmodels STL</a> · тест: <a className="text-brand underline" href="https://www.statsmodels.org/stable/generated/statsmodels.stats.diagnostic.acorr_ljungbox.html" target="_blank" rel="noreferrer">Ljung–Box</a></p>
      </div>
      <p className="mt-2 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p>
      {profile.warnings.length > 0 && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.warnings.join(" ")}</p>}
    </div>
    <div role="tablist" aria-label="Графики декомпозиции" className="flex shrink-0 flex-wrap gap-1.5 border-b border-neutral-100 px-4 py-2">
      {TABS.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={view === tab.id} onClick={() => setView(tab.id)} className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${view === tab.id ? "border-neutral-300 bg-neutral-200 text-neutral-800" : "border-neutral-200 bg-neutral-50 text-neutral-500 hover:bg-neutral-100"}`}>{tab.label}</button>)}
    </div>
    {view === "components" && <ExpandableChartPanel chartId="decomposition-components" title="Компоненты STL">{componentsDetail.loading && <div aria-hidden="true" className="absolute left-0 right-0 top-0 z-30 h-0.5 animate-pulse bg-brand" />}<ComponentsChart profile={componentsDetail.data ?? profile} /></ExpandableChartPanel>}
    {view === "seasonal" && <ExpandableChartPanel chartId="decomposition-seasonal" title="Сезонный профиль STL"><SeasonalChart profile={profile} /></ExpandableChartPanel>}
    {view === "acf" && <ExpandableChartPanel chartId="decomposition-acf" title="ACF остатка STL"><ResidualAcfChart profile={profile} /></ExpandableChartPanel>}
    {view === "diagnostics" && <Diagnostics profile={profile} />}
    <p className="shrink-0 px-4 pb-3 text-[9px] text-neutral-400">{profile.methodology_note}</p>
  </section>;
}
