"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import { MissingMatrixChart, MissingCorrelationChart, MissingBoxplotChart } from "./PreprocessingMissingVisualizations";
// Task 97.4 (Этап 4, spec_max_graf_fix.md §8): тиражирование раскрытия
// графиков. Корень Обзора: relative всегда (правка A), overflow переключается
// по expandedChartId (правка C); чарт-блоки из PreprocessingMissingVisualizations
// обёрнуты в ExpandableChartPanel на уровне ИСПОЛЬЗОВАНИЯ (§7.2), таблица
// колонок и прогресс-бар полноты — без панели. detail_level не заказан
// (Этап 5 опционален) — раскрытие чисто визуальное.
import { ExpandableChartPanel } from "./ExpandableChartPanel";
import { ExpandableChartsProvider } from "./ExpandableChartsProvider";
import { useExpandableChartState } from "../hooks/useExpandableChart";

export interface MissingProfileItem {
  column: string;
  dtype: string;
  semantic: "numeric" | "datetime" | "categorical" | "text";
  total_count: number;
  missing_count: number;
  non_missing_count: number;
  missing_pct: number | null;
  recommended_strategy: "none" | "drop_rows" | "median_mode" | "mean_mode" | "constant" | "interpolate" | "flag";
  missing_examples: number[];
}

export interface MissingRowHistogramItem {
  missing_in_row: number;
  row_count: number;
}

export interface MissingProfileResponse {
  rule_source: "system" | "not_applicable";
  // Режим остановки и производный статус (Task 47, применено к
  // «Предобработке»): mode -- что выбрал аналитик; status -- честный
  // результат с учётом режима ("skipped" при disabled или when нет
  // колонок); status_reason различает эти два случая skipped.
  mode: "auto" | "enabled" | "disabled";
  status: "done" | "warning" | "pending" | "skipped";
  status_reason: "not_required" | "disabled" | null;
  total_rows: number;
  total_columns: number;
  total_missing: number;
  missing_rate_pct: number | null;
  rows_with_missing: number;
  rows_with_missing_pct: number | null;
  empty_rows: number;
  columns: MissingProfileItem[];
  row_histogram: MissingRowHistogramItem[];
}

const STRATEGY_LABEL: Record<MissingProfileItem["recommended_strategy"], string> = {
  none: "—",
  drop_rows: "Удалить строки",
  median_mode: "Заполнить медианой/модой",
  mean_mode: "Заполнить средним/модой",
  constant: "Заполнить нулём/Unknown",
  interpolate: "Линейная интерполяция",
  flag: "Добавить флаг пропуска",
};

async function responseDetail(response: Response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить профиль пропусков (HTTP ${response.status})`;
}

const pctLabel = (value: number | null) => (value === null ? "—" : `${value.toFixed(1)}%`);

export function PreprocessingMissingOverview({ refreshKey = 0 }: { refreshKey?: number }) {
  return (
    <ExpandableChartsProvider>
      <PreprocessingMissingOverviewInner refreshKey={refreshKey} />
    </ExpandableChartsProvider>
  );
}

function PreprocessingMissingOverviewInner({ refreshKey = 0 }: { refreshKey?: number }) {
  const [profile, setProfile] = useState<MissingProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"table" | "matrix" | "correlation" | "boxplot">("table");
  const { expandedChartId } = useExpandableChartState();

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/missing-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: MissingProfileResponse = await response.json();
        if (active) setProfile(data);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль пропусков");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [refreshKey]);

  const totals = useMemo(() => {
    const complete = profile ? profile.total_rows * profile.total_columns - profile.total_missing : 0;
    return { complete, missing: profile?.total_missing ?? 0 };
  }, [profile]);
  const totalCells = totals.complete + totals.missing;
  const completePct = totalCells > 0 ? (totals.complete / totalCells) * 100 : 0;

  if (loading) {
    return <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Загрузка профиля пропусков…</div>;
  }
  if (error) {
    return <div role="alert" className="flex h-[468px] items-center justify-center rounded-lg bg-red-50 px-8 text-center text-sm text-red-700">{error}</div>;
  }
  if (!profile || profile.columns.length === 0) {
    return (
      <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-600">
        В активном датасете нет ни одной колонки — проверка пропусков неприменима.
      </div>
    );
  }
  if (profile.status === "skipped") {
    return (
      <div role="status" className="flex h-[468px] items-center justify-center rounded-lg bg-neutral-50 px-8 text-center text-sm text-neutral-600">
        {profile.status_reason === "disabled"
          ? "Остановка «Пропуски» отключена аналитиком и не участвует в прогрессе."
          : "Проверка пропусков не требуется для этого датасета."}
      </div>
    );
  }

  return (
    <section className={`relative flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white feed-scroll ${expandedChartId ? "overflow-hidden" : "overflow-y-auto"}`}>
      <div className="shrink-0 border-b border-neutral-100 p-4">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-semibold text-neutral-800">Полнота данных</h4>
          <span className="text-xs text-neutral-400">{profile.columns.length} колонок · {profile.total_rows} строк</span>
        </div>
        <div
          role="img"
          aria-label={`Заполнено ячеек: ${totals.complete}; пропусков: ${totals.missing}`}
          className="mt-3 flex h-3 overflow-hidden rounded-full bg-neutral-100"
        >
          {totals.complete > 0 && <div className="bg-green-500" style={{ width: `${completePct}%` }} />}
          {totals.missing > 0 && <div className="bg-amber-400" style={{ width: `${100 - completePct}%` }} />}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-neutral-600">
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-green-500" />Заполнено — {totals.complete}</span>
          <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400" />Пропусков — {totals.missing} ({pctLabel(profile.missing_rate_pct)})</span>
          <span>Строк с пропуском — {profile.rows_with_missing} ({pctLabel(profile.rows_with_missing_pct)})</span>
          {profile.empty_rows > 0 && <span className="font-medium text-red-600">Полностью пустых строк — {profile.empty_rows}</span>}
        </div>
      </div>

      <div className="flex shrink-0 gap-1 border-b border-neutral-100 px-4 pt-2">
        {(
          [
            { id: "table", label: "Таблица" },
            { id: "matrix", label: "Матрица" },
            { id: "correlation", label: "Корреляция" },
            { id: "boxplot", label: "Boxplot" },
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
          <table aria-label="Матрица пропусков по колонкам" className="w-full min-w-[760px] text-left text-xs">
            <thead className="sticky top-0 bg-neutral-50 text-neutral-500">
              <tr>
                <th className="px-3 py-2">Колонка</th>
                <th className="px-3 py-2">Тип</th>
                <th className="px-3 py-2 text-right">Пропусков</th>
                <th className="px-3 py-2">Статус</th>
                <th className="px-3 py-2">Рекомендация</th>
              </tr>
            </thead>
            <tbody>
              {profile.columns.map((item) => (
                <tr key={item.column} className="border-t border-neutral-100 text-neutral-700">
                  <td className="px-3 py-2">
                    <span className="block font-medium text-neutral-800">{item.column}</span>
                    {item.missing_examples.length > 0 && (
                      <span className="block max-w-[220px] truncate text-[11px] text-neutral-400">
                        Строки: {item.missing_examples.join(", ")}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 tabular-nums">{item.dtype}</td>
                  <td className="px-3 py-2 text-right font-mono">{item.missing_count} ({pctLabel(item.missing_pct)})</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-1 font-medium ${item.missing_count > 0 ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"}`}>
                      {item.missing_count > 0 ? "Найдены проблемы" : "Пройдено"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-neutral-600">{STRATEGY_LABEL[item.recommended_strategy]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {activeView === "matrix" && <ExpandableChartPanel chartId="missing-matrix" title="Матрица пропусков"><MissingMatrixChart /></ExpandableChartPanel>}
      {activeView === "correlation" && <ExpandableChartPanel chartId="missing-correlation" title="Корреляция пропусков"><MissingCorrelationChart /></ExpandableChartPanel>}
      {activeView === "boxplot" && <ExpandableChartPanel chartId="missing-boxplot" title="Boxplot пропусков"><MissingBoxplotChart columns={profile.columns} /></ExpandableChartPanel>}
    </section>
  );
}
