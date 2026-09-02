"use client";

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";


export type ScalingMethod = "standard" | "minmax" | "robust" | "maxabs" | "quantile";
export type ScalingColumn = {
  name: string; role: "target" | "generated" | "source"; dtype: string;
  missing_count: number; unique_count: number; binary: boolean; constant: boolean;
  eligible: boolean; recommended: boolean; exclusion_reason: string | null;
  minimum: number | null; maximum: number | null; mean: number | null; std: number | null;
  median: number | null; q1: number | null; q3: number | null; iqr: number | null;
  outlier_pct: number | null; skewness?: number | null; scale: number | null;
};
export type ScalingRecipe = {
  kind: "scaling_recipe"; target_column: string; columns: string[]; method: ScalingMethod;
  parameters: Record<string, unknown>; fit_policy: "per_train_fold"; modeling_safe: boolean;
  materializes_columns: boolean; configured_on_n: number; source_signature: string;
  target_included: boolean; inverse_transform_required_for_target: boolean; nonlinear: boolean;
};
export type ScalingProfile = {
  target_column: string; applicable: boolean; reason: string | null; n_observations: number;
  numeric_count: number; eligible_count: number; suggested_columns: string[];
  recommended_method: ScalingMethod; configured: boolean; saved_recipe: ScalingRecipe | null;
  focus_column: string | null; scale_ratio: number; orders_of_magnitude: number;
  columns: ScalingColumn[];
  preview_points: Array<{ x: string; original: number | null; scaled: number | null }>;
  range_points: Array<{ column: string; scale_before: number | null; scale_after: number | null; log_scale_before: number | null; log_scale_after: number | null }>;
  distribution_points: Array<{ x_before: number | null; density_before: number | null; x_after: number | null; density_after: number | null }>;
  box_points: Array<{ column: string; stage: "before" | "after"; minimum: number | null; q1: number | null; median: number | null; q3: number | null; maximum: number | null }>;
  correlation_points: Array<{ x: string; y: string; before: number | null; after: number | null; delta: number | null }>;
  methods: Array<{ method: ScalingMethod; label: string; linear: boolean; centers: string; scales: string; outlier_robust: boolean; bounded: boolean; preserves_zero: boolean; max_correlation_delta: number; note: string }>;
  warnings: string[]; recommendation: string; methodology_note: string;
};
export type ScalingProfileResponse = {
  mode: "auto" | "enabled" | "disabled";
  status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null;
  profile: ScalingProfile;
};

type View = "preview" | "ranges" | "distribution" | "correlations" | "methods";
const TABS: Array<{ id: View; label: string }> = [
  { id: "preview", label: "До/после" }, { id: "ranges", label: "Масштабы" },
  { id: "distribution", label: "Распределение" }, { id: "correlations", label: "Корреляции" },
  { id: "methods", label: "Методы" },
];
const TICK = { fontSize: 9, fill: "#737373" };
const number = (value: number | null | undefined, digits = 3) => value == null ? "—" : value.toLocaleString("ru-RU", { maximumFractionDigits: digits });
const fmtX = (value: string) => value.length > 12 ? value.slice(0, 10) : value;


function PreviewView({ profile }: { profile: ScalingProfile }) {
  return <div role="img" aria-label="Ряд до и после диагностического масштабирования" className="min-h-0 flex-1 p-3"><ResponsiveContainer width="100%" height="100%"><LineChart data={profile.preview_points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x" tick={TICK} tickFormatter={fmtX} minTickGap={35} /><YAxis yAxisId="original" tick={TICK} width={48} /><YAxis yAxisId="scaled" orientation="right" tick={TICK} width={42} /><Tooltip /><Legend wrapperStyle={{ fontSize: 9 }} /><Line yAxisId="original" dataKey="original" name={`${profile.focus_column ?? "X"}: исходная`} stroke="#737373" dot={false} isAnimationActive={false} /><Line yAxisId="scaled" dataKey="scaled" name={profile.recommended_method} stroke="#7C3AED" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>;
}


function RangesView({ profile }: { profile: ScalingProfile }) {
  return <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 feed-scroll"><div role="img" aria-label="Сравнение масштабов числовых признаков" className="min-h-0 flex-1"><ResponsiveContainer width="100%" height="100%"><BarChart data={profile.range_points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="column" tick={TICK} interval={0} angle={-12} height={45} /><YAxis tick={TICK} width={38} label={{ value: "log10 σ", angle: -90, position: "insideLeft", fontSize: 9 }} /><Tooltip /><Legend wrapperStyle={{ fontSize: 9 }} /><Bar dataKey="log_scale_before" name="до" fill="#A3A3A3" /><Bar dataKey="log_scale_after" name="после" fill="#7C3AED" /></BarChart></ResponsiveContainer></div><p className="mt-2 shrink-0 text-[10px] text-neutral-500">Логарифмическая ось показывает, сколько порядков величины разделяет стандартные отклонения. Квартильные профили рассчитаны для {profile.box_points.length / 2 || 0} колонок.</p></div>;
}

function DistributionView({ profile }: { profile: ScalingProfile }) {
  return <div role="img" aria-label="Распределение до и после масштабирования" className="grid min-h-0 flex-1 grid-cols-2 gap-3 p-3"><ResponsiveContainer width="100%" height="100%"><LineChart data={profile.distribution_points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x_before" tick={TICK} /><YAxis tick={TICK} width={32} /><Tooltip /><Line dataKey="density_before" name="До" stroke="#737373" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer><ResponsiveContainer width="100%" height="100%"><LineChart data={profile.distribution_points}><CartesianGrid stroke="#F0F0F0" vertical={false} /><XAxis dataKey="x_after" tick={TICK} /><YAxis tick={TICK} width={32} /><Tooltip /><Line dataKey="density_after" name="После" stroke="#7C3AED" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>;
}

function CorrelationsView({ profile }: { profile: ScalingProfile }) {
  if (!profile.correlation_points.length) return <p role="status" className="p-8 text-center text-sm text-neutral-500">Для матрицы из одной колонки парные корреляции отсутствуют.</p>;
  return <div className="min-h-0 flex-1 overflow-auto p-3 feed-scroll"><table aria-label="Изменение корреляций после преобразования" className="w-full text-left text-xs"><thead className="sticky top-0 bg-white text-neutral-500"><tr><th className="p-2">Пара</th><th className="p-2">До</th><th className="p-2">После</th><th className="p-2">Δ</th></tr></thead><tbody>{profile.correlation_points.map((item) => <tr key={`${item.x}-${item.y}`} className="border-t border-neutral-100"><td className="p-2">{item.x} ↔ {item.y}</td><td className="p-2">{number(item.before)}</td><td className="p-2">{number(item.after)}</td><td className={`p-2 ${Math.abs(item.delta ?? 0) > 0.01 ? "text-amber-700" : "text-green-700"}`}>{number(item.delta, 5)}</td></tr>)}</tbody></table></div>;
}

function MethodsView({ profile }: { profile: ScalingProfile }) {
  return <div className="min-h-0 flex-1 overflow-auto p-3 feed-scroll"><table aria-label="Сравнение методов масштабирования" className="w-full min-w-[760px] text-left text-xs"><thead className="sticky top-0 bg-white text-neutral-500"><tr><th className="p-2">Метод</th><th className="p-2">Центр / масштаб</th><th className="p-2">Выбросы</th><th className="p-2">Линейный</th><th className="p-2">max |Δ corr|</th><th className="p-2">Контракт</th></tr></thead><tbody>{profile.methods.map((item) => <tr key={item.method} className={`border-t border-neutral-100 ${item.method === profile.recommended_method ? "bg-brand-light" : ""}`}><td className="p-2 font-medium">{item.label}</td><td className="p-2">{item.centers} / {item.scales}</td><td className="p-2">{item.outlier_robust ? "устойчив" : "чувствителен"}</td><td className="p-2">{item.linear ? "да" : "нет"}</td><td className="p-2">{number(item.max_correlation_delta, 5)}</td><td className="p-2 text-[10px] text-neutral-600">{item.note}</td></tr>)}</tbody></table></div>;
}

export function PreprocessingScalingOverview({ profile, loading, error, noDataset }: { profile: ScalingProfile | null; loading: boolean; error: string | null; noDataset: boolean }) {
  const [view, setView] = useState<View>("preview");
  if (loading) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Сравниваем масштабы признаков и методы…</div>;
  if (error) return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Загрузите датасет для настройки масштабирования.</div>;
  if (!profile) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Выберите числовой target для отделения X от цели.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Масштабирование неприменимо."}</div>;
  return <section className="flex h-[468px] min-h-0 flex-col overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll"><div className="shrink-0 border-b border-neutral-100 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h4 className="text-sm font-semibold">Матрица масштабов X для «{profile.target_column}»</h4><p className="mt-1 text-[10px] text-neutral-500">N={profile.n_observations} · target по умолчанию исключён · preview: {profile.focus_column ?? "—"}</p></div><div className="grid grid-cols-3 gap-2 text-center text-[10px]"><span className="rounded bg-neutral-50 px-2 py-1">X в рецепте<strong className="block text-xs">{profile.suggested_columns.length}</strong></span><span className="rounded bg-neutral-50 px-2 py-1">Разброс σ<strong className="block text-xs">×{number(profile.scale_ratio, 1)}</strong></span><span className="rounded bg-neutral-50 px-2 py-1">Метод<strong className="block text-xs">{profile.recommended_method}</strong></span></div></div><p className="mt-2 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p><div role="tablist" aria-label="Представления масштабирования" className="mt-3 flex flex-wrap gap-2">{TABS.map((tab) => <button key={tab.id} role="tab" aria-selected={view === tab.id} onClick={() => setView(tab.id)} className={`rounded-full border px-3 py-1 text-xs ${view === tab.id ? "border-neutral-300 bg-neutral-200 text-neutral-800" : "border-neutral-200 bg-neutral-50 text-neutral-500 hover:bg-neutral-100"}`}>{tab.label}</button>)}</div></div>{view === "preview" && <PreviewView profile={profile} />}{view === "ranges" && <RangesView profile={profile} />}{view === "distribution" && <DistributionView profile={profile} />}{view === "correlations" && <CorrelationsView profile={profile} />}{view === "methods" && <MethodsView profile={profile} />}<div className="shrink-0 border-t border-neutral-100 px-4 py-3 text-[9px] text-neutral-500"><p>{profile.methodology_note}</p>{profile.warnings.map((warning) => <p key={warning} className="mt-1 text-amber-700">{warning}</p>)}<p className="mt-2">Официальные источники: <a className="text-brand underline" href="https://scikit-learn.org/stable/modules/preprocessing.html" target="_blank" rel="noreferrer">scikit-learn preprocessing</a> · <a className="text-brand underline" href="https://scikit-learn.org/stable/common_pitfalls.html" target="_blank" rel="noreferrer">data leakage</a> · <a className="text-brand underline" href="https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.RobustScaler.html" target="_blank" rel="noreferrer">RobustScaler</a> · <a className="text-brand underline" href="https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.QuantileTransformer.html" target="_blank" rel="noreferrer">QuantileTransformer</a>.</p></div></section>;
}
