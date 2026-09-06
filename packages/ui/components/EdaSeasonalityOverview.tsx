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
// Task 97.4 (Этап 4, spec_max_graf_fix.md §8): тиражирование раскрытия
// графиков. Корень Обзора: relative всегда (правка A), overflow переключается
// по expandedChartId (правка C); спектральные графики обёрнуты в
// ExpandableChartPanel (уровень ИСПОЛЬЗОВАНИЯ, §7.2), таблица кандидатов —
// без панели. Панель фазы — только при наличии данных (прецедент Этапа 2).
// detail_level не заказан (Этап 5 опционален) — раскрытие чисто визуальное.
import { ExpandableChartPanel } from "./ExpandableChartPanel";
import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import { useExpandableChartState } from "../hooks/useExpandableChart";


export interface EdaSpectrumPoint {
  frequency: number;
  period: number;
  amplitude: number | null;
  power: number | null;
  is_peak: boolean;
}

export interface EdaSeasonalityCandidate {
  rank: number;
  period: number;
  period_rounded: number;
  frequency: number;
  amplitude: number;
  power: number;
  power_share: number;
  prominence: number;
  spectral_snr: number;
  autocorrelation: number;
  seasonal_strength: number;
  cycles: number;
  confirmed: boolean;
  calendar_hint: string | null;
  harmonic_of: number | null;
}

export interface EdaSeasonalityPhasePoint {
  phase: number;
  mean: number;
  lower: number;
  upper: number;
  count: number;
}

export interface EdaSeasonalityResponse {
  column: string;
  applicable: boolean;
  reason: string | null;
  n_observations: number;
  missing_count: number;
  min_cycles: number;
  max_candidates: number;
  max_period: number | null;
  detrend: "linear";
  window: "hann";
  order_source: "time_column" | "row_order";
  order_column: string | null;
  order_warning: string | null;
  frequency: string | null;
  spectral_entropy: number | null;
  dominant_period: number | null;
  dominant_strength: number | null;
  confirmed_periods: number;
  fft: EdaSpectrumPoint[];
  periodogram: EdaSpectrumPoint[];
  candidates: EdaSeasonalityCandidate[];
  phase_period: number | null;
  phase_profile: EdaSeasonalityPhasePoint[];
  recommendations: string[];
}

export interface EdaSeasonalityParameters {
  minCycles: number;
  maxCandidates: number;
}

interface EdaSeasonalityOverviewProps {
  profile: EdaSeasonalityResponse | null;
  loading: boolean;
  error: string | null;
  noDataset: boolean;
  parameters: EdaSeasonalityParameters;
  onParametersChange: (changes: Partial<EdaSeasonalityParameters>) => void;
}

type SeasonalityView = "fft" | "periodogram" | "phase" | "candidates";

const TABS: { id: SeasonalityView; label: string }[] = [
  { id: "fft", label: "FFT" },
  { id: "periodogram", label: "Периодограмма" },
  { id: "phase", label: "Фазовый профиль" },
  { id: "candidates", label: "Кандидаты" },
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

function SpectrumChart({
  profile,
  kind,
}: {
  profile: EdaSeasonalityResponse;
  kind: "fft" | "periodogram";
}) {
  const points = kind === "fft" ? profile.fft : profile.periodogram;
  const dataKey = kind === "fft" ? "amplitude" : "power";
  const peaks = points.filter((point) => point.is_peak);
  const label = kind === "fft" ? "FFT-спектр" : "Периодограмма";
  return (
    <div role="img" aria-label={`${label} для ${profile.column}`} className="min-h-0 flex-1 px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis
            dataKey="frequency"
            type="number"
            domain={[0, "dataMax"]}
            tick={{ fontSize: 10 }}
            label={{ value: "Частота, циклов/наблюдение", position: "insideBottomRight", offset: -5, fontSize: 10 }}
          />
          <YAxis tick={{ fontSize: 10 }} width={52} />
          <Tooltip
            formatter={(value: number | string, name: string) => [
              typeof value === "number" ? value.toPrecision(4) : value,
              name === dataKey ? (kind === "fft" ? "Амплитуда" : "Мощность") : name,
            ]}
            labelFormatter={(_, payload) => {
              const point = payload?.[0]?.payload as EdaSpectrumPoint | undefined;
              return point ? `Период ≈ ${formatValue(point.period)} наблюдения` : "";
            }}
          />
          <Line type="monotone" dataKey={dataKey} stroke="#2563eb" dot={false} isAnimationActive={false} />
          <Scatter data={peaks} dataKey={dataKey} fill="#dc2626" isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function PhaseChart({ profile }: { profile: EdaSeasonalityResponse }) {
  if (!profile.phase_profile.length || profile.phase_period === null) {
    return <p role="status" className="flex min-h-0 flex-1 items-center justify-center p-8 text-center text-sm text-neutral-500">Нет периода-кандидата для фазового профиля.</p>;
  }
  return (
    <div role="img" aria-label={`Фазовый профиль периода ${profile.phase_period} для ${profile.column}`} className="min-h-0 flex-1 px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={profile.phase_profile} margin={{ top: 8, right: 18, left: 4, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis dataKey="phase" type="number" domain={[1, profile.phase_period]} tick={{ fontSize: 10 }} label={{ value: "Фаза", position: "insideBottomRight", offset: -5, fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} width={52} />
          <Tooltip formatter={(value: number | string) => typeof value === "number" ? value.toFixed(4) : value} />
          <ReferenceLine y={0} stroke="#a3a3a3" />
          <Line type="monotone" dataKey="upper" name="Верхняя 95% граница" stroke="#a3a3a3" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="lower" name="Нижняя 95% граница" stroke="#a3a3a3" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="mean" name="Среднее по фазе" stroke="#16a34a" strokeWidth={2} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function CandidatesTable({ candidates }: { candidates: EdaSeasonalityCandidate[] }) {
  if (!candidates.length) {
    return <p role="status" className="flex min-h-0 flex-1 items-center justify-center p-8 text-center text-sm text-neutral-500">Локальные спектральные пики не обнаружены.</p>;
  }
  return (
    <div className="shrink-0 overflow-x-auto">
      <table aria-label="Периоды-кандидаты" className="w-full min-w-[880px] text-left text-xs">
        <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
          <tr>
            <th className="px-2 py-2">#</th><th className="px-2 py-2 text-right">Период</th><th className="px-2 py-2">Интерпретация</th>
            <th className="px-2 py-2 text-right">Циклов</th><th className="px-2 py-2 text-right">Энергия</th><th className="px-2 py-2 text-right">SNR</th>
            <th className="px-2 py-2 text-right">ACF</th><th className="px-2 py-2 text-right">Сила</th><th className="px-2 py-2">Статус</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((item) => (
            <tr key={`${item.rank}-${item.period}`} className="border-t border-neutral-100 text-neutral-700">
              <td className="px-2 py-2">{item.rank}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatValue(item.period)}</td>
              <td className="px-2 py-2">{item.calendar_hint ?? (item.harmonic_of ? `гармоника периода ${formatValue(item.harmonic_of)}` : "—")}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatValue(item.cycles, 1)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatValue(item.power_share, 1)}%</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatValue(item.spectral_snr, 1)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatValue(item.autocorrelation)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatValue(item.seasonal_strength)}</td>
              <td className={`px-2 py-2 font-medium ${item.confirmed ? "text-green-700" : "text-neutral-500"}`}>{item.confirmed ? "подтверждён" : "кандидат"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EdaSeasonalityOverview(props: EdaSeasonalityOverviewProps) {
  return (
    <ExpandableChartsProvider>
      <EdaSeasonalityOverviewInner {...props} />
    </ExpandableChartsProvider>
  );
}

function EdaSeasonalityOverviewInner({
  profile,
  loading,
  error,
  noDataset,
  parameters,
  onParametersChange,
}: EdaSeasonalityOverviewProps) {
  const [activeView, setActiveView] = useState<SeasonalityView>("fft");
  const { expandedChartId } = useExpandableChartState();

  if (loading) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Строим спектральный и фазовый профиль…</div>;
  if (error) return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (noDataset) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Загрузите датасет, чтобы исследовать сезонность.</div>;
  if (!profile) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">Выберите числовой исследуемый признак.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason ?? "Спектральный анализ неприменим."}</div>;

  return (
    <section className={`relative flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white feed-scroll ${expandedChartId ? "overflow-hidden" : "overflow-y-auto"}`}>
      <div className="shrink-0 border-b border-neutral-100 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-sm font-semibold text-neutral-800">Периодическая структура «{profile.column}»</h4>
            <p className="mt-1 text-xs text-neutral-500">
              {profile.order_column ? `Порядок: ${profile.order_column} по возрастанию` : "Порядок: последовательность строк"}
              {profile.frequency ? ` · частота ${profile.frequency}` : ""}{` · n=${profile.n_observations} · detrend linear · Hann`}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <ParameterSelect label="Минимум полных циклов" value={parameters.minCycles} options={[2, 3, 4, 5]} onChange={(value) => onParametersChange({ minCycles: value })} />
            <ParameterSelect label="Число кандидатов" value={parameters.maxCandidates} options={[3, 5, 8, 10]} onChange={(value) => onParametersChange({ maxCandidates: value })} />
          </div>
        </div>
        {profile.order_warning && <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.order_warning}</p>}
        {profile.recommendations[0] && <p className="mt-2 text-xs text-neutral-600">{profile.recommendations[0]}</p>}
      </div>

      <div className="flex shrink-0 gap-1 border-b border-neutral-100 px-4 pt-2" role="tablist" aria-label="Представления сезонности и периодичности">
        {TABS.map((tab) => (
          <button key={tab.id} type="button" role="tab" aria-selected={activeView === tab.id} onClick={() => setActiveView(tab.id)} className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${activeView === tab.id ? "border border-b-0 border-neutral-200 bg-white text-brand" : "text-neutral-500 hover:text-neutral-700"}`}>
            {tab.label}
          </button>
        ))}
      </div>

      {activeView === "fft" && <ExpandableChartPanel chartId="seasonality-fft" title="FFT-спектр"><SpectrumChart profile={profile} kind="fft" /></ExpandableChartPanel>}
      {activeView === "periodogram" && <ExpandableChartPanel chartId="seasonality-periodogram" title="Периодограмма"><SpectrumChart profile={profile} kind="periodogram" /></ExpandableChartPanel>}
      {/* Панель фазы — только при наличии данных, иначе бейдж раскрытия на пустом status-сообщении */}
      {activeView === "phase" && (profile.phase_profile.length > 0 && profile.phase_period !== null ? <ExpandableChartPanel chartId="seasonality-phase" title="Фазовый профиль"><PhaseChart profile={profile} /></ExpandableChartPanel> : <PhaseChart profile={profile} />)}
      {activeView === "candidates" && <CandidatesTable candidates={profile.candidates} />}
    </section>
  );
}
