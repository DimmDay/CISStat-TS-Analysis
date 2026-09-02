"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { CalendarFeature, FeatureGenerationProfile } from "./PreprocessingFeatureEngineeringOverview";


const CALENDAR_LABELS: Array<{ id: CalendarFeature; label: string }> = [
  { id: "year", label: "Год" }, { id: "quarter", label: "Квартал" },
  { id: "month_cyclic", label: "Месяц sin/cos" }, { id: "dayofweek_cyclic", label: "День недели sin/cos" },
  { id: "dayofyear_cyclic", label: "День года sin/cos" }, { id: "hour_cyclic", label: "Час sin/cos" },
  { id: "is_weekend", label: "Выходной" },
];
type Preview = { feature_names: string[]; feature_count: number; rows_before: number; rows_after: number; rows_dropped: number; max_lookback: number };
const list = (value: string): number[] => value.trim() ? value.split(",").map((item) => Number(item.trim())) : [];


export function PreprocessingFeatureEngineeringPipeline({ column, profile, onApplied }: { column: string | null; profile: FeatureGenerationProfile | null; onApplied: () => void }) {
  const [lags, setLags] = useState("");
  const [windows, setWindows] = useState("");
  const [differences, setDifferences] = useState("1");
  const [rollingStats, setRollingStats] = useState<string[]>(["mean", "std"]);
  const [calendar, setCalendar] = useState<CalendarFeature[]>([]);
  const [fourierPeriods, setFourierPeriods] = useState("");
  const [harmonics, setHarmonics] = useState(1);
  const [includeTime, setIncludeTime] = useState(true);
  const [dropWarmup, setDropWarmup] = useState(true);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!profile?.applicable) return;
    setLags(profile.suggested_lags.join(", "));
    setWindows(profile.suggested_rolling_windows.join(", "));
    setCalendar(profile.suggested_calendar_features);
    setFourierPeriods(profile.suggested_fourier_periods.join(", "));
    setPreview(null); setConfirmed(false); setError(null); setSuccess(null);
  }, [profile?.column, profile?.n_observations]);

  const invalidate = () => { setPreview(null); setConfirmed(false); setSuccess(null); };
  const payload = (apply: boolean) => ({
    column, lags: list(lags), rolling_windows: list(windows),
    rolling_statistics: rollingStats, difference_lags: list(differences),
    calendar_features: calendar, fourier_periods: list(fourierPeriods),
    fourier_harmonics: harmonics, include_time_index: includeTime,
    drop_warmup_rows: dropWarmup, apply,
  });
  const request = async (apply: boolean) => {
    if (!column) return;
    setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/preprocessing/feature-generations"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload(apply)),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Не удалось сгенерировать признаки");
      setPreview(data);
      if (apply) { setSuccess(`Добавлено признаков: ${data.feature_count}. Строк: ${data.rows_after}.`); setConfirmed(false); onApplied(); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось сгенерировать признаки"); }
    finally { setBusy(null); }
  };
  const toggle = <T,>(value: T, current: T[], setter: (next: T[]) => void) => {
    setter(current.includes(value) ? current.filter((item) => item !== value) : [...current, value]); invalidate();
  };

  if (!column) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Выберите числовой target.</div>;
  if (!profile) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Сначала дождитесь профиля генерации признаков.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason}</div>;

  return <section role="region" aria-label="Мастер генерации признаков" className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll"><div className="grid gap-4 lg:grid-cols-2"><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Прошлое target</h4><label className="mt-2 block text-xs text-neutral-600">Лаги, через запятую<input aria-label="Лаги target" value={lags} onChange={(event) => { setLags(event.target.value); invalidate(); }} className="mt-1 w-full rounded border px-2 py-1.5" /></label><label className="mt-2 block text-xs text-neutral-600">Rolling-окна<input aria-label="Rolling окна" value={windows} onChange={(event) => { setWindows(event.target.value); invalidate(); }} className="mt-1 w-full rounded border px-2 py-1.5" /></label><div className="mt-2 flex flex-wrap gap-2">{["mean", "std", "min", "max"].map((stat) => <label key={stat} className="text-xs"><input type="checkbox" checked={rollingStats.includes(stat)} onChange={() => toggle(stat, rollingStats, setRollingStats)} className="mr-1 accent-brand" />{stat}</label>)}</div><label className="mt-2 block text-xs text-neutral-600">Разностные лаги<input aria-label="Разностные лаги" value={differences} onChange={(event) => { setDifferences(event.target.value); invalidate(); }} className="mt-1 w-full rounded border px-2 py-1.5" /></label><p className="mt-2 text-[10px] text-neutral-500">Rolling и разности сначала используют shift(1): текущее y[t] не входит в X[t].</p></div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Известные будущие признаки</h4><p className="mt-1 text-[10px] text-neutral-500">Периоды из спектрального анализа: {profile.spectral_periods.join(", ") || "не сохранены"}</p><label className="mt-2 block text-xs text-neutral-600">Fourier-периоды<input aria-label="Fourier периоды" value={fourierPeriods} onChange={(event) => { setFourierPeriods(event.target.value); invalidate(); }} className="mt-1 w-full rounded border px-2 py-1.5" /></label><label className="mt-2 block text-xs text-neutral-600">Гармоник на период<select aria-label="Число Fourier гармоник" value={harmonics} onChange={(event) => { setHarmonics(Number(event.target.value)); invalidate(); }} className="ml-2 rounded border px-2 py-1">{[1, 2, 3, 4, 5].map((value) => <option key={value}>{value}</option>)}</select></label><div className="mt-2 grid grid-cols-2 gap-1">{CALENDAR_LABELS.map((item) => <label key={item.id} className={`text-[10px] ${profile.order_column ? "" : "text-neutral-400"}`}><input type="checkbox" disabled={!profile.order_column} checked={calendar.includes(item.id)} onChange={() => toggle(item.id, calendar, setCalendar)} className="mr-1 accent-brand" />{item.label}</label>)}</div><label className="mt-2 block text-xs"><input type="checkbox" checked={includeTime} onChange={(event) => { setIncludeTime(event.target.checked); invalidate(); }} className="mr-1 accent-brand" />Линейный time_idx</label></div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><label className="mt-2 flex items-start gap-2 text-xs"><input type="checkbox" checked={dropWarmup} onChange={(event) => { setDropWarmup(event.target.checked); invalidate(); }} className="mt-0.5 accent-brand" />Удалить общий warm-up префикс без доступной истории</label><button type="button" disabled={busy !== null} onClick={() => void request(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Проверка…" : "Проверить набор признаков"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs"><p>Будет добавлено: {preview.feature_names.length}</p><p>Максимальный lookback: {preview.max_lookback}</p><p>Будет удалено начальных строк: {preview.rows_dropped}</p><p>Строк после: {preview.rows_after}</p></div>}</div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Применение</h4><p className="mt-1 text-xs text-neutral-500">Формулы построчно каузальны. Выбор набора по полной истории всё равно повторяется внутри train-fold. Для горизонта &gt;1 лаги target требуют рекурсивного сценария.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" aria-label="Подтверждаю применение набора признаков" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 accent-brand" />Подтверждаю применение набора признаков</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => void request(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Генерация…" : "Сгенерировать признаки"}</button></div></div>{error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}</section>;
}
