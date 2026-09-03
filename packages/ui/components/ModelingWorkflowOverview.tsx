"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "./Button";
import { getApiBase } from "../lib/apiClient";


const API_BASE = getApiBase();

interface RankingItem {
  rank: number;
  model_id: string;
  model_name: string;
  family_id: string;
  metrics: { mae: number; rmse: number; mape: number; mase: number };
  weighted_score: number;
  baseline_eligible: boolean;
  baseline_note: string;
}

interface ComparisonResult {
  comparison_id: string;
  normalization: string;
  ranking: RankingItem[];
  warnings: string[];
}

interface Props {
  stageId: string;
  modelIds: string[];
  onStageComplete?: (stageId: string) => void;
}

async function postJson(path: string, body: Record<string, unknown>) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
  }
  return payload;
}

export function ModelingWorkflowOverview({ stageId, modelIds, onStageComplete }: Props) {
  const supportedModelIds = ["tuning", "diagnostics"].includes(stageId)
    ? modelIds.filter((item) => ["ets", "ets_damped", "arima"].includes(item))
    : modelIds;
  const [modelId, setModelId] = useState(supportedModelIds[0] ?? "");
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [selection, setSelection] = useState<{ selected_model_id: string; ensemble_recommended?: boolean } | null>(null);
  const [riskAcknowledged, setRiskAcknowledged] = useState<Record<string, boolean>>({});
  const [card, setCard] = useState<{ card_id: string; card: Record<string, unknown> } | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!supportedModelIds.includes(modelId)) setModelId(supportedModelIds[0] ?? "");
  }, [modelId, supportedModelIds]);

  const execute = useCallback(async (action: () => Promise<Record<string, unknown>>, stage: string) => {
    setLoading(true);
    setError(null);
    try {
      const value = await action();
      setResult(value);
      onStageComplete?.(stage);
      return value;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ошибка операции моделирования");
      return null;
    } finally {
      setLoading(false);
    }
  }, [onStageComplete]);

  const loadComparison = async () => {
    const value = await execute(
      () => postJson("/v1/session/modeling/compare", { model_ids: modelIds }),
      "comparison",
    ) as unknown as ComparisonResult | null;
    if (value) setComparison(value);
  };

  const select = async (item: RankingItem) => {
    const value = await execute(
      () => postJson("/v1/session/modeling/select", {
        model_id: item.model_id,
        acknowledge_baseline_risk: !item.baseline_eligible && Boolean(riskAcknowledged[item.model_id]),
      }),
      "selection",
    ) as unknown as { selected_model_id: string; ensemble_recommended?: boolean } | null;
    if (value) setSelection(value);
  };

  const generateCard = async () => {
    const value = await execute(() => postJson("/v1/session/modeling/card", {}), "model_card") as unknown as { card_id: string; card: Record<string, unknown> } | null;
    if (value) setCard(value);
  };

  const modelSelector = (
    <select value={modelId} onChange={(event) => setModelId(event.target.value)} className="rounded border border-neutral-300 bg-white px-2 py-1 text-xs">
      {supportedModelIds.map((item) => <option key={item} value={item}>{item}</option>)}
    </select>
  );

  return (
    <section className="flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white p-4" data-testid="modeling-workflow-overview">
      <div className="shrink-0">
        {stageId === "tuning" && (
          <div className="flex items-center justify-between gap-3">
            <div><h3 className="font-semibold">Тюнинг на временных folds</h3><p className="text-xs text-neutral-500">Доступен для ETS, ETS Damped и ARIMA; параметры оцениваются только на train.</p></div>
            <div className="flex items-center gap-2">{modelSelector}<Button disabled={loading || !modelId} onClick={() => void execute(() => postJson("/v1/session/modeling/tune", { model_id: modelId }), "tuning")}>Запустить тюнинг</Button></div>
          </div>
        )}
        {stageId === "diagnostics" && (
          <div className="flex items-center justify-between gap-3">
            <div><h3 className="font-semibold">Диагностика остатков</h3><p className="text-xs text-neutral-500">Ljung–Box, Jarque–Bera, ARCH-LM и Durbin–Watson для точной tuned-конфигурации.</p></div>
            <div className="flex items-center gap-2">{modelSelector}<Button disabled={loading || !modelId} onClick={() => void execute(() => postJson("/v1/session/modeling/diagnostics", { model_id: modelId }), "diagnostics")}>Проверить остатки</Button></div>
          </div>
        )}
        {stageId === "comparison" && (
          <div className="flex items-center justify-between"><div><h3 className="font-semibold">Сравнение моделей</h3><p className="text-xs text-neutral-500">Единое разбиение; min-max внутри сопоставимого пула.</p></div><Button disabled={loading} onClick={() => void loadComparison()}>Сравнить модели</Button></div>
        )}
        {stageId === "selection" && (
          <div className="flex items-center justify-between"><div><h3 className="font-semibold">Выбор модели</h3><p className="text-xs text-neutral-500">Top-1 — рекомендация, override остаётся явным решением аналитика.</p></div>{!comparison && <Button disabled={loading} onClick={() => void loadComparison()}>Загрузить рейтинг</Button>}</div>
        )}
        {stageId === "model_card" && (
          <div className="flex items-center justify-between"><div><h3 className="font-semibold">Model Card JSON</h3><p className="text-xs text-neutral-500">Воспроизводимый итог с checkpoint, метриками, диагностикой и ограничениями.</p></div><Button disabled={loading} onClick={() => void generateCard()}>Сформировать Model Card</Button></div>
        )}
      </div>

      {loading && <div className="flex flex-1 items-center justify-center gap-2 text-sm text-neutral-500"><Loader2 size={16} className="animate-spin" /> Выполняется…</div>}
      {error && <div className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-xs text-red-700">{error}</div>}
      {!loading && comparison && ["comparison", "selection"].includes(stageId) && (
        <div className="mt-4 min-h-0 flex-1 overflow-auto feed-scroll">
          <table className="w-full text-xs"><thead><tr className="border-b text-left text-neutral-500"><th className="py-2">#</th><th>Модель</th><th>MASE</th><th>Score</th><th>Baseline</th>{stageId === "selection" && <th>Действие</th>}</tr></thead>
            <tbody>{comparison.ranking.map((item) => <tr key={item.model_id} className="border-b border-neutral-100"><td className="py-2">{item.rank}</td><td className="font-medium">{item.model_name}</td><td>{item.metrics.mase.toFixed(3)}</td><td>{item.weighted_score.toFixed(3)}</td><td className={item.baseline_eligible ? "text-green-700" : "text-amber-700"}>{item.baseline_note}</td>{stageId === "selection" && <td>{!item.baseline_eligible && <label className="mr-2 inline-flex items-center gap-1 text-[10px] text-amber-700"><input type="checkbox" checked={Boolean(riskAcknowledged[item.model_id])} onChange={(event) => setRiskAcknowledged((previous) => ({ ...previous, [item.model_id]: event.target.checked }))} />Принимаю риск</label>}<button className="text-brand underline disabled:text-neutral-300" disabled={!item.baseline_eligible && !riskAcknowledged[item.model_id]} onClick={() => void select(item)} aria-label={`Выбрать ${item.model_name}`}>Выбрать</button></td>}</tr>)}</tbody>
          </table>
          {comparison.warnings.map((warning) => <p key={warning} className="mt-2 text-[10px] text-amber-700">{warning}</p>)}
        </div>
      )}
      {selection && stageId === "selection" && <div className="mt-3 rounded border border-green-200 bg-green-50 p-3 text-sm text-green-700">Выбрана модель: {selection.selected_model_id}</div>}
      {card && stageId === "model_card" && <div className="mt-4 min-h-0 flex-1 overflow-auto"><div className="mb-2 flex items-center justify-between text-xs"><span>{card.card_id}</span><a className="text-brand underline" href={`${API_BASE}/v1/session/modeling/card/${card.card_id}`} download>Скачать JSON</a></div><pre className="whitespace-pre-wrap rounded bg-neutral-950 p-3 text-[10px] text-neutral-100">{JSON.stringify(card.card, null, 2)}</pre></div>}
      {result && !comparison && !card && <pre className="mt-4 min-h-0 flex-1 overflow-auto whitespace-pre-wrap rounded bg-neutral-50 p-3 text-[10px]">{JSON.stringify(result, null, 2)}</pre>}
    </section>
  );
}
