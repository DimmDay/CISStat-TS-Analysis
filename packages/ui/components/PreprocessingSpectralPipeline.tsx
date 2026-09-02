"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { PreprocessingSpectralProfile } from "./PreprocessingSpectralOverview";


export interface SpectralParameters {
  minCycles: number; maxCandidates: number; welchSegmentLength: number | null; waveletScales: number;
}
interface SelectionResponse {
  applied: boolean; column: string; selected_periods: number[]; confirmed_periods: number[];
  unconfirmed_periods: number[]; suggested_lags: number[];
}

async function detail(response: Response): Promise<string> {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

export function PreprocessingSpectralPipeline({ column, profile, parameters, onParametersChange, onApplied }: {
  column: string | null;
  profile: PreprocessingSpectralProfile | null;
  parameters?: SpectralParameters;
  onParametersChange?: (changes: Partial<SpectralParameters>) => void;
  onApplied: () => void;
}) {
  const config = parameters ?? { minCycles: profile?.min_cycles ?? 3, maxCandidates: profile?.max_candidates ?? 6, welchSegmentLength: null, waveletScales: 24 };
  const [selected, setSelected] = useState<number[]>(profile?.saved_periods ?? []);
  const [confirmUnconfirmed, setConfirmUnconfirmed] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<SelectionResponse | null>(null);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  useEffect(() => {
    setSelected(profile?.saved_periods ?? []); setPreview(null); setConfirmed(false); setConfirmUnconfirmed(false);
  }, [column, profile?.saved_periods?.join(",")]);
  const candidatePeriods = useMemo(() => {
    const seen = new Set<number>();
    return (profile?.candidates ?? []).filter((item) => {
      if (seen.has(item.period_rounded)) return false;
      seen.add(item.period_rounded);
      return true;
    });
  }, [profile]);
  const hasUnconfirmed = candidatePeriods.some((item) => selected.includes(item.period_rounded) && !item.confirmed);
  const invalidate = () => { setPreview(null); setConfirmed(false); setError(null); setSuccess(null); };
  const changeParameter = (changes: Partial<SpectralParameters>) => { invalidate(); onParametersChange?.(changes); };
  const toggle = (period: number) => { invalidate(); setSelected((current) => current.includes(period) ? current.filter((value) => value !== period) : [...current, period].sort((a, b) => a - b)); };
  const request = async (apply: boolean) => {
    if (!column) return;
    setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/preprocessing/spectral-selections"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ column, periods: selected, min_cycles: config.minCycles, max_candidates: config.maxCandidates, welch_segment_length: config.welchSegmentLength, confirm_unconfirmed: confirmUnconfirmed, apply }),
      });
      if (!response.ok) throw new Error(await detail(response));
      const data: SelectionResponse = await response.json(); setPreview(data); setConfirmed(false);
      if (apply) { setSuccess("Периоды сохранены как аналитический контракт для генерации признаков"); onApplied(); }
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось сохранить периоды"); }
    finally { setBusy(null); }
  };

  if (!column) return <section role="region" aria-label="Мастер спектрального анализа" className="h-[468px] rounded-lg border border-neutral-200 bg-white p-4"><p role="status" className="rounded bg-amber-50 p-3 text-sm text-amber-800">Выберите числовой исследуемый признак.</p></section>;
  return <section role="region" aria-label="Мастер спектрального анализа" className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll"><div className="grid gap-4 lg:grid-cols-2"><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Разрешение анализа</h4><div className="mt-2 grid grid-cols-2 gap-2"><label className="text-xs text-neutral-600">Минимум циклов<select aria-label="Минимум полных циклов" value={config.minCycles} onChange={(event) => changeParameter({ minCycles: Number(event.target.value) })} className="mt-1 w-full rounded border px-2 py-1.5">{[2, 3, 4, 5].map((value) => <option key={value}>{value}</option>)}</select></label><label className="text-xs text-neutral-600">Число кандидатов<select aria-label="Число спектральных кандидатов" value={config.maxCandidates} onChange={(event) => changeParameter({ maxCandidates: Number(event.target.value) })} className="mt-1 w-full rounded border px-2 py-1.5">{[3, 6, 8, 10].map((value) => <option key={value}>{value}</option>)}</select></label><label className="col-span-2 text-xs text-neutral-600">Сегмент Welch<select aria-label="Длина сегмента Welch" value={config.welchSegmentLength ?? "auto"} onChange={(event) => changeParameter({ welchSegmentLength: event.target.value === "auto" ? null : Number(event.target.value) })} className="mt-1 w-full rounded border px-2 py-1.5"><option value="auto">Авто · не менее 3 сегментов</option>{[32, 64, 128, 256].filter((value) => value <= (profile?.n_observations ?? value)).map((value) => <option key={value} value={value}>{value}</option>)}</select></label></div><p className="mt-2 text-[10px] text-neutral-500">Меньший сегмент Welch даёт больше усреднений, но грубее частотное разрешение. 50% overlap фиксирован по рекомендации SciPy для Hann.</p></div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Периоды-кандидаты</h4>{candidatePeriods.length ? <div className="mt-2 max-h-36 space-y-1 overflow-y-auto">{candidatePeriods.map((item) => <label key={item.period_rounded} className="flex items-start gap-2 rounded bg-neutral-50 p-2 text-xs"><input type="checkbox" aria-label={`Период ${item.period_rounded}`} checked={selected.includes(item.period_rounded)} onChange={() => toggle(item.period_rounded)} className="mt-0.5 accent-brand" /><span><strong>{item.period_rounded}</strong> наблюдений · {item.calendar_hint ?? `≈ ${item.period.toFixed(2)}`}<small className={`ml-2 ${item.confirmed ? "text-green-700" : "text-amber-700"}`}>{item.confirmed ? "подтверждён" : "не подтверждён"}</small></span></label>)}</div> : <p className="mt-2 text-xs text-neutral-500">Устойчивые пики не найдены. Можно сохранить явное решение «без периодов».</p>}{hasUnconfirmed && <label className="mt-2 flex items-start gap-2 text-xs text-amber-800"><input type="checkbox" aria-label="Подтверждаю выбор неподтверждённых периодов" checked={confirmUnconfirmed} onChange={(event) => { invalidate(); setConfirmUnconfirmed(event.target.checked); }} className="mt-0.5 accent-brand" />Подтверждаю предметный выбор неподтверждённых периодов</label>}</div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Проверка решения</h4><p className="mt-1 text-xs text-neutral-500">Остановка не создаёт лаговые признаки и не изменяет датасет — это задача следующего шага.</p><button type="button" disabled={busy !== null || (hasUnconfirmed && !confirmUnconfirmed)} onClick={() => void request(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Проверка…" : "Проверить выбор периодов"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs"><p>Выбрано: {preview.selected_periods.join(", ") || "без периодов"}</p><p>Лаги-кандидаты: {preview.suggested_lags.join(", ") || "нет"}</p><p>Неподтверждённые: {preview.unconfirmed_periods.join(", ") || "нет"}</p></div>}</div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Сохранение</h4><p className="mt-1 text-xs text-neutral-500">Решение получено по полной истории и не должно переноситься в backtest как заранее известное: lag selection повторяется внутри train-fold.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" aria-label="Подтверждаю сохранение аналитического решения" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 accent-brand" />Подтверждаю сохранение аналитического решения</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => void request(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Сохранение…" : "Сохранить периоды"}</button></div></div>{error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}</section>;
}
