"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { VarianceMethod } from "./PreprocessingVarianceOverview";


interface CorrectionResponse {
  applied: boolean; column: string; method: VarianceMethod; lambda_value: number | null;
  output_column: string; rows_before: number; rows_after: number;
  columns_before: number; columns_after: number;
  metadata: { inverse_supported: boolean; fitted_on_n: number };
}

async function detail(response: Response): Promise<string> {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

export function PreprocessingVariancePipeline({ column, recommendedMethod, onApplied }: {
  column: string | null; recommendedMethod: VarianceMethod | null; onApplied: () => void;
}) {
  const [method, setMethod] = useState<VarianceMethod>(recommendedMethod ?? "yeo_johnson");
  const [autoLambda, setAutoLambda] = useState(true);
  const [lambdaValue, setLambdaValue] = useState("0");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => { setMethod(recommendedMethod ?? "yeo_johnson"); setPreview(null); setConfirmed(false); }, [column, recommendedMethod]);
  const invalidate = () => { setPreview(null); setConfirmed(false); setError(null); setSuccess(null); };
  const isPower = method === "box_cox" || method === "yeo_johnson";
  const request = async (apply: boolean) => {
    if (!column) return;
    setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/preprocessing/variance-transformations"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ column, method, lambda_value: isPower && !autoLambda ? Number(lambdaValue) : null, apply }),
      });
      if (!response.ok) throw new Error(await detail(response));
      const data: CorrectionResponse = await response.json();
      setPreview(data); setConfirmed(false);
      if (apply) { setSuccess("Трансформированная колонка и параметры обратного преобразования сохранены"); onApplied(); }
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось применить трансформацию"); }
    finally { setBusy(null); }
  };

  return <section role="region" aria-label="Мастер стабилизации дисперсии" className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll">
    {!column ? <p role="status" className="rounded bg-amber-50 p-3 text-sm text-amber-800">Выберите числовой исследуемый признак.</p> : <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Метод</h4><label className="mt-2 block text-xs text-neutral-600">Метод трансформации<select aria-label="Метод трансформации" value={method} onChange={(event) => { invalidate(); setMethod(event.target.value as VarianceMethod); }} className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm"><option value="box_cox">Box–Cox · только y &gt; 0</option><option value="yeo_johnson">Yeo–Johnson · любые значения</option><option value="log">Log · только y &gt; 0</option><option value="log1p">Log1p · y &gt; −1</option><option value="sqrt">Квадратный корень · y ≥ 0</option></select></label>{isPower && <><label className="mt-3 flex items-start gap-2 text-xs text-neutral-700"><input aria-label="Подбирать λ автоматически по MLE" type="checkbox" checked={autoLambda} onChange={(event) => { invalidate(); setAutoLambda(event.target.checked); }} className="mt-0.5 accent-brand" />Подбирать λ автоматически по MLE</label>{!autoLambda && <label className="mt-2 block text-xs text-neutral-600">Значение λ<input aria-label="Значение λ" type="number" min={-5} max={5} step={0.1} value={lambdaValue} onChange={(event) => { invalidate(); setLambdaValue(event.target.value); }} className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm" /></label>}</>}</div>
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Контракт выхода</h4><p className="mt-2 text-xs text-neutral-600">Будет добавлена новая колонка <b>{column}_{method}</b>. Исходный ряд не перезаписывается.</p><p className="mt-2 text-[10px] text-neutral-500">Метод и λ сохраняются в сессии для обратного преобразования. Стандартизация выключена: масштабирование выполняется отдельной остановкой.</p></div>
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на глубокой копии датасета.</p><button type="button" disabled={busy !== null} onClick={() => void request(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs text-neutral-700"><p>Колонок: {preview.columns_before} → {preview.columns_after}</p><p>Будет добавлена: {preview.output_column}</p><p>λ: {preview.lambda_value === null ? "не используется" : preview.lambda_value.toFixed(6)}</p></div>}</div>
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Применение</h4><p className="mt-1 text-xs text-neutral-500">В backtest λ нужно оценивать на train и неизменно применять к validation/test.</p><label className="mt-3 flex items-start gap-2 text-xs text-neutral-700"><input type="checkbox" aria-label="Подтверждаю добавление трансформированной колонки" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 accent-brand" />Подтверждаю добавление трансформированной колонки</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => void request(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Применение…" : "Добавить колонку"}</button></div>
    </div>}
    {error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}
  </section>;
}
