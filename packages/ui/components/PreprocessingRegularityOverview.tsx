"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import { RegularityIntervalsChart, RegularityTimelineChart } from "./PreprocessingRegularityVisualizations";
// Task 97.4 (Этап 4, spec_max_graf_fix.md §8): тиражирование раскрытия
// графиков. Корень Обзора: relative всегда (правка A), overflow переключается
// по expandedChartId (правка C); графические представления (чарт-блоки из
// PreprocessingRegularityVisualizations) обёрнуты в ExpandableChartPanel
// на уровне ИСПОЛЬЗОВАНИЯ (§7.2), таблица групп — без панели.
// detail_level не заказан (Этап 5 опционален) — раскрытие чисто визуальное.
import { ExpandableChartPanel } from "./ExpandableChartPanel";
import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import { useExpandableChartState } from "../hooks/useExpandableChart";

export interface RegularityGapExample {
  previous_date: string;
  current_date: string;
  missing_periods: number;
}

export interface RegularityGroup {
  group: string;
  observations: number;
  inferred_frequency: string | null;
  modal_interval: string | null;
  gap_count: number;
  missing_period_count: number;
  duplicate_count: number;
  sort_violations: number;
  gap_examples: RegularityGapExample[];
}

export interface RegularityProfile {
  applicable: boolean;
  applicability_message: string | null;
  date_column: string | null;
  entity_column: string | null;
  target_frequency: string | null;
  detected_frequency: string | null;
  gap_threshold_multiplier: number;
  is_sorted: boolean;
  sort_violations: number;
  invalid_date_count: number;
  duplicate_count: number;
  gap_count: number;
  missing_period_count: number;
  total_violations: number;
  groups: RegularityGroup[];
  supported_actions: string[];
}

export interface RegularityProfileResponse {
  mode: "auto" | "enabled" | "disabled";
  status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null;
  profile: RegularityProfile;
}

async function responseDetail(response: Response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить профиль регулярности (HTTP ${response.status})`;
}

export function PreprocessingRegularityOverview({ refreshKey = 0 }: { refreshKey?: number }) {
  return (
    <ExpandableChartsProvider>
      <PreprocessingRegularityOverviewInner refreshKey={refreshKey} />
    </ExpandableChartsProvider>
  );
}

function PreprocessingRegularityOverviewInner({ refreshKey = 0 }: { refreshKey?: number }) {
  const [data, setData] = useState<RegularityProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"table" | "intervals" | "timeline">("table");
  const { expandedChartId } = useExpandableChartState();

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/preprocessing/regularity-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const json: RegularityProfileResponse = await response.json();
        if (active) setData(json);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль регулярности");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [refreshKey]);

  if (loading) {
    return <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Загрузка профиля регулярности…</div>;
  }
  if (error) {
    return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  }
  if (!data || !data.profile.applicable) {
    return (
      <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-600">
        {data?.profile.applicability_message ?? "Не удалось определить временную колонку — проверка регулярности неприменима."}
      </div>
    );
  }
  if (data.status === "skipped") {
    return (
      <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">
        {data.status_reason === "disabled"
          ? "Остановка «Регулярность» отключена аналитиком и не участвует в прогрессе."
          : "Проверка регулярности не требуется для этого датасета."}
      </div>
    );
  }

  const profile = data.profile;

  return (
    <section className={`relative flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white feed-scroll ${expandedChartId ? "overflow-hidden" : "overflow-y-auto"}`}>
      <div className="shrink-0 border-b border-neutral-100 p-4">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-semibold text-neutral-800">Временная ось: {profile.date_column}{profile.entity_column ? ` · сущность: ${profile.entity_column}` : ""}</h4>
          <span className="text-xs text-neutral-400">
            Частота: {profile.target_frequency ?? "не определена"} {profile.detected_frequency && profile.detected_frequency !== profile.target_frequency ? `(обнаружена: ${profile.detected_frequency})` : ""}
          </span>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-neutral-600">
          <span>Разрывов — {profile.gap_count} ({profile.missing_period_count} пропущенных периодов)</span>
          <span>Дублей дат — {profile.duplicate_count}</span>
          <span>Нарушений сортировки — {profile.sort_violations}</span>
          {profile.invalid_date_count > 0 && <span className="font-medium text-red-600">Некорректных дат — {profile.invalid_date_count}</span>}
        </div>
      </div>

      <div className="flex shrink-0 gap-1 border-b border-neutral-100 px-4 pt-2">
        {(
          [
            { id: "table", label: "Таблица" },
            { id: "intervals", label: "Интервалы" },
            { id: "timeline", label: "Таймлайн" },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveView(tab.id)}
            aria-pressed={activeView === tab.id}
            className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
              activeView === tab.id
                ? "bg-white text-brand border border-b-0 border-neutral-200"
                : "text-neutral-500 hover:text-neutral-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeView === "table" && (
        <div className="shrink-0 overflow-x-auto">
          <table aria-label="Регулярность по группам" className="w-full min-w-[760px] text-left text-xs">
            <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
              <tr>
                <th className="px-3 py-2">Группа</th>
                <th className="px-3 py-2 text-right">Наблюдений</th>
                <th className="px-3 py-2">Частота</th>
                <th className="px-3 py-2 text-right">Разрывов</th>
                <th className="px-3 py-2 text-right">Дублей</th>
                <th className="px-3 py-2">Статус</th>
              </tr>
            </thead>
            <tbody>
              {profile.groups.map((item) => {
                const hasIssues = item.gap_count + item.duplicate_count + item.sort_violations > 0;
                return (
                  <tr key={item.group} className="border-t border-neutral-100 text-neutral-700">
                    <td className="px-3 py-2 font-medium text-neutral-800">{item.group}</td>
                    <td className="px-3 py-2 text-right font-mono">{item.observations}</td>
                    <td className="px-3 py-2 text-neutral-600">{item.inferred_frequency ?? "—"}</td>
                    <td className="px-3 py-2 text-right font-mono">{item.gap_count}</td>
                    <td className="px-3 py-2 text-right font-mono">{item.duplicate_count}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-2 py-1 font-medium ${hasIssues ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>
                        {hasIssues ? "Найдены проблемы" : "Пройдено"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {activeView === "intervals" && <ExpandableChartPanel chartId="regularity-intervals" title="Интервалы между наблюдениями"><RegularityIntervalsChart refreshKey={refreshKey} /></ExpandableChartPanel>}
      {activeView === "timeline" && <ExpandableChartPanel chartId="regularity-timeline" title="Таймлайн наблюдений"><RegularityTimelineChart refreshKey={refreshKey} /></ExpandableChartPanel>}
    </section>
  );
}
