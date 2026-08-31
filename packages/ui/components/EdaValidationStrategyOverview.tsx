"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type ValidationStrategy = "expanding" | "sliding" | "single";

export interface EdaValidationFold {
  fold: number;
  train_start: number; train_end: number; train_size: number;
  gap_start: number | null; gap_end: number | null; gap_size: number;
  test_start: number; test_end: number; test_size: number;
  train_start_label: string | null; train_end_label: string | null;
  test_start_label: string | null; test_end_label: string | null;
}

export interface EdaValidationAlternative {
  strategy: ValidationStrategy;
  label: string;
  suitable: boolean;
  required_observations: number;
  reason: string;
}

export interface EdaValidationStrategyResponse {
  column: string; applicable: boolean; reason: string | null;
  strategy: ValidationStrategy; horizon: number; requested_splits: number; effective_splits: number;
  gap: number; train_window: number; min_train_observations: number;
  n_observations: number; missing_count: number; required_observations: number;
  initial_train_size: number; unused_observations: number; test_coverage: number;
  order_source: "time_column" | "row_order"; order_column: string | null;
  order_warning: string | null; frequency: string | null; comparable_duration: boolean;
  folds: EdaValidationFold[]; alternatives: EdaValidationAlternative[];
  recommendation: string | null; recommendations: string[]; warnings: string[];
}

export interface EdaValidationStrategyParameters {
  strategy: ValidationStrategy;
  horizon: number;
  nSplits: number;
  gap: number;
  trainWindow: number;
}

interface Props {
  profile: EdaValidationStrategyResponse | null;
  loading: boolean;
  error: string | null;
  noDataset: boolean;
  parameters: EdaValidationStrategyParameters;
  onParametersChange: (changes: Partial<EdaValidationStrategyParameters>) => void;
}

type View = "folds" | "train" | "alternatives" | "table";

const TABS: Array<{ id: View; label: string }> = [
  { id: "folds", label: "Схема folds" },
  { id: "train", label: "Размер train" },
  { id: "alternatives", label: "Альтернативы" },
  { id: "table", label: "Таблица" },
];

const STRATEGY_LABELS: Record<ValidationStrategy, string> = {
  expanding: "Расширяющееся окно",
  sliding: "Скользящее окно",
  single: "Финальный holdout",
};

function Select({ label, value, options, onChange, disabled = false }: {
  label: string; value: string | number; options: Array<{ value: string | number; label: string }>;
  onChange: (value: string) => void; disabled?: boolean;
}) {
  return <label className="text-[10px] text-neutral-500"><span className="block">{label}</span><select aria-label={label} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="mt-0.5 rounded border border-neutral-300 bg-white px-1.5 py-1 text-xs text-neutral-700 disabled:bg-neutral-100">{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
}

function Controls({ parameters, onChange }: { parameters: EdaValidationStrategyParameters; onChange: Props["onParametersChange"] }) {
  const numbers = (items: number[]) => items.map((value) => ({ value, label: String(value) }));
  return <div className="flex flex-wrap justify-end gap-2">
    <Select label="Схема" value={parameters.strategy} options={Object.entries(STRATEGY_LABELS).map(([value, label]) => ({ value, label }))} onChange={(value) => onChange({ strategy: value as ValidationStrategy })} />
    <Select label="Горизонт" value={parameters.horizon} options={numbers([1, 3, 6, 10, 12, 24, 30])} onChange={(value) => onChange({ horizon: Number(value) })} />
    <Select label="Число folds" value={parameters.nSplits} options={numbers([3, 5, 7, 10])} disabled={parameters.strategy === "single"} onChange={(value) => onChange({ nSplits: Number(value) })} />
    <Select label="Gap" value={parameters.gap} options={numbers([0, 1, 2, 6, 12])} onChange={(value) => onChange({ gap: Number(value) })} />
    <Select label="Train-окно" value={parameters.trainWindow} options={numbers([20, 40, 60, 120, 240])} disabled={parameters.strategy !== "sliding"} onChange={(value) => onChange({ trainWindow: Number(value) })} />
  </div>;
}

function FoldTimeline({ profile }: { profile: EdaValidationStrategyResponse }) {
  const width = (start: number, end: number) => `${Math.max(0, (end - start + 1) / profile.n_observations * 100)}%`;
  const left = (start: number) => `${start / profile.n_observations * 100}%`;
  return <div role="img" aria-label={`Схема временных folds для ${profile.column}`} className="space-y-3 p-4">
    <div className="flex flex-wrap gap-4 text-[10px] text-neutral-600"><span><i className="mr-1 inline-block h-2 w-3 rounded bg-blue-400" />Train</span><span><i className="mr-1 inline-block h-2 w-3 rounded bg-amber-300" />Gap</span><span><i className="mr-1 inline-block h-2 w-3 rounded bg-green-400" />Test</span><span className="ml-auto">0 … {profile.n_observations - 1}</span></div>
    {profile.folds.map((fold) => <div key={fold.fold} className="grid grid-cols-[48px_1fr] items-center gap-2"><span className="text-xs font-medium text-neutral-600">Fold {fold.fold}</span><div className="relative h-7 overflow-hidden rounded bg-neutral-100">
      <div title={`Train ${fold.train_start}–${fold.train_end}`} className="absolute top-0 h-full bg-blue-400" style={{ left: left(fold.train_start), width: width(fold.train_start, fold.train_end) }}><span className="pl-2 text-[9px] font-medium text-white">Train</span></div>
      {fold.gap_start !== null && fold.gap_end !== null ? <div title={`Gap ${fold.gap_start}–${fold.gap_end}`} className="absolute top-0 h-full bg-amber-300" style={{ left: left(fold.gap_start), width: width(fold.gap_start, fold.gap_end) }} /> : null}
      <div title={`Test ${fold.test_start}–${fold.test_end}`} className="absolute top-0 h-full bg-green-400" style={{ left: left(fold.test_start), width: width(fold.test_start, fold.test_end) }}><span className="pl-1 text-[9px] font-medium text-white">Test</span></div>
    </div></div>)}
    <p className="text-[11px] text-neutral-500">Последний test: {profile.folds.at(-1)?.test_start_label ?? profile.folds.at(-1)?.test_start} — {profile.folds.at(-1)?.test_end_label ?? profile.folds.at(-1)?.test_end}</p>
  </div>;
}

function TrainChart({ profile }: { profile: EdaValidationStrategyResponse }) {
  return <div role="img" aria-label={`Рост обучающего окна для ${profile.column}`} className="h-[270px] p-3"><ResponsiveContainer width="100%" height="100%"><BarChart data={profile.folds} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" /><XAxis dataKey="fold" tick={{ fontSize: 10 }} label={{ value: "Fold", position: "insideBottom", offset: -3, fontSize: 10 }} /><YAxis tick={{ fontSize: 10 }} width={48} /><Tooltip formatter={(value: number | string) => [value, "Train наблюдений"]} /><Bar dataKey="train_size" name="Train" fill="#60a5fa" isAnimationActive={false} /></BarChart></ResponsiveContainer></div>;
}

function Alternatives({ profile }: { profile: EdaValidationStrategyResponse }) {
  return <div className="grid gap-3 p-4 md:grid-cols-3">{profile.alternatives.map((item) => <article key={item.strategy} className={`rounded border p-3 ${item.strategy === profile.strategy ? "border-brand bg-brand-light" : "border-neutral-200"}`}><div className="flex items-start justify-between gap-2"><h5 className="text-xs font-semibold text-neutral-800">{item.label}</h5><span className={`rounded px-1.5 py-0.5 text-[9px] ${item.suitable ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>{item.suitable ? "доступно" : "мало данных"}</span></div><p className="mt-2 text-[11px] text-neutral-600">{item.reason}</p><p className="mt-2 text-[10px] text-neutral-500">Требуется ≥ {item.required_observations}</p></article>)}</div>;
}

function FoldTable({ profile }: { profile: EdaValidationStrategyResponse }) {
  return <div className="overflow-x-auto"><table aria-label="Границы временной валидации" className="w-full min-w-[760px] text-left text-xs"><thead className="bg-neutral-50 text-neutral-500"><tr><th className="px-2 py-2">Fold</th><th className="px-2 py-2">Train</th><th className="px-2 py-2 text-right">N train</th><th className="px-2 py-2">Gap</th><th className="px-2 py-2">Test</th><th className="px-2 py-2 text-right">N test</th></tr></thead><tbody>{profile.folds.map((fold) => <tr key={fold.fold} className="border-t border-neutral-100"><td className="px-2 py-2 font-medium">{fold.fold}</td><td className="px-2 py-2">{fold.train_start}–{fold.train_end}</td><td className="px-2 py-2 text-right tabular-nums">{fold.train_size}</td><td className="px-2 py-2">{fold.gap_size ? `${fold.gap_start}–${fold.gap_end}` : "—"}</td><td className="px-2 py-2">{fold.test_start}–{fold.test_end}</td><td className="px-2 py-2 text-right tabular-nums">{fold.test_size}</td></tr>)}</tbody></table></div>;
}

export function EdaValidationStrategyOverview({ profile, loading, error, noDataset, parameters, onParametersChange }: Props) {
  const [view, setView] = useState<View>("folds");
  return <section className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
    <div className="border-b border-neutral-100 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h4 className="text-sm font-semibold text-neutral-800">План временной валидации{profile ? ` «${profile.column}»` : ""}</h4>{profile ? <p className="mt-1 text-xs text-neutral-500">{STRATEGY_LABELS[profile.strategy]} · h={profile.horizon} · folds={profile.effective_splits} · gap={profile.gap}</p> : null}<p className="mt-1 text-[10px] text-neutral-500">Методология: <a className="text-brand underline" href="https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html" target="_blank" rel="noreferrer">scikit-learn TimeSeriesSplit</a> · <a className="text-brand underline" href="https://skforecast.org/latest/user_guides/backtesting.html" target="_blank" rel="noreferrer">skforecast backtesting</a></p></div><Controls parameters={parameters} onChange={onParametersChange} /></div>{profile?.recommendation ? <p className="mt-3 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p> : null}{profile?.warnings.length ? <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.warnings.join(" ")}</p> : null}</div>
    {loading ? <div role="status" className="flex h-[260px] items-center justify-center text-sm text-neutral-500">Строим временные folds…</div> : error ? <div role="alert" className="flex h-[260px] items-center justify-center bg-red-50 px-8 text-center text-sm text-red-700">{error}</div> : noDataset ? <div role="status" className="flex h-[260px] items-center justify-center text-sm text-neutral-600">Загрузите датасет, чтобы спроектировать валидацию.</div> : !profile ? <div role="status" className="flex h-[260px] items-center justify-center text-sm text-neutral-600">Выберите числовой исследуемый признак.</div> : !profile.applicable ? <div role="status" className="flex h-[260px] items-center justify-center bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Стратегия неприменима."}</div> : <><div role="tablist" aria-label="Представления стратегии валидации" className="flex flex-wrap gap-1 border-b border-neutral-100 px-4 pt-3">{TABS.map((tab) => <button key={tab.id} role="tab" aria-selected={view === tab.id} onClick={() => setView(tab.id)} className={`rounded-t px-3 py-2 text-xs font-medium ${view === tab.id ? "bg-brand text-white" : "bg-neutral-50 text-neutral-600 hover:bg-neutral-100"}`}>{tab.label}</button>)}</div>{view === "folds" ? <FoldTimeline profile={profile} /> : null}{view === "train" ? <TrainChart profile={profile} /> : null}{view === "alternatives" ? <Alternatives profile={profile} /> : null}{view === "table" ? <FoldTable profile={profile} /> : null}</>}
  </section>;
}
