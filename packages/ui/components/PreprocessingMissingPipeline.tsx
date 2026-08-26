"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { MissingProfileItem, MissingProfileResponse } from "./PreprocessingMissingOverview";

type Strategy = "drop_rows" | "median_mode" | "mean_mode" | "constant" | "interpolate" | "flag";

interface ColumnStats {
  mean: number | null;
  std: number | null;
  median: number | null;
}

interface CorrectionResponse {
  applied: boolean;
  strategy: Strategy;
  total_missing: number;
  total_changed: number;
  total_still_missing: number;
  rows_removed: number;
  added_columns: string[];
  columns: Array<{
    column: string;
    missing_count: number;
    changed_count: number;
    still_missing: number;
    missing_examples: number[];
    flag_column: string | null;
    stats_before: ColumnStats | null;
    stats_after: ColumnStats | null;
  }>;
  profile: MissingProfileItem[];
}

const STRATEGY_TEXT: Record<Strategy, { label: string; help: string }> = {
  drop_rows: {
    label: "Удалить строки с пропусками",
    help: "Удаляется объединение строк, где отсутствует значение хотя бы в одной из отмеченных колонок.",
  },
  median_mode: {
    label: "Заполнить медианой / модой",
    help: "Числовые колонки — медианой корректных значений; текстовые/категориальные — самым частым значением (модой).",
  },
  mean_mode: {
    label: "Заполнить средним / модой",
    help: "Числовые колонки — средним значением корректных наблюдений; текстовые/категориальные — модой.",
  },
  constant: {
    label: "Заполнить нулём / Unknown",
    help: "Числовые колонки заполняются нулём, текстовые/категориальные — значением «Unknown».",
  },
  interpolate: {
    label: "Линейная интерполяция",
    help: "Доступно только для числовых колонок; пропуск оценивается по соседним точкам ряда.",
  },
  flag: {
    label: "Добавить флаг пропуска",
    help: "Исходные значения сохраняются как есть; рядом создаётся индикаторная колонка *_missing_flag.",
  },
};

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

// ── Прогноз влияния на статистики (перенос app.py "Прогноз влияния на
//    статистики", кнопка btn_show_fill_preview) ──
const STAT_LABEL: Record<"mean" | "median" | "std", string> = {
  mean: "Mean", median: "Median", std: "Std",
};

function formatStat(value: number | null): string {
  return value === null ? "N/A" : value.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

function formatDeltaPct(before: number | null, after: number | null): string {
  if (before === null || after === null || before === 0 || before === after) return "";
  const pct = ((after - before) / Math.abs(before)) * 100;
  const sign = pct >= 0 ? "+" : "";
  return ` (${sign}${pct.toFixed(1)}%)`;
}

export function PreprocessingMissingPipeline({ onApplied }: { onApplied: () => void }) {
  const [profile, setProfile] = useState<MissingProfileResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [strategy, setStrategy] = useState<Strategy>("median_mode");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const hasApplicableColumns = (profile?.columns.length ?? 0) > 0;
  const noMissingValues = hasApplicableColumns && profile!.total_missing === 0;

  // Интерполяция применима только к числовым колонкам -- недопустимые
  // выборы снимаются автоматически при переключении стратегии, а не
  // молча игнорируются бэкендом (пользователь должен видеть, что выбор
  // изменился).
  const eligibleForStrategy = (item: MissingProfileItem) =>
    strategy !== "interpolate" || item.semantic === "numeric";

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/missing-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: MissingProfileResponse = await response.json();
        if (!active) return;
        setProfile(data);
        setSelected(data.columns.filter((item) => item.missing_count > 0).map((item) => item.column));
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль пропусков");
      } finally {
        if (active) setBusy(null);
      }
    })();
    return () => { active = false; };
  }, []);

  const invalidatePreview = () => {
    setPreview(null);
    setConfirmed(false);
    setSuccess(null);
    setError(null);
  };

  const requestCorrection = async (apply: boolean) => {
    setBusy(apply ? "apply" : "preview");
    setError(null);
    setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/missing-corrections"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ columns: selected, strategy, apply }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const data: CorrectionResponse = await response.json();
      setPreview(data);
      setConfirmed(false);
      if (apply) {
        setProfile((current) => current ? {
          ...current,
          columns: data.profile,
          total_missing: data.profile.reduce((sum, item) => sum + item.missing_count, 0),
        } : current);
        setSelected(data.profile.filter((item) => item.missing_count > 0).map((item) => item.column));
        setSuccess("Изменения применены, профиль пересчитан");
        onApplied();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось исправить пропуски");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      role="region"
      aria-label="Мастер исправления пропусков"
      className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll"
    >
      {noMissingValues && (
        <div role="status" className="mb-4 rounded bg-green-50 px-3 py-2 text-sm text-green-700">
          <p className="font-medium">Пропусков в датасете не найдено.</p>
          <p className="mt-0.5 text-xs">Исправление не требуется.</p>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">1. Колонки с пропусками</h4>
          <p className="mt-1 text-xs text-neutral-500">Предзаполнены колонки, где найден хотя бы один пропуск.</p>
          <div className="mt-3 space-y-2">
            {busy === "load" && <p className="text-sm text-neutral-400">Загрузка профиля…</p>}
            {!hasApplicableColumns && busy !== "load" && (
              <div className="rounded bg-amber-50 p-2 text-sm text-amber-800">
                <p className="font-medium">В датасете нет колонок.</p>
              </div>
            )}
            {profile?.columns.map((item) => (
              <label
                key={item.column}
                className={`block rounded p-2 text-sm text-neutral-700 ${eligibleForStrategy(item) ? "bg-neutral-50" : "bg-neutral-100 opacity-60"}`}
              >
                <span className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(item.column)}
                    disabled={item.missing_count === 0 || !eligibleForStrategy(item)}
                    onChange={() => {
                      invalidatePreview();
                      setSelected((current) => current.includes(item.column)
                        ? current.filter((column) => column !== item.column)
                        : [...current, item.column]);
                    }}
                    aria-label={`Выбрать колонку ${item.column}`}
                    className="accent-brand"
                  />
                  <span className="font-medium">{item.column}</span>
                  <span className="ml-auto text-xs">пропусков: {item.missing_count}</span>
                </span>
                <span className="mt-1 block text-[11px] text-neutral-500">{item.dtype} · {item.semantic}</span>
                {!eligibleForStrategy(item) && (
                  <span className="mt-1 block text-xs text-amber-700">Интерполяция недоступна для нечисловой колонки</span>
                )}
                {item.missing_examples.length > 0 && (
                  <span className="mt-1 block text-xs text-amber-700">Примеры строк: {item.missing_examples.join(", ")}</span>
                )}
              </label>
            ))}
          </div>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">2. Стратегия исправления</h4>
          <p className="mt-1 text-xs text-neutral-500">Выберите действие для всех отмеченных колонок.</p>
          <select
            aria-label="Стратегия исправления пропусков"
            value={strategy}
            onChange={(event) => {
              invalidatePreview();
              const next = event.target.value as Strategy;
              setStrategy(next);
              if (next === "interpolate" && profile) {
                setSelected((current) => current.filter((column) => {
                  const item = profile.columns.find((candidate) => candidate.column === column);
                  return item?.semantic === "numeric";
                }));
              }
            }}
            className="mt-3 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm"
          >
            {(Object.keys(STRATEGY_TEXT) as Strategy[]).map((key) => (
              <option key={key} value={key}>{STRATEGY_TEXT[key].label}</option>
            ))}
          </select>
          <p className="mt-2 text-xs text-neutral-600">{STRATEGY_TEXT[strategy].help}</p>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">3. Предпросмотр</h4>
          <p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на копии и не изменяет активный датасет.</p>
          <button
            type="button"
            disabled={selected.length === 0 || busy !== null}
            onClick={() => requestCorrection(false)}
            className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}
          </button>
          {preview && (
            <div className="mt-3 rounded bg-neutral-50 p-2 text-xs text-neutral-700">
              <p className="font-medium">Исправлено значений: {preview.total_changed}</p>
              <p>Осталось пропусков: {preview.total_still_missing}</p>
              {preview.rows_removed > 0 && <p>Будет удалено строк: {preview.rows_removed}</p>}
              {preview.added_columns.length > 0 && <p>Добавлены колонки: {preview.added_columns.join(", ")}</p>}
            </div>
          )}
          {preview && preview.columns.some((item) => item.stats_before) && (
            <div className="mt-3 rounded border border-neutral-200 p-2">
              <p className="text-xs font-medium text-neutral-800">Прогноз влияния на статистики</p>
              <p className="mt-0.5 text-[11px] text-neutral-500">
                Числовые колонки: среднее / медиана / стандартное отклонение до и после стратегии на копии.
              </p>
              <div className="mt-2 space-y-2">
                {preview.columns.filter((item) => item.stats_before).map((item) => (
                  <div key={item.column} className="text-xs text-neutral-700">
                    <p className="font-medium">{item.column}</p>
                    <dl className="mt-0.5 grid grid-cols-3 gap-x-2 gap-y-0.5 text-[11px]">
                      {(["mean", "median", "std"] as const).map((stat) => (
                        <div key={stat}>
                          <dt className="text-neutral-400">{STAT_LABEL[stat]}</dt>
                          <dd className="font-mono">
                            {formatStat(item.stats_before?.[stat] ?? null)} → {formatStat(item.stats_after?.[stat] ?? null)}
                            {formatDeltaPct(item.stats_before?.[stat] ?? null, item.stats_after?.[stat] ?? null)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-amber-700">
                Заметный сдвиг среднего или резкое падение стандартного отклонения — сигнал, что стратегия слишком агрессивно сглаживает эту колонку; рассмотрите другую стратегию.
              </p>
            </div>
          )}
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">4. Применение</h4>
          <p className="mt-1 text-xs text-neutral-500">После подтверждения копия сохраняется атомарно, затем профиль пересчитывается повторно.</p>
          <label className="mt-3 flex items-start gap-2 text-xs text-neutral-700">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={!preview || busy !== null}
              onChange={(event) => setConfirmed(event.target.checked)}
              aria-label="Подтверждаю изменение активного датасета"
              className="mt-0.5 accent-brand"
            />
            Подтверждаю изменение активного датасета
          </label>
          <button
            type="button"
            disabled={!preview || !confirmed || busy !== null}
            onClick={() => requestCorrection(true)}
            className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === "apply" ? "Применение…" : "Применить исправления"}
          </button>
        </div>
      </div>
      {error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}
    </section>
  );
}
