"use client";

// packages/ui/components/TsAnalysisPreprocessing.tsx
//
// ОБЩИЙ компонент фичи "Предобработка" -- используется И embedded-,
// И standalone-приложением. Только внешняя "рамка" (шапка/навигация)
// вокруг него отличается между apps/embedded и apps/standalone;
// сама аналитическая UI-логика -- одна, чтобы не плодить дубли
// (см. историю разговора: 4 копии calculate_ts_passport -- урок учтён).
//
// Компоновка v2 (по макету «Компоновка2 вкладки_Предобработка»):
//   [Левая ~240px]     [Центр flex-1]         [Правая ~320px]
//   ▼ Признак: price   Метрики и алгоритм     Проверка: ...
//   3/10 ████░░         [текстовое поле]       [бейдж результата]
//   ┌─Пропуски──⚠─┐    Обзор: Пропуски        описание
//   ├─Выбросы───⚠─┤    [график]               ▼ Метрики
//   └─────────────┘    [Строк][Проп][Выбр]    ▼ Пайплайн
//                                                [Пересчитать]

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { StepperNextModuleButton } from "./StepperNextModuleButton";
import { sessionApiUrl } from "../lib/apiClient";
import { useTargetColumn } from "../hooks/useTargetColumn";
// Волна 2 plan_review_charts.md (RCH-2): инвалидация модуль-глобального
// кэша раскрытия графиков в единственной точке истины — обработчике apply.
import { invalidateChartDetailCache } from "../hooks/useChartDetailData";
import { PreprocessingMissingOverview, type MissingProfileResponse } from "./PreprocessingMissingOverview";
import { PreprocessingMissingPipeline } from "./PreprocessingMissingPipeline";
import { PreprocessingOutliersOverview, type OutlierProfileResponse } from "./PreprocessingOutliersOverview";
import { PreprocessingOutliersPipeline } from "./PreprocessingOutliersPipeline";
import { PreprocessingRegularityOverview, type RegularityProfileResponse } from "./PreprocessingRegularityOverview";
import { PreprocessingRegularityPipeline } from "./PreprocessingRegularityPipeline";
import {
  PreprocessingDecompositionOverview,
  type PreprocessingDecompositionProfileResponse,
} from "./PreprocessingDecompositionOverview";
import { PreprocessingDecompositionPipeline } from "./PreprocessingDecompositionPipeline";
import {
  PreprocessingVarianceOverview,
  type VarianceProfileResponse,
} from "./PreprocessingVarianceOverview";
import { PreprocessingVariancePipeline } from "./PreprocessingVariancePipeline";
import {
  PreprocessingSmoothingOverview,
  type SmoothingProfileResponse,
} from "./PreprocessingSmoothingOverview";
import { PreprocessingSmoothingPipeline } from "./PreprocessingSmoothingPipeline";
import {
  PreprocessingStationarityOverview,
  type StationarityProfileResponse,
} from "./PreprocessingStationarityOverview";
import { PreprocessingStationarityPipeline } from "./PreprocessingStationarityPipeline";
import {
  PreprocessingSpectralOverview,
  type PreprocessingSpectralProfileResponse,
} from "./PreprocessingSpectralOverview";
import {
  PreprocessingSpectralPipeline,
  type SpectralParameters,
} from "./PreprocessingSpectralPipeline";
import {
  PreprocessingFeatureEngineeringOverview,
  type FeatureGenerationProfileResponse,
} from "./PreprocessingFeatureEngineeringOverview";
import { PreprocessingFeatureEngineeringPipeline } from "./PreprocessingFeatureEngineeringPipeline";
import {
  PreprocessingScalingOverview,
  type ScalingProfileResponse,
} from "./PreprocessingScalingOverview";
import { PreprocessingScalingPipeline } from "./PreprocessingScalingPipeline";
import { DatasetPassportPanel } from "./DatasetPassportPanel";
import { describeNode } from "../lib/knowledge/knowledge";

// ── Типы ──────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
}

// ── Моковые данные (заменить на API) ─────────────────────────

const CHECKS: Check[] = [
  { id: "missing", label: "Пропуски", status: "pending", count: null,
    description: "Пропуски нарушают DatetimeIndex, делают невозможной STL-декомпозицию, искажают ACF/PACF и ломают ARIMA/SARIMA. Стратегии: удаление строк, медиана/мода, среднее/мода, ноль/Unknown, линейная интерполяция, флаг пропуска." },
  { id: "outliers", label: "Выбросы", status: "pending", count: null,
    description: "Выбросы завышают дисперсию, искажают оценки тренда и ломают тесты стационарности (ADF/KPSS). Методы: IQR, Z-score, Modified Z-score (MAD), процентильный. Обнаружение — на сырых значениях по умолчанию; на остатке после STL-декомпозиции — опционально, когда декомпозиция применима." },
  { id: "regularity", label: "Регулярность ряда", status: "pending", count: null,
    description: "Нерегулярный временной шаг мешает декомпозиции (STL), спектральному анализу (FFT) и моделям ARIMA/SARIMA. Стратегии: сортировка по дате, ресемплирование к целевой частоте с интерполяцией/ffill/bfill/нулём/без заполнения, флаг нарушения." },
  { id: "decomposition", label: "Декомпозиция ряда", status: "pending", count: null,
    description: "Робастный STL: наблюдение = тренд + сезонность + остаток. Диагностика — strength-метрики, ACF/Ljung–Box и Jarque–Bera; отдельная «циклическая» компонента не приписывается STL." },
  { id: "variance_stab", label: "Стабилизация дисперсии", status: "pending", count: null,
    description: "Гетероскедастичность ломает доверительные интервалы и тесты. Трансформации: Box-Cox, Yeo-Johnson, log, sqrt. Параметры сохраняются для обратного преобразования." },
  { id: "smoothing", label: "Сглаживание ряда", status: "pending", count: null,
    description: "Удаление высокочастотного шума методами SMA, EMA, Holt-Winters, HP-filter, Savitzky-Golay или фильтром Калмана. Опциональный шаг для зашумлённых рядов." },
  { id: "stationarity", label: "Стационарность ряда", status: "pending", count: null,
    description: "Консенсус ADF/KPSS различает стационарность уровня, тренд-стационарность, единичный корень и неопределённость. Доступны detrend, минимальные обычные/сезонные разности и log-разность с сохранением inverse-границ." },
  { id: "spectral", label: "Спектральный анализ", status: "pending", count: null,
    description: "Диагностика периодической структуры: Hann FFT/periodogram, медианный Welch PSD, CWT и подтверждение кандидатов через ACF/фазовый профиль. Периоды сохраняются для следующего шага без мутации ряда." },
  { id: "feature_eng", label: "Генерация признаков", status: "pending", count: null,
    description: "Каузальные лаги, trailing rolling-статистики и лаговые разности; известные заранее календарные sin/cos, time_idx и Fourier-гармоники периодов из спектрального анализа." },
  { id: "scaling", label: "Масштабирование", status: "pending", count: null,
    description: "Fold-safe рецепты StandardScaler, MinMaxScaler, RobustScaler, MaxAbsScaler и осознанный QuantileTransformer. Scaler обучается только на train каждого временного fold." },
];

// ── Справка по целям модуля «Предобработка» (из app.py) ───────────


// ── Метрики и алгоритм / Мастер: остановка «Пропуски» ─────────────
// Единственная остановка степпера с реальным backend -- см.
// app/preprocessing/missing.py, apps/api/missing_correction.py. Формат
// текста -- по образцу RANGES_METRICS_DESCRIPTION/RANGES_PIPELINE_DESCRIPTION
// из TsAnalysisValidation.tsx (Цель / Метрики / Алгоритм backend /
// опциональный смысловой блок; отдельная константа для мастера).





















type PreprocessingCheckMode = "auto" | "enabled" | "disabled";

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisPreprocessing() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  // Инвариант информативности (2026-09-15, зеркально VALID-2): активная
  // остановка степпера АВТОМАТИЧЕСКИ загружает в «Описание» содержимое
  // «Метрики и алгоритм» данной остановки (и делает кнопку активной) —
  // вне зависимости от статуса остановки. Контент метрик — статические
  // константы компонента (без зависимостей от /dataset/*-профилей и
  // наличия датасета), поэтому автозагрузка возможна всегда. Секция null
  // более не производится: начальное состояние — метрики первой активной
  // остановки («Пропуски»); placeholder-ветка ниже остаётся как
  // defense-in-depth при недостижимом null.
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | null>("metrics");
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // Общий target_column вместо сломанного mock-списка тикеров. Хук
  // восстанавливает сохранённый выбор из AnalysisSession либо один раз
  // фиксирует backend-рекомендацию (первая числовая, кроме временной оси).
  const {
    targetColumn: activeFeature,
    availableColumns: numericFeatures,
    loading: targetLoading,
    error: targetError,
    setColumn: setActiveFeature,
    passportResetNotice,
  } = useTargetColumn(undefined);

  // ── Режимы остановок (Task 47, применено к «Предобработке») ──
  // «Авто» / «Включена» / «Отключена» -- сохраняются в сессии через
  // GET/PUT /dataset/preprocessing-check-modes, отдельно от режимов
  // «Валидации» (другой степпер, другой словарь на бэкенде). Только
  // Селектор показывается только у остановок с реальным backend-профилем;
  // для ещё не реализованных «Масштабирования»/«Паспорта» режим не обещаем.
  const [checkModes, setCheckModes] = useState<Record<string, PreprocessingCheckMode>>({});
  const [modeSaving, setModeSaving] = useState<string | null>(null);
  const [modeError, setModeError] = useState<{ checkId: string; message: string } | null>(null);

  // ── Версия состояния датасета модуля (инвалидация всех профилей) ──
  // Применение исправления в ЛЮБОЙ остановке (onApplied всех 10 мастеров)
  // мутирует активный датасет сессии — после этого профили ВСЕХ остановок
  // (их applicability-гейты зависят от пропусков/выбросов/регулярности,
  // см. preprocessing_decomposition.py: «В ряду N пропусков; сначала
  // завершите остановку „Пропуски“») становятся устаревшими. Единый
  // счётчик в deps всех profile-fetch useEffect гарантирует, что после
  // каждого применения степпер, бейджи, метрики и Обзоры автоматически
  // перезапрашиваются — без перезагрузки страницы. Собственные
  // xxxRefreshKey остальных 7 остановок остаются точками РУЧНОГО
  // пересчёта (смена режима, кнопка «Пересчитать») и чужие профили не
  // инвалидируют. Self-fetch Обзор-панели трёх остановок («Пропуски»,
  // «Выбросы», «Регулярность») получают СУММУ ключей
  // xxxRefreshKey + datasetVersion (PREPR-4): PREPR-3 бампил только
  // datasetVersion, а Обзоры оставались на собственных ключах, которые
  // после PREPR-3 никто не бампил в применениях — данные Обзора
  // замерзали до перезагрузки страницы (та же природа бага, что чинил
  // PREPR-3). Сумма монотонно растёт от ЛЮБОГО источника инвалидации:
  // применение (datasetVersion) обновляет все Обзоры, смена режима
  // (собственный ключ) — только Обзор своей остановки.
  const [datasetVersion, setDatasetVersion] = useState(0);

  // ── Волна 2 plan_review_charts.md (RCH-2): единый обработчик apply ──
  // Все 10 мастеров получают ОДИН обработчик: bump datasetVersion
  // (перезапрос профилей, PREPR-4) + invalidateChartDetailCache() —
  // очистка модуль-глобального кэша раскрытия useChartDetailData. Ключ
  // кэша (profileKey, fingerprint, params) не видит мутацию датасета
  // (column/параметры раскрытия от apply не меняются) и переживает
  // ремоунты/переходы между модулями — без очистки раскрытый график
  // Обзора отдавал бы payload ДО мутации (класс OUTL-1 в слое C).
  // Глобальная инвалидация закрывает и EdaStructuralBreaksOverview
  // (fingerprint=datasetKey не меняется при in-place мутации).
  const handleApplied = () => {
    setDatasetVersion((v) => v + 1);
    invalidateChartDetailCache();
  };

  // ── Остановка «Пропуски»: реальный статус вместо мока ──
  // Лёгкий собственный запрос профиля (тот же /dataset/missing-profile,
  // что использует и PreprocessingMissingOverview) -- нужен здесь отдельно,
  // чтобы степпер слева и статус-бейдж справа отражали состояние даже пока
  // Overview/Pipeline ещё не смонтированы (активна другая проверка).
  // Дублирование запроса такое же, как между /dataset/validate и
  // /dataset/range-profile в TsAnalysisValidation.tsx -- уже принятый
  // в проекте компромисс между простотой компонента и числом запросов.
  const [missingProfile, setMissingProfile] = useState<MissingProfileResponse | null>(null);
  const [missingLoading, setMissingLoading] = useState(true);
  const [missingNoDataset, setMissingNoDataset] = useState(false);
  const [missingError, setMissingError] = useState<string | null>(null);
  const [missingRefreshKey, setMissingRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setMissingLoading(true);
    setMissingError(null);
    setMissingNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/missing-profile"), { credentials: "include" });
        if (response.status === 404) {
          if (active) setMissingNoDataset(true);
          return;
        }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: MissingProfileResponse = await response.json();
        if (active) {
          setMissingProfile(data);
          setCheckModes((current) => ({ ...current, missing: data.mode }));
        }
      } catch (caught) {
        if (active) setMissingError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль пропусков");
      } finally {
        if (active) setMissingLoading(false);
      }
    })();
    return () => { active = false; };
  }, [missingRefreshKey, datasetVersion]);

  // Режим и статус остановки «Пропуски» приходят напрямую с бэкенда
  // (единый источник истины -- та же политика auto/enabled/disabled, что
  // применяется к /dataset/missing-profile). "skipped" покрывает и явное
  // отключение, и нейтральную неприменимость (0 колонок) -- разница
  // передаётся через status_reason, не через отдельные значения иконки.
  const missingStatus: CheckStatus = missingLoading
    ? "running"
    : missingNoDataset
    ? "skipped"
    : missingError
    ? "error"
    : missingProfile
    ? missingProfile.status
    : "pending";

  // ── Остановка «Выбросы»: тот же паттерн, что и «Пропуски» ──
  const [outliersProfile, setOutliersProfile] = useState<OutlierProfileResponse | null>(null);
  const [outliersLoading, setOutliersLoading] = useState(true);
  const [outliersNoDataset, setOutliersNoDataset] = useState(false);
  const [outliersError, setOutliersError] = useState<string | null>(null);
  const [outliersRefreshKey, setOutliersRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setOutliersLoading(true);
    setOutliersError(null);
    setOutliersNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/outlier-profile?method=iqr"), { credentials: "include" });
        if (response.status === 404) {
          if (active) setOutliersNoDataset(true);
          return;
        }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: OutlierProfileResponse = await response.json();
        if (active) {
          setOutliersProfile(data);
          setCheckModes((current) => ({ ...current, outliers: data.mode }));
        }
      } catch (caught) {
        if (active) setOutliersError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль выбросов");
      } finally {
        if (active) setOutliersLoading(false);
      }
    })();
    return () => { active = false; };
  }, [outliersRefreshKey, datasetVersion]);

  const outliersStatus: CheckStatus = outliersLoading
    ? "running"
    : outliersNoDataset
    ? "skipped"
    : outliersError
    ? "error"
    : outliersProfile
    ? outliersProfile.status
    : "pending";

  // ── Остановка «Регулярность»: тот же паттерн ──
  const [regularityProfile, setRegularityProfile] = useState<RegularityProfileResponse | null>(null);
  const [regularityLoading, setRegularityLoading] = useState(true);
  const [regularityNoDataset, setRegularityNoDataset] = useState(false);
  const [regularityError, setRegularityError] = useState<string | null>(null);
  const [regularityRefreshKey, setRegularityRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setRegularityLoading(true);
    setRegularityError(null);
    setRegularityNoDataset(false);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/preprocessing/regularity-profile"), { credentials: "include" });
        if (response.status === 404) {
          if (active) setRegularityNoDataset(true);
          return;
        }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: RegularityProfileResponse = await response.json();
        if (active) {
          setRegularityProfile(data);
          setCheckModes((current) => ({ ...current, regularity: data.mode }));
        }
      } catch (caught) {
        if (active) setRegularityError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль регулярности");
      } finally {
        if (active) setRegularityLoading(false);
      }
    })();
    return () => { active = false; };
  }, [regularityRefreshKey, datasetVersion]);

  const regularityStatus: CheckStatus = regularityLoading
    ? "running"
    : regularityNoDataset
    ? "skipped"
    : regularityError
    ? "error"
    : regularityProfile
    ? regularityProfile.status
    : "pending";

  // ── Остановка «Декомпозиция»: профиль зависит от общего target ──
  const [decompositionProfile, setDecompositionProfile] = useState<PreprocessingDecompositionProfileResponse | null>(null);
  const [decompositionLoading, setDecompositionLoading] = useState(false);
  const [decompositionNoDataset, setDecompositionNoDataset] = useState(false);
  const [decompositionError, setDecompositionError] = useState<string | null>(null);
  const [decompositionRefreshKey, setDecompositionRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setDecompositionError(null);
    setDecompositionNoDataset(false);
    if (!activeFeature) {
      setDecompositionProfile(null);
      setDecompositionLoading(false);
      return () => { active = false; };
    }
    setDecompositionLoading(true);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl(`/dataset/preprocessing/decomposition-profile?column=${encodeURIComponent(activeFeature)}`), { credentials: "include" });
        if (response.status === 404) { if (active) setDecompositionNoDataset(true); return; }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: PreprocessingDecompositionProfileResponse = await response.json();
        if (active) {
          setDecompositionProfile(data);
          setCheckModes((current) => ({ ...current, decomposition: data.mode }));
        }
      } catch (caught) {
        if (active) setDecompositionError(caught instanceof Error ? caught.message : "Не удалось выполнить декомпозицию");
      } finally { if (active) setDecompositionLoading(false); }
    })();
    return () => { active = false; };
  }, [activeFeature, decompositionRefreshKey, datasetVersion]);

  const decompositionStatus: CheckStatus = decompositionLoading
    ? "running"
    : decompositionNoDataset
    ? "skipped"
    : decompositionError
    ? "error"
    : decompositionProfile
    ? decompositionProfile.status
    : "pending";

  // ── Остановка «Стабилизация дисперсии»: профиль target + preview ──
  const [varianceProfile, setVarianceProfile] = useState<VarianceProfileResponse | null>(null);
  const [varianceLoading, setVarianceLoading] = useState(false);
  const [varianceNoDataset, setVarianceNoDataset] = useState(false);
  const [varianceError, setVarianceError] = useState<string | null>(null);
  const [varianceRefreshKey, setVarianceRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setVarianceError(null); setVarianceNoDataset(false);
    if (!activeFeature) { setVarianceProfile(null); setVarianceLoading(false); return () => { active = false; }; }
    setVarianceLoading(true);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl(`/dataset/preprocessing/variance-profile?column=${encodeURIComponent(activeFeature)}`), { credentials: "include" });
        if (response.status === 404) { if (active) setVarianceNoDataset(true); return; }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: VarianceProfileResponse = await response.json();
        if (active) { setVarianceProfile(data); setCheckModes((current) => ({ ...current, variance_stab: data.mode })); }
      } catch (caught) {
        if (active) setVarianceError(caught instanceof Error ? caught.message : "Не удалось оценить стабильность дисперсии");
      } finally { if (active) setVarianceLoading(false); }
    })();
    return () => { active = false; };
  }, [activeFeature, varianceRefreshKey, datasetVersion]);

  const varianceStatus: CheckStatus = varianceLoading ? "running" : varianceNoDataset ? "skipped" : varianceError ? "error" : varianceProfile ? varianceProfile.status : "pending";

  // ── Остановка «Сглаживание ряда»: каузальный baseline + offline-сравнение ──
  const [smoothingProfile, setSmoothingProfile] = useState<SmoothingProfileResponse | null>(null);
  const [smoothingLoading, setSmoothingLoading] = useState(false);
  const [smoothingNoDataset, setSmoothingNoDataset] = useState(false);
  const [smoothingError, setSmoothingError] = useState<string | null>(null);
  const [smoothingRefreshKey, setSmoothingRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setSmoothingError(null); setSmoothingNoDataset(false);
    if (!activeFeature) { setSmoothingProfile(null); setSmoothingLoading(false); return () => { active = false; }; }
    setSmoothingLoading(true);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl(`/dataset/preprocessing/smoothing-profile?column=${encodeURIComponent(activeFeature)}`), { credentials: "include" });
        if (response.status === 404) { if (active) setSmoothingNoDataset(true); return; }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: SmoothingProfileResponse = await response.json();
        if (active) { setSmoothingProfile(data); setCheckModes((current) => ({ ...current, smoothing: data.mode })); }
      } catch (caught) {
        if (active) setSmoothingError(caught instanceof Error ? caught.message : "Не удалось оценить потребность в сглаживании");
      } finally { if (active) setSmoothingLoading(false); }
    })();
    return () => { active = false; };
  }, [activeFeature, smoothingRefreshKey, datasetVersion]);

  const smoothingStatus: CheckStatus = smoothingLoading ? "running" : smoothingNoDataset ? "skipped" : smoothingError ? "error" : smoothingProfile ? smoothingProfile.status : "pending";

  // ── Остановка «Стационарность ряда»: ADF/KPSS + безопасные разности ──
  const [stationarityProfile, setStationarityProfile] = useState<StationarityProfileResponse | null>(null);
  const [stationarityLoading, setStationarityLoading] = useState(false);
  const [stationarityNoDataset, setStationarityNoDataset] = useState(false);
  const [stationarityError, setStationarityError] = useState<string | null>(null);
  const [stationarityRefreshKey, setStationarityRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setStationarityError(null); setStationarityNoDataset(false);
    if (!activeFeature) { setStationarityProfile(null); setStationarityLoading(false); return () => { active = false; }; }
    setStationarityLoading(true);
    void (async () => {
      try {
        const query = new URLSearchParams({ column: activeFeature, seasonal_period: "12" });
        const response = await fetch(sessionApiUrl(`/dataset/preprocessing/stationarity-profile?${query.toString()}`), { credentials: "include" });
        if (response.status === 404) { if (active) setStationarityNoDataset(true); return; }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: StationarityProfileResponse = await response.json();
        if (active) { setStationarityProfile(data); setCheckModes((current) => ({ ...current, stationarity: data.mode })); }
      } catch (caught) {
        if (active) setStationarityError(caught instanceof Error ? caught.message : "Не удалось проверить стационарность");
      } finally { if (active) setStationarityLoading(false); }
    })();
    return () => { active = false; };
  }, [activeFeature, stationarityRefreshKey, datasetVersion]);

  const stationarityStatus: CheckStatus = stationarityLoading ? "running" : stationarityNoDataset ? "skipped" : stationarityError ? "error" : stationarityProfile ? stationarityProfile.status : "pending";

  // ── Остановка «Спектральный анализ»: global PSD + Welch + CWT ──
  const [spectralProfile, setSpectralProfile] = useState<PreprocessingSpectralProfileResponse | null>(null);
  const [spectralLoading, setSpectralLoading] = useState(false);
  const [spectralNoDataset, setSpectralNoDataset] = useState(false);
  const [spectralError, setSpectralError] = useState<string | null>(null);
  const [spectralRefreshKey, setSpectralRefreshKey] = useState(0);
  const [spectralParameters, setSpectralParameters] = useState<SpectralParameters>({
    minCycles: 3, maxCandidates: 6, welchSegmentLength: null, waveletScales: 24,
  });

  useEffect(() => {
    let active = true;
    setSpectralError(null); setSpectralNoDataset(false);
    if (!activeFeature) { setSpectralProfile(null); setSpectralLoading(false); return () => { active = false; }; }
    setSpectralLoading(true);
    void (async () => {
      try {
        const query = new URLSearchParams({
          column: activeFeature,
          min_cycles: String(spectralParameters.minCycles),
          max_candidates: String(spectralParameters.maxCandidates),
          wavelet_scales: String(spectralParameters.waveletScales),
        });
        if (spectralParameters.welchSegmentLength !== null) query.set("welch_segment_length", String(spectralParameters.welchSegmentLength));
        const response = await fetch(sessionApiUrl(`/dataset/preprocessing/spectral-profile?${query.toString()}`), { credentials: "include" });
        if (response.status === 404) { if (active) setSpectralNoDataset(true); return; }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: PreprocessingSpectralProfileResponse = await response.json();
        if (active) { setSpectralProfile(data); setCheckModes((current) => ({ ...current, spectral: data.mode })); }
      } catch (caught) {
        if (active) setSpectralError(caught instanceof Error ? caught.message : "Не удалось выполнить спектральный анализ");
      } finally { if (active) setSpectralLoading(false); }
    })();
    return () => { active = false; };
  }, [activeFeature, spectralRefreshKey, spectralParameters, datasetVersion]);

  const spectralStatus: CheckStatus = spectralLoading ? "running" : spectralNoDataset ? "skipped" : spectralError ? "error" : spectralProfile ? spectralProfile.status : "pending";

  // ── Остановка «Генерация признаков»: causal X + spectral hand-off ──
  const [featureGenerationProfile, setFeatureGenerationProfile] = useState<FeatureGenerationProfileResponse | null>(null);
  const [featureGenerationLoading, setFeatureGenerationLoading] = useState(false);
  const [featureGenerationNoDataset, setFeatureGenerationNoDataset] = useState(false);
  const [featureGenerationError, setFeatureGenerationError] = useState<string | null>(null);
  const [featureGenerationRefreshKey, setFeatureGenerationRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setFeatureGenerationError(null); setFeatureGenerationNoDataset(false);
    if (!activeFeature) { setFeatureGenerationProfile(null); setFeatureGenerationLoading(false); return () => { active = false; }; }
    setFeatureGenerationLoading(true);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl(`/dataset/preprocessing/feature-generation-profile?column=${encodeURIComponent(activeFeature)}`), { credentials: "include" });
        if (response.status === 404) { if (active) setFeatureGenerationNoDataset(true); return; }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: FeatureGenerationProfileResponse = await response.json();
        if (active) { setFeatureGenerationProfile(data); setCheckModes((current) => ({ ...current, feature_eng: data.mode })); }
      } catch (caught) {
        if (active) setFeatureGenerationError(caught instanceof Error ? caught.message : "Не удалось подготовить генерацию признаков");
      } finally { if (active) setFeatureGenerationLoading(false); }
    })();
    return () => { active = false; };
  }, [activeFeature, featureGenerationRefreshKey, datasetVersion]);

  const featureGenerationStatus: CheckStatus = featureGenerationLoading ? "running" : featureGenerationNoDataset ? "skipped" : featureGenerationError ? "error" : featureGenerationProfile ? featureGenerationProfile.status : "pending";

  // ── Остановка «Масштабирование»: X-matrix audit + fold-safe recipe ──
  const [scalingProfile, setScalingProfile] = useState<ScalingProfileResponse | null>(null);
  const [scalingLoading, setScalingLoading] = useState(false);
  const [scalingNoDataset, setScalingNoDataset] = useState(false);
  const [scalingError, setScalingError] = useState<string | null>(null);
  const [scalingRefreshKey, setScalingRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setScalingError(null); setScalingNoDataset(false);
    if (!activeFeature) { setScalingProfile(null); setScalingLoading(false); return () => { active = false; }; }
    setScalingLoading(true);
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl(`/dataset/preprocessing/scaling-profile?column=${encodeURIComponent(activeFeature)}`), { credentials: "include" });
        if (response.status === 404) { if (active) setScalingNoDataset(true); return; }
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
        const data: ScalingProfileResponse = await response.json();
        if (active) { setScalingProfile(data); setCheckModes((current) => ({ ...current, scaling: data.mode })); }
      } catch (caught) {
        if (active) setScalingError(caught instanceof Error ? caught.message : "Не удалось подготовить масштабирование");
      } finally { if (active) setScalingLoading(false); }
    })();
    return () => { active = false; };
  }, [activeFeature, scalingRefreshKey, datasetVersion]);

  const scalingStatus: CheckStatus = scalingLoading ? "running" : scalingNoDataset ? "skipped" : scalingError ? "error" : scalingProfile ? scalingProfile.status : "pending";

  // Итоговый список проверок -- статика для ещё не реализованных
  // остановок, реальные данные для «Пропусков», «Выбросов» и «Регулярности».
  const checks = useMemo<Check[]>(() => CHECKS.map((check) => {
    if (check.id === "missing") return { ...check, status: missingStatus, count: missingProfile?.total_missing ?? null };
    if (check.id === "outliers") return { ...check, status: outliersStatus, count: outliersProfile?.total_outliers ?? null };
    if (check.id === "regularity") return { ...check, status: regularityStatus, count: regularityProfile?.profile?.total_violations ?? null };
    if (check.id === "decomposition") return { ...check, status: decompositionStatus, count: decompositionProfile?.profile?.warnings.length ?? null };
    if (check.id === "variance_stab") return { ...check, status: varianceStatus, count: varianceProfile?.profile?.needs_stabilization ? 1 : 0 };
    if (check.id === "smoothing") return { ...check, status: smoothingStatus, count: smoothingProfile?.profile?.needs_smoothing ? 1 : 0 };
    if (check.id === "stationarity") return { ...check, status: stationarityStatus, count: stationarityProfile?.profile?.needs_transformation ? 1 : 0 };
    if (check.id === "spectral") return { ...check, status: spectralStatus, count: spectralProfile?.profile?.confirmed_periods ?? null };
    if (check.id === "feature_eng") return { ...check, status: featureGenerationStatus, count: featureGenerationProfile?.profile?.saved_feature_names.length ?? 0 };
    if (check.id === "scaling") return { ...check, status: scalingStatus, count: scalingProfile?.profile?.saved_recipe?.columns.length ?? 0 };
    return check;
  }), [missingStatus, missingProfile, outliersStatus, outliersProfile, regularityStatus, regularityProfile, decompositionStatus, decompositionProfile, varianceStatus, varianceProfile, smoothingStatus, smoothingProfile, stationarityStatus, stationarityProfile, spectralStatus, spectralProfile, featureGenerationStatus, featureGenerationProfile, scalingStatus, scalingProfile]);

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

  // Отключённые и нейтрально неприменимые остановки исключаются из
  // прогресса -- та же политика, что применена к DQ Score «Валидации»
  // в Task 47 (applicableChecks/evaluatedChecks).
  const applicableChecks = checks.filter((c) => c.status !== "skipped");
  const doneCount = applicableChecks.filter((c) => c.status === "done").length;
  const progressPct = applicableChecks.length > 0
    ? Math.round((doneCount / applicableChecks.length) * 100)
    : 100;
  const activeCheck = checks.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...checks].sort((a, b) =>
    a.id === activeCheckId ? -1 : b.id === activeCheckId ? 1 : 0
  );

  const handleCheckModeChange = async (checkId: string, mode: PreprocessingCheckMode) => {
    if (modeSaving) return;
    const previous = checkModes;
    setCheckModes((current) => ({ ...current, [checkId]: mode }));
    setModeSaving(checkId);
    setModeError(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/preprocessing-check-modes"), {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modes: { [checkId]: mode } }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      // Режим сохранён -- запускаем повторную проверку затронутой
      // остановки, чтобы степпер/панель немедленно отразили новый режим
      // (та же идея, что runValidation() после смены режима в Validation).
      if (checkId === "missing") setMissingRefreshKey((k) => k + 1);
      if (checkId === "outliers") setOutliersRefreshKey((k) => k + 1);
      if (checkId === "regularity") setRegularityRefreshKey((k) => k + 1);
      if (checkId === "decomposition") setDecompositionRefreshKey((k) => k + 1);
      if (checkId === "variance_stab") setVarianceRefreshKey((k) => k + 1);
      if (checkId === "smoothing") setSmoothingRefreshKey((k) => k + 1);
      if (checkId === "stationarity") setStationarityRefreshKey((k) => k + 1);
      if (checkId === "spectral") setSpectralRefreshKey((k) => k + 1);
      if (checkId === "feature_eng") setFeatureGenerationRefreshKey((k) => k + 1);
      if (checkId === "scaling") setScalingRefreshKey((k) => k + 1);
    } catch {
      setCheckModes(previous);
      setModeError({ checkId, message: "Не удалось сохранить режим проверки" });
    } finally {
      setModeSaving(null);
    }
  };

  // Переключение секции описания в центральном текстовом поле
  const handleDescriptionClick = (check: Check, section: "metrics" | "pipeline") => {
    setActiveCheckId(check.id);
    setDescriptionSection(section);
  };

  // Показать/скрыть справку по целям модуля (toggle: закрытие возвращает
  // к метрикам активной остановки — инвариант информативности)
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
      return describeNode("preprocessing", null, "module_help")?.text ?? null;
    }
    if (!descriptionSection) return null;
    return (
      describeNode("preprocessing", activeCheckId, descriptionSection)?.text ??
      // defense-in-depth: операция без записи в реестре (инвариант покрытия
      // гарантирует отсутствие этого пути для 10 реализованных операций)
      (descriptionSection === "metrics"
        ? `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`
        : `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`)
    );
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка — Цели модуля и результаты прохождения";
    if (!descriptionSection) return "Выберите раздел в боковой панели";
    if (activeCheckId === "missing") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Пропуски" : "Мастер исправления пропусков";
    }
    if (activeCheckId === "outliers") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Выбросы" : "Мастер исправления выбросов";
    }
    if (activeCheckId === "regularity") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Регулярность" : "Мастер исправления регулярности";
    }
    if (activeCheckId === "decomposition") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Декомпозиция ряда" : "Мастер декомпозиции ряда";
    }
    if (activeCheckId === "variance_stab") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Стабилизация дисперсии" : "Мастер стабилизации дисперсии";
    }
    if (activeCheckId === "smoothing") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Сглаживание ряда" : "Мастер сглаживания ряда";
    }
    if (activeCheckId === "stationarity") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Стационарность ряда" : "Мастер обеспечения стационарности";
    }
    if (activeCheckId === "spectral") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Спектральный анализ" : "Мастер спектрального анализа";
    }
    if (activeCheckId === "feature_eng") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Генерация признаков" : "Мастер генерации признаков";
    }
    if (activeCheckId === "scaling") {
      return descriptionSection === "metrics" ? "Метрики и алгоритм — Масштабирование" : "Мастер масштабирования";
    }
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
              Preprocessing
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
            Математические преобразования
          </p>
        </div>

        {/* Селектор числового признака */}
        <div>
          <label htmlFor="preprocessing-active-feature" className="text-[11px] text-neutral-500 block mb-1">
            Исследуемый признак:
          </label>
          <select
            id="preprocessing-active-feature"
            value={activeFeature ?? ""}
            onChange={(e) => void setActiveFeature(e.target.value)}
            disabled={targetLoading || numericFeatures.length === 0}
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
            {doneCount}/{applicableChecks.length}
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
                // VALID-2): переключение остановки автозагружает её
                // «Метрики и алгоритм» (вместо прежнего сброса Справки
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
          {/* ── Приглашение «Перейти к EDA» — паттерн Загрузки ──
              Общий StepperNextModuleButton ("Ведём исследователя за руку"):
              тот же дизайн, что на «Загрузке» (геометрия степпер-кнопок,
              пастельная заливка, индиго при наведении); светло-серая полоса
              border-t встроена в обёртку компонента. Ставится последним
              элементом списка степпера: это переход к ДРУГОМУ модулю
              пайплайна, а не ещё одна остановка Предобработки. */}
          <StepperNextModuleButton label="Перейти к EDA" href="/eda" />
        </div>
      </aside>

      {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: метрики-текст + график + метрики-карточки ── */}
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

        {/* График / Обзор / Мастер исправления */}
        <div>
          <h3 className="font-semibold mb-1">
            {activeCheckId === "missing" && descriptionSection === "pipeline"
              ? "Мастер исправления пропусков"
              : activeCheckId === "outliers" && descriptionSection === "pipeline"
              ? "Мастер исправления выбросов"
              : activeCheckId === "regularity" && descriptionSection === "pipeline"
              ? "Мастер исправления регулярности"
              : activeCheckId === "decomposition" && descriptionSection === "pipeline"
              ? "Мастер декомпозиции ряда"
              : activeCheckId === "variance_stab" && descriptionSection === "pipeline"
              ? "Мастер стабилизации дисперсии"
              : activeCheckId === "smoothing" && descriptionSection === "pipeline"
              ? "Мастер сглаживания ряда"
              : activeCheckId === "stationarity" && descriptionSection === "pipeline"
              ? "Мастер обеспечения стационарности"
              : activeCheckId === "spectral" && descriptionSection === "pipeline"
              ? "Мастер спектрального анализа"
              : activeCheckId === "feature_eng" && descriptionSection === "pipeline"
              ? "Мастер генерации признаков"
              : activeCheckId === "scaling" && descriptionSection === "pipeline"
              ? "Мастер масштабирования"
              : `Обзор: ${activeCheck.label}`}
          </h3>
          <p className="text-xs text-neutral-500 mb-3">
            {activeCheckId === "missing" && descriptionSection === "pipeline"
              ? "Выберите колонки и стратегию, оцените последствия на копии и примените исправления."
              : activeCheckId === "missing"
              ? "Полнота данных по колонкам, рекомендованная стратегия исправления."
              : activeCheckId === "outliers" && descriptionSection === "pipeline"
              ? "Выберите колонку, метод и стратегию; обнаружение — на сырых значениях или (опционально) на остатке после STL-декомпозиции."
              : activeCheckId === "outliers"
              ? "Выбросы по числовым колонкам методом IQR, границы и рекомендованный метод на колонку."
              : activeCheckId === "regularity" && descriptionSection === "pipeline"
              ? "Выберите стратегию и целевую частоту, оцените последствия на копии и примените исправления."
              : activeCheckId === "regularity"
              ? "Разрывы, дубликаты и нарушения сортировки по группам; интервалы и таймлайн — во вкладках."
              : activeCheckId === "decomposition" && descriptionSection === "pipeline"
              ? "Настройте период и выходы, оцените новые колонки на копии и подтвердите добавление."
              : activeCheckId === "decomposition"
              ? "Компоненты STL, сезонный профиль, ACF остатка и диагностика — во вкладках-бейджах."
              : activeCheckId === "variance_stab" && descriptionSection === "pipeline"
              ? "Выберите обратимую трансформацию, оцените новую колонку на копии и подтвердите добавление."
              : activeCheckId === "variance_stab"
              ? "До/после, скользящая σ, сравнение методов, распределения и диагностика — во вкладках-бейджах."
              : activeCheckId === "smoothing" && descriptionSection === "pipeline"
              ? "Выберите каузальный или offline-метод, оцените новую колонку на копии и подтвердите добавление."
              : activeCheckId === "smoothing"
              ? "Ряд, удалённая компонента/ACF, сравнение методов, спектр и диагностика — во вкладках-бейджах."
              : activeCheckId === "stationarity" && descriptionSection === "pipeline"
              ? "Выберите минимальный оператор, оцените потерю строк и inverse-контракт, затем подтвердите применение."
              : activeCheckId === "stationarity"
              ? "Ряд, rolling μ/σ, комплементарные тесты, ACF и сравнение кандидатов — во вкладках-бейджах."
              : activeCheckId === "spectral" && descriptionSection === "pipeline"
              ? "Настройте разрешение, подтвердите периоды и сохраните их без изменения датасета."
              : activeCheckId === "spectral"
              ? "FFT/periodogram, Welch PSD, CWT, фазовый профиль и кандидаты — во вкладках-бейджах."
              : activeCheckId === "feature_eng" && descriptionSection === "pipeline"
              ? "Настройте лаги, trailing rolling, календарь и Fourier; проверьте warm-up и подтвердите применение."
              : activeCheckId === "feature_eng"
              ? "Превью X, лаг-корреляции, доступность, циклические признаки и каталог — во вкладках-бейджах."
              : activeCheckId === "scaling" && descriptionSection === "pipeline"
              ? "Выберите X и scaler, выполните диагностический preview и сохраните fold-safe рецепт."
              : activeCheckId === "scaling"
              ? "До/после, масштабы, распределение, корреляции и матрица методов — во вкладках-бейджах."
              : "Меняется автоматически под активную проверку."}
          </p>

          {activeCheckId === "missing" && descriptionSection === "pipeline" ? (
            <PreprocessingMissingPipeline onApplied={handleApplied} />
          ) : activeCheckId === "missing" ? (
            <PreprocessingMissingOverview refreshKey={missingRefreshKey + datasetVersion} />
          ) : activeCheckId === "outliers" && descriptionSection === "pipeline" ? (
            <PreprocessingOutliersPipeline onApplied={handleApplied} />
          ) : activeCheckId === "outliers" ? (
            <PreprocessingOutliersOverview refreshKey={outliersRefreshKey + datasetVersion} column={activeFeature} />
          ) : activeCheckId === "regularity" && descriptionSection === "pipeline" ? (
            <PreprocessingRegularityPipeline onApplied={handleApplied} />
          ) : activeCheckId === "regularity" ? (
            <PreprocessingRegularityOverview refreshKey={regularityRefreshKey + datasetVersion} />
          ) : activeCheckId === "decomposition" && descriptionSection === "pipeline" ? (
            <PreprocessingDecompositionPipeline
              column={activeFeature}
              profile={decompositionProfile?.profile ?? null}
              onApplied={handleApplied}
            />
          ) : activeCheckId === "decomposition" ? (
            <PreprocessingDecompositionOverview
              profile={decompositionProfile?.profile ?? null}
              loading={decompositionLoading}
              error={decompositionError}
              noDataset={decompositionNoDataset}
              refreshKey={decompositionRefreshKey + datasetVersion}
            />
          ) : activeCheckId === "variance_stab" && descriptionSection === "pipeline" ? (
            <PreprocessingVariancePipeline
              column={activeFeature}
              recommendedMethod={varianceProfile?.profile.selected_method ?? null}
              onApplied={handleApplied}
            />
          ) : activeCheckId === "variance_stab" ? (
            <PreprocessingVarianceOverview
              profile={varianceProfile?.profile ?? null}
              loading={varianceLoading}
              error={varianceError}
              noDataset={varianceNoDataset}
            />
          ) : activeCheckId === "smoothing" && descriptionSection === "pipeline" ? (
            <PreprocessingSmoothingPipeline
              column={activeFeature}
              recommendedMethod={smoothingProfile?.profile.selected_method ?? null}
              onApplied={handleApplied}
            />
          ) : activeCheckId === "smoothing" ? (
            <PreprocessingSmoothingOverview
              profile={smoothingProfile?.profile ?? null}
              loading={smoothingLoading}
              error={smoothingError}
              noDataset={smoothingNoDataset}
            />
          ) : activeCheckId === "stationarity" && descriptionSection === "pipeline" ? (
            <PreprocessingStationarityPipeline
              column={activeFeature}
              recommendedMethod={stationarityProfile?.profile?.selected_method ?? null}
              seasonalPeriod={stationarityProfile?.profile?.seasonal_period ?? 12}
              onApplied={handleApplied}
            />
          ) : activeCheckId === "stationarity" ? (
            <PreprocessingStationarityOverview
              profile={stationarityProfile?.profile ?? null}
              loading={stationarityLoading}
              error={stationarityError}
              noDataset={stationarityNoDataset}
            />
          ) : activeCheckId === "spectral" && descriptionSection === "pipeline" ? (
            <PreprocessingSpectralPipeline
              column={activeFeature}
              profile={spectralProfile?.profile ?? null}
              parameters={spectralParameters}
              onParametersChange={(changes) => setSpectralParameters((current) => ({ ...current, ...changes }))}
              onApplied={handleApplied}
            />
          ) : activeCheckId === "spectral" ? (
            <PreprocessingSpectralOverview
              profile={spectralProfile?.profile ?? null}
              loading={spectralLoading}
              error={spectralError}
              noDataset={spectralNoDataset}
              parameters={spectralParameters}
              refreshKey={spectralRefreshKey + datasetVersion}
            />
          ) : activeCheckId === "feature_eng" && descriptionSection === "pipeline" ? (
            <PreprocessingFeatureEngineeringPipeline
              column={activeFeature}
              profile={featureGenerationProfile?.profile ?? null}
              onApplied={handleApplied}
            />
          ) : activeCheckId === "feature_eng" ? (
            <PreprocessingFeatureEngineeringOverview
              profile={featureGenerationProfile?.profile ?? null}
              loading={featureGenerationLoading}
              error={featureGenerationError}
              noDataset={featureGenerationNoDataset}
            />
          ) : activeCheckId === "scaling" && descriptionSection === "pipeline" ? (
            <PreprocessingScalingPipeline
              targetColumn={activeFeature}
              profile={scalingProfile?.profile ?? null}
              onApplied={handleApplied}
            />
          ) : activeCheckId === "scaling" ? (
            <PreprocessingScalingOverview
              profile={scalingProfile?.profile ?? null}
              loading={scalingLoading}
              error={scalingError}
              noDataset={scalingNoDataset}
            />
          ) : (
            <div className="bg-brand-light rounded-lg h-[468px] flex items-center justify-center text-sm text-neutral-500">
              [ график для «{activeCheck.label}» ]
            </div>
          )}

          {activeCheckId === "missing" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Строк" value={missingProfile ? String(missingProfile.total_rows) : "—"} />
              <Metric label="Колонок" value={missingProfile ? String(missingProfile.total_columns) : "—"} />
              <Metric label="Пропусков" value={missingProfile ? String(missingProfile.total_missing) : "—"} />
              <Metric label="Строк с пропуском" value={missingProfile ? String(missingProfile.rows_with_missing) : "—"} />
            </div>
          ) : activeCheckId === "outliers" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Строк" value={outliersProfile ? String(outliersProfile.total_rows) : "—"} />
              <Metric label="Числовых колонок" value={outliersProfile ? String(outliersProfile.total_numeric_columns) : "—"} />
              <Metric label="Выбросов" value={outliersProfile ? String(outliersProfile.total_outliers) : "—"} />
              <Metric label="Затронуто колонок" value={outliersProfile ? String(outliersProfile.affected_columns.length) : "—"} />
            </div>
          ) : activeCheckId === "regularity" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Разрывов" value={regularityProfile ? String(regularityProfile.profile.gap_count) : "—"} />
              <Metric label="Дублей" value={regularityProfile ? String(regularityProfile.profile.duplicate_count) : "—"} />
              <Metric label="Нарушений сортировки" value={regularityProfile ? String(regularityProfile.profile.sort_violations) : "—"} />
              <Metric label="Частота" value={regularityProfile?.profile.target_frequency ?? "—"} />
            </div>
          ) : activeCheckId === "decomposition" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Период" value={decompositionProfile?.profile.period ? String(decompositionProfile.profile.period) : "—"} />
              <Metric label="Сила тренда" value={decompositionProfile?.profile.trend_strength !== null && decompositionProfile?.profile.trend_strength !== undefined ? `${(100 * decompositionProfile.profile.trend_strength).toFixed(1)}%` : "—"} />
              <Metric label="Сила сезонности" value={decompositionProfile?.profile.seasonal_strength !== null && decompositionProfile?.profile.seasonal_strength !== undefined ? `${(100 * decompositionProfile.profile.seasonal_strength).toFixed(1)}%` : "—"} />
              <Metric label="Ljung–Box p" value={decompositionProfile?.profile.ljung_box_pvalue !== null && decompositionProfile?.profile.ljung_box_pvalue !== undefined ? decompositionProfile.profile.ljung_box_pvalue.toFixed(4) : "—"} />
            </div>
          ) : activeCheckId === "variance_stab" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Метод" value={varianceProfile?.profile.selected_method?.replace("_", "–") ?? "—"} />
              <Metric label="λ" value={varianceProfile?.profile.lambda_value !== null && varianceProfile?.profile.lambda_value !== undefined ? varianceProfile.profile.lambda_value.toFixed(4) : "—"} />
              <Metric label="Score до" value={varianceProfile?.profile.diagnostics_before ? varianceProfile.profile.diagnostics_before.stability_score.toFixed(1) : "—"} />
              <Metric label="Score после" value={varianceProfile?.profile.diagnostics_after ? varianceProfile.profile.diagnostics_after.stability_score.toFixed(1) : "—"} />
            </div>
          ) : activeCheckId === "smoothing" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Метод" value={smoothingProfile?.profile.selected_method?.toUpperCase() ?? "—"} />
              <Metric label="Roughness до" value={smoothingProfile?.profile.diagnostics_before?.normalized_roughness !== null && smoothingProfile?.profile.diagnostics_before?.normalized_roughness !== undefined ? smoothingProfile.profile.diagnostics_before.normalized_roughness.toFixed(3) : "—"} />
              <Metric label="High-freq до" value={smoothingProfile?.profile.diagnostics_before?.high_frequency_power_share !== null && smoothingProfile?.profile.diagnostics_before?.high_frequency_power_share !== undefined ? `${(100 * smoothingProfile.profile.diagnostics_before.high_frequency_power_share).toFixed(1)}%` : "—"} />
              <Metric label="High-freq после" value={smoothingProfile?.profile.diagnostics_after?.high_frequency_power_share !== null && smoothingProfile?.profile.diagnostics_after?.high_frequency_power_share !== undefined ? `${(100 * smoothingProfile.profile.diagnostics_after.high_frequency_power_share).toFixed(1)}%` : "—"} />
            </div>
          ) : activeCheckId === "stationarity" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Консенсус до" value={stationarityProfile?.profile?.consensus_before ?? "—"} />
              <Metric label="Метод" value={stationarityProfile?.profile?.selected_method?.replace(/_/g, " ") ?? "—"} />
              <Metric label="Консенсус после" value={stationarityProfile?.profile?.consensus_after ?? "—"} />
              <Metric label="Потеря N" value={stationarityProfile?.profile ? String(stationarityProfile.profile.lost_observations) : "—"} />
            </div>
          ) : activeCheckId === "spectral" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Дом. период" value={spectralProfile?.profile?.dominant_period !== null && spectralProfile?.profile?.dominant_period !== undefined ? spectralProfile.profile.dominant_period.toFixed(2) : "—"} />
              <Metric label="Подтверждено" value={spectralProfile?.profile ? String(spectralProfile.profile.confirmed_periods) : "—"} />
              <Metric label="Entropy" value={spectralProfile?.profile?.spectral_entropy !== null && spectralProfile?.profile?.spectral_entropy !== undefined ? spectralProfile.profile.spectral_entropy.toFixed(3) : "—"} />
              <Metric label="Welch сегментов" value={spectralProfile?.profile ? String(spectralProfile.profile.welch_segments) : "—"} />
            </div>
          ) : activeCheckId === "feature_eng" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Признаков" value={featureGenerationProfile?.profile ? String(featureGenerationProfile.profile.preview_feature_count) : "—"} />
              <Metric label="Lookback" value={featureGenerationProfile?.profile ? String(featureGenerationProfile.profile.max_lookback) : "—"} />
              <Metric label="Лаги" value={featureGenerationProfile?.profile?.suggested_lags.join(", ") || "—"} />
              <Metric label="Сохранено" value={featureGenerationProfile?.profile ? String(featureGenerationProfile.profile.saved_feature_names.length) : "—"} />
            </div>
          ) : activeCheckId === "scaling" ? (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Числовых" value={scalingProfile?.profile ? String(scalingProfile.profile.numeric_count) : "—"} />
              <Metric label="В Auto X" value={scalingProfile?.profile ? String(scalingProfile.profile.suggested_columns.length) : "—"} />
              <Metric label="Разброс σ" value={scalingProfile?.profile ? `×${scalingProfile.profile.scale_ratio.toFixed(1)}` : "—"} />
              <Metric label="Рецепт" value={scalingProfile?.profile?.saved_recipe?.method ?? "—"} />
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-3 mt-4">
              <Metric label="Строк" value="200" />
              <Metric label="Пропусков" value="11" />
              <Metric label="Выбросов" value="1145" />
              <Metric label="ADF p" value="0.03" />
              <Metric label="Частота" value="D" />
            </div>
          )}
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: панель управления + список проверок ── */}
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
                <StatusIcon status={check.status} /> Преобразование: {check.label}
              </h3>

              <p className="text-sm text-neutral-600 mb-2">{check.description}</p>

              {/* Режим проверки — только для остановок с реальным API. */}
              {(check.id === "missing" || check.id === "outliers" || check.id === "regularity" || check.id === "decomposition" || check.id === "variance_stab" || check.id === "smoothing" || check.id === "stationarity" || check.id === "spectral" || check.id === "feature_eng" || check.id === "scaling") && (
                <label className="mb-2 block text-[11px] font-medium text-neutral-600">
                  Режим проверки
                  <select
                    aria-label={`Режим проверки ${check.label}`}
                    value={checkModes[check.id] ?? "auto"}
                    disabled={modeSaving !== null}
                    onChange={(event) => void handleCheckModeChange(check.id, event.target.value as PreprocessingCheckMode)}
                    className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm font-normal text-neutral-800 focus:outline-none focus:ring-1 focus:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <option value="auto">Авто</option>
                    <option value="enabled">Включена</option>
                    <option value="disabled">Отключена</option>
                  </select>
                </label>
              )}
              {modeSaving === check.id && (
                <p role="status" className="mb-2 text-[11px] text-brand">Сохранение режима…</p>
              )}
              {modeError?.checkId === check.id && (
                <p role="alert" className="mb-2 text-[11px] text-red-700">{modeError.message}</p>
              )}

              {/* Бейдж результата -- для «Пропусков»/«Выбросов» все
                  состояния явно различимы; для остальных (ещё не
                  подключённых) остановок -- прежняя упрощённая логика
                  по count/status. */}
              {check.id === "missing" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка выполняется…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {missingError ?? "Ошибка выполнения проверки"}
                    </p>
                  )}
                  {check.status === "pending" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка не запускалась
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {missingNoDataset
                        ? "Нет активного датасета"
                        : missingProfile?.status_reason === "disabled"
                        ? "Отключено"
                        : "Не требуется"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      Найдено {check.count ?? 0} пропусков
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Проверка пройдена, пропусков нет
                    </p>
                  )}
                </>
              ) : check.id === "outliers" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка выполняется…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {outliersError ?? "Ошибка выполнения проверки"}
                    </p>
                  )}
                  {check.status === "pending" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка не запускалась
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {outliersNoDataset
                        ? "Нет активного датасета"
                        : outliersProfile?.status_reason === "disabled"
                        ? "Отключено"
                        : "Не требуется"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      Найдено {check.count ?? 0} выбросов
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Проверка пройдена, выбросов нет
                    </p>
                  )}
                </>
              ) : check.id === "regularity" ? (
                <>
                  {check.status === "running" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка выполняется…
                    </p>
                  )}
                  {check.status === "error" && (
                    <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                      {regularityError ?? "Ошибка выполнения проверки"}
                    </p>
                  )}
                  {check.status === "pending" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      Проверка не запускалась
                    </p>
                  )}
                  {check.status === "skipped" && (
                    <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                      {regularityNoDataset
                        ? "Нет активного датасета"
                        : regularityProfile?.status_reason === "disabled"
                        ? "Отключено"
                        : "Не требуется"}
                    </p>
                  )}
                  {check.status === "warning" && (
                    <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                      Найдено {check.count ?? 0} нарушений регулярности
                    </p>
                  )}
                  {check.status === "done" && (
                    <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                      Проверка пройдена, нарушений нет
                    </p>
                  )}
                </>
              ) : check.id === "decomposition" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Выполняется STL-декомпозиция…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{decompositionError ?? "Ошибка выполнения декомпозиции"}</p>}
                  {check.status === "pending" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Проверка не запускалась</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{decompositionNoDataset ? "Нет активного датасета" : decompositionProfile?.status_reason === "disabled" ? "Отключено" : decompositionProfile?.profile.reason ?? "Не применимо"}</p>}
                  {check.status === "warning" && <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">STL выполнен; остаток требует внимания ({check.count ?? 0})</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">STL выполнен, остаточная диагностика пройдена</p>}
                </>
              ) : check.id === "variance_stab" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Оценивается стабильность дисперсии…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{varianceError ?? "Ошибка диагностики дисперсии"}</p>}
                  {check.status === "pending" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Проверка не запускалась</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{varianceNoDataset ? "Нет активного датасета" : varianceProfile?.status_reason === "disabled" ? "Отключено" : varianceProfile?.profile.reason ?? "Не применимо"}</p>}
                  {check.status === "warning" && <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">Обнаружена нестабильность масштаба; сравните трансформации</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">Сильных признаков нестабильной дисперсии нет</p>}
                </>
              ) : check.id === "smoothing" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Оценивается высокочастотная составляющая…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{smoothingError ?? "Ошибка диагностики сглаживания"}</p>}
                  {check.status === "pending" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Проверка не запускалась</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{smoothingNoDataset ? "Нет активного датасета" : smoothingProfile?.status_reason === "disabled" ? "Отключено" : smoothingProfile?.profile.reason ?? "Не применимо"}</p>}
                  {check.status === "warning" && <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">Высокочастотная составляющая выражена; сравните фильтры</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">Сильного сигнала для обязательного сглаживания нет</p>}
                </>
              ) : check.id === "stationarity" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Выполняются ADF/KPSS и сравнение преобразований…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{stationarityError ?? "Ошибка диагностики стационарности"}</p>}
                  {check.status === "pending" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Проверка не запускалась</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{stationarityNoDataset ? "Нет активного датасета" : stationarityProfile?.status_reason === "disabled" ? "Отключено" : stationarityProfile?.profile?.reason ?? "Не применимо"}</p>}
                  {check.status === "warning" && <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">{stationarityProfile?.profile?.consensus_before === "trend-stationary" ? "Ряд тренд-стационарен; сравните detrend с явным трендом модели" : stationarityProfile?.profile?.consensus_before === "inconclusive" ? "ADF/KPSS расходятся; требуется аналитическое решение" : "Обнаружены признаки единичного корня; сравните минимальные разности"}</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">Ряд стационарен вокруг уровня; преобразование не требуется</p>}
                </>
              ) : check.id === "spectral" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Выполняются FFT, Welch и CWT…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{spectralError ?? "Ошибка спектрального анализа"}</p>}
                  {check.status === "pending" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Анализ не запускался</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{spectralNoDataset ? "Нет активного датасета" : spectralProfile?.status_reason === "disabled" ? "Отключено" : spectralProfile?.profile?.reason ?? "Не применимо"}</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">{spectralProfile?.profile?.confirmed_periods ? `Подтверждено периодов: ${spectralProfile.profile.confirmed_periods}` : "Устойчивые периоды не подтверждены"}</p>}
                </>
              ) : check.id === "feature_eng" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Строится безопасный preview матрицы X…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{featureGenerationError ?? "Ошибка генерации признаков"}</p>}
                  {check.status === "pending" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Набор признаков не проверялся</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{featureGenerationNoDataset ? "Нет активного датасета" : featureGenerationProfile?.status_reason === "disabled" ? "Отключено" : featureGenerationProfile?.profile?.reason ?? "Не применимо"}</p>}
                  {check.status === "warning" && <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">Набор рекомендован, но ещё не применён</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">Сгенерировано признаков: {featureGenerationProfile?.profile?.saved_feature_names.length ?? 0}</p>}
                </>
              ) : check.id === "scaling" ? (
                <>
                  {check.status === "running" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Сравниваются масштабы и scaler-рецепты…</p>}
                  {check.status === "error" && <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">{scalingError ?? "Ошибка профиля масштабирования"}</p>}
                  {check.status === "pending" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">Профиль масштабирования не проверялся</p>}
                  {check.status === "skipped" && <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">{scalingNoDataset ? "Нет активного датасета" : scalingProfile?.status_reason === "disabled" ? "Отключено" : scalingProfile?.profile?.reason ?? "Не применимо"}</p>}
                  {check.status === "warning" && <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">Рецепт масштабирования ещё не сохранён</p>}
                  {check.status === "done" && <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">Fold-safe рецепт сохранён: {scalingProfile?.profile?.saved_recipe?.columns.length ?? 0} колонок</p>}
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
                      Проверка пройдена, нарушений нет
                    </p>
                  )}
                </>
              )}

              {/* Кнопка «Метрики и алгоритм» -- активирует контент в центральном поле */}
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

              {/* Для реализованных остановок открывается специализированный мастер. */}
              <button
                onClick={() => handleDescriptionClick(check, "pipeline")}
                className={`w-full mb-3 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "pipeline"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                {check.id === "missing" ? "Исправить пропуски" : check.id === "outliers" ? "Исправить выбросы" : check.id === "regularity" ? "Исправить регулярность" : check.id === "decomposition" ? "Настроить декомпозицию" : check.id === "variance_stab" ? "Настроить трансформацию" : check.id === "smoothing" ? "Настроить сглаживание" : check.id === "stationarity" ? "Обеспечить стационарность" : check.id === "spectral" ? "Зафиксировать периоды" : check.id === "feature_eng" ? "Сгенерировать признаки" : check.id === "scaling" ? "Настроить масштабирование" : "Полный пайплайн"}
              </button>

              {/* PROGR-9: кнопка пересчёта — только у остановок с реальным
                  обработчиком (ручной fallback: чужая мутация датасета мимо
                  открытой вкладки — общая cookie-сессия, ретрай после сбоя
                  GET). У остальных шести остановок onClick был undefined —
                  «мёртвые» кнопки (pre-existing) введены пользователя в
                  заблуждение и удалены: автопересчёт после изменений
                  аналитика (apply мастера, смена режима/признака/параметров)
                  покрывает ВСЕ остановки единообразно через datasetVersion
                  в deps эффектов, поэтому кнопка без обработчика не нужна. */}
              {(check.id === "stationarity" || check.id === "spectral" || check.id === "feature_eng" || check.id === "scaling") && (
                <Button onClick={check.id === "stationarity" ? () => setStationarityRefreshKey((key) => key + 1) : check.id === "spectral" ? () => setSpectralRefreshKey((key) => key + 1) : check.id === "feature_eng" ? () => setFeatureGenerationRefreshKey((key) => key + 1) : check.id === "scaling" ? () => setScalingRefreshKey((key) => key + 1) : undefined}>{check.id === "spectral" ? "Пересчитать спектральный профиль" : check.id === "feature_eng" ? "Пересчитать профиль признаков" : check.id === "scaling" ? "Пересчитать профиль масштабов" : `Пересчитать свойства после преобразования (${check.label.toLowerCase()})`}</Button>
              )}
            </article>
          ))}
        </div>
        </aside>
      </div>
      <DatasetPassportPanel
        stage="exit"
        targetColumn={activeFeature}
        historyResetNotice={passportResetNotice
          ? `Смена исследуемого признака «${passportResetNotice.previousColumn}» → «${passportResetNotice.newColumn}» сбросила цепочку паспортов.`
          : null}
      />
    </div>
  );
}
