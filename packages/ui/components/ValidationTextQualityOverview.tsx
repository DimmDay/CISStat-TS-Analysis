"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

export interface TextQualityIssueCounts {
  garbage: number;
  empty: number;
  too_short: number;
  too_long: number;
  whitespace: number;
  pattern: number;
}

export interface TextQualityProfileItem {
  column: string;
  total_count: number;
  valid_count: number;
  invalid_count: number;
  invalid_pct: number | null;
  min_length: number;
  max_length: number;
  issue_counts: TextQualityIssueCounts;
  invalid_examples: string[];
  supported_actions: string[];
}

export interface TextQualityProfileResponse {
  rule_source: "system" | "template" | "session" | "not_applicable";
  columns: TextQualityProfileItem[];
}

async function responseDetail(response: Response) {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось загрузить профиль целостности текста (HTTP ${response.status})`;
}

const ISSUE_LABELS: Array<[keyof TextQualityIssueCounts, string]> = [
  ["garbage", "Мусор"], ["empty", "Пустые"], ["too_short", "Короткие"],
  ["too_long", "Длинные"], ["whitespace", "Пробелы"], ["pattern", "Шаблон"],
];

const issueSummary = (counts: TextQualityIssueCounts) => {
  const items = ISSUE_LABELS.filter(([key]) => counts[key] > 0).map(([key, label]) => `${label}: ${counts[key]}`);
  return items.length ? items.join("; ") : "—";
};

export function ValidationTextQualityOverview({ refreshKey = 0 }: { refreshKey?: number }) {
  const [profile, setProfile] = useState<TextQualityProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(null);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/text-quality-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: TextQualityProfileResponse = await response.json();
        if (active) setProfile(data);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль целостности текста");
      } finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, [refreshKey]);

  const totals = useMemo(() => ({
    valid: profile?.columns.reduce((sum, item) => sum + item.valid_count, 0) ?? 0,
    invalid: profile?.columns.reduce((sum, item) => sum + item.invalid_count, 0) ?? 0,
  }), [profile]);
  const total = totals.valid + totals.invalid;

  if (loading) return <p className="text-sm text-neutral-400">Загрузка профиля целостности текста…</p>;
  if (error) return <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!profile || profile.columns.length === 0) {
    return <div className="rounded bg-neutral-50 px-3 py-3 text-sm text-neutral-600"><p className="font-medium">В датасете нет текстовых колонок.</p><p className="mt-1 text-xs">Системная проверка неприменима и не влияет на DQ Score.</p></div>;
  }

  return (
    <section className="space-y-3">
      <div>
        <div className="mb-1 flex justify-between text-xs text-neutral-500"><span>Чистота текстовых значений</span><span>{profile.columns.length} колонок</span></div>
        <div role="img" aria-label={`Чистых значений: ${totals.valid}; нарушений: ${totals.invalid}`} className="flex h-3 overflow-hidden rounded-full bg-neutral-100">
          <div className="bg-green-500" style={{ width: `${total ? totals.valid / total * 100 : 0}%` }} />
          <div className="bg-amber-400" style={{ width: `${total ? totals.invalid / total * 100 : 0}%` }} />
        </div>
        <div className="mt-1 flex gap-4 text-xs text-neutral-600"><span>● Чистые {totals.valid}</span><span className="text-amber-700">● Нарушения {totals.invalid}</span></div>
      </div>
      <div className="overflow-x-auto rounded border border-neutral-200">
        <table aria-label="Матрица целостности текста" className="w-full text-left text-xs">
          <thead className="bg-neutral-50 text-neutral-500"><tr><th className="px-3 py-2">Колонка</th><th className="px-3 py-2">Правило длины</th><th className="px-3 py-2">Типы нарушений</th><th className="px-3 py-2">Примеры</th><th className="px-3 py-2">Статус</th><th className="px-3 py-2 text-right">Нарушения</th></tr></thead>
          <tbody>{profile.columns.map((item) => (
            <tr key={item.column} className="border-t border-neutral-100 text-neutral-700">
              <td className="px-3 py-2 font-mono font-medium text-neutral-800">{item.column}</td>
              <td className="px-3 py-2">{item.min_length}–{item.max_length} символов</td>
              <td className="px-3 py-2">{issueSummary(item.issue_counts)}</td>
              <td className="max-w-[220px] truncate px-3 py-2" title={item.invalid_examples.join(" | ")}>{item.invalid_examples.join(" | ") || "—"}</td>
              <td className="px-3 py-2"><span className={`rounded px-2 py-1 font-medium ${item.invalid_count ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>{item.invalid_count ? "Найдены проблемы" : "Соответствует"}</span></td>
              <td className="px-3 py-2 text-right font-mono">{item.invalid_count}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}
