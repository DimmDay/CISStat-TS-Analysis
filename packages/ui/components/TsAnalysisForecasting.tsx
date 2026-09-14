"use client";

// packages/ui/components/TsAnalysisForecasting.tsx
//
// ОБЩИЙ компонент фичи «Прогнозирование» (шестой этап пайплайна,
// spec_forecasting2.md) -- используется И embedded-, И standalone-оболочкой.
// 3-колоночный лейаут по принятому паттерну платформы (как TsAnalysisModeling):
//
//   [Левая ~240px]            [Центр flex-1]                    [Правая ~320px]
//   Этап/шаги/статус          Описание + Обзор:                 Панель управления:
//   Model Card hand-off       график факт+прогноз+интервал      селектор Model Card,
//                             ожидаемая точность (бэктест)      горизонт, alpha,
//                             предупреждения, веер              история, сравнение,
//                                                               экспорт
//
// Методологическая честность (§5.4): метрики подписаны «по результатам
// бэктеста»; прогноз потребляет Model Card и не переоткрывает выбор модели.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronDown, ChevronUp, Loader2, Play, RefreshCw, Wand2 } from "lucide-react";
import { Button } from "./Button";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { ForecastChart } from "./ForecastChart";
import { ForecastAccuracyPanel } from "./ForecastAccuracyPanel";
import { ForecastHistoryList } from "./ForecastHistoryList";
import { ForecastExportMenu } from "./ForecastExportMenu";
import { useAppShell } from "../context/AppShellContext";
import {
  ALPHA_SOURCE_LABELS,
  CI_METHOD_LABELS,
  type CardSummary,
  type ForecastRun,
  compareForecasts,
  computeSensitivity,
  fetchCardSummaries,
  fetchForecastHistory,
  generateForecast,
} from "../lib/forecasting";

const FORECASTING_DESCRIPTION = `Цель: построить реальный прогноз вперёд по выбранной Model Card -- финальный рефит на ВСЕЙ доступной истории с замороженными гиперпараметрами (после кросс-валидации модель переобучается на всех данных -- Hyndman & Athanasopoulos, FPP3, гл. 5.9).

Метрики: точечный прогноз всегда из сертифицированного реестра исполнения; интервал -- методом по семейству модели (аналитический / параметрическая симуляция / нативный адаптер / эмпирический на OOF-остатках бэктеста). Каждая граница интервала инвертируется отдельно через нелинейную обратную трансформацию -- без схлопывания к медиане.

Алгоритм backend: POST /v1/session/modeling/forecast -> final fit (полная история) -> MODEL_EXECUTION_REGISTRY.execute -> интервалы -> аномалии (detect_outlier_mask) -> ForecastRun в артефактах сессии с событием трассы forecast_generated.`;

const FORECASTING_HELP = `Справка этапа «Прогнозирование»

• Прогноз строится ТОЛЬКО по Model Card, созданной на вкладке «Моделирование»: модель, гиперпараметры и предобработка уже зафиксированы и верифицированы бэктестом. Прогноз не выбирает модель заново.

• Горизонт по умолчанию -- тот же, что проверен бэктестом (training.horizon). Больший горизонт допустим: аналитические/симуляционные интервалы экстраполируют модельную структуру (мягкое предупреждение), а эмпирический интервал за проверенной границей честно переходит на квантиль последнего валидированного шага (консервативная оценка).

• Уровень доверия: alpha=0.05 -> 95% интервал. Для нейро-моделей допустимы только 0.01/0.05/0.10 (сертифицированный whitelist адаптеров). Prophet/TBATS и модели на деревьях отдают нативные интервалы на фиксированном уровне адаптера (80%/90%) -- запрошенная alpha не подменяется другим методом, а дисклоужерится.

• «Ожидаемая точность» -- это исторические метрики модели на бэктесте, а НЕ точность этого прогноза: у будущих точек нет фактов, ошибка станет известна только после наступления будущего.

• Чувствительность показывает веер прогнозов на границах уже исследованного тюнингом пространства параметров -- за его пределами модель не проверена на ваших данных.`;

const STEP_LABELS: Array<{ key: string; label: string }> = [
  { key: "generate", label: "Прогноз построен" },
  { key: "compare", label: "Сравнение прогнозов" },
  { key: "sensitivity", label: "Чувствительность" },
  { key: "export", label: "Экспорт" },
];

function stepStatus(forecasts: ForecastRun[], active: ForecastRun | null, key: string): CheckStatus {
  if (forecasts.length === 0) return "pending";
  if (key === "generate") return "done";
  if (key === "compare") {
    return forecasts.some((run) =>
      (run.trace_events ?? []).some((event) => event.event_type === "forecast_compared"),
    ) ? "done" : "pending";
  }
  if (key === "sensitivity") {
    const source = active ?? forecasts[forecasts.length - 1];
    return source?.sensitivity ? "done" : "pending";
  }
  if (key === "export") {
    return forecasts.some((run) =>
      (run.trace_events ?? []).some((event) => event.event_type === "forecast_exported"),
    ) ? "done" : "pending";
  }
  return "pending";
}

const ALPHA_OPTIONS = [0.01, 0.05, 0.10];

export function TsAnalysisForecasting() {
  const { activeDataset, stages, addLogEntry } = useAppShell();

  const [cards, setCards] = useState<CardSummary[]>([]);
  const [cardsLoading, setCardsLoading] = useState(true);
  const [cardsError, setCardsError] = useState<string | null>(null);
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [horizon, setHorizon] = useState<number | null>(null);
  const [alpha, setAlpha] = useState<number>(0.05);

  const [forecasts, setForecasts] = useState<ForecastRun[]>([]);
  const [activeForecastId, setActiveForecastId] = useState<string | null>(null);
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([]);
  const [comparison, setComparison] = useState<ForecastRun[] | null>(null);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [descriptionSection, setDescriptionSection] = useState<"main" | "help">("main");

  const refreshAll = useCallback(async () => {
    setCardsLoading(true);
    setError(null);
    try {
      const [cardSummaries, history] = await Promise.all([
        fetchCardSummaries(),
        fetchForecastHistory(),
      ]);
      setCards(cardSummaries);
      setForecasts(history);
      setCardsError(null);
      setSelectedCardId((current) => {
        if (current && cardSummaries.some((card) => card.card_id === current)) return current;
        return cardSummaries.length > 0 ? cardSummaries[cardSummaries.length - 1].card_id : null;
      });
      setActiveForecastId((current) => {
        if (current && history.some((run) => run.forecast_id === current)) return current;
        return history.length > 0 ? history[history.length - 1].forecast_id : null;
      });
    } catch (exc) {
      setCardsError(exc instanceof Error ? exc.message : "Ошибка загрузки состояния");
    } finally {
      setCardsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const activeForecast = useMemo(
    () => forecasts.find((run) => run.forecast_id === activeForecastId) ?? null,
    [forecasts, activeForecastId],
  );
  const selectedCard = cards.find((card) => card.card_id === selectedCardId) ?? null;
  const effectiveHorizon = horizon ?? selectedCard?.horizon ?? 12;

  const generate = useCallback(async () => {
    if (!selectedCardId) return;
    setBusy("generate");
    setError(null);
    try {
      const run = await generateForecast({
        model_card_id: selectedCardId,
        horizon: horizon ?? null,
        alpha,
      });
      addLogEntry(
        "INFO",
        `Прогноз построен: ${run.model_name}, горизонт ${run.horizon}, интервал ${Math.round((1 - run.alpha_effective) * 100)}% (${run.ci_method})`,
      );
      setForecasts((previous) => [...previous, run]);
      setActiveForecastId(run.forecast_id);
      setDescriptionSection("main");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "Ошибка построения прогноза";
      setError(message);
      addLogEntry("ERROR", `Прогноз не построен: ${message}`);
    } finally {
      setBusy(null);
    }
  }, [selectedCardId, horizon, alpha, addLogEntry]);

  const runCompare = useCallback(async () => {
    if (selectedForCompare.length < 2) return;
    setBusy("compare");
    setError(null);
    try {
      const compared = await compareForecasts(selectedForCompare);
      setForecasts((previous) =>
        previous.map((run) => compared.find((item) => item.forecast_id === run.forecast_id) ?? run),
      );
      setComparison(compared);
      addLogEntry("INFO", `Сравнение прогнозов: ${compared.map((run) => run.model_name).join(" · ")}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Ошибка сравнения");
    } finally {
      setBusy(null);
    }
  }, [selectedForCompare, addLogEntry]);

  const runSensitivity = useCallback(async () => {
    if (!activeForecast) return;
    setBusy("sensitivity");
    setError(null);
    try {
      const updated = await computeSensitivity(activeForecast.forecast_id);
      setForecasts((previous) =>
        previous.map((run) => (run.forecast_id === updated.forecast_id ? updated : run)),
      );
      addLogEntry(
        "INFO",
        `Веер чувствительности: ${updated.sensitivity?.combos.length ?? 0} комбинаций по осям ${(updated.sensitivity?.varied_axes ?? []).join(", ")}`,
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Ошибка расчёта чувствительности");
    } finally {
      setBusy(null);
    }
  }, [activeForecast, addLogEntry]);

  const toggleCompare = useCallback((forecastId: string) => {
    setSelectedForCompare((previous) =>
      previous.includes(forecastId)
        ? previous.filter((item) => item !== forecastId)
        : [...previous, forecastId].slice(-3),
    );
    setComparison(null);
  }, []);

  const forecastStage = stages["forecasting"] ?? "pending";
  const modelingStage = stages["modeling"] ?? "pending";
  const hasCards = cards.length > 0;
  const phase: "no-dataset" | "no-modeling" | "no-card" | "ready" = !activeDataset
    ? "no-dataset"
    : modelingStage !== "done"
      ? "no-modeling"
      : !hasCards
        ? "no-card"
        : "ready";

  const descriptionContent = descriptionSection === "help" ? FORECASTING_HELP : FORECASTING_DESCRIPTION;

  // ── Рендер ──
  return (
    <div className="flex gap-6">
      {/* ══ ЛЕВАЯ КОЛОНКА ══ */}
      <aside className="w-60 shrink-0 flex flex-col gap-3 pt-1">
        <div className="mb-1">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-neutral-900">Прогнозирование</h2>
            <button
              type="button"
              onClick={() => setDescriptionSection("help")}
              className="flex h-6 w-6 items-center justify-center rounded-full border border-neutral-300 text-xs text-neutral-500 hover:border-brand hover:text-brand"
              aria-label="Справка по этапу"
              data-testid="forecasting-help-btn"
            >
              ?
            </button>
          </div>
          <p className="mt-0.5 text-[11px] text-neutral-500">
            Шестой этап: реальный прогноз по зафиксированной Model Card
          </p>
        </div>

        <div className="rounded border border-neutral-200 bg-white px-2.5 py-2 text-[10px]" data-testid="stage-status-card">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-neutral-700">Стадия пайплайна</span>
            <span className={forecastStage === "done" ? "text-green-700" : forecastStage === "in_progress" ? "text-blue-700" : "text-neutral-500"}>
              {forecastStage === "done" ? "завершён" : forecastStage === "in_progress" ? "в процессе" : "не начат"}
            </span>
          </div>
          <p className="mt-1 text-neutral-500">
            Завершение фиксируется первым экспортом прогноза (derived-статус, §10.5).
          </p>
        </div>

        <div className="rounded border border-neutral-200 bg-white px-2.5 py-2">
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-400">
            Шаги этапа
          </p>
          <ul className="flex flex-col gap-1" data-testid="forecasting-steps">
            {STEP_LABELS.map((step) => (
              <li key={step.key} className="flex items-center gap-2 text-[11px] text-neutral-700">
                <StatusIcon status={stepStatus(forecasts, activeForecast, step.key)} size={14} />
                {step.label}
              </li>
            ))}
          </ul>
        </div>

        {selectedCard && (
          <div className="rounded border border-neutral-200 bg-white px-2.5 py-2 text-[10px]" data-testid="card-handoff">
            <p className="font-semibold text-neutral-700">Model Card</p>
            <p className="mt-1 text-neutral-600">{selectedCard.model_name ?? selectedCard.model_id}</p>
            <p className="mt-0.5 text-neutral-400">
              model: {selectedCard.model_id} · horizon бэктеста: {selectedCard.horizon ?? "—"}
            </p>
            <p className="mt-1 truncate font-mono text-neutral-400" title={selectedCard.fingerprint ?? ""}>
              SHA {selectedCard.fingerprint?.slice(0, 12) ?? "—"}…
            </p>
          </div>
        )}

        <button
          type="button"
          onClick={() => void refreshAll()}
          className="mt-auto flex items-center justify-center gap-1.5 rounded border border-neutral-200 px-2 py-1.5 text-[11px] text-neutral-600 hover:border-brand hover:text-brand"
          data-testid="refresh-state-btn"
        >
          <RefreshCw size={12} /> Обновить состояние
        </button>
      </aside>

      {/* ══ ЦЕНТР ══ */}
      <main className="min-w-0 flex-1 flex flex-col gap-4">
        <div>
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-neutral-800">
              {descriptionSection === "help" ? "Справка" : "Описание этапа"}
            </h3>
            {descriptionSection === "help" && (
              <button
                type="button"
                onClick={() => setDescriptionSection("main")}
                className="text-[11px] font-medium text-brand underline"
              >
                К описанию этапа
              </button>
            )}
          </div>
          <div className="relative">
            <div
              className={`mt-1 rounded-lg border px-4 py-3 text-xs text-neutral-600 whitespace-pre-wrap ${
                descriptionExpanded
                  ? "absolute top-0 left-0 right-0 z-20 max-h-[calc(100vh-180px)] min-h-[220px] overflow-y-auto border-brand/30 bg-brand-light shadow-lg"
                  : "max-h-[220px] min-h-[220px] overflow-hidden bg-brand-light/50 border-neutral-200"
              }`}
            >
              {descriptionContent}
            </div>
            <button
              onClick={() => setDescriptionExpanded((value) => !value)}
              className="absolute bottom-1 left-1/2 flex -translate-x-1/2 items-center justify-center rounded-t bg-brand/10 px-3 py-0.5 text-brand hover:bg-brand/20"
              aria-label={descriptionExpanded ? "Свернуть описание" : "Развернуть описание"}
              data-testid="desc-toggle-btn"
            >
              {descriptionExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700" role="alert" data-testid="forecasting-error">
            Ошибка: {error}
          </div>
        )}

        {cardsError && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800" data-testid="cards-error">
            {cardsError}
          </div>
        )}

        {phase === "no-dataset" && (
          <div className="flex h-[468px] items-center justify-center rounded-lg border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-800" data-testid="no-dataset-gate">
            Загрузите датасет на вкладке «Загрузка», чтобы начать прогнозирование.
          </div>
        )}
        {phase === "no-modeling" && (
          <div className="flex h-[468px] items-center justify-center rounded-lg border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-800" data-testid="no-modeling-gate">
            Прогноз строится по Model Card. Завершите этап «Моделирование»: сравнение, выбор
            модели и создание Model Card.
          </div>
        )}
        {phase === "no-card" && (
          <div className="flex h-[468px] items-center justify-center rounded-lg border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-800" data-testid="no-card-gate">
            Model Card не найдена. Сформируйте её на вкладке{" "}
            <Link href="/modeling" className="ml-1 underline">Моделирование</Link>, затем вернитесь.
          </div>
        )}

        {phase === "ready" && !activeDataset && null}

        {phase === "ready" && (
          <>
            {!activeForecast && !busy && (
              <div className="flex h-[468px] items-center justify-center rounded-lg border border-neutral-200 bg-neutral-50 text-sm text-neutral-500" data-testid="empty-state">
                Прогнозов пока нет. Выберите Model Card справа и постройте прогноз.
              </div>
            )}
            {busy === "generate" && (
              <div className="flex h-[468px] items-center justify-center gap-2 rounded-lg border border-neutral-200 bg-white text-sm text-neutral-500" data-testid="generating-state">
                <Loader2 size={16} className="animate-spin" /> Финальный рефит и прогноз…
              </div>
            )}
            {comparison && comparison.length >= 2 && (
              <div className="rounded-lg border border-neutral-200 bg-white p-4" data-testid="comparison-view">
                <h4 className="mb-2 text-sm font-semibold text-neutral-800">
                  Наложение прогнозов ({comparison.length})
                </h4>
                <ul className="mb-2 flex flex-wrap gap-2 text-[10px] text-neutral-600">
                  {comparison.map((run) => (
                    <li key={run.forecast_id} className="rounded bg-brand/10 px-2 py-0.5 text-brand">
                      {run.model_name} · H={run.horizon}
                    </li>
                  ))}
                </ul>
                <p className="text-[11px] text-neutral-500">
                  Сравнение -- наложение уже построенных артефактов (без нового ранжирования, §5.6).
                  Детали каждого прогноза -- в истории справа.
                </p>
              </div>
            )}
            {activeForecast && (
              <>
                <div id="forecast-chart-export-anchor" data-testid="forecast-chart-anchor">
                  <ForecastChart run={activeForecast} />
                </div>
                <ForecastAccuracyPanel run={activeForecast} />
                {(activeForecast.warnings ?? []).length > 0 && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3" data-testid="warnings-block">
                    <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-amber-800">
                      <AlertTriangle size={13} /> Предупреждения
                    </div>
                    <ul className="list-disc space-y-1 pl-5 text-[11px] text-amber-800">
                      {(activeForecast.warnings ?? []).map((warning, index) => (
                        <li key={index}>{warning}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {activeForecast.sensitivity && (
                  <div className="rounded-lg border border-neutral-200 bg-white p-4" data-testid="sensitivity-view">
                    <h4 className="mb-1 text-sm font-semibold text-neutral-800">
                      Веер чувствительности · {activeForecast.sensitivity.combos.length} комбинаций
                    </h4>
                    <p className="mb-2 text-[11px] text-neutral-500">
                      Оси: {activeForecast.sensitivity.varied_axes.join(", ")}
                      {activeForecast.sensitivity.truncated ? " · усечено до 8 комбинаций" : ""}
                    </p>
                    <ul className="flex flex-wrap gap-2 text-[10px] text-neutral-600">
                      {activeForecast.sensitivity.combos.map((combo, index) => (
                        <li
                          key={index}
                          className="rounded bg-neutral-100 px-2 py-1"
                          title={Object.entries(combo.params).map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(", ")}
                        >
                          #{index + 1}: {combo.points[combo.points.length - 1]?.value?.toFixed(2)} (шаг {combo.points.length})
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="text-[10px] text-neutral-400" data-testid="lineage-note">
                  Прогноз {activeForecast.forecast_id.slice(0, 8)} · карта {activeForecast.model_card_id.slice(0, 8)} ·
                  метод {CI_METHOD_LABELS[activeForecast.ci_method]} · alpha {activeForecast.alpha_effective} (
                  {ALPHA_SOURCE_LABELS[activeForecast.alpha_source]})
                </div>
              </>
            )}
          </>
        )}
      </main>

      {/* ══ ПРАВАЯ КОЛОНКА ══ */}
      <aside className="w-80 shrink-0 pt-1">
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-neutral-200 bg-white p-4" data-testid="control-panel">
            <h4 className="mb-3 text-sm font-semibold text-neutral-800">Панель управления</h4>

            <label className="mb-1 block text-[11px] font-medium text-neutral-600" htmlFor="card-select">
              Model Card
            </label>
            <select
              id="card-select"
              value={selectedCardId ?? ""}
              onChange={(event) => {
                setSelectedCardId(event.target.value || null);
                setHorizon(null);
              }}
              disabled={cards.length === 0}
              className="mb-1 w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-xs"
              data-testid="card-select"
            >
              {cards.length === 0 && <option value="">Нет Model Card</option>}
              {cards.map((card) => (
                <option key={card.card_id} value={card.card_id}>
                  {card.model_name ?? card.model_id} ({card.model_id})
                </option>
              ))}
            </select>

            <div className="mb-1 mt-3 grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block text-[11px] font-medium text-neutral-600" htmlFor="horizon-input">
                  Горизонт
                </label>
                <input
                  id="horizon-input"
                  type="number"
                  min={1}
                  max={120}
                  value={effectiveHorizon}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    setHorizon(Number.isFinite(value) && value > 0 ? Math.floor(value) : null);
                  }}
                  className="w-full rounded border border-neutral-300 px-2 py-1.5 text-xs"
                  data-testid="horizon-input"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-neutral-600" htmlFor="alpha-select">
                  Уровень (1−α)
                </label>
                <select
                  id="alpha-select"
                  value={alpha}
                  onChange={(event) => setAlpha(Number(event.target.value))}
                  className="w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-xs"
                  data-testid="alpha-select"
                >
                  {ALPHA_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {Math.round((1 - value) * 100)}%
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <p className="mb-3 text-[10px] text-neutral-400">
              Дефолт горизонта -- проверенный бэктестом; больше -- с честным предупреждением.
            </p>

            <Button
              onClick={() => void generate()}
              disabled={phase !== "ready" || !selectedCardId || busy !== null}
              className="w-full text-xs"
              data-testid="generate-btn"
            >
              {busy === "generate" ? (
                <span className="flex items-center justify-center gap-1">
                  <Loader2 size={12} className="animate-spin" /> Строю прогноз…
                </span>
              ) : (
                <span className="flex items-center justify-center gap-1">
                  <Play size={12} /> Построить прогноз
                </span>
              )}
            </Button>
          </div>

          <div className="rounded-lg border border-neutral-200 bg-white p-4" data-testid="history-panel">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-sm font-semibold text-neutral-800">История прогнозов</h4>
              <Button
                variant="secondary"
                onClick={() => void runCompare()}
                disabled={selectedForCompare.length < 2 || busy !== null}
                className="!px-2 !py-1 !text-[10px]"
                data-testid="compare-btn"
              >
                {busy === "compare" ? (
                  <Loader2 size={11} className="animate-spin" />
                ) : (
                  `Сравнить (${selectedForCompare.length})`
                )}
              </Button>
            </div>
            <ForecastHistoryList
              forecasts={forecasts}
              activeForecastId={activeForecastId}
              selectedForCompare={selectedForCompare}
              onSelect={(forecastId) => {
                setActiveForecastId(forecastId);
                setComparison(null);
              }}
              onToggleCompare={toggleCompare}
            />
          </div>

          {activeForecast && (
            <div className="rounded-lg border border-neutral-200 bg-white p-4" data-testid="sensitivity-panel">
              <h4 className="mb-2 text-sm font-semibold text-neutral-800">Чувствительность</h4>
              <Button
                variant="secondary"
                onClick={() => void runSensitivity()}
                disabled={busy !== null}
                className="w-full text-xs"
                data-testid="sensitivity-btn"
              >
                {busy === "sensitivity" ? (
                  <span className="flex items-center justify-center gap-1">
                    <Loader2 size={12} className="animate-spin" /> Считаю веер…
                  </span>
                ) : (
                  <span className="flex items-center justify-center gap-1">
                    <Wand2 size={12} /> Веер по границам param_space
                  </span>
                )}
              </Button>
              <p className="mt-1.5 text-[10px] text-neutral-400">
                Только в границах уже исследованного тюнингом пространства (§5.7).
              </p>
            </div>
          )}

          <div className="rounded-lg border border-neutral-200 bg-white p-4" data-testid="export-panel">
            <h4 className="mb-2 text-sm font-semibold text-neutral-800">Экспорт</h4>
            <ForecastExportMenu
              forecastId={activeForecast?.forecast_id ?? null}
              chartContainerId="forecast-chart-export-anchor"
              onExported={(format) => {
                addLogEntry("INFO", `Экспорт прогноза: ${format.toUpperCase()}`);
                void refreshAll();
              }}
            />
          </div>
        </div>
      </aside>
    </div>
  );
}
