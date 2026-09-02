"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { OutlierProfileItem, OutlierProfileResponse } from "./PreprocessingOutliersOverview";

type Method = "iqr" | "zscore" | "mad" | "percentile";
type Strategy = "drop_rows" | "cap" | "median" | "flag";

const METHOD_TEXT: Record<Method, { label: string; help: string; paramLabel: string; paramDefault: string }> = {
  iqr: { label: "IQR (межквартильный размах)", help: "Границы Q1 − k×IQR … Q3 + k×IQR. Устойчив, подходит по умолчанию.", paramLabel: "Множитель k", paramDefault: "1.5" },
  zscore: { label: "Z-score", help: "|значение − среднее| / стандартное отклонение выше порога. Чувствителен к самим выбросам (среднее/std искажаются ими же).", paramLabel: "Порог |Z|", paramDefault: "3.0" },
  mad: { label: "Modified Z-score (MAD)", help: "Как Z-score, но на медиане и медианном отклонении — устойчив при сильной асимметрии распределения.", paramLabel: "Порог |модиф. Z|", paramDefault: "3.5" },
  percentile: { label: "Процентильный", help: "Всё ниже нижнего и выше верхнего процентиля — выброс.", paramLabel: "Нижний / верхний процентиль", paramDefault: "1 / 99" },
};

const STRATEGY_TEXT: Record<Strategy, { label: string; help: string }> = {
  drop_rows: { label: "Удалить строки", help: "Удаляется объединение строк, где выброс найден хотя бы в одной из отмеченных колонок." },
  cap: { label: "Кэпирование (winsorize по IQR)", help: "Значения обрезаются до границ Q1 − 1.5×IQR / Q3 + 1.5×IQR — не зависит от выбранного метода обнаружения." },
  median: { label: "Замена медианой", help: "Выброс заменяется медианой остальных (не-выбросных) значений колонки." },
  flag: { label: "Добавить флаг выброса", help: "Исходные значения сохраняются как есть; рядом создаётся индикаторная колонка *_outlier_flag." },
};

interface ColumnStats {
  mean: number | null;
  std: number | null;
  median: number | null;
}

interface CorrectionResponse {
  applied: boolean;
  strategy: Strategy;
  method: Method;
  used_residual: boolean;
  total_outliers: number;
  total_changed: number;
  total_still_outliers: number;
  rows_removed: number;
  added_columns: string[];
  columns: Array<{
    column: string;
    outlier_count: number;
    changed_count: number;
    still_outliers: number;
    outlier_examples: number[];
    flag_column: string | null;
    stats_before: ColumnStats | null;
    stats_after: ColumnStats | null;
  }>;
  profile: OutlierProfileItem[];
}

// ── Прогноз влияния на статистики (перенос app.py "Прогноз влияния на
//    статистики" + того же блока, уже реализованного для «Пропусков» в
//    PreprocessingMissingPipeline.tsx) ──
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

interface AllColumnsResponse {
  columns: Array<{ column: string }>;
}

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

export function PreprocessingOutliersPipeline({ onApplied }: { onApplied: () => void }) {
  const [profile, setProfile] = useState<OutlierProfileResponse | null>(null);
  const [allColumns, setAllColumns] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [method, setMethod] = useState<Method>("iqr");
  const [param, setParam] = useState(METHOD_TEXT.iqr.paramDefault);
  const [strategy, setStrategy] = useState<Strategy>("cap");
  const [useResidual, setUseResidual] = useState(false);
  const [dateColumn, setDateColumn] = useState("");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const hasApplicableColumns = (profile?.columns.length ?? 0) > 0;
  const noOutliers = hasApplicableColumns && profile!.total_outliers === 0;
  const dateColumnCandidates = allColumns.filter((c) => !selected.includes(c));
  const residualAvailable = selected.length === 1 && dateColumnCandidates.length > 0;

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const [profileRes, columnsRes] = await Promise.all([
          fetch(sessionApiUrl(`/dataset/outlier-profile?method=${method}`), { credentials: "include" }),
          fetch(sessionApiUrl("/dataset/missing-profile"), { credentials: "include" }),
        ]);
        if (!profileRes.ok) throw new Error(await responseDetail(profileRes));
        const data: OutlierProfileResponse = await profileRes.json();
        const allCols: AllColumnsResponse | null = columnsRes.ok ? await columnsRes.json() : null;
        if (!active) return;
        // Оба setState синхронно в одном тике -- без await между ними,
        // иначе первый рендер покажет чекбокс «Остаток STL» disabled
        // (allColumns ещё пуст), а второй -- enabled, что делает тест на
        // «сразу доступно при одной выбранной колонке» гонкой.
        setProfile(data);
        setSelected(data.columns.filter((item) => item.outlier_count > 0).map((item) => item.column));
        if (allCols) setAllColumns(allCols.columns.map((c) => c.column));
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль выбросов");
      } finally {
        if (active) setBusy(null);
      }
    })();
    return () => { active = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- метод в query влияет лишь на предзаполнение, не переопрашиваем при его смене здесь

  const invalidatePreview = () => {
    setPreview(null);
    setConfirmed(false);
    setSuccess(null);
    setError(null);
  };

  const parsedParam = (): number | [number, number] => {
    if (method === "percentile") {
      const [low, high] = param.split("/").map((v) => parseFloat(v.trim()));
      return [Number.isFinite(low) ? low : 1, Number.isFinite(high) ? high : 99];
    }
    const value = parseFloat(param);
    return Number.isFinite(value) ? value : parseFloat(METHOD_TEXT[method].paramDefault);
  };

  const requestCorrection = async (apply: boolean) => {
    setBusy(apply ? "apply" : "preview");
    setError(null);
    setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/outlier-corrections"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          columns: selected,
          strategy,
          method,
          param: parsedParam(),
          use_residual: useResidual && residualAvailable,
          date_column: useResidual && residualAvailable ? dateColumn : null,
          apply,
        }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const data: CorrectionResponse = await response.json();
      setPreview(data);
      setConfirmed(false);
      if (apply) {
        setProfile((current) => current ? {
          ...current,
          columns: data.profile,
          total_outliers: data.profile.reduce((sum, item) => sum + item.outlier_count, 0),
        } : current);
        setSelected(data.profile.filter((item) => item.outlier_count > 0).map((item) => item.column));
        setSuccess("Изменения применены, профиль пересчитан");
        onApplied();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось исправить выбросы");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      role="region"
      aria-label="Мастер исправления выбросов"
      className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll"
    >
      {noOutliers && (
        <div role="status" className="mb-4 rounded bg-green-50 px-3 py-2 text-sm text-green-700">
          <p className="font-medium">Выбросов в датасете не найдено выбранным методом.</p>
          <p className="mt-0.5 text-xs">Исправление не требуется.</p>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">1. Колонки с выбросами</h4>
          <p className="mt-1 text-xs text-neutral-500">Предзаполнены числовые колонки, где найден хотя бы один выброс.</p>
          <div className="mt-3 space-y-2">
            {busy === "load" && <p className="text-sm text-neutral-400">Загрузка профиля…</p>}
            {!hasApplicableColumns && busy !== "load" && (
              <div className="rounded bg-amber-50 p-2 text-sm text-amber-800">
                <p className="font-medium">В датасете нет числовых колонок.</p>
              </div>
            )}
            {profile?.columns.map((item) => (
              <label key={item.column} className="block rounded bg-neutral-50 p-2 text-sm text-neutral-700">
                <span className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(item.column)}
                    onChange={() => {
                      invalidatePreview();
                      setSelected((current) => current.includes(item.column)
                        ? current.filter((c) => c !== item.column)
                        : [...current, item.column]);
                    }}
                    aria-label={`Выбрать колонку ${item.column}`}
                    className="accent-brand"
                  />
                  <span className="font-medium">{item.column}</span>
                  <span className="ml-auto text-xs">выбросов: {item.outlier_count}</span>
                </span>
                {item.outlier_examples.length > 0 && (
                  <span className="mt-1 block text-xs text-amber-700">Примеры строк: {item.outlier_examples.join(", ")}</span>
                )}
              </label>
            ))}
          </div>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">2. Метод обнаружения</h4>
          <select
            aria-label="Метод обнаружения выбросов"
            value={method}
            onChange={(event) => {
              invalidatePreview();
              const next = event.target.value as Method;
              setMethod(next);
              setParam(METHOD_TEXT[next].paramDefault);
            }}
            className="mt-2 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm"
          >
            {(Object.keys(METHOD_TEXT) as Method[]).map((key) => (
              <option key={key} value={key}>{METHOD_TEXT[key].label}</option>
            ))}
          </select>
          <p className="mt-2 text-xs text-neutral-600">{METHOD_TEXT[method].help}</p>
          <label className="mt-2 block text-xs text-neutral-600">
            {METHOD_TEXT[method].paramLabel}
            <input
              type="text"
              value={param}
              onChange={(event) => { invalidatePreview(); setParam(event.target.value); }}
              className="mt-1 block w-full rounded border border-neutral-300 px-2 py-1 text-sm"
            />
          </label>

          <div className="mt-3 border-t border-neutral-100 pt-2">
            <label className="flex items-start gap-2 text-xs text-neutral-700">
              <input
                type="checkbox"
                checked={useResidual && residualAvailable}
                disabled={!residualAvailable}
                onChange={(event) => { invalidatePreview(); setUseResidual(event.target.checked); }}
                aria-label="Обнаруживать на остатке после STL-декомпозиции"
                className="mt-0.5 accent-brand"
              />
              Обнаруживать на остатке после STL-декомпозиции (вместо исходных значений)
            </label>
            {!residualAvailable && selected.length !== 1 && (
              <p className="mt-1 text-[11px] text-neutral-400">Доступно только при выборе ровно одной колонки.</p>
            )}
            {useResidual && residualAvailable && (
              <label className="mt-2 block text-xs text-neutral-600">
                Колонка с датой
                <select
                  aria-label="Колонка с датой для декомпозиции"
                  value={dateColumn}
                  onChange={(event) => { invalidatePreview(); setDateColumn(event.target.value); }}
                  className="mt-1 block w-full rounded border border-neutral-300 px-2 py-1 text-sm"
                >
                  <option value="">— выберите —</option>
                  {dateColumnCandidates.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <span className="mt-1 block text-[11px] text-neutral-400">
                  Недоступно для панельных данных (несколько строк на одну дату) и нерегулярных частот — вернётся понятная ошибка, если декомпозиция неприменима.
                </span>
              </label>
            )}
          </div>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">3. Стратегия исправления</h4>
          <select
            aria-label="Стратегия исправления выбросов"
            value={strategy}
            onChange={(event) => { invalidatePreview(); setStrategy(event.target.value as Strategy); }}
            className="mt-2 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm"
          >
            {(Object.keys(STRATEGY_TEXT) as Strategy[]).map((key) => (
              <option key={key} value={key}>{STRATEGY_TEXT[key].label}</option>
            ))}
          </select>
          <p className="mt-2 text-xs text-neutral-600">{STRATEGY_TEXT[strategy].help}</p>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">4. Предпросмотр</h4>
          <p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на копии и не изменяет активный датасет.</p>
          <button
            type="button"
            disabled={selected.length === 0 || busy !== null || (useResidual && residualAvailable && !dateColumn)}
            onClick={() => requestCorrection(false)}
            className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}
          </button>
          {preview && (
            <div className="mt-3 rounded bg-neutral-50 p-2 text-xs text-neutral-700">
              <p className="font-medium">Найдено выбросов: {preview.total_outliers}</p>
              <p>Исправлено значений: {preview.total_changed}</p>
              <p>Осталось выбросов: {preview.total_still_outliers}</p>
              {preview.used_residual && <p className="text-brand">Обнаружение на остатке после декомпозиции</p>}
              {preview.rows_removed > 0 && <p>Будет удалено строк: {preview.rows_removed}</p>}
              {preview.added_columns.length > 0 && <p>Добавлены колонки: {preview.added_columns.join(", ")}</p>}
            </div>
          )}
          {preview && preview.columns.some((item) => item.stats_before) && (
            <div className="mt-3 rounded border border-neutral-200 p-2">
              <p className="text-xs font-medium text-neutral-800">Прогноз влияния на статистики</p>
              <p className="mt-0.5 text-[11px] text-neutral-500">
                Среднее / медиана / стандартное отклонение до и после стратегии на копии.
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
                Заметное падение стандартного отклонения — ожидаемый эффект кэпирования/замены медианой; резкий сдвиг среднего в других стратегиях стоит перепроверить.
              </p>
            </div>
          )}
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">5. Применение</h4>
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
