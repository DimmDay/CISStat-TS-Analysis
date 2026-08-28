"use client";

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";


export interface EdaIhFeature {
  feature: string;
  kind: "numeric" | "categorical" | "lag";
  dtype: string;
  n_observations: number;
  r: number;
  r_adjusted: number;
  mi: number;
  h_x: number;
  h_y: number;
  n_bins_x: number;
  n_bins_y: number;
  permutation_baseline: number;
  p_value: number;
  q_value: number;
  significant: boolean;
  error: string | null;
}

export interface EdaIhSynergy {
  pair: string;
  feature_1: string;
  feature_2: string;
  r_1: number;
  r_2: number;
  r_combined: number;
  incremental_gain: number;
  interaction_delta: number;
}

export interface EdaIhConditionalRow {
  x_bin: string;
  values: number[];
}

export interface EdaIhResponse {
  column: string;
  applicable: boolean;
  reason: string | null;
  n_observations: number;
  features_analyzed: number;
  sharpness: number;
  min_samples: number;
  top_k: number;
  max_lag: number;
  permutations: number;
  target_entropy: number | null;
  target_bins: number;
  order_source: "time_column" | "row_order";
  order_column: string | null;
  order_warning: string | null;
  frequency: string | null;
  lag_features_included: boolean;
  results: EdaIhFeature[];
  synergies: EdaIhSynergy[];
  conditional_feature: string | null;
  conditional_x_bins: string[];
  conditional_y_bins: string[];
  conditional_matrix: EdaIhConditionalRow[];
  recommendations: string[];
}

export interface EdaIhParameters {
  sharpness: number;
  minSamples: number;
  topK: number;
  maxLag: number;
}

interface EdaIhOverviewProps {
  profile: EdaIhResponse | null;
  loading: boolean;
  error: string | null;
  noDataset: boolean;
  parameters: EdaIhParameters;
  onParametersChange: (changes: Partial<EdaIhParameters>) => void;
}

type IhView = "ranking" | "metrics" | "synergy" | "conditional" | "table";

const TABS: { id: IhView; label: string }[] = [
  { id: "ranking", label: "Рейтинг" },
  { id: "metrics", label: "Карта метрик" },
  { id: "synergy", label: "Синергия" },
  { id: "conditional", label: "Условная карта" },
  { id: "table", label: "Таблица" },
];

function formatValue(value: number | null, digits = 3): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("ru-RU", { maximumFractionDigits: digits });
}

function ParameterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: number;
  options: number[];
  onChange: (value: number) => void;
}) {
  return (
    <label className="text-[10px] text-neutral-500">
      <span className="block">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-0.5 rounded border border-neutral-300 bg-white px-1.5 py-1 text-xs text-neutral-700"
      >
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function RankingChart({ profile }: { profile: EdaIhResponse }) {
  const data = [...profile.results].reverse();
  return (
    <div role="img" aria-label={`Рейтинг IH-информативности для ${profile.column}`} className="h-[270px] px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 22, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis type="number" domain={[0, 1]} tick={{ fontSize: 10 }} />
          <YAxis dataKey="feature" type="category" width={105} tick={{ fontSize: 10 }} />
          <Tooltip formatter={(value: number | string) => typeof value === "number" ? value.toFixed(4) : value} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="r" name="R(Y|X)" fill="#60a5fa" isAnimationActive={false} />
          <Bar dataKey="r_adjusted" name="R после baseline" fill="#2563eb" isAnimationActive={false}>
            {data.map((item) => <Cell key={item.feature} fill={item.significant ? "#16a34a" : "#2563eb"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function MetricsMap({ results }: { results: EdaIhFeature[] }) {
  const maxima = useMemo(() => ({
    h_x: Math.max(...results.map((item) => item.h_x), 1e-9),
    mi: Math.max(...results.map((item) => item.mi), 1e-9),
    r: 1,
  }), [results]);
  const cellStyle = (value: number, max: number) => ({
    backgroundColor: `rgba(37, 99, 235, ${0.08 + 0.62 * Math.min(1, value / max)})`,
  });
  return (
    <div className="overflow-x-auto p-3">
      <table aria-label="Карта энтропийных метрик" className="w-full text-left text-xs">
        <thead className="text-neutral-500">
          <tr><th className="px-2 py-2">Фактор</th><th className="px-2 py-2">H(X)</th><th className="px-2 py-2">I(X;Y)</th><th className="px-2 py-2">R(Y|X)</th><th className="px-2 py-2">R adj.</th></tr>
        </thead>
        <tbody>
          {results.map((item) => (
            <tr key={item.feature} className="border-t border-neutral-100 text-neutral-700">
              <td className="px-2 py-2 font-medium">{item.feature}</td>
              <td className="px-2 py-2 tabular-nums" style={cellStyle(item.h_x, maxima.h_x)}>{formatValue(item.h_x)}</td>
              <td className="px-2 py-2 tabular-nums" style={cellStyle(item.mi, maxima.mi)}>{formatValue(item.mi)}</td>
              <td className="px-2 py-2 tabular-nums" style={cellStyle(item.r, maxima.r)}>{formatValue(item.r)}</td>
              <td className="px-2 py-2 tabular-nums" style={cellStyle(item.r_adjusted, maxima.r)}>{formatValue(item.r_adjusted)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SynergyChart({ items }: { items: EdaIhSynergy[] }) {
  if (!items.length) {
    return <p role="status" className="p-8 text-center text-sm text-neutral-500">Для парного анализа нужны минимум два обычных фактора, не считая лагов.</p>;
  }
  const data = [...items].slice(0, 8).reverse();
  return (
    <div role="img" aria-label="График взаимодействия факторов" className="h-[270px] px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 18, left: 55, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis type="number" tick={{ fontSize: 10 }} />
          <YAxis dataKey="pair" type="category" width={125} tick={{ fontSize: 9 }} />
          <ReferenceLine x={0} stroke="#737373" />
          <Tooltip formatter={(value: number | string) => typeof value === "number" ? value.toFixed(4) : value} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="incremental_gain" name="Добавка к лучшему фактору" fill="#2563eb" isAnimationActive={false} />
          <Bar dataKey="interaction_delta" name="Interaction ΔR" fill="#f59e0b" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ConditionalMap({ profile }: { profile: EdaIhResponse }) {
  if (!profile.conditional_matrix.length) {
    return <p role="status" className="p-8 text-center text-sm text-neutral-500">Условное распределение недоступно.</p>;
  }
  return (
    <div className="overflow-auto p-3">
      <p className="mb-2 text-xs text-neutral-500">
        Строки — интервалы «{profile.conditional_feature}», столбцы — интервалы «{profile.column}»; каждая строка суммируется до 100%.
      </p>
      <table aria-label="Условное распределение цели по интервалам фактора" className="min-w-full text-center text-xs">
        <thead className="text-neutral-500">
          <tr>
            <th className="px-2 py-2 text-left">X \ Y</th>
            {profile.conditional_y_bins.map((bin) => <th key={bin} className="px-2 py-2">{bin}</th>)}
          </tr>
        </thead>
        <tbody>
          {profile.conditional_matrix.map((row) => (
            <tr key={row.x_bin} className="border-t border-neutral-100">
              <th className="px-2 py-2 text-left font-medium text-neutral-700">{row.x_bin}</th>
              {row.values.map((value, index) => (
                <td
                  key={`${row.x_bin}-${profile.conditional_y_bins[index]}`}
                  className="px-2 py-2 tabular-nums text-neutral-800"
                  style={{ backgroundColor: `rgba(37, 99, 235, ${0.05 + 0.75 * value / 100})` }}
                >
                  {formatValue(value, 1)}%
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultsTable({ results }: { results: EdaIhFeature[] }) {
  return (
    <div className="overflow-x-auto">
      <table aria-label="Результаты IH-анализа" className="w-full min-w-[940px] text-left text-xs">
        <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
          <tr>
            <th className="px-2 py-2">Фактор</th><th className="px-2 py-2">Тип</th><th className="px-2 py-2 text-right">N</th>
            <th className="px-2 py-2 text-right">R</th><th className="px-2 py-2 text-right">R adj.</th><th className="px-2 py-2 text-right">MI</th>
            <th className="px-2 py-2 text-right">H(X)</th><th className="px-2 py-2 text-right">Бины</th><th className="px-2 py-2 text-right">p</th><th className="px-2 py-2 text-right">q (FDR)</th>
          </tr>
        </thead>
        <tbody>
          {results.map((item) => (
            <tr key={item.feature} className="border-t border-neutral-100 text-neutral-700">
              <td className="px-2 py-2 font-medium">{item.feature}</td><td className="px-2 py-2">{item.kind}</td><td className="px-2 py-2 text-right">{item.n_observations}</td>
              <td className="px-2 py-2 text-right">{formatValue(item.r)}</td><td className="px-2 py-2 text-right">{formatValue(item.r_adjusted)}</td><td className="px-2 py-2 text-right">{formatValue(item.mi)}</td>
              <td className="px-2 py-2 text-right">{formatValue(item.h_x)}</td><td className="px-2 py-2 text-right">{item.n_bins_x}</td><td className="px-2 py-2 text-right">{formatValue(item.p_value)}</td>
              <td className={`px-2 py-2 text-right ${item.significant ? "font-semibold text-green-700" : ""}`}>{formatValue(item.q_value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EdaIhOverview({
  profile,
  loading,
  error,
  noDataset,
  parameters,
  onParametersChange,
}: EdaIhOverviewProps) {
  const [activeView, setActiveView] = useState<IhView>("ranking");

  if (loading) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Вычисляем IH-профиль и перестановочный baseline…</div>;
  if (error) return <div role="alert" className="flex h-[420px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Загрузите датасет, чтобы выполнить IH-анализ.</div>;
  if (!profile) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "IH-анализ неприменим."}</div>;

  return (
    <section className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
      <div className="border-b border-neutral-100 p-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-neutral-800">IH-профиль факторов для «{profile.column}»</h4>
            <p className="mt-1 text-xs text-neutral-500">
              H(Y)={formatValue(profile.target_entropy)} бит · исследовано {profile.features_analyzed} факторов · {profile.permutations} перестановок
            </p>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <ParameterSelect label="Резкость дискретизации" value={parameters.sharpness} options={[0.1, 0.2, 0.25, 0.5]} onChange={(sharpness) => onParametersChange({ sharpness })} />
            <ParameterSelect label="Мин. на интервал" value={parameters.minSamples} options={[5, 10, 20, 50]} onChange={(minSamples) => onParametersChange({ minSamples })} />
            <ParameterSelect label="Топ факторов" value={parameters.topK} options={[5, 10, 15, 20]} onChange={(topK) => onParametersChange({ topK })} />
            <ParameterSelect label="Лагов цели" value={parameters.maxLag} options={[0, 1, 3, 5, 10]} onChange={(maxLag) => onParametersChange({ maxLag })} />
          </div>
        </div>
        {profile.order_warning && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.order_warning}</p>}
        {profile.recommendations[0] && <p className="mt-2 rounded bg-brand-light/60 px-3 py-2 text-xs text-neutral-700">{profile.recommendations[0]}</p>}
      </div>

      <div className="flex gap-1 overflow-x-auto border-b border-neutral-100 px-3 pt-2" role="tablist" aria-label="Представления IH-анализа">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeView === tab.id}
            onClick={() => setActiveView(tab.id)}
            className={`whitespace-nowrap rounded-t px-2.5 py-1.5 text-xs font-medium transition-colors ${activeView === tab.id ? "border border-b-0 border-neutral-200 bg-white text-brand" : "text-neutral-500 hover:text-neutral-700"}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeView === "ranking" && <RankingChart profile={profile} />}
      {activeView === "metrics" && <MetricsMap results={profile.results} />}
      {activeView === "synergy" && <SynergyChart items={profile.synergies} />}
      {activeView === "conditional" && <ConditionalMap profile={profile} />}
      {activeView === "table" && <ResultsTable results={profile.results} />}
    </section>
  );
}
