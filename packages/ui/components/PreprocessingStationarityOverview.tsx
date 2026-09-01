"use client";

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";


export type StationarityConsensus = "stationary" | "trend-stationary" | "non-stationary" | "inconclusive";
export type StationarityTransformMethod = "linear_detrend" | "first_difference" | "second_difference" | "seasonal_difference" | "combined_difference" | "log_difference";
export type StationarityProfileMethod = "none" | StationarityTransformMethod;

export interface StationarityProfile {
  column: string; applicable: boolean; reason: string | null; n_observations: number;
  missing_count: number; min_observations: number; alpha: number;
  order_source: "time_column" | "row_order"; order_column: string | null;
  frequency: string | null; regular: boolean; seasonal_period: number;
  selected_method: StationarityProfileMethod | null; needs_transformation: boolean;
  consensus_before: StationarityConsensus | null; consensus_after: StationarityConsensus | null;
  lost_observations: number; acf_lag1_before: number | null; acf_lag1_after: number | null;
  variance_before: number | null; variance_after: number | null; over_differencing_warning: boolean;
  tests: Array<{ id: string; label: string; null_hypothesis: string; before_p_value: number | null; after_p_value: number | null; before_supports_stationarity: boolean | null; after_supports_stationarity: boolean | null }>;
  candidates: Array<{ method: StationarityTransformMethod; label: string; available: boolean; reason: string | null; consensus: StationarityConsensus | null; lost_observations: number; adf_p_value: number | null; kpss_p_value: number | null; acf_lag1: number | null; variance_ratio: number | null; over_differencing_warning: boolean }>;
  points: Array<{ x: string; original: number; transformed: number | null; rolling_mean_z_before: number | null; rolling_mean_z_after: number | null; rolling_std_ratio_before: number | null; rolling_std_ratio_after: number | null }>;
  acf: Array<{ lag: number; before: number; after: number; confidence_before: number; confidence_after: number }>;
  warnings: string[]; recommendation: string; methodology_note: string;
}

export interface StationarityProfileResponse {
  mode: "auto" | "enabled" | "disabled";
  status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null;
  profile: StationarityProfile;
}

interface Props { profile: StationarityProfile | null; loading: boolean; error: string | null; noDataset: boolean }
type View = "series" | "rolling" | "tests" | "acf" | "candidates";
const TABS: Array<{ id: View; label: string }> = [
  { id: "series", label: "Ряд" }, { id: "rolling", label: "Rolling μ/σ" },
  { id: "tests", label: "Тесты" }, { id: "acf", label: "ACF" },
  { id: "candidates", label: "Кандидаты" },
];
const TICK = { fontSize: 10, fill: "#737373" };

function fmt(value: number | null, digits = 4): string { return value === null ? "—" : value.toFixed(digits); }
function fmtX(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("ru-RU", { year: "2-digit", month: "short" });
}
function methodLabel(method: StationarityProfileMethod | null): string {
  const labels: Record<StationarityProfileMethod, string> = {
    none: "без преобразования", linear_detrend: "линейный detrend",
    first_difference: "первая разность", second_difference: "вторая разность",
    seasonal_difference: "сезонная разность", combined_difference: "сезонная + первая",
    log_difference: "log-разность",
  };
  return method ? labels[method] : "—";
}
function consensusLabel(value: StationarityConsensus | null): string {
  return value ? ({ stationary: "стационарен", "trend-stationary": "тренд-стационарен", "non-stationary": "нестационарен", inconclusive: "неопределённость" } as Record<StationarityConsensus, string>)[value] : "—";
}

function SeriesView({ profile }: { profile: StationarityProfile }) {
  return <div role="img" aria-label="Ряд до и после обеспечения стационарности" className="grid h-[270px] grid-cols-2 gap-2 p-3"><div><p className="text-center text-[10px] text-neutral-500">Исходный уровень</p><ResponsiveContainer width="100%" height="92%"><LineChart data={profile.points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={36} /><YAxis tick={TICK} width={44} /><Tooltip labelFormatter={(value: string) => fmtX(value)} /><Line dataKey="original" name="Исходный" stroke="#A3A3A3" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div><div><p className="text-center text-[10px] text-neutral-500">После: {methodLabel(profile.selected_method)}</p><ResponsiveContainer width="100%" height="92%"><LineChart data={profile.points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={36} /><YAxis tick={TICK} width={44} /><Tooltip labelFormatter={(value: string) => fmtX(value)} /><Line dataKey="transformed" name="После" stroke="#2E3192" dot={false} connectNulls={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div></div>;
}

function RollingView({ profile }: { profile: StationarityProfile }) {
  return <div role="img" aria-label="Скользящие среднее и отклонение" className="grid h-[270px] grid-cols-2 gap-2 p-3"><div><p className="text-center text-[10px] text-neutral-500">Rolling mean: отклонение в σ ряда</p><ResponsiveContainer width="100%" height="92%"><LineChart data={profile.points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={38} /><YAxis tick={TICK} width={38} /><Tooltip /><Legend wrapperStyle={{ fontSize: 9 }} /><Line dataKey="rolling_mean_z_before" name="До" stroke="#A3A3A3" dot={false} isAnimationActive={false} /><Line dataKey="rolling_mean_z_after" name="После" stroke="#2E3192" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div><div><p className="text-center text-[10px] text-neutral-500">Rolling σ / глобальная σ</p><ResponsiveContainer width="100%" height="92%"><LineChart data={profile.points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={38} /><YAxis tick={TICK} width={38} /><Tooltip /><Legend wrapperStyle={{ fontSize: 9 }} /><Line dataKey="rolling_std_ratio_before" name="До" stroke="#A3A3A3" dot={false} isAnimationActive={false} /><Line dataKey="rolling_std_ratio_after" name="После" stroke="#16A34A" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div></div>;
}

function TestsView({ profile }: { profile: StationarityProfile }) {
  const data = profile.tests.filter((item) => item.before_p_value !== null || item.after_p_value !== null);
  return <div role="img" aria-label="P-значения до и после преобразования" className="h-[270px] p-3"><p className="px-2 text-[10px] text-neutral-500">ADF/PP/ZA: p&lt;α поддерживает стационарность; KPSS: p≥α. Линия — α={profile.alpha}.</p><ResponsiveContainer width="100%" height="92%"><BarChart data={data} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="label" tick={TICK} /><YAxis domain={[0, 1]} tick={TICK} width={38} /><Tooltip /><Legend wrapperStyle={{ fontSize: 10 }} /><ReferenceLine y={profile.alpha} stroke="#DC2626" strokeDasharray="4 3" /><Bar dataKey="before_p_value" name="p до" fill="#A3A3A3" isAnimationActive={false} /><Bar dataKey="after_p_value" name="p после" fill="#2E3192" isAnimationActive={false} /></BarChart></ResponsiveContainer></div>;
}

function AcfView({ profile }: { profile: StationarityProfile }) {
  const confidence = profile.acf[0]?.confidence_after ?? 0;
  return <div role="img" aria-label="ACF до и после преобразования" className="h-[270px] p-3"><ResponsiveContainer width="100%" height="100%"><BarChart data={profile.acf}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="lag" tick={TICK} /><YAxis domain={[-1, 1]} tick={TICK} width={38} /><Tooltip /><Legend wrapperStyle={{ fontSize: 10 }} /><ReferenceLine y={confidence} stroke="#D97706" strokeDasharray="3 3" /><ReferenceLine y={-confidence} stroke="#D97706" strokeDasharray="3 3" /><Bar dataKey="before" name="До" fill="#A3A3A3" isAnimationActive={false} /><Bar dataKey="after" name="После" fill="#2E3192" isAnimationActive={false} /></BarChart></ResponsiveContainer></div>;
}

function CandidatesView({ profile }: { profile: StationarityProfile }) {
  return <div className="h-[270px] overflow-auto p-3 feed-scroll"><table aria-label="Сравнение преобразований стационарности" className="w-full min-w-[720px] text-left text-xs"><thead className="sticky top-0 bg-white text-neutral-500"><tr><th className="p-2">Метод</th><th className="p-2">Консенсус</th><th className="p-2">Потеря N</th><th className="p-2">ADF p</th><th className="p-2">KPSS p</th><th className="p-2">ACF(1)</th><th className="p-2">Var after/before</th></tr></thead><tbody>{profile.candidates.map((item) => <tr key={item.method} className="border-t border-neutral-100"><td className="p-2 font-medium">{item.label}{!item.available && <span className="block font-normal text-amber-700">{item.reason}</span>}</td><td className="p-2">{consensusLabel(item.consensus)}</td><td className="p-2">{item.available ? item.lost_observations : "—"}</td><td className="p-2 font-mono">{fmt(item.adf_p_value)}</td><td className="p-2 font-mono">{fmt(item.kpss_p_value)}</td><td className={item.over_differencing_warning ? "p-2 font-mono text-amber-700" : "p-2 font-mono"}>{fmt(item.acf_lag1)}</td><td className="p-2 font-mono">{fmt(item.variance_ratio, 3)}</td></tr>)}</tbody></table></div>;
}

export function PreprocessingStationarityOverview({ profile, loading, error, noDataset }: Props) {
  const [view, setView] = useState<View>("series");
  if (loading) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Выполняются ADF/KPSS и сравнение преобразований…</div>;
  if (error) return <div role="alert" className="flex h-[420px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Загрузите датасет для диагностики стационарности.</div>;
  if (!profile) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Диагностика неприменима."}</div>;

  return <section className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll"><div className="border-b border-neutral-100 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h4 className="text-sm font-semibold text-neutral-800">{profile.column}: {consensusLabel(profile.consensus_before)} → {consensusLabel(profile.consensus_after)}</h4><p className="mt-1 text-[10px] text-neutral-500">{profile.order_source === "time_column" ? `ось ${profile.order_column}` : "порядок строк"} · {profile.frequency ?? "частота не определена"} · s={profile.seasonal_period} · {methodLabel(profile.selected_method)}</p></div><p className="max-w-[430px] text-right text-[10px] text-neutral-500">Методология: <a aria-label="statsmodels ADF" className="text-brand underline" href="https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html" target="_blank" rel="noreferrer">statsmodels ADF</a> · <a aria-label="statsmodels KPSS" className="text-brand underline" href="https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.kpss.html" target="_blank" rel="noreferrer">statsmodels KPSS</a> · <a className="text-brand underline" href="https://arch.readthedocs.io/en/stable/unitroot/generated/arch.unitroot.PhillipsPerron.html" target="_blank" rel="noreferrer">arch PP</a> · <a className="text-brand underline" href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.detrend.html" target="_blank" rel="noreferrer">SciPy detrend</a> · <a aria-label="FPP3 differencing" className="text-brand underline" href="https://otexts.com/fpp3/stationarity.html" target="_blank" rel="noreferrer">FPP3 differencing</a></p></div><p className="mt-2 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p>{profile.warnings.length > 0 && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.warnings.join(" ")}</p>}</div><div role="tablist" aria-label="Графики стационарности ряда" className="flex flex-wrap gap-1.5 border-b border-neutral-100 px-4 py-2">{TABS.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={view === tab.id} onClick={() => setView(tab.id)} className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${view === tab.id ? "border-neutral-300 bg-neutral-200 text-neutral-800" : "border-neutral-200 bg-neutral-50 text-neutral-500 hover:bg-neutral-100"}`}>{tab.label}</button>)}</div>{view === "series" && <SeriesView profile={profile} />}{view === "rolling" && <RollingView profile={profile} />}{view === "tests" && <TestsView profile={profile} />}{view === "acf" && <AcfView profile={profile} />}{view === "candidates" && <CandidatesView profile={profile} />}<p className="px-4 pb-3 text-[9px] text-neutral-400">{profile.methodology_note}</p></section>;
}
