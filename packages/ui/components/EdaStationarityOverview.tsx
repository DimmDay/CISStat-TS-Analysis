"use client";

import { useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";


export type StationarityConsensus =
  | "stationary"
  | "trend-stationary"
  | "non-stationary"
  | "inconclusive";

export interface EdaStationarityTest {
  id: "adf_level" | "adf_trend" | "kpss_level" | "kpss_trend" | "pp" | "zivot_andrews";
  label: string;
  null_hypothesis: string;
  alternative_hypothesis: string;
  available: boolean;
  statistic: number | null;
  p_value: number | null;
  lags: number | null;
  reject_null: boolean | null;
  supports_stationarity: boolean | null;
  critical_values: Record<string, number>;
  note: string | null;
}

export interface EdaStationarityRollingPoint {
  index: number;
  label: string | null;
  value: number;
  rolling_mean: number | null;
  rolling_std: number | null;
}

export interface EdaStationarityResponse {
  column: string;
  applicable: boolean;
  reason: string | null;
  n_observations: number;
  missing_count: number;
  min_observations: number;
  alpha: number;
  requested_rolling_window: number;
  rolling_window: number;
  consensus: StationarityConsensus | null;
  recommendation: string | null;
  order_source: "time_column" | "row_order";
  order_column: string | null;
  order_warning: string | null;
  frequency: string | null;
  breakpoint_index: number | null;
  breakpoint_label: string | null;
  tests: EdaStationarityTest[];
  rolling: EdaStationarityRollingPoint[];
  rolling_sampled: boolean;
  rolling_original_count: number;
  recommendations: string[];
  warnings: string[];
}

export interface EdaStationarityParameters {
  alpha: number;
  rollingWindow: number;
}

interface EdaStationarityOverviewProps {
  profile: EdaStationarityResponse | null;
  loading: boolean;
  error: string | null;
  noDataset: boolean;
  parameters: EdaStationarityParameters;
  onParametersChange: (changes: Partial<EdaStationarityParameters>) => void;
}

type StationarityView = "series" | "rolling_std" | "pvalues" | "tests";

const TABS: { id: StationarityView; label: string }[] = [
  { id: "series", label: "Ряд и μ" },
  { id: "rolling_std", label: "Скользящее σ" },
  { id: "pvalues", label: "p-значения" },
  { id: "tests", label: "Таблица" },
];

const CONSENSUS_LABELS: Record<StationarityConsensus, string> = {
  stationary: "Стационарен",
  "trend-stationary": "Стационарен вокруг тренда",
  "non-stationary": "Нестационарен",
  inconclusive: "Неопределённо",
};

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("ru-RU", { maximumFractionDigits: digits });
}

function formatTickLabel(point: EdaStationarityRollingPoint): string {
  if (!point.label) return String(point.index);
  const date = new Date(point.label);
  return Number.isNaN(date.getTime()) ? point.label : date.toLocaleDateString("ru-RU");
}

function localizeKpssDiagnostic(note: string | null, pValue?: number | null): string | null {
  if (!note) return null;
  const normalized = note.toLowerCase();
  if (normalized.includes("actual p-value is smaller") || pValue !== null && pValue !== undefined && pValue <= 0.01) {
    return "Расчётное p-значение ниже нижней границы табличного диапазона 0,01; показано граничное значение 0,01.";
  }
  if (normalized.includes("actual p-value is greater") || pValue !== null && pValue !== undefined && pValue >= 0.10) {
    return "Расчётное p-значение выше верхней границы табличного диапазона 0,10; показано граничное значение 0,10.";
  }
  if (normalized.includes("kpss currently returns a plain tuple")) return null;
  if (normalized.includes("p-value ограничен таблицей")) {
    return "p-значение ограничено табличным диапазоном метода KPSS.";
  }
  return note;
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
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}

function SeriesChart({ profile }: { profile: EdaStationarityResponse }) {
  return (
    <div role="img" aria-label={`Ряд и скользящее среднее для ${profile.column}`} className="h-[265px] px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={profile.rolling} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis dataKey="index" tick={{ fontSize: 10 }} tickFormatter={(index) => {
            const point = profile.rolling.find((item) => item.index === index);
            return point ? formatTickLabel(point) : String(index);
          }} />
          <YAxis tick={{ fontSize: 10 }} width={58} />
          <Tooltip
            labelFormatter={(index) => {
              const point = profile.rolling.find((item) => item.index === Number(index));
              return point ? formatTickLabel(point) : `Наблюдение ${index}`;
            }}
            formatter={(value: number | string, name: string) => [
              typeof value === "number" ? formatNumber(value) : value,
              name === "value" ? profile.column : "Скользящее μ",
            ]}
          />
          {profile.breakpoint_index !== null && (
            <ReferenceLine x={profile.breakpoint_index} stroke="#dc2626" strokeDasharray="4 3" label={{ value: "ZA-разрыв", fontSize: 9, fill: "#dc2626" }} />
          )}
          <Line type="monotone" dataKey="value" stroke="#94a3b8" dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="rolling_mean" stroke="#2563eb" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function RollingStdChart({ profile }: { profile: EdaStationarityResponse }) {
  return (
    <div role="img" aria-label={`Скользящее стандартное отклонение для ${profile.column}`} className="h-[265px] px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={profile.rolling} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis dataKey="index" tick={{ fontSize: 10 }} tickFormatter={(index) => {
            const point = profile.rolling.find((item) => item.index === index);
            return point ? formatTickLabel(point) : String(index);
          }} />
          <YAxis tick={{ fontSize: 10 }} width={58} domain={[0, "auto"]} />
          <Tooltip formatter={(value: number | string) => typeof value === "number" ? formatNumber(value) : value} />
          {profile.breakpoint_index !== null && <ReferenceLine x={profile.breakpoint_index} stroke="#dc2626" strokeDasharray="4 3" />}
          <Line type="monotone" dataKey="rolling_std" name="Скользящее σ" stroke="#7c3aed" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function PValueChart({ profile }: { profile: EdaStationarityResponse }) {
  const data = profile.tests
    .filter((item) => item.available && item.p_value !== null)
    .map((item) => ({
      label: item.label.replace("Phillips–Perron", "PP").replace("Zivot–Andrews", "ZA"),
      p_value: item.p_value,
      supports_stationarity: item.supports_stationarity,
    }));
  return (
    <div role="img" aria-label={`Сопоставление p-значений тестов стационарности для ${profile.column}`} className="h-[265px] px-2 py-2">
      <p className="px-2 text-[10px] text-neutral-500">Зелёный — вывод поддерживает стационарность. Для ADF/PP/ZA это p&lt;α, для KPSS — p≥α.</p>
      <div className="h-[238px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 18, left: 4, bottom: 22 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
            <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={0} angle={-12} textAnchor="end" height={48} />
            <YAxis tick={{ fontSize: 10 }} width={52} domain={[0, "auto"]} />
            <Tooltip formatter={(value: number | string) => typeof value === "number" ? formatNumber(value) : value} />
            <ReferenceLine y={profile.alpha} stroke="#dc2626" strokeDasharray="4 3" label={{ value: `α=${profile.alpha}`, fontSize: 9, fill: "#dc2626" }} />
            <Bar dataKey="p_value" name="p-значение" isAnimationActive={false}>
              {data.map((item) => <Cell key={item.label} fill={item.supports_stationarity ? "#16a34a" : "#d97706"} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function TestsTable({ profile }: { profile: EdaStationarityResponse }) {
  return (
    <div className="overflow-x-auto">
      <table aria-label="Результаты тестов стационарности" className="w-full min-w-[940px] text-left text-xs">
        <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
          <tr>
            <th className="px-2 py-2">Тест</th><th className="px-2 py-2">H₀</th>
            <th className="px-2 py-2 text-right">Статистика</th><th className="px-2 py-2 text-right">p-значение</th>
            <th className="px-2 py-2 text-right">Лаги</th><th className="px-2 py-2">Решение при α={profile.alpha}</th>
          </tr>
        </thead>
        <tbody>
          {profile.tests.map((item) => (
            <tr key={item.id} className="border-t border-neutral-100 text-neutral-700">
              <td className="px-2 py-2 font-medium">{item.label}</td>
              <td className="px-2 py-2">{item.null_hypothesis}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatNumber(item.statistic)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatNumber(item.p_value)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{item.lags ?? "—"}</td>
              <td className={`px-2 py-2 font-medium ${item.supports_stationarity === true ? "text-green-700" : item.supports_stationarity === false ? "text-amber-700" : "text-neutral-500"}`}>
                {!item.available ? "недоступен" : item.reject_null ? "H₀ отвергается" : "H₀ не отвергается"}
                {localizeKpssDiagnostic(item.note, item.p_value) ? <span className="mt-0.5 block font-normal text-neutral-500">{localizeKpssDiagnostic(item.note, item.p_value)}</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EdaStationarityOverview({
  profile,
  loading,
  error,
  noDataset,
  parameters,
  onParametersChange,
}: EdaStationarityOverviewProps) {
  const [activeView, setActiveView] = useState<StationarityView>("series");
  const localizedWarnings = profile?.warnings
    .map((warning) => localizeKpssDiagnostic(warning))
    .filter((warning): warning is string => Boolean(warning)) ?? [];

  if (loading) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Выполняем ADF/KPSS/PP и скользящие диагностики…</div>;
  if (error) return <div role="alert" className="flex h-[420px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Загрузите датасет, чтобы проверить стационарность.</div>;
  if (!profile) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Проверка стационарности неприменима."}</div>;

  return (
    <section className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
      <div className="border-b border-neutral-100 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-sm font-semibold text-neutral-800">Стационарность «{profile.column}»</h4>
              {profile.consensus && <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${profile.consensus === "stationary" ? "bg-green-50 text-green-700" : profile.consensus === "non-stationary" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700"}`}>{CONSENSUS_LABELS[profile.consensus]}</span>}
            </div>
            <p className="mt-1 text-xs text-neutral-500">
              {profile.order_column ? `Порядок: ${profile.order_column} по возрастанию` : "Порядок: последовательность строк"}
              {profile.frequency ? ` · частота ${profile.frequency}` : ""}{` · n=${profile.n_observations} · окно ${profile.rolling_window}`}
              {profile.rolling_sampled ? ` · график LTTB из ${profile.rolling_original_count}` : ""}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <ParameterSelect label="Уровень значимости α" value={parameters.alpha} options={[0.01, 0.05, 0.1]} onChange={(value) => onParametersChange({ alpha: value })} />
            <ParameterSelect label="Окно скользящих статистик" value={parameters.rollingWindow} options={[5, 10, 12, 20, 30]} onChange={(value) => onParametersChange({ rollingWindow: value })} />
          </div>
        </div>
        {profile.recommendation && <p className="mt-3 rounded bg-brand-light px-3 py-2 text-xs text-neutral-700">{profile.recommendation}</p>}
        {localizedWarnings.length > 0 && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{localizedWarnings.join(" ")}</p>}
      </div>

      <div role="tablist" aria-label="Представления стационарности" className="flex flex-wrap gap-1 border-b border-neutral-100 px-4 pt-3">
        {TABS.map((tab) => (
          <button key={tab.id} role="tab" aria-selected={activeView === tab.id} onClick={() => setActiveView(tab.id)} className={`rounded-t px-3 py-2 text-xs font-medium ${activeView === tab.id ? "bg-brand text-white" : "bg-neutral-50 text-neutral-600 hover:bg-neutral-100"}`}>{tab.label}</button>
        ))}
      </div>

      {activeView === "series" ? <SeriesChart profile={profile} /> : null}
      {activeView === "rolling_std" ? <RollingStdChart profile={profile} /> : null}
      {activeView === "pvalues" ? <PValueChart profile={profile} /> : null}
      {activeView === "tests" ? <TestsTable profile={profile} /> : null}
    </section>
  );
}
