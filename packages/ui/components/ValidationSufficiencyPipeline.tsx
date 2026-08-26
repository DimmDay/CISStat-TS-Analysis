"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { SufficiencyProfile, SufficiencyProfileResponse } from "./ValidationSufficiencyOverview";

type Strategy = "restrict_models" | "flag_groups" | "drop_groups";
interface PlanResponse { applied: boolean; strategy: Strategy; rows_before: number; rows_after: number; rows_removed: number; added_columns: string[]; eligible_groups: string[]; insufficient_groups: string[]; profile: SufficiencyProfile }
const STRATEGIES: Record<Strategy, { label: string; help: string }> = {
  restrict_models: { label: "Принять ограничения моделей", help: "Сохраняет данные и фиксирует решение использовать только методы, для которых наблюдений достаточно. Рекомендуется." },
  flag_groups: { label: "Отметить группы флагом", help: "Добавляет _sufficiency_eligible для фильтрации групп в следующих этапах." },
  drop_groups: { label: "Исключить недостаточные группы", help: "Удаляет целые группы. Доступно только для панельных данных и требует подтверждения." },
};
async function responseDetail(response: Response) { try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ } return `Не удалось выполнить операцию (HTTP ${response.status})`; }

export function ValidationSufficiencyPipeline({ onApplied, onOpenRules }: { onApplied: () => void; onOpenRules: () => void }) {
  const [data, setData] = useState<SufficiencyProfileResponse | null>(null);
  const [strategy, setStrategy] = useState<Strategy>("restrict_models");
  const [preview, setPreview] = useState<PlanResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => { let active = true; void (async () => { try { const response = await fetch(sessionApiUrl("/dataset/sufficiency-profile"), { credentials: "include" }); if (!response.ok) throw new Error(await responseDetail(response)); const body: SufficiencyProfileResponse = await response.json(); if (active) setData(body); } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль достаточности"); } finally { if (active) setBusy(null); } })(); return () => { active = false; }; }, []);
  const invalidate = () => { setPreview(null); setConfirmed(false); setSuccess(null); setError(null); };
  const requestPlan = async (apply: boolean) => { setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null); try { const response = await fetch(sessionApiUrl("/dataset/sufficiency-plan"), { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify({ strategy, apply }) }); if (!response.ok) throw new Error(await responseDetail(response)); const body: PlanResponse = await response.json(); setPreview(body); setConfirmed(false); if (apply) { setData((current) => current ? { ...current, plan: { strategy }, profile: body.profile } : current); setSuccess("План анализа сохранён, валидация запущена повторно"); onApplied(); } } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось сохранить план анализа"); } finally { setBusy(null); } };
  const profile = data?.profile;
  const passed = Boolean(profile?.applicable && profile.total_failed_checks === 0);
  const hasSavedPlan = typeof data?.plan?.strategy === "string";
  return <section role="region" aria-label="Мастер решений по достаточности" className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll">
    {hasSavedPlan && <div role="status" className="mb-4 rounded bg-blue-50 px-3 py-2 text-sm text-blue-700">Для текущего профиля уже сохранён план анализа.</div>}
    {profile && !profile.applicable && <div className="mb-4 rounded bg-neutral-50 p-3 text-sm text-neutral-600"><p className="font-medium">{profile.applicability_message}</p><button type="button" onClick={onOpenRules} className="mt-2 rounded border border-neutral-300 px-3 py-1.5 text-xs font-medium">Открыть управление правилами</button></div>}
    {passed && <div role="status" className="mb-4 rounded bg-green-50 px-3 py-2 text-sm text-green-700"><p className="font-medium">Требования к длине ряда выполнены.</p><p className="mt-0.5 text-xs">Дополнительное решение не требуется.</p></div>}
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Ряд и требования</h4><p className="mt-1 text-xs text-neutral-500">Считаются только строки с корректной датой и числовым значением.</p>{busy === "load" ? <p className="mt-3 text-sm text-neutral-400">Загрузка профиля…</p> : profile?.applicable && <div className="mt-3 space-y-1 text-xs"><p>Цель: <strong className="font-mono">{profile.target_column}</strong></p><p>Ось / группа: <strong className="font-mono">{profile.date_column}</strong> / <strong className="font-mono">{profile.entity_column || "весь датасет"}</strong></p><p>Достаточно групп: <strong>{profile.sufficient_groups}</strong>; ограничено: <strong>{profile.insufficient_groups}</strong></p></div>}</div>
      <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Решение аналитика</h4><p className="mt-1 text-xs text-neutral-500">Данные не дополняются синтетически и не агрегируются под видом увеличения n.</p><select aria-label="Решение по достаточности" value={strategy} onChange={(event) => { invalidate(); setStrategy(event.target.value as Strategy); }} className="mt-3 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm">{(Object.keys(STRATEGIES) as Strategy[]).map((key) => <option key={key} value={key}>{STRATEGIES[key].label}</option>)}</select><p className="mt-2 text-xs text-neutral-600">{STRATEGIES[strategy].help}</p></div>
      <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><p className="mt-1 text-xs text-neutral-500">Показывает охват решения без изменения активного датасета.</p><button type="button" disabled={!profile?.applicable || passed || busy !== null} onClick={() => requestPlan(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Выполняется…" : "Предпросмотр решения"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs"><p>Достаточные группы: {preview.eligible_groups.join(", ") || "нет"}</p><p>Ограниченные группы: {preview.insufficient_groups.join(", ") || "нет"}</p><p>Удаляемых строк: {preview.rows_removed}</p>{preview.added_columns.length > 0 && <p>Добавлены колонки: {preview.added_columns.join(", ")}</p>}</div>}</div>
      <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Сохранение решения</h4><p className="mt-1 text-xs text-neutral-500">Ограничение моделей сохраняет план; маркировка и исключение также меняют датасет.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} aria-label="Подтверждаю выбранное решение" className="mt-0.5 accent-brand"/>Подтверждаю выбранное решение и его последствия</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => requestPlan(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Сохранение…" : "Сохранить план анализа"}</button></div>
    </div>{error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}
  </section>;
}
