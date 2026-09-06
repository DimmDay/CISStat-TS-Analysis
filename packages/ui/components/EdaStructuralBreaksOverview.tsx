"use client";

import { useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
// Task 97.2 (Этап 2, spec_max_graf_fix.md §4.4): интеграция раскрытия графиков.
// Корень Обзора: relative всегда (правка A), overflow переключается по
// expandedChartId (правка C); графики вкладок обёрнуты в ExpandableChartPanel.
// Task 97.3 (Этап 3, spec_max_graf_fix.md §6.3): панели «Режимы» и «CUSUM»
// при раскрытии дозагружают detail_level=expanded (LTTB-потолок series/
// cusum_path растёт TARGET_SAMPLED_POINTS → EXPANDED_TARGET_SAMPLED_POINTS);
// «Чувствительность» плотного ряда не содержит — раскрытие остаётся
// чисто визуальным (§6.3.6). Пока запрос летит, показывается компактный
// график + лёгкий индикатор сверху панели (§6.3.3).
import { ExpandableChartPanel } from "./ExpandableChartPanel";
import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import { useExpandableChartState } from "../hooks/useExpandableChart";
import { useChartDetailData } from "../hooks/useChartDetailData";

export interface EdaStructuralBreakCandidate {
  rank: number; index: number; label: string | null; level_change: number;
  standardized_level_change: number; slope_before: number; slope_after: number;
  slope_change: number; rss_gain: number; chow_statistic: number; p_value: number;
  adjusted_p_value: number | null; stability_support: number; supported: boolean;
}
export interface EdaStructuralBreaksResponse {
  column: string; applicable: boolean; reason: string | null; n_observations: number;
  missing_count: number; min_observations: number; alpha: number;
  requested_min_segment: number; min_segment: number;
  requested_penalty_multiplier: number; penalty_multiplier: number; penalty_value: number | null;
  max_breaks: number; jump: number; model: "piecewise_linear";
  status: "breaks_detected" | "candidates_only" | "global_instability" | "stable" | "not_applicable";
  break_count: number; supported_count: number; order_source: "time_column" | "row_order";
  order_column: string | null; order_warning: string | null; frequency: string | null;
  cusum: { statistic: number | null; p_value: number | null; reject_stability: boolean | null; critical_values: Record<string, number> };
  candidates: EdaStructuralBreakCandidate[];
  segments: Array<{ id: number; start_index: number; end_index: number; start_label: string | null; end_label: string | null; n_observations: number; mean: number; std: number; slope: number }>;
  series: Array<{ index: number; label: string | null; value: number; fitted: number; segment_id: number }>;
  cusum_path: Array<{ index: number; label: string | null; value: number; upper: number; lower: number }>;
  sensitivity: Array<{ penalty_multiplier: number; index: number; label: string | null }>;
  series_sampled: boolean; series_original_count: number; cusum_sampled: boolean;
  recommendation: string | null; recommendations: string[]; warnings: string[];
}
export interface EdaStructuralBreaksParameters { alpha: number; minSegment: number; penaltyMultiplier: number }

interface Props {
  profile: EdaStructuralBreaksResponse | null;
  loading: boolean;
  error: string | null;
  noDataset: boolean;
  parameters: EdaStructuralBreaksParameters;
  onParametersChange: (changes: Partial<EdaStructuralBreaksParameters>) => void;
  /** Идентичность датасета (datasetId) — ключ инвалидации кэша detail_level. */
  datasetKey?: string | null;
}

/** Параметры compact-запроса контейнера (методология expanded обязана
 * совпадать с compact, §6.4) — единая сборка для обеих панелей. */
function detailParams(profile: EdaStructuralBreaksResponse | null, parameters: EdaStructuralBreaksParameters) {
  return {
    column: profile?.column,
    alpha: parameters.alpha,
    min_segment: parameters.minSegment,
    penalty_multiplier: parameters.penaltyMultiplier,
  };
}

type StructuralView = "regimes" | "cusum" | "sensitivity" | "segments" | "candidates";
const TABS: Array<{ id: StructuralView; label: string }> = [
  { id: "regimes", label: "Режимы" }, { id: "cusum", label: "CUSUM" },
  { id: "sensitivity", label: "Чувствительность" }, { id: "segments", label: "Сегменты" },
  { id: "candidates", label: "Кандидаты" },
];
const STATUS_LABELS: Record<EdaStructuralBreaksResponse["status"], string> = {
  breaks_detected: "Устойчивые сдвиги обнаружены", candidates_only: "Есть неподтверждённые кандидаты",
  global_instability: "Обнаружена общая нестабильность", stable: "Сдвиги не обнаружены",
  not_applicable: "Диагностика неприменима",
};

function number(value: number | null | undefined, digits = 4): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? "—" : value.toLocaleString("ru-RU", { maximumFractionDigits: digits });
}
function position(label: string | null, index: number): string {
  return label ? new Date(label).toLocaleDateString("ru-RU") : `№ ${index}`;
}
function ParameterSelect({ label, value, options, onChange }: { label: string; value: number; options: number[]; onChange: (value: number) => void }) {
  return <label className="text-[10px] text-neutral-500"><span className="block">{label}</span><select aria-label={label} value={value} onChange={(event) => onChange(Number(event.target.value))} className="mt-0.5 rounded border border-neutral-300 bg-white px-1.5 py-1 text-xs text-neutral-700">{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>;
}

function Regimes({ profile }: { profile: EdaStructuralBreaksResponse }) {
  return <div role="img" aria-label={`Режимы и структурные сдвиги для ${profile.column}`} className="min-h-0 flex-1 px-2 py-3"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={profile.series} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5"/><XAxis dataKey="index" type="number" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10 }}/><YAxis tick={{ fontSize: 10 }} width={58}/><Tooltip labelFormatter={(value) => `Наблюдение ${value}`} formatter={(value: number | string, name: string) => [typeof value === "number" ? number(value) : value, name === "value" ? "Ряд" : "Кусочно-линейная оценка"]}/><Line dataKey="value" name="Ряд" stroke="#94a3b8" strokeWidth={1.2} dot={false} isAnimationActive={false}/><Line dataKey="fitted" name="Кусочно-линейная оценка" stroke="#2563eb" strokeWidth={2.2} dot={false} isAnimationActive={false}/>{profile.candidates.map((item) => <ReferenceLine key={item.index} x={item.index} stroke={item.supported ? "#dc2626" : "#f59e0b"} strokeDasharray={item.supported ? undefined : "4 3"}/>)}</ComposedChart></ResponsiveContainer></div>;
}
function Cusum({ profile }: { profile: EdaStructuralBreaksResponse }) {
  return <div role="img" aria-label={`CUSUM-диагностика для ${profile.column}`} className="min-h-0 flex-1 px-2 py-3"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={profile.cusum_path} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5"/><XAxis dataKey="index" type="number" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10 }}/><YAxis tick={{ fontSize: 10 }} width={58}/><Tooltip formatter={(value: number | string, name: string) => [typeof value === "number" ? number(value) : value, name === "value" ? "Накопленные остатки" : "Критическая граница"]}/><Line dataKey="value" stroke="#2563eb" strokeWidth={2} dot={false} isAnimationActive={false}/><Line dataKey="upper" stroke="#dc2626" strokeDasharray="5 3" dot={false} isAnimationActive={false}/><Line dataKey="lower" stroke="#dc2626" strokeDasharray="5 3" dot={false} isAnimationActive={false}/></ComposedChart></ResponsiveContainer></div>;
}
function Sensitivity({ profile }: { profile: EdaStructuralBreaksResponse }) {
  return <div role="img" aria-label={`Устойчивость точек PELT для ${profile.column}`} className="min-h-0 flex-1 px-2 py-3"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={profile.sensitivity} margin={{ top: 8, right: 18, left: 4, bottom: 12 }}><CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5"/><XAxis dataKey="index" type="number" domain={[0, profile.n_observations - 1]} tick={{ fontSize: 10 }} name="Положение"/><YAxis dataKey="penalty_multiplier" type="number" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10 }} width={48} name="Множитель штрафа"/><Tooltip formatter={(value: number | string, name: string) => [value, name === "penalty_multiplier" ? "Множитель штрафа" : "Положение"]}/><Scatter dataKey="penalty_multiplier" fill="#2563eb" isAnimationActive={false}/></ComposedChart></ResponsiveContainer></div>;
}
function Segments({ profile }: { profile: EdaStructuralBreaksResponse }) {
  return <div className="shrink-0 overflow-x-auto"><table aria-label="Сегменты ряда" className="w-full min-w-[720px] text-left text-xs"><thead className="sticky top-0 bg-neutral-50 text-neutral-500"><tr><th className="px-2 py-2">Режим</th><th className="px-2 py-2">Период</th><th className="px-2 py-2 text-right">N</th><th className="px-2 py-2 text-right">Среднее</th><th className="px-2 py-2 text-right">Станд. откл.</th><th className="px-2 py-2 text-right">Наклон</th></tr></thead><tbody>{profile.segments.map((item) => <tr key={item.id} className="border-t border-neutral-100 text-neutral-700"><td className="px-2 py-2 font-medium">{item.id}</td><td className="px-2 py-2">{position(item.start_label, item.start_index)} — {position(item.end_label, item.end_index)}</td><td className="px-2 py-2 text-right">{item.n_observations}</td><td className="px-2 py-2 text-right">{number(item.mean)}</td><td className="px-2 py-2 text-right">{number(item.std)}</td><td className="px-2 py-2 text-right">{number(item.slope, 6)}</td></tr>)}</tbody></table></div>;
}
function Candidates({ profile }: { profile: EdaStructuralBreaksResponse }) {
  return <div className="shrink-0 overflow-x-auto"><table aria-label="Кандидаты структурных сдвигов" className="w-full min-w-[900px] text-left text-xs"><thead className="sticky top-0 bg-neutral-50 text-neutral-500"><tr><th className="px-2 py-2">Точка</th><th className="px-2 py-2 text-right">Δ уровня</th><th className="px-2 py-2 text-right">Δ наклона</th><th className="px-2 py-2 text-right">Выигрыш RSS</th><th className="px-2 py-2 text-right">p после Холма</th><th className="px-2 py-2 text-right">Устойчивость</th><th className="px-2 py-2">Вывод</th></tr></thead><tbody>{profile.candidates.map((item) => <tr key={item.index} className="border-t border-neutral-100 text-neutral-700"><td className="px-2 py-2 font-medium">{position(item.label, item.index)}</td><td className="px-2 py-2 text-right">{number(item.level_change)}</td><td className="px-2 py-2 text-right">{number(item.slope_change, 6)}</td><td className="px-2 py-2 text-right">{number(item.rss_gain)}</td><td className="px-2 py-2 text-right">{number(item.adjusted_p_value)}</td><td className="px-2 py-2 text-right">{number(100 * item.stability_support, 1)}%</td><td className={`px-2 py-2 font-medium ${item.supported ? "text-red-700" : "text-amber-700"}`}>{item.supported ? "поддержан" : "кандидат"}</td></tr>)}</tbody></table></div>;
}

export function EdaStructuralBreaksOverview(props: Props) {
  return (
    <ExpandableChartsProvider>
      <EdaStructuralBreaksOverviewInner {...props} />
    </ExpandableChartsProvider>
  );
}

function EdaStructuralBreaksOverviewInner({ profile, loading, error, noDataset, parameters, onParametersChange, datasetKey }: Props) {
  const [activeView, setActiveView] = useState<StructuralView>("regimes");
  const { expandedChartId } = useExpandableChartState();
  // Task 97.3 (§6.3): дозагрузка expanded для плотных панелей. Хуки до
  // ранних return'ов (правила хуков); при свёрнутых панелях network нет.
  const regimesDetail = useChartDetailData<EdaStructuralBreaksResponse>({
    path: "/dataset/eda-structural-breaks",
    profileKey: "structural-regimes",
    params: detailParams(profile, parameters),
    fingerprint: datasetKey,
    enabled: expandedChartId === "structural-regimes",
  });
  const cusumDetail = useChartDetailData<EdaStructuralBreaksResponse>({
    path: "/dataset/eda-structural-breaks",
    profileKey: "structural-cusum",
    params: detailParams(profile, parameters),
    fingerprint: datasetKey,
    enabled: expandedChartId === "structural-cusum",
  });
  if (loading) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Ищем изменения уровня и наклона…</div>;
  if (error) return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Загрузите датасет, чтобы исследовать структурные сдвиги.</div>;
  if (!profile) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Диагностика структурных сдвигов неприменима."}</div>;
  return <section className={`relative flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white feed-scroll ${expandedChartId ? "overflow-hidden" : "overflow-y-auto"}`}><div className="shrink-0 border-b border-neutral-100 p-4"><div className="flex items-start justify-between gap-4"><div><div className="flex flex-wrap items-center gap-2"><h4 className="text-sm font-semibold text-neutral-800">Структурные сдвиги «{profile.column}»</h4><span className={`rounded px-2 py-0.5 text-[10px] font-medium ${profile.status === "stable" ? "bg-green-50 text-green-700" : profile.status === "breaks_detected" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700"}`}>{STATUS_LABELS[profile.status]}</span></div><p className="mt-1 text-xs text-neutral-500">n={profile.n_observations} · CUSUM p={number(profile.cusum.p_value)} · кандидатов {profile.break_count} · поддержано {profile.supported_count}</p></div><div className="flex shrink-0 gap-2"><ParameterSelect label="Уровень значимости α" value={parameters.alpha} options={[0.01, 0.05, 0.1]} onChange={(value) => onParametersChange({ alpha: value })}/><ParameterSelect label="Минимальная длина сегмента" value={parameters.minSegment} options={[10, 20, 30, 50]} onChange={(value) => onParametersChange({ minSegment: value })}/><ParameterSelect label="Штраф PELT" value={parameters.penaltyMultiplier} options={[0.75, 1, 2, 3, 5]} onChange={(value) => onParametersChange({ penaltyMultiplier: value })}/></div></div>{profile.recommendation && <p className="mt-3 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p>}{profile.warnings.length > 0 && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.warnings.join(" ")}</p>}</div><div role="tablist" aria-label="Представления структурных сдвигов" className="flex shrink-0 flex-wrap gap-1 border-b border-neutral-100 px-4 pt-3">{TABS.map((tab) => <button key={tab.id} role="tab" aria-selected={activeView === tab.id} onClick={() => setActiveView(tab.id)} className={`rounded-t px-3 py-2 text-xs font-medium ${activeView === tab.id ? "bg-brand text-white" : "bg-neutral-50 text-neutral-600 hover:bg-neutral-100"}`}>{tab.label}</button>)}</div>{activeView === "regimes" && <ExpandableChartPanel chartId="structural-regimes" title="Режимы и структурные сдвиги">{regimesDetail.loading && <div aria-hidden="true" className="absolute left-0 right-0 top-0 z-30 h-0.5 animate-pulse bg-brand" />}<Regimes profile={regimesDetail.data ?? profile}/></ExpandableChartPanel>} {activeView === "cusum" && <ExpandableChartPanel chartId="structural-cusum" title="CUSUM-диагностика">{cusumDetail.loading && <div aria-hidden="true" className="absolute left-0 right-0 top-0 z-30 h-0.5 animate-pulse bg-brand" />}<Cusum profile={cusumDetail.data ?? profile}/></ExpandableChartPanel>} {activeView === "sensitivity" && <ExpandableChartPanel chartId="structural-sensitivity" title="Устойчивость точек PELT"><Sensitivity profile={profile}/></ExpandableChartPanel>} {activeView === "segments" && <Segments profile={profile}/>} {activeView === "candidates" && <Candidates profile={profile}/>}</section>;
}
