"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import {
  HistogramDistributionChart,
  KdeDistributionChart,
  SamplingBadge,
  ScatterDistributionChart,
  type DistributionChartData,
} from "./DistributionCharts";
// Task 97.4 (Этап 4, spec_max_graf_fix.md §8): тиражирование раскрытия
// графиков. Корень Обзора: relative всегда (правка A), overflow переключается
// по expandedChartId (правка C); контейнер визуализации (чарт-блоки из
// DistributionCharts) обёрнут в ExpandableChartPanel на уровне ИСПОЛЬЗОВАНИЯ
// (§7.2), таблица статистик — без панели. detail_level не заказан (Этап 5
// опционален) — раскрытие чисто визуальное.
import { ExpandableChartPanel } from "./ExpandableChartPanel";
import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import { useExpandableChartState } from "../hooks/useExpandableChart";
// PGV-11 (spec_passport_graphics_visual.md §13 «Export EDA/IH/tasks»):
// «Скачать PNG» представлений Обзора (таблица статистик + scatter/
// histogram/kde — отдельные view со своей frozen геометрией; AC01).
import { VisualExportButton } from "./VisualExportButton";
import { serializeChartSvgSafe } from "../lib/serializeChartSvg";

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

export function EdaDescriptiveOverview(props: EdaDescriptiveOverviewProps) {
  return (
    <ExpandableChartsProvider>
      <EdaDescriptiveOverviewInner {...props} />
    </ExpandableChartsProvider>
  );
}

function EdaDescriptiveOverviewInner({
  profile,
  activeFeature,
  loading,
  error,
  noDataset,
  refreshKey = 0,
}: EdaDescriptiveOverviewProps) {
  const [activeView, setActiveView] = useState<DescriptiveView>("table");
  // PGV-11: ref СВОЕЙ поверхности рендера (frozen геометрия активного
  // представления -- не первый SVG документа); объявлен ДО ранних
  // возвратов (урок PGV-10: hooks после return запрещены).
  const exportSectionRef = useRef<HTMLElement>(null);
  const { expandedChartId } = useExpandableChartState();
  const [distribution, setDistribution] = useState<DistributionChartData | null>(null);
  const [distributionCacheKey, setDistributionCacheKey] = useState<string | null>(null);
  const [distributionLoading, setDistributionLoading] = useState(false);
  const [distributionError, setDistributionError] = useState<string | null>(null);
  // EDA-RECALC-COMPENSATION ④ (RCH-3): mount-scoped префикс ревизии.
  // Источник бампа refreshKey в TsAnalysisEDA больше не кнопка (постоянные
  // кнопки «Пересчитать…» удалены), поэтому «свежее пространство URL на
  // каждое монтирование» гарантирует отдельный идентификатор: без него
  // revision=0:<feature> после перемонтирования совпал бы с прежним
  // монтированием и теоретический HTTP-кэш промежуточных слоёв мог бы
  // отдать график, рассчитанный по устаревшей ревизии данных. useId НЕ
  // подходит: его формат содержит двоеточия, а контракт revision —
  // три двоеточие-разделённых сегмента <mount>:<refreshKey>:<feature>.
  const mountScope = useState(() => Math.random().toString(36).slice(2, 10))[0];
  const requestKey = `${mountScope}:${refreshKey}:${activeFeature}`;

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
        // Волна 3 plan_review_charts.md (Task RCH-3): канон OUTL-1 -- ревизия
        // включается в query как cache-buster. Эффект и так перезапускается
        // requestKey-гвардом, но теоретический HTTP-кэш промежуточных слоёв
        // мог отдать устаревший payload при повторном запросе с той же парой
        // column+refreshKey; revision=${requestKey} делает URL чистой функцией
        // ключа эффекта. EDA-RECALC-COMPENSATION ④: requestKey теперь
        // <mount-scope>:<refreshKey>:<feature> -- бампы внутри монтирования
        // (фокус-рефетч/подтверждение даты/«Повторить») меняют средний
        // сегмент, перемонтирование модуля порождает новый префикс.
        // Неизвестный query-параметр FastAPI игнорирует -- бэкенд не меняется.
        const response = await fetch(
          sessionApiUrl(`/dataset/distribution?column=${encodeURIComponent(activeFeature)}&revision=${requestKey}`),
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
    <section ref={exportSectionRef} className={`relative flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white feed-scroll ${expandedChartId ? "overflow-hidden" : "overflow-y-auto"}`}>
      <div className="shrink-0 border-b border-neutral-100 p-4">
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
        {/* Task w/n-4: переключатели представлений — бейдж-паттерн «Обзора»
            «Предобработки» (эталон «Генерации признаков»): tablist внутри шапки,
            контейнер mt-3 flex flex-wrap gap-2, бейджи rounded-full px-3 py-1;
            aria-selected без aria-pressed (прецедент Task w/n-3). */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <VisualExportButton
            viewId={
              activeView === "table"
                ? "eda.descriptive.stats"
                : activeView === "histogram"
                  ? "eda.descriptive.distribution.histogram"
                  : activeView === "kde"
                    ? "eda.descriptive.distribution.kde"
                    : "eda.descriptive.distribution.scatter"
            }
            label="Скачать PNG: активное представление"
            compact
            getScreenSvg={
              activeView === "table"
                ? undefined
                : () => serializeChartSvgSafe(() => exportSectionRef.current)
            }
          />
        </div>
        <div role="tablist" aria-label="Представления описательных статистик" className="mt-3 flex flex-wrap gap-2">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeView === tab.id}
              onClick={() => setActiveView(tab.id)}
              className={`rounded-full border px-3 py-1 text-xs ${
                activeView === tab.id
                  ? "border-neutral-300 bg-neutral-200 text-neutral-800"
                  : "border-neutral-200 bg-neutral-50 text-neutral-500 hover:bg-neutral-100"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {activeView === "table" ? (
        <div className="shrink-0 overflow-x-auto">
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
        <ExpandableChartPanel chartId="descriptive-visualization" title="Визуализация распределения">
        <div data-testid="descriptive-visualization" className="flex min-h-0 flex-1 flex-col p-4">
          <p className="mb-3 shrink-0 text-xs text-neutral-500">
            {activeView === "histogram"
              ? `Частотное распределение «${activeFeature}» по интервалам.`
              : activeView === "kde"
              ? `Сглаженная оценка плотности «${activeFeature}»; недоступна для константного или слишком короткого ряда.`
              : `Наблюдения «${activeFeature}» по позиции в очищенном ряде; экстремумы выделяются отдельно.`}
          </p>
          {(distributionLoading || !distributionReady) && !distributionError && (
            <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-neutral-400">Загрузка визуализации…</div>
          )}
          {distributionError && (
            <div role="alert" className="flex min-h-0 flex-1 items-center justify-center px-8 text-center text-sm text-red-700">{distributionError}</div>
          )}
          {!distributionLoading && distributionReady && !distributionError && activeView === "histogram" && (
            <HistogramDistributionChart data={distribution} className="min-h-0 flex-1" />
          )}
          {!distributionLoading && distributionReady && !distributionError && activeView === "kde" && (
            <KdeDistributionChart data={distribution} className="min-h-0 flex-1" />
          )}
          {!distributionLoading && distributionReady && !distributionError && activeView === "scatter" && (
            <>
              <ScatterDistributionChart data={distribution} className="min-h-0 flex-1" />
              <div className="shrink-0"><SamplingBadge data={distribution} /></div>
            </>
          )}
        </div>
        </ExpandableChartPanel>
      )}
    </section>
  );
}
