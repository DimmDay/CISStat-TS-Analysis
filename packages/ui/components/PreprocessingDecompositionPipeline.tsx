"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { PreprocessingDecompositionProfile } from "./PreprocessingDecompositionOverview";


type Output = "components" | "seasonally_adjusted" | "detrended";

const OUTPUTS: Array<{ id: Output; label: string; help: string }> = [
  { id: "components", label: "Компоненты", help: "Добавить *_trend, *_seasonal и *_resid." },
  { id: "seasonally_adjusted", label: "Сезонно скорректированный ряд", help: "Добавить исходный ряд минус сезонная компонента." },
  { id: "detrended", label: "Ряд без тренда", help: "Добавить исходный ряд минус тренд." },
];

interface CorrectionResponse {
  applied: boolean; period: number; rows_before: number; rows_after: number;
  columns_before: number; columns_after: number; added_columns: string[];
}

async function detail(response: Response): Promise<string> {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

export function PreprocessingDecompositionPipeline({
  column, profile, onApplied,
}: {
  column: string | null;
  profile: PreprocessingDecompositionProfile | null;
  onApplied: () => void;
}) {
  const [period, setPeriod] = useState(profile?.period ? String(profile.period) : "");
  const [robust, setRobust] = useState(true);
  const [outputs, setOutputs] = useState<Output[]>(["components"]);
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => { setPeriod(profile?.period ? String(profile.period) : ""); setPreview(null); setConfirmed(false); }, [column, profile?.period]);

  const invalidate = () => { setPreview(null); setConfirmed(false); setError(null); setSuccess(null); };
  const toggle = (output: Output) => {
    invalidate();
    setOutputs((current) => current.includes(output) ? current.filter((item) => item !== output) : [...current, output]);
  };
  const request = async (apply: boolean) => {
    if (!column) return;
    setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/preprocessing/decomposition-outputs"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ column, period: period ? Number(period) : null, robust, outputs, apply }),
      });
      if (!response.ok) throw new Error(await detail(response));
      const data: CorrectionResponse = await response.json();
      setPreview(data); setConfirmed(false);
      if (apply) { setSuccess("Новые колонки сохранены в активном датасете"); onApplied(); }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось выполнить декомпозицию");
    } finally { setBusy(null); }
  };

  return <section role="region" aria-label="Мастер декомпозиции ряда" className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll">
    {!column ? <p role="status" className="rounded bg-amber-50 p-3 text-sm text-amber-800">Выберите числовой исследуемый признак.</p> : <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Параметры STL</h4><label className="mt-2 block text-xs text-neutral-600">Сезонный период<input aria-label="Сезонный период" type="number" min={2} value={period} onChange={(event) => { invalidate(); setPeriod(event.target.value); }} placeholder="автоматически" className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm" /></label><label className="mt-3 flex items-start gap-2 text-xs text-neutral-700"><input aria-label="Робастный STL" type="checkbox" checked={robust} onChange={(event) => { invalidate(); setRobust(event.target.checked); }} className="mt-0.5 accent-brand" />Робастные веса STL — рекомендуются после первичной обработки выбросов.</label></div>
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Выходные колонки</h4><div className="mt-2 space-y-2">{OUTPUTS.map((item) => <label key={item.id} className="flex items-start gap-2 text-xs text-neutral-700"><input type="checkbox" aria-label={item.label} checked={outputs.includes(item.id)} onChange={() => toggle(item.id)} className="mt-0.5 accent-brand" /><span><b className="font-medium">{item.label}</b><span className="block text-[10px] text-neutral-500">{item.help}</span></span></label>)}</div><p className="mt-2 text-[10px] text-neutral-500">Исходная колонка не изменяется. Это сохраняет возможность реконструкции ряда.</p></div>
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на глубокой копии датасета.</p><button type="button" disabled={busy !== null || outputs.length === 0} onClick={() => void request(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs text-neutral-700"><p>Колонок: {preview.columns_before} → {preview.columns_after}</p><p>Будут добавлены: {preview.added_columns.join(", ")}</p></div>}</div>
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Применение</h4><p className="mt-1 text-xs text-neutral-500">Для моделирования не используйте компоненты, оценённые на всём ряде: внутри backtest STL должен обучаться заново только на train.</p><label className="mt-3 flex items-start gap-2 text-xs text-neutral-700"><input type="checkbox" aria-label="Подтверждаю добавление колонок декомпозиции" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 accent-brand" />Подтверждаю добавление колонок</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => void request(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Применение…" : "Добавить колонки"}</button></div>
    </div>}
    {error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
    {success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}
  </section>;
}
