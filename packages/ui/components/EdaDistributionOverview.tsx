"use client";

import { useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
// Task 97.4 (Этап 4, spec_max_graf_fix.md §8): тиражирование раскрытия
// графиков. Корень Обзора: relative всегда (правка A), overflow переключается
// по expandedChartId (правка C); графические представления обёрнуты в
// ExpandableChartPanel (уровень ИСПОЛЬЗОВАНИЯ, §7.2), таблица «Тесты» —
// без панели. detail_level не заказан (Этап 5 опционален) — раскрытие
// чисто визуальное, с compact-данными.
import { ExpandableChartPanel } from "./ExpandableChartPanel";
import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import { useExpandableChartState } from "../hooks/useExpandableChart";

export type DistributionNormalityStatus = "compatible" | "departed" | "inconclusive" | "not_applicable";

export interface EdaDistributionTest {
  id: "shapiro" | "jarque_bera" | "lilliefors";
  label: string;
  available: boolean;
  statistic: number | null;
  p_value: number | null;
  adjusted_p_value: number | null;
  reject_normality: boolean | null;
  n_used: number | null;
  calibration: "standard" | "monte_carlo" | "asymptotic" | "table" | null;
  note: string | null;
}

export interface EdaDistributionResponse {
  column: string;
  applicable: boolean;
  reason: string | null;
  n_observations: number;
  missing_count: number;
  min_observations: number;
  alpha: number;
  requested_bins: number;
  bins: number;
  is_discrete: boolean;
  unique_count: number;
  mean: number | null;
  median: number | null;
  std: number | null;
  q1: number | null;
  q3: number | null;
  iqr: number | null;
  mad: number | null;
  skewness: number | null;
  excess_kurtosis: number | null;
  shape_label: string;
  normality_applicable: boolean;
  normality_status: DistributionNormalityStatus;
  qq_r: number | null;
  qq_slope: number | null;
  qq_intercept: number | null;
  tests: EdaDistributionTest[];
  histogram: Array<{ x0: number; x1: number; count: number; density: number; normal_expected_count: number }>;
  density: Array<{ x: number; empirical: number; normal: number }>;
  qq: Array<{ theoretical: number; observed: number; reference: number }>;
  cdf: Array<{ x: number; empirical: number; normal: number }>;
  recommendation: string | null;
  recommendations: string[];
  warnings: string[];
}

export interface EdaDistributionParameters {
  alpha: number;
  bins: number;
}

interface EdaDistributionOverviewProps {
  profile: EdaDistributionResponse | null;
  loading: boolean;
  error: string | null;
  noDataset: boolean;
  parameters: EdaDistributionParameters;
  onParametersChange: (changes: Partial<EdaDistributionParameters>) => void;
}

type DistributionView = "histogram" | "density" | "qq" | "cdf" | "tests";

const TABS: Array<{ id: DistributionView; label: string }> = [
  { id: "histogram", label: "Гистограмма" },
  { id: "density", label: "Плотность" },
  { id: "qq", label: "Q–Q" },
  { id: "cdf", label: "F(x)" },
  { id: "tests", label: "Тесты" },
];

const STATUS_LABELS: Record<DistributionNormalityStatus, string> = {
  compatible: "Совместимо с нормальной формой",
  departed: "Есть отклонение от нормальной формы",
  inconclusive: "Результат неоднозначен",
  not_applicable: "Тесты неприменимы",
};

const CALIBRATION_LABELS: Record<NonNullable<EdaDistributionTest["calibration"]>, string> = {
  standard: "стандартная",
  monte_carlo: "Монте-Карло",
  asymptotic: "асимптотическая",
  table: "табличная",
};

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("ru-RU", { maximumFractionDigits: digits });
}

function ParameterSelect({ label, value, options, onChange }: {
  label: string;
  value: number;
  options: number[];
  onChange: (value: number) => void;
}) {
  return (
    <label className="text-[10px] text-neutral-500">
      <span className="block">{label}</span>
      <select aria-label={label} value={value} onChange={(event) => onChange(Number(event.target.value))} className="mt-0.5 rounded border border-neutral-300 bg-white px-1.5 py-1 text-xs text-neutral-700">
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function HistogramView({ profile }: { profile: EdaDistributionResponse }) {
  const data = profile.histogram.map((item) => ({ ...item, interval: `${formatNumber(item.x0)}–${formatNumber(item.x1)}` }));
  return (
    <div role="img" aria-label={`Гистограмма распределения для ${profile.column}`} className="min-h-0 flex-1 px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 18, left: 4, bottom: 18 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis dataKey="interval" tick={{ fontSize: 9 }} interval="preserveStartEnd" angle={-10} textAnchor="end" height={42} />
          <YAxis tick={{ fontSize: 10 }} width={52} />
          <Tooltip formatter={(value: number | string, name: string) => [typeof value === "number" ? formatNumber(value) : value, name === "count" ? "Наблюдения" : "Ожидается при нормальной форме"]} />
          <Bar dataKey="count" name="Наблюдения" fill="#93c5fd" isAnimationActive={false} />
          <Line type="monotone" dataKey="normal_expected_count" name="Нормальная форма" stroke="#dc2626" strokeWidth={2} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function DensityView({ profile }: { profile: EdaDistributionResponse }) {
  return (
    <div role="img" aria-label={`Сравнение плотностей для ${profile.column}`} className="min-h-0 flex-1 px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={profile.density} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} width={58} />
          <Tooltip formatter={(value: number | string, name: string) => [typeof value === "number" ? formatNumber(value, 6) : value, name === "empirical" ? "Оценка KDE" : "Нормальная плотность"]} />
          <Line type="monotone" dataKey="empirical" name="Оценка KDE" stroke="#2563eb" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="normal" name="Нормальная плотность" stroke="#dc2626" strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function QqView({ profile }: { profile: EdaDistributionResponse }) {
  return (
    <div role="img" aria-label={`Q–Q график для ${profile.column}`} className="min-h-0 flex-1 px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={profile.qq} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis dataKey="theoretical" type="number" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10 }} name="Теоретический квантиль" />
          <YAxis dataKey="observed" type="number" domain={["auto", "auto"]} tick={{ fontSize: 10 }} width={58} name="Наблюдаемый квантиль" />
          <Tooltip formatter={(value: number | string) => typeof value === "number" ? formatNumber(value) : value} />
          <Line type="linear" dataKey="reference" name="Опорная прямая" stroke="#dc2626" dot={false} isAnimationActive={false} />
          <Scatter dataKey="observed" name="Квантили" fill="#2563eb" isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function CdfView({ profile }: { profile: EdaDistributionResponse }) {
  return (
    <div role="img" aria-label={`Сравнение функций распределения для ${profile.column}`} className="min-h-0 flex-1 px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={profile.cdf} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10 }} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} width={48} />
          <Tooltip formatter={(value: number | string, name: string) => [typeof value === "number" ? formatNumber(value) : value, name === "empirical" ? "Эмпирическая F(x)" : "Нормальная F(x)"]} />
          <Line type="stepAfter" dataKey="empirical" name="Эмпирическая F(x)" stroke="#2563eb" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="normal" name="Нормальная F(x)" stroke="#dc2626" strokeDasharray="5 3" dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function TestsView({ profile }: { profile: EdaDistributionResponse }) {
  return (
    <div className="shrink-0 overflow-x-auto">
      <table aria-label="Тесты нормальности" className="w-full min-w-[790px] text-left text-xs">
        <thead className="sticky top-0 bg-neutral-50 text-neutral-500"><tr>
          <th className="px-2 py-2">Тест</th><th className="px-2 py-2 text-right">Статистика</th><th className="px-2 py-2 text-right">p</th><th className="px-2 py-2 text-right">p после Холма</th><th className="px-2 py-2">Калибровка</th><th className="px-2 py-2">Решение при α={profile.alpha}</th>
        </tr></thead>
        <tbody>{profile.tests.map((item) => <tr key={item.id} className="border-t border-neutral-100 text-neutral-700">
          <td className="px-2 py-2 font-medium">{item.label}{item.note ? <span className="mt-0.5 block max-w-[270px] font-normal text-neutral-500">{item.note}</span> : null}</td>
          <td className="px-2 py-2 text-right tabular-nums">{formatNumber(item.statistic)}</td>
          <td className="px-2 py-2 text-right tabular-nums">{formatNumber(item.p_value)}</td>
          <td className="px-2 py-2 text-right tabular-nums">{formatNumber(item.adjusted_p_value)}</td>
          <td className="px-2 py-2">{item.calibration ? CALIBRATION_LABELS[item.calibration] : "—"}</td>
          <td className={`px-2 py-2 font-medium ${item.reject_normality === true ? "text-red-700" : item.reject_normality === false ? "text-green-700" : "text-neutral-500"}`}>{!item.available ? "неприменим" : item.reject_normality ? "нормальная форма отвергается" : "нет оснований отвергнуть"}</td>
        </tr>)}</tbody>
      </table>
    </div>
  );
}

export function EdaDistributionOverview(props: EdaDistributionOverviewProps) {
  return (
    <ExpandableChartsProvider>
      <EdaDistributionOverviewInner {...props} />
    </ExpandableChartsProvider>
  );
}

function EdaDistributionOverviewInner({ profile, loading, error, noDataset, parameters, onParametersChange }: EdaDistributionOverviewProps) {
  const [activeView, setActiveView] = useState<DistributionView>("histogram");
  const { expandedChartId } = useExpandableChartState();

  if (loading) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Оцениваем форму распределения и выполняем тесты…</div>;
  if (error) return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Загрузите датасет, чтобы исследовать распределение.</div>;
  if (!profile) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Анализ распределения неприменим."}</div>;

  return (
    <section className={`relative flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white feed-scroll ${expandedChartId ? "overflow-hidden" : "overflow-y-auto"}`}>
      <div className="shrink-0 border-b border-neutral-100 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2"><h4 className="text-sm font-semibold text-neutral-800">Распределение «{profile.column}»</h4><span className={`rounded px-2 py-0.5 text-[10px] font-medium ${profile.normality_status === "compatible" ? "bg-green-50 text-green-700" : profile.normality_status === "departed" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700"}`}>{STATUS_LABELS[profile.normality_status]}</span></div>
            <p className="mt-1 text-xs text-neutral-500">{profile.shape_label} · n={profile.n_observations} · уникальных значений {profile.unique_count} · асимметрия {formatNumber(profile.skewness)} · эксцесс {formatNumber(profile.excess_kurtosis)}</p>
          </div>
          <div className="flex shrink-0 gap-2">
            <ParameterSelect label="Уровень значимости α" value={parameters.alpha} options={[0.01, 0.05, 0.1]} onChange={(value) => onParametersChange({ alpha: value })} />
            <ParameterSelect label="Число интервалов" value={parameters.bins} options={[10, 20, 30, 50]} onChange={(value) => onParametersChange({ bins: value })} />
          </div>
        </div>
        {profile.recommendation && <p className="mt-3 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p>}
        {profile.warnings.length > 0 && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.warnings.join(" ")}</p>}
      </div>
      <div role="tablist" aria-label="Представления распределения" className="flex shrink-0 flex-wrap gap-1 border-b border-neutral-100 px-4 pt-3">
        {TABS.map((tab) => <button key={tab.id} role="tab" aria-selected={activeView === tab.id} onClick={() => setActiveView(tab.id)} className={`rounded-t px-3 py-2 text-xs font-medium ${activeView === tab.id ? "bg-brand text-white" : "bg-neutral-50 text-neutral-600 hover:bg-neutral-100"}`}>{tab.label}</button>)}
      </div>
      {activeView === "histogram" ? <ExpandableChartPanel chartId="distribution-histogram" title="Гистограмма распределения"><HistogramView profile={profile} /></ExpandableChartPanel> : null}
      {activeView === "density" ? <ExpandableChartPanel chartId="distribution-density" title="Плотность: KDE и нормальная"><DensityView profile={profile} /></ExpandableChartPanel> : null}
      {activeView === "qq" ? <ExpandableChartPanel chartId="distribution-qq" title="Q–Q график"><QqView profile={profile} /></ExpandableChartPanel> : null}
      {activeView === "cdf" ? <ExpandableChartPanel chartId="distribution-cdf" title="Функции распределения"><CdfView profile={profile} /></ExpandableChartPanel> : null}
      {activeView === "tests" ? <TestsView profile={profile} /> : null}
    </section>
  );
}
