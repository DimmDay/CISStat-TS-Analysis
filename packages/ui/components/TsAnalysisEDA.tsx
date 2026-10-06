"use client";

// packages/ui/components/TsAnalysisEDA.tsx
//
// ОБЩИЙ компонент фичи "Разведочный EDA" -- используется И embedded-,
// И standalone-приложением. Структура повторяет 3-колоночный лейаут
// TsAnalysisPreprocessing/TsAnalysisValidation.
//
// Компоновка:
//   [Левая ~240px]     [Центр flex-1]         [Правая ~320px]
//   EDA  [Справка]      Описание               Исследование: ...
//   ▼ Признак: price   [текстовое поле]       описание
//   0/10 ░░░░░░         Обзор: ...             [бейдж]
//   ┌─Описательные──○─┐  [график]              [Метрики и алгоритм]
//   ├─ACF/PACF────○─┤   [карточки]            [Полный пайплайн]
//   └────────────────┘                         [Запустить анализ]

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { sessionApiUrl, progressApiUrl } from "../lib/apiClient";
import { useTargetColumn } from "../hooks/useTargetColumn";
import { useAppShell } from "../context/AppShellContext";
import { Button } from "./Button";
import { StepperNextModuleButton } from "./StepperNextModuleButton";
import {
  EdaDescriptiveOverview,
  type DescriptiveStatsResponse,
} from "./EdaDescriptiveOverview";
import {
  EdaCorrelationOverview,
  type EdaCorrelationResponse,
} from "./EdaCorrelationOverview";
import {
  EdaIhOverview,
  type EdaIhParameters,
  type EdaIhResponse,
} from "./EdaIhOverview";
import {
  EdaSeasonalityOverview,
  type EdaSeasonalityParameters,
  type EdaSeasonalityResponse,
} from "./EdaSeasonalityOverview";
import {
  EdaStationarityOverview,
  type EdaStationarityParameters,
  type EdaStationarityResponse,
  type StationarityConsensus,
} from "./EdaStationarityOverview";
import {
  EdaDistributionOverview,
  type EdaDistributionParameters,
  type EdaDistributionResponse,
} from "./EdaDistributionOverview";
import {
  EdaStructuralBreaksOverview,
  type EdaStructuralBreaksParameters,
  type EdaStructuralBreaksResponse,
} from "./EdaStructuralBreaksOverview";
import {
  EdaFeatureSelectionOverview,
  type EdaFeatureSelectionParameters,
  type EdaFeatureSelectionResponse,
} from "./EdaFeatureSelectionOverview";
import {
  EdaValidationStrategyOverview,
  type EdaValidationStrategyParameters,
  type EdaValidationStrategyResponse,
} from "./EdaValidationStrategyOverview";
import {
  EdaModelMatrixOverview,
  type EdaModelMatrixParameters,
  type EdaModelMatrixResponse,
} from "./EdaModelMatrixOverview";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { DatasetPassportPanel } from "./DatasetPassportPanel";
import { describeNode } from "../lib/knowledge/knowledge";
// ── Единый реестр остановок EDA (spec_progress.md §12 п.2, Task PROGR-2) ──
// Источник id/label/description -- общий JSON, читаемый также
// app/core/pipeline_graph.py (граф сервиса «Прогресс»). Вшитого списка
// id в компоненте больше нет; рассинхрон ловится тестами
// (tests/api/test_pipeline_graph.py, packages/ui/eda-checks-json.test.ts).
import edaChecksJson from "../../../shared/pipeline_nodes/eda_checks.json";

// ── Типы ──────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
}

interface EdaCheckDef {
  id: string;
  label: string;
  description: string;
}

// ── 10 исследований EDA ──────────────────────────────────────
// id/label/description -- из общего JSON (§12 п.2), порядок объектов =
// порядок остановок степпера. status/count -- рантайм-состояние
// компонента, исходные значения -- pending/null (как до выноса).

const EDA_CHECK_DEFS = edaChecksJson.nodes as EdaCheckDef[];

const CHECKS: Check[] = EDA_CHECK_DEFS.map((def) => ({
  id: def.id,
  label: def.label,
  description: def.description,
  status: "pending" as CheckStatus,
  count: null,
}));

// ── Справка по целям модуля «Разведочный EDA» ────────────────






















async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить описательные статистики (HTTP ${response.status})`;
}

async function correlationResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось рассчитать ACF/PACF (HTTP ${response.status})`;
}

async function ihResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось выполнить IH-анализ (HTTP ${response.status})`;
}

async function seasonalityResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось выполнить спектральный анализ (HTTP ${response.status})`;
}

async function stationarityResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось проверить стационарность (HTTP ${response.status})`;
}

async function distributionResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось исследовать распределение (HTTP ${response.status})`;
}

async function structuralResponseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось исследовать структурные сдвиги (HTTP ${response.status})`;
}

async function featureSelectionResponseDetail(response: Response): Promise<string> {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch {}
  return `Не удалось выполнить отбор признаков (HTTP ${response.status})`;
}

async function validationStrategyResponseDetail(response: Response): Promise<string> {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch {}
  return `Не удалось построить стратегию валидации (HTTP ${response.status})`;
}

async function modelMatrixResponseDetail(response: Response): Promise<string> {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch {}
  return `Не удалось построить матрицу моделей (HTTP ${response.status})`;
}

function formatMetric(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const normalized = Object.is(value, -0) ? 0 : value;
  return normalized.toLocaleString("ru-RU", { maximumFractionDigits: 3 });
}

function stationarityConsensusLabel(consensus: StationarityConsensus | null | undefined): string {
  if (consensus === "stationary") return "Стационарен";
  if (consensus === "trend-stationary") return "Вокруг тренда";
  if (consensus === "non-stationary") return "Нестационарен";
  if (consensus === "inconclusive") return "Неопределённо";
  return "—";
}

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisEDA() {
  const { activeDataset } = useAppShell();
  // dataset_id меняется даже при повторной загрузке файла с тем же именем.
  // Имя остаётся fallback для старых ответов/тестовых фикстур.
  const datasetKey = activeDataset?.datasetId ?? activeDataset?.name;
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  // Инвариант информативности (2026-09-15, зеркально VALID-2/PREPR-2):
  // активная остановка степпера АВТОМАТИЧЕСКИ загружает в «Описание»
  // содержимое «Метрики и алгоритм» данной остановки (и делает кнопку
  // активной) — вне зависимости от статуса остановки. Контент метрик —
  // статические константы компонента (без зависимостей от
  // /dataset/eda-*-профилей и наличия датасета), поэтому автозагрузка
  // возможна всегда. Секция null более не производится: начальное
  // состояние — метрики первой активной остановки («Описательные
  // статистики»); placeholder-ветка ниже остаётся как defense-in-depth
  // при недостижимом null.
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | null>("metrics");
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // Единый исследуемый признак всей платформы. Backend исключает
  // date/year-похожие числовые колонки из АВТОМАТИЧЕСКОЙ рекомендации,
  // а явный выбор пользователя сохраняется в AnalysisSession и доступен
  // на остальных вкладках через тот же GET/POST /target-column.
  const {
    targetColumn: activeFeature,
    availableColumns: numericFeatures,
    hasDataset,
    loading: targetLoading,
    error: targetError,
    setColumn: setActiveFeature,
    passportResetNotice,
  } = useTargetColumn(datasetKey);

  // ── Остановка «Описательные статистики»: реальные данные ──
  // Переиспользуем endpoint вкладки «Загрузка»: он уже считает профиль по
  // полному session.dataframe и честно сохраняет разреженные колонки.
  const [descriptiveProfile, setDescriptiveProfile] = useState<DescriptiveStatsResponse | null>(null);
  const [descriptiveLoading, setDescriptiveLoading] = useState(true);
  const [descriptiveNoDataset, setDescriptiveNoDataset] = useState(false);
  const [descriptiveError, setDescriptiveError] = useState<string | null>(null);
  const [descriptiveRefreshKey, setDescriptiveRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setDescriptiveLoading(true);
    setDescriptiveError(null);
    setDescriptiveNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/stats"), { credentials: "include" });
        if (response.status === 404) {
          if (active) {
            setDescriptiveNoDataset(true);
            setDescriptiveProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: DescriptiveStatsResponse = await response.json();
        if (active) {
          setDescriptiveProfile(data);
        }
      } catch (caught) {
        if (active) {
          setDescriptiveError(
            caught instanceof Error ? caught.message : "Не удалось загрузить описательные статистики",
          );
        }
      } finally {
        if (active) setDescriptiveLoading(false);
      }
    })();
    return () => { active = false; };
  }, [datasetKey, descriptiveRefreshKey]);

  const descriptiveBusy = descriptiveLoading || targetLoading;
  const descriptiveRequestError = descriptiveError ?? targetError;
  const insufficientColumns = descriptiveProfile?.columns.filter((item) => item.stats === null).length ?? 0;
  const descriptiveStatus: CheckStatus = descriptiveBusy
    ? "running"
    : descriptiveRequestError
    ? "error"
    : descriptiveNoDataset || descriptiveProfile?.columns.length === 0
    ? "skipped"
    : insufficientColumns > 0
    ? "warning"
    : descriptiveProfile
    ? "done"
    : "pending";

  // ── Остановка «Корреляция»: ACF/PACF выбранного общего признака ──
  const [correlationProfile, setCorrelationProfile] = useState<EdaCorrelationResponse | null>(null);
  const [correlationLoading, setCorrelationLoading] = useState(false);
  const [correlationNoDataset, setCorrelationNoDataset] = useState(false);
  const [correlationError, setCorrelationError] = useState<string | null>(null);
  const [correlationRefreshKey, setCorrelationRefreshKey] = useState(0);
  const [correlationMaxLags, setCorrelationMaxLags] = useState(40);

  useEffect(() => {
    if (activeCheckId !== "correlation" || targetLoading) return;
    if (!hasDataset) {
      setCorrelationNoDataset(true);
      setCorrelationProfile(null);
      setCorrelationLoading(false);
      return;
    }
    if (!activeFeature) {
      setCorrelationNoDataset(false);
      setCorrelationProfile(null);
      setCorrelationLoading(false);
      return;
    }

    let active = true;
    setCorrelationLoading(true);
    setCorrelationError(null);
    setCorrelationNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(
          sessionApiUrl(
            `/dataset/eda-correlation?column=${encodeURIComponent(activeFeature)}&max_lags=${correlationMaxLags}`,
          ),
          { credentials: "include" },
        );
        if (response.status === 404) {
          if (active) {
            setCorrelationNoDataset(true);
            setCorrelationProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await correlationResponseDetail(response));
        const data: EdaCorrelationResponse = await response.json();
        if (active) setCorrelationProfile(data);
      } catch (caught) {
        if (active) {
          setCorrelationError(
            caught instanceof Error ? caught.message : "Не удалось рассчитать ACF/PACF",
          );
        }
      } finally {
        if (active) setCorrelationLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, correlationMaxLags, correlationRefreshKey, datasetKey, hasDataset, targetLoading]);

  const correlationBusy = correlationLoading || (activeCheckId === "correlation" && targetLoading);
  const correlationRequestError = correlationError ?? (activeCheckId === "correlation" ? targetError : null);
  const correlationStatus: CheckStatus = correlationBusy
    ? "running"
    : correlationRequestError
    ? "error"
    : correlationNoDataset || (hasDataset && !activeFeature)
    ? "skipped"
    : correlationProfile?.applicable === false
    ? "warning"
    : correlationProfile?.applicable
    ? "done"
    : "pending";

  // ── Остановка «IH-анализ»: факторы X относительно общего target Y ──
  const [ihProfile, setIhProfile] = useState<EdaIhResponse | null>(null);
  const [ihLoading, setIhLoading] = useState(false);
  const [ihNoDataset, setIhNoDataset] = useState(false);
  const [ihError, setIhError] = useState<string | null>(null);
  const [ihRefreshKey, setIhRefreshKey] = useState(0);
  const [ihParameters, setIhParameters] = useState<EdaIhParameters>({
    sharpness: 0.25,
    minSamples: 20,
    topK: 10,
    maxLag: 3,
  });

  useEffect(() => {
    if (activeCheckId !== "ih_analysis" || targetLoading) return;
    if (!hasDataset) {
      setIhNoDataset(true);
      setIhProfile(null);
      setIhLoading(false);
      return;
    }
    if (!activeFeature) {
      setIhNoDataset(false);
      setIhProfile(null);
      setIhLoading(false);
      return;
    }

    let active = true;
    setIhLoading(true);
    setIhError(null);
    setIhNoDataset(false);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          sharpness: String(ihParameters.sharpness),
          min_samples: String(ihParameters.minSamples),
          top_k: String(ihParameters.topK),
          max_lag: String(ihParameters.maxLag),
          permutations: "49",
        });
        const response = await fetch(
          sessionApiUrl(`/dataset/eda-ih?${query.toString()}`),
          { credentials: "include" },
        );
        if (response.status === 404) {
          if (active) {
            setIhNoDataset(true);
            setIhProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await ihResponseDetail(response));
        const data: EdaIhResponse = await response.json();
        if (active) setIhProfile(data);
      } catch (caught) {
        if (active) {
          setIhError(caught instanceof Error ? caught.message : "Не удалось выполнить IH-анализ");
        }
      } finally {
        if (active) setIhLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, datasetKey, hasDataset, ihParameters, ihRefreshKey, targetLoading]);

  const ihBusy = ihLoading || (activeCheckId === "ih_analysis" && targetLoading);
  const ihRequestError = ihError ?? (activeCheckId === "ih_analysis" ? targetError : null);
  const ihStatus: CheckStatus = ihBusy
    ? "running"
    : ihRequestError
    ? "error"
    : ihNoDataset || (hasDataset && !activeFeature)
    ? "skipped"
    : ihProfile?.applicable === false
    ? "warning"
    : ihProfile?.applicable
    ? "done"
    : "pending";

  // ── Остановка «Сезонность и периодичность»: спектр общего target ──
  const [seasonalityProfile, setSeasonalityProfile] = useState<EdaSeasonalityResponse | null>(null);
  const [seasonalityLoading, setSeasonalityLoading] = useState(false);
  const [seasonalityNoDataset, setSeasonalityNoDataset] = useState(false);
  const [seasonalityError, setSeasonalityError] = useState<string | null>(null);
  const [seasonalityRefreshKey, setSeasonalityRefreshKey] = useState(0);
  const [seasonalityParameters, setSeasonalityParameters] = useState<EdaSeasonalityParameters>({
    minCycles: 3,
    maxCandidates: 5,
  });

  useEffect(() => {
    if (activeCheckId !== "seasonality" || targetLoading) return;
    if (!hasDataset) {
      setSeasonalityNoDataset(true);
      setSeasonalityProfile(null);
      setSeasonalityLoading(false);
      return;
    }
    if (!activeFeature) {
      setSeasonalityNoDataset(false);
      setSeasonalityProfile(null);
      setSeasonalityLoading(false);
      return;
    }

    let active = true;
    setSeasonalityLoading(true);
    setSeasonalityError(null);
    setSeasonalityNoDataset(false);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          min_cycles: String(seasonalityParameters.minCycles),
          max_candidates: String(seasonalityParameters.maxCandidates),
        });
        const response = await fetch(
          sessionApiUrl(`/dataset/eda-seasonality?${query.toString()}`),
          { credentials: "include" },
        );
        if (response.status === 404) {
          if (active) {
            setSeasonalityNoDataset(true);
            setSeasonalityProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await seasonalityResponseDetail(response));
        const data: EdaSeasonalityResponse = await response.json();
        if (active) setSeasonalityProfile(data);
      } catch (caught) {
        if (active) {
          setSeasonalityError(
            caught instanceof Error ? caught.message : "Не удалось выполнить спектральный анализ",
          );
        }
      } finally {
        if (active) setSeasonalityLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, datasetKey, hasDataset, seasonalityParameters, seasonalityRefreshKey, targetLoading]);

  const seasonalityBusy = seasonalityLoading || (activeCheckId === "seasonality" && targetLoading);
  const seasonalityRequestError = seasonalityError ?? (activeCheckId === "seasonality" ? targetError : null);
  const seasonalityStatus: CheckStatus = seasonalityBusy
    ? "running"
    : seasonalityRequestError
    ? "error"
    : seasonalityNoDataset || (hasDataset && !activeFeature)
    ? "skipped"
    : seasonalityProfile?.applicable === false
    ? "warning"
    : seasonalityProfile?.applicable
    ? "done"
    : "pending";

  // ── Остановка «Верификация стационарности»: общий target без мутации ──
  const [stationarityProfile, setStationarityProfile] = useState<EdaStationarityResponse | null>(null);
  const [stationarityLoading, setStationarityLoading] = useState(false);
  const [stationarityNoDataset, setStationarityNoDataset] = useState(false);
  const [stationarityError, setStationarityError] = useState<string | null>(null);
  const [stationarityRefreshKey, setStationarityRefreshKey] = useState(0);
  const [stationarityParameters, setStationarityParameters] = useState<EdaStationarityParameters>({
    alpha: 0.05,
    rollingWindow: 12,
  });

  useEffect(() => {
    if (activeCheckId !== "stationarity" || targetLoading) return;
    if (!hasDataset) {
      setStationarityNoDataset(true);
      setStationarityProfile(null);
      setStationarityLoading(false);
      return;
    }
    if (!activeFeature) {
      setStationarityNoDataset(false);
      setStationarityProfile(null);
      setStationarityLoading(false);
      return;
    }

    let active = true;
    setStationarityLoading(true);
    setStationarityError(null);
    setStationarityNoDataset(false);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          alpha: String(stationarityParameters.alpha),
          rolling_window: String(stationarityParameters.rollingWindow),
        });
        const response = await fetch(
          sessionApiUrl(`/dataset/eda-stationarity?${query.toString()}`),
          { credentials: "include" },
        );
        if (response.status === 404) {
          if (active) {
            setStationarityNoDataset(true);
            setStationarityProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await stationarityResponseDetail(response));
        const data: EdaStationarityResponse = await response.json();
        if (active) setStationarityProfile(data);
      } catch (caught) {
        if (active) {
          setStationarityError(
            caught instanceof Error ? caught.message : "Не удалось проверить стационарность",
          );
        }
      } finally {
        if (active) setStationarityLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, datasetKey, hasDataset, stationarityParameters, stationarityRefreshKey, targetLoading]);

  const stationarityBusy = stationarityLoading || (activeCheckId === "stationarity" && targetLoading);
  const stationarityRequestError = stationarityError ?? (activeCheckId === "stationarity" ? targetError : null);
  const stationarityStatus: CheckStatus = stationarityBusy
    ? "running"
    : stationarityRequestError
    ? "error"
    : stationarityNoDataset || (hasDataset && !activeFeature)
    ? "skipped"
    : stationarityProfile?.applicable === false
    ? "warning"
    : stationarityProfile?.consensus === "stationary" || stationarityProfile?.consensus === "trend-stationary"
    ? "done"
    : stationarityProfile?.applicable
    ? "warning"
    : "pending";

  // ── Остановка «Распределение»: общий target, пять представлений ──
  const [distributionProfile, setDistributionProfile] = useState<EdaDistributionResponse | null>(null);
  const [distributionLoading, setDistributionLoading] = useState(false);
  const [distributionNoDataset, setDistributionNoDataset] = useState(false);
  const [distributionError, setDistributionError] = useState<string | null>(null);
  const [distributionRefreshKey, setDistributionRefreshKey] = useState(0);
  const [distributionParameters, setDistributionParameters] = useState<EdaDistributionParameters>({
    alpha: 0.05,
    bins: 20,
  });

  useEffect(() => {
    if (activeCheckId !== "distribution" || targetLoading) return;
    if (!hasDataset) {
      setDistributionNoDataset(true);
      setDistributionProfile(null);
      setDistributionLoading(false);
      return;
    }
    if (!activeFeature) {
      setDistributionNoDataset(false);
      setDistributionProfile(null);
      setDistributionLoading(false);
      return;
    }

    let active = true;
    setDistributionLoading(true);
    setDistributionError(null);
    setDistributionNoDataset(false);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          alpha: String(distributionParameters.alpha),
          bins: String(distributionParameters.bins),
        });
        const response = await fetch(
          sessionApiUrl(`/dataset/eda-distribution?${query.toString()}`),
          { credentials: "include" },
        );
        if (response.status === 404) {
          if (active) {
            setDistributionNoDataset(true);
            setDistributionProfile(null);
          }
          return;
        }
        if (!response.ok) throw new Error(await distributionResponseDetail(response));
        const data: EdaDistributionResponse = await response.json();
        if (active) setDistributionProfile(data);
      } catch (caught) {
        if (active) {
          setDistributionError(
            caught instanceof Error ? caught.message : "Не удалось исследовать распределение",
          );
        }
      } finally {
        if (active) setDistributionLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, datasetKey, distributionParameters, distributionRefreshKey, hasDataset, targetLoading]);

  const distributionBusy = distributionLoading || (activeCheckId === "distribution" && targetLoading);
  const distributionRequestError = distributionError ?? (activeCheckId === "distribution" ? targetError : null);
  const distributionStatus: CheckStatus = distributionBusy
    ? "running"
    : distributionRequestError
    ? "error"
    : distributionNoDataset || (hasDataset && !activeFeature)
    ? "skipped"
    : distributionProfile?.applicable === false
    ? "warning"
    : distributionProfile?.normality_status === "compatible"
    ? "done"
    : distributionProfile?.applicable
    ? "warning"
    : "pending";

  // ── Остановка «Структурные сдвиги»: CUSUM + PELT + Chow ──
  const [structuralProfile, setStructuralProfile] = useState<EdaStructuralBreaksResponse | null>(null);
  const [structuralLoading, setStructuralLoading] = useState(false);
  const [structuralNoDataset, setStructuralNoDataset] = useState(false);
  const [structuralError, setStructuralError] = useState<string | null>(null);
  const [structuralRefreshKey, setStructuralRefreshKey] = useState(0);
  const [structuralParameters, setStructuralParameters] = useState<EdaStructuralBreaksParameters>({
    alpha: 0.05, minSegment: 20, penaltyMultiplier: 2,
  });

  useEffect(() => {
    if (activeCheckId !== "structural" || targetLoading) return;
    if (!hasDataset) {
      setStructuralNoDataset(true); setStructuralProfile(null); setStructuralLoading(false); return;
    }
    if (!activeFeature) {
      setStructuralNoDataset(false); setStructuralProfile(null); setStructuralLoading(false); return;
    }
    let active = true;
    setStructuralLoading(true); setStructuralError(null); setStructuralNoDataset(false);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          alpha: String(structuralParameters.alpha),
          min_segment: String(structuralParameters.minSegment),
          penalty_multiplier: String(structuralParameters.penaltyMultiplier),
        });
        const response = await fetch(
          sessionApiUrl(`/dataset/eda-structural-breaks?${query.toString()}`),
          { credentials: "include" },
        );
        if (response.status === 404) {
          const detail = await structuralResponseDetail(response);
          if (detail === "В сессии нет активного датасета") {
            if (active) { setStructuralNoDataset(true); setStructuralProfile(null); }
            return;
          }
          throw new Error(detail);
        }
        if (!response.ok) throw new Error(await structuralResponseDetail(response));
        const data: EdaStructuralBreaksResponse = await response.json();
        if (active) setStructuralProfile(data);
      } catch (caught) {
        if (active) setStructuralError(caught instanceof Error ? caught.message : "Не удалось исследовать структурные сдвиги");
      } finally {
        if (active) setStructuralLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, datasetKey, hasDataset, structuralParameters, structuralRefreshKey, targetLoading]);

  const structuralBusy = structuralLoading || (activeCheckId === "structural" && targetLoading);
  const structuralRequestError = structuralError ?? (activeCheckId === "structural" ? targetError : null);
  const structuralStatus: CheckStatus = structuralBusy
    ? "running" : structuralRequestError ? "error"
    : structuralNoDataset || (hasDataset && !activeFeature) ? "skipped"
    : structuralProfile?.applicable === false ? "warning"
    : structuralProfile?.status === "stable" ? "done"
    : structuralProfile?.applicable ? "warning" : "pending";

  const [featureSelectionProfile, setFeatureSelectionProfile] = useState<EdaFeatureSelectionResponse | null>(null);
  const [featureSelectionLoading, setFeatureSelectionLoading] = useState(false);
  const [featureSelectionNoDataset, setFeatureSelectionNoDataset] = useState(false);
  const [featureSelectionError, setFeatureSelectionError] = useState<string | null>(null);
  const [featureSelectionRefreshKey, setFeatureSelectionRefreshKey] = useState(0);
  const [featureSelectionParameters, setFeatureSelectionParameters] = useState<EdaFeatureSelectionParameters>({alpha:.05,maxLag:3,correlationThreshold:.3,vifThreshold:5,differenceOrder:0});
  useEffect(()=>{
    if(activeCheckId!=="feature_select"||targetLoading)return;
    if(!hasDataset){setFeatureSelectionNoDataset(true);setFeatureSelectionProfile(null);return;}
    if(!activeFeature){setFeatureSelectionProfile(null);return;}
    let active=true; setFeatureSelectionLoading(true); setFeatureSelectionError(null); setFeatureSelectionNoDataset(false);
    void(async()=>{try{const p=featureSelectionParameters;const query=new URLSearchParams({column:activeFeature,alpha:String(p.alpha),max_lag:String(p.maxLag),correlation_threshold:String(p.correlationThreshold),vif_threshold:String(p.vifThreshold),difference_order:String(p.differenceOrder)});const response=await fetch(sessionApiUrl(`/dataset/eda-feature-selection?${query}`),{credentials:"include"});if(response.status===404){const detail=await featureSelectionResponseDetail(response);if(detail==="В сессии нет активного датасета"){if(active)setFeatureSelectionNoDataset(true);return;}throw new Error(detail);}if(!response.ok)throw new Error(await featureSelectionResponseDetail(response));const data:EdaFeatureSelectionResponse=await response.json();if(active)setFeatureSelectionProfile(data);}catch(e){if(active)setFeatureSelectionError(e instanceof Error?e.message:"Не удалось выполнить отбор признаков");}finally{if(active)setFeatureSelectionLoading(false);}})();
    return()=>{active=false};
  },[activeCheckId,activeFeature,datasetKey,featureSelectionParameters,featureSelectionRefreshKey,hasDataset,targetLoading]);
  const featureSelectionBusy=featureSelectionLoading||(activeCheckId==="feature_select"&&targetLoading);
  const featureSelectionRequestError=featureSelectionError??(activeCheckId==="feature_select"?targetError:null);
  const featureSelectionStatus:CheckStatus=featureSelectionBusy?"running":featureSelectionRequestError?"error":featureSelectionNoDataset||(hasDataset&&!activeFeature)||featureSelectionProfile?.applicability_status==="not_required"?"skipped":featureSelectionProfile?.applicable===false?"warning":featureSelectionProfile?.review_features.length||featureSelectionProfile?.low_signal_features.length?"warning":featureSelectionProfile?.applicable?"done":"pending";

  const [validationStrategyProfile, setValidationStrategyProfile] = useState<EdaValidationStrategyResponse | null>(null);
  const [validationStrategyLoading, setValidationStrategyLoading] = useState(false);
  const [validationStrategyNoDataset, setValidationStrategyNoDataset] = useState(false);
  const [validationStrategyError, setValidationStrategyError] = useState<string | null>(null);
  const [validationStrategyRefreshKey, setValidationStrategyRefreshKey] = useState(0);
  const [validationStrategyParameters, setValidationStrategyParameters] = useState<EdaValidationStrategyParameters>({
    strategy: "expanding", horizon: 12, nSplits: 5, gap: 0, trainWindow: 60,
  });

  useEffect(() => {
    if (activeCheckId !== "validation_strategy" || targetLoading) return;
    if (!hasDataset) { setValidationStrategyNoDataset(true); setValidationStrategyProfile(null); return; }
    if (!activeFeature) { setValidationStrategyProfile(null); return; }
    let active = true;
    setValidationStrategyLoading(true); setValidationStrategyError(null); setValidationStrategyNoDataset(false);
    void (async () => {
      try {
        const parameters = validationStrategyParameters;
        const query = new URLSearchParams({
          column: activeFeature,
          strategy: parameters.strategy,
          horizon: String(parameters.horizon),
          n_splits: String(parameters.nSplits),
          gap: String(parameters.gap),
          train_window: String(parameters.trainWindow),
        });
        const response = await fetch(sessionApiUrl(`/dataset/eda-validation-strategy?${query}`), { credentials: "include" });
        if (response.status === 404) {
          const detail = await validationStrategyResponseDetail(response);
          if (detail === "В сессии нет активного датасета") { if (active) setValidationStrategyNoDataset(true); return; }
          throw new Error(detail);
        }
        if (!response.ok) throw new Error(await validationStrategyResponseDetail(response));
        const data: EdaValidationStrategyResponse = await response.json();
        if (active) setValidationStrategyProfile(data);
      } catch (error) {
        if (active) setValidationStrategyError(error instanceof Error ? error.message : "Не удалось построить стратегию валидации");
      } finally {
        if (active) setValidationStrategyLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, datasetKey, hasDataset, targetLoading, validationStrategyParameters, validationStrategyRefreshKey]);

  const validationStrategyBusy = validationStrategyLoading || (activeCheckId === "validation_strategy" && targetLoading);
  const validationStrategyRequestError = validationStrategyError ?? (activeCheckId === "validation_strategy" ? targetError : null);
  const validationStrategyStatus: CheckStatus = validationStrategyBusy ? "running"
    : validationStrategyRequestError ? "error"
    : validationStrategyNoDataset || (hasDataset && !activeFeature) ? "skipped"
    : validationStrategyProfile?.applicable === false ? "warning"
    : validationStrategyProfile?.strategy === "single" || (validationStrategyProfile?.warnings.length ?? 0) > 0 ? "warning"
    : validationStrategyProfile?.applicable ? "done" : "pending";

  const [modelMatrixProfile, setModelMatrixProfile] = useState<EdaModelMatrixResponse | null>(null);
  const [modelMatrixLoading, setModelMatrixLoading] = useState(false);
  const [modelMatrixNoDataset, setModelMatrixNoDataset] = useState(false);
  const [modelMatrixError, setModelMatrixError] = useState<string | null>(null);
  const [modelMatrixRefreshKey, setModelMatrixRefreshKey] = useState(0);
  const [modelMatrixParameters, setModelMatrixParameters] = useState<EdaModelMatrixParameters>({
    task: "forecast", horizon: 12,
  });

  useEffect(() => {
    if (activeCheckId !== "model_matrix" || targetLoading) return;
    if (!hasDataset) { setModelMatrixNoDataset(true); setModelMatrixProfile(null); return; }
    if (!activeFeature) { setModelMatrixProfile(null); return; }
    let active = true;
    setModelMatrixLoading(true); setModelMatrixError(null); setModelMatrixNoDataset(false);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          task: modelMatrixParameters.task,
          horizon: String(modelMatrixParameters.horizon),
          validation_strategy: validationStrategyParameters.strategy,
          n_splits: String(validationStrategyParameters.nSplits),
          gap: String(validationStrategyParameters.gap),
          train_window: String(validationStrategyParameters.trainWindow),
        });
        const response = await fetch(sessionApiUrl(`/dataset/eda-model-matrix?${query}`), { credentials: "include" });
        if (response.status === 404) {
          const detail = await modelMatrixResponseDetail(response);
          if (detail === "В сессии нет активного датасета") { if (active) setModelMatrixNoDataset(true); return; }
          throw new Error(detail);
        }
        if (!response.ok) throw new Error(await modelMatrixResponseDetail(response));
        const data: EdaModelMatrixResponse = await response.json();
        if (active) setModelMatrixProfile(data);
      } catch (error) {
        if (active) setModelMatrixError(error instanceof Error ? error.message : "Не удалось построить матрицу моделей");
      } finally {
        if (active) setModelMatrixLoading(false);
      }
    })();
    return () => { active = false; };
  }, [activeCheckId, activeFeature, datasetKey, hasDataset, modelMatrixParameters, modelMatrixRefreshKey, targetLoading, validationStrategyParameters]);

  const modelMatrixBusy = modelMatrixLoading || (activeCheckId === "model_matrix" && targetLoading);
  const modelMatrixRequestError = modelMatrixError ?? (activeCheckId === "model_matrix" ? targetError : null);
  const modelMatrixStatus: CheckStatus = modelMatrixBusy ? "running"
    : modelMatrixRequestError ? "error"
    : modelMatrixNoDataset || (hasDataset && !activeFeature) ? "skipped"
    : modelMatrixProfile?.applicable === false ? "warning"
    : (modelMatrixProfile?.summary.blocked ?? 0) > 0 || (modelMatrixProfile?.warnings.length ?? 0) > 0 ? "warning"
    : modelMatrixProfile?.applicable ? "done" : "pending";

  // Результаты принадлежат конкретному датасету. При его смене убираем
  // старые красные/жёлтые статусы; активная остановка ниже пересчитается
  // благодаря datasetKey в зависимостях запроса.
  useEffect(() => {
    setCorrelationProfile(null); setCorrelationError(null); setCorrelationNoDataset(false);
    setIhProfile(null); setIhError(null); setIhNoDataset(false);
    setSeasonalityProfile(null); setSeasonalityError(null); setSeasonalityNoDataset(false);
    setStationarityProfile(null); setStationarityError(null); setStationarityNoDataset(false);
    setDistributionProfile(null); setDistributionError(null); setDistributionNoDataset(false);
    setStructuralProfile(null); setStructuralError(null); setStructuralNoDataset(false);
    setFeatureSelectionProfile(null); setFeatureSelectionError(null); setFeatureSelectionNoDataset(false);
    setValidationStrategyProfile(null); setValidationStrategyError(null); setValidationStrategyNoDataset(false);
    setModelMatrixProfile(null); setModelMatrixError(null); setModelMatrixNoDataset(false);
  }, [datasetKey]);

  const checks = useMemo<Check[]>(() => CHECKS.map((check) =>
    check.id === "descriptive"
      ? { ...check, status: descriptiveStatus, count: insufficientColumns }
      : check.id === "correlation"
      ? { ...check, status: correlationStatus, count: null }
      : check.id === "ih_analysis"
      ? { ...check, status: ihStatus, count: null }
      : check.id === "seasonality"
      ? { ...check, status: seasonalityStatus, count: seasonalityProfile?.confirmed_periods ?? null }
      : check.id === "stationarity"
      ? { ...check, status: stationarityStatus, count: null }
      : check.id === "distribution"
      ? { ...check, status: distributionStatus, count: null }
      : check.id === "structural"
      ? { ...check, status: structuralStatus, count: structuralProfile?.supported_count ?? null }
      : check.id === "feature_select"
      ? { ...check, status: featureSelectionStatus, count: (featureSelectionProfile?.review_features.length ?? 0) + (featureSelectionProfile?.low_signal_features.length ?? 0) }
      : check.id === "validation_strategy"
      ? { ...check, status: validationStrategyStatus, count: null }
      : check.id === "model_matrix"
      ? { ...check, status: modelMatrixStatus, count: modelMatrixProfile?.summary.blocked ?? null }
      : check,
  ), [correlationStatus, descriptiveStatus, distributionStatus, featureSelectionProfile, featureSelectionStatus, ihStatus, insufficientColumns, modelMatrixProfile?.summary.blocked, modelMatrixStatus, seasonalityProfile?.confirmed_periods, seasonalityStatus, stationarityStatus, structuralProfile?.supported_count, structuralStatus, validationStrategyStatus]);

  // ── PROGR-18: отчёт фактов просмотров исследований в панель
  // «Прогресс» (зеркало PROGR-16-A/17, spec_progress_v1.1.md §2,
  // категория B) ──
  // Узлы EDA не достигали done от самого модуля (profile_viewed --
  // running): факт-контур стадии не имел носителя прохождения. Решение
  // тимлида по семантике (v1.1 §2): статус done/pending по факту
  // «аналитик открыл и просмотрел результат», warning НЕ вводить (EDA
  // -- анализ, а не проверка качества: ложная тревога там, где нет
  // критерия ошибки). Исследование считается просмотренным, когда оно
  // активно И его результат показан модулем (статус исследования
  // done/warning -- найденные особенности результата НЕ мешают факту
  // просмотра; running/error/skipped результата не показывают). Множество
  // просмотренных монотонно в пределах датасета (увиденный результат
  // не «развидеть»); смена датасета -- новая вселенная фактов.
  //
  // Отчёт -- снапшот ВСЕХ 10 исследований общего реестра
  // (eda_checks.json §12 п.2): viewed -> done, остальные -- pending
  // (all-or-nothing контракт бэкенда), POST /v1/progress/eda-checks.
  // URL-контракт (урок PROGR-15-A): progressApiUrl, НЕ sessionApiUrl.
  // HTTP-неудача -- тем же контуром повтора, что в PROGR-16-A/17:
  // res.ok проверяется, при !ok маркер сбрасывается -- следующий
  // снапшот повторит отправление (вспомогательный контур §12 п.8,
  // без алертов и таймеров).
  //
  // ЯКОРЬ В ЖУРНАЛЕ (отличие от зеркала, осознанное): вкладки платформы
  // -- роуты Next.js, модуль размонтируется при каждом переключении;
  // кумулятивное множество просмотренных НЕ выводится заново из ответов
  // (в отличие от детерминированных статусов Валидации/Предобработки).
  // Без якоря первый же снапшот после перемонтирования/перезагрузки
  // (descriptive-only) ПЕРЕЗАПИСАЛ бы факты назад (last-wins): панель
  // и Наставник занижали бы прогресс, журнал -- регрессировал. Поэтому
  // при монтировании одноразовый GET /v1/progress/trace (§7.2-прецедент:
  // клиент строит сводку из уже полученных данных -- тут уже
  // ПОСЧИТАННЫЕ состояния узлов, не опрос profile-эндпоинтов, решение
  // Расхождения №1 не трогается) даёт seed done-узлов eda/*, маркер
  // отчёта инициализируется seed-снапшотом -- отчёт происходит только
  // по НОВОМУ просмотру; дедупликация переживает перемонтирование.
  // Seed best-effort (§12 п.8): сбой /trace -- пустой якорь, отчёт
  // идёт с чистого множества (тот же backend, что принимает отчёт).
  const buildEdaChecksSnapshot = (viewed: Set<string>): string =>
    JSON.stringify(
      Object.fromEntries(
        CHECKS.map((check) => [check.id, viewed.has(check.id) ? "done" : "pending"]),
      ),
    );
  const [edaViewedIds, setEdaViewedIds] = useState<Set<string>>(new Set());
  const [edaSeedReady, setEdaSeedReady] = useState(false);
  const edaSeedReadyRef = useRef(false);
  const lastReportedEdaChecksRef = useRef<string>("");
  // Порядок эффектов ВАЖЕН (урок PROGR-17): сброс -- ДО seed-эффекта и
  // эффекта отчёта; в коммите смены датасета сброс выполняется первым.
  // Ключ вселенной фактов -- datasetKey (datasetId ?? name):
  // datasetId меняется даже при повторной загрузке файла с тем же именем.
  useEffect(() => {
    edaSeedReadyRef.current = false;
    setEdaViewedIds(new Set());
    setEdaSeedReady(false);
    lastReportedEdaChecksRef.current = "";
  }, [datasetKey]);
  useEffect(() => {
    if (!datasetKey) {
      edaSeedReadyRef.current = true;
      setEdaSeedReady(true);
      return;
    }
    let cancelled = false;
    void (async () => {
      const knownIds = new Set(CHECKS.map((check) => check.id));
      const seedViewed = new Set<string>();
      try {
        const response = await fetch(progressApiUrl("/trace"), { credentials: "include" });
        if (response.ok) {
          const data = await response.json();
          const statuses = data?.node_statuses;
          if (statuses && typeof statuses === "object") {
            for (const [key, status] of Object.entries(statuses as Record<string, unknown>)) {
              if (!key.startsWith("eda/")) continue;
              const nodeId = key.slice("eda/".length);
              if (status === "done" && knownIds.has(nodeId)) seedViewed.add(nodeId);
            }
          }
        }
      } catch {
        // Seed best-effort (§12 п.8): сбой якоря -- пустое множество,
        // отчёт пойдёт с чистого листа; контур фактов не ломается.
      }
      if (cancelled) return;
      edaSeedReadyRef.current = true;
      setEdaViewedIds((prev) => {
        const merged = new Set(prev);
        seedViewed.forEach((id) => merged.add(id));
        return merged;
      });
      lastReportedEdaChecksRef.current = buildEdaChecksSnapshot(seedViewed);
      setEdaSeedReady(true);
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetKey]);
  const postEdaChecks = useCallback((reported: Record<string, string>) => {
    fetch(progressApiUrl("/eda-checks"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ checks: reported }),
    })
      .then((res) => {
        if (!res.ok) lastReportedEdaChecksRef.current = "";
      })
      .catch(() => {
        // Отчёт фактов -- вспомогательный контур (§12 п.8): сбой не ломает
        // модуль; следующее изменение снапшота повторит отчёт.
        lastReportedEdaChecksRef.current = "";
      });
  }, []);
  // Факт просмотра: активное исследование с ПОКАЗАННЫМ результатом
  // (done/warning). edaSeedReadyRef-гейт отсекает устаревшие статусы
  // предыдущей вселенной в коммите смены датасета (сброс объявлен
  // раньше и синхронно опускает ref -- факта просмотра в мёртвой
  // вселенной не возникает). Запись идемпотентна (множество).
  useEffect(() => {
    if (!edaSeedReadyRef.current) return;
    const activeStatus = checks.find((check) => check.id === activeCheckId)?.status;
    if (activeStatus !== "done" && activeStatus !== "warning") return;
    setEdaViewedIds((prev) => {
      if (prev.has(activeCheckId)) return prev;
      const next = new Set(prev);
      next.add(activeCheckId);
      return next;
    });
  }, [checks, activeCheckId, edaSeedReady]);
  // Снапшот -- до первого показанного результата отчёта НЕТ (модуль
  // без просмотренных результатов -- не источник фактов; зеркало
  // семантики Валидации «до первого запуска отчёта нет»), после seed --
  // только расхождение с якорем (новый просмотр).
  const edaChecksReportSnapshot: string | null =
    activeDataset && edaSeedReady && edaViewedIds.size > 0
      ? buildEdaChecksSnapshot(edaViewedIds)
      : null;
  useEffect(() => {
    if (!edaChecksReportSnapshot) return;
    if (edaChecksReportSnapshot === lastReportedEdaChecksRef.current) return;
    lastReportedEdaChecksRef.current = edaChecksReportSnapshot;
    postEdaChecks(JSON.parse(edaChecksReportSnapshot) as Record<string, string>);
  }, [edaChecksReportSnapshot, postEdaChecks]);

  // Сворачиваем при смене секции
  useEffect(() => {
    setDescriptionExpanded(false);
  }, [descriptionSection]);

  // Click-outside: сворачиваем при клике вне description box
  const handleOutsideClick = useCallback((e: MouseEvent) => {
    if (descRef.current && !descRef.current.contains(e.target as Node)) {
      setDescriptionExpanded(false);
    }
  }, []);
  useEffect(() => {
    if (descriptionExpanded) {
      document.addEventListener("mousedown", handleOutsideClick);
      return () => document.removeEventListener("mousedown", handleOutsideClick);
    }
  }, [descriptionExpanded, handleOutsideClick]);

  const applicableChecks = checks.filter((check) => check.status !== "skipped");
  const evaluatedCount = applicableChecks.filter(
    (check) => check.status === "done" || check.status === "warning",
  ).length;
  const progressPct = applicableChecks.length > 0
    ? Math.round((evaluatedCount / applicableChecks.length) * 100)
    : 100;
  const activeCheck = checks.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...checks].sort((a, b) =>
    a.id === activeCheckId ? -1 : b.id === activeCheckId ? 1 : 0
  );

  // Переключение секции описания в центральном текстовом поле
  const handleDescriptionClick = (check: Check, section: "metrics" | "pipeline") => {
    setActiveCheckId(check.id);
    setDescriptionSection(section);
  };

  // Показать/скрыть справку (toggle: закрытие возвращает к метрикам
  // активной остановки — инвариант информативности)
  const handleHelpClick = () => {
    setDescriptionSection((prev) => prev === "help" ? "metrics" : "help");
  };

  // ── Overflow detection для expandable description ──
  useEffect(() => {
    const el = descRef.current;
    if (!el) return;
    const checkOverflow = () => {
      setHasOverflow(el.scrollHeight > el.clientHeight + 2);
    };
    checkOverflow();
    const observer = new ResizeObserver(checkOverflow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [descriptionSection]); // ResizeObserver отслеживает контент

  // Текст описания для центрального поля — из единого реестра справки
  // (Шаг 3, ревизия 2026-09-22: describeNode по (stage_id, node_id, facet);
  // паритет миграции застрахован фиксстурой help-parity.fixture.json, §13)
  const descriptionContent = (() => {
    if (descriptionSection === "help") {
      return describeNode("eda", null, "module_help")?.text ?? null;
    }
    if (!descriptionSection) return null;
    return (
      describeNode("eda", activeCheckId, descriptionSection)?.text ??
      // defense-in-depth: остановка без записи в реестре (инвариант покрытия
      // гарантирует отсутствие этого пути для 10 реализованных остановок)
      (descriptionSection === "metrics"
        ? `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`
        : `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`)
    );
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка — Цели модуля и результаты EDA";
    if (!descriptionSection) return "Выберите раздел в боковой панели";
    if (activeCheckId === "descriptive") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Описательные статистики"
        : "Полный пайплайн — Описательные статистики";
    }
    if (activeCheckId === "correlation") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Корреляция (ACF/PACF)"
        : "Полный пайплайн — Корреляция (ACF/PACF)";
    }
    if (activeCheckId === "ih_analysis") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — IH-анализ"
        : "Полный пайплайн — IH-анализ";
    }
    if (activeCheckId === "seasonality") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Сезонность и периодичность"
        : "Полный пайплайн — Сезонность и периодичность";
    }
    if (activeCheckId === "stationarity") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Верификация стационарности"
        : "Полный пайплайн — Верификация стационарности";
    }
    if (activeCheckId === "distribution") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Распределение"
        : "Полный пайплайн — Распределение";
    }
    if (activeCheckId === "structural") {
      return descriptionSection === "metrics"
        ? "Метрики и алгоритм — Структурные сдвиги"
        : "Полный пайплайн — Структурные сдвиги";
    }
    if (activeCheckId === "feature_select") return descriptionSection === "metrics" ? "Метрики и алгоритм — Отбор признаков" : "Полный пайплайн — Отбор признаков";
    if (activeCheckId === "validation_strategy") return descriptionSection === "metrics" ? "Метрики и алгоритм — Стратегия валидации" : "Полный пайплайн — Стратегия валидации";
    if (activeCheckId === "model_matrix") return descriptionSection === "metrics" ? "Метрики и алгоритм — Матрица моделей" : "Полный пайплайн — Матрица моделей";
    if (descriptionSection === "metrics") return `Метрики и алгоритм — ${activeCheck.label}`;
    return `Полный пайплайн — ${activeCheck.label}`;
  })();

  return (
    <div className="space-y-5">
      <div className="flex gap-6">
      {/* ── ЛЕВАЯ КОЛОНКА: селектор признака + прогресс + степпер ── */}
      <aside className="w-60 shrink-0 flex flex-col gap-3 pt-1">
        {/* Заголовок модуля + справка */}
        <div className="mb-1">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-neutral-800 truncate min-w-0">
              Разведочный EDA
            </h2>
            <button
              onClick={handleHelpClick}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                descriptionSection === "help"
                  ? "bg-brand text-white"
                  : "bg-brand-light text-neutral-700 hover:bg-brand-light/80"
              }`}
            >
              Справка
            </button>
          </div>
          <p className="text-[11px] text-neutral-500 mt-0.5">
            Финал перед моделированием
          </p>
        </div>

        {/* Селектор числового признака */}
        <div>
          <label htmlFor="eda-active-feature" className="text-[11px] text-neutral-500 block mb-1">
            Исследуемый признак:
          </label>
          <select
            id="eda-active-feature"
            value={activeFeature ?? ""}
            onChange={(e) => void setActiveFeature(e.target.value)}
            disabled={descriptiveBusy || numericFeatures.length === 0}
            className="w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
          >
            {numericFeatures.length ? (
              numericFeatures.map((feature) => (
                <option key={feature} value={feature}>{feature}</option>
              ))
            ) : (
              <option value="">Нет числовых признаков</option>
            )}
          </select>
          {targetError && (
            <p role="alert" className="mt-1 text-[10px] text-red-600">
              Не удалось синхронизировать признак: {targetError}
            </p>
          )}
        </div>

        {/* Прогресс */}
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-neutral-500 tabular-nums">
            {evaluatedCount}/{applicableChecks.length}
          </p>
          <div className="flex-1 bg-neutral-200 rounded-full h-1.5">
            <div
              className="bg-brand h-1.5 rounded-full transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Степпер: прямоугольные карточки с текстом + иконка.
            Паттерн «Моделирования»: пройденная остановка (зелёная галочка,
            status done) подсвечивается светло-зелёным с зелёным текстом;
            при других статусах кнопка не окрашивается. Активная остановка
            сохраняет приоритет индиго, как в эталоне. */}
        <div className="flex flex-col gap-1.5">
          {checks.map((check) => (
            <button
              key={check.id}
              onClick={() => {
                setActiveCheckId(check.id);
                // Инвариант информативности (2026-09-15, зеркально
                // VALID-2/PREPR-2): переключение остановки автозагружает
                // её «Метрики и алгоритм» (вместо прежнего сброса Справки
                // в placeholder). Клик по УЖЕ активной остановке секцию
                // не меняет (открытая Справка остаётся) — прежняя
                // семантика сохранена.
                if (check.id !== activeCheckId) setDescriptionSection("metrics");
              }}
              className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition-colors ${
                check.id === activeCheckId
                  ? "bg-brand text-white border-brand"
                  : check.status === "done"
                  ? "bg-green-50 border-green-200 text-green-800"
                  : "bg-white border-neutral-200 hover:bg-neutral-50 text-neutral-800"
              }`}
            >
              <span className="truncate">{check.label}</span>
              <span className="ml-2 shrink-0">
                <StatusIcon status={check.status} />
              </span>
            </button>
          ))}
          {/* ── Приглашение «Перейти к моделированию» — паттерн цепочки ──
              Общий StepperNextModuleButton ("Ведём исследователя за руку"):
              тот же дизайн, что на «Загрузке» (геометрия степпер-кнопок,
              пастельная заливка, индиго при наведении); светло-серая полоса
              border-t встроена в обёртку компонента. Ставится последним
              элементом списка степпера: это переход к ДРУГОМУ модулю
              пайплайна, а не ещё одно исследование EDA. */}
          <StepperNextModuleButton label="Перейти к моделированию" href="/modeling" />
        </div>
      </aside>

      {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: описание + график + метрики ── */}
      <section className="flex-1 min-w-0">
        {/* Блок «Описание» — текстовое поле над графиком */}
        <div className="mb-5">
          <h3 className="font-semibold mb-1">
            Описание
          </h3>
          <p className="text-xs text-neutral-500 mb-2">
            {descriptionSubtitle}
          </p>
          {/* ── Expandable Description Box ──
              collapsed: min-h=220px, max-h=220px, scroll (in-flow)
              expanded: position:absolute overlay over graph, max-h=calc(100vh-180px)
              chevron: shown only when hasOverflow
          */}
          <div className="relative min-h-[220px]">
            <div
              ref={descRef}
              className={`rounded-lg border border-neutral-200 px-4 py-3 overflow-y-auto text-sm text-neutral-600 whitespace-pre-wrap ${
                descriptionExpanded
                  ? "absolute top-0 left-0 right-0 z-20 max-h-[calc(100vh-180px)] shadow-lg border-brand/30 min-h-[220px] bg-brand-light"
                  : "max-h-[220px] min-h-[220px] bg-brand-light/50"
              }`}
            >
              {descriptionContent || (
                <span className="text-neutral-400 italic">
                  Нажмите «Метрики и алгоритм», «Полный пайплайн» или «Справка»
                </span>
              )}
              {/* Collapse chevron — sticky прилипает к низу scroll-области */}
              {descriptionExpanded && (
                <div className="sticky bottom-0 flex justify-center py-1 bg-brand-light rounded-b-lg">
                  <button
                    onClick={() => setDescriptionExpanded(false)}
                    className="flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                    aria-label="Свернуть описание"
                    data-testid="desc-collapse-btn"
                  >
                    <ChevronUp size={14} />
                  </button>
                </div>
              )}
            </div>
            {/* Expand chevron — только при overflow, collapsed */}
            {hasOverflow && !descriptionExpanded && (
              <button
                onClick={() => setDescriptionExpanded(true)}
                className="absolute bottom-1 left-1/2 -translate-x-1/2 flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                aria-label="Развернуть описание"
                data-testid="desc-expand-btn"
              >
                <ChevronDown size={14} />
              </button>
            )}
          </div>
        </div>

        {/* График */}
        <div>
          <h3 className="font-semibold mb-1">Обзор: {activeCheck.label}</h3>
          <p className="text-xs text-neutral-500 mb-3">
            Визуализация результатов исследования.
          </p>

          {activeCheckId === "descriptive" ? (
            <EdaDescriptiveOverview
              profile={descriptiveProfile}
              activeFeature={activeFeature ?? ""}
              loading={descriptiveBusy}
              error={descriptiveRequestError}
              noDataset={descriptiveNoDataset}
              refreshKey={descriptiveRefreshKey}
            />
          ) : activeCheckId === "correlation" ? (
            <EdaCorrelationOverview
              profile={correlationProfile}
              loading={correlationBusy}
              error={correlationRequestError}
              noDataset={correlationNoDataset}
              maxLags={correlationMaxLags}
              onMaxLagsChange={setCorrelationMaxLags}
            />
          ) : activeCheckId === "ih_analysis" ? (
            <EdaIhOverview
              profile={ihProfile}
              loading={ihBusy}
              error={ihRequestError}
              noDataset={ihNoDataset}
              parameters={ihParameters}
              onParametersChange={(changes) => setIhParameters((current) => ({ ...current, ...changes }))}
            />
          ) : activeCheckId === "seasonality" ? (
            <EdaSeasonalityOverview
              profile={seasonalityProfile}
              loading={seasonalityBusy}
              error={seasonalityRequestError}
              noDataset={seasonalityNoDataset}
              parameters={seasonalityParameters}
              onParametersChange={(changes) => setSeasonalityParameters((current) => ({ ...current, ...changes }))}
            />
          ) : activeCheckId === "stationarity" ? (
            <EdaStationarityOverview
              profile={stationarityProfile}
              loading={stationarityBusy}
              error={stationarityRequestError}
              noDataset={stationarityNoDataset}
              parameters={stationarityParameters}
              onParametersChange={(changes) => setStationarityParameters((current) => ({ ...current, ...changes }))}
            />
          ) : activeCheckId === "distribution" ? (
            <EdaDistributionOverview
              profile={distributionProfile}
              loading={distributionBusy}
              error={distributionRequestError}
              noDataset={distributionNoDataset}
              parameters={distributionParameters}
              onParametersChange={(changes) => setDistributionParameters((current) => ({ ...current, ...changes }))}
            />
          ) : activeCheckId === "structural" ? (
            <EdaStructuralBreaksOverview
              profile={structuralProfile}
              loading={structuralBusy}
              error={structuralRequestError}
              noDataset={structuralNoDataset}
              parameters={structuralParameters}
              onParametersChange={(changes) => setStructuralParameters((current) => ({ ...current, ...changes }))}
              datasetKey={datasetKey}
            />
          ) : activeCheckId === "feature_select" ? (
            <EdaFeatureSelectionOverview profile={featureSelectionProfile} loading={featureSelectionBusy} error={featureSelectionRequestError} noDataset={featureSelectionNoDataset} parameters={featureSelectionParameters} onParametersChange={(changes)=>setFeatureSelectionParameters(current=>({...current,...changes}))}/>
          ) : activeCheckId === "validation_strategy" ? (
            <EdaValidationStrategyOverview
              profile={validationStrategyProfile}
              loading={validationStrategyBusy}
              error={validationStrategyRequestError}
              noDataset={validationStrategyNoDataset}
              parameters={validationStrategyParameters}
              onParametersChange={(changes) => setValidationStrategyParameters((current) => ({ ...current, ...changes }))}
            />
          ) : activeCheckId === "model_matrix" ? (
            <EdaModelMatrixOverview
              profile={modelMatrixProfile}
              loading={modelMatrixBusy}
              error={modelMatrixRequestError}
              noDataset={modelMatrixNoDataset}
              parameters={modelMatrixParameters}
              onParametersChange={(changes) => setModelMatrixParameters((current) => ({ ...current, ...changes }))}
            />
          ) : (
            <div className="bg-brand-light rounded-lg h-[468px] flex items-center justify-center text-sm text-neutral-500">
              [ график для «{activeCheck.label}» ]
            </div>
          )}

          {activeCheckId === "descriptive" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              {(() => {
                const selected = descriptiveProfile?.columns.find((item) => item.name === activeFeature) ?? null;
                return (
                  <>
                    <Metric label="N" value={selected ? String(selected.non_null_count) : "—"} />
                    <Metric label="Mean" value={formatMetric(selected?.stats?.mean)} />
                    <Metric label="Median" value={formatMetric(selected?.stats?.median)} />
                    <Metric label="Std" value={formatMetric(selected?.stats?.std)} />
                    <Metric label="Skewness" value={formatMetric(selected?.stats?.skewness)} />
                    <Metric label="Kurtosis" value={formatMetric(selected?.stats?.kurtosis)} />
                  </>
                );
              })()}
            </div>
          ) : activeCheckId === "correlation" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              <Metric label="N" value={correlationProfile ? String(correlationProfile.n_observations) : "—"} />
              <Metric label="Макс. лаг" value={correlationProfile?.applicable ? String(correlationProfile.max_lag) : "—"} />
              <Metric label="Значимых ACF" value={correlationProfile?.applicable ? String(correlationProfile.significant_acf_lags.length) : "—"} />
              <Metric label="Значимых PACF" value={correlationProfile?.applicable ? String(correlationProfile.significant_pacf_lags.length) : "—"} />
              <Metric label="Ljung–Box p" value={formatMetric(correlationProfile?.ljung_box_pvalue)} />
              <Metric
                label="Кандидаты p / q"
                value={correlationProfile?.applicable
                  ? `${correlationProfile.suggested_p ?? "—"} / ${correlationProfile.suggested_q ?? "—"}`
                  : "—"}
              />
            </div>
          ) : activeCheckId === "ih_analysis" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              {(() => {
                const top = ihProfile?.results[0] ?? null;
                const bestGain = ihProfile?.synergies.length
                  ? Math.max(...ihProfile.synergies.map((item) => item.incremental_gain))
                  : null;
                return (
                  <>
                    <Metric label="N" value={ihProfile ? String(ihProfile.n_observations) : "—"} />
                    <Metric label="H(Y), бит" value={formatMetric(ihProfile?.target_entropy)} />
                    <Metric label="Топ R" value={formatMetric(top?.r)} />
                    <Metric label="Топ R adj." value={formatMetric(top?.r_adjusted)} />
                    <Metric label="Значимых q≤0,05" value={ihProfile?.applicable ? String(ihProfile.results.filter((item) => item.significant).length) : "—"} />
                    <Metric label="Лучший прирост ΔR" value={formatMetric(bestGain)} />
                  </>
                );
              })()}
            </div>
          ) : activeCheckId === "seasonality" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              <Metric label="N" value={seasonalityProfile ? String(seasonalityProfile.n_observations) : "—"} />
              <Metric label="Частота" value={seasonalityProfile?.frequency ?? (seasonalityProfile?.order_source === "row_order" ? "индекс" : "—")} />
              <Metric label="Топ-период" value={formatMetric(seasonalityProfile?.dominant_period)} />
              <Metric label="Сила профиля" value={formatMetric(seasonalityProfile?.dominant_strength)} />
              <Metric label="Спектр. энтропия" value={formatMetric(seasonalityProfile?.spectral_entropy)} />
              <Metric label="Подтверждено" value={seasonalityProfile?.applicable ? String(seasonalityProfile.confirmed_periods) : "—"} />
            </div>
          ) : activeCheckId === "stationarity" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              {(() => {
                const byId = (id: string) => stationarityProfile?.tests.find((item) => item.id === id) ?? null;
                return (
                  <>
                    <Metric label="N" value={stationarityProfile ? String(stationarityProfile.n_observations) : "—"} />
                    <Metric label="Сводный вывод" value={stationarityConsensusLabel(stationarityProfile?.consensus)} />
                    <Metric label="ADF: p" value={formatMetric(byId("adf_level")?.p_value)} />
                    <Metric label="KPSS: p" value={formatMetric(byId("kpss_level")?.p_value)} />
                    <Metric label="PP: p" value={formatMetric(byId("pp")?.p_value)} />
                    <Metric label="Разрыв по ZA" value={stationarityProfile?.breakpoint_label ?? (stationarityProfile?.breakpoint_index !== null && stationarityProfile?.breakpoint_index !== undefined ? String(stationarityProfile.breakpoint_index) : "—")} />
                  </>
                );
              })()}
            </div>
          ) : activeCheckId === "distribution" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              <Metric label="N" value={distributionProfile ? String(distributionProfile.n_observations) : "—"} />
              <Metric label="Форма" value={distributionProfile?.shape_label ?? "—"} />
              <Metric label="Асимметрия" value={formatMetric(distributionProfile?.skewness)} />
              <Metric label="Эксцесс" value={formatMetric(distributionProfile?.excess_kurtosis)} />
              <Metric label="Q–Q: r" value={formatMetric(distributionProfile?.qq_r)} />
              <Metric label="Отклонено тестов" value={distributionProfile?.applicable ? String(distributionProfile.tests.filter((item) => item.reject_normality === true).length) : "—"} />
            </div>
          ) : activeCheckId === "structural" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              <Metric label="N" value={structuralProfile ? String(structuralProfile.n_observations) : "—"} />
              <Metric label="CUSUM p" value={formatMetric(structuralProfile?.cusum.p_value)} />
              <Metric label="Кандидатов" value={structuralProfile?.applicable ? String(structuralProfile.break_count) : "—"} />
              <Metric label="Поддержано" value={structuralProfile?.applicable ? String(structuralProfile.supported_count) : "—"} />
              <Metric label="Сегментов" value={structuralProfile?.applicable ? String(structuralProfile.segments.length) : "—"} />
              <Metric label="Штраф" value={formatMetric(structuralProfile?.penalty_value)} />
            </div>
          ) : activeCheckId === "feature_select" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4"><Metric label="N" value={featureSelectionProfile?String(featureSelectionProfile.n_observations):"—"}/><Metric label="Кандидатов" value={featureSelectionProfile?.applicable?String(featureSelectionProfile.analyzed_features):"—"}/><Metric label="Сохранить" value={String(featureSelectionProfile?.kept_features.length??0)}/><Metric label="Проверить" value={String(featureSelectionProfile?.review_features.length??0)}/><Metric label="Слабый сигнал" value={String(featureSelectionProfile?.low_signal_features.length??0)}/><Metric label="Значимых Granger" value={String(featureSelectionProfile?.features.filter(x=>x.granger_significant).length??0)}/></div>
          ) : activeCheckId === "validation_strategy" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              <Metric label="N" value={validationStrategyProfile ? String(validationStrategyProfile.n_observations) : "—"} />
              <Metric label="Схема" value={validationStrategyProfile?.strategy ?? "—"} />
              <Metric label="Горизонт" value={validationStrategyProfile ? String(validationStrategyProfile.horizon) : "—"} />
              <Metric label="Folds" value={validationStrategyProfile?.applicable ? String(validationStrategyProfile.effective_splits) : "—"} />
              <Metric label="Начальный train" value={validationStrategyProfile?.applicable ? String(validationStrategyProfile.initial_train_size) : "—"} />
              <Metric label="Test coverage" value={validationStrategyProfile?.applicable ? `${formatMetric(validationStrategyProfile.test_coverage)}%` : "—"} />
            </div>
          ) : activeCheckId === "model_matrix" ? (
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              <Metric label="Моделей" value={modelMatrixProfile ? String(modelMatrixProfile.summary.total_models) : "—"} />
              <Metric label="Совместимы" value={modelMatrixProfile?.applicable ? String(modelMatrixProfile.summary.candidates) : "—"} />
              <Metric label="С оговорками" value={modelMatrixProfile?.applicable ? String(modelMatrixProfile.summary.conditional) : "—"} />
              <Metric label="Заблокированы" value={modelMatrixProfile?.applicable ? String(modelMatrixProfile.summary.blocked) : "—"} />
              <Metric label="Backend готов" value={modelMatrixProfile?.applicable ? String(modelMatrixProfile.summary.ready) : "—"} />
              <Metric label="Runnable shortlist" value={modelMatrixProfile?.applicable ? String(modelMatrixProfile.runnable_shortlist.length) : "—"} />
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Строк" value="200" />
              <Metric label="Признаков" value="8" />
              <Metric label="H(ряд)" value="2.14" />
              <Metric label="ADF p" value="0.03" />
              <Metric label="Частота" value="D" />
            </div>
          )}
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: панель управления + список исследований ── */}
      <aside className="w-80 shrink-0 pt-1">
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-neutral-800">
            Панель управления
          </h2>
        </div>
        <div className="max-h-[830px] overflow-y-auto pr-2 space-y-5 feed-scroll">
          {orderedChecks.map((check) => (
            <article
              key={check.id}
              className={`pb-5 border-b border-neutral-100 ${
                check.id === activeCheckId ? "border-l-4 border-l-brand pl-3" : ""
              }`}
            >
              <h3 className="font-semibold mb-1">
                <StatusIcon status={check.status} /> Исследование: {check.label}
              </h3>

              <p className="text-sm text-neutral-600 mb-2">{check.description}</p>

              {/* Бейдж результата — после описания */}
              {check.id === "descriptive" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Рассчитываем статистики по полному датасету…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {descriptiveRequestError ?? "Ошибка расчёта статистик"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {descriptiveNoDataset
                        ? "Нет активного датасета"
                        : "В датасете нет числовых признаков"}
                    </p>
                  )}
                  {check.status === "warning" && check.count !== null && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      Для {check.count} {check.count === 1 ? "признака" : "признаков"} недостаточно наблюдений
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Рассчитано признаков: {descriptiveProfile?.columns.length ?? 0}
                    </p>
                  )}
                </>
              ) : check.id === "correlation" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Рассчитываем ACF/PACF по полному ряду…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {correlationRequestError ?? "Ошибка расчёта ACF/PACF"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {correlationNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      {correlationProfile?.reason ?? "ACF/PACF неприменимы"}
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      {correlationProfile?.is_white_noise
                        ? "Ljung–Box: автокорреляция совместно не обнаружена"
                        : `Значимых лагов: ACF ${correlationProfile?.significant_acf_lags.length ?? 0}, PACF ${correlationProfile?.significant_pacf_lags.length ?? 0}`}
                    </p>
                  )}
                </>
              ) : check.id === "ih_analysis" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Вычисляем IH-профиль и перестановочный baseline…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {ihRequestError ?? "Ошибка IH-анализа"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {ihNoDataset ? "Нет активного датасета" : "Нет исследуемого признака Y"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      {ihProfile?.reason ?? "IH-анализ неприменим"}
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Исследовано факторов: {ihProfile?.features_analyzed ?? 0}; значимых после FDR: {ihProfile?.results.filter((item) => item.significant).length ?? 0}
                    </p>
                  )}
                </>
              ) : check.id === "seasonality" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Строим спектральный и фазовый профиль…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {seasonalityRequestError ?? "Ошибка спектрального анализа"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {seasonalityNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      {seasonalityProfile?.reason ?? "Спектральный анализ неприменим"}
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      {seasonalityProfile?.confirmed_periods
                        ? `Подтверждено периодов: ${seasonalityProfile.confirmed_periods}`
                        : "Анализ завершён: устойчивые периоды не подтверждены"}
                    </p>
                  )}
                </>
              ) : check.id === "stationarity" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Выполняем ADF/KPSS/PP и скользящие диагностики…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {stationarityRequestError ?? "Ошибка проверки стационарности"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {stationarityNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      {stationarityProfile?.applicable === false
                        ? stationarityProfile.reason
                        : stationarityProfile?.recommendation ?? "Результаты тестов требуют проверки"}
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      {stationarityConsensusLabel(stationarityProfile?.consensus)} при α={stationarityProfile?.alpha ?? stationarityParameters.alpha}
                    </p>
                  )}
                </>
              ) : check.id === "distribution" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                      Оцениваем форму распределения и выполняем тесты…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {distributionRequestError ?? "Ошибка анализа распределения"}
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {distributionNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      {distributionProfile?.applicable === false
                        ? distributionProfile.reason
                        : distributionProfile?.recommendation ?? "Форма требует дополнительной проверки"}
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Нормальная форма не отвергается при α={distributionProfile?.alpha ?? distributionParameters.alpha}
                    </p>
                  )}
                </>
              ) : check.id === "structural" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">Ищем изменения уровня и наклона…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{structuralRequestError ?? "Ошибка анализа структурных сдвигов"}</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{structuralNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}</p>}
                  {check.status === "warning" && <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">{structuralProfile?.applicable === false ? structuralProfile.reason : structuralProfile?.recommendation ?? "Найдены кандидаты, требующие проверки"}</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">Структурные сдвиги не обнаружены при выбранных параметрах</p>}
                </>
              ) : check.id === "feature_select" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">Сопоставляем связь с целью, VIF и Granger…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{featureSelectionRequestError}</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{featureSelectionNoDataset?"Нет активного датасета":featureSelectionProfile?.applicability_status==="not_required"?"Одномерный ряд: отбор признаков не требуется":"Нет числовой цели Y"}</p>}
                  {check.status === "warning" && <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">{featureSelectionProfile?.reason??featureSelectionProfile?.recommendation}</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">Предварительно сохранить: {featureSelectionProfile?.kept_features.length??0}</p>}
                </>
              ) : check.id === "validation_strategy" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">Строим временные folds без утечки…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{validationStrategyRequestError}</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{validationStrategyNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}</p>}
                  {check.status === "warning" && <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">{validationStrategyProfile?.reason ?? validationStrategyProfile?.warnings[0] ?? validationStrategyProfile?.recommendation}</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">Готово folds: {validationStrategyProfile?.effective_splits ?? 0}; последний test до конца ряда</p>}
                </>
              ) : check.id === "model_matrix" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">Проверяем требования каталога моделей…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{modelMatrixRequestError}</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{modelMatrixNoDataset ? "Нет активного датасета" : "Нет числового исследуемого признака"}</p>}
                  {check.status === "warning" && <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">{modelMatrixProfile?.reason ?? `Shortlist: ${modelMatrixProfile?.shortlist.length ?? 0}; backend готов: ${modelMatrixProfile?.runnable_shortlist.length ?? 0}`}</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">Runnable shortlist: {modelMatrixProfile?.runnable_shortlist.length ?? 0}; сравните на временных folds</p>}
                </>
              ) : (
                <>
                  {check.count !== null && check.count > 0 && (
                    <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      ⚠️ Найдено {check.count} нарушений
                    </p>
                  )}
                  {check.status === "done" && (
                    <p className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Исследование завершено
                    </p>
                  )}
                </>
              )}

              {/* Кнопка «Метрики и алгоритм» */}
              <button
                onClick={() => handleDescriptionClick(check, "metrics")}
                className={`w-full mb-2 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "metrics"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Метрики и алгоритм
              </button>

              {/* Кнопка «Полный пайплайн» */}
              <button
                onClick={() => handleDescriptionClick(check, "pipeline")}
                className={`w-full mb-3 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "pipeline"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Полный пайплайн
              </button>

              {check.id === "descriptive" ? (
                <Button
                  type="button"
                  onClick={() => setDescriptiveRefreshKey((key) => key + 1)}
                  disabled={descriptiveBusy}
                >
                  {descriptiveBusy ? "Рассчитываем…" : "Пересчитать статистики"}
                </Button>
              ) : check.id === "correlation" ? (
                <Button
                  type="button"
                  onClick={() => setCorrelationRefreshKey((key) => key + 1)}
                  disabled={correlationBusy || !activeFeature}
                >
                  {correlationBusy ? "Рассчитываем…" : "Пересчитать корреляцию"}
                </Button>
              ) : check.id === "ih_analysis" ? (
                <Button
                  type="button"
                  onClick={() => setIhRefreshKey((key) => key + 1)}
                  disabled={ihBusy || !activeFeature}
                >
                  {ihBusy ? "Рассчитываем…" : "Пересчитать IH-анализ"}
                </Button>
              ) : check.id === "seasonality" ? (
                <Button
                  type="button"
                  onClick={() => setSeasonalityRefreshKey((key) => key + 1)}
                  disabled={seasonalityBusy || !activeFeature}
                >
                  {seasonalityBusy ? "Рассчитываем…" : "Пересчитать сезонность"}
                </Button>
              ) : check.id === "stationarity" ? (
                <Button
                  type="button"
                  onClick={() => setStationarityRefreshKey((key) => key + 1)}
                  disabled={stationarityBusy || !activeFeature}
                >
                  {stationarityBusy ? "Рассчитываем…" : "Пересчитать стационарность"}
                </Button>
              ) : check.id === "distribution" ? (
                <Button
                  type="button"
                  onClick={() => setDistributionRefreshKey((key) => key + 1)}
                  disabled={distributionBusy || !activeFeature}
                >
                  {distributionBusy ? "Рассчитываем…" : "Пересчитать распределение"}
                </Button>
              ) : check.id === "structural" ? (
                <Button
                  type="button"
                  onClick={() => setStructuralRefreshKey((key) => key + 1)}
                  disabled={!activeFeature}
                >
                  Пересчитать сдвиги
                </Button>
              ) : check.id === "feature_select" ? (
                <Button type="button" onClick={()=>setFeatureSelectionRefreshKey(key=>key+1)} disabled={featureSelectionBusy||!activeFeature}>{featureSelectionBusy?"Рассчитываем…":"Пересчитать отбор"}</Button>
              ) : check.id === "validation_strategy" ? (
                <Button type="button" onClick={() => setValidationStrategyRefreshKey((key) => key + 1)} disabled={validationStrategyBusy || !activeFeature}>{validationStrategyBusy ? "Строим…" : "Пересчитать стратегию"}</Button>
              ) : check.id === "model_matrix" ? (
                <Button type="button" onClick={() => setModelMatrixRefreshKey((key) => key + 1)} disabled={modelMatrixBusy || !activeFeature}>{modelMatrixBusy ? "Проверяем…" : "Пересчитать матрицу"}</Button>
              ) : (
                <Button>Запустить анализ ({check.label.toLowerCase()})</Button>
              )}
            </article>
          ))}
        </div>
      </aside>
      </div>
      <DatasetPassportPanel
        stage="modeling_entry"
        targetColumn={activeFeature}
        historyResetNotice={passportResetNotice
          ? `Смена исследуемого признака «${passportResetNotice.previousColumn}» → «${passportResetNotice.newColumn}» сбросила цепочку паспортов.`
          : null}
      />
    </div>
  );
}
