"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { StationarityProfileMethod, StationarityTransformMethod } from "./PreprocessingStationarityOverview";


interface StationarityResponse {
  applied: boolean; column: string; method: StationarityTransformMethod; output_column: string;
  rows_before: number; rows_after: number; rows_dropped: number; columns_before: number; columns_after: number;
  metadata: { causal: boolean; modeling_safe: boolean; inverse_supported: boolean; regular_order: number; seasonal_order: number; seasonal_period: number | null; lost_observations: number; fitted_on_n: number };
}
async function detail(response: Response): Promise<string> {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

export function PreprocessingStationarityPipeline({ column, recommendedMethod, seasonalPeriod, onApplied }: {
  column: string | null; recommendedMethod: StationarityProfileMethod | null; seasonalPeriod: number; onApplied: () => void;
}) {
  const recommended = recommendedMethod && recommendedMethod !== "none" ? recommendedMethod : "first_difference";
  const [method, setMethod] = useState<StationarityTransformMethod>(recommended);
  const [period, setPeriod] = useState(seasonalPeriod);
  const [confirmOffline, setConfirmOffline] = useState(false);
  const [preview, setPreview] = useState<StationarityResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const offline = method === "linear_detrend";
  const usesSeason = method === "seasonal_difference" || method === "combined_difference";

  useEffect(() => {
    setMethod(recommendedMethod && recommendedMethod !== "none" ? recommendedMethod : "first_difference");
    setPeriod(seasonalPeriod); setPreview(null); setConfirmed(false); setConfirmOffline(false);
  }, [column, recommendedMethod, seasonalPeriod]);
  const invalidate = () => { setPreview(null); setConfirmed(false); setError(null); setSuccess(null); };
  const request = async (apply: boolean) => {
    if (!column) return;
    setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/preprocessing/stationarity-transformations"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ column, method, seasonal_period: period, confirm_non_causal: offline && confirmOffline, apply }),
      });
      if (!response.ok) throw new Error(await detail(response));
      const data: StationarityResponse = await response.json(); setPreview(data); setConfirmed(false);
      if (apply) { setSuccess("Новая колонка, границы инверсии и порядок разностей сохранены в сессии"); onApplied(); }
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось выполнить преобразование"); }
    finally { setBusy(null); }
  };

  return <section role="region" aria-label="Мастер обеспечения стационарности" className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll">{!column ? <p role="status" className="rounded bg-amber-50 p-3 text-sm text-amber-800">Выберите числовой исследуемый признак.</p> : <div className="grid gap-4 lg:grid-cols-2"><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Преобразование</h4><label className="mt-2 block text-xs text-neutral-600">Метод обеспечения стационарности<select aria-label="Метод обеспечения стационарности" value={method} onChange={(event) => { invalidate(); setMethod(event.target.value as StationarityTransformMethod); setConfirmOffline(false); }} className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm"><option value="first_difference">Первая разность Δ · каузальная</option><option value="seasonal_difference">Сезонная разность Δs · каузальная</option><option value="combined_difference">Сезонная + первая · каузальная</option><option value="log_difference">Log-разность · каузальная</option><option value="linear_detrend">Линейный detrend · offline</option><option value="second_difference">Вторая разность Δ² · осторожно</option></select></label>{usesSeason && <label className="mt-2 block text-xs text-neutral-600">Сезонный период<input aria-label="Сезонный период" type="number" min={2} max={10000} value={period} onChange={(event) => { invalidate(); setPeriod(Number(event.target.value)); }} className="mt-1 w-full rounded border px-2 py-1.5" /></label>}<p className="mt-2 text-[10px] text-neutral-500">Δ² — повторная разность, не разность с лагом 2. Сезонный период должен быть подтверждён EDA/предметной логикой.</p></div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Временной и inverse-контракт</h4>{offline ? <><p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-800">Тренд для обзора оценивается по полной истории. Для backtest коэффициенты нужно переоценить только на train.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" aria-label="Подтверждаю некаузальный offline-detrend" checked={confirmOffline} onChange={(event) => { invalidate(); setConfirmOffline(event.target.checked); }} className="mt-0.5 accent-brand" />Подтверждаю некаузальный offline-detrend</label></> : <p className="mt-2 rounded bg-green-50 p-2 text-xs text-green-800">Оператор каузален: значение в t использует только текущую и прошлую историю. Порядок всё равно выбирается внутри train-fold.</p>}<p className="mt-2 text-[10px] text-neutral-500">Исходный target сохраняется. Неопределённый начальный префикс удаляется синхронно из всего датасета; anchors сохраняются для обратного преобразования прогноза.</p></div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><p className="mt-1 text-xs text-neutral-500">Проверяется потеря наблюдений и имя новой колонки без мутации сессии.</p><button type="button" disabled={busy !== null || (offline && !confirmOffline)} onClick={() => void request(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Выполняется…" : "Предпросмотр преобразования"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs"><p>Строк: {preview.rows_before} → {preview.rows_after}</p><p>Будет удалено начальных строк: {preview.rows_dropped}</p><p>Будет добавлена: {preview.output_column}</p><p>Inverse: {preview.metadata.inverse_supported ? "поддерживается" : "не поддерживается"}</p></div>}</div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Применение</h4><p className="mt-1 text-xs text-neutral-500">Применение атомарно сортирует временную ось, удаляет только математически неопределённый префикс и добавляет новую колонку.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" aria-label="Подтверждаю изменение активного датасета" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 accent-brand" />Подтверждаю изменение активного датасета</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => void request(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Применение…" : "Применить преобразование"}</button></div></div>}{error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}</section>;
}
