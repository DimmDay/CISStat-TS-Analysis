"use client";

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";


export type SmoothingMethod = "sma" | "ema" | "wma" | "median" | "savgol" | "lowess";

export interface SmoothingDiagnostics {
  normalized_roughness: number | null;
  difference_std_ratio: number | null;
  lag1_autocorrelation: number | null;
  high_frequency_power_share: number | null;
  standard_deviation: number | null;
}

export interface SmoothingProfile {
  column: string; applicable: boolean; reason: string | null;
  n_observations: number; missing_count?: number;
  order_source: "time_column" | "row_order"; order_column: string | null;
  frequency: string | null; regular: boolean | null;
  selected_method: SmoothingMethod | null; selected_parameters: Record<string, number>;
  needs_smoothing: boolean;
  diagnostics_before: SmoothingDiagnostics | null;
  diagnostics_after: SmoothingDiagnostics | null;
  candidates: Array<{
    method: SmoothingMethod; label: string; causal: boolean; available: boolean;
    reason: string | null; parameter_label: string; correlation: number | null;
    roughness_reduction_pct: number | null; high_frequency_reduction_pct: number | null;
    variance_retained_pct: number | null; residual_ljung_box_pvalue: number | null;
  }>;
  points: Array<{ x: string; original: number; smoothed: number; residual: number }>;
  spectrum: Array<{ frequency: number; before: number; after: number }>;
  residual_acf: Array<{ lag: number; value: number }>;
  warnings: string[]; recommendation: string; methodology_note: string;
}

export interface SmoothingProfileResponse {
  mode: "auto" | "enabled" | "disabled";
  status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null;
  profile: SmoothingProfile;
}

interface Props { profile: SmoothingProfile | null; loading: boolean; error: string | null; noDataset: boolean }
type View = "series" | "residual" | "methods" | "spectrum" | "diagnostics";
const TABS: Array<{ id: View; label: string }> = [
  { id: "series", label: "Ряд" }, { id: "residual", label: "Остаток / ACF" },
  { id: "methods", label: "Методы" }, { id: "spectrum", label: "Спектр" },
  { id: "diagnostics", label: "Диагностика" },
];
const TICK = { fontSize: 10, fill: "#737373" };

function fmtX(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("ru-RU", { year: "2-digit", month: "short" });
}
function fmt(value: number | null, digits = 3): string { return value === null ? "—" : value.toFixed(digits); }
function methodName(method: SmoothingMethod | null): string {
  return ({ sma: "Trailing SMA", ema: "EMA", wma: "Trailing WMA", median: "Trailing median", savgol: "Savitzky–Golay", lowess: "LOWESS" } as Record<string, string>)[method ?? ""] ?? "—";
}

function SeriesView({ profile }: { profile: SmoothingProfile }) {
  return <div role="img" aria-label="Исходный и сглаженный ряд" className="min-h-0 flex-1 p-3"><ResponsiveContainer width="100%" height="100%"><LineChart data={profile.points} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={34} /><YAxis tick={TICK} width={48} /><Tooltip labelFormatter={(value: string) => fmtX(value)} /><Legend wrapperStyle={{ fontSize: 10 }} /><Line dataKey="original" name="Исходный" stroke="#A3A3A3" strokeWidth={1.2} dot={false} isAnimationActive={false} /><Line dataKey="smoothed" name="Сглаженный" stroke="#2E3192" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>;
}

function ResidualView({ profile }: { profile: SmoothingProfile }) {
  return <div className="grid min-h-0 flex-1 grid-cols-2 gap-2 p-3"><div role="img" aria-label="Удалённая компонента"><ResponsiveContainer width="100%" height="100%"><LineChart data={profile.points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={40} /><YAxis tick={TICK} width={42} /><Tooltip /><Line dataKey="residual" name="y − smooth" stroke="#DC2626" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div><div role="img" aria-label="ACF удалённой компоненты"><ResponsiveContainer width="100%" height="100%"><BarChart data={profile.residual_acf}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="lag" tick={TICK} /><YAxis domain={[-1, 1]} tick={TICK} width={38} /><Tooltip /><Bar dataKey="value" name="ACF" fill="#2E3192" isAnimationActive={false} /></BarChart></ResponsiveContainer></div></div>;
}

function MethodsView({ profile }: { profile: SmoothingProfile }) {
  const data = profile.candidates.filter((item) => item.available);
  return <div role="img" aria-label="Сравнение методов сглаживания" className="min-h-0 flex-1 p-3"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="label" tick={TICK} /><YAxis tick={TICK} width={42} /><Tooltip /><Legend wrapperStyle={{ fontSize: 10 }} /><Bar dataKey="roughness_reduction_pct" name="Снижение roughness, %" fill="#2E3192" isAnimationActive={false} /><Bar dataKey="high_frequency_reduction_pct" name="Снижение high-freq, %" fill="#16A34A" isAnimationActive={false} /></BarChart></ResponsiveContainer></div>;
}

function SpectrumView({ profile }: { profile: SmoothingProfile }) {
  return <div role="img" aria-label="Спектр до и после сглаживания" className="min-h-0 flex-1 p-3"><ResponsiveContainer width="100%" height="100%"><LineChart data={profile.spectrum} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="frequency" tick={TICK} /><YAxis tick={TICK} width={48} /><Tooltip /><Legend wrapperStyle={{ fontSize: 10 }} /><Line dataKey="before" name="До" stroke="#A3A3A3" dot={false} isAnimationActive={false} /><Line dataKey="after" name="После" stroke="#2E3192" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>;
}

function DiagnosticsView({ profile }: { profile: SmoothingProfile }) {
  const before = profile.diagnostics_before!; const after = profile.diagnostics_after!;
  return <div className="flex min-h-0 flex-1 flex-col justify-center p-4"><div className="grid gap-3 md:grid-cols-2"><div className="rounded border bg-neutral-50 p-3"><p className="text-[10px] text-neutral-500">Нормированная roughness</p><p className="font-mono text-sm">{fmt(before.normalized_roughness)} → {fmt(after.normalized_roughness)}</p></div><div className="rounded border bg-neutral-50 p-3"><p className="text-[10px] text-neutral-500">High-frequency power share</p><p className="font-mono text-sm">{fmt(before.high_frequency_power_share)} → {fmt(after.high_frequency_power_share)}</p></div><div className="rounded border bg-neutral-50 p-3"><p className="text-[10px] text-neutral-500">σ(Δy) / σ(y)</p><p className="font-mono text-sm">{fmt(before.difference_std_ratio)} → {fmt(after.difference_std_ratio)}</p></div><div className="rounded border bg-neutral-50 p-3"><p className="text-[10px] text-neutral-500">Lag-1 autocorrelation</p><p className="font-mono text-sm">{fmt(before.lag1_autocorrelation)} → {fmt(after.lag1_autocorrelation)}</p></div></div><p className="mt-3 rounded bg-neutral-50 p-3 text-xs text-neutral-600">Эвристика «нужно сглаживание» — не статистический тест и не оценка прогнозной точности. Проверяйте эффект expanding-window backtest-ом.</p></div>;
}

export function PreprocessingSmoothingOverview({ profile, loading, error, noDataset }: Props) {
  const [view, setView] = useState<View>("series");
  if (loading) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Оценивается высокочастотная составляющая…</div>;
  if (error) return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Загрузите датасет для диагностики сглаживания.</div>;
  if (!profile) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable || !profile.diagnostics_before || !profile.diagnostics_after) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Диагностика неприменима."}</div>;

  const parameterText = Object.entries(profile.selected_parameters).map(([key, value]) => `${key}=${Number(value).toFixed(key === "alpha" ? 3 : 0)}`).join(" · ");
  return <section className="flex h-[468px] min-h-0 flex-col overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll"><div className="shrink-0 border-b border-neutral-100 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h4 className="text-sm font-semibold text-neutral-800">{profile.column}: {methodName(profile.selected_method)}{parameterText ? ` · ${parameterText}` : ""}</h4><p className="mt-1 text-[10px] text-neutral-500">{profile.order_source === "time_column" ? `ось ${profile.order_column}` : "порядок строк"} · {profile.frequency ?? "частота не определена"} · {profile.n_observations} наблюдений</p></div><p className="text-[10px] text-neutral-500">Методы: <a aria-label="pandas rolling" className="text-brand underline" href="https://pandas.pydata.org/docs/reference/api/pandas.Series.rolling.html" target="_blank" rel="noreferrer">pandas rolling</a> · <a className="text-brand underline" href="https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.ewm.html" target="_blank" rel="noreferrer">pandas EWM</a> · <a aria-label="SciPy periodogram" className="text-brand underline" href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html" target="_blank" rel="noreferrer">SciPy periodogram</a> · <a aria-label="SciPy Savitzky–Golay" className="text-brand underline" href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html" target="_blank" rel="noreferrer">SciPy Savitzky–Golay</a> · <a className="text-brand underline" href="https://www.statsmodels.org/stable/generated/statsmodels.nonparametric.smoothers_lowess.lowess" target="_blank" rel="noreferrer">statsmodels LOWESS</a></p></div><p className="mt-2 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p>{profile.warnings.length > 0 && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.warnings.join(" ")}</p>}</div><div role="tablist" aria-label="Графики сглаживания ряда" className="flex shrink-0 flex-wrap gap-1.5 border-b border-neutral-100 px-4 py-2">{TABS.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={view === tab.id} onClick={() => setView(tab.id)} className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${view === tab.id ? "border-neutral-300 bg-neutral-200 text-neutral-800" : "border-neutral-200 bg-neutral-50 text-neutral-500 hover:bg-neutral-100"}`}>{tab.label}</button>)}</div>{view === "series" && <SeriesView profile={profile} />}{view === "residual" && <ResidualView profile={profile} />}{view === "methods" && <MethodsView profile={profile} />}{view === "spectrum" && <SpectrumView profile={profile} />}{view === "diagnostics" && <DiagnosticsView profile={profile} />}<p className="shrink-0 px-4 pb-3 text-[9px] text-neutral-400">{profile.methodology_note}</p></section>;
}
