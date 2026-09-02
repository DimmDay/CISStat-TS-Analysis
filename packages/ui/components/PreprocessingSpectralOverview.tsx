"use client";

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceLine,
  ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from "recharts";


export interface SpectralPoint {
  frequency: number; period: number; amplitude: number | null; power: number | null; is_peak: boolean;
}
export interface SpectralWelchPoint extends SpectralPoint { power_share: number }
export interface SpectralCandidate {
  rank: number; period: number; period_rounded: number; frequency: number; amplitude: number; power: number;
  power_share: number; prominence: number; spectral_snr: number; autocorrelation: number; seasonal_strength: number;
  cycles: number; confirmed: boolean; calendar_hint: string | null; harmonic_of: number | null;
}
export interface SpectralPhasePoint { phase: number; mean: number; lower: number; upper: number; count: number }
export interface SpectralWaveletPoint {
  x: string; index: number; period: number; power: number; normalized_power: number; edge_affected: boolean;
}
export interface PreprocessingSpectralProfile {
  column: string; applicable: boolean; reason: string | null; n_observations: number; missing_count: number;
  min_cycles: number; max_candidates: number; max_period: number | null; detrend: "linear"; window: "hann";
  order_source: "time_column" | "row_order"; order_column: string | null; order_warning: string | null; frequency: string | null;
  spectral_entropy: number | null; dominant_period: number | null; dominant_strength: number | null; confirmed_periods: number;
  frequency_resolution: number | null; nyquist_frequency: number | null; welch_segment_length: number | null; welch_segments: number;
  wavelet_method: string; wavelet_period_min: number | null; wavelet_period_max: number | null;
  analysis_only: boolean; causal: boolean; modeling_safe: boolean; saved_periods: number[];
  fft: SpectralPoint[]; periodogram: SpectralPoint[]; welch: SpectralWelchPoint[];
  bands: Array<{ id: "low" | "mid" | "high"; label: string; frequency_min: number; frequency_max: number; power_share: number }>;
  candidates: SpectralCandidate[]; phase_period: number | null; phase_profile: SpectralPhasePoint[];
  wavelet: SpectralWaveletPoint[]; wavelet_global: Array<{ period: number; power_share: number }>;
  recommendations: string[]; warnings: string[]; methodology_note: string;
}
export interface PreprocessingSpectralProfileResponse {
  mode: "auto" | "enabled" | "disabled"; status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null; profile: PreprocessingSpectralProfile;
}

type View = "global" | "welch" | "wavelet" | "phase" | "candidates";
const TABS: Array<{ id: View; label: string }> = [
  { id: "global", label: "FFT / Periodogram" },
  { id: "welch", label: "Welch PSD" },
  { id: "wavelet", label: "CWT" },
  { id: "phase", label: "Фазовый профиль" },
  { id: "candidates", label: "Кандидаты" },
];

const number = (value: number | null | undefined, digits = 3) => value === null || value === undefined || !Number.isFinite(value) ? "—" : value.toLocaleString("ru-RU", { maximumFractionDigits: digits });
const percent = (value: number | null | undefined) => value === null || value === undefined ? "—" : `${(100 * value).toFixed(1)}%`;

function SpectrumChart({ data, dataKey, label, color }: { data: SpectralPoint[]; dataKey: "amplitude" | "power"; label: string; color: string }) {
  const peaks = data.filter((point) => point.is_peak);
  return <div className="min-w-0"><p className="px-2 text-[10px] font-medium text-neutral-600">{label}</p><div className="h-[235px]" role="img" aria-label={label}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} margin={{ top: 8, right: 10, bottom: 12, left: -15 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" /><XAxis dataKey="frequency" type="number" domain={[0, 0.5]} tick={{ fontSize: 9 }} label={{ value: "частота", position: "insideBottomRight", offset: -6, fontSize: 9 }} /><YAxis tick={{ fontSize: 9 }} width={48} /><Tooltip labelFormatter={(_, payload) => { const point = payload?.[0]?.payload as SpectralPoint | undefined; return point ? `Период ≈ ${number(point.period)}` : ""; }} /><Line type="monotone" dataKey={dataKey} stroke={color} dot={false} isAnimationActive={false} /><Scatter data={peaks} dataKey={dataKey} fill="#dc2626" isAnimationActive={false} /></ComposedChart></ResponsiveContainer></div></div>;
}

function GlobalView({ profile }: { profile: PreprocessingSpectralProfile }) {
  return <div role="img" aria-label="Глобальные FFT и periodogram спектры" className="grid grid-cols-2 gap-2 px-2 pt-3"><SpectrumChart data={profile.fft} dataKey="amplitude" label="FFT amplitude" color="#2563eb" /><SpectrumChart data={profile.periodogram} dataKey="power" label="Hann periodogram" color="#7c3aed" /></div>;
}

function WelchView({ profile }: { profile: PreprocessingSpectralProfile }) {
  return <div role="img" aria-label="Welch PSD и частотные диапазоны" className="grid grid-cols-[minmax(0,2fr)_minmax(170px,1fr)] gap-2 px-3 pt-3"><div className="h-[245px]"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={profile.welch} margin={{ top: 8, right: 12, bottom: 12, left: -8 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" /><XAxis dataKey="frequency" type="number" domain={[0, 0.5]} tick={{ fontSize: 9 }} /><YAxis tick={{ fontSize: 9 }} width={52} /><Tooltip labelFormatter={(_, payload) => { const point = payload?.[0]?.payload as SpectralWelchPoint | undefined; return point ? `Период ≈ ${number(point.period)}` : ""; }} /><Line dataKey="power" name="Median Welch PSD" stroke="#0891b2" dot={false} isAnimationActive={false} /></ComposedChart></ResponsiveContainer></div><div className="h-[245px]"><ResponsiveContainer width="100%" height="100%"><BarChart data={profile.bands} layout="vertical" margin={{ top: 12, right: 16, bottom: 12, left: 12 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" /><XAxis type="number" domain={[0, 1]} tickFormatter={(value) => `${Math.round(100 * value)}%`} tick={{ fontSize: 9 }} /><YAxis dataKey="label" type="category" width={58} tick={{ fontSize: 9 }} /><Tooltip formatter={(value: number | string) => typeof value === "number" ? percent(value) : value} /><Bar dataKey="power_share" name="Доля мощности" fill="#16a34a" isAnimationActive={false} /></BarChart></ResponsiveContainer></div></div>;
}

function WaveletView({ profile }: { profile: PreprocessingSpectralProfile }) {
  const timeIndices = [...new Set(profile.wavelet.map((point) => point.index))];
  const columns = Math.max(1, timeIndices.length);
  return <div role="img" aria-label="CWT скалограмма" className="px-4 pt-3"><div className="mb-1 flex justify-between text-[10px] text-neutral-500"><span>Высокие частоты / короткие периоды</span><span>{profile.wavelet_method}</span></div><div className="grid h-[205px] overflow-hidden rounded border border-neutral-200" style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}>{profile.wavelet.map((point) => <span key={`${point.period}-${point.index}`} title={`${point.x}: период ${number(point.period)}, мощность ${number(point.power)}`} style={{ backgroundColor: `rgba(37, 99, 235, ${0.04 + 0.96 * point.normalized_power})`, opacity: point.edge_affected ? 0.5 : 1 }} />)}</div><div className="mt-1 flex justify-between text-[10px] text-neutral-500"><span>Низкие частоты / длинные периоды</span><span>бледные края — edge-affected</span></div><div className="mt-2 flex h-3 overflow-hidden rounded"><span className="flex-1 bg-blue-50" /><span className="flex-1 bg-blue-300" /><span className="flex-1 bg-blue-600" /></div></div>;
}

function PhaseView({ profile }: { profile: PreprocessingSpectralProfile }) {
  if (!profile.phase_profile.length || profile.phase_period === null) return <p role="status" className="p-8 text-center text-sm text-neutral-500">Нет периода-кандидата для фазового профиля.</p>;
  return <div role="img" aria-label={`Фазовый профиль периода ${profile.phase_period}`} className="h-[275px] px-3 pt-3"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={profile.phase_profile} margin={{ top: 8, right: 16, bottom: 8, left: -8 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" /><XAxis dataKey="phase" type="number" domain={[1, profile.phase_period]} tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 10 }} width={52} /><Tooltip /><ReferenceLine y={0} stroke="#a3a3a3" /><Line dataKey="upper" name="Верхняя 95%" stroke="#a3a3a3" strokeDasharray="4 3" dot={false} isAnimationActive={false} /><Line dataKey="lower" name="Нижняя 95%" stroke="#a3a3a3" strokeDasharray="4 3" dot={false} isAnimationActive={false} /><Line dataKey="mean" name="Среднее фазы" stroke="#16a34a" strokeWidth={2} isAnimationActive={false} /></ComposedChart></ResponsiveContainer></div>;
}

function CandidatesView({ profile }: { profile: PreprocessingSpectralProfile }) {
  if (!profile.candidates.length) return <p role="status" className="p-8 text-center text-sm text-neutral-500">Локальные пики не обнаружены.</p>;
  return <div className="overflow-x-auto"><table aria-label="Спектральные периоды-кандидаты" className="w-full min-w-[860px] text-left text-xs"><thead className="sticky top-0 bg-neutral-50 text-neutral-500"><tr><th className="px-2 py-2">#</th><th className="px-2 py-2 text-right">Период</th><th className="px-2 py-2">Смысл</th><th className="px-2 py-2 text-right">Циклов</th><th className="px-2 py-2 text-right">Power</th><th className="px-2 py-2 text-right">SNR</th><th className="px-2 py-2 text-right">ACF</th><th className="px-2 py-2 text-right">Сила</th><th className="px-2 py-2">Решение</th></tr></thead><tbody>{profile.candidates.map((item) => <tr key={`${item.rank}-${item.period}`} className="border-t border-neutral-100"><td className="px-2 py-2">{item.rank}</td><td className="px-2 py-2 text-right tabular-nums">{number(item.period)}</td><td className="px-2 py-2">{item.calendar_hint ?? (item.harmonic_of ? `гармоника ${number(item.harmonic_of)}` : "—")}</td><td className="px-2 py-2 text-right">{number(item.cycles, 1)}</td><td className="px-2 py-2 text-right">{number(item.power_share, 1)}%</td><td className="px-2 py-2 text-right">{number(item.spectral_snr, 1)}</td><td className="px-2 py-2 text-right">{number(item.autocorrelation)}</td><td className="px-2 py-2 text-right">{number(item.seasonal_strength)}</td><td className={`px-2 py-2 font-medium ${item.confirmed ? "text-green-700" : "text-neutral-500"}`}>{item.confirmed ? "подтверждён" : "кандидат"}</td></tr>)}</tbody></table></div>;
}

export function PreprocessingSpectralOverview({ profile, loading, error, noDataset }: { profile: PreprocessingSpectralProfile | null; loading: boolean; error: string | null; noDataset: boolean }) {
  const [view, setView] = useState<View>("global");
  if (loading) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Строим FFT, Welch и CWT…</div>;
  if (error) return <div role="alert" className="flex h-[420px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Загрузите датасет для спектрального анализа.</div>;
  if (!profile) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Спектральный анализ неприменим."}</div>;
  return <section className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll"><div className="border-b border-neutral-100 p-4"><div className="flex items-start justify-between gap-4"><div><h4 className="text-sm font-semibold">Частотная структура «{profile.column}»</h4><p className="mt-1 text-xs text-neutral-500">{profile.order_column ? `Порядок: ${profile.order_column}` : "Порядок строк"}{profile.frequency ? ` · ${profile.frequency}` : ""} · n={profile.n_observations} · Δf={number(profile.frequency_resolution, 5)}</p></div><div className="grid grid-cols-3 gap-2 text-center text-[10px]"><span className="rounded bg-neutral-50 px-2 py-1">P*<strong className="block text-xs">{number(profile.dominant_period)}</strong></span><span className="rounded bg-neutral-50 px-2 py-1">Подтверждено<strong className="block text-xs">{profile.confirmed_periods}</strong></span><span className="rounded bg-neutral-50 px-2 py-1">Entropy<strong className="block text-xs">{number(profile.spectral_entropy)}</strong></span></div></div><div role="tablist" aria-label="Представления спектрального анализа" className="mt-3 flex flex-wrap gap-2">{TABS.map((tab) => <button key={tab.id} role="tab" aria-selected={view === tab.id} onClick={() => setView(tab.id)} className={`rounded-full bg-neutral-100 px-3 py-1 text-xs ${view === tab.id ? "ring-2 ring-neutral-400" : "text-neutral-600 hover:bg-neutral-200"}`}>{tab.label}</button>)}</div></div>{view === "global" && <GlobalView profile={profile} />}{view === "welch" && <WelchView profile={profile} />}{view === "wavelet" && <WaveletView profile={profile} />}{view === "phase" && <PhaseView profile={profile} />}{view === "candidates" && <CandidatesView profile={profile} />}<div className="border-t border-neutral-100 px-4 py-3 text-[10px] text-neutral-500"><p>{profile.methodology_note}</p>{profile.warnings.map((warning) => <p key={warning} className="mt-1 text-amber-700">{warning}</p>)}<p className="mt-2">Официальные источники: <a className="text-brand underline" href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html" target="_blank" rel="noreferrer">SciPy periodogram</a> · <a className="text-brand underline" href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html" target="_blank" rel="noreferrer">SciPy Welch</a> · <a className="text-brand underline" href="https://pywavelets.readthedocs.io/en/stable/ref/cwt.html" target="_blank" rel="noreferrer">PyWavelets CWT</a> · <a className="text-brand underline" href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.lombscargle.html" target="_blank" rel="noreferrer">SciPy Lomb–Scargle</a></p></div></section>;
}
