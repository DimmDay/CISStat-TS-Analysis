"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import {
  HistogramDistributionChart,
  KdeDistributionChart,
  SamplingBadge,
  ScatterDistributionChart,
  type DistributionChartData,
} from "./DistributionCharts";

export interface DescriptiveStatsValues {
  mean: number;
  median: number;
  std: number;
  skewness: number | null;
  kurtosis: number | null;
  q1: number;
  q3: number;
  iqr: number;
  distribution_hint: string;
}

export interface DescriptiveColumnStats {
  name: string;
  non_null_count: number;
  stats: DescriptiveStatsValues | null;
}

export interface DescriptiveStatsResponse {
  columns: DescriptiveColumnStats[];
  min_non_null_for_stats: number;
}

type DescriptiveView = "table" | "histogram" | "kde" | "scatter";

interface EdaDescriptiveOverviewProps {
  profile: DescriptiveStatsResponse | null;
  activeFeature: string;
  loading: boolean;
  error: string | null;
  noDataset: boolean;
  refreshKey?: number;
}

const TABS: { id: DescriptiveView; label: string }[] = [
  { id: "table", label: "Таблица" },
  { id: "histogram", label: "Гистограмма" },
  { id: "kde", label: "KDE" },
  { id: "scatter", label: "Разброс" },
];

function formatStat(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const normalized = Object.is(value, -0) ? 0 : value;
  return normalized.toLocaleString("ru-RU", { maximumFractionDigits: 3 });
}

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить распределение (HTTP ${response.status})`;
}

export function EdaDescriptiveOverview({
  profile,
  activeFeature,
  loading,
  error,
  noDataset,
  refreshKey = 0,
}: EdaDescriptiveOverviewProps) {
  const [activeView, setActiveView] = useState<DescriptiveView>("table");
  const [distribution, setDistribution] = useState<DistributionChartData | null>(null);
  const [distributionCacheKey, setDistributionCacheKey] = useState<string | null>(null);
  const [distributionLoading, setDistributionLoading] = useState(false);
  const [distributionError, setDistributionError] = useState<string | null>(null);
  const requestKey = `${refreshKey}:${activeFeature}`;

  const selected = useMemo(
    () => profile?.columns.find((item) => item.name === activeFeature) ?? null,
    [profile, activeFeature],
  );

  useEffect(() => {
    if (
      activeView === "table" ||
      !profile ||
      !activeFeature ||
      distributionCacheKey === requestKey
    ) {
      return;
    }

    let active = true;
    setDistributionLoading(true);
    setDistributionError(null);
    void (async () => {
      try {
        const response = await fetch(
          sessionApiUrl(`/dataset/distribution?column=${encodeURIComponent(activeFeature)}`),
          { credentials: "include" },
        );
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: DistributionChartData = await response.json();
        if (active) {
          setDistribution(data);
          setDistributionCacheKey(requestKey);
        }
      } catch (caught) {
        if (active) {
          setDistributionError(
            caught instanceof Error ? caught.message : "Не удалось загрузить распределение",
          );
        }
      } finally {
        if (active) setDistributionLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeView, activeFeature, distributionCacheKey, profile, requestKey]);

  const distributionReady = distributionCacheKey === requestKey;

  if (loading) {
    return (
      <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">
        Рассчитываем описательные статистики…
      </div>
    );
  }
  if (error) {
    return (
      <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">
        {error}
      </div>
    );
  }
  if (noDataset) {
    return (
      <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">
        Загрузите датасет, чтобы рассчитать описательные статистики.
      </div>
    );
  }
  if (!profile || profile.columns.length === 0) {
    return (
      <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">
        В активном датасете нет числовых признаков — описательные статистики неприменимы.
      </div>
    );
  }

  return (
    <section className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white feed-scroll">
      <div className="border-b border-neutral-100 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-neutral-800">Профиль числовых признаков</h4>
            <p className="mt-1 text-xs text-neutral-500">
              Расчёт по полному текущему датасету после применённых преобразований, а не по превью строк.
            </p>
          </div>
          <span className="shrink-0 text-xs text-neutral-400">{profile.columns.length} признаков</span>
        </div>
        {selected?.stats && (
          <p className="mt-3 rounded bg-brand-light/60 px-3 py-2 text-xs text-neutral-700">
            <strong>{activeFeature}</strong>: {selected.stats.distribution_hint}; n={selected.non_null_count}
          </p>
        )}
      </div>

      <div className="flex gap-1 border-b border-neutral-100 px-4 pt-2" role="tablist" aria-label="Представления описательных статистик">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeView === tab.id}
            aria-pressed={activeView === tab.id}
            onClick={() => setActiveView(tab.id)}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              activeView === tab.id
                ? "border border-b-0 border-neutral-200 bg-white text-brand"
                : "text-neutral-500 hover:text-neutral-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeView === "table" ? (
        <div className="overflow-x-auto">
          <table aria-label="Описательные статистики по числовым признакам" className="w-full min-w-[980px] text-left text-xs">
            <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
              <tr>
                <th className="px-3 py-2">Признак</th>
                <th className="px-3 py-2 text-right">N</th>
                <th className="px-3 py-2 text-right">Mean</th>
                <th className="px-3 py-2 text-right">Median</th>
                <th className="px-3 py-2 text-right">Std</th>
                <th className="px-3 py-2 text-right">Q1</th>
                <th className="px-3 py-2 text-right">Q3</th>
                <th className="px-3 py-2 text-right">IQR</th>
                <th className="px-3 py-2 text-right">Skew</th>
                <th className="px-3 py-2 text-right">Kurtosis</th>
                <th className="px-3 py-2">Интерпретация</th>
              </tr>
            </thead>
            <tbody>
              {profile.columns.map((item) => (
                <tr
                  key={item.name}
                  className={`border-t border-neutral-100 text-neutral-700 ${item.name === activeFeature ? "bg-brand-light/30" : ""}`}
                >
                  <td className="px-3 py-2 font-medium text-neutral-800">{item.name}</td>
                  <td className="px-3 py-2 text-right font-mono">{item.non_null_count}</td>
                  {item.stats ? (
                    <>
                      <td className="px-3 py-2 text-right font-mono">{formatStat(item.stats.mean)}</td>
                      <td className="px-3 py-2 text-right font-mono">{formatStat(item.stats.median)}</td>
                      <td className="px-3 py-2 text-right font-mono">{formatStat(item.stats.std)}</td>
                      <td className="px-3 py-2 text-right font-mono">{formatStat(item.stats.q1)}</td>
                      <td className="px-3 py-2 text-right font-mono">{formatStat(item.stats.q3)}</td>
                      <td className="px-3 py-2 text-right font-mono">{formatStat(item.stats.iqr)}</td>
                      <td className="px-3 py-2 text-right font-mono">{formatStat(item.stats.skewness)}</td>
                      <td className="px-3 py-2 text-right font-mono">{formatStat(item.stats.kurtosis)}</td>
                      <td className="px-3 py-2">{item.stats.distribution_hint}</td>
                    </>
                  ) : (
                    <td colSpan={9} className="px-3 py-2 text-amber-700">
                      Недостаточно данных (n={item.non_null_count}, минимум {profile.min_non_null_for_stats})
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="p-4">
          <p className="mb-3 text-xs text-neutral-500">
            {activeView === "histogram"
              ? `Частотное распределение «${activeFeature}» по интервалам.`
              : activeView === "kde"
              ? `Сглаженная оценка плотности «${activeFeature}»; недоступна для константного или слишком короткого ряда.`
              : `Наблюдения «${activeFeature}» по позиции в очищенном ряде; экстремумы выделяются отдельно.`}
          </p>
          {(distributionLoading || !distributionReady) && !distributionError && (
            <div className="flex h-[250px] items-center justify-center text-sm text-neutral-400">Загрузка визуализации…</div>
          )}
          {distributionError && (
            <div role="alert" className="flex h-[250px] items-center justify-center px-8 text-center text-sm text-red-700">{distributionError}</div>
          )}
          {!distributionLoading && distributionReady && !distributionError && activeView === "histogram" && (
            <HistogramDistributionChart data={distribution} />
          )}
          {!distributionLoading && distributionReady && !distributionError && activeView === "kde" && (
            <KdeDistributionChart data={distribution} />
          )}
          {!distributionLoading && distributionReady && !distributionError && activeView === "scatter" && (
            <>
              <ScatterDistributionChart data={distribution} />
              <SamplingBadge data={distribution} />
            </>
          )}
        </div>
      )}
    </section>
  );
}
