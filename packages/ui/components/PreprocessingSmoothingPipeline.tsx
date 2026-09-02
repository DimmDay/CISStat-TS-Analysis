"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { SmoothingMethod } from "./PreprocessingSmoothingOverview";


interface SmoothingResponse {
  applied: boolean; column: string; method: SmoothingMethod; output_column: string;
  rows_before: number; rows_after: number; columns_before: number; columns_after: number;
  metadata: { parameters: Record<string, number>; causal: boolean; modeling_safe: boolean; inverse_supported: boolean; fitted_on_n: number };
}
async function detail(response: Response): Promise<string> {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}
const OFFLINE = new Set<SmoothingMethod>(["savgol", "lowess"]);

export function PreprocessingSmoothingPipeline({ column, recommendedMethod, onApplied }: {
  column: string | null; recommendedMethod: SmoothingMethod | null; onApplied: () => void;
}) {
  const [method, setMethod] = useState<SmoothingMethod>(recommendedMethod ?? "ema");
  const [window, setWindow] = useState(7); const [span, setSpan] = useState(7);
  const [frac, setFrac] = useState(0.2); const [polyorder, setPolyorder] = useState(2);
  const [confirmOffline, setConfirmOffline] = useState(false);
  const [preview, setPreview] = useState<SmoothingResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null); const [success, setSuccess] = useState<string | null>(null);
  const offline = OFFLINE.has(method);

  useEffect(() => { setMethod(recommendedMethod ?? "ema"); setPreview(null); setConfirmed(false); setConfirmOffline(false); }, [column, recommendedMethod]);
  const invalidate = () => { setPreview(null); setConfirmed(false); setError(null); setSuccess(null); };
  const request = async (apply: boolean) => {
    if (!column) return;
    setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/preprocessing/smoothing-transformations"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ column, method, window, span, frac, polyorder, confirm_non_causal: offline && confirmOffline, apply }),
      });
      if (!response.ok) throw new Error(await detail(response));
      const data: SmoothingResponse = await response.json(); setPreview(data); setConfirmed(false);
      if (apply) { setSuccess("Сглаженная колонка и параметры сохранены в сессии"); onApplied(); }
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось выполнить сглаживание"); }
    finally { setBusy(null); }
  };

  return <section role="region" aria-label="Мастер сглаживания ряда" className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll">{!column ? <p role="status" className="rounded bg-amber-50 p-3 text-sm text-amber-800">Выберите числовой исследуемый признак.</p> : <div className="grid gap-4 lg:grid-cols-2"><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Метод и параметр</h4><label className="mt-2 block text-xs text-neutral-600">Метод сглаживания<select aria-label="Метод сглаживания" value={method} onChange={(event) => { invalidate(); setMethod(event.target.value as SmoothingMethod); setConfirmOffline(false); }} className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm"><option value="ema">EMA · каузальный</option><option value="sma">Trailing SMA · каузальный</option><option value="wma">Trailing WMA · каузальный</option><option value="median">Trailing median · каузальный</option><option value="savgol">Savitzky–Golay · offline</option><option value="lowess">LOWESS · offline</option></select></label>{method === "ema" ? <label className="mt-2 block text-xs text-neutral-600">Span<input aria-label="Span EMA" type="number" min={2} max={501} value={span} onChange={(event) => { invalidate(); setSpan(Number(event.target.value)); }} className="mt-1 w-full rounded border px-2 py-1.5" /></label> : method === "lowess" ? <label className="mt-2 block text-xs text-neutral-600">Frac<input aria-label="Frac LOWESS" type="number" min={0.01} max={1} step={0.01} value={frac} onChange={(event) => { invalidate(); setFrac(Number(event.target.value)); }} className="mt-1 w-full rounded border px-2 py-1.5" /></label> : <><label className="mt-2 block text-xs text-neutral-600">Window<input aria-label="Окно сглаживания" type="number" min={3} max={501} step={2} value={window} onChange={(event) => { invalidate(); setWindow(Number(event.target.value)); }} className="mt-1 w-full rounded border px-2 py-1.5" /></label>{method === "savgol" && <label className="mt-2 block text-xs text-neutral-600">Polyorder<input aria-label="Порядок полинома" type="number" min={1} max={10} value={polyorder} onChange={(event) => { invalidate(); setPolyorder(Number(event.target.value)); }} className="mt-1 w-full rounded border px-2 py-1.5" /></label>}</>}</div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Временной контракт</h4>{offline ? <><p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-800">Метод использует будущие наблюдения. Результат предназначен для offline-обзора и не является готовым признаком backtest.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" aria-label="Подтверждаю некаузальный offline-режим" checked={confirmOffline} onChange={(event) => { invalidate(); setConfirmOffline(event.target.checked); }} className="mt-0.5 accent-brand" />Подтверждаю некаузальный offline-режим</label></> : <p className="mt-2 rounded bg-green-50 p-2 text-xs text-green-800">Каузальный фильтр: в точке t используются только текущие и прошлые значения. Параметр всё равно следует выбирать только на train.</p>}<p className="mt-2 text-[10px] text-neutral-500">Добавится <b>{column}_{method}</b>; исходный target не перезаписывается. Сглаживание необратимо.</p></div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на глубокой копии датасета.</p><button type="button" disabled={busy !== null || (offline && !confirmOffline)} onClick={() => void request(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Выполняется…" : "Предпросмотр сглаживания"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs"><p>Колонок: {preview.columns_before} → {preview.columns_after}</p><p>Будет добавлена: {preview.output_column}</p><p>Режим: {preview.metadata.causal ? "каузальный" : "offline"}</p></div>}</div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Применение</h4><p className="mt-1 text-xs text-neutral-500">Полезность сглаженной колонки подтверждается временным backtest, а не визуальной гладкостью.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" aria-label="Подтверждаю добавление сглаженной колонки" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 accent-brand" />Подтверждаю добавление сглаженной колонки</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => void request(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Применение…" : "Добавить сглаженную колонку"}</button></div></div>}{error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}</section>;
}
