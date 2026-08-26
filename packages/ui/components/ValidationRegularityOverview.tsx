"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

export interface RegularityGroup {
  group: string; observations: number; inferred_frequency: string | null; modal_interval: string | null;
  gap_count: number; missing_period_count: number; duplicate_count: number; sort_violations: number;
  gap_examples: Array<{ previous_date: string; current_date: string; missing_periods: number }>;
}

export interface RegularityProfile {
  applicable: boolean; applicability_message: string | null; date_column: string | null; entity_column: string | null;
  target_frequency: string | null; detected_frequency: string | null; gap_threshold_multiplier: number;
  is_sorted: boolean; sort_violations: number; invalid_date_count: number; duplicate_count: number;
  gap_count: number; missing_period_count: number; total_violations: number;
  groups: RegularityGroup[]; supported_actions: string[];
}

export interface RegularityProfileResponse {
  rule_source: "system" | "template" | "session" | "not_applicable";
  profile: RegularityProfile;
}

async function responseDetail(response: Response) {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось загрузить профиль равномерности (HTTP ${response.status})`;
}

export function ValidationRegularityOverview({ refreshKey = 0 }: { refreshKey?: number }) {
  const [data, setData] = useState<RegularityProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(null);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/regularity-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const body: RegularityProfileResponse = await response.json();
        if (active) setData(body);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль равномерности");
      } finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, [refreshKey]);

  const groupTotals = useMemo(() => ({
    regular: data?.profile.groups.filter((item) => item.gap_count + item.duplicate_count + item.sort_violations === 0).length ?? 0,
    problematic: data?.profile.groups.filter((item) => item.gap_count + item.duplicate_count + item.sort_violations > 0).length ?? 0,
  }), [data]);
  const totalGroups = groupTotals.regular + groupTotals.problematic;

  if (loading) return <p className="text-sm text-neutral-400">Загрузка профиля равномерности…</p>;
  if (error) return <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!data?.profile.applicable) return <div className="rounded bg-neutral-50 px-3 py-3 text-sm text-neutral-600"><p className="font-medium">{data?.profile.applicability_message || "Проверка неприменима"}</p><p className="mt-1 text-xs">Укажите временную ось в «Управлении правилами» либо отключите остановку.</p></div>;

  const profile = data.profile;
  return (
    <section className="space-y-3">
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div className="rounded bg-neutral-50 p-2"><span className="text-neutral-500">Временная ось</span><strong className="block font-mono">{profile.date_column}</strong></div>
        <div className="rounded bg-neutral-50 p-2"><span className="text-neutral-500">Группировка</span><strong className="block font-mono">{profile.entity_column || "Нет"}</strong></div>
        <div className="rounded bg-neutral-50 p-2"><span className="text-neutral-500">Целевой шаг</span><strong className="block font-mono">{profile.target_frequency || "Не определён"}</strong></div>
        <div className="rounded bg-neutral-50 p-2"><span className="text-neutral-500">Пропущено периодов</span><strong className="block font-mono">{profile.missing_period_count}</strong></div>
      </div>
      <div>
        <div className="mb-1 flex justify-between text-xs text-neutral-500"><span>Равномерность групп</span><span>{totalGroups} групп</span></div>
        <div role="img" aria-label={`Регулярных групп: ${groupTotals.regular}; проблемных групп: ${groupTotals.problematic}`} className="flex h-3 overflow-hidden rounded-full bg-neutral-100">
          <div className="bg-green-500" style={{ width: `${totalGroups ? groupTotals.regular / totalGroups * 100 : 0}%` }} />
          <div className="bg-amber-400" style={{ width: `${totalGroups ? groupTotals.problematic / totalGroups * 100 : 0}%` }} />
        </div>
        <div className="mt-1 flex gap-4 text-xs text-neutral-600"><span>● Регулярные {groupTotals.regular}</span><span className="text-amber-700">● С проблемами {groupTotals.problematic}</span></div>
      </div>
      <div className="overflow-x-auto rounded border border-neutral-200">
        <table aria-label="Матрица равномерности временного шага" className="w-full text-left text-xs">
          <thead className="bg-neutral-50 text-neutral-500"><tr><th className="px-3 py-2">Группа</th><th className="px-3 py-2">Наблюдения</th><th className="px-3 py-2">Частота / интервал</th><th className="px-3 py-2">Разрывы</th><th className="px-3 py-2">Дубли / сортировка</th><th className="px-3 py-2">Статус</th></tr></thead>
          <tbody>{profile.groups.map((item) => {
            const problems = item.gap_count + item.duplicate_count + item.sort_violations;
            return <tr key={item.group} className="border-t border-neutral-100 text-neutral-700">
              <td className="px-3 py-2 font-mono font-medium text-neutral-800">{item.group}</td><td className="px-3 py-2">{item.observations}</td>
              <td className="px-3 py-2">{item.inferred_frequency || profile.target_frequency || item.modal_interval || "—"}</td>
              <td className="px-3 py-2">{item.gap_count ? <><span>{item.gap_count} разр.</span>; <span>{item.missing_period_count} пропущен{item.missing_period_count === 1 ? "" : "о"}</span></> : "0"}</td>
              <td className="px-3 py-2">{item.duplicate_count} / {item.sort_violations}</td>
              <td className="px-3 py-2"><span className={`rounded px-2 py-1 font-medium ${problems ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>{problems ? "Найдены проблемы" : "Соответствует"}</span></td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      {(profile.invalid_date_count > 0 || profile.total_violations === 0) && <p role="status" className={`rounded px-3 py-2 text-xs ${profile.total_violations ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>{profile.total_violations ? `Некорректных дат: ${profile.invalid_date_count}. Всего причин нарушений: ${profile.total_violations}.` : "Проверка пройдена: временной шаг равномерен."}</p>}
    </section>
  );
}
