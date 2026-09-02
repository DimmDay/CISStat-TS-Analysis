"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";


export interface UniquenessGroup {
  key_values: Record<string, string>;
  occurrences: number;
  redundant_rows: number;
  row_numbers: number[];
}

export interface UniquenessProfile {
  applicable: boolean;
  applicability_message: string | null;
  mode: "composite_key" | "inferred_key" | "full_row";
  key_columns: string[];
  total_rows: number;
  valid_rows: number;
  duplicate_rows: number | null;
  duplicate_groups: number | null;
  redundant_rows: number | null;
  duplicate_pct: number | null;
  groups: UniquenessGroup[];
  supported_actions: string[];
}

export interface UniquenessProfileResponse {
  rule_source: "system" | "template" | "session" | "not_applicable";
  profile: UniquenessProfile;
}

async function detail(response: Response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch { /* нейтральное сообщение ниже */ }
  return `Не удалось загрузить профиль (HTTP ${response.status})`;
}

export const uniquenessKeyLabel = (profile: UniquenessProfile) => profile.mode === "full_row"
  ? "Полные строки"
  : `${profile.mode === "composite_key" ? "Составной ключ" : "Системный ключ"}: ${profile.key_columns.join(" + ")}`;

const uniquenessCheckLabel = (profile: UniquenessProfile) => profile.mode === "full_row"
  ? "полным строкам"
  : `${profile.mode === "composite_key" ? "составному ключу" : "системному ключу"} ${profile.key_columns.join(" + ")}`;

export function ValidationUniquenessOverview({ refreshKey = 0 }: { refreshKey?: number }) {
  const [response, setResponse] = useState<UniquenessProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const result = await fetch(sessionApiUrl("/dataset/uniqueness-profile"), { credentials: "include" });
        if (!result.ok) throw new Error(await detail(result));
        const data = await result.json();
        if (active) setResponse(data);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль уникальности");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [refreshKey]);

  if (loading) return <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Загрузка профиля уникальности…</div>;
  if (error) return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  if (!response?.profile.applicable) return <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-600">{response?.profile.applicability_message || "Правило уникальности неприменимо. Проверьте составной ключ в «Управлении правилами»."}</div>;

  const profile = response.profile;
  const duplicates = profile.duplicate_rows ?? 0;
  const validPct = profile.total_rows ? (profile.valid_rows / profile.total_rows) * 100 : 100;
  return (
    <section className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
      <div className="border-b border-neutral-100 p-4">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-semibold text-neutral-800">Распределение строк</h4>
          <span className="text-xs text-neutral-500">{uniquenessKeyLabel(profile)}</span>
        </div>
        <div role="img" aria-label={`Уникальных строк: ${profile.valid_rows}; строк в группах дублей: ${duplicates}`} className="mt-3 flex h-3 overflow-hidden rounded-full bg-neutral-100">
          {profile.valid_rows > 0 && <div className="bg-green-500" style={{ width: `${validPct}%` }} />}
          {duplicates > 0 && <div className="bg-amber-400" style={{ width: `${100 - validPct}%` }} />}
        </div>
        <div className="mt-2 flex flex-wrap gap-5 text-xs text-neutral-600">
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-500" />Вне групп дублей — {profile.valid_rows}</span>
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400" />В группах дублей — {duplicates}</span>
          <span>Лишних копий — {profile.redundant_rows ?? 0}</span>
        </div>
      </div>

      {duplicates === 0 ? (
        <div className="flex h-[270px] flex-col items-center justify-center px-8 text-center">
          <p className="font-medium text-green-700">Дубликаты не найдены</p>
          <p className="mt-2 text-sm text-neutral-500">Строки проверены по {uniquenessCheckLabel(profile)}.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table aria-label="Группы дубликатов" className="w-full min-w-[650px] text-left text-xs">
            <thead className="sticky top-0 bg-neutral-50 text-neutral-500"><tr><th className="px-3 py-2">Значения ключа</th><th className="px-3 py-2 text-right">Повторов</th><th className="px-3 py-2 text-right">Лишних</th><th className="px-3 py-2">Строки</th></tr></thead>
            <tbody>{profile.groups.map((group, index) => (
              <tr key={index} className="border-t border-neutral-100 text-neutral-700">
                <td className="px-3 py-2 font-medium">{Object.entries(group.key_values).map(([key, value]) => `${key}=${value}`).join(" · ")}</td>
                <td className="px-3 py-2 text-right font-mono">{group.occurrences}</td>
                <td className="px-3 py-2 text-right font-mono">{group.redundant_rows}</td>
                <td className="px-3 py-2">{group.row_numbers.join(", ")}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}
