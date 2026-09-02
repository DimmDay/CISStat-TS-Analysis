"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { RegularityProfile, RegularityProfileResponse } from "./PreprocessingRegularityOverview";

type Strategy = "sort" | "interpolate" | "ffill" | "bfill" | "asfreq" | "fictitious_zero" | "flag";

const STRATEGY_TEXT: Record<Strategy, { label: string; help: string; needsFrequency: boolean }> = {
  sort: { label: "Отсортировать по дате", help: "Только переупорядочивает строки (по сущности, затем по дате). Не меняет частоту, не создаёт и не удаляет строки.", needsFrequency: false },
  interpolate: { label: "Ресемплировать + линейная интерполяция", help: "Приводит ряд к регулярной сетке целевой частоты; числовые пропуски в новых точках заполняются линейной интерполяцией, остальные — ffill/bfill.", needsFrequency: true },
  ffill: { label: "Ресемплировать + forward fill", help: "Регулярная сетка; пропуски заполняются последним известным значением.", needsFrequency: true },
  bfill: { label: "Ресемплировать + backward fill", help: "Регулярная сетка; пропуски заполняются следующим известным значением.", needsFrequency: true },
  asfreq: { label: "Ресемплировать без заполнения", help: "Регулярная сетка; новые точки остаются пропусками (для последующей обработки на остановке «Пропуски»).", needsFrequency: true },
  fictitious_zero: { label: "Ресемплировать + заполнить нулём/Unknown", help: "Регулярная сетка; числовые пропуски → 0, остальные — ffill/bfill.", needsFrequency: true },
  flag: { label: "Только пометить флагом", help: "Данные не меняются; добавляется индикаторная колонка _has_gap (1 — строка на разрыве/дубле/нарушении сортировки).", needsFrequency: false },
};

interface CorrectionResponse {
  applied: boolean;
  strategy: string;
  frequency: string | null;
  rows_before: number;
  rows_after: number;
  rows_added: number;
  duplicates_aggregated: number;
  total_violations_before: number;
  total_violations_after: number;
  sort_violations_before: number;
  sort_violations_after: number;
  added_columns: string[];
  profile: RegularityProfile;
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

export function PreprocessingRegularityPipeline({ onApplied }: { onApplied: () => void }) {
  const [profile, setProfile] = useState<RegularityProfile | null>(null);
  const [strategy, setStrategy] = useState<Strategy>("interpolate");
  const [frequency, setFrequency] = useState("");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/preprocessing/regularity-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: RegularityProfileResponse = await response.json();
        if (!active) return;
        setProfile(data.profile);
        setFrequency(data.profile.target_frequency ?? "");
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль регулярности");
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
      const response = await fetch(sessionApiUrl("/dataset/preprocessing/regularity-corrections"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          strategy,
          frequency: STRATEGY_TEXT[strategy].needsFrequency ? (frequency || null) : null,
          apply,
        }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const data: CorrectionResponse = await response.json();
      setPreview(data);
      setConfirmed(false);
      if (apply) {
        setProfile(data.profile);
        setSuccess("Изменения применены, профиль пересчитан");
        onApplied();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось исправить регулярность");
    } finally {
      setBusy(null);
    }
  };

  const noViolations = profile ? profile.total_violations === 0 : false;

  return (
    <section
      role="region"
      aria-label="Мастер исправления регулярности"
      className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll"
    >
      {busy === "load" && <p className="text-sm text-neutral-400">Загрузка профиля…</p>}
      {!busy && !profile?.applicable && (
        <div role="status" className="mb-4 rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Не удалось определить временную колонку — мастер недоступен.
        </div>
      )}
      {noViolations && (
        <div role="status" className="mb-4 rounded bg-green-50 px-3 py-2 text-sm text-green-700">
          <p className="font-medium">Нарушений регулярности не найдено.</p>
          <p className="mt-0.5 text-xs">Исправление не требуется.</p>
        </div>
      )}
      {profile?.applicable && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-md border border-neutral-200 p-3">
            <h4 className="text-sm font-semibold text-neutral-800">1. Стратегия исправления</h4>
            <select
              aria-label="Стратегия исправления регулярности"
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
            <h4 className="text-sm font-semibold text-neutral-800">2. Целевая частота</h4>
            {STRATEGY_TEXT[strategy].needsFrequency ? (
              <>
                <input
                  type="text"
                  aria-label="Целевая частота (pandas frequency alias)"
                  value={frequency}
                  onChange={(event) => { invalidatePreview(); setFrequency(event.target.value); }}
                  placeholder="например, D, W, MS, QS, YS"
                  className="mt-2 block w-full rounded border border-neutral-300 px-2 py-1.5 text-sm"
                />
                <p className="mt-2 text-xs text-neutral-500">
                  По умолчанию — определённая целевая частота ({profile.target_frequency ?? "не определена"}). Укажите свою через pandas-alias (D/W/MS/QS/YS/h/min и т.п.), если нужна другая.
                </p>
              </>
            ) : (
              <p className="mt-2 text-xs text-neutral-500">Не требуется для этой стратегии — данные не ресемплируются.</p>
            )}
          </div>

          <div className="rounded-md border border-neutral-200 p-3">
            <h4 className="text-sm font-semibold text-neutral-800">3. Предпросмотр</h4>
            <p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на копии и не изменяет активный датасет.</p>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => requestCorrection(false)}
              className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}
            </button>
            {preview && (
              <div className="mt-3 rounded bg-neutral-50 p-2 text-xs text-neutral-700">
                <p className="font-medium">Нарушений: {preview.total_violations_before} → {preview.total_violations_after}</p>
                <p>Строк: {preview.rows_before} → {preview.rows_after} ({preview.rows_added > 0 ? `+${preview.rows_added}` : preview.rows_added})</p>
                {preview.duplicates_aggregated > 0 && <p>Дублей агрегировано: {preview.duplicates_aggregated}</p>}
                {preview.added_columns.length > 0 && <p>Добавлены колонки: {preview.added_columns.join(", ")}</p>}
              </div>
            )}
          </div>

          <div className="rounded-md border border-neutral-200 p-3">
            <h4 className="text-sm font-semibold text-neutral-800">4. Применение</h4>
            <p className="mt-1 text-xs text-neutral-500">После подтверждения копия сохраняется атомарно, затем профиль регулярности пересчитывается повторно.</p>
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
      )}
      {error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}
    </section>
  );
}
