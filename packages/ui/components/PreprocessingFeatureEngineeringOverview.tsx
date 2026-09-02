"use client";

import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";


export type FeatureFamily = "lag" | "rolling" | "difference" | "calendar" | "fourier" | "trend";
export type CalendarFeature = "year" | "quarter" | "month_cyclic" | "dayofweek_cyclic" | "dayofyear_cyclic" | "hour_cyclic" | "is_weekend";
export interface FeatureCatalogItem {
  name: string; family: FeatureFamily; formula: string; lookback: number;
  known_in_advance: boolean; causal: boolean; missing_count: number; coverage: number;
}
export interface FeatureGenerationProfile {
  column: string; applicable: boolean; reason: string | null; n_observations: number;
  order_source: "time_column" | "row_order"; order_column: string | null;
  frequency: string | null; regular: boolean; spectral_periods: number[];
  suggested_lags: number[]; suggested_rolling_windows: number[];
  suggested_calendar_features: CalendarFeature[]; suggested_fourier_periods: number[];
  generated: boolean; saved_feature_names: string[]; max_lookback: number;
  preview_feature_count: number;
  preview_points: Array<{ x: string; target: number; lag: number | null; rolling: number | null; fourier: number | null }>;
  lag_correlations: Array<{ lag: number; correlation: number | null; selected: boolean }>;
  availability: Array<{ name: string; family: FeatureFamily; available_count: number; missing_count: number; coverage: number }>;
  cyclic_points: Array<{ x: string; feature: string; value: number | null }>;
  catalog: FeatureCatalogItem[]; warnings: string[]; recommendation: string; methodology_note: string;
}
export interface FeatureGenerationProfileResponse {
  mode: "auto" | "enabled" | "disabled"; status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null; profile: FeatureGenerationProfile;
}

type View = "preview" | "lags" | "availability" | "cycles" | "catalog";
const TABS: Array<{ id: View; label: string }> = [
  { id: "preview", label: "Превью" }, { id: "lags", label: "Лаг-корреляции" },
  { id: "availability", label: "Доступность" }, { id: "cycles", label: "Циклы" },
  { id: "catalog", label: "Каталог" },
];
const COLORS = ["#2E3192", "#0891B2", "#16A34A", "#D97706", "#7C3AED", "#DC2626"];
const TICK = { fontSize: 9, fill: "#737373" };
const pct = (value: number) => `${(100 * value).toFixed(1)}%`;
const fmtX = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("ru-RU", { year: "2-digit", month: "short" });
};

function PreviewView({ profile }: { profile: FeatureGenerationProfile }) {
  return <div role="img" aria-label="Превью сгенерированных признаков" className="h-[255px] p-3"><ResponsiveContainer width="100%" height="100%"><LineChart data={profile.preview_points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={35} /><YAxis yAxisId="target" tick={TICK} width={45} /><YAxis yAxisId="cycle" orientation="right" domain={[-1, 1]} hide /><Tooltip labelFormatter={(value: string) => fmtX(value)} /><Legend wrapperStyle={{ fontSize: 9 }} /><Line yAxisId="target" dataKey="target" name="target" stroke="#A3A3A3" dot={false} isAnimationActive={false} /><Line yAxisId="target" dataKey="lag" name="первый лаг" stroke="#2E3192" dot={false} connectNulls={false} isAnimationActive={false} /><Line yAxisId="target" dataKey="rolling" name="rolling mean" stroke="#16A34A" dot={false} connectNulls={false} isAnimationActive={false} /><Line yAxisId="cycle" dataKey="fourier" name="Fourier sin" stroke="#D97706" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>;
}

function LagsView({ profile }: { profile: FeatureGenerationProfile }) {
  return <div role="img" aria-label="Корреляции цели с прошлыми лагами" className="h-[255px] p-3"><p className="px-2 text-[10px] text-neutral-500">Диагностическая Pearson corr(y[t], y[t−k]); выделены рекомендуемые лаги. Это не оценка out-of-sample полезности.</p><ResponsiveContainer width="100%" height="92%"><BarChart data={profile.lag_correlations}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="lag" tick={TICK} /><YAxis domain={[-1, 1]} tick={TICK} width={35} /><Tooltip /><Bar dataKey="correlation" name="Корреляция" isAnimationActive={false}>{profile.lag_correlations.map((item) => <Cell key={item.lag} fill={item.selected ? "#2E3192" : "#D4D4D4"} />)}</Bar></BarChart></ResponsiveContainer></div>;
}

function AvailabilityView({ profile }: { profile: FeatureGenerationProfile }) {
  const data = [...profile.availability].sort((a, b) => a.coverage - b.coverage).slice(0, 20);
  return <div role="img" aria-label="Доступность признаков после warm-up" className="h-[255px] p-3"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{ left: 45, right: 15 }}><CartesianGrid stroke="#F0F0F0" /><XAxis type="number" domain={[0, 1]} tick={TICK} tickFormatter={(value) => `${Math.round(100 * value)}%`} /><YAxis dataKey="name" type="category" tick={TICK} width={120} /><Tooltip formatter={(value: number | string) => typeof value === "number" ? pct(value) : value} /><Bar dataKey="coverage" name="Доступно" fill="#0891B2" isAnimationActive={false} /></BarChart></ResponsiveContainer></div>;
}

function CyclesView({ profile }: { profile: FeatureGenerationProfile }) {
  const { data, names } = useMemo(() => {
    const rows = new Map<string, Record<string, string | number | null>>();
    const series = [...new Set(profile.cyclic_points.map((point) => point.feature))];
    profile.cyclic_points.forEach((point) => {
      const row = rows.get(point.x) ?? { x: point.x };
      row[point.feature] = point.value;
      rows.set(point.x, row);
    });
    return { data: [...rows.values()], names: series };
  }, [profile.cyclic_points]);
  if (!names.length) return <p role="status" className="p-8 text-center text-sm text-neutral-500">Для текущей оси циклические признаки не предложены.</p>;
  return <div role="img" aria-label="Календарные и Fourier циклы" className="h-[255px] p-3"><ResponsiveContainer width="100%" height="100%"><LineChart data={data}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={35} /><YAxis domain={[-1, 1]} tick={TICK} width={35} /><Tooltip /><Legend wrapperStyle={{ fontSize: 8 }} />{names.map((name, index) => <Line key={name} dataKey={name} name={name} stroke={COLORS[index % COLORS.length]} dot={false} isAnimationActive={false} />)}</LineChart></ResponsiveContainer></div>;
}

function CatalogView({ profile }: { profile: FeatureGenerationProfile }) {
  return <div className="h-[255px] overflow-auto p-3 feed-scroll"><table aria-label="Каталог рекомендуемых признаков" className="w-full min-w-[780px] text-left text-xs"><thead className="sticky top-0 bg-white text-neutral-500"><tr><th className="p-2">Признак</th><th className="p-2">Семейство</th><th className="p-2">Формула</th><th className="p-2">Lookback</th><th className="p-2">Известен заранее</th><th className="p-2">Coverage</th></tr></thead><tbody>{profile.catalog.map((item) => <tr key={item.name} className="border-t border-neutral-100"><td className="p-2 font-medium">{item.name}</td><td className="p-2">{item.family}</td><td className="p-2 font-mono text-[10px]">{item.formula}</td><td className="p-2">{item.lookback}</td><td className="p-2">{item.known_in_advance ? "да" : "только история"}</td><td className="p-2">{pct(item.coverage)}</td></tr>)}</tbody></table></div>;
}

export function PreprocessingFeatureEngineeringOverview({ profile, loading, error, noDataset }: { profile: FeatureGenerationProfile | null; loading: boolean; error: string | null; noDataset: boolean }) {
  const [view, setView] = useState<View>("preview");
  if (loading) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Строим безопасные lag/rolling/calendar/Fourier-признаки…</div>;
  if (error) return <div role="alert" className="flex h-[420px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Загрузите датасет для генерации признаков.</div>;
  if (!profile) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Генерация признаков неприменима."}</div>;
  return <section className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll"><div className="border-b border-neutral-100 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h4 className="text-sm font-semibold">Матрица признаков «{profile.column}»</h4><p className="mt-1 text-[10px] text-neutral-500">{profile.order_column ? `ось ${profile.order_column}` : "порядок строк"} · {profile.frequency ?? "индексная шкала"} · N={profile.n_observations}</p></div><div className="grid grid-cols-3 gap-2 text-center text-[10px]"><span className="rounded bg-neutral-50 px-2 py-1">Признаков<strong className="block text-xs">{profile.preview_feature_count}</strong></span><span className="rounded bg-neutral-50 px-2 py-1">Lookback<strong className="block text-xs">{profile.max_lookback}</strong></span><span className="rounded bg-neutral-50 px-2 py-1">Спектр P<strong className="block text-xs">{profile.spectral_periods.join(", ") || "—"}</strong></span></div></div><p className="mt-2 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p><div role="tablist" aria-label="Представления генерации признаков" className="mt-3 flex flex-wrap gap-2">{TABS.map((tab) => <button key={tab.id} role="tab" aria-selected={view === tab.id} onClick={() => setView(tab.id)} className={`rounded-full border px-3 py-1 text-xs ${view === tab.id ? "border-neutral-300 bg-neutral-200 text-neutral-800" : "border-neutral-200 bg-neutral-50 text-neutral-500 hover:bg-neutral-100"}`}>{tab.label}</button>)}</div></div>{view === "preview" && <PreviewView profile={profile} />}{view === "lags" && <LagsView profile={profile} />}{view === "availability" && <AvailabilityView profile={profile} />}{view === "cycles" && <CyclesView profile={profile} />}{view === "catalog" && <CatalogView profile={profile} />}<div className="border-t border-neutral-100 px-4 py-3 text-[9px] text-neutral-500"><p>{profile.methodology_note}</p>{profile.warnings.map((warning) => <p key={warning} className="mt-1 text-amber-700">{warning}</p>)}<p className="mt-2">Официальные источники: <a className="text-brand underline" href="https://pandas.pydata.org/docs/reference/api/pandas.Series.shift.html" target="_blank" rel="noreferrer">pandas shift</a> · <a className="text-brand underline" href="https://pandas.pydata.org/docs/reference/api/pandas.Series.rolling.html" target="_blank" rel="noreferrer">pandas rolling</a> · <a className="text-brand underline" href="https://scikit-learn.org/stable/auto_examples/applications/plot_cyclical_feature_engineering.html" target="_blank" rel="noreferrer">scikit-learn cyclic features</a> · <a className="text-brand underline" href="https://www.statsmodels.org/stable/generated/statsmodels.tsa.deterministic.Fourier.html" target="_blank" rel="noreferrer">statsmodels Fourier</a>.</p></div></section>;
}
