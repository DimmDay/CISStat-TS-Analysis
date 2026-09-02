"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

export interface RangeProfileItem {
  column: string;
  rule_name: string;
  min_allowed: number | null;
  max_allowed: number | null;
  actual_min: number | null;
  actual_max: number | null;
  total_count: number;
  valid_count: number;
  invalid_count: number;
  invalid_pct: number | null;
  invalid_examples: number[];
}

export interface RangeProfileResponse {
  rule_source: "system" | "template" | "session" | "not_applicable";
  columns: RangeProfileItem[];
}

async function responseDetail(response: Response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить профиль диапазонов (HTTP ${response.status})`;
}

const valueLabel = (value: number | null, fallback: string) =>
  value === null ? fallback : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 }).format(value);

export function ValidationRangeOverview({ refreshKey = 0 }: { refreshKey?: number }) {
  const [profile, setProfile] = useState<RangeProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/range-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: RangeProfileResponse = await response.json();
        if (active) setProfile(data);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль диапазонов");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [refreshKey]);

  const totals = useMemo(() => ({
    valid: profile?.columns.reduce((sum, item) => sum + item.valid_count, 0) ?? 0,
    invalid: profile?.columns.reduce((sum, item) => sum + item.invalid_count, 0) ?? 0,
  }), [profile]);
  const total = totals.valid + totals.invalid;
  const validPct = total > 0 ? (totals.valid / total) * 100 : 0;

  if (loading) {
    return <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Загрузка профиля диапазонов…</div>;
  }
  if (error) {
    return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  }
  if (!profile || profile.columns.length === 0) {
    return (
      <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-600">
        Эталон диапазонов не задан. Выберите шаблон или добавьте min/max-правило в «Управлении правилами».
      </div>
    );
  }

  return (
    <section className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
      <div className="border-b border-neutral-100 p-4">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-semibold text-neutral-800">Соответствие допустимым границам</h4>
          <span className="text-xs text-neutral-400">{profile.columns.length} колонок</span>
        </div>
        <div
          role="img"
          aria-label={`В допустимом диапазоне: ${totals.valid}; нарушений: ${totals.invalid}`}
          className="mt-3 flex h-3 overflow-hidden rounded-full bg-neutral-100"
        >
          {totals.valid > 0 && <div className="bg-green-500" style={{ width: `${validPct}%` }} />}
          {totals.invalid > 0 && <div className="bg-amber-400" style={{ width: `${100 - validPct}%` }} />}
        </div>
        <div className="mt-2 flex gap-5 text-xs text-neutral-600">
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-500" />В диапазоне — {totals.valid}</span>
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400" />Нарушения — {totals.invalid}</span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table aria-label="Матрица диапазонов колонок" className="w-full min-w-[760px] text-left text-xs">
          <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
            <tr>
              <th className="px-3 py-2">Колонка</th>
              <th className="px-3 py-2">Фактический min / max</th>
              <th className="px-3 py-2">Допустимый min / max</th>
              <th className="px-3 py-2">Статус</th>
              <th className="px-3 py-2 text-right">Нарушения</th>
            </tr>
          </thead>
          <tbody>
            {profile.columns.map((item) => (
              <tr key={item.column} className="border-t border-neutral-100 text-neutral-700">
                <td className="px-3 py-2">
                  <span className="block font-medium text-neutral-800">{item.column}</span>
                  <span className="block max-w-[220px] truncate text-[11px] text-neutral-400" title={item.rule_name}>{item.rule_name}</span>
                </td>
                <td className="px-3 py-2 tabular-nums">{valueLabel(item.actual_min, "—")} / {valueLabel(item.actual_max, "—")}</td>
                <td className="px-3 py-2 tabular-nums">{valueLabel(item.min_allowed, "−∞")} / {valueLabel(item.max_allowed, "+∞")}</td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-1 font-medium ${item.invalid_count > 0 ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>
                    {item.invalid_count > 0 ? "Найдены проблемы" : "Соответствует"}
                  </span>
                </td>
                <td className="px-3 py-2 text-right font-mono">{item.invalid_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
