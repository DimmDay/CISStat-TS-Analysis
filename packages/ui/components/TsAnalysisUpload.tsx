"use client";

// packages/ui/components/TsAnalysisUpload.tsx
//
// ОБЩИЙ компонент фичи "Загрузка" -- используется И embedded-,
// И standalone-приложением. Компоновка ПЕРЕВЕДЕНА на общий 3-колоночный
// паттерн платформы (тот же, что в TsAnalysisPreprocessing/Validation/
// EDA.tsx), по решению тимлида -- метафора "маршрут / руль-педали /
// лобовое стекло":
//
//   [Левая ~240px]        [Центр flex-1]              [Правая ~320px]
//   Загрузка              Описание                    Обзор / Управление
//   Признак: ▾price       [текстовое поле]             (меняется по
//   2/4 ██░░               Обзор: {label}                активной
//   ┌─Обзор──────✓─┐      [таблица/график/карточки]      остановке)
//   ├─Распределение✓┤      [Metric-карточки]
//   ├─Структура───⚠┤
//   └─Качество────⚠┘
//
// Верхняя полоса "Источник данных" (dropzone) -- ВНЕ 3-колоночного
// блока, на всю ширину: она не принадлежит ни одной "остановке", нужна
// всегда (пере-загрузка файла возможна с любой активной остановки).
//
// Контракт вкладки «Загрузка» (по решению тимлида) -- 8 пунктов,
// распределены по 4 "остановкам" степпера:
//   Обзор:         1. Превью датасета
//                  2. Техническая информация (строки/колонки/память/типы)
//                  7. Флаг проблем парсинга (кодировка/заголовок) -- РЕАЛЬНЫЙ,
//                     apps/api/upload_common.py::_compute_parse_warnings
//   Распределение: 3. Визуализация распределения (точечный/гистограмма/KDE) --
//                     РЕАЛЬНАЯ (Recharts + GET /dataset/distribution),
//                     см. пометку 🟢 ниже
//                  4. Описательные статистики -- РЕАЛЬНЫЕ (не моки),
//                     apps/api/routers/session.py::get_dataset_stats
//                     (mean/median/std/skew/kurtosis/Q1/Q3/IQR по scipy/pandas
//                     над полным столбцом, не превью)
//   Структура:     5. Подтверждение автоопределения (дата/группировка/частота)
//                  8. Структурный класс данных -- клиентская эвристика,
//                     packages/ui/lib/structuralClass.ts (описание -- см. её
//                     докстринг: сама авто-маршрутизация -- future work,
//                     здесь только сигнал)
//   Качество:      6. Teaser качества (только счётчики → Валидация)
//
// 🟢 Визуализация распределения -- РЕАЛЬНЫЕ графики (Recharts), первая
//    точка подключения на платформе (2026-08-14, по решению тимлида).
//    Данные -- GET /v1/session/dataset/distribution, см.
//    apps/api/chart_data.py (LTTB-сэмплинг scatter выше ~3000 точек,
//    гистограмма/KDE всегда по полному столбцу). Компоненты --
//    packages/ui/components/DistributionCharts.tsx, переиспользуемые.
//    Остальные модули (Preprocessing/Validation/EDA) пока НЕ подключены --
//    ждём одобрения визуального представления стейкхолдерами, затем
//    масштабируем по той же схеме (см. договорённость с тимлидом).
// 🟡 Подтверждение автоопределения -- клиентская эвристика по
//    columns_info (см. buildDetectionFromColumns ниже), не настоящий
//    бэкенд-детектор (см. TODO там же).

import { useCallback, useEffect, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import Link from "next/link";
import {
  Upload,
  FileText,
  Calendar,
  Tag,
  Clock,
  ChevronDown,
  Database,
  Eye,
  BarChart3,
  ScatterChart,
  Activity,
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  Loader2,
  Route,
} from "lucide-react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import {
  DistributionChartData,
  HistogramDistributionChart,
  KdeDistributionChart,
  SamplingBadge,
  ScatterDistributionChart,
} from "./DistributionCharts";
import { TimeSeriesLineChart, type TimeSeriesChartData } from "./TimeSeriesLineChart";
import { DecompositionBadges, type DecompositionData } from "./DecompositionBadges";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { StructuralClassSchema } from "./StructuralClassSchema";
import { useAppShell } from "../context/AppShellContext";
import { apiUrl, sessionApiUrl } from "../lib/apiClient";
import { classifyStructure, type PanelBalance, type StructuralClassResult } from "../lib/structuralClass";
import { useTargetColumn } from "../hooks/useTargetColumn";

// ──────────────────────────────────────────────────────────────────────
// ТИПЫ (зеркало apps/api/schemas.py -- поля намеренно snake_case, как
// отдаёт API, без промежуточного camelCase-слоя)
// ──────────────────────────────────────────────────────────────────────

interface ColumnInfoOut {
  name: string;
  dtype: string;
  type_icon: "numeric" | "datetime" | "categorical" | "text";
  non_null: number;
  nulls: number;
  unique: number;
}

interface QualityTeaserOut {
  cols_with_missing: number;
  cols_with_outliers: number;
  rows_total: number;
  duplicates: number;
  missing_cols: string[];
  outlier_cols: string[];
}

interface UploadApiResponse {
  dataset_id: string;
  name: string;
  rows: number;
  columns: number;
  preview: { head: string[][]; tail: string[][] };
  columns_info: ColumnInfoOut[] | null;
  quality: QualityTeaserOut | null;
  size_label: string | null;
  parse_warnings: string[];
  error?: string | null;
  detail?: string | { loc: (string | number)[]; msg: string; type: string }[]; // FastAPI: строка (HTTPException) ИЛИ массив (422 validation error)
  frequency?: string;
  domain?: string;
  n_series?: number;
  has_seasonality?: boolean;
  is_regular?: boolean;
}

interface ColumnStatsValues {
  mean: number;
  median: number;
  std: number;
  skewness: number | null; // NaN на бэкенде сериализуется в null (слишком мало точек)
  kurtosis: number | null;
  q1: number;
  q3: number;
  iqr: number;
  distribution_hint: string;
}

interface ColumnStatsOut {
  name: string;
  non_null_count: number;
  stats: ColumnStatsValues | null; // null -- недостаточно значений, см. non_null_count
}

interface DetectionCandidate {
  name: string;
  score: number;
}

interface StructureDetection {
  dateCol: { selected: string; confidence: number; candidates: DetectionCandidate[] };
  entityCol: { selected: string; confidence: number; candidates: DetectionCandidate[] };
  freq: { selected: string; confidence: number; options: string[] };
}

type StopId = "overview" | "chart" | "distribution" | "structure" | "quality";

interface Stop {
  id: StopId;
  label: string;
  description: string;
}

const STOPS: Stop[] = [
  {
    id: "overview",
    label: "Превью датасета",
    description:
      "Проверка, что файл прочитан правильно: предпросмотр строк, типы колонок, объём. Если при чтении что-то пошло не так технически (кодировка, сдвинутый заголовок) — флаг появится здесь же.",
  },
  {
    id: "chart",
    label: "График",
    description:
      "Линейный график исследуемого признака по реальной временной оси — первый визуальный взгляд на форму ряда до статистики. Ниже — бейджи декомпозиции (Тренд/Сезонность/Цикличность/Остаток) как индикатор уровня шума в данных на старте анализа.",
  },
  {
    id: "distribution",
    label: "Распределение",
    description:
      "Форма распределения выбранного числового признака: точечный график, гистограмма, KDE и описательные статистики (mean/median/std/skew/kurtosis/Q1/Q3/IQR) — ориентир для выбора семейства моделей позже.",
  },
  {
    id: "structure",
    label: "Структура",
    description:
      "Подтверждение автоопределения даты, группирующей колонки и частоты ряда, и итоговый структурный класс данных — от него зависит, какие проверки и модели будут актуальны дальше по пайплайну.",
  },
  {
    id: "quality",
    label: "Качество",
    description:
      "Только счётчики проблем (пропуски/выбросы/дубликаты) — анонс перехода к «Валидации», не содержательный анализ. Полный разбор — в следующем модуле.",
  },
];

const FREQ_OPTIONS = [
  "H — почасовая",
  "D — ежедневная",
  "W — недельная",
  "M — месячная",
  "Q — квартальная",
  "Y — годовая",
  "(авто, не получилось)",
];

// ──────────────────────────────────────────────────────────────────────
// ВСПОМОГАТЕЛЬНЫЕ
// ──────────────────────────────────────────────────────────────────────

function confidenceColor(pct: number): string {
  if (pct >= 85) return "bg-green-100 text-green-700";
  if (pct >= 70) return "bg-amber-100 text-amber-700";
  return "bg-red-100 text-red-700";
}

function formatNum(n: number): string {
  return n.toLocaleString("ru-RU").replace(/,/g, " ");
}

function fmtStat(n: number | null): string {
  if (n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

/**
 * FastAPI отдаёт ошибки в ДВУХ разных формах: {"detail": "строка"} для
 * ручных HTTPException, {"detail": [{"loc":..,"msg":..,"type":..}, ...]}
 * для автоматической 422-валидации запроса (например, не пришёл
 * обязательный заголовок). Раньше `new Error(data.detail)` на втором
 * случае превращался в "[object Object]" -- Error coerces non-string
 * аргумент через String(), а String() массива объектов даёт именно это.
 */
function extractErrorMessage(data: UploadApiResponse): string | null {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    return data.detail.map((e) => e.msg).join("; ");
  }
  if (data.error) return data.error;
  return null;
}

/**
 * Клиентская ЭВРИСТИКА подтверждения структуры -- см. TODO в шапке файла.
 */
/**
 * БАГ (найден пользователем 2026-08-14 на реальном датасете
 * TEST_dataset_FAO: Country/Year/Price): buildDetectionFromColumns
 * (клиентская ЭВРИСТИКА) при отсутствии pandas-datetime-типизированной
 * колонки (что для "голых" числовых лет вроде Year НИКОГДА не так)
 * откатывалась на ПЕРВЫЕ 3 КОЛОНКИ ФАЙЛА с искусственно убывающим score
 * (0.9/0.7/0.5) -- отсюда абсурдные кандидаты Country/Price.
 *
 * Заменено на fetchStructureDetection ниже -- реальный контентный
 * скоринг с бэкенда (GET /dataset/structure-detection, см.
 * app/data/detectors.py::score_all_columns_as_date). Функция оставлена
 * НЕиспользуемой в файле намеренно закомментированной -- как
 * исторический референс бага, легко удалить позже.
 */
// function buildDetectionFromColumns(columnsInfo: ColumnInfoOut[]): StructureDetection { ... } -- УДАЛЕНО, см. fetchStructureDetection

/** Топ-кандидаты с ненулевым score; если ВСЕ нулевые (нет ни одного
 * правдоподобного кандидата) -- всё равно показываем несколько первых
 * для ручного override в селекторе, но НЕ подделываем их score. */
function topCandidates(candidates: DetectionCandidate[], max = 8): DetectionCandidate[] {
  const nonZero = candidates.filter((c) => c.score > 0);
  return (nonZero.length > 0 ? nonZero : candidates).slice(0, max);
}

async function fetchStructureDetection(): Promise<StructureDetection | null> {
  try {
    const res = await fetch(sessionApiUrl("/dataset/structure-detection"), { credentials: "include" });
    if (!res.ok) return null;
    const data = await res.json();
    const dateCandidates = topCandidates(data.date_col.candidates);
    const entityCandidates = topCandidates(data.entity_col.candidates);
    return {
      dateCol: {
        selected: data.date_col.selected,
        confidence: data.date_col.confidence,
        candidates: dateCandidates,
      },
      entityCol: {
        selected: data.entity_col.selected,
        confidence: data.entity_col.confidence,
        candidates: entityCandidates,
      },
      // Частота (2026-08-14): РЕАЛЬНОЕ значение с бэкенда
      // (app/data/detectors.py::detect_column_frequency, pd.infer_freq
      // на уникальных отсортированных датах). Раньше здесь была
      // захардкоженная заглушка "D — ежедневная" при confidence>0 --
      // пользователь поймал баг: годовой FAO-датасет показывал
      // "ежедневная". data.frequency===null, если date_col не
      // определена уверенно (нет уверенной даты -- нечего анализировать).
      freq: {
        selected: data.frequency?.selected ?? "(авто, не получилось)",
        confidence: data.frequency?.confidence ?? 0,
        // Реальная формулировка с бэкенда (detect_column_frequency)
        // может отличаться от статического списка FREQ_OPTIONS
        // (например, "Y — годовая (начало года)" vs "Y — годовая",
        // или неучтённый код вроде "H — почасовая") -- гарантируем,
        // что <select> всегда может отобразить РЕАЛЬНОЕ значение, а
        // не молча показать первую опцию списка из-за несовпадения
        // (ровно так проявлялся баг с частотой -- см. регресс-тест).
        options: data.frequency?.selected && !FREQ_OPTIONS.includes(data.frequency.selected)
          ? [data.frequency.selected, ...FREQ_OPTIONS]
          : FREQ_OPTIONS,
      },
    };
  } catch {
    return null;
  }
}

// ──────────────────────────────────────────────────────────────────────
// ГЛАВНЫЙ КОМПОНЕНТ
// ──────────────────────────────────────────────────────────────────────

export function TsAnalysisUpload() {
  const { activeDataset, setActiveDataset, refreshSession, addLogEntry } = useAppShell();

  // ── Источник данных (верхняя полоса, вне степпера) ──
  const [source, setSource] = useState<"file" | "db">("file");
  const [fileName, setFileName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadData, setUploadData] = useState<UploadApiResponse | null>(null);
  const [hydrating, setHydrating] = useState(false);

  // ── Степпер / 3-колоночный блок ──
  const [activeStop, setActiveStop] = useState<StopId>("overview");
  const [detection, setDetection] = useState<StructureDetection | null>(null);
  const [stats, setStats] = useState<ColumnStatsOut[] | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [distribution, setDistribution] = useState<DistributionChartData | null>(null);
  const [distributionLoading, setDistributionLoading] = useState(false);
  // ── Остановка «График» (2026-08-14): линейный график + декомпозиция ──
  const [timeseries, setTimeseries] = useState<TimeSeriesChartData | null>(null);
  const [timeseriesLoading, setTimeseriesLoading] = useState(false);
  const [decomposition, setDecomposition] = useState<DecompositionData | null>(null);
  const [decompositionLoading, setDecompositionLoading] = useState(false);
  const [decompositionRequested, setDecompositionRequested] = useState(false);
  const [overviewTab, setOverviewTab] = useState<"preview" | "columns">("preview");

  // ── Единый "исследуемый признак" (target_column) для всей платформы
  // (2026-08-14) -- заменяет прежний локальный useState<string|null>,
  // который сбрасывался при каждом уходе с вкладки и откатывался к
  // numericCols[0] (первой числовой колонке ПО ПОРЯДКУ В ДАТАФРЕЙМЕ --
  // для Country/Year/Price это был Year, не Price). См. packages/ui/hooks/useTargetColumn.ts.
  const {
    targetColumn: selectedFeature,
    wasAutoSelected,
    columnResetNotice,
    dismissColumnResetNotice,
    setColumn: setSelectedFeature,
    refetch: refetchTargetColumn,
  } = useTargetColumn(activeDataset?.name);

  const isUploaded = uploadData !== null;

  // ── Уведомление о смене признака при загрузке нового датасета ──
  // (2026-08-14, согласовано с тимлидом: "и то, и другое" -- toast И
  // инлайн-бейдж). columnResetNotice приходит из useTargetColumn, когда
  // РАНЕЕ выбранная колонка (например Price) отсутствует в новом
  // датасете -- backend сам сбрасывает target_column при set_dataset().
  useEffect(() => {
    if (columnResetNotice) {
      toast.warning(
        `Признак «${columnResetNotice.previousColumn}» недоступен в новом датасете — выбран «${columnResetNotice.newColumn}»`
      );
      dismissColumnResetNotice();
    }
  }, [columnResetNotice, dismissColumnResetNotice]);
  const columnsInfo = uploadData?.columns_info ?? [];
  const numericCols = columnsInfo.filter((c) => c.type_icon === "numeric").map((c) => c.name);

  // ── Загрузка описательной статистики (реальный эндпоинт) ──
  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const resp = await fetch(sessionApiUrl("/dataset/stats"), { credentials: "include" });
      if (resp.ok) {
        const data = await resp.json();
        setStats(data.columns ?? []);
      }
    } catch {
      // Обзор/Структура/Качество не зависят от статистики -- не блокируем страницу
    } finally {
      setStatsLoading(false);
    }
  }, []);

  // ── Загрузка данных для графиков распределения (эндпоинт per-column,
  // не часть общего /dataset/stats -- считать scatter/histogram/KDE для
  // ВСЕХ числовых колонок сразу было бы избыточно, запрашиваем только
  // выбранный признак). apps/api/routers/session.py::get_dataset_distribution ──
  useEffect(() => {
    if (!selectedFeature || !isUploaded) {
      setDistribution(null);
      return;
    }
    let cancelled = false;
    setDistributionLoading(true);
    fetch(sessionApiUrl(`/dataset/distribution?column=${encodeURIComponent(selectedFeature)}`), {
      credentials: "include",
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: DistributionChartData | null) => {
        // Защита от гонки: пока запрос летел, пользователь мог уже
        // переключить признак -- не затираем более свежий выбор устаревшим ответом.
        if (!cancelled) setDistribution(data);
      })
      .catch(() => {
        if (!cancelled) setDistribution(null);
      })
      .finally(() => {
        if (!cancelled) setDistributionLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFeature, isUploaded]);

  // Уверенно определённая date-колонка (порог 70 -- тот же, что уже
  // используется для статуса остановки «Структура», см. stopStatus ниже)
  // -- без неё линейный график и декомпозиция технически бессмысленны
  // (дата "(не использовать)"/угаданная с confidence=25 дала бы кривую
  // ось X или неверный частотный гейт декомпозиции).
  // БАГ (найдено 2026-08-14, сообщено пользователем): confidence -- это
  // статическая оценка АВТО-детекта, которая НЕ пересчитывается при
  // ручном выборе колонки в селекторе на «Структуре» (onChange меняет
  // только dateCol.selected, не confidence) -- поэтому гейт "confidence
  // >= 70" продолжал блокировать «График» даже ПОСЛЕ того, как
  // пользователь явно выбрал Year. Правильный гейт: доверяем любому
  // осознанному выбору (не placeholder), confidence -- только для
  // решения, нужно ли ПРЕДУПРЕДИТЬ о низкой уверенности АВТО-детекта,
  // а не для блокировки функциональности после ручной коррекции.
  const confidentDateCol =
    detection && detection.dateCol.selected !== "(не использовать)" ? detection.dateCol.selected : null;

  // ── Линейный график (остановка «График», авто при заходе -- в отличие
  // от декомпозиции ниже, LTTB-сэмплинг быстрый, не требует STL) ──
  // apps/api/routers/session.py::get_dataset_timeseries
  useEffect(() => {
    if (!selectedFeature || !confidentDateCol || !isUploaded) {
      setTimeseries(null);
      return;
    }
    let cancelled = false;
    setTimeseriesLoading(true);
    fetch(
      sessionApiUrl(
        `/dataset/timeseries?column=${encodeURIComponent(selectedFeature)}&date_column=${encodeURIComponent(confidentDateCol)}`
      ),
      { credentials: "include" }
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((data: TimeSeriesChartData | null) => {
        if (!cancelled) setTimeseries(data);
      })
      .catch(() => {
        if (!cancelled) setTimeseries(null);
      })
      .finally(() => {
        if (!cancelled) setTimeseriesLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFeature, confidentDateCol, isUploaded]);

  // Сбрасываем декомпозицию при смене признака -- старый результат для
  // другой колонки не должен "залипать" под новым выбором (пользователь
  // должен нажать кнопку заново -- по решению тимлида, ленивый расчёт).
  useEffect(() => {
    setDecomposition(null);
    setDecompositionRequested(false);
  }, [selectedFeature, confidentDateCol]);

  // ── Декомпозиция (остановка «График», ПО КНОПКЕ -- STL на statsmodels
  // не мгновенная, см. согласование с тимлидом 2026-08-14) ──
  // apps/api/routers/session.py::get_dataset_decomposition
  const fetchDecomposition = useCallback(() => {
    if (!selectedFeature || !confidentDateCol) return;
    setDecompositionRequested(true);
    setDecompositionLoading(true);
    fetch(
      sessionApiUrl(
        `/dataset/decomposition?column=${encodeURIComponent(selectedFeature)}&date_column=${encodeURIComponent(confidentDateCol)}`
      ),
      { credentials: "include" }
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((data: DecompositionData | null) => setDecomposition(data))
      .catch(() => setDecomposition(null))
      .finally(() => setDecompositionLoading(false));
  }, [selectedFeature, confidentDateCol]);

  // Если в сессии уже есть активный датасет (пользователь пришёл сюда по
  // кнопке "Продолжить" с Home), подтягиваем превью/техинфо/качество +
  // статистику заново с бэкенда, не заставляя грузить файл повторно.
  useEffect(() => {
    if (!activeDataset || uploadData) return;
    let cancelled = false;
    setHydrating(true);
    fetch(sessionApiUrl("/dataset"), { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: UploadApiResponse | null) => {
        if (cancelled || !data) return;
        setUploadData(data);
        if (data.columns_info) {
          fetchStructureDetection().then((d) => setDetection(d));
          // Больше НЕ выбираем "первую числовую" вручную (это и было
          // причиной бага -- откатывалось на Year вместо Price). Сервер
          // уже сбросил target_column при этой загрузке (upload_common.py::set_dataset)
          // -- рефетчим, useTargetColumn сам применит suggested_column-эвристику и запишет её.
          refetchTargetColumn();
        }
        fetchStats();
      })
      .catch(() => {
        // Молча остаёмся в состоянии "нет данных для превью" -- у
        // пользователя всё равно есть activeDataset.name/rows на Home.
      })
      .finally(() => {
        if (!cancelled) setHydrating(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDataset]);

  const doUpload = useCallback(
    async (file: File) => {
      setUploading(true);
      setUploadError(null);
      try {
        const formData = new FormData();
        formData.append("file", file);
        const resp = await fetch(apiUrl("/upload"), {
          method: "POST",
          body: formData,
          credentials: "include", // несёт cookie сессии -- сервер обновит AnalysisSession
        });
        const data: UploadApiResponse = await resp.json();
        if (!resp.ok) {
          throw new Error(extractErrorMessage(data) || "Не удалось загрузить файл");
        }
        setUploadData(data);
        setActiveStop("overview");
        setOverviewTab("preview");
        if (data.columns_info) {
          fetchStructureDetection().then((d) => setDetection(d));
          refetchTargetColumn();
        }
        fetchStats();

        // Автозаполнение профиля для «Моделирования» -- поля из ответа API
        // имеют приоритет. Раньше был fallback на freqCode из клиентской
        // эвристики детекции (buildDetectionFromColumns) -- убран вместе
        // с самой эвристикой (2026-08-14, см. fetchStructureDetection):
        // детекция теперь асинхронная (реальный запрос к бэкенду), не
        // может быть готова синхронно в этой точке. Без data.frequency
        // с бэкенда поле просто остаётся неопределённым, а не подделывается.
        setActiveDataset({
          name: data.name,
          rows: data.rows,
          sizeLabel: data.size_label ?? "—",
          ...(data.frequency && { frequency: data.frequency }),
          ...(data.domain && { domain: data.domain }),
          ...(data.n_series != null && { nSeries: data.n_series }),
          ...(data.has_seasonality != null && { hasSeasonality: data.has_seasonality }),
          ...(data.is_regular != null && { isRegular: data.is_regular }),
        });

        await refreshSession();
        toast.success("Файл загружен успешно!");

        if (data.parse_warnings.length > 0) {
          toast.warning(`Технические предупреждения при чтении файла (${data.parse_warnings.length})`);
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : "Неизвестная ошибка загрузки";
        setUploadError(message);
        toast.error(`Ошибка: ${message}`);
        addLogEntry("ERROR", `Ошибка загрузки файла: ${message}`);
      } finally {
        setUploading(false);
      }
    },
    [setActiveDataset, refreshSession, addLogEntry, fetchStats]
  );

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      const file = acceptedFiles[0];
      if (!file) return;
      setFileName(file.name);
      doUpload(file);
    },
    [doUpload]
  );

  // react-dropzone проверяет dataTransfer.items/types в рантайме браузера,
  // не только files -- обычный fireEvent.drop в тестах это тоже требует
  // (см. TsAnalysisUpload.test.tsx::dropFiles).
  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    onDrop,
    multiple: false,
    // 4MB, не 50MB -- Vercel Serverless Function ограничивает тело запроса
    // 4.5MB, а с новым server-side rewrite-прокси (apps/standalone/
    // next.config.mjs, нужен для first-party cookie) запрос идёт именно
    // через эту функцию. Прежний лимит 50MB физически не мог пройти на
    // проде через прокси -- команда поймала это независимо, см. worklog.
    maxSize: 4 * 1024 * 1024,
    accept: {
      "text/csv": [".csv"],
      "application/vnd.ms-excel": [".xls"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/json": [".json"],
    },
  });

  const rejectedFiles = fileRejections.map(({ file, errors }) => ({
    file,
    errors: errors.map((e) => {
      if (e.code === "file-too-large") return "Файл слишком большой (макс. 4MB)";
      if (e.code === "file-invalid-type") return "Неподдерживаемый формат";
      return e.message;
    }),
  }));

  const handleReset = () => {
    setUploadData(null);
    setUploadError(null);
    setDetection(null);
    setStats(null);
    setFileName(null);
    setActiveStop("overview");
  };

  const handleApplyOverride = () => {
    // ЗАМЕНИТЬ: PATCH /v1/internal/datasets/{id}/column-mapping -- эндпоинт
    // ещё не реализован на бэкенде. Пока -- локальное подтверждение.
    if (detection) setDetection({ ...detection });
    addLogEntry("INFO", "Подтверждение структуры сохранено (пока только локально — см. TODO в коде)");
  };

  // ── Структурный класс (пункт 8) -- вычисляется из detection + columnsInfo ──
  const [panelBalance, setPanelBalance] = useState<PanelBalance>("unknown");
  const entityColInfoForClass = detection ? columnsInfo.find((c) => c.name === detection.entityCol.selected) : null;
  const isPanelCandidate =
    !!detection &&
    detection.dateCol.selected !== "(не использовать)" &&
    detection.entityCol.selected !== "(нет)" &&
    (entityColInfoForClass?.unique ?? 0) > 1;

  // Balanced/Unbalanced требует полных данных (сравнение множеств дат по
  // группам) -- реальный запрос к бэкенду, не клиентская эвристика, см.
  // apps/api/routers/session.py::get_panel_balance. Перезапрашивается при
  // смене выбранных колонок даты/группировки (override пользователя).
  useEffect(() => {
    if (!isPanelCandidate || !detection) {
      setPanelBalance("unknown");
      return;
    }
    let cancelled = false;
    setPanelBalance("unknown");
    const params = new URLSearchParams({ date_col: detection.dateCol.selected, entity_col: detection.entityCol.selected });
    fetch(sessionApiUrl(`/dataset/panel-balance?${params}`), { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { balanced: boolean } | null) => {
        if (cancelled || !data) return;
        setPanelBalance(data.balanced ? "balanced" : "unbalanced");
      })
      .catch(() => {
        // Молча остаёмся "unknown" -- карточка структурного класса покажет
        // "Panel Data" без уточнения баланса, ничего не ломается.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPanelCandidate, detection?.dateCol.selected, detection?.entityCol.selected]);

  const structuralClass: StructuralClassResult | null = useMemo(() => {
    if (!detection || columnsInfo.length === 0) return null;
    return classifyStructure({
      hasDateColumn: detection.dateCol.selected !== "(не использовать)",
      hasEntityColumn: detection.entityCol.selected !== "(нет)",
      entityUniqueCount: entityColInfoForClass?.unique ?? null,
      isRegularFrequency: detection.freq.selected !== "(авто, не получилось)",
      columnsInfo,
      panelBalance,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detection, columnsInfo, panelBalance]);

  // ── Статусы остановок степпера (реальные, не моки) ──
  const stopStatus: Record<StopId, CheckStatus> = {
    overview: !isUploaded ? "pending" : (uploadData?.parse_warnings.length ?? 0) > 0 ? "warning" : "done",
    chart: !isUploaded ? "pending" : !detection || detection.dateCol.confidence < 70 ? "warning" : "done",
    distribution: !isUploaded ? "pending" : numericCols.length === 0 ? "pending" : "done",
    structure: !detection ? "pending" : detection.dateCol.confidence < 70 || detection.entityCol.confidence < 70 ? "warning" : "done",
    quality:
      !uploadData?.quality
        ? "pending"
        : uploadData.quality.cols_with_missing > 0 || uploadData.quality.cols_with_outliers > 0 || uploadData.quality.duplicates > 0
        ? "warning"
        : "done",
  };
  const doneCount = STOPS.filter((s) => stopStatus[s.id] === "done").length;
  const progressPct = Math.round((doneCount / STOPS.length) * 100);
  const activeStopDef = STOPS.find((s) => s.id === activeStop)!;
  const selectedStats = stats?.find((s) => s.name === selectedFeature) ?? null;

  return (
    <div className="space-y-5">
      {/* ════════ Верхняя полоса: Источник данных (вне степпера) ════════ */}
      <section className="bg-white rounded-lg border border-neutral-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-neutral-900 inline-flex items-center gap-2">
            <Upload size={18} className="text-brand" aria-hidden="true" />
            Источник данных
          </h2>
          {isUploaded && (
            <button
              type="button"
              onClick={handleReset}
              className="text-xs text-neutral-500 hover:text-neutral-700 inline-flex items-center gap-1"
            >
              <RefreshCw size={12} aria-hidden="true" /> Сменить файл
            </button>
          )}
        </div>

        {!isUploaded ? (
          <>
            <div className="grid grid-cols-2 gap-4">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" checked={source === "file"} onChange={() => setSource("file")} className="accent-brand" />
                Файл .xlsx, .xls, .csv, .json
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" checked={source === "db"} onChange={() => setSource("db")} className="accent-brand" />
                База данных (SQL)
              </label>
            </div>

            {source === "file" ? (
              <div
                {...getRootProps()}
                className={`mt-4 border-2 border-dashed rounded-lg p-6 text-center transition-colors cursor-pointer ${
                  isDragActive ? "border-brand bg-brand-light" : "border-neutral-300 bg-neutral-50"
                }`}
              >
                <input {...getInputProps()} data-testid="dropzone-input" />
                <div className="text-sm text-neutral-600 inline-flex flex-col items-center gap-2">
                  {uploading || hydrating ? (
                    <>
                      <Loader2 size={24} className="text-brand animate-spin" aria-hidden="true" />
                      <span>{uploading ? "Загружаем и анализируем файл…" : "Восстанавливаем сессию…"}</span>
                    </>
                  ) : (
                    <>
                      <Upload size={24} className="text-neutral-400" aria-hidden="true" />
                      <span>{isDragActive ? "Отпустите файл здесь…" : "Перетащите файл сюда или нажмите для выбора"}</span>
                      <span className="text-xs text-neutral-500">Поддерживаемые форматы: .csv, .xlsx, .xls, .json (макс. 4MB)</span>
                      {fileName && (
                        <span className="text-green-600">
                          Выбран: <strong>{fileName}</strong>
                        </span>
                      )}
                    </>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-sm text-neutral-500 mb-4 mt-4 bg-neutral-50 rounded p-4">(форма подключения к БД — заглушка)</p>
            )}

            {rejectedFiles.length > 0 && (
              <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg">
                <h3 className="font-medium text-red-700 mb-1 text-sm">Ошибки:</h3>
                <ul className="list-disc list-inside text-sm text-red-600">
                  {rejectedFiles.map(({ file, errors }) => (
                    <li key={file.name}>
                      {file.name}: {errors.join(", ")}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {uploadError && (
              <div className="mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
                <AlertTriangle size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
                <span>{uploadError}</span>
              </div>
            )}
          </>
        ) : (
          <div className="mt-1 border border-neutral-200 rounded-lg p-4 text-sm bg-neutral-50">
            <div className="flex items-center gap-2 text-neutral-700 flex-wrap">
              <FileText size={16} className="text-brand" aria-hidden="true" />
              <strong className="text-neutral-900">{uploadData!.name}</strong>
              <span className="text-neutral-400">·</span>
              <span>{uploadData!.size_label ?? "—"}</span>
              <span className="text-neutral-400">·</span>
              <span>{formatNum(uploadData!.rows)} строк</span>
              <span className="text-neutral-400">·</span>
              <span>{uploadData!.columns} колонок</span>
            </div>
          </div>
        )}
      </section>

      {/* ════════ 3-колоночный блок (общий паттерн платформы) ════════ */}
      {/* detection теперь ЗАГРУЖАЕТСЯ АСИНХРОННО (GET /dataset/structure-detection,
          см. fetchStructureDetection выше, 2026-08-14) -- раньше была
          синхронная клиентская эвристика (buildDetectionFromColumns),
          поэтому detection был готов мгновенно и гейтить весь layout
          на detection было безопасно. Теперь так делать нельзя: весь
          layout (степпер, графики, метрики) не должен ждать сетевого
          запроса детекции -- только содержимое остановки «Структура»
          ждёт detection (см. loading-state внутри неё ниже). */}
      {isUploaded && (
        <div className="flex gap-6">
          {/* ── ЛЕВАЯ КОЛОНКА: заголовок + признак + прогресс + степпер ── */}
          <aside className="w-60 shrink-0 flex flex-col gap-3 pt-1">
            <div className="mb-1">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-neutral-800 truncate min-w-0">Загрузка</h2>
              </div>
              <p className="text-[11px] text-neutral-500 mt-0.5">Проверка и структура датасета</p>
            </div>

            {numericCols.length > 0 && (
              <div>
                <label className="text-[11px] text-neutral-500 block mb-1">Исследуемый признак:</label>
                <select
                  value={selectedFeature ?? numericCols[0]}
                  onChange={(e) => setSelectedFeature(e.target.value)}
                  className="w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
                >
                  {numericCols.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
                {wasAutoSelected && selectedFeature && (
                  <p className="text-[10px] text-neutral-400 mt-1" data-testid="auto-selected-hint">
                    Выбрано автоматически — можно изменить
                  </p>
                )}
              </div>
            )}

            <div className="flex items-center gap-2">
              <p className="text-[11px] text-neutral-500 tabular-nums">
                {doneCount}/{STOPS.length}
              </p>
              <div className="flex-1 bg-neutral-200 rounded-full h-1.5">
                <div className="bg-brand h-1.5 rounded-full transition-all" style={{ width: `${progressPct}%` }} />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              {STOPS.map((stop) => (
                <button
                  key={stop.id}
                  onClick={() => setActiveStop(stop.id)}
                  className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition-colors ${
                    stop.id === activeStop ? "bg-brand text-white border-brand" : "bg-white border-neutral-200 hover:bg-neutral-50 text-neutral-800"
                  }`}
                >
                  <span className="truncate">{stop.label}</span>
                  <span className="ml-2 shrink-0">
                    <StatusIcon status={stopStatus[stop.id]} />
                  </span>
                </button>
              ))}
            </div>
          </aside>

          {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: Описание + Обзор ("лобовое стекло") ── */}
          <section className="flex-1 min-w-0">
            <div className="mb-5">
              <h3 className="font-semibold mb-1">Описание</h3>
              <div className="min-h-[90px] rounded-lg border border-neutral-200 bg-brand-light/50 px-4 py-3 text-sm text-neutral-600">
                {activeStopDef.description}
              </div>
            </div>

            <div>
              <h3 className="font-semibold mb-1">Обзор: {activeStopDef.label}</h3>
              <p className="text-xs text-neutral-500 mb-3">Меняется автоматически под активную остановку слева.</p>

              {/* ── Обзор ── */}
              {activeStop === "overview" && (
                <>
                  {uploadData!.parse_warnings.length > 0 && (
                    <div className="mb-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 space-y-1">
                      {uploadData!.parse_warnings.map((w, i) => (
                        <p key={i} className="text-sm text-amber-800 flex items-start gap-2">
                          <AlertTriangle size={14} className="shrink-0 mt-0.5" aria-hidden="true" />
                          {w}
                        </p>
                      ))}
                    </div>
                  )}

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                    <Metric label="Строк" value={formatNum(uploadData!.rows)} />
                    <Metric label="Колонок" value={String(uploadData!.columns)} />
                    <Metric label="Размер" value={uploadData!.size_label ?? "—"} />
                    <Metric label="Числовых" value={String(numericCols.length)} />
                  </div>

                  <div className="flex gap-1 mb-2">
                    <button
                      onClick={() => setOverviewTab("preview")}
                      className={`text-xs px-3 py-1.5 rounded-t border-b-2 transition-colors ${
                        overviewTab === "preview" ? "border-brand text-brand font-medium" : "border-transparent text-neutral-500 hover:text-neutral-800"
                      }`}
                    >
                      <Eye size={12} className="inline mr-1" aria-hidden="true" />
                      Превью
                    </button>
                    <button
                      onClick={() => setOverviewTab("columns")}
                      className={`text-xs px-3 py-1.5 rounded-t border-b-2 transition-colors ${
                        overviewTab === "columns" ? "border-brand text-brand font-medium" : "border-transparent text-neutral-500 hover:text-neutral-800"
                      }`}
                    >
                      <Database size={12} className="inline mr-1" aria-hidden="true" />
                      Типы колонок
                    </button>
                  </div>

                  {overviewTab === "preview" ? (
                    <div className="overflow-x-auto border border-neutral-200 rounded-lg">
                      <table className="w-full text-xs">
                        <thead className="bg-neutral-50 text-neutral-500 uppercase">
                          <tr>
                            {uploadData!.preview.head[0]?.map((colName, i) => (
                              <th key={i} className="text-left px-2 py-1.5">
                                {colName}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-neutral-100">
                          {uploadData!.preview.head.slice(1).map((row, i) => (
                            <tr key={`head-${i}`}>
                              {row.map((cell, j) => (
                                <td key={j} className="px-2 py-1.5">
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                          <tr className="text-neutral-400">
                            <td colSpan={uploadData!.preview.head[0]?.length ?? 1} className="px-2 py-1.5 text-center">
                              …
                            </td>
                          </tr>
                          {uploadData!.preview.tail.map((row, i) => (
                            <tr key={`tail-${i}`}>
                              {row.map((cell, j) => (
                                <td key={j} className="px-2 py-1.5">
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="overflow-x-auto border border-neutral-200 rounded-lg">
                      <table className="w-full text-sm">
                        <thead className="bg-neutral-50 text-xs text-neutral-500 uppercase">
                          <tr>
                            <th className="text-left px-3 py-2 font-medium">Колонка</th>
                            <th className="text-left px-3 py-2 font-medium">Тип</th>
                            <th className="text-right px-3 py-2 font-medium">Не пусто</th>
                            <th className="text-right px-3 py-2 font-medium">Пропуски</th>
                            <th className="text-right px-3 py-2 font-medium">Уникальных</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-neutral-100">
                          {columnsInfo.map((col) => (
                            <tr key={col.name}>
                              <td className="px-3 py-2 font-medium">{col.name}</td>
                              <td className="px-3 py-2 text-neutral-600">{col.dtype}</td>
                              <td className="text-right px-3 py-2">{formatNum(col.non_null)}</td>
                              <td className="text-right px-3 py-2">{col.nulls > 0 ? formatNum(col.nulls) : "—"}</td>
                              <td className="text-right px-3 py-2">{formatNum(col.unique)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}

              {/* ── График ── */}
              {activeStop === "chart" && (
                <>
                  {!confidentDateCol ? (
                    <p className="text-sm text-neutral-500 bg-neutral-50 rounded-lg p-4">
                      Дата не определена уверенно (см. остановку «Структура») — линейный график и декомпозиция
                      недоступны без надёжной временной оси.
                    </p>
                  ) : (
                    <>
                      <TimeSeriesLineChart data={timeseries} loading={timeseriesLoading} />
                      <div className="mt-4">
                        <h4 className="text-xs font-semibold mb-2 text-neutral-600">Декомпозиция</h4>
                        <DecompositionBadges
                          data={decomposition}
                          loading={decompositionLoading}
                          onCompute={fetchDecomposition}
                          hasComputed={decompositionRequested}
                        />
                      </div>
                    </>
                  )}
                </>
              )}

              {/* ── Распределение ── */}
              {activeStop === "distribution" && (
                <>
                  {numericCols.length === 0 ? (
                    <p className="text-sm text-neutral-500 bg-neutral-50 rounded-lg p-4">Числовые колонки не обнаружены.</p>
                  ) : (
                    <>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                        <div>
                          <h4 className="text-xs font-semibold mb-2 inline-flex items-center gap-1.5 text-neutral-600">
                            <ScatterChart size={13} aria-hidden="true" /> Точечный график
                          </h4>
                          {distributionLoading && !distribution ? (
                            <div className="h-[200px] border border-neutral-200 rounded flex items-center justify-center text-xs text-neutral-500 bg-neutral-50">
                              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                            </div>
                          ) : (
                            <>
                              <ScatterDistributionChart data={distribution} />
                              <SamplingBadge data={distribution} />
                            </>
                          )}
                        </div>
                        <div>
                          <h4 className="text-xs font-semibold mb-2 inline-flex items-center gap-1.5 text-neutral-600">
                            <BarChart3 size={13} aria-hidden="true" /> Гистограмма
                          </h4>
                          {distributionLoading && !distribution ? (
                            <div className="h-[200px] border border-neutral-200 rounded flex items-center justify-center text-xs text-neutral-500 bg-neutral-50">
                              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                            </div>
                          ) : (
                            <HistogramDistributionChart data={distribution} />
                          )}
                        </div>
                        <div>
                          <h4 className="text-xs font-semibold mb-2 inline-flex items-center gap-1.5 text-neutral-600">
                            <Activity size={13} aria-hidden="true" /> KDE (плотность)
                          </h4>
                          {distributionLoading && !distribution ? (
                            <div className="h-[200px] border border-neutral-200 rounded flex items-center justify-center text-xs text-neutral-500 bg-neutral-50">
                              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                            </div>
                          ) : (
                            <KdeDistributionChart data={distribution} />
                          )}
                        </div>
                      </div>

                      {statsLoading ? (
                        <p className="text-sm text-neutral-500 inline-flex items-center gap-2">
                          <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Считаем статистику…
                        </p>
                      ) : selectedStats?.stats ? (
                        <>
                          <p className="text-sm mb-3">
                            <span className="text-neutral-500">Тип распределения: </span>
                            <strong className="text-neutral-900">{selectedStats.stats.distribution_hint}</strong>
                          </p>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            <Metric label="Mean (среднее)" value={fmtStat(selectedStats.stats.mean)} />
                            <Metric label="Median (медиана)" value={fmtStat(selectedStats.stats.median)} />
                            <Metric label="Std (стандартное отклонение)" value={fmtStat(selectedStats.stats.std)} />
                            <Metric label="Skewness (асимметрия)" value={fmtStat(selectedStats.stats.skewness)} />
                            <Metric label="Kurtosis (эксцесс)" value={fmtStat(selectedStats.stats.kurtosis)} />
                            <Metric label="Q1 (1 квартиль)" value={fmtStat(selectedStats.stats.q1)} />
                            <Metric label="Q3 (3 квартиль)" value={fmtStat(selectedStats.stats.q3)} />
                            <Metric label="IQR (межквартильный размах)" value={fmtStat(selectedStats.stats.iqr)} />
                          </div>
                        </>
                      ) : selectedStats ? (
                        <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                          Недостаточно значений для расчёта статистики: непустых {selectedStats.non_null_count}{" "}
                          {selectedStats.non_null_count === 1 ? "значение" : "значения"} из {formatNum(uploadData!.rows)} строк
                          — данные слишком разрежены по этой колонке.
                        </p>
                      ) : (
                        <p className="text-sm text-neutral-500">Статистика недоступна для этой колонки.</p>
                      )}
                    </>
                  )}
                </>
              )}

              {/* ── Структура ── */}
              {activeStop === "structure" && !detection && (
                <p className="text-sm text-neutral-500 bg-neutral-50 rounded-lg p-4">
                  Определяем колонку даты и группировки…
                </p>
              )}
              {activeStop === "structure" && detection && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="border border-neutral-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-neutral-500 uppercase tracking-wide inline-flex items-center gap-1.5">
                        <Calendar size={12} aria-hidden="true" /> Колонка даты
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${confidenceColor(detection.dateCol.confidence)}`}>{detection.dateCol.confidence}%</span>
                    </div>
                    <select
                      value={detection.dateCol.selected}
                      onChange={(e) => setDetection({ ...detection, dateCol: { ...detection.dateCol, selected: e.target.value } })}
                      className="w-full border border-neutral-300 rounded px-2 py-1.5 text-sm font-medium"
                    >
                      {detection.dateCol.candidates.map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                      <option value="(не использовать)">(не использовать)</option>
                    </select>
                    <details className="mt-2 text-xs text-neutral-500">
                      <summary className="cursor-pointer inline-flex items-center gap-1">
                        <ChevronDown size={10} aria-hidden="true" /> кандидаты ({detection.dateCol.candidates.length})
                      </summary>
                      <ul className="mt-1 space-y-0.5">
                        {detection.dateCol.candidates.map((c) => (
                          <li key={c.name}>
                            • {c.name} — score {c.score.toFixed(2)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  </div>

                  <div className="border border-neutral-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-neutral-500 uppercase tracking-wide inline-flex items-center gap-1.5">
                        <Tag size={12} aria-hidden="true" /> Группирующая колонка
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${confidenceColor(detection.entityCol.confidence)}`}>{detection.entityCol.confidence}%</span>
                    </div>
                    <select
                      value={detection.entityCol.selected}
                      onChange={(e) => setDetection({ ...detection, entityCol: { ...detection.entityCol, selected: e.target.value } })}
                      className="w-full border border-neutral-300 rounded px-2 py-1.5 text-sm font-medium"
                    >
                      {detection.entityCol.candidates.map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                      <option value="(нет)">(нет)</option>
                    </select>
                    <details className="mt-2 text-xs text-neutral-500">
                      <summary className="cursor-pointer inline-flex items-center gap-1">
                        <ChevronDown size={10} aria-hidden="true" /> кандидаты ({detection.entityCol.candidates.length})
                      </summary>
                      <ul className="mt-1 space-y-0.5">
                        {detection.entityCol.candidates.map((c) => (
                          <li key={c.name}>
                            • {c.name} — score {c.score.toFixed(2)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  </div>

                  <div className="border border-neutral-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-neutral-500 uppercase tracking-wide inline-flex items-center gap-1.5">
                        <Clock size={12} aria-hidden="true" /> Частота ряда
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${confidenceColor(detection.freq.confidence)}`}>{detection.freq.confidence}%</span>
                    </div>
                    <select
                      value={detection.freq.selected}
                      onChange={(e) => setDetection({ ...detection, freq: { ...detection.freq, selected: e.target.value } })}
                      className="w-full border border-neutral-300 rounded px-2 py-1.5 text-sm font-medium"
                    >
                      {detection.freq.options.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                    <p className="mt-2 text-xs text-neutral-500">Оценено по {formatNum(uploadData!.rows)} строкам.</p>
                  </div>

                  {structuralClass && (
                    <div className="md:col-span-3 border border-brand/30 bg-brand-light/50 rounded-lg p-4">
                      <div className="flex items-center gap-2 mb-1">
                        <Route size={14} className="text-brand" aria-hidden="true" />
                        <span className="text-xs font-medium text-neutral-500 uppercase tracking-wide">Структурный класс данных</span>
                      </div>
                      <p className="font-semibold text-neutral-900">{structuralClass.label}</p>
                      <p className="text-sm text-neutral-600 mt-1">{structuralClass.description}</p>
                      <p className="text-xs text-neutral-500 mt-2">{structuralClass.routingHint}</p>
                    </div>
                  )}

                  <div className="md:col-span-3">
                    <StructuralClassSchema activeClassId={structuralClass?.id ?? null} />
                  </div>
                </div>
              )}

              {/* ── Качество ── */}
              {activeStop === "quality" && uploadData!.quality && (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                    <Metric label="Колонок с пропусками" value={String(uploadData!.quality.cols_with_missing)} />
                    <Metric label="Колонок с выбросами" value={String(uploadData!.quality.cols_with_outliers)} />
                    <Metric label="Всего строк" value={formatNum(uploadData!.quality.rows_total)} />
                    <Metric label="Дубликатов" value={String(uploadData!.quality.duplicates)} />
                  </div>
                  {(uploadData!.quality.cols_with_missing > 0 || uploadData!.quality.cols_with_outliers > 0 || uploadData!.quality.duplicates > 0) && (
                    <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5">
                      ⚠️{" "}
                      {[
                        uploadData!.quality.cols_with_missing > 0 && `${uploadData!.quality.cols_with_missing} колонки содержат пропуски`,
                        uploadData!.quality.cols_with_outliers > 0 && `${uploadData!.quality.cols_with_outliers} — потенциальные выбросы`,
                        uploadData!.quality.duplicates > 0 && `${uploadData!.quality.duplicates} дублирующихся строк`,
                      ]
                        .filter(Boolean)
                        .join(", ")}{" "}
                      → см. Валидация
                    </p>
                  )}
                </>
              )}
            </div>
          </section>

          {/* ── ПРАВАЯ КОЛОНКА: "руль и педали" — управление под активную остановку ── */}
          <aside className="w-80 shrink-0">
            {activeStop === "overview" && (
              <article>
                <h3 className="font-semibold mb-2">Файл</h3>
                <p className="text-sm text-neutral-600 mb-3">
                  {uploadData!.parse_warnings.length > 0
                    ? "Обнаружены технические предупреждения при чтении — проверьте превью и типы колонок слева перед тем, как продолжать."
                    : "Файл прочитан без технических замечаний. Проверьте превью и типы колонок — совпадают ли они с ожиданиями."}
                </p>
                <Button onClick={handleReset} variant="secondary" className="w-full">
                  Сменить файл
                </Button>
              </article>
            )}

            {activeStop === "chart" && (
              <article>
                <h3 className="font-semibold mb-2">Зачем это здесь</h3>
                <p className="text-sm text-neutral-600 mb-3">
                  Форма ряда на глаз (тренд, разрывы, аномальные всплески) — до того, как погружаться в статистику
                  распределения. Декомпозиция показывает, сколько в ряде объясняется трендом/сезонностью, а сколько
                  остаётся шумом — ориентир сложности задачи прогнозирования.
                </p>
                {!confidentDateCol && (
                  <p className="text-sm bg-amber-50 border border-amber-200 rounded px-3 py-2 text-amber-800">
                    Уверенная дата не найдена — перейдите на «Структуру» и подтвердите/скорректируйте date-колонку.
                  </p>
                )}
              </article>
            )}

            {activeStop === "distribution" && (
              <article>
                <h3 className="font-semibold mb-2">Зачем это здесь</h3>
                <p className="text-sm text-neutral-600 mb-3">
                  Асимметрия и эксцесс подсказывают, какие модели и трансформации будут уместны позже: сильная асимметрия обычно требует
                  стабилизации дисперсии в «Предобработке» до того, как переходить к ARIMA/SARIMA.
                </p>
                {selectedStats?.stats && (
                  <p className="text-sm bg-brand-light/60 rounded px-3 py-2 text-neutral-700">
                    <strong>{selectedFeature}</strong>: {selectedStats.stats.distribution_hint.toLowerCase()}
                  </p>
                )}
              </article>
            )}

            {activeStop === "structure" && (
              <article>
                <h3 className="font-semibold mb-2">Подтверждение</h3>
                <p className="text-sm text-neutral-600 mb-3">
                  Override сохраняется серверно (in-memory на этапе прототипа, Redis+TTL в продакшене) — переживёт F5. Применение
                  override-эндпоинта на бэкенде — TODO.
                </p>
                <Button onClick={handleApplyOverride} className="w-full">
                  Применить и пересчитать превью
                </Button>
              </article>
            )}

            {activeStop === "quality" && uploadData!.quality && (
              <article>
                <h3 className="font-semibold mb-2">Что дальше</h3>
                <p className="text-sm text-neutral-600 mb-2">Только счётчики — содержательный разбор проблем качества живёт в «Валидации».</p>
                {uploadData!.quality.missing_cols.length > 0 && (
                  <p className="text-xs text-neutral-500 mb-1">
                    <strong>С пропусками:</strong> {uploadData!.quality.missing_cols.join(", ")}
                  </p>
                )}
                {uploadData!.quality.outlier_cols.length > 0 && (
                  <p className="text-xs text-neutral-500 mb-3">
                    <strong>С выбросами:</strong> {uploadData!.quality.outlier_cols.join(", ")}
                  </p>
                )}
                <Link
                  href="/validation"
                  className="mt-2 inline-flex items-center justify-center gap-2 w-full bg-brand text-white rounded px-4 py-2 text-sm font-medium hover:bg-brand/90 transition-colors"
                >
                  Перейти к Валидации <ArrowRight size={16} aria-hidden="true" />
                </Link>
              </article>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
