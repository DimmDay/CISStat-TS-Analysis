"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

export interface InclusionProfileItem {
  column: string;
  allowed_values: Array<string | number | boolean>;
  allowed_count: number;
  total_count: number;
  valid_count: number;
  invalid_count: number;
  invalid_pct: number | null;
  invalid_values: Array<{ value: string; count: number }>;
  default_value: string | number | boolean | null;
  default_valid: boolean;
  supported_actions: string[];
}

export interface InclusionProfileResponse {
  rule_source: "system" | "template" | "session" | "not_applicable";
  columns: InclusionProfileItem[];
}

async function responseDetail(response: Response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch { /* нейтральная ошибка ниже */ }
  return `Не удалось загрузить профиль допустимых наборов (HTTP ${response.status})`;
}

const listLabel = (values: Array<string | number | boolean>, limit = 6) => {
  const shown = values.slice(0, limit).map(String).join(", ");
  return values.length > limit ? `${shown} … (+${values.length - limit})` : shown;
};

export function ValidationInclusionOverview({ refreshKey = 0 }: { refreshKey?: number }) {
  const [profile, setProfile] = useState<InclusionProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/inclusion-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: InclusionProfileResponse = await response.json();
        if (active) setProfile(data);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль допустимых наборов");
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

  if (loading) return <p className="text-sm text-neutral-400">Загрузка профиля допустимых наборов…</p>;
  if (error) return <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!profile || profile.columns.length === 0) {
    return (
      <div className="rounded bg-amber-50 px-3 py-3 text-sm text-amber-800">
        <p className="font-medium">Эталон допустимых наборов не задан.</p>
        <p className="mt-1 text-xs">Выберите предметный шаблон или добавьте наборы в «Управлении правилами». Система не выводит справочник из проверяемых значений.</p>
      </div>
    );
  }

  return (
    <section className="space-y-3">
      <div>
        <div className="mb-1 flex justify-between text-xs text-neutral-500">
          <span>Соответствие допустимым наборам</span><span>{profile.columns.length} правил</span>
        </div>
        <div role="img" aria-label={`Допустимых значений: ${totals.valid}; нарушений: ${totals.invalid}`} className="flex h-3 overflow-hidden rounded-full bg-neutral-100">
          <div className="bg-green-500" style={{ width: `${total ? totals.valid / total * 100 : 0}%` }} />
          <div className="bg-amber-400" style={{ width: `${total ? totals.invalid / total * 100 : 0}%` }} />
        </div>
        <div className="mt-1 flex gap-4 text-xs text-neutral-600"><span>● Допустимые {totals.valid}</span><span className="text-amber-700">● Нарушения {totals.invalid}</span></div>
      </div>
      <div className="overflow-x-auto rounded border border-neutral-200">
        <table aria-label="Матрица принадлежности к наборам" className="w-full text-left text-xs">
          <thead className="bg-neutral-50 text-neutral-500"><tr><th className="px-3 py-2">Колонка</th><th className="px-3 py-2">Допустимый набор</th><th className="px-3 py-2">Недопустимые значения</th><th className="px-3 py-2">Статус</th><th className="px-3 py-2 text-right">Нарушения</th></tr></thead>
          <tbody>{profile.columns.map((item) => (
            <tr key={item.column} className="border-t border-neutral-100 text-neutral-700">
              <td className="px-3 py-2 font-medium text-neutral-800">{item.column}</td>
              <td className="max-w-[260px] px-3 py-2" title={item.allowed_values.map(String).join(", ")}>{listLabel(item.allowed_values)}</td>
              <td className="px-3 py-2 text-amber-700">{item.invalid_values.length ? item.invalid_values.map((entry) => `${entry.value} × ${entry.count}`).join(", ") : "—"}</td>
              <td className="px-3 py-2"><span className={`rounded px-2 py-1 font-medium ${item.invalid_count ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>{item.invalid_count ? "Найдены проблемы" : "Соответствует"}</span></td>
              <td className="px-3 py-2 text-right font-mono">{item.invalid_count}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}
