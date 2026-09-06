"use client";

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
// Task 97.4 (Этап 4, spec_max_graf_fix.md §8): тиражирование раскрытия
// графиков. Корень Обзора: relative всегда (правка A), overflow переключается
// по expandedChartId (правка C); графические представления обёрнуты в
// ExpandableChartPanel (уровень ИСПОЛЬЗОВАНИЯ, §7.2), «Диагностика» (метрики)
// — без панели. detail_level не заказан (Этап 5 опционален) — раскрытие
// чисто визуальное, с compact-данными.
import { ExpandableChartPanel } from "./ExpandableChartPanel";
import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import { useExpandableChartState } from "../hooks/useExpandableChart";


export type VarianceMethod = "box_cox" | "yeo_johnson" | "log" | "log1p" | "sqrt";

export interface VarianceDiagnostics {
  rolling_window: number; mean_std_correlation: number | null;
  levene_statistic: number | null; levene_pvalue: number | null;
  block_variance_ratio: number | null; arch_lm_lag: number;
  arch_lm_pvalue: number | null; skewness: number | null; stability_score: number;
}

export interface VarianceProfile {
  column: string; applicable: boolean; reason: string | null;
  n_observations: number; missing_count: number; minimum: number | null; maximum: number | null;
  order_source: "time_column" | "row_order"; order_column: string | null;
  selected_method: VarianceMethod | null; lambda_value: number | null;
  needs_stabilization: boolean; diagnostics_before: VarianceDiagnostics | null;
  diagnostics_after: VarianceDiagnostics | null;
  candidates: Array<{ method: VarianceMethod; label: string; available: boolean; reason: string | null; lambda_value: number | null; stability_score: number | null }>;
  points: Array<{ x: string; original: number; transformed: number; rolling_std_before: number | null; rolling_std_after: number | null }>;
  histogram: Array<{ bin: number; original_x: number; original_density: number; transformed_x: number; transformed_density: number }>;
  warnings: string[]; recommendation: string; methodology_note: string;
}

export interface VarianceProfileResponse {
  mode: "auto" | "enabled" | "disabled";
  status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null;
  profile: VarianceProfile;
}

interface Props { profile: VarianceProfile | null; loading: boolean; error: string | null; noDataset: boolean }
type View = "series" | "rolling" | "methods" | "distribution" | "diagnostics";

const TABS: Array<{ id: View; label: string }> = [
  { id: "series", label: "До / после" },
  { id: "rolling", label: "Скользящая σ" },
  { id: "methods", label: "Методы" },
  { id: "distribution", label: "Распределения" },
  { id: "diagnostics", label: "Диагностика" },
];
const TICK = { fontSize: 10, fill: "#737373" };

function methodName(method: VarianceMethod | null): string {
  return ({ box_cox: "Box–Cox", yeo_johnson: "Yeo–Johnson", log: "Log", log1p: "Log1p", sqrt: "Квадратный корень" } as Record<string, string>)[method ?? ""] ?? "—";
}

function fmtX(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("ru-RU", { year: "2-digit", month: "short" });
}

function SeriesChart({ profile }: { profile: VarianceProfile }) {
  return <div role="img" aria-label="Ряд до и после стабилизации" className="min-h-0 flex-1 p-3">
    <ResponsiveContainer width="100%" height="100%"><LineChart data={profile.points} margin={{ top: 8, right: 14, bottom: 0, left: -8 }}>
      <CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={34} />
      <YAxis yAxisId="before" tick={TICK} width={48} /><YAxis yAxisId="after" orientation="right" tick={TICK} width={48} />
      <Tooltip labelFormatter={(value: string) => fmtX(value)} /><Legend wrapperStyle={{ fontSize: 10 }} />
      <Line yAxisId="before" dataKey="original" name="Исходная шкала" stroke="#2E3192" strokeWidth={1.7} dot={false} isAnimationActive={false} />
      <Line yAxisId="after" dataKey="transformed" name="После трансформации" stroke="#16A34A" strokeWidth={1.7} dot={false} isAnimationActive={false} />
    </LineChart></ResponsiveContainer>
  </div>;
}

function RollingChart({ profile }: { profile: VarianceProfile }) {
  return <div role="img" aria-label="Скользящее стандартное отклонение до и после" className="min-h-0 flex-1 p-3">
    <ResponsiveContainer width="100%" height="100%"><LineChart data={profile.points} margin={{ top: 8, right: 14, bottom: 0, left: -8 }}>
      <CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={34} />
      <YAxis yAxisId="before" tick={TICK} width={48} /><YAxis yAxisId="after" orientation="right" tick={TICK} width={48} />
      <Tooltip labelFormatter={(value: string) => fmtX(value)} /><Legend wrapperStyle={{ fontSize: 10 }} />
      <Line yAxisId="before" dataKey="rolling_std_before" name="σ до" stroke="#DC2626" strokeWidth={1.7} dot={false} connectNulls isAnimationActive={false} />
      <Line yAxisId="after" dataKey="rolling_std_after" name="σ после" stroke="#16A34A" strokeWidth={1.7} dot={false} connectNulls isAnimationActive={false} />
    </LineChart></ResponsiveContainer>
  </div>;
}

function MethodsChart({ profile }: { profile: VarianceProfile }) {
  const data = profile.candidates.filter((item) => item.available && item.stability_score !== null);
  return <div role="img" aria-label="Сравнение методов стабилизации" className="min-h-0 flex-1 p-3">
    <ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
      <CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="label" tick={TICK} /><YAxis domain={[0, 100]} tick={TICK} width={42} />
      <Tooltip formatter={(value: number) => [`${value.toFixed(1)} / 100`, "Score нестабильности"]} />
      <Bar dataKey="stability_score" name="Меньше — стабильнее" fill="#2E3192" isAnimationActive={false} />
    </BarChart></ResponsiveContainer>
  </div>;
}

function DistributionCharts({ profile }: { profile: VarianceProfile }) {
  return <div role="img" aria-label="Распределения до и после" className="grid min-h-0 flex-1 grid-cols-2 gap-2 p-3">
    <ResponsiveContainer width="100%" height="100%"><BarChart data={profile.histogram} margin={{ top: 18, right: 5, bottom: 0, left: -14 }}>
      <CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="original_x" tick={TICK} tickFormatter={(v: number) => v.toPrecision(3)} /><YAxis tick={TICK} width={44} />
      <Tooltip /><Bar dataKey="original_density" name="Плотность до" fill="#2E3192" isAnimationActive={false} />
    </BarChart></ResponsiveContainer>
    <ResponsiveContainer width="100%" height="100%"><BarChart data={profile.histogram} margin={{ top: 18, right: 5, bottom: 0, left: -14 }}>
      <CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="transformed_x" tick={TICK} tickFormatter={(v: number) => v.toPrecision(3)} /><YAxis tick={TICK} width={44} />
      <Tooltip /><Bar dataKey="transformed_density" name="Плотность после" fill="#16A34A" isAnimationActive={false} />
    </BarChart></ResponsiveContainer>
  </div>;
}

function value(value: number | null, digits = 4): string { return value === null ? "—" : value.toFixed(digits); }
function DiagnosticCard({ label, before, after, hint }: { label: string; before: string; after: string; hint: string }) {
  return <div className="rounded border border-neutral-200 bg-neutral-50 p-3"><p className="text-[10px] font-medium text-neutral-600">{label}</p><p className="mt-1 font-mono text-sm text-neutral-800">{before} → {after}</p><p className="mt-1 text-[9px] text-neutral-400">{hint}</p></div>;
}
function Diagnostics({ profile }: { profile: VarianceProfile }) {
  const before = profile.diagnostics_before!; const after = profile.diagnostics_after!;
  return <div className="grid min-h-0 flex-1 content-center gap-3 p-4 md:grid-cols-2">
    <DiagnosticCard label="corr(mean, σ)" before={value(before.mean_std_correlation)} after={value(after.mean_std_correlation)} hint="|r| ближе к 0: масштаб слабее связан с уровнем" />
    <DiagnosticCard label="Brown–Forsythe" before={`p=${value(before.levene_pvalue)}`} after={`p=${value(after.levene_pvalue)}`} hint="p < 0,05: дисперсии временных блоков различаются" />
    <DiagnosticCard label="Отношение дисперсий блоков" before={value(before.block_variance_ratio, 2)} after={value(after.block_variance_ratio, 2)} hint="Ближе к 1 — равномернее" />
    <DiagnosticCard label={`ARCH-LM · lag ${before.arch_lm_lag}`} before={`p=${value(before.arch_lm_pvalue)}`} after={`p=${value(after.arch_lm_pvalue)}`} hint="Отдельный сигнал условной волатильности, не критерий power transform" />
  </div>;
}

export function PreprocessingVarianceOverview(props: Props) {
  return (
    <ExpandableChartsProvider>
      <PreprocessingVarianceOverviewInner {...props} />
    </ExpandableChartsProvider>
  );
}

function PreprocessingVarianceOverviewInner({ profile, loading, error, noDataset }: Props) {
  const [view, setView] = useState<View>("series");
  const { expandedChartId } = useExpandableChartState();
  if (loading) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Оценивается стабильность дисперсии…</div>;
  if (error) return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Загрузите датасет для диагностики дисперсии.</div>;
  if (!profile) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable || !profile.diagnostics_before || !profile.diagnostics_after) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Диагностика неприменима."}</div>;

  const lambda = profile.lambda_value === null ? "" : ` · λ=${profile.lambda_value.toFixed(3)}`;
  return <section className={`relative flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white feed-scroll ${expandedChartId ? "overflow-hidden" : "overflow-y-auto"}`}>
    <div className="shrink-0 border-b border-neutral-100 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2"><div><h4 className="text-sm font-semibold text-neutral-800">{profile.column}: {methodName(profile.selected_method)}{lambda}</h4><p className="mt-1 text-[10px] text-neutral-500">{profile.order_source === "time_column" ? `ось ${profile.order_column}` : "порядок строк"} · {profile.n_observations} наблюдений · score {profile.diagnostics_before.stability_score.toFixed(1)} → {profile.diagnostics_after.stability_score.toFixed(1)}</p></div><p className="text-[10px] text-neutral-500">Методы: <a aria-label="SciPy Box–Cox" className="text-brand underline" href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.boxcox.html" target="_blank" rel="noreferrer">SciPy Box–Cox</a> · <a className="text-brand underline" href="https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.PowerTransformer.html" target="_blank" rel="noreferrer">PowerTransformer</a> · <a className="text-brand underline" href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.levene.html" target="_blank" rel="noreferrer">Brown–Forsythe</a></p></div>
      <p className="mt-2 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p>
      {profile.warnings.length > 0 && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.warnings.join(" ")}</p>}
    </div>
    <div role="tablist" aria-label="Графики стабилизации дисперсии" className="flex shrink-0 flex-wrap gap-1.5 border-b border-neutral-100 px-4 py-2">{TABS.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={view === tab.id} onClick={() => setView(tab.id)} className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${view === tab.id ? "border-neutral-300 bg-neutral-200 text-neutral-800" : "border-neutral-200 bg-neutral-50 text-neutral-500 hover:bg-neutral-100"}`}>{tab.label}</button>)}</div>
    {view === "series" && <ExpandableChartPanel chartId="variance-series" title="Ряд до и после стабилизации"><SeriesChart profile={profile} /></ExpandableChartPanel>}{view === "rolling" && <ExpandableChartPanel chartId="variance-rolling" title="Скользящая σ до/после"><RollingChart profile={profile} /></ExpandableChartPanel>}{view === "methods" && <ExpandableChartPanel chartId="variance-methods" title="Сравнение методов"><MethodsChart profile={profile} /></ExpandableChartPanel>}{view === "distribution" && <ExpandableChartPanel chartId="variance-distribution" title="Распределения до и после"><DistributionCharts profile={profile} /></ExpandableChartPanel>}{view === "diagnostics" && <Diagnostics profile={profile} />}
    <p className="shrink-0 px-4 pb-3 text-[9px] text-neutral-400">{profile.methodology_note}</p>
  </section>;
}
