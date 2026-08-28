"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

export interface OutlierBounds {
  lower: number;
  upper: number;
}

export interface OutlierProfileItem {
  column: string;
  sample_size: number;
  outlier_count: number;
  outlier_pct: number | null;
  recommended_method: "iqr" | "zscore" | "mad" | "percentile";
  bounds: OutlierBounds | null;
  outlier_examples: number[];
  insufficient_sample: boolean;
}

export interface OutlierProfileResponse {
  rule_source: "system" | "not_applicable";
  mode: "auto" | "enabled" | "disabled";
  status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null;
  method: "iqr" | "zscore" | "mad" | "percentile";
  total_rows: number;
  total_numeric_columns: number;
  total_outliers: number;
  outlier_rate_pct: number | null;
  affected_columns: string[];
  columns: OutlierProfileItem[];
}

const METHOD_LABEL: Record<OutlierProfileItem["recommended_method"], string> = {
  iqr: "IQR (межквартильный размах)",
  zscore: "Z-score",
  mad: "Modified Z-score (MAD)",
  percentile: "Процентильный",
};

async function responseDetail(response: Response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить профиль выбросов (HTTP ${response.status})`;
}

const pctLabel = (value: number | null) => (value === null ? "—" : `${value.toFixed(1)}%`);

export function PreprocessingOutliersOverview({
  refreshKey = 0,
  method = "iqr",
}: {
  refreshKey?: number;
  method?: OutlierProfileItem["recommended_method"];
}) {
  const [profile, setProfile] = useState<OutlierProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const response = await fetch(
          sessionApiUrl(`/dataset/outlier-profile?method=${method}`),
          { credentials: "include" }
        );
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: OutlierProfileResponse = await response.json();
        if (active) setProfile(data);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль выбросов");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [refreshKey, method]);

  if (loading) {
    return <div className="flex h-[420px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Загрузка профиля выбросов…</div>;
  }
  if (error) {
    return <div role="alert" className="flex h-[420px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  }
  if (!profile || profile.columns.length === 0) {
    return (
      <div className="flex h-[420px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-600">
        В активном датасете нет числовых колонок — проверка выбросов неприменима.
      </div>
    );
  }
  if (profile.status === "skipped") {
    return (
      <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">
        {profile.status_reason === "disabled"
          ? "Остановка «Выбросы» отключена аналитиком и не участвует в прогрессе."
          : "Проверка выбросов не требуется для этого датасета."}
      </div>
    );
  }

  return (
    <section className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
      <div className="border-b border-neutral-100 p-4">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-semibold text-neutral-800">Выбросы по числовым колонкам</h4>
          <span className="text-xs text-neutral-400">{profile.columns.length} числовых колонок · метод: {METHOD_LABEL[profile.method]}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-neutral-600">
          <span>Выбросов всего — {profile.total_outliers} ({pctLabel(profile.outlier_rate_pct)})</span>
          {profile.affected_columns.length > 0 && (
            <span>Затронутые колонки — {profile.affected_columns.join(", ")}</span>
          )}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table aria-label="Выбросы по числовым колонкам" className="w-full min-w-[760px] text-left text-xs">
          <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
            <tr>
              <th className="px-3 py-2">Колонка</th>
              <th className="px-3 py-2 text-right">Выбросов</th>
              <th className="px-3 py-2">Границы метода</th>
              <th className="px-3 py-2">Статус</th>
              <th className="px-3 py-2">Рекомендованный метод</th>
            </tr>
          </thead>
          <tbody>
            {profile.columns.map((item) => (
              <tr key={item.column} className="border-t border-neutral-100 text-neutral-700">
                <td className="px-3 py-2">
                  <span className="block font-medium text-neutral-800">{item.column}</span>
                  {item.outlier_examples.length > 0 && (
                    <span className="block max-w-[220px] truncate text-[11px] text-neutral-400">
                      Строки: {item.outlier_examples.join(", ")}
                    </span>
                  )}
                  {item.insufficient_sample && (
                    <span className="block text-[11px] text-amber-700">Недостаточно наблюдений (&lt;10)</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right font-mono">{item.outlier_count} ({pctLabel(item.outlier_pct)})</td>
                <td className="px-3 py-2 text-neutral-600">
                  {item.bounds ? `${item.bounds.lower.toFixed(2)} … ${item.bounds.upper.toFixed(2)}` : "—"}
                </td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-1 font-medium ${item.outlier_count > 0 ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>
                    {item.outlier_count > 0 ? "Найдены проблемы" : "Пройдено"}
                  </span>
                </td>
                <td className="px-3 py-2 text-neutral-600">{METHOD_LABEL[item.recommended_method]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
