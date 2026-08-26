"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { RegularityProfile, RegularityProfileResponse } from "./ValidationRegularityOverview";

type Strategy = "sort" | "interpolate" | "ffill" | "bfill" | "asfreq" | "fictitious_zero" | "flag";
interface CorrectionResponse {
  applied: boolean; strategy: Strategy; frequency: string | null; rows_before: number; rows_after: number; rows_added: number;
  duplicates_aggregated: number; total_violations_before: number; total_violations_after: number;
  sort_violations_before: number; sort_violations_after: number; added_columns: string[]; profile: RegularityProfile;
}
const STRATEGIES: Record<Strategy, { label: string; help: string; needsFrequency: boolean }> = {
  interpolate: { label: "Resample + Interpolate", help: "Строит полную сетку; числовые значения интерполируются, остальные протягиваются.", needsFrequency: true },
  ffill: { label: "Resample + Forward Fill", help: "Новые периоды получают последнее известное значение.", needsFrequency: true },
  bfill: { label: "Resample + Backward Fill", help: "Новые периоды получают следующее известное значение.", needsFrequency: true },
  asfreq: { label: "Resample без заполнения", help: "Создаёт полную сетку, оставляя значения новых строк пропусками.", needsFrequency: true },
  fictitious_zero: { label: "Добавить фиктивные нули", help: "Числовые значения новых периодов равны нулю; категории протягиваются.", needsFrequency: true },
  sort: { label: "Только отсортировать", help: "Упорядочивает временные метки внутри каждой сущности, не добавляя строк.", needsFrequency: false },
  flag: { label: "Только отметить флагом", help: "Сохраняет данные и добавляет признак _has_gap к строкам с причиной нарушения.", needsFrequency: false },
};
async function responseDetail(response: Response) { try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ } return `Не удалось выполнить операцию (HTTP ${response.status})`; }

export function ValidationRegularityPipeline({ onApplied, onOpenRules }: { onApplied: () => void; onOpenRules: () => void }) {
  const [profile, setProfile] = useState<RegularityProfileResponse | null>(null);
  const [strategy, setStrategy] = useState<Strategy>("interpolate");
  const [frequency, setFrequency] = useState("");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => { let active = true; void (async () => { try {
    const response = await fetch(sessionApiUrl("/dataset/regularity-profile"), { credentials: "include" });
    if (!response.ok) throw new Error(await responseDetail(response));
    const body: RegularityProfileResponse = await response.json(); if (!active) return;
    setProfile(body); setFrequency(body.profile.target_frequency || "");
    if (body.profile.sort_violations > 0) setStrategy("sort");
  } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль равномерности"); } finally { if (active) setBusy(null); } })(); return () => { active = false; }; }, []);

  const invalidate = () => { setPreview(null); setConfirmed(false); setSuccess(null); setError(null); };
  const requestCorrection = async (apply: boolean) => { setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null); try {
    const body = { strategy, frequency: STRATEGIES[strategy].needsFrequency ? frequency : null, apply };
    const response = await fetch(sessionApiUrl("/dataset/regularity-corrections"), { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(body) });
    if (!response.ok) throw new Error(await responseDetail(response));
    const data: CorrectionResponse = await response.json(); setPreview(data); setConfirmed(false);
    if (apply) { setProfile((current) => current ? { ...current, profile: data.profile } : current); setSuccess("Изменения применены, проверка запущена повторно"); onApplied(); }
  } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось исправить равномерность шага"); } finally { setBusy(null); } };
  const current = profile?.profile;
  const passed = Boolean(current?.applicable && current.total_violations === 0);

  return <section role="region" aria-label="Мастер исправления равномерности шага" className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll">
    {current && !current.applicable && <div className="mb-4 rounded bg-neutral-50 p-3 text-sm text-neutral-600"><p className="font-medium">{current.applicability_message}</p><button type="button" onClick={onOpenRules} className="mt-2 rounded border border-neutral-300 px-3 py-1.5 text-xs font-medium">Открыть управление правилами</button></div>}
    {passed && <div role="status" className="mb-4 rounded bg-green-50 px-3 py-2 text-sm text-green-700"><p className="font-medium">Временной шаг равномерен.</p><p className="mt-0.5 text-xs">Исправление не требуется.</p></div>}
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Ось времени и группы</h4><p className="mt-1 text-xs text-neutral-500">Проверка выполняется внутри каждой сущности; системные колонки можно переопределить правилами.</p>{busy === "load" ? <p className="mt-3 text-sm text-neutral-400">Загрузка профиля…</p> : current?.applicable && <div className="mt-3 space-y-1 text-xs"><p>Временная колонка: <strong className="font-mono">{current.date_column}</strong></p><p>Группа: <strong className="font-mono">{current.entity_column || "весь датасет"}</strong></p><p>Разрывы: <strong>{current.gap_count}</strong>; пропущено периодов: <strong>{current.missing_period_count}</strong></p><p>Дубли: <strong>{current.duplicate_count}</strong>; сортировка: <strong>{current.sort_violations}</strong></p></div>}</div>
      <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Стратегия исправления</h4><p className="mt-1 text-xs text-neutral-500">Выберите действие и явно подтвердите частоту временной сетки.</p><select aria-label="Стратегия исправления равномерности шага" value={strategy} onChange={(event) => { invalidate(); setStrategy(event.target.value as Strategy); }} className="mt-3 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm">{(Object.keys(STRATEGIES) as Strategy[]).map((key) => <option key={key} value={key}>{STRATEGIES[key].label}</option>)}</select>{STRATEGIES[strategy].needsFrequency && <label className="mt-2 block text-xs text-neutral-600">Частота (pandas)<input aria-label="Частота временной сетки" value={frequency} onChange={(event) => { invalidate(); setFrequency(event.target.value); }} placeholder="D, W, MS, YS…" className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 font-mono" /></label>}<p className="mt-2 text-xs text-neutral-600">{STRATEGIES[strategy].help}</p></div>
      <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на копии и не меняет активный датасет.</p><button type="button" disabled={!current?.applicable || passed || busy !== null || (STRATEGIES[strategy].needsFrequency && !frequency.trim())} onClick={() => requestCorrection(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs"><p className="font-medium">Добавлено строк: {preview.rows_added}</p><p>Агрегировано дублей: {preview.duplicates_aggregated}</p><p>Нарушений после исправления: {preview.total_violations_after}</p>{preview.added_columns.length > 0 && <p>Добавлены колонки: {preview.added_columns.join(", ")}</p>}</div>}</div>
      <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Применение</h4><p className="mt-1 text-xs text-neutral-500">После сохранения общая валидация запускается повторно.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} aria-label="Подтверждаю изменение активного датасета" className="mt-0.5 accent-brand"/>Подтверждаю изменение активного датасета</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => requestCorrection(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Применение…" : "Применить исправления"}</button></div>
    </div>{error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}
  </section>;
}
