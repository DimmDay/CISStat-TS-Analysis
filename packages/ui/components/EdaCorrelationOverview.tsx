"use client";

import { useState } from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";


export interface EdaCorrelationPoint {
  lag: number;
  value: number;
  confidence_lower: number;
  confidence_upper: number;
  significant: boolean;
}

export interface EdaCorrelationResponse {
  column: string;
  applicable: boolean;
  reason: string | null;
  n_observations: number;
  missing_count: number;
  requested_max_lags: number;
  max_lag: number;
  alpha: number;
  order_source: "time_column" | "row_order";
  order_column: string | null;
  order_warning: string | null;
  frequency: string | null;
  acf: EdaCorrelationPoint[];
  pacf: EdaCorrelationPoint[];
  significant_acf_lags: number[];
  significant_pacf_lags: number[];
  ljung_box_lag: number | null;
  ljung_box_pvalue: number | null;
  is_white_noise: boolean | null;
  suggested_p: number | null;
  suggested_q: number | null;
}

type CorrelationView = "acf" | "pacf" | "table";

interface EdaCorrelationOverviewProps {
  profile: EdaCorrelationResponse | null;
  loading: boolean;
  error: string | null;
  noDataset: boolean;
  maxLags: number;
  onMaxLagsChange: (value: number) => void;
}

const TABS: { id: CorrelationView; label: string }[] = [
  { id: "acf", label: "ACF" },
  { id: "pacf", label: "PACF" },
  { id: "table", label: "Таблица" },
];

const LAG_OPTIONS = [20, 40, 60, 100];

function formatValue(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 4 });
}

function CorrelationChart({
  kind,
  column,
  points,
}: {
  kind: "ACF" | "PACF";
  column: string;
  points: EdaCorrelationPoint[];
}) {
  return (
    <div role="img" aria-label={`График ${kind} для ${column}`} className="h-[275px] px-2 py-3">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis
            dataKey="lag"
            type="number"
            domain={[0, "dataMax"]}
            tick={{ fontSize: 11 }}
            label={{ value: "Лаг", position: "insideBottomRight", offset: -2, fontSize: 11 }}
          />
          <YAxis domain={[-1, 1]} tick={{ fontSize: 11 }} width={42} />
          <Tooltip
            formatter={(value: number | string, name: string) => [
              typeof value === "number" ? value.toFixed(4) : value,
              name === "value" ? kind : name === "confidence_upper" ? "Верхняя 95% граница" : "Нижняя 95% граница",
            ]}
            labelFormatter={(lag) => `Лаг ${lag}`}
          />
          <ReferenceLine y={0} stroke="#737373" />
          <Line
            type="monotone"
            dataKey="confidence_upper"
            stroke="#a3a3a3"
            strokeDasharray="5 4"
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="confidence_lower"
            stroke="#a3a3a3"
            strokeDasharray="5 4"
            dot={false}
            isAnimationActive={false}
          />
          <Bar dataKey="value" barSize={4} isAnimationActive={false}>
            {points.map((point) => (
              <Cell key={point.lag} fill={point.significant ? "#dc2626" : "#2563eb"} />
            ))}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function EdaCorrelationOverview({
  profile,
  loading,
  error,
  noDataset,
  maxLags,
  onMaxLagsChange,
}: EdaCorrelationOverviewProps) {
  const [activeView, setActiveView] = useState<CorrelationView>("acf");

  if (loading) {
    return (
      <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">
        Рассчитываем ACF/PACF по полному ряду…
      </div>
    );
  }
  if (error) {
    return (
      <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">
        {error}
      </div>
    );
  }
  if (noDataset) {
    return (
      <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">
        Загрузите датасет, чтобы исследовать корреляционную структуру ряда.
      </div>
    );
  }
  if (!profile) {
    return (
      <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">
        Выберите числовой исследуемый признак.
      </div>
    );
  }
  if (!profile.applicable) {
    return (
      <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">
        {profile.reason ?? "ACF/PACF неприменимы к выбранному ряду."}
      </div>
    );
  }

  const pointsByLag = profile.acf.map((acfPoint, index) => ({
    lag: acfPoint.lag,
    acf: acfPoint,
    pacf: profile.pacf[index],
  }));

  return (
    <section className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
      <div className="border-b border-neutral-100 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-sm font-semibold text-neutral-800">Корреляционная структура «{profile.column}»</h4>
            <p className="mt-1 text-xs text-neutral-500">
              {profile.order_column
                ? `Порядок: ${profile.order_column} по возрастанию${profile.frequency ? ` · частота ${profile.frequency}` : ""}`
                : "Порядок: последовательность строк датасета"}
              {` · n=${profile.n_observations}`}
            </p>
          </div>
          <label className="shrink-0 text-xs text-neutral-500">
            Максимальный лаг
            <select
              aria-label="Максимальный лаг"
              value={maxLags}
              onChange={(event) => onMaxLagsChange(Number(event.target.value))}
              className="ml-2 rounded border border-neutral-300 bg-white px-2 py-1 text-xs text-neutral-700"
            >
              {LAG_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
        </div>
        {profile.order_warning && (
          <p className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">{profile.order_warning}</p>
        )}
        {profile.max_lag < profile.requested_max_lags && (
          <p className="mt-2 text-xs text-neutral-500">
            Показаны лаги 0–{profile.max_lag}: горизонт безопасно ограничен объёмом ряда для PACF.
          </p>
        )}
      </div>

      <div className="flex gap-1 border-b border-neutral-100 px-4 pt-2" role="tablist" aria-label="Представления корреляционной структуры">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeView === tab.id}
            onClick={() => setActiveView(tab.id)}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              activeView === tab.id
                ? "border border-b-0 border-neutral-200 bg-white text-brand"
                : "text-neutral-500 hover:text-neutral-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeView === "acf" && <CorrelationChart kind="ACF" column={profile.column} points={profile.acf} />}
      {activeView === "pacf" && <CorrelationChart kind="PACF" column={profile.column} points={profile.pacf} />}
      {activeView === "table" && (
        <div className="overflow-x-auto">
          <table aria-label="Значения ACF и PACF по лагам" className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
              <tr>
                <th className="px-3 py-2">Лаг</th>
                <th className="px-3 py-2 text-right">ACF</th>
                <th className="px-3 py-2">Статус ACF</th>
                <th className="px-3 py-2 text-right">PACF</th>
                <th className="px-3 py-2">Статус PACF</th>
              </tr>
            </thead>
            <tbody>
              {pointsByLag.map(({ lag, acf: acfPoint, pacf: pacfPoint }) => (
                <tr key={lag} className="border-t border-neutral-100 text-neutral-700">
                  <td className="px-3 py-2 tabular-nums">{lag}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatValue(acfPoint.value)}</td>
                  <td className="px-3 py-2">
                    <span className={acfPoint.significant ? "text-red-700" : "text-neutral-400"}>
                      {acfPoint.significant ? "Значимая" : "В границах"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatValue(pacfPoint?.value ?? null)}</td>
                  <td className="px-3 py-2">
                    <span className={pacfPoint?.significant ? "text-red-700" : "text-neutral-400"}>
                      {pacfPoint?.significant ? "Значимая" : "В границах"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
