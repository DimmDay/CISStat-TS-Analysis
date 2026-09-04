"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "./Button";
import { getApiBase } from "../lib/apiClient";
import type {
  ApplicabilityLevel,
  BacktestResponse,
  ComparisonRankingItem,
  ModelingComparisonResponse,
  ModelingSelectionAnalysis,
  ModelingSelectionResult,
} from "../lib/modeling";


const API_BASE = getApiBase();

interface TuningResult {
  strategy?: "single" | "expanding" | "sliding";
  cohort_id?: string | null;
  folds?: Array<{ fold: number }>;
  preprocessing?: { fit_policy?: string; evaluation_scale?: string };
  tuning_id?: string | null;
  parameter_signature?: string | null;
  promoted_backtest?: BacktestResponse | null;
}

interface TuningJobResult {
  job_id: string;
  status: "in_progress" | "completed";
  completed_trials: number;
  total_trials: number;
  tuning_response: TuningResult | null;
}

interface DiagnosticItem {
  test: "ljung_box" | "jarque_bera" | "arch_lm" | "durbin_watson";
  applicable: boolean;
  statistic: number | null;
  p_value: number | null;
  status: "pass" | "warning" | "fail";
  reason?: string | null;
}

interface DiagnosticsResult {
  model_id: string;
  residuals_source: "backtest_oof" | "tuned_backtest_oof";
  params_source: "model_default" | "tuning";
  params?: Record<string, unknown>;
  parameter_signature?: string | null;
  cohort_id?: string | null;
  tuning_id?: string | null;
  backtest_run_id: string;
  residuals_signature: string;
  preprocessing?: { fit_policy?: string; evaluation_scale?: string };
  diagnostics: DiagnosticItem[];
}

interface Props {
  stageId: string;
  modelIds: string[];
  onStageComplete?: (stageId: string) => void;
  onBacktestPromoted?: (result: BacktestResponse) => void;
}

const DIAGNOSTIC_LABELS: Record<DiagnosticItem["test"], string> = {
  ljung_box: "Ljung–Box",
  jarque_bera: "Jarque–Bera",
  arch_lm: "ARCH-LM",
  durbin_watson: "Durbin–Watson",
};

function diagnosticStatus(item: DiagnosticItem): string {
  if (!item.applicable) return "Неприменимо";
  if (item.status === "pass") return "Пройдено";
  if (item.status === "warning") return "Предупреждение";
  return "Не пройдено";
}

function comparisonDiagnosticStatus(status: ComparisonRankingItem["diagnostics"]["overall_status"]): string {
  if (status === "pass") return "Пройдено";
  if (status === "warning") return "Предупреждение";
  return "Не пройдено";
}

function applicabilityLabel(level: ApplicabilityLevel): string {
  if (level === "RECOMMENDED") return "Рекомендована";
  if (level === "CONDITIONALLY_APPLICABLE") return "Условно применима";
  if (level === "NOT_RECOMMENDED") return "Не рекомендуется";
  return "Неприменима";
}

function ensembleStatusLabel(status: ModelingSelectionAnalysis["ensemble"]["status"]): string {
  if (status === "recommended") return "Рекомендован по фактическому OOF";
  if (status === "tested_no_gain") return "Проверен, улучшение не доказано";
  return "Не допущен к проверке";
}

function percent(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function apiErrorDetail(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const value = detail as Record<string, unknown>;
    const lists = [
      "missing_backtests", "missing_diagnostics", "stale_diagnostics", "missing_applicability",
    ]
      .flatMap((key) => Array.isArray(value[key]) ? value[key] as string[] : []);
    return `${typeof value.message === "string" ? value.message : `HTTP ${status}`}${lists.length ? `: ${lists.join(", ")}` : ""}`;
  }
  return `HTTP ${status}`;
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
    throw new Error(apiErrorDetail(payload.detail, response.status));
  }
  return payload;
}

export function ModelingWorkflowOverview({ stageId, modelIds, onStageComplete, onBacktestPromoted }: Props) {
  const supportedModelIds = stageId === "tuning"
    ? modelIds.filter((item) => ["ets", "ets_damped", "arima"].includes(item))
    : modelIds;
  const [modelId, setModelId] = useState(supportedModelIds[0] ?? "");
  const [comparison, setComparison] = useState<ModelingComparisonResponse | null>(null);
  const [diagnosticFilter, setDiagnosticFilter] = useState<"all" | "pass" | "warning" | "fail">("all");
  const [applicabilityFilter, setApplicabilityFilter] = useState<"all" | ApplicabilityLevel>("all");
  const [familyFilter, setFamilyFilter] = useState("all");
  const [baselineFilter, setBaselineFilter] = useState<"all" | "eligible" | "risk">("all");
  const [selectionAnalysis, setSelectionAnalysis] = useState<ModelingSelectionAnalysis | null>(null);
  const [selection, setSelection] = useState<ModelingSelectionResult | null>(null);
  const [riskAcknowledged, setRiskAcknowledged] = useState<Record<string, boolean>>({});
  const [selectionBiasAcknowledged, setSelectionBiasAcknowledged] = useState(false);
  const [ensembleNoGainAcknowledged, setEnsembleNoGainAcknowledged] = useState(false);
  const [card, setCard] = useState<{ card_id: string; card: Record<string, unknown> } | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tuningProgress, setTuningProgress] = useState<{ completed: number; total: number } | null>(null);

  useEffect(() => {
    if (!supportedModelIds.includes(modelId)) setModelId(supportedModelIds[0] ?? "");
  }, [modelId, supportedModelIds]);

  useEffect(() => {
    setResult(null);
    setError(null);
  }, [stageId]);

  const execute = useCallback(async (action: () => Promise<Record<string, unknown>>, stage: string) => {
    setLoading(true);
    setError(null);
    try {
      const value = await action();
      if (["tuning", "diagnostics"].includes(stage)) {
        setComparison(null);
        setSelectionAnalysis(null);
        setSelection(null);
        setCard(null);
        setSelectionBiasAcknowledged(false);
        setEnsembleNoGainAcknowledged(false);
        setRiskAcknowledged({});
      } else if (stage === "comparison") {
        setSelectionAnalysis(null);
        setSelection(null);
        setCard(null);
        setSelectionBiasAcknowledged(false);
        setEnsembleNoGainAcknowledged(false);
        setRiskAcknowledged({});
      }
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
    ) as unknown as ModelingComparisonResponse | null;
    if (value) setComparison(value);
  };

  const evaluateSelection = async () => {
    const value = await execute(
      () => postJson("/v1/session/modeling/selection/evaluate", {}),
      "selection_evaluation",
    ) as unknown as ModelingSelectionAnalysis | null;
    if (value) {
      setSelectionAnalysis(value);
      setSelection(null);
      setCard(null);
      setSelectionBiasAcknowledged(false);
      setEnsembleNoGainAcknowledged(false);
      setRiskAcknowledged({});
    }
  };

  const selectCandidate = async (candidateId: string, baselineRisk: boolean, ensembleNoGain = false) => {
    if (!selectionAnalysis) return;
    const value = await execute(
      () => postJson("/v1/session/modeling/select", {
        model_id: candidateId,
        selection_analysis_id: selectionAnalysis.selection_analysis_id,
        selection_signature: selectionAnalysis.selection_signature,
        acknowledge_baseline_risk: baselineRisk && Boolean(riskAcknowledged[candidateId]),
        acknowledge_selection_bias: selectionBiasAcknowledged,
        acknowledge_ensemble_no_gain: ensembleNoGain && ensembleNoGainAcknowledged,
      }),
      "selection",
    ) as unknown as ModelingSelectionResult | null;
    if (value) setSelection(value);
  };

  const selectionBaselineRisk = (item: ComparisonRankingItem): boolean => {
    if (!selectionAnalysis) return false;
    const metric = selectionAnalysis.policy.primary_metric;
    return item.metrics[metric] > selectionAnalysis.best_baseline.primary_loss;
  };

  const generateCard = async () => {
    const value = await execute(() => postJson("/v1/session/modeling/card", {}), "model_card") as unknown as { card_id: string; card: Record<string, unknown> } | null;
    if (value) setCard(value);
  };

  const runTuning = async () => {
    setTuningProgress(null);
    const value = await execute(
      async () => {
        let job = await postJson(
          "/v1/session/modeling/tuning/start", { model_id: modelId },
        ) as unknown as TuningJobResult;
        if (job.total_trials < 1 || job.total_trials > 64) {
          throw new Error("Backend вернул недопустимый размер tuning plan");
        }
        setTuningProgress({ completed: job.completed_trials, total: job.total_trials });
        while (job.status === "in_progress") {
          const expectedTrialIndex = job.completed_trials;
          job = await postJson("/v1/session/modeling/tuning/step", {
            job_id: job.job_id,
            expected_trial_index: expectedTrialIndex,
          }) as unknown as TuningJobResult;
          if (job.status === "in_progress" && job.completed_trials <= expectedTrialIndex) {
            throw new Error("Tuning progress не продвигается; повторите запуск");
          }
          setTuningProgress({ completed: job.completed_trials, total: job.total_trials });
        }
        if (!job.tuning_response) {
          throw new Error("Tuning job завершён без верифицируемого результата");
        }
        return job.tuning_response as unknown as Record<string, unknown>;
      },
      "tuning",
    ) as unknown as TuningResult | null;
    if (value?.promoted_backtest) onBacktestPromoted?.(value.promoted_backtest);
  };

  const modelSelector = (
    <select value={modelId} onChange={(event) => { setModelId(event.target.value); setResult(null); }} className="rounded border border-neutral-300 bg-white px-2 py-1 text-xs">
      {supportedModelIds.map((item) => <option key={item} value={item}>{item}</option>)}
    </select>
  );
  const tuningResult = stageId === "tuning" && result
    ? result as unknown as TuningResult
    : null;
  const diagnosticsResult = stageId === "diagnostics" && result
    ? result as unknown as DiagnosticsResult
    : null;
  const filteredRanking = comparison?.ranking.filter((item) => (
    diagnosticFilter === "all" || item.diagnostics.overall_status === diagnosticFilter
  )).filter((item) => applicabilityFilter === "all" || item.applicability_level === applicabilityFilter)
    .filter((item) => familyFilter === "all" || item.family_id === familyFilter)
    .filter((item) => (
      baselineFilter === "all"
      || (baselineFilter === "eligible" ? item.baseline_eligible : !item.baseline_eligible)
    )) ?? [];
  const comparisonFamilies = Array.from(new Set(comparison?.ranking.map((item) => item.family_id) ?? []));
  const ensembleCandidateId = selectionAnalysis?.ensemble.backtest?.model_id;
  const ensembleBaselineRisk = Boolean(
    selectionAnalysis && selectionAnalysis.ensemble.backtest
    && selectionAnalysis.ensemble.backtest.metrics[selectionAnalysis.policy.primary_metric]
      > selectionAnalysis.best_baseline.primary_loss,
  );

  return (
    <section className="flex h-[468px] min-h-0 flex-col rounded-lg border border-neutral-200 bg-white p-4" data-testid="modeling-workflow-overview">
      <div className="shrink-0">
        {stageId === "tuning" && (
          <div className="flex items-center justify-between gap-3">
            <div><h3 className="font-semibold">Тюнинг на временных folds</h3><p className="text-xs text-neutral-500">ETS, ETS Damped и ARIMA исполняют точный EDA BacktestPlan; preprocessing fit-ится только на train.</p></div>
            <div className="flex items-center gap-2">{modelSelector}<Button disabled={loading || !modelId} onClick={() => void runTuning()}>Запустить тюнинг</Button></div>
          </div>
        )}
        {stageId === "diagnostics" && (
          <div className="flex items-center justify-between gap-3">
            <div><h3 className="font-semibold">Диагностика остатков</h3><p className="text-xs text-neutral-500">Четыре теста по OOF точного backtest; для tuned-модели используется promoted trial.</p></div>
            <div className="flex items-center gap-2">{modelSelector}<Button disabled={loading || !modelId} onClick={() => void execute(() => postJson("/v1/session/modeling/diagnostics", { model_id: modelId }), "diagnostics")}>Проверить остатки</Button></div>
          </div>
        )}
        {stageId === "comparison" && (
          <div className="flex items-center justify-between"><div><h3 className="font-semibold">Сравнение моделей</h3><p className="text-xs text-neutral-500">Точные общие OOF; min-max внутри сопоставимого пула, diagnostics отдельно.</p></div><Button disabled={loading} onClick={() => void loadComparison()}>Сравнить модели</Button></div>
        )}
        {stageId === "selection" && (
          <div className="flex items-center justify-between"><div><h3 className="font-semibold">Трассируемый выбор модели</h3><p className="text-xs text-neutral-500">Primary OOF loss определяет single-кандидата; корреляция только допускает ensemble к фактической проверке.</p></div>{!comparison ? <Button disabled={loading} onClick={() => void loadComparison()}>Загрузить рейтинг</Button> : !selectionAnalysis && <Button disabled={loading} onClick={() => void evaluateSelection()}>Верифицировать выбор</Button>}</div>
        )}
        {stageId === "model_card" && (
          <div className="flex items-center justify-between"><div><h3 className="font-semibold">Model Card JSON</h3><p className="text-xs text-neutral-500">Воспроизводимый итог с checkpoint, метриками, диагностикой и ограничениями.</p></div><Button disabled={loading} onClick={() => void generateCard()}>Сформировать Model Card</Button></div>
        )}
      </div>

      {loading && <div className="flex flex-1 items-center justify-center gap-2 text-sm text-neutral-500"><Loader2 size={16} className="animate-spin" /> {stageId === "tuning" && tuningProgress ? `Trial ${tuningProgress.completed}/${tuningProgress.total}` : "Выполняется…"}</div>}
      {error && <div className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-xs text-red-700">{error}</div>}
      {!loading && comparison && ["comparison", "selection"].includes(stageId) && (
        <div className="mt-4 min-h-0 flex-1 overflow-auto feed-scroll">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded border border-blue-200 bg-blue-50 p-2 text-[10px] text-blue-900" data-testid="comparison-lineage">
            <span title={comparison.comparison_signature}><b>Comparison SHA:</b> {comparison.comparison_signature.slice(0, 13)}</span>
            <span title={comparison.cohort_id}><b>Cohort:</b> {comparison.cohort_id.slice(0, 12)}</span>
            <span><b>OOF:</b> {comparison.error_correlation.n_points} точек</span>
            <span><b>Policy:</b> diagnostics не входят в score</span>
          </div>
          {stageId === "selection" && selectionAnalysis && (
            <div className="mb-3 rounded border border-violet-200 bg-violet-50 p-3 text-[10px] text-violet-950" data-testid="selection-analysis">
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                <span title={selectionAnalysis.selection_signature}><b>Selection SHA:</b> {selectionAnalysis.selection_signature.slice(0, 13)}</span>
                <span><b>Primary:</b> {selectionAnalysis.policy.primary_metric.toUpperCase()}</span>
                <span><b>Single:</b> {selectionAnalysis.recommended_single.model_id} ({selectionAnalysis.recommended_single.primary_loss.toFixed(3)})</span>
                <span><b>Baseline:</b> {selectionAnalysis.best_baseline.model_id} ({selectionAnalysis.best_baseline.primary_loss.toFixed(3)})</span>
              </div>
              <div className="mt-2 border-t border-violet-200 pt-2" data-testid="ensemble-verdict">
                <p><b>Ensemble:</b> {ensembleStatusLabel(selectionAnalysis.ensemble.status)} · {selectionAnalysis.ensemble.member_ids.join(" + ") || "нет пары"}</p>
                <p>Корреляция ошибок: {selectionAnalysis.ensemble.error_correlation?.toFixed(3) ?? "—"}; улучшение к single: {percent(selectionAnalysis.ensemble.relative_improvement_vs_best_single)}; fold wins: {percent(selectionAnalysis.ensemble.fold_win_rate)}</p>
                {selectionAnalysis.ensemble.reasons.map((reason) => <p key={reason} className="text-amber-800">{reason}</p>)}
                {selectionAnalysis.ensemble.backtest && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {selectionAnalysis.ensemble.status === "tested_no_gain" && <label className="inline-flex items-center gap-1 text-amber-800"><input type="checkbox" checked={ensembleNoGainAcknowledged} onChange={(event) => setEnsembleNoGainAcknowledged(event.target.checked)} />Явно выбрать ensemble без доказанного выигрыша</label>}
                    {ensembleBaselineRisk && ensembleCandidateId && <label className="inline-flex items-center gap-1 text-amber-800"><input type="checkbox" checked={Boolean(riskAcknowledged[ensembleCandidateId])} onChange={(event) => setRiskAcknowledged((previous) => ({ ...previous, [ensembleCandidateId]: event.target.checked }))} />Ensemble уступает OOF baseline</label>}
                    <button
                      className="text-brand underline disabled:text-neutral-300"
                      disabled={!selectionBiasAcknowledged || (selectionAnalysis.ensemble.status === "tested_no_gain" && !ensembleNoGainAcknowledged) || (ensembleBaselineRisk && !riskAcknowledged[ensembleCandidateId!])}
                      onClick={() => void selectCandidate(
                        selectionAnalysis.ensemble.backtest!.model_id,
                        ensembleBaselineRisk,
                        selectionAnalysis.ensemble.status === "tested_no_gain",
                      )}
                    >Выбрать проверенный ensemble</button>
                  </div>
                )}
              </div>
              {selectionAnalysis.warnings.map((warning) => <p key={warning} className="mt-1 text-amber-800">{warning}</p>)}
              <label className="mt-2 inline-flex items-center gap-1 font-medium"><input aria-label="Подтвердить отсутствие независимого holdout" type="checkbox" checked={selectionBiasAcknowledged} onChange={(event) => setSelectionBiasAcknowledged(event.target.checked)} />Подтверждаю: независимый final holdout не использован</label>
            </div>
          )}
          <div className="mb-2 flex items-center gap-2">
            <label htmlFor="applicability-filter" className="text-[10px] text-neutral-500">Применимость</label>
            <select id="applicability-filter" aria-label="Фильтр применимости" value={applicabilityFilter} onChange={(event) => setApplicabilityFilter(event.target.value as typeof applicabilityFilter)} className="rounded border border-neutral-300 bg-white px-2 py-1 text-[10px]">
              <option value="all">Все уровни</option><option value="RECOMMENDED">Рекомендована</option><option value="CONDITIONALLY_APPLICABLE">Условно применима</option><option value="NOT_RECOMMENDED">Не рекомендуется</option><option value="NOT_APPLICABLE">Неприменима</option>
            </select>
            <label htmlFor="diagnostic-filter" className="text-[10px] text-neutral-500">Диагностика</label>
            <select id="diagnostic-filter" aria-label="Фильтр диагностики" value={diagnosticFilter} onChange={(event) => setDiagnosticFilter(event.target.value as typeof diagnosticFilter)} className="rounded border border-neutral-300 bg-white px-2 py-1 text-[10px]">
              <option value="all">Все статусы</option><option value="pass">Пройдено</option><option value="warning">Предупреждение</option><option value="fail">Не пройдено</option>
            </select>
            <label htmlFor="family-filter" className="text-[10px] text-neutral-500">Семейство</label>
            <select id="family-filter" aria-label="Фильтр семейства" value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)} className="rounded border border-neutral-300 bg-white px-2 py-1 text-[10px]"><option value="all">Все семейства</option>{comparisonFamilies.map((family) => <option key={family} value={family}>{family}</option>)}</select>
            <label htmlFor="baseline-filter" className="text-[10px] text-neutral-500">Baseline</label>
            <select id="baseline-filter" aria-label="Фильтр baseline" value={baselineFilter} onChange={(event) => setBaselineFilter(event.target.value as typeof baselineFilter)} className="rounded border border-neutral-300 bg-white px-2 py-1 text-[10px]"><option value="all">Все</option><option value="eligible">MASE ≤ 1.05</option><option value="risk">Риск</option></select>
          </div>
          <table className="w-full text-[10px]" data-testid="comparison-ranking"><thead><tr className="border-b text-left text-neutral-500"><th className="py-2">#</th><th>Модель</th><th>Применимость</th><th>RMSE</th><th>MASE</th><th>Score</th><th>Fold RMSE μ±σ</th><th>Диагностика</th><th>Baseline</th>{stageId === "selection" && <th>Действие</th>}</tr></thead>
            <tbody>{filteredRanking.map((item) => {
              const actualBaselineRisk = selectionBaselineRisk(item);
              return <tr key={item.model_id} className="border-b border-neutral-100"><td className="py-2">{item.rank}</td><td className="font-medium" title={`run: ${item.backtest_run_id}`}>{item.model_name}<span className="block text-[9px] font-normal text-neutral-400">{item.family_id}</span></td><td>{applicabilityLabel(item.applicability_level)}</td><td>{item.metrics.rmse.toFixed(3)}</td><td>{item.metrics.mase == null ? "—" : item.metrics.mase.toFixed(3)}</td><td title={JSON.stringify(item.normalized_metrics)}>{item.weighted_score.toFixed(3)}</td><td>{item.fold_stability.mean.toFixed(3)} ± {item.fold_stability.std.toFixed(3)}<span className="block text-[9px] text-neutral-400">top-1 {(item.fold_stability.top1_rate * 100).toFixed(0)}%</span></td><td title={`pass: ${item.diagnostics.passed.join(", ")}; warning: ${item.diagnostics.warnings.join(", ")}; fail: ${item.diagnostics.failed.join(", ")}`}>{comparisonDiagnosticStatus(item.diagnostics.overall_status)}</td><td className={item.baseline_eligible ? "text-green-700" : "text-amber-700"}>{item.baseline_note}</td>{stageId === "selection" && <td>{selectionAnalysis && actualBaselineRisk && <label className="mr-2 inline-flex items-center gap-1 text-[10px] text-amber-700"><input type="checkbox" checked={Boolean(riskAcknowledged[item.model_id])} onChange={(event) => setRiskAcknowledged((previous) => ({ ...previous, [item.model_id]: event.target.checked }))} />Уступает OOF baseline</label>}<button className="text-brand underline disabled:text-neutral-300" disabled={!selectionAnalysis || !selectionBiasAcknowledged || (actualBaselineRisk && !riskAcknowledged[item.model_id])} onClick={() => void selectCandidate(item.model_id, actualBaselineRisk)} aria-label={`Выбрать ${item.model_name}`}>Выбрать</button></td>}</tr>;
            })}</tbody>
          </table>
          {stageId === "comparison" && <div className="mt-3" data-testid="error-correlation-matrix"><h4 className="mb-1 text-[10px] font-semibold text-neutral-700">Корреляция точно совмещённых OOF-ошибок</h4><table className="text-[10px]"><thead><tr><th className="px-2 py-1" />{comparison.error_correlation.model_ids.map((model) => <th key={model} className="px-2 py-1 text-neutral-500">{model}</th>)}</tr></thead><tbody>{comparison.error_correlation.model_ids.map((model, row) => <tr key={model}><th className="px-2 py-1 text-left text-neutral-500">{model}</th>{(comparison.error_correlation.values[row] ?? []).map((value, column) => <td key={`${model}-${column}`} className="px-2 py-1 text-right">{value == null ? "—" : value.toFixed(3)}</td>)}</tr>)}</tbody></table></div>}
          {comparison.warnings.map((warning) => <p key={warning} className="mt-2 text-[10px] text-amber-700">{warning}</p>)}
        </div>
      )}
      {selection && stageId === "selection" && <div className="mt-3 rounded border border-green-200 bg-green-50 p-3 text-sm text-green-700">Выбран кандидат ({selection.selected_kind}): {selection.selected_model_id}</div>}
      {card && stageId === "model_card" && <div className="mt-4 min-h-0 flex-1 overflow-auto"><div className="mb-2 flex items-center justify-between text-xs"><span>{card.card_id}</span><a className="text-brand underline" href={`${API_BASE}/v1/session/modeling/card/${card.card_id}`} download>Скачать JSON</a></div><pre className="whitespace-pre-wrap rounded bg-neutral-950 p-3 text-[10px] text-neutral-100">{JSON.stringify(card.card, null, 2)}</pre></div>}
      {tuningResult && (
        <div className="mt-3 grid grid-cols-4 gap-2 rounded border border-blue-200 bg-blue-50 p-2 text-[10px] text-blue-900" data-testid="tuning-plan-summary">
          <span><b>Стратегия:</b> {tuningResult.strategy ?? "—"}</span>
          <span><b>Folds:</b> {tuningResult.folds?.length ?? 0} folds</span>
          <span><b>Preprocessing:</b> {tuningResult.preprocessing?.fit_policy ?? "none"}</span>
          <span title={tuningResult.cohort_id ?? undefined}><b>Cohort:</b> {tuningResult.cohort_id?.slice(0, 12) ?? "—"}</span>
        </div>
      )}
      {diagnosticsResult && (
        <div className="mt-3 min-h-0 flex-1 overflow-auto" data-testid="diagnostics-report">
          <div className="mb-3 grid grid-cols-2 gap-2 rounded border border-blue-200 bg-blue-50 p-2 text-[10px] text-blue-900" data-testid="diagnostics-lineage">
            <span><b>OOF:</b> {diagnosticsResult.residuals_source}</span>
            <span><b>Параметры:</b> {diagnosticsResult.params_source}</span>
            <span className="col-span-2 break-all"><b>Конфигурация:</b> {JSON.stringify(diagnosticsResult.params ?? {})}</span>
            <span title={diagnosticsResult.cohort_id ?? undefined}><b>Cohort:</b> {diagnosticsResult.cohort_id?.slice(0, 12) ?? "—"}</span>
            <span title={diagnosticsResult.tuning_id ?? undefined}><b>Tuning:</b> {diagnosticsResult.tuning_id?.slice(0, 12) ?? "не требуется"}</span>
            <span title={diagnosticsResult.backtest_run_id}><b>Backtest run:</b> {diagnosticsResult.backtest_run_id?.slice(0, 12)}</span>
            <span title={diagnosticsResult.parameter_signature ?? undefined}><b>Params SHA:</b> {diagnosticsResult.parameter_signature?.slice(0, 12) ?? "—"}</span>
            <span title={diagnosticsResult.residuals_signature}><b>Residuals SHA:</b> {diagnosticsResult.residuals_signature?.slice(0, 12)}</span>
            <span><b>Preprocessing:</b> {diagnosticsResult.preprocessing?.fit_policy ?? "none"}</span>
          </div>
          <table className="w-full text-xs">
            <thead><tr className="border-b text-left text-neutral-500"><th className="py-2">Проверка</th><th>Статистика</th><th>p-value</th><th>Статус</th></tr></thead>
            <tbody>{diagnosticsResult.diagnostics.map((item) => (
              <tr key={item.test} className="border-b border-neutral-100">
                <td className="py-2 font-medium">{DIAGNOSTIC_LABELS[item.test]}</td>
                <td>{item.statistic == null ? "—" : item.statistic.toFixed(4)}</td>
                <td>{item.p_value == null ? "—" : item.p_value.toFixed(4)}</td>
                <td title={item.reason ?? undefined}>{diagnosticStatus(item)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {result && !comparison && !card && stageId !== "diagnostics" && <pre className="mt-4 min-h-0 flex-1 overflow-auto whitespace-pre-wrap rounded bg-neutral-50 p-3 text-[10px]">{JSON.stringify(result, null, 2)}</pre>}
    </section>
  );
}
