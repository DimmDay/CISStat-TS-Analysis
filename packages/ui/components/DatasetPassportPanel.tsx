"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { sessionApiUrl } from "../lib/apiClient";
import { Button } from "./Button";
import { Metric } from "./Metric";

export type PassportStage = "start" | "validation" | "exit";

interface PassportPointStatus {
  captured: boolean;
  captured_at: string | null;
  is_stale: boolean | null;
  fingerprint: string | null;
  history_count: number;
}

interface DatasetPassportStatus {
  has_dataset: boolean;
  target_column: string | null;
  date_column: string | null;
  series_ready: boolean;
  reason: string | null;
  current_fingerprint: string | null;
  start: PassportPointStatus;
  validation: PassportPointStatus;
  exit: PassportPointStatus;
}

interface DateColumnResponse {
  date_column: string | null;
  suggested_column: string | null;
  candidates: Array<{ name: string; score: number }>;
  has_dataset: boolean;
  passport_history_reset: boolean;
}

type Passport = Record<string, unknown>;

interface PassportCaptureResponse {
  snapshot_id: string;
  stage: PassportStage;
  passport: Passport;
  fingerprint: string;
  target_column: string;
  date_column: string | null;
  captured_at: string;
}

interface NumericChange {
  v_old: number;
  v_new: number;
  delta: number;
  delta_pct: number;
}

interface NamedChange {
  v_old?: unknown;
  v_new?: unknown;
  changed?: boolean;
  added?: unknown[];
  removed?: unknown[];
}

interface PassportComparison {
  metrics: Record<string, NumericChange>;
  qualitative_changes: string[];
  categorical_changes: Record<string, NamedChange>;
  list_changes: Record<string, NamedChange>;
  boolean_changes: Record<string, NamedChange>;
  summary: string;
}

interface PassportComparisonPair {
  from_stage: PassportStage;
  to_stage: PassportStage;
  from_snapshot_id: string;
  to_snapshot_id: string;
  comparison: PassportComparison;
}

interface PassportCompareResponse {
  target_column: string;
  date_column: string | null;
  path: PassportStage[];
  comparisons: PassportComparisonPair[];
}

export interface DatasetPassportPanelProps {
  stage: PassportStage;
  targetColumn?: string | null;
  suggestedDateColumn?: string | null;
  historyResetNotice?: string | null;
}

const STAGE_TEXT: Record<PassportStage, { title: string; short: string; action: string }> = {
  start: {
    title: "Паспорт свойств ряда: Загрузка",
    short: "Загрузка",
    action: "Рассчитать паспорт на загрузке",
  },
  validation: {
    title: "Паспорт свойств ряда: Валидация",
    short: "Валидация",
    action: "Рассчитать паспорт после валидации",
  },
  exit: {
    title: "Паспорт свойств ряда: Предобработка",
    short: "Предобработка",
    action: "Рассчитать итоговый паспорт",
  },
};

function asSection(passport: Passport, key: string): Record<string, unknown> {
  const value = passport[key];
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatNumber(value: unknown, digits = 4): string {
  const numeric = asFiniteNumber(value);
  if (numeric === null) return "—";
  return numeric.toLocaleString("ru-RU", { maximumSignificantDigits: digits });
}

function formatList(value: unknown): string {
  if (!Array.isArray(value) || value.length === 0) return "—";
  return value.map((item) => formatNumber(item)).join("; ");
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральный fallback ниже покрывает ответы без JSON.
  }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

function PassportMetrics({ passport }: { passport: Passport }) {
  const basic = asSection(passport, "basic_stats");
  const freq = asSection(passport, "freq");
  const stationarity = asSection(passport, "stationarity");
  const determinism = asSection(passport, "determinism");
  const autocorrelation = asSection(passport, "autocorrelation");
  const normality = asSection(passport, "normality");
  const trend = asSection(passport, "trend");
  const seasonality = asSection(passport, "seasonality");
  const hurst = asSection(passport, "hurst");
  const correlations = asSection(passport, "correlations");
  const fft = asSection(passport, "fft");
  const top3 = correlations.top3 && typeof correlations.top3 === "object"
    ? Object.entries(correlations.top3 as Record<string, unknown>)
      .map(([name, value]) => `${name}: ${formatNumber(value, 3)}`)
      .join("; ")
    : "—";
  const direction = trend.direction === "up"
    ? "восходящий"
    : trend.direction === "down"
    ? "нисходящий"
    : trend.direction === "flat"
    ? "горизонтальный"
    : "—";

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6" data-testid="passport-metrics">
      <Metric label="Наблюдений" value={formatNumber(basic.n, 8)} />
      <Metric label="Частота" value={typeof freq.value === "string" ? freq.value : "—"} />
      <Metric
        label="ADF p-value"
        value={`${formatNumber(stationarity.value)}${stationarity.is_stationary === true ? " · стационарен" : stationarity.is_stationary === false ? " · нестационарен" : ""}`}
      />
      <Metric label="R² тренда" value={formatNumber(determinism.value)} />
      <Metric label="Ljung–Box p-value" value={formatNumber(autocorrelation.value)} />
      <Metric label="Jarque–Bera p-value" value={formatNumber(normality.value)} />
      <Metric label="Тренд" value={`${direction} · ${formatNumber(trend.slope)}`} />
      <Metric label="Сила сезонности" value={formatNumber(seasonality.strength)} />
      <Metric label="Показатель Хёрста" value={formatNumber(hurst.value)} />
      <Metric label="Среднее / σ" value={`${formatNumber(basic.mean)} / ${formatNumber(basic.std)}`} />
      <Metric label="Топ-корреляции" value={top3} />
      <Metric label="FFT-периоды" value={formatList(fft.dominant_periods)} />
    </div>
  );
}

function deltaClass(label: string, delta: number): string {
  if (delta === 0) return "text-neutral-500";
  if (label.startsWith("ADF p-value")) return delta < 0 ? "text-green-700" : "text-red-700";
  if (label.startsWith("Jarque-Bera p-value")) return delta > 0 ? "text-green-700" : "text-red-700";
  return "text-neutral-600";
}

function ComparisonView({ data }: { data: PassportCompareResponse }) {
  const metricNames = Array.from(new Set(
    data.comparisons.flatMap((pair) => Object.keys(pair.comparison.metrics)),
  ));
  const values = new Map<string, Partial<Record<PassportStage, number>>>();
  metricNames.forEach((name) => values.set(name, {}));
  data.comparisons.forEach((pair) => {
    Object.entries(pair.comparison.metrics).forEach(([name, metric]) => {
      const row = values.get(name) ?? {};
      row[pair.from_stage] = metric.v_old;
      row[pair.to_stage] = metric.v_new;
      values.set(name, row);
    });
  });

  const qualitative = data.comparisons.flatMap((pair) => pair.comparison.qualitative_changes);
  const categorical = data.comparisons.flatMap((pair) =>
    Object.entries(pair.comparison.categorical_changes)
      .filter(([, change]) => change.changed)
      .map(([label, change]) => ({ label, text: `${String(change.v_old)} → ${String(change.v_new)}` })),
  );
  const listChanges = data.comparisons.flatMap((pair) =>
    Object.entries(pair.comparison.list_changes)
      .filter(([, change]) => change.changed)
      .map(([label, change]) => ({ label, added: change.added ?? [], removed: change.removed ?? [] })),
  );
  const booleanChanges = data.comparisons.flatMap((pair) =>
    Object.entries(pair.comparison.boolean_changes)
      .filter(([, change]) => change.changed)
      .map(([label, change]) => ({
        label,
        text: `${change.v_old ? "Да" : "Нет"} → ${change.v_new ? "Да" : "Нет"}`,
      })),
  );

  return (
    <div className="space-y-4" data-testid="passport-comparison">
      <div className="overflow-x-auto rounded-lg border border-neutral-200">
        <table className="w-full min-w-[720px] text-xs">
          <thead className="bg-neutral-50 text-neutral-600">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Метрика</th>
              {data.path.map((stage) => (
                <th key={stage} className="px-3 py-2 text-right font-medium">{STAGE_TEXT[stage].short}</th>
              ))}
              {data.comparisons.map((pair) => (
                <th key={`${pair.from_stage}-${pair.to_stage}`} className="px-3 py-2 text-right font-medium">
                  Δ {STAGE_TEXT[pair.from_stage].short} → {STAGE_TEXT[pair.to_stage].short}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100">
            {metricNames.map((name) => (
              <tr key={name}>
                <td className="px-3 py-2 font-medium text-neutral-800">{name}</td>
                {data.path.map((stage) => (
                  <td key={stage} className="px-3 py-2 text-right tabular-nums">
                    {formatNumber(values.get(name)?.[stage])}
                  </td>
                ))}
                {data.comparisons.map((pair) => {
                  const metric = pair.comparison.metrics[name];
                  return (
                    <td
                      key={`${pair.from_stage}-${pair.to_stage}`}
                      className={`px-3 py-2 text-right tabular-nums ${metric ? deltaClass(name, metric.delta) : "text-neutral-400"}`}
                    >
                      {metric ? `${metric.delta > 0 ? "+" : ""}${formatNumber(metric.delta)} (${metric.delta_pct > 0 ? "+" : ""}${formatNumber(metric.delta_pct)}%)` : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.comparisons.map((pair) => (
        <p key={`${pair.from_snapshot_id}-${pair.to_snapshot_id}`} className="rounded-lg bg-brand-light px-3 py-2 text-sm text-neutral-700">
          <strong>{STAGE_TEXT[pair.from_stage].short} → {STAGE_TEXT[pair.to_stage].short}:</strong>{" "}
          {pair.comparison.summary}
        </p>
      ))}

      {(qualitative.length > 0 || categorical.length > 0 || listChanges.length > 0 || booleanChanges.length > 0) && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-neutral-800">Качественные изменения</h4>
          <div className="flex flex-wrap gap-2">
            {qualitative.map((text, index) => (
              <span key={`${text}-${index}`} className="rounded-full bg-neutral-100 px-2.5 py-1 text-xs text-neutral-700">{text}</span>
            ))}
            {categorical.map((item, index) => (
              <span key={`${item.label}-${index}`} className="rounded-full bg-neutral-100 px-2.5 py-1 text-xs text-neutral-700">
                {item.label}: {item.text}
              </span>
            ))}
            {booleanChanges.map((item, index) => (
              <span key={`${item.label}-${index}`} className="rounded-full bg-neutral-100 px-2.5 py-1 text-xs text-neutral-700">
                {item.label}: {item.text}
              </span>
            ))}
          </div>
          {listChanges.map((item, index) => (
            <div key={`${item.label}-${index}`} className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="font-medium text-neutral-700">{item.label}:</span>
              {item.added.map((value) => (
                <span key={`added-${String(value)}`} className="rounded bg-green-50 px-2 py-1 text-green-700">+ {String(value)}</span>
              ))}
              {item.removed.map((value) => (
                <span key={`removed-${String(value)}`} className="line-through rounded bg-red-50 px-2 py-1 text-red-700">− {String(value)}</span>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function DatasetPassportPanel({
  stage,
  targetColumn = null,
  suggestedDateColumn = null,
  historyResetNotice = null,
}: DatasetPassportPanelProps) {
  const [status, setStatus] = useState<DatasetPassportStatus | null>(null);
  const [dateConfig, setDateConfig] = useState<DateColumnResponse | null>(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [passport, setPassport] = useState<PassportCaptureResponse | null>(null);
  const [comparison, setComparison] = useState<PassportCompareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"capture" | "compare" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statusResponse, dateResponse] = await Promise.all([
        fetch(sessionApiUrl("/dataset/passport/status"), { credentials: "include" }),
        fetch(sessionApiUrl("/date-column"), { credentials: "include" }),
      ]);
      if (!statusResponse.ok) throw new Error(await responseDetail(statusResponse));
      if (!dateResponse.ok) throw new Error(await responseDetail(dateResponse));
      const [nextStatus, nextDate] = await Promise.all([
        statusResponse.json() as Promise<DatasetPassportStatus>,
        dateResponse.json() as Promise<DateColumnResponse>,
      ]);
      setStatus(nextStatus);
      setDateConfig(nextDate);
      const nextCandidates = Array.isArray(nextDate.candidates) ? nextDate.candidates : [];
      const candidateNames = nextCandidates.map((candidate) => candidate.name);
      const preferred = nextDate.date_column
        ?? (suggestedDateColumn && candidateNames.includes(suggestedDateColumn) ? suggestedDateColumn : null)
        ?? nextDate.suggested_column
        ?? candidateNames[0]
        ?? "";
      setSelectedDate(preferred);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось загрузить состояние паспорта");
    } finally {
      setLoading(false);
    }
  }, [suggestedDateColumn]);

  useEffect(() => {
    setPassport(null);
    setComparison(null);
    setNotice(null);
    void load();
  }, [load, targetColumn]);

  const startPoint = status?.start ?? null;
  const validationPoint = status?.validation ?? null;
  const exitPoint = status?.exit ?? null;
  const dateCandidates = Array.isArray(dateConfig?.candidates)
    ? dateConfig.candidates.filter((candidate) => candidate.score >= 0.7 || candidate.name === dateConfig.date_column)
    : [];
  const currentPoint = stage === "start" ? startPoint : stage === "validation" ? validationPoint : exitPoint;
  const baselinePoint = stage === "start"
    ? startPoint
    : stage === "validation"
    ? (validationPoint?.captured ? validationPoint : startPoint)
    : exitPoint?.captured
    ? exitPoint
    : validationPoint?.captured
    ? validationPoint
    : startPoint;

  const disabledReason = useMemo(() => {
    if (loading) return "Загружается состояние паспорта";
    if (!status?.has_dataset) return "Сначала загрузите датасет";
    if (!status.target_column) return "Сначала выберите исследуемый признак";
    if (!status.date_column && !selectedDate) return "Выберите временную колонку";
    if (stage === "start" && (validationPoint?.captured || exitPoint?.captured)) {
      return "Baseline нельзя менять после фиксации следующей точки";
    }
    if (stage !== "start" && !startPoint?.captured) {
      return "Сначала зафиксируйте паспорт на вкладке «Загрузка»";
    }
    if (stage === "validation" && exitPoint?.captured) {
      return "Итоговый паспорт уже зафиксирован";
    }
    if (!status.series_ready && status.date_column && status.reason) return status.reason;
    if (baselinePoint?.captured && baselinePoint.is_stale === false) {
      return "Свойства ряда не изменились с последнего расчёта";
    }
    return null;
  }, [baselinePoint, exitPoint, loading, selectedDate, stage, startPoint, status, validationPoint]);

  const capture = async () => {
    if (!status || disabledReason || busy) return;
    setBusy("capture");
    setError(null);
    setNotice(null);
    let dateHistoryWasReset = false;
    try {
      if (selectedDate && selectedDate !== status.date_column) {
        const dateResponse = await fetch(sessionApiUrl("/date-column"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ column: selectedDate }),
        });
        if (!dateResponse.ok) throw new Error(await responseDetail(dateResponse));
        const nextDate: DateColumnResponse = await dateResponse.json();
        setDateConfig(nextDate);
        dateHistoryWasReset = nextDate.passport_history_reset;
        if (nextDate.passport_history_reset && stage !== "start") {
          setNotice("Временная колонка изменена; цепочка паспортов сброшена. Сначала зафиксируйте новый паспорт на вкладке «Загрузка».");
          await load();
          return;
        }
      }

      const response = await fetch(sessionApiUrl(`/dataset/passport/${stage}`), {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const body: PassportCaptureResponse = await response.json();
      setPassport(body);
      setComparison(null);
      setNotice(`${dateHistoryWasReset ? "Смена временной колонки сбросила прежнюю цепочку. " : ""}Снимок зафиксирован: ${formatDate(body.captured_at)}`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось рассчитать паспорт");
    } finally {
      setBusy(null);
    }
  };

  const compare = async () => {
    if (stage === "start" || busy) return;
    if (comparison) {
      setComparison(null);
      return;
    }
    setBusy("compare");
    setError(null);
    try {
      const response = await fetch(sessionApiUrl(`/dataset/passport/compare?to=${stage}`), {
        credentials: "include",
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      setComparison(await response.json() as PassportCompareResponse);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось сравнить паспорта");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-5" aria-labelledby={`passport-${stage}-title`}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 id={`passport-${stage}-title`} className="text-base font-semibold text-neutral-900">
            {STAGE_TEXT[stage].title}
          </h2>
          <p className="mt-1 text-xs text-neutral-500">
            Фиксация характеристик ряда без pass/fail-оценки · target: {status?.target_column ?? targetColumn ?? "не выбран"}
          </p>
          {currentPoint?.captured && (
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-600">
              <span>Последний снимок: {formatDate(currentPoint.captured_at)}</span>
              <span>Снимков в истории: {currentPoint.history_count}</span>
              <span className={currentPoint.is_stale ? "text-amber-700" : "text-green-700"}>
                {currentPoint.is_stale ? "Текущий ряд изменён" : "Снимок соответствует текущему ряду"}
              </span>
            </div>
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end">
          <label className="min-w-[190px] text-[11px] text-neutral-500">
            Временная колонка
            <select
              aria-label="Временная колонка паспорта"
              value={selectedDate}
              onChange={(event) => {
                setSelectedDate(event.target.value);
                setError(null);
              }}
              disabled={loading || !dateConfig?.has_dataset || dateCandidates.length === 0}
              className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm text-neutral-800 disabled:bg-neutral-50"
            >
              {!selectedDate && <option value="">Не выбрана</option>}
              {dateCandidates.map((candidate) => (
                <option key={candidate.name} value={candidate.name}>
                  {candidate.name} · {Math.round(candidate.score * 100)}%
                </option>
              ))}
            </select>
          </label>
          <Button
            onClick={() => void capture()}
            disabled={Boolean(disabledReason) || busy !== null}
            title={disabledReason ?? undefined}
            className="whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "capture" ? "Рассчитываем…" : STAGE_TEXT[stage].action}
          </Button>
          {stage !== "start" && currentPoint?.captured && (
            <Button
              variant="secondary"
              onClick={() => void compare()}
              disabled={busy !== null}
              className="whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy === "compare" ? "Сравниваем…" : comparison ? "Скрыть сравнение" : "Сравнить паспорта свойств"}
            </Button>
          )}
        </div>
      </div>

      {!loading && !currentPoint?.captured && (
        <p className="mt-4 rounded-lg bg-neutral-50 px-3 py-2 text-sm text-neutral-600">
          {disabledReason ?? "Паспорт этой точки ещё не зафиксирован."}
        </p>
      )}
      {error && <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {historyResetNotice && (
        <p role="status" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {historyResetNotice}
        </p>
      )}
      {notice && <p role="status" className="mt-4 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">{notice}</p>}
      {passport && <div className="mt-4"><PassportMetrics passport={passport.passport} /></div>}
      {comparison && <div className="mt-5"><ComparisonView data={comparison} /></div>}
    </section>
  );
}
