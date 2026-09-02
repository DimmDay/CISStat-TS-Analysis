"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";


export interface ConsistencyProfileItem {
  rule_index: number;
  rule_name: string;
  rule_type: string;
  description: string | null;
  columns: string[];
  time_column: string | null;
  group_column: string | null;
  applicable: boolean;
  applicability_message: string | null;
  checked_count: number;
  valid_count: number;
  invalid_count: number | null;
  affected_rows: number;
  invalid_examples: string[];
  supported_actions: string[];
}

export interface ConsistencyProfileResponse {
  rule_source: "system" | "template" | "session" | "not_applicable";
  rules: ConsistencyProfileItem[];
}


async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Ответ без JSON получает нейтральное сообщение ниже.
  }
  return `Не удалось загрузить профиль (HTTP ${response.status})`;
}


const ruleColumns = (item: ConsistencyProfileItem) => {
  const base = item.columns.join(" ↔ ") || "—";
  return item.group_column ? `${base} · группы: ${item.group_column}` : base;
};


export function ValidationConsistencyOverview({ refreshKey = 0 }: { refreshKey?: number }) {
  const [profile, setProfile] = useState<ConsistencyProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/consistency-profile"), {
          credentials: "include",
        });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: ConsistencyProfileResponse = await response.json();
        if (active) setProfile(data);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль логики");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [refreshKey]);

  const applicable = useMemo(
    () => profile?.rules.filter((item) => item.applicable) ?? [],
    [profile]
  );
  const totals = useMemo(() => ({
    valid: applicable.reduce((sum, item) => sum + item.valid_count, 0),
    invalid: applicable.reduce((sum, item) => sum + (item.invalid_count ?? 0), 0),
  }), [applicable]);
  const total = totals.valid + totals.invalid;
  const validPct = total > 0 ? (totals.valid / total) * 100 : 0;

  if (loading) {
    return <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Загрузка профиля логики и хронологии…</div>;
  }
  if (error) {
    return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  }
  if (!profile || applicable.length === 0) {
    return (
      <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-600">
        Эталон логики и хронологии не задан. Базовая хронология определяется системой при наличии временной колонки; предметные сравнения добавьте в «Управлении правилами».
      </div>
    );
  }

  return (
    <section className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
      <div className="border-b border-neutral-100 p-4">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-semibold text-neutral-800">Соблюдение правил</h4>
          <span className="text-xs text-neutral-400">{applicable.length} применимых правил</span>
        </div>
        <div
          role="img"
          aria-label={`Проверок соблюдено: ${totals.valid}; нарушений: ${totals.invalid}`}
          className="mt-3 flex h-3 overflow-hidden rounded-full bg-neutral-100"
        >
          {totals.valid > 0 && <div className="bg-green-500" style={{ width: `${validPct}%` }} />}
          {totals.invalid > 0 && <div className="bg-amber-400" style={{ width: `${100 - validPct}%` }} />}
        </div>
        <div className="mt-2 flex gap-5 text-xs text-neutral-600">
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-500" />Соблюдено — {totals.valid}</span>
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400" />Нарушения — {totals.invalid}</span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table aria-label="Матрица логики и хронологии" className="w-full min-w-[780px] text-left text-xs">
          <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
            <tr>
              <th className="px-3 py-2">Правило</th>
              <th className="px-3 py-2">Тип</th>
              <th className="px-3 py-2">Колонки</th>
              <th className="px-3 py-2">Статус</th>
              <th className="px-3 py-2 text-right">Нарушения</th>
            </tr>
          </thead>
          <tbody>
            {profile.rules.map((item) => (
              <tr key={item.rule_index} className="border-t border-neutral-100 text-neutral-700">
                <td className="px-3 py-2">
                  <span className="block font-medium text-neutral-800">{item.rule_name}</span>
                  {item.description && <span className="block max-w-[240px] truncate text-[11px] text-neutral-400" title={item.description}>{item.description}</span>}
                </td>
                <td className="px-3 py-2 font-mono text-[11px]">{item.rule_type}</td>
                <td className="px-3 py-2">{ruleColumns(item)}</td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-1 font-medium ${
                    !item.applicable
                      ? "bg-neutral-100 text-neutral-600"
                      : (item.invalid_count ?? 0) > 0
                        ? "bg-amber-50 text-amber-700"
                        : "bg-green-50 text-green-700"
                  }`}>
                    {!item.applicable ? "Не применимо" : (item.invalid_count ?? 0) > 0 ? "Найдены проблемы" : "Соответствует"}
                  </span>
                  {!item.applicable && item.applicability_message && (
                    <span className="mt-1 block max-w-[190px] text-[10px] text-neutral-400">{item.applicability_message}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right font-mono">{item.invalid_count ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
