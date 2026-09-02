"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { ScalingMethod, ScalingProfile } from "./PreprocessingScalingOverview";


type Preview = { method: ScalingMethod; columns: string[]; metrics: Array<{ column: string; mean_after: number | null; std_after: number | null }>; warnings: string[] };
const METHODS: Array<{ id: ScalingMethod; label: string }> = [
  { id: "standard", label: "StandardScaler — mean/std" },
  { id: "robust", label: "RobustScaler — median/IQR" },
  { id: "minmax", label: "MinMaxScaler — диапазон" },
  { id: "maxabs", label: "MaxAbsScaler — max |x|" },
  { id: "quantile", label: "QuantileTransformer — ECDF" },
];


export function PreprocessingScalingPipeline({ targetColumn, profile, onApplied }: { targetColumn: string | null; profile: ScalingProfile | null; onApplied: () => void }) {
  const [columns, setColumns] = useState<string[]>([]);
  const [method, setMethod] = useState<ScalingMethod>("standard");
  const [featureMin, setFeatureMin] = useState(0);
  const [featureMax, setFeatureMax] = useState(1);
  const [quantileLow, setQuantileLow] = useState(25);
  const [quantileHigh, setQuantileHigh] = useState(75);
  const [outputDistribution, setOutputDistribution] = useState<"uniform" | "normal">("normal");
  const [nQuantiles, setNQuantiles] = useState(1000);
  const [confirmNonlinear, setConfirmNonlinear] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!profile?.applicable) return;
    setColumns(profile.suggested_columns);
    setMethod(profile.recommended_method);
    setConfirmNonlinear(false); setPreview(null); setConfirmed(false); setError(null); setSuccess(null);
  }, [profile?.target_column, profile?.n_observations]);
  const invalidate = () => { setPreview(null); setConfirmed(false); setSuccess(null); };
  const toggleColumn = (name: string) => {
    setColumns((current) => current.includes(name) ? current.filter((column) => column !== name) : [...current, name]);
    invalidate();
  };
  const payload = (apply: boolean) => ({
    target_column: targetColumn, columns, method,
    feature_range: [featureMin, featureMax], quantile_range: [quantileLow, quantileHigh],
    output_distribution: outputDistribution, n_quantiles: nQuantiles,
    confirm_nonlinear: method === "quantile" && confirmNonlinear, apply,
  });
  const request = async (apply: boolean) => {
    if (!targetColumn) return;
    setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/preprocessing/scaling-recipes"), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload(apply)),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Не удалось проверить рецепт масштабирования");
      setPreview(data);
      if (apply) { setSuccess(`Рецепт ${data.method} сохранён для ${data.columns.length} колонок.`); setConfirmed(false); onApplied(); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось проверить рецепт масштабирования"); }
    finally { setBusy(null); }
  };

  if (!targetColumn) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Выберите числовой target.</div>;
  if (!profile) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-neutral-50 text-sm text-neutral-600">Сначала дождитесь профиля масштабов.</div>;
  if (!profile.applicable) return <div role="status" className="flex h-[420px] items-center justify-center rounded-lg bg-amber-50 px-8 text-center text-sm text-amber-800">{profile.reason}</div>;
  const eligible = profile.columns.filter((column) => column.eligible);
  const nonlinearBlocked = method === "quantile" && !confirmNonlinear;

  return <section role="region" aria-label="Мастер масштабирования" className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll"><div className="grid gap-4 lg:grid-cols-2"><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Колонки</h4><p className="mt-1 text-[10px] text-neutral-500">Auto использует непрерывные X после генерации признаков. Бинарные 0/1 и уже ограниченные sin/cos не выбираются автоматически.</p><div className="mt-2 max-h-36 overflow-y-auto rounded bg-neutral-50 p-2 feed-scroll">{eligible.map((column) => <label key={column.name} className="flex items-center justify-between gap-2 py-1 text-xs"><span><input type="checkbox" aria-label={`Масштабировать ${column.name}`} checked={columns.includes(column.name)} onChange={() => toggleColumn(column.name)} className="mr-2 accent-brand" />{column.name}</span><span className="text-[9px] text-neutral-400">{column.role === "target" ? "target" : column.role === "generated" ? "feature" : "source"}</span></label>)}</div>{columns.includes(targetColumn) && <p className="mt-2 text-[10px] text-amber-700">Target потребует inverse_transform параметрами каждого train-fold.</p>}</div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Метод</h4><label className="mt-2 block text-xs text-neutral-600">Метод масштабирования<select aria-label="Метод масштабирования" value={method} onChange={(event) => { setMethod(event.target.value as ScalingMethod); setConfirmNonlinear(false); invalidate(); }} className="mt-1 w-full rounded border px-2 py-1.5">{METHODS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>{method === "minmax" && <div className="mt-2 flex gap-2"><label className="text-[10px]">min<input aria-label="Минимум диапазона" type="number" value={featureMin} onChange={(event) => { setFeatureMin(Number(event.target.value)); invalidate(); }} className="ml-1 w-16 rounded border px-1 py-1" /></label><label className="text-[10px]">max<input aria-label="Максимум диапазона" type="number" value={featureMax} onChange={(event) => { setFeatureMax(Number(event.target.value)); invalidate(); }} className="ml-1 w-16 rounded border px-1 py-1" /></label></div>}{method === "robust" && <div className="mt-2 flex gap-2"><label className="text-[10px]">Q low<input aria-label="Нижний квантиль" type="number" value={quantileLow} onChange={(event) => { setQuantileLow(Number(event.target.value)); invalidate(); }} className="ml-1 w-16 rounded border px-1 py-1" /></label><label className="text-[10px]">Q high<input aria-label="Верхний квантиль" type="number" value={quantileHigh} onChange={(event) => { setQuantileHigh(Number(event.target.value)); invalidate(); }} className="ml-1 w-16 rounded border px-1 py-1" /></label></div>}{method === "quantile" && <div className="mt-2 rounded bg-amber-50 p-2"><label className="block text-[10px]">Распределение<select aria-label="Выходное распределение" value={outputDistribution} onChange={(event) => { setOutputDistribution(event.target.value as "uniform" | "normal"); invalidate(); }} className="ml-2 rounded border px-1 py-1"><option value="normal">normal</option><option value="uniform">uniform</option></select></label><label className="mt-2 block text-[10px]">Квантилей<input aria-label="Число квантилей" type="number" min={10} max={1000} value={nQuantiles} onChange={(event) => { setNQuantiles(Number(event.target.value)); invalidate(); }} className="ml-2 w-20 rounded border px-1 py-1" /></label><label className="mt-2 flex items-start gap-2 text-[10px] text-amber-800"><input type="checkbox" aria-label="Разрешаю нелинейное ранговое преобразование" checked={confirmNonlinear} onChange={(event) => { setConfirmNonlinear(event.target.checked); invalidate(); }} className="mt-0.5 accent-brand" />Разрешаю нелинейное ранговое преобразование, меняющее корреляции и расстояния</label></div>}</div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Диагностический preview</h4><p className="mt-1 text-[10px] text-neutral-500">Расчёт на полной истории нужен только для графиков; его параметры не сохраняются.</p><button type="button" disabled={!columns.length || nonlinearBlocked || busy !== null} onClick={() => void request(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Проверка…" : "Проверить рецепт"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs"><p>Колонок в рецепте: {preview.columns.length}</p><p>Метод: {preview.method}</p><p>Preview-метрик: {preview.metrics.length}</p></div>}</div><div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Сохранение</h4><p className="mt-1 text-xs text-neutral-600">DataFrame не меняется. Сохраняется конфигурация; fit выполняется заново внутри каждого train-fold, затем тем же scaler выполняется transform validation/test.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" aria-label="Подтверждаю сохранение рецепта" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} className="mt-0.5 accent-brand" />Подтверждаю сохранение рецепта</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => void request(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Сохранение…" : "Сохранить рецепт"}</button></div></div>{error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}</section>;
}

