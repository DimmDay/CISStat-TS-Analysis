"use client";

import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type ModelMatrixTask = "forecast" | "multivariate" | "volatility";
export type ModelCriterionStatus = "pass" | "attention" | "fail" | "unknown" | "not_required";
export type ModelCompatibility = "candidate" | "conditional" | "blocked";

export interface EdaModelCriterion {
  id: string; label: string; status: ModelCriterionStatus; observed: string;
  requirement: string; conclusion: string; blocking: boolean;
}

export interface EdaModelMatrixModel {
  model_id: string; model_name: string; family_id: string; family_name: string;
  compatibility: ModelCompatibility; platform_status: "ready" | "catalog_only";
  min_observations: number; supports_exogenous: boolean; libraries: string[];
  training_time: string; criteria: EdaModelCriterion[];
  blocking_reasons: string[]; cautions: string[];
}

export interface EdaModelMatrixFamily {
  family_id: string; family_name: string; candidates: number; conditional: number;
  blocked: number; ready: number; catalog_only: number;
}

export interface EdaModelMatrixResponse {
  column: string; applicable: boolean; reason: string | null; task: ModelMatrixTask;
  horizon: number; spec_version: string;
  profile: {
    n_observations: number; missing_count: number; numeric_series_count: number; n_exogenous: number;
    order_source: "time_column" | "row_order"; order_column: string | null; frequency: string | null;
    is_regular: boolean | null; temporal_status: "regular" | "irregular" | "panel" | "invalid" | "unknown";
    seasonality_status: "present" | "absent" | "unknown"; seasonal_periods: number[];
    stationarity_status: "stationary" | "non_stationary" | "inconclusive" | "unknown";
    has_negative_values: boolean; validation_strategy?: "expanding" | "sliding" | "single";
    initial_train_observations?: number; required_observations?: number;
  };
  summary: { total_models: number; candidates: number; conditional: number; blocked: number; ready: number; catalog_only: number };
  families: EdaModelMatrixFamily[]; models: EdaModelMatrixModel[];
  shortlist: string[]; runnable_shortlist: string[]; recommendation: string;
  methodology_note: string; warnings: string[];
}

export interface EdaModelMatrixParameters { task: ModelMatrixTask; horizon: number }

interface Props {
  profile: EdaModelMatrixResponse | null; loading: boolean; error: string | null; noDataset: boolean;
  parameters: EdaModelMatrixParameters;
  onParametersChange: (changes: Partial<EdaModelMatrixParameters>) => void;
}

type View = "matrix" | "families" | "shortlist" | "details";

const TABS: Array<{ id: View; label: string }> = [
  { id: "matrix", label: "Матрица" },
  { id: "families", label: "Семейства" },
  { id: "shortlist", label: "Shortlist" },
  { id: "details", label: "Детали" },
];

const TASK_LABELS: Record<ModelMatrixTask, string> = {
  forecast: "Прогноз уровня", multivariate: "Многомерная система", volatility: "Волатильность",
};
const COMPATIBILITY_LABELS: Record<ModelCompatibility, string> = {
  candidate: "совместима", conditional: "с оговорками", blocked: "заблокирована",
};
const STATUS_CELL: Record<ModelCriterionStatus, { label: string; className: string }> = {
  pass: { label: "✓", className: "bg-green-100 text-green-800" },
  attention: { label: "!", className: "bg-amber-100 text-amber-800" },
  fail: { label: "×", className: "bg-red-100 text-red-800" },
  unknown: { label: "?", className: "bg-sky-100 text-sky-800" },
  not_required: { label: "—", className: "bg-neutral-100 text-neutral-500" },
};
const COMPATIBILITY_BADGE: Record<ModelCompatibility, string> = {
  candidate: "bg-green-50 text-green-700", conditional: "bg-amber-50 text-amber-700", blocked: "bg-red-50 text-red-700",
};

function Controls({ parameters, onChange }: { parameters: EdaModelMatrixParameters; onChange: Props["onParametersChange"] }) {
  return <div className="flex flex-wrap justify-end gap-2">
    <label className="text-[10px] text-neutral-500"><span className="block">Задача</span><select aria-label="Задача" value={parameters.task} onChange={(event) => onChange({ task: event.target.value as ModelMatrixTask })} className="mt-0.5 rounded border border-neutral-300 bg-white px-1.5 py-1 text-xs text-neutral-700">{Object.entries(TASK_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <label className="text-[10px] text-neutral-500"><span className="block">Горизонт</span><select aria-label="Горизонт" value={parameters.horizon} onChange={(event) => onChange({ horizon: Number(event.target.value) })} className="mt-0.5 rounded border border-neutral-300 bg-white px-1.5 py-1 text-xs text-neutral-700">{[1, 3, 6, 10, 12, 24, 30].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
  </div>;
}

function RequirementMatrix({ profile }: { profile: EdaModelMatrixResponse }) {
  const criteria = useMemo(() => {
    const first = profile.models[0]?.criteria ?? [];
    return first.map((item) => ({ id: item.id, label: item.label }));
  }, [profile.models]);
  return <div className="overflow-auto p-3"><table aria-label="Тепловая карта применимости моделей" className="w-full min-w-[980px] text-left text-[10px]"><thead className="sticky top-0 bg-white text-neutral-500"><tr><th className="px-2 py-2">Модель</th><th className="px-2 py-2">Итог</th>{criteria.map((item) => <th key={item.id} className="px-1 py-2 text-center">{item.label}</th>)}</tr></thead><tbody>{profile.models.map((model) => <tr key={model.model_id} className="border-t border-neutral-100"><td className="px-2 py-1.5"><span className="block font-medium text-neutral-800">{model.model_name}</span><span className="text-[9px] text-neutral-400">{model.family_name}</span></td><td className="px-2 py-1.5"><span className={`rounded px-1.5 py-0.5 ${COMPATIBILITY_BADGE[model.compatibility]}`}>{COMPATIBILITY_LABELS[model.compatibility]}</span></td>{criteria.map(({ id }) => { const item = model.criteria.find((candidate) => candidate.id === id); const visual = STATUS_CELL[item?.status ?? "unknown"]; return <td key={id} className="px-1 py-1.5 text-center"><span title={item ? `${item.observed}. ${item.conclusion}` : "Нет данных"} aria-label={`${model.model_name}: ${item?.label ?? id} — ${visual.label}`} className={`inline-flex h-6 w-7 items-center justify-center rounded font-semibold ${visual.className}`}>{visual.label}</span></td>; })}</tr>)}</tbody></table><div className="mt-3 flex flex-wrap gap-3 text-[10px] text-neutral-500">{Object.entries(STATUS_CELL).map(([id, item]) => <span key={id}><i className={`mr-1 inline-flex h-4 w-5 items-center justify-center rounded not-italic ${item.className}`}>{item.label}</i>{({ pass: "выполнено", attention: "нужно действие", fail: "блокирует", unknown: "неизвестно", not_required: "не требуется" } as Record<string, string>)[id]}</span>)}</div></div>;
}

function FamilyChart({ profile }: { profile: EdaModelMatrixResponse }) {
  const data = profile.families.map((item) => ({ ...item, name: item.family_name.replace("Экспоненциальное сглаживание / State Space", "ETS / State Space") }));
  return <div role="img" aria-label="Сводка применимости по семействам" className="h-[310px] p-3"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{ left: 20, right: 18, top: 5, bottom: 5 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" /><XAxis type="number" allowDecimals={false} tick={{ fontSize: 9 }} /><YAxis type="category" dataKey="name" width={132} tick={{ fontSize: 9 }} /><Tooltip /><Legend wrapperStyle={{ fontSize: 10 }} /><Bar dataKey="candidates" name="Совместимы" stackId="a" fill="#4ade80" isAnimationActive={false} /><Bar dataKey="conditional" name="С оговорками" stackId="a" fill="#fbbf24" isAnimationActive={false} /><Bar dataKey="blocked" name="Заблокированы" stackId="a" fill="#f87171" isAnimationActive={false} /></BarChart></ResponsiveContainer></div>;
}

function Shortlist({ profile }: { profile: EdaModelMatrixResponse }) {
  const rows = profile.models.filter((item) => profile.shortlist.includes(item.model_id));
  return <div className="grid gap-3 p-4 md:grid-cols-2">{rows.length ? rows.map((model) => <article key={model.model_id} className="rounded border border-neutral-200 p-3"><div className="flex items-start justify-between gap-2"><div><h5 className="text-xs font-semibold text-neutral-800">{model.model_name}</h5><p className="text-[10px] text-neutral-500">{model.family_name}</p></div><span className={`rounded px-1.5 py-0.5 text-[9px] ${COMPATIBILITY_BADGE[model.compatibility]}`}>{COMPATIBILITY_LABELS[model.compatibility]}</span></div><p className={`mt-2 text-[10px] font-medium ${model.platform_status === "ready" ? "text-green-700" : "text-amber-700"}`}>{model.platform_status === "ready" ? "Backend: готова к backtest" : "Backend: только каталог"}</p>{model.cautions.length ? <p className="mt-2 text-[10px] text-neutral-600">{model.cautions[0]}</p> : null}<p className="mt-2 text-[9px] text-neutral-400">{model.libraries.length ? model.libraries.join(" · ") : "встроенный baseline"}</p></article>) : <p className="col-span-2 rounded bg-amber-50 p-4 text-sm text-amber-800">При текущей задаче и схеме валидации shortlist пуст.</p>}</div>;
}

function DetailTable({ profile }: { profile: EdaModelMatrixResponse }) {
  return <div className="overflow-auto"><table aria-label="Детальные выводы матрицы моделей" className="w-full min-w-[900px] text-left text-xs"><thead className="bg-neutral-50 text-neutral-500"><tr><th className="px-2 py-2">Модель</th><th className="px-2 py-2">Статус</th><th className="px-2 py-2">Блокирует</th><th className="px-2 py-2">Оговорки</th><th className="px-2 py-2">Backend</th></tr></thead><tbody>{profile.models.map((model) => <tr key={model.model_id} className="border-t border-neutral-100 align-top"><td className="px-2 py-2 font-medium">{model.model_name}</td><td className="px-2 py-2">{COMPATIBILITY_LABELS[model.compatibility]}</td><td className="max-w-[260px] px-2 py-2 text-[10px] text-red-700">{model.blocking_reasons.join(" ") || "—"}</td><td className="max-w-[320px] px-2 py-2 text-[10px] text-amber-800">{model.cautions.join(" ") || "—"}</td><td className="px-2 py-2">{model.platform_status === "ready" ? "готов" : "только каталог"}</td></tr>)}</tbody></table></div>;
}

export function EdaModelMatrixOverview({ profile, loading, error, noDataset, parameters, onParametersChange }: Props) {
  const [view, setView] = useState<View>("matrix");
  return <section className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
    <div className="border-b border-neutral-100 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h4 className="text-sm font-semibold text-neutral-800">Матрица применимости{profile ? ` «${profile.column}»` : ""}</h4>{profile ? <p className="mt-1 text-xs text-neutral-500">{TASK_LABELS[profile.task]} · h={profile.horizon} · каталог {profile.spec_version}</p> : null}<p className="mt-1 text-[10px] text-neutral-500">Реализации: <a className="text-brand underline" href="https://www.statsmodels.org/stable/tsa/" target="_blank" rel="noreferrer">statsmodels TSA</a> · <a className="text-brand underline" href="https://nixtlaverse.nixtla.io/statsforecast/index.html" target="_blank" rel="noreferrer">StatsForecast</a> · <a className="text-brand underline" href="https://nixtlaverse.nixtla.io/neuralforecast/docs/getting-started/introduction.html" target="_blank" rel="noreferrer">NeuralForecast</a></p></div><Controls parameters={parameters} onChange={onParametersChange} /></div>{profile?.recommendation ? <p className="mt-3 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p> : null}{profile?.warnings.length ? <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.warnings.join(" ")}</p> : null}</div>
    {loading ? <div role="status" className="flex h-[260px] items-center justify-center text-sm text-neutral-500">Проверяем требования 24 моделей…</div> : error ? <div role="alert" className="flex h-[260px] items-center justify-center bg-red-50 px-8 text-center text-sm text-red-700">{error}</div> : noDataset ? <div role="status" className="flex h-[260px] items-center justify-center text-sm text-neutral-600">Загрузите датасет, чтобы построить матрицу.</div> : !profile ? <div role="status" className="flex h-[260px] items-center justify-center text-sm text-neutral-600">Выберите числовой исследуемый признак.</div> : !profile.applicable ? <div role="status" className="flex h-[260px] items-center justify-center bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Матрица неприменима."}</div> : <><div role="tablist" aria-label="Представления матрицы моделей" className="flex flex-wrap gap-1 border-b border-neutral-100 px-4 pt-3">{TABS.map((tab) => <button key={tab.id} role="tab" aria-selected={view === tab.id} onClick={() => setView(tab.id)} className={`rounded-t px-3 py-2 text-xs font-medium ${view === tab.id ? "bg-brand text-white" : "bg-neutral-50 text-neutral-600 hover:bg-neutral-100"}`}>{tab.label}</button>)}</div>{view === "matrix" ? <RequirementMatrix profile={profile} /> : null}{view === "families" ? <FamilyChart profile={profile} /> : null}{view === "shortlist" ? <Shortlist profile={profile} /> : null}{view === "details" ? <DetailTable profile={profile} /> : null}</>}
  </section>;
}
