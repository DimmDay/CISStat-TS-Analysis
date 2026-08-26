"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

export interface SufficiencyCheck { id: string; label: string; actual: number; threshold: number; unit: string; passed: boolean; deficit: number; models: string }
export interface SufficiencyGroup {
  group: string; rows_total: number; valid_observations: number; invalid_target_count: number; invalid_date_count: number;
  unique_timestamps: number; frequency: string | null; seasonal_period: number; seasonal_cycles: number;
  failed_checks: number; passed_checks: number; checks: SufficiencyCheck[]; available_capabilities: string[]; unavailable_capabilities: string[];
}
export interface SufficiencyProfile {
  applicable: boolean; applicability_message: string | null; date_column: string | null; entity_column: string | null; target_column: string | null;
  frequency: string | null; seasonal_period: number | null; groups_total: number; sufficient_groups: number; insufficient_groups: number;
  total_failed_checks: number; groups: SufficiencyGroup[]; thresholds: Array<{ id: string; label: string; threshold: number; unit: string; models: string }>;
  supported_actions: string[];
}
export interface SufficiencyProfileResponse { rule_source: "system" | "template" | "session" | "not_applicable"; plan: Record<string, unknown>; profile: SufficiencyProfile }

async function responseDetail(response: Response) { try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ } return `Не удалось загрузить профиль достаточности (HTTP ${response.status})`; }

export function ValidationSufficiencyOverview({ refreshKey = 0 }: { refreshKey?: number }) {
  const [data, setData] = useState<SufficiencyProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { let active = true; setLoading(true); setError(null); void (async () => { try {
    const response = await fetch(sessionApiUrl("/dataset/sufficiency-profile"), { credentials: "include" });
    if (!response.ok) throw new Error(await responseDetail(response));
    const body: SufficiencyProfileResponse = await response.json(); if (active) setData(body);
  } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль достаточности"); } finally { if (active) setLoading(false); } })(); return () => { active = false; }; }, [refreshKey]);

  const totals = useMemo(() => ({ sufficient: data?.profile.sufficient_groups ?? 0, limited: data?.profile.insufficient_groups ?? 0 }), [data]);
  const total = totals.sufficient + totals.limited;
  if (loading) return <p className="text-sm text-neutral-400">Загрузка профиля достаточности…</p>;
  if (error) return <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!data?.profile.applicable) return <div className="rounded bg-neutral-50 px-3 py-3 text-sm text-neutral-600"><p className="font-medium">{data?.profile.applicability_message || "Проверка неприменима"}</p><p className="mt-1 text-xs">Укажите временную, целевую и при необходимости группирующую колонки в «Управлении правилами» либо отключите остановку.</p></div>;
  const profile = data.profile;
  const planStrategy = typeof data.plan?.strategy === "string" ? data.plan.strategy : null;
  return <section className="space-y-3">
    {planStrategy && <p className="rounded bg-blue-50 px-3 py-2 text-xs text-blue-700">Решение принято: {planStrategy === "restrict_models" ? "аналитик принял ограничения доступных методов" : planStrategy === "flag_groups" ? "группы отмечены диагностическим флагом" : "недостаточные группы исключены"}.</p>}
    <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
      <div className="rounded bg-neutral-50 p-2"><span className="text-neutral-500">Целевой ряд</span><strong className="block font-mono">{profile.target_column}</strong></div>
      <div className="rounded bg-neutral-50 p-2"><span className="text-neutral-500">Временная ось</span><strong className="block font-mono">{profile.date_column}</strong></div>
      <div className="rounded bg-neutral-50 p-2"><span className="text-neutral-500">Частота / цикл</span><strong className="block font-mono">{profile.frequency || "—"} / {profile.seasonal_period}</strong></div>
      <div className="rounded bg-neutral-50 p-2"><span className="text-neutral-500">Недоступных требований</span><strong className="block font-mono">{profile.total_failed_checks}</strong></div>
    </div>
    <div><div className="mb-1 flex justify-between text-xs text-neutral-500"><span>Применимость по группам</span><span>{total} групп</span></div>
      <div role="img" aria-label={`Достаточных групп: ${totals.sufficient}; ограниченных групп: ${totals.limited}`} className="flex h-3 overflow-hidden rounded-full bg-neutral-100">
        <div className="bg-green-500" style={{ width: `${total ? totals.sufficient / total * 100 : 0}%` }} /><div className="bg-amber-400" style={{ width: `${total ? totals.limited / total * 100 : 0}%` }} />
      </div><div className="mt-1 flex gap-4 text-xs text-neutral-600"><span>● Достаточные {totals.sufficient}</span><span className="text-amber-700">● Ограниченные {totals.limited}</span></div>
    </div>
    <div className="overflow-x-auto rounded border border-neutral-200"><table aria-label="Матрица достаточности наблюдений" className="w-full text-left text-xs">
      <thead className="bg-neutral-50 text-neutral-500"><tr><th className="px-3 py-2">Группа</th><th className="px-3 py-2">Валидные наблюдения</th><th className="px-3 py-2">Циклы</th><th className="px-3 py-2">Недоступно</th><th className="px-3 py-2">Статус</th></tr></thead>
      <tbody>{profile.groups.map((item) => <tr key={item.group} className="border-t border-neutral-100 text-neutral-700">
        <td className="px-3 py-2 font-mono font-medium text-neutral-800">{item.group}</td><td className="px-3 py-2">{item.valid_observations}{item.invalid_target_count ? ` (${item.invalid_target_count} пропусков)` : ""}</td><td className="px-3 py-2">{item.seasonal_cycles} × {item.seasonal_period}</td><td className="max-w-64 px-3 py-2">{item.unavailable_capabilities.join(", ") || "—"}</td><td className="px-3 py-2"><span className={`rounded px-2 py-1 font-medium ${item.failed_checks ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>{item.failed_checks ? "Ограниченный выбор моделей" : "Достаточно"}</span></td>
      </tr>)}</tbody>
    </table></div>
    <p role="status" className={`rounded px-3 py-2 text-xs ${profile.total_failed_checks && !planStrategy ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>{profile.total_failed_checks ? planStrategy ? "Ограничение принято и учтено в общей валидации." : "Данные пригодны для части методов. Откройте мастер, чтобы зафиксировать безопасный план анализа." : "Проверка пройдена: все заданные требования к длине ряда выполнены."}</p>
  </section>;
}
