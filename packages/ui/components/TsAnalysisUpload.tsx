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
//   Загрузка [Справка]    Описание                    Обзор / Управление
//   Признак: ▾price       [текстовое поле]             (меняется по
//   2/4 ██░░               Обзор: {label}                активной
//   ┌─Обзор──────✓─┐      [таблица/график/карточки]      остановке)
//   ├─График──────✓┤      [Metric-карточки]
//   ├─Распределение✓┤
//   ├─Структура───⚠┤      UPLOAD-SEM-1 (2026-10-20): статусы
//   └─Качество────✓┘      ознакомительных остановок -- done/pending
//                         по факту просмотра (паттерн EDA PROGR-18);
//                         только «Структура» факт-обусловленная:
//                         done/warning/error (PROGR-14-A + error
//                         «структура не определяется»).
//
// Кнопка «Справка» в заголовке колонки «Загрузка» (UI-UPLOAD-HELP-1,
// паттерн «Валидации») раскрывает в окне «Описание» развёрнутое описание
// модуля из единого реестра справки (describeNode("upload", null,
// "module_help"), нативная запись upload.module.module_help).
//
// Верхняя полоса "Источник данных" (dropzone) -- ВНЕ 3-колоночного
// блока, на всю ширину: она не принадлежит ни одной "остановке", нужна
// всегда (пере-загрузка файла возможна с любой активной остановки).
//
// UPLOAD-SEM-1 (2026-10-20, решение тимлида): семантика статусов
// остановок переведена на «агентность аналитика» -- warning/error
// только там, где есть действие in-place. Ознакомительные остановки
// (Обзор/График/Распределение/Качество) получают done/pending по факту
// просмотра (монотонное множество, seed трассы + якорь -- паттерн EDA
// PROGR-18/AUDIT-2B).
//
// UPLOAD-RECOMP-2 (2026-10-20): «Структура» -- решающе-обусловленная:
// (2a) зелёный done ТОЛЬКО после явного подтверждения кнопкой
// «Подтвердить структуру данных» -- связка двух фактов (локальный
// structureConfirmed + POST /date-column confirmed=true, бэкенд пишет
// structure_confirmed; reportUploadStopsNow -- зеркальный ре-пост
// панели); уверенная детекция без подтверждения -- pending «ждёт
// подтверждения»; warning/error семантика PROGR-14-A/UPLOAD-SEM-1
// сохранена до подтверждения. (2b) Схема «Определение структуры» --
// компактная таблица с русскими определениями (RU_DEFINITION) и
// решаемыми задачами (RU_TASKS) из единого источника structuralClass.ts.
// (2c) Панельные микросервисы: при классе панели -- блок «три пути
// исследования» (фильтр сущности / агрегация по времени -- preview/
// apply по POST /dataset/entity-filter, /dataset/panel-aggregate;
// пассивный бейдж «Ряд не трансформируем»). После apply --
// transformEpoch+1: новая вселенная фактов (сброс просмотров/
// подтверждения, seed не выполняется -- трасса принадлежит прежнему
// содержимому), re-detection контура детекции, ре-фетч статистик/превью.
//
// Контракт вкладки «Загрузка» (по решению тимлида) -- 8 пунктов,
// распределены по 4 "остановкам" степпера:
//   Обзор:         1. Превью датасета -- три вкладки (UI-UPLOAD-FULL-1,
//                     2026-10-14): «Превью» (head/tail), «Типы колонок»,
//                     «Весь датасет» -- виртуализированный просмотр ВСЕХ
//                     строк (ползунок размечен на весь датасет, окна строк
//                     догружаются с GET /dataset/rows?offset=&limit=,
//                     apps/api/routers/session.py::get_dataset_rows)
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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  Table,
  BarChart3,
  ScatterChart,
  Activity,
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  Loader2,
  Route,
  Info,
  Layers,
} from "lucide-react";
import { Button } from "./Button";
import { DbConnectionForm } from "./DbConnectionForm";
import type { ColumnInfoOut, UploadApiResponse } from "../lib/upload";
import { Metric } from "./Metric";
import { StepperNextModuleButton } from "./StepperNextModuleButton";
import {
  DistributionChartData,
  HistogramDistributionChart,
  KdeDistributionChart,
  SamplingBadge,
  ScatterDistributionChart,
} from "./DistributionCharts";
import { TimeSeriesLineChart, type TimeSeriesChartData } from "./TimeSeriesLineChart";
import { VisualExportButton, VisualExportChartScope } from "./VisualExportButton";
import { DecompositionBadges, type DecompositionData } from "./DecompositionBadges";
import { DecompositionSeriesChart, type DecompositionSeriesData } from "./DecompositionSeriesChart";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { StructuralClassSchema } from "./StructuralClassSchema";
// PROGR-13-A1 (§12 п.2): общий реестр остановок «Загрузки» -- тот же
// файл, что читают граф бэкенда и зеркало панели (см. комментарий у STOPS).
import uploadStopsJson from "../../../shared/pipeline_nodes/upload_stops.json";
import { useAppShell } from "../context/AppShellContext";
import { apiUrl, sessionApiUrl, progressApiUrl } from "../lib/apiClient";
import { useProgressMapDelivery } from "../hooks/useProgressMapDelivery";
import { classifyStructure, type PanelBalance, type StructuralClassResult } from "../lib/structuralClass";
import { useTargetColumn } from "../hooks/useTargetColumn";
// UI-UPLOAD-HELP-1 (2026-10-14): развёрнутое описание модуля для кнопки
// «Справка» берётся из ЕДИНОГО реестра методологий/описаний платформы
// (packages/ui/lib/knowledge) -- никаких текстовых констант в компоненте.
import { describeNode } from "../lib/knowledge/knowledge";
import { DatasetPassportPanel } from "./DatasetPassportPanel";
import { DEMO_DATASETS, demoDatasetToFile } from "../lib/demoDatasets";
// MNS-LINK-3: узловый deep-link Наставника -- якорь #stop=<node_id> и
// same-route событие (панель «Прогресс» доступна на всех вкладках).
import { GOTO_STOP_EVENT, stopFromHash, type GotoStopDetail } from "../lib/stopLinks";

// ──────────────────────────────────────────────────────────────────────
// ТИПЫ (зеркало apps/api/schemas.py -- поля намеренно snake_case, как
// отдаёт API, без промежуточного camelCase-слоя)
// ──────────────────────────────────────────────────────────────────────

// File and SQL uploads share the same wire response.
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

/** Окно строк полного датасета -- GET /dataset/rows (UI-UPLOAD-FULL-1).
 *  Зеркало apps/api/schemas.py::DatasetRowsResponse. */
interface DatasetRowsResponse {
  columns: string[];
  rows: string[][];
  offset: number;
  limit: number;
  total_rows: number;
  returned: number;
  has_more: boolean;
}

type StopId = "overview" | "chart" | "distribution" | "structure" | "quality";

interface Stop {
  id: StopId;
  label: string;
  description: string;
}

// PROGR-13-A1 (§12 п.2, паттерн eda_checks.json): реестр остановок --
// ОБЩИЙ JSON (single source): его же читает граф бэкенда
// (app/core/pipeline_graph.py::UPLOAD_STAGE_IDS) и зеркало панели
// (packages/ui/lib/progress.ts). Вшитой копии в компоненте больше нет:
// дефект 1а PROGR-13 (панель «Прогресс» показывала 1 остановку из 5)
// стал возможен именно из-за независимых списков. Порядок объектов =
// порядок остановок степпера.
const STOPS: Stop[] = (
  uploadStopsJson.nodes as ReadonlyArray<{
    id: StopId;
    label: string;
    description: string;
  }>
).map((stop) => ({ ...stop }));

// UPLOAD-SEM-1: зеркало CheckStatus (StatusIcon.tsx) для фильтра seed'а
// трассы -- узлы с чужими/мусорными статусами не сеются (журнал -- R3
// PROGR-1-CERT: событие хранится, фантомного статуса не создаёт).
const UPLOAD_SEED_STATUSES: ReadonlySet<string> = new Set([
  "done",
  "warning",
  "pending",
  "skipped",
  "running",
  "error",
]);

/** Канонический снапшот карты остановок для дедупа/якоря AUDIT-2B
 * (форма совпадает с map, ключи -- реестр upload_stops.json). */
function buildUploadStopsSnapshot(statuses: Record<StopId, CheckStatus>): string {
  return JSON.stringify(
    Object.fromEntries(STOPS.map((s) => [s.id, statuses[s.id] ?? "pending"])),
  );
}

const FREQ_OPTIONS = [
  "H — почасовая",
  "D — ежедневная",
  "W — недельная",
  "M — месячная",
  "Q — квартальная",
  "Y — годовая",
  "(авто, не получилось)",
];

// ── Вкладка «Весь датасет» (UI-UPLOAD-FULL-1, 2026-10-14) ────────────
// Виртуализированный просмотр ВСЕГО датасета: spacer контейнера имеет
// высоту FULL_HEADER_H + total_rows * FULL_ROW_H -- native ползунок
// справа размечен на ВЕСЬ датасет сразу (аналитик может прокрутить от
// первой до последней строки). По позиции прокрутки вычисляется видимое
// окно строк; недостающие страницы (по FULL_PAGE_LIMIT строк) догружаются
// с GET /dataset/rows?offset=&limit= (бэкенд-капа -- 1000/страницу).
// Вне окна DOM не содержит строк -- браузер держит любой размер датасета.
const FULL_PAGE_LIMIT = 200; // строк на страницу запроса (<= капы бэкенда)
const FULL_ROW_H = 32; // px, фиксированная высота строки (виртуализация)
const FULL_HEADER_H = 36; // px, высота закреплённой шапки колонок
const FULL_VIEWPORT_H = 480; // px, высота контейнера прокрутки
const FULL_OVERSCAN_ROWS = 10; // запас строк выше/ниже видимого окна

/** Сетка строки/шапки «Весь датасет»: ведущая колонка № + колонки датасета. */
function fullGridTemplate(nCols: number): string {
  return `44px repeat(${nCols}, minmax(150px, 1fr))`;
}

// ──────────────────────────────────────────────────────────────────────
// ВСПОМОГАТЕЛЬНЫЕ
// ──────────────────────────────────────────────────────────────────────

function confidenceColor(pct: number): string {
  if (pct >= 85) return "bg-green-100 text-green-700";
  if (pct >= 70) return "bg-amber-100 text-amber-700";
  return "bg-red-100 text-red-700";
}

// PROGR-14-A: явные выборы-маркеры отсутствия колонки -- «(нет)» у
// группирующей, «(не использовать)» у даты. Это РЕШАЮЩИЕ состояния выбора
// («колонки нет»), а не сомнительные догадки: у авто-детекта здесь нечему
// быть «неуверенным», и raw confidence 0% описывает отсутствие скоринга,
// а не сомнение (бэкенд отдаёт 0%, когда колонки такого рода в датасете
// нет -- см. apps/api/routers/session.py::get_structure_detection).
const EXPLICIT_NONE_CHOICES: ReadonlySet<string> = new Set(["(нет)", "(не использовать)"]);

function isExplicitNoneChoice(selected: string): boolean {
  return EXPLICIT_NONE_CHOICES.has(selected);
}

/**
 * PROGR-14-A: решение «Структуры» по одной колонке -- уверенное, если
 * выбран явный маркер отсутствия (см. EXPLICIT_NONE_CHOICES) ЛИБО raw
 * confidence авто-детекта >= 70 (порог прежний). Статус выводится из
 * ФАКТА РЕШЕНИЯ, а не из сырой оценки: raw confidence сохраняет ровно
 * один смысл -- честно ПРЕДУПРЕДИТЬ о сомнительном угадывании
 * КОНКРЕТНОЙ колонки (прецедент гейта confidentDateCol 2026-08-14:
 * «доверяем осознанному выбору, confidence -- только для предупреждения
 * о низком авто-детекте»).
 */
function isStructureDecisionConfident(col: { selected: string; confidence: number }): boolean {
  return isExplicitNoneChoice(col.selected) || col.confidence >= 70;
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
  // PROGR-4 (§6.1): addLogEntry удалён из shell-контекста -- факты загрузки
  // пишет бэкенд-хук (upload_completed, §4.2); ошибки -- инлайн + тост ниже.
  const { activeDataset, setActiveDataset, refreshSession } = useAppShell();

  // ── Источник данных (верхняя полоса, вне степпера) ──
  const [source, setSource] = useState<"file" | "db">("file");
  const [fileName, setFileName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadData, setUploadData] = useState<UploadApiResponse | null>(null);
  const [hydrating, setHydrating] = useState(false);

  // ── Степпер / 3-колоночный блок ──
  const [activeStop, setActiveStop] = useState<StopId>("overview");
  // ── MNS-LINK-3: узловый deep-link Наставника (spec_mentor_next_step.md
  // §5.3, решение Q6). Якорь #stop=<node_id> читается при МОНТИРОВАНИИ
  // (cross-stage переход, перезагрузка, закладка), на hashchange
  // (back/forward) и явным событием GOTO_STOP_EVENT (same-route переход
  // из MentorPanel -- панель доступна на всех вкладках). Парс
  // fail-closed (stopFromHash): неизвестный/чужой узел -- null, степпер
  // остаётся на дефолте. Переключение -- с семантикой клика по остановке
  // (инвариант UI-UPLOAD-HELP-1): Справка закрывается, «Описание»
  // показывает новую остановку; no-op для уже активной (Справка
  // сохраняется). Событие/якорь -- совет, не факт: в трассу не пишется.
  useEffect(() => {
    const gotoStop = (nodeId: string) => {
      if (nodeId === activeStop) return;
      setActiveStop(nodeId as StopId);
      setDescriptionSection("stop");
    };
    const onHashChange = () => {
      const requested = stopFromHash(window.location.hash, "upload");
      if (requested) gotoStop(requested);
    };
    const onGotoStop = (event: Event) => {
      const detail = (event as CustomEvent<GotoStopDetail>).detail;
      if (detail?.stage === "upload" && typeof detail.node_id === "string") gotoStop(detail.node_id);
    };
    onHashChange();
    window.addEventListener("hashchange", onHashChange);
    window.addEventListener(GOTO_STOP_EVENT, onGotoStop);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
      window.removeEventListener(GOTO_STOP_EVENT, onGotoStop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeStop]);
  // ── Секция окна «Описание» (UI-UPLOAD-HELP-1, паттерн «Валидации»):
  // "stop" -- описание активной остановки (дефолт), "help" -- развёрнутое
  // описание модуля из единого реестра справки (кнопка «Справка»).
  // Toggle-закрытие и переключение остановки возвращают "stop"
  // (инвариант информативности -- см. TsAnalysisValidation).
  const [descriptionSection, setDescriptionSection] = useState<"stop" | "help">("stop");
  // Toggle «Справки» (паттерн «Валидации»): закрытие возвращает описание
  // активной остановки -- инвариант информативности, не placeholder.
  const handleHelpClick = () => {
    setDescriptionSection((prev) => (prev === "help" ? "stop" : "help"));
  };
  const [detection, setDetection] = useState<StructureDetection | null>(null);
  const [stats, setStats] = useState<ColumnStatsOut[] | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [distribution, setDistribution] = useState<DistributionChartData | null>(null);
  const [distributionLoading, setDistributionLoading] = useState(false);
  // ── Остановка «График» (2026-08-14): линейный график + декомпозиция ──
  const [timeseries, setTimeseries] = useState<TimeSeriesChartData | null>(null);
  const [timeseriesLoading, setTimeseriesLoading] = useState(false);
  const [decomposition, setDecomposition] = useState<DecompositionData | null>(null);
  const [decompositionSeries, setDecompositionSeries] = useState<DecompositionSeriesData | null>(null);
  const [decompositionLoading, setDecompositionLoading] = useState(false);
  const [decompositionRequested, setDecompositionRequested] = useState(false);
  const [overviewTab, setOverviewTab] = useState<"preview" | "columns" | "full">("preview");

  // ── Вкладка «Весь датасет» (UI-UPLOAD-FULL-1) ──
  // Мета (колонки + total_rows) приходит с ЛЮБОЙ страницей /dataset/rows;
  // страницы кэшируются (обратное переключение вкладок не перезапрашивает),
  // смена датасета сбрасывает всё (гонка «старый датасет -> новый»).
  const [fullMeta, setFullMeta] = useState<{ columns: string[]; totalRows: number } | null>(null);
  const [fullPages, setFullPages] = useState<Map<number, string[][]>>(new Map());
  const [fullPending, setFullPending] = useState(0); // число запросов в полёте
  const [fullError, setFullError] = useState<string | null>(null);
  const [fullScrollTop, setFullScrollTop] = useState(0);
  const fullInFlightRef = useRef<Set<number>>(new Set());
  const fullDatasetKeyRef = useRef<string | null>(null);

  // ── Единый "исследуемый признак" (target_column) для всей платформы
  // (2026-08-14) -- заменяет прежний локальный useState<string|null>,
  // который сбрасывался при каждом уходе с вкладки и откатывался к
  // numericCols[0] (первой числовой колонке ПО ПОРЯДКУ В ДАТАФРЕЙМЕ --
  // для Country/Year/Price это был Year, не Price). См. packages/ui/hooks/useTargetColumn.ts.
  const {
    targetColumn: selectedFeature,
    suggestedColumn,
    wasAutoSelected,
    columnResetNotice,
    dismissColumnResetNotice,
    passportResetNotice,
    setColumn: setSelectedFeature,
    refetch: refetchTargetColumn,
  } = useTargetColumn(activeDataset?.name);

  const isUploaded = uploadData !== null;

  // ── Уведомление о смене признака при загрузке нового датасета ──
  // (2026-08-14, согласовано с тимлидом: "и то, и другое" -- toast И
  // инлайн-бейдж). columnResetNotice приходит из useTargetColumn, когда
  // РАНЕЕ выбранная колонка (например Price) отсутствует в новом
  // датасете -- backend сам сбрасывает target_column при set_dataset().
  // ПРОГР-25-B: авто-ПОСТ снят -- хук ничего не фиксирует, поэтому
  // newColumn в уведомлении -- РЕКОМЕНДАЦИЯ бэкенда (suggested_column)
  // или null; текст честно различает «рекомендация» и «выберите».
  useEffect(() => {
    if (columnResetNotice) {
      toast.warning(
        columnResetNotice.newColumn
          ? `Признак «${columnResetNotice.previousColumn}» недоступен в новом датасете — рекомендация: «${columnResetNotice.newColumn}»`
          : `Признак «${columnResetNotice.previousColumn}» недоступен в новом датасете — выберите новый признак`,
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

  // UPLOAD-RECOMP-2 §3.4: панельные преобразования (entity-filter /
  // panel-aggregate) меняют СОДЕРЖИМОЕ датасета при том же datasetId
  // (lineage-файл) -- факты просмотров/подтверждения прежнего содержимого
  // не валидны для нового. Счётчик transformEpoch (+1 на каждый apply)
  // входит в ключ вселенной факт-контура; снапшоты разных epoch не
  // смешиваются (H27-безопасно). Смена datasetId продолжает сбрасывать
  // счётчик косвенно (новая вселенная целиком).
  // UPLOAD-RECOMP-2-FIX (2026-10-20): счётчик объявлен ДО эффектов
  // выборки данных (распределение/график/декомпозиция/кэш «Весь
  // датасет») -- они подписаны на transformEpoch и ре-фетчат
  // преобразованное содержимое (дефект «график не изменился»).
  const [transformEpoch, setTransformEpoch] = useState(0);

  // ── Загрузка данных для графиков распределения (эндпоинт per-column,
  // не часть общего /dataset/stats -- считать scatter/histogram/KDE для
  // ВСЕХ числовых колонок сразу было бы избыточно, запрашиваем только
  // выбранный признак). apps/api/routers/session.py::get_dataset_distribution ──
  // UPLOAD-RECOMP-2-FIX (2026-10-20): transformEpoch в зависимостях --
  // панельное преобразование (entity-filter/panel-aggregate) меняет
  // СОДЕРЖИМОЕ датасета при том же dataset_id -- распределение старой
  // панели не должно «залипать» после apply.
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
  }, [selectedFeature, isUploaded, transformEpoch]);

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
  // UPLOAD-RECOMP-2-FIX (2026-10-20): transformEpoch в зависимостях --
  // после apply панельного микросервиса («Фильтр сущности»/«Агрегация по
  // времени») содержимое датасета изменилось при том же dataset_id:
  // график обязан показать преобразованный ряд (сценарий тимлида:
  // панель -> «Структура» -> микросервис -> «Подтвердить структуру
  // данных» -> возврат на «График» -- график оставался панельным).
  // selectedFeature/confidentDateCol при преобразовании не меняются --
  // без transformEpoch эффект не перезапускается и данные остаются
  // старыми (дефект воспроизведён тестом upload-panel-chart-refresh).
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
  }, [selectedFeature, confidentDateCol, isUploaded, transformEpoch]);

  // Сбрасываем декомпозицию при смене признака -- старый результат для
  // другой колонки не должен "залипать" под новым выбором (пользователь
  // должен нажать кнопку заново -- по решению тимлида, ленивый расчёт).
  // UPLOAD-RECOMP-2-FIX (2026-10-20): transformEpoch -- панельное
  // преобразование меняет содержимое датасета; результат декомпозиции
  // ПАНЕЛИ не переживает apply (ленивый пересчёт той же кнопкой).
  useEffect(() => {
    setDecomposition(null);
    setDecompositionSeries(null);
    setDecompositionRequested(false);
  }, [selectedFeature, confidentDateCol, transformEpoch]);

  // ── «Весь датасет»: сброс кэша страниц при смене датасета ──
  // Гонка «страницы старого датасета под новым» невозможна: ключ
  // (dataset_id) меняется -- кэш, мета и позиция ползунка обнуляются ДО
  // первого запроса нового окна (fetchFullPage читает ключ из ref).
  // UPLOAD-RECOMP-2-FIX (2026-10-20): панельное преобразование меняет
  // содержимое при ТОМ ЖЕ dataset_id -- ключ дополнен transformEpoch,
  // кэш панельных страниц не переживает apply.
  useEffect(() => {
    const key = `${uploadData?.dataset_id ?? null}:${transformEpoch}`;
    if (fullDatasetKeyRef.current !== key) {
      fullDatasetKeyRef.current = key;
      setFullMeta(null);
      setFullPages(new Map());
      setFullError(null);
      setFullScrollTop(0);
      fullInFlightRef.current = new Set();
    }
  }, [uploadData?.dataset_id, transformEpoch]);

  // ── «Весь датасет»: загрузка одной страницы строк ──
  // GET /dataset/rows?offset=&limit= (apps/api/routers/session.py::
  // get_dataset_rows). Мета берётся из первого ответа (колонки +
  // total_rows); страницы складываются в кэш; ошибка -- честный
  // инлайн-статус с «Повторить» (не тихий пропуск).
  const fetchFullPage = useCallback(async (page: number) => {
    if (fullInFlightRef.current.has(page)) return;
    fullInFlightRef.current.add(page);
    setFullPending((n) => n + 1);
    try {
      const offset = page * FULL_PAGE_LIMIT;
      const res = await fetch(
        sessionApiUrl(`/dataset/rows?offset=${offset}&limit=${FULL_PAGE_LIMIT}`),
        { credentials: "include" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: DatasetRowsResponse = await res.json();
      setFullMeta((prev) => prev ?? { columns: data.columns, totalRows: data.total_rows });
      setFullPages((prev) => {
        const next = new Map(prev);
        next.set(page, data.rows);
        return next;
      });
      setFullError(null);
    } catch {
      setFullError("Не удалось загрузить строки датасета — проверьте соединение с API");
    } finally {
      fullInFlightRef.current.delete(page);
      setFullPending((n) => n - 1);
    }
  }, []);

  // ── «Весь датасет»: видимое окно строк по позиции ползунка ──
  // Ползунок размечен на весь датасет (spacer = header + total*ROW_H),
  // поэтому прокрутка от начала до конца работает нативно; здесь из
  // scrollTop вычисляется окно [fullStart, fullEnd) с запасом overscan.
  const fullTotal = fullMeta?.totalRows ?? 0;
  const fullStart = Math.max(0, Math.floor(fullScrollTop / FULL_ROW_H) - FULL_OVERSCAN_ROWS);
  const fullEnd = Math.min(
    fullTotal,
    Math.ceil((fullScrollTop + FULL_VIEWPORT_H) / FULL_ROW_H) + FULL_OVERSCAN_ROWS
  );

  // Догрузка страниц, пересекающихся с видимым окном (и первое открытие
  // вкладки -- страница 0 одной строкой логики). При ошибке ждём
  // «Повторить» (fullError -> null перезапускает эффект).
  useEffect(() => {
    if (overviewTab !== "full" || fullError) return;
    if (!fullMeta) {
      fetchFullPage(0);
      return;
    }
    if (fullTotal <= 0) return;
    const firstPage = Math.floor(fullStart / FULL_PAGE_LIMIT);
    const lastPage = Math.floor(Math.max(fullEnd - 1, fullStart) / FULL_PAGE_LIMIT);
    for (let p = firstPage; p <= lastPage; p++) {
      if (!fullPages.has(p)) fetchFullPage(p);
    }
    // fullPages сознательно вне зависимостей: проверка актуальна на момент
    // изменения окна; успешно загруженная страница не должна перезапускать
    // цикл (fetchFullPage сам защищён от повторов in-flight).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overviewTab, fullMeta, fullStart, fullEnd, fullError, fullTotal, fetchFullPage]);

  // Видимые строки из кэша страниц (страницы вне кэша честно отсутствуют
  // в DOM -- место под них уже зарезервировано spacer'ом, догрузка видна
  // как «догружаем…» в статусной строке).
  const fullVisibleRows: Array<{ rowIndex: number; values: string[] }> = [];
  if (fullMeta && fullTotal > 0) {
    for (let i = fullStart; i < fullEnd; i++) {
      const page = Math.floor(i / FULL_PAGE_LIMIT);
      const rows = fullPages.get(page);
      const row = rows ? rows[i - page * FULL_PAGE_LIMIT] : undefined;
      if (row) fullVisibleRows.push({ rowIndex: i, values: row });
    }
  }

  const handleFullScroll = (e: React.UIEvent<HTMLDivElement>) => {
    setFullScrollTop(e.currentTarget.scrollTop);
  };

  // ── Декомпозиция (остановка «График», ПО КНОПКЕ -- STL на statsmodels
  // не мгновенная, см. согласование с тимлидом 2026-08-14) ──
  // apps/api/routers/session.py::get_dataset_decomposition +
  // get_dataset_decomposition_series (2026-08-19, "визуализировать
  // данный декомпозированный ряд на дополнительном графике") -- один
  // клик по кнопке запускает ОБА запроса параллельно (бейджи + график
  // компонент), не два отдельных действия пользователя.
  const fetchDecomposition = useCallback(() => {
    if (!selectedFeature || !confidentDateCol) return;
    setDecompositionRequested(true);
    setDecompositionLoading(true);
    const badgesUrl = sessionApiUrl(
      `/dataset/decomposition?column=${encodeURIComponent(selectedFeature)}&date_column=${encodeURIComponent(confidentDateCol)}`
    );
    const seriesUrl = sessionApiUrl(
      `/dataset/decomposition-series?column=${encodeURIComponent(selectedFeature)}&date_column=${encodeURIComponent(confidentDateCol)}`
    );
    Promise.all([
      fetch(badgesUrl, { credentials: "include" }).then((r) => (r.ok ? r.json() : null)),
      fetch(seriesUrl, { credentials: "include" }).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([badges, series]: [DecompositionData | null, DecompositionSeriesData | null]) => {
        setDecomposition(badges);
        setDecompositionSeries(series);
      })
      .catch(() => {
        setDecomposition(null);
        setDecompositionSeries(null);
      })
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
          // причиной бага -- откатывалось на Year вместо Price).
          // ПРОГР-25-A: бэкенд сам авто-фиксирует признак при загрузке
          // (ровно один кандидат) -- рефетчим, чтобы селектор/бейджи
          // показали актуальное состояние; при неоднозначности остаётся
          // честное «не выбран» с отображаемой рекомендацией.
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

  // One acceptance path: DB loads update all five stops, target, shell and
  // session exactly like file uploads; no second frontend progress reducer.
  const acceptUploadedData = useCallback(async (data: UploadApiResponse, fromDatabase = false) => {
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
      datasetId: data.dataset_id,
      name: data.name,
      rows: data.rows,
      sizeLabel: data.size_label ?? "—",
      ...(data.frequency && { frequency: data.frequency }),
      ...(data.domain && { domain: data.domain }),
      ...(data.n_series != null && { nSeries: data.n_series }),
      ...(data.has_seasonality != null && { hasSeasonality: data.has_seasonality }),
      ...(data.is_regular != null && { isRegular: data.is_regular }),
    });

    try { await refreshSession(); } catch { toast.warning("Данные загружены; не удалось обновить сведения о сессии."); }
    toast.success(fromDatabase ? "Данные из БД загружены успешно!" : "Файл загружен успешно!");

    if (data.parse_warnings.length > 0) {
      toast.warning(`${fromDatabase ? "Технические предупреждения при загрузке данных" : "Технические предупреждения при чтении файла"} (${data.parse_warnings.length})`);
    }
  }, [setActiveDataset, refreshSession, fetchStats, refetchTargetColumn]);

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
        await acceptUploadedData(data);
      } catch (e) {
        const message = e instanceof Error ? e.message : "Неизвестная ошибка загрузки";
        setUploadError(message);
        toast.error(`Ошибка: ${message}`);
      } finally {
        setUploading(false);
      }
    },
    [acceptUploadedData]
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
    disabled: uploading || hydrating,
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

  // (handleApplyOverride -- «локальное подтверждение» -- удалено:
  // UPLOAD-RECOMP-2a заменил его связкой фактов «Подтвердить структуру
  // данных» -- handleConfirmStructure.)

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
      // UPLOAD-RECOMP-2-DECOMP (2026-10-20): выбранная временная колонка
      // исключается из иерархической цепочки (время -- не уровень
      // вложенности сущностей): без этого любая панель со строчными
      // датами CSV (type_icon "categorical") классифицировалась как
      // Hierarchical (region -> month), панельные микросервисы не
      // появлялись и путь «панель -> преобразование -> декомпозиция»
      // на остановке «График» был заблокирован (дефект воспроизведён
      // на живом стеке standalone+api, см. structuralClass.test.ts).
      dateColumnName: detection.dateCol.selected !== "(не использовать)" ? detection.dateCol.selected : null,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detection, columnsInfo, panelBalance]);

  // ── UPLOAD-SEM-1: просмотры остановок + seed фактов панели ──────────
  // Статусы ознакомительных остановок стали просмотр-зависимыми и
  // перестали быть детерминированной функцией данных: remount с пустым
  // множеством просмотров отправил бы all-pending карту ПОВЕРХ
  // записанных done-фактов (last-wins -- регресс панели, класс H27).
  // Паттерн EDA PROGR-18/AUDIT-2B/3: одноразовый GET /v1/progress/trace
  // на вселенную; done-узлы upload/* (validity=current) сеются в
  // просмотренные («Структура» не сеется -- она факт-обусловленная);
  // якорь = снапшот записанных статусов как есть (идентичный снапшот
  // не доставляется повторно); seed не получен -- отчёт удерживается
  // (H27), ретрай по новому просмотру; легаси-жёлтые перезаписываются
  // первым отличающимся снапшотом (миграция §3.4 плана задачи).
  // Ключ вселенной фактов просмотров -- СОБСТВЕННЫЙ факт модуля:
  // dataset_id из ответа загрузки/гидратации (uploadData). Контекст
  // AppShell (activeDataset) ненадёжен для этого: refreshSession внутри
  // acceptUploadedData перезаписывает его ответом /current -- при
  // медленном/отказном /current ключ схлопнулся бы в null и сброс
  // вселенной не срабатывал бы (класс H28).
  const datasetUniverseKey = uploadData?.dataset_id ?? activeDataset?.datasetId ?? null;
  // UPLOAD-RECOMP-2 §3.4: счётчик transformEpoch объявлен выше, рядом с
  // эффектами выборки данных (подписаны на него -- FIX 2026-10-20);
  // здесь -- ключ вселенной факт-контура просмотров/подтверждений.
  const factsUniverseKey = datasetUniverseKey ? `${datasetUniverseKey}:${transformEpoch}` : null;
  const [viewedStops, setViewedStops] = useState<Set<StopId>>(new Set());
  const [uploadSeedReady, setUploadSeedReady] = useState(false);
  const [uploadSeedFailed, setUploadSeedFailed] = useState(false);
  const [uploadSeedAnchor, setUploadSeedAnchor] = useState<string | null>(null);
  const [uploadSeedRetryTick, setUploadSeedRetryTick] = useState(0);
  const uploadSeedReadyRef = useRef(false);
  const uploadSeedFailedRef = useRef(false);
  // Явное решение аналитика по колонке даты (снимает критерий error:
  // «(не использовать)»/конкретная колонка -- выбор сделан, см. stopStatus).
  const [dateColTouched, setDateColTouched] = useState(false);
  // UPLOAD-RECOMP-2 §3.1: решающе-обусловленный статус «Структуры» --
  // done ТОЛЬКО после явного подтверждения аналитика (кнопка
  // «Подтвердить структуру данных»): уверенная детекция -- pending
  // «ждёт подтверждения». Сеется из трассы (узел upload/structure=done
  // -- исключение «Структура не сеется» снято), сбрасывается сменой
  // датасета/селекторов/панельным преобразованием (новая вселенная).
  const [structureConfirmed, setStructureConfirmed] = useState(false);

  // Сброс вселенной фактов -- ДО seed-эффекта (порядок декларации =
  // порядок запуска, урок PROGR-17): новая вселенная -- чистое
  // множество просмотров, якорь null, seed перезапускается.
  useEffect(() => {
    uploadSeedReadyRef.current = false;
    uploadSeedFailedRef.current = false;
    setViewedStops(new Set());
    setUploadSeedReady(false);
    setUploadSeedFailed(false);
    setUploadSeedAnchor(null);
    setDateColTouched(false);
    setStructureConfirmed(false);
  }, [factsUniverseKey]);

  useEffect(() => {
    if (!factsUniverseKey) {
      uploadSeedReadyRef.current = true;
      uploadSeedFailedRef.current = false;
      setUploadSeedReady(true);
      setUploadSeedFailed(false);
      return;
    }
    // UPLOAD-RECOMP-2 §3.4: transformEpoch > 0 -- трасса принадлежит
    // ПРЕЖНЕМУ содержимому датасета (панельное преобразование); seed не
    // выполняется: честная новая вселенная -- всё pending до новых
    // просмотров, отчёт доставляется как первое наблюдение (без якоря).
    if (transformEpoch > 0) {
      uploadSeedReadyRef.current = true;
      uploadSeedFailedRef.current = false;
      setUploadSeedReady(true);
      setUploadSeedFailed(false);
      setUploadSeedAnchor(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      const knownIds = new Set(STOPS.map((s) => s.id));
      const seedViewed = new Set<StopId>();
      const seedStatuses: Partial<Record<StopId, CheckStatus>> = {};
      // UPLOAD-RECOMP-2 §3.1: seed structureConfirmed -- узел
      // upload/structure=done (факт structure_confirmed бэкенда) сеется
      // в локальное подтверждение (исключение «Структура не сеется»
      // снято: остановка решающе-обусловленная, зелёный = подтверждено).
      let seedStructureConfirmed = false;
      let seedOk = false;
      try {
        const response = await fetch(progressApiUrl("/trace"), { credentials: "include" });
        if (response.ok) {
          const data = await response.json();
          // AUDIT-3 (план §13): seed -- только из ПОЛНОЙ проекции
          // (projection_complete=false -- историю не выдаёт, отчёт
          // удерживается); stale/unknown факты не воскрешаются (H28).
          if (data?.projection_complete !== false) {
            const nodeStates = Array.isArray(data?.nodes) ? data.nodes : null;
            if (nodeStates) {
              for (const state of nodeStates) {
                if (!state || typeof state !== "object") continue;
                if (state.stage !== "upload") continue;
                if (state.validity !== undefined && state.validity !== "current") continue;
                const nodeId = String(state.node_id) as StopId;
                if (!knownIds.has(nodeId)) continue;
                const status = typeof state.status === "string" ? state.status : null;
                if (!status || !UPLOAD_SEED_STATUSES.has(status)) continue;
                if (status === "done" && nodeId !== "structure") seedViewed.add(nodeId);
                if (status === "done" && nodeId === "structure") seedStructureConfirmed = true;
                seedStatuses[nodeId] = status as CheckStatus;
              }
            } else {
              // Старый бэкенд (поля nodes нет) -- прежний плоский
              // node_statuses (как в EDA).
              const statuses = data?.node_statuses;
              if (statuses && typeof statuses === "object") {
                for (const [key, status] of Object.entries(statuses as Record<string, unknown>)) {
                  if (!key.startsWith("upload/")) continue;
                  const nodeId = key.slice("upload/".length) as StopId;
                  if (!knownIds.has(nodeId) || typeof status !== "string") continue;
                  if (!UPLOAD_SEED_STATUSES.has(status)) continue;
                  if (status === "done" && nodeId !== "structure") seedViewed.add(nodeId);
                  if (status === "done" && nodeId === "structure") seedStructureConfirmed = true;
                  seedStatuses[nodeId] = status as CheckStatus;
                }
              }
            }
            seedOk = true;
          }
        }
      } catch {
        // Seed не получен (сеть/отказ): отчёт удерживается до ретрая (H27).
      }
      if (cancelled) return;
      uploadSeedReadyRef.current = true;
      uploadSeedFailedRef.current = !seedOk;
      setViewedStops((prev) => {
        const merged = new Set(prev);
        seedViewed.forEach((id) => merged.add(id));
        return merged;
      });
      if (seedStructureConfirmed) setStructureConfirmed(true);
      setUploadSeedReady(true);
      setUploadSeedFailed(!seedOk);
      setUploadSeedAnchor(
        seedOk
          ? buildUploadStopsSnapshot({
              overview: seedStatuses.overview ?? "pending",
              chart: seedStatuses.chart ?? "pending",
              distribution: seedStatuses.distribution ?? "pending",
              structure: seedStatuses.structure ?? "pending",
              quality: seedStatuses.quality ?? "pending",
            })
          : null,
      );
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [factsUniverseKey, transformEpoch, uploadSeedRetryTick]);

  // Факт просмотра (UPLOAD-SEM-1, решение тимлида 2026-10-20): остановка
  // активна И её результат показан модулем (EDA PROGR-18: найденные
  // особенности результата НЕ мешают факту просмотра; «Распределение»
  // без числовых колонок и «Качество» без счётчиков результата не
  // показывают -- просмотров не засчитываются). «Структура» --
  // факт-решение, просмотром не сеется. Гейт uploadSeedReadyRef отсекает
  // просмотры мёртвой вселенной в коммите смены датасета (H28). Запись
  // идемпотентна (множество), монотонна в пределах датасета.
  useEffect(() => {
    if (!uploadSeedReadyRef.current) return;
    if (!isUploaded) return;
    const stopId: StopId | null =
      activeStop === "overview"
        ? "overview"
        : activeStop === "chart"
        ? "chart"
        : activeStop === "distribution"
        ? numericCols.length > 0
          ? "distribution"
          : null
        : activeStop === "quality"
        ? uploadData?.quality
          ? "quality"
          : null
        : null;
    if (!stopId) return;
    setViewedStops((prev) => (prev.has(stopId) ? prev : new Set(prev).add(stopId)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  // Reset and a fast seed may batch false -> true without changing ready.
  // Revisit the visible stop after its viewed set is replaced, as in EDA.
  // The prev.has guard preserves Set identity once recorded (no render loop).
  }, [activeStop, isUploaded, numericCols.length, uploadData, uploadSeedReady, viewedStops]);

  // AUDIT-3 (H27): новый просмотр при несостоявшемся seed'е -- ретрай
  // seed'а (успех -- отчёт уходит объединённым снапшотом; неудача --
  // отчёт остаётся удержанным; без новых просмотров отчёт и не нужен).
  const viewedStopsCount = viewedStops.size;
  useEffect(() => {
    if (uploadSeedFailedRef.current && viewedStopsCount > 0) {
      setUploadSeedRetryTick((tick) => tick + 1);
    }
  }, [viewedStopsCount]);

  // ── Статусы остановок степпера (UPLOAD-SEM-1, 2026-10-20, решение тимлида) ──
  // Модуль «Загрузка» -- ознакомительный: он ничего не исправляет и не
  // преобразует (справка модуля), поэтому жёлтый «факт о входных данных»
  // на степпере создавал тупик Наставника («откройте остановку и
  // разберите» -- а разбирать нечем). Новый контракт -- «агентность
  // аналитика»:
  //   * overview/chart/distribution/quality -- done/pending ПО ФАКТУ
  //     ПРОСМОТРА (паттерн EDA PROGR-18: «аналитик открыл и результат
  //     показан»; найденные особенности результата НЕ мешают факту).
  //     Информация о данных не теряется: parse_warnings -- тост при
  //     загрузке + баннер на «Обзоре»; счётчики качества -- на
  //     «Качестве» (честный анонс «Валидации», где есть мастера
  //     исправлений);
  //   * structure -- решающе-обусловленная (UPLOAD-RECOMP-2a, 2026-10-20):
  //     done = ТОЛЬКО явное подтверждение аналитика (structureConfirmed:
  //     кнопка «Подтвердить структуру данных» + POST /date-column
  //     confirmed=true -- связка двух фактов, зеркало structure_confirmed
  //     бэкенда); уверенная детекция БЕЗ подтверждения -- pending «ждёт
  //     подтверждения» (R3); warning = сомнительное угадывание конкретной
  //     колонки (PROGR-14-A), error = UPLOAD-SEM-1 -- авто-детект не
  //     нашёл НИ ОДНОГО правдоподобного кандидата временной колонки
  //     (реальная форма бэкенда: selected="(не использовать)", все score
  //     нулевые) и аналитик ещё не сделал явного выбора (dateColTouched):
  //     структура данных не определяется -- подтвердить вручную или
  //     заменить датасет. Критерий консервативен: сомнительное
  //     угадывание с ненулевым score (Year@40, прецедент FAO) --
  //     по-прежнему warning, нерегулярная сетка при уверенной дате --
  //     pending до подтверждения, легитимный однорядный датасет
  //     («(нет)») -- не error.
  const dateStructureImpossible =
    !!detection &&
    !dateColTouched &&
    !detection.dateCol.candidates.some((c) => c.score > 0);
  // Сомнительное угадывание КОНКРЕТНОЙ колонки (PROGR-14-A, именованное
  // вычисление -- спека §3.1): явный маркер отсутствия («(нет)»/
  // «(не использовать)») -- уверенное решение; raw confidence < 70
  // конкретной колонки -- сомнение.
  const suspicious =
    !!detection &&
    !(isStructureDecisionConfident(detection.dateCol) && isStructureDecisionConfident(detection.entityCol));
  const stopStatus: Record<StopId, CheckStatus> = {
    overview: !isUploaded ? "pending" : viewedStops.has("overview") ? "done" : "pending",
    chart: !isUploaded ? "pending" : viewedStops.has("chart") ? "done" : "pending",
    distribution:
      !isUploaded || numericCols.length === 0
        ? "pending"
        : viewedStops.has("distribution")
        ? "done"
        : "pending",
    structure: !detection
      ? "pending"
      : structureConfirmed
      ? "done"
      : dateStructureImpossible
      ? "error"
      : suspicious
      ? "warning"
      : "pending",
    quality: !uploadData?.quality ? "pending" : viewedStops.has("quality") ? "done" : "pending",
  };
  const doneCount = STOPS.filter((s) => stopStatus[s.id] === "done").length;
  const progressPct = Math.round((doneCount / STOPS.length) * 100);
  const activeStopDef = STOPS.find((s) => s.id === activeStop)!;

  // ── AUDIT-2B: доставка карты остановок в панель «Прогресс» ──
  // ЕДИНЫЙ механизм useProgressMapDelivery (план plan_progress_audit.md
  // §12, контракт docs/progress_audit_contract.md аддендум §20) --
  // замена прежней связки «ref-маркер + один fetch» (PROGR-13-A5):
  //   * v2-конверт AUDIT-2A (schema_version=2 + run_id + context_id +
  //     report_id): биндинг -- наблюдаемый контекст GET
  //     /v1/progress/trace (I3, client bind to observed context);
  //   * идемпотентность по report_id (P07): retry повторяет тот же
  //     ключ и payload, сервер возвращает прежний receipt;
  //   * delivered -- только после receipt; acceptance легаси-режима
  //     (биндинг недоступен) -- честный accepted_legacy;
  //   * ограниченный retry с backoff при сетевом отказе/5xx -- H26
  //     («отказ доставки при неизменном снапшоте») закрыт штатным
  //     механизмом, без сброса ref-а;
  //   * дедуп поставки -- по (run, context, снапшот), НЕ по имени
  //     файла: повторная загрузка одноимённого файла (новый run)
  //     доставляется заново (план §12 п.4);
  //   * поздние/устаревшие ответы изолированы токеном поставки.
  // Статус доставки -- вспомогательный контур (§12 п.8): сбой не ломает
  // модуль и не мешает чтению научного результата; без алертов.
  // UPLOAD-SEM-1: карта доставляется ПОСЛЕ seed'а фактов (remount с
  // пустым множеством просмотров не перезаписывает recorded done);
  // якорь seed'а (uploadSeedAnchor) -- идентичный записанному снапшоту
  // не доставляется повторно (семантика EDA-якоря). При seed-отказе
  // отчёт удерживается (H27) до ретрая по новому просмотру.
  const stopsMap = isUploaded && uploadSeedReady && !uploadSeedFailed ? stopStatus : null;
  const { redeliver: redeliverStops } = useProgressMapDelivery({
    endpoint: "/upload-stops",
    bodyKey: "stops",
    map: stopsMap,
    anchorSnapshot: uploadSeedAnchor,
    // Ключ вселенной фактов: новый датасет (в т.ч. одноимённый файл --
    // новый datasetId) ИЛИ панельное преобразование (transformEpoch --
    // UPLOAD-RECOMP-2 §3.4) -- повторная доставка даже при идентичной
    // картине (план §12 п.4, легаси-фолбэк).
    universeKey: factsUniverseKey,
  });

  // Ре-пост ПОСЛЕ подтверждения структуры: бэкенд пишет свой факт
  // structure_confirmed (узел structure -> done), но модуль может всё ещё
  // показывать warning (сомнительное угадывание) или error -- панель
  // обязана остаться зеркалом модуля: хронология решает (последнее
  // событие узла выигрывает в едином движке node_status). Принудительная
  // повторная поставка текущего снапшота с НОВЫМ report_id (новое
  // клиентское наблюдение). UPLOAD-SEM-1: якорь seed'а снимается --
  // принудительная поставка обязана дойти даже при совпадении снапшота
  // с записанным (после поставки дедуп deliveredKey берёт дубли на себя;
  // при remount seed установит свежий якорь из трассы).
  const reportUploadStopsNow = useCallback(() => {
    if (!isUploaded) return;
    setUploadSeedAnchor(null);
    redeliverStops();
  }, [isUploaded, redeliverStops]);

  // ── UPLOAD-RECOMP-2a: подтверждение структуры аналитиком ────────────
  // Связка двух фактов (спека §3.1): (1) бэкенд -- POST /date-column
  // confirmed=true пишет structure_confirmed (узел upload/structure ->
  // done в едином движке node_status); (2) фронт -- setStructureConfirmed
  // -> done; затем reportUploadStopsNow() (якорь снимается -- зеркальный
  // ре-пост, хронология решает). Отказ бэкенда честный (инлайн + тост):
  // локальный done не ставится -- модуль и панель остаются
  // согласованными. Активность кнопки: конкретная колонка ИЛИ маркер
  // «(не использовать)» после явного выбора (dateColTouched).
  const [structureConfirming, setStructureConfirming] = useState(false);
  const [structureConfirmError, setStructureConfirmError] = useState<string | null>(null);
  const canConfirmStructure =
    !!detection &&
    (detection.dateCol.selected !== "(не использовать)" || dateColTouched);
  const handleConfirmStructure = useCallback(async () => {
    if (!detection || !canConfirmStructure || structureConfirmed || structureConfirming) return;
    setStructureConfirming(true);
    setStructureConfirmError(null);
    try {
      const res = await fetch(sessionApiUrl("/date-column"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ column: detection.dateCol.selected, confirmed: true }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const message =
          (data as { detail?: string } | null)?.detail ??
          `Бэкенд отклонил подтверждение (HTTP ${res.status})`;
        setStructureConfirmError(message);
        toast.error(`Подтверждение не принято: ${message}`);
        return;
      }
      setStructureConfirmed(true);
      reportUploadStopsNow();
    } catch {
      const message = "Сеть недоступна -- подтверждение не доставлено на бэкенд";
      setStructureConfirmError(message);
      toast.error(message);
    } finally {
      setStructureConfirming(false);
    }
  }, [detection, canConfirmStructure, structureConfirmed, structureConfirming, reportUploadStopsNow]);

  // ── UPLOAD-RECOMP-2c: панельные микросервисы (остановка «Структура») ──
  // При структурном классе панели -- блок «Панельные данные: три пути
  // исследования»: (1) фильтр сущности, (2) агрегация по времени --
  // preview/apply по сертифицированному паттерну (payload.apply); (3)
  // пассивный бейдж «Ряд не трансформируем» (дефолт). Молчаливой
  // агрегации нет: любое изменение данных -- только явная кнопка
  // «Применить». После apply -- transformEpoch+1 (новая вселенная
  // фактов), re-detection контура модуля, ре-фетч статистик/превью.
  const isPanelClass =
    !!structuralClass &&
    (structuralClass.id === "panel_balanced" ||
      structuralClass.id === "panel_unbalanced" ||
      structuralClass.id === "panel_unknown");
  const [panelEntityValue, setPanelEntityValue] = useState<string>("");
  const [panelEntityOptions, setPanelEntityOptions] = useState<string[]>([]);
  const [panelEntityPreview, setPanelEntityPreview] = useState<{ n_rows_after: number | null; n_dates: number | null; date_min: string | null; date_max: string | null; frequency: string | null } | null>(null);
  const [panelEntityBusy, setPanelEntityBusy] = useState(false);
  const [panelEntityError, setPanelEntityError] = useState<string | null>(null);
  const PANEL_AGG_FUNCS = ["mean", "sum", "median", "min", "max"] as const;
  const [panelAggFunc, setPanelAggFunc] = useState<(typeof PANEL_AGG_FUNCS)[number]>("mean");
  const [panelAggPreview, setPanelAggPreview] = useState<{ n_rows_after: number | null; n_dates: number | null; n_dates_skipped: number | null; dropped_columns: string[] } | null>(null);
  const [panelAggBusy, setPanelAggBusy] = useState(false);
  const [panelAggError, setPanelAggError] = useState<string | null>(null);

  // Опрос доступных значений сущности (селектор) при появлении блока.
  useEffect(() => {
    if (!isPanelClass || !detection) return;
    let cancelled = false;
    setPanelEntityValue("");
    setPanelEntityPreview(null);
    setPanelEntityError(null);
    fetch(sessionApiUrl("/dataset/entity-filter"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity_col: detection.entityCol.selected, value: null, apply: false }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: { available_values?: string[] }) => {
        if (cancelled) return;
        setPanelEntityOptions(Array.isArray(data?.available_values) ? data.available_values : []);
      })
      .catch(() => {
        if (cancelled) return;
        setPanelEntityOptions([]);
        setPanelEntityError("Не удалось получить список сущностей");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPanelClass, detection?.entityCol.selected]);

  // Preview фильтра по выбранной сущности.
  useEffect(() => {
    if (!isPanelClass || !detection || !panelEntityValue) {
      setPanelEntityPreview(null);
      return;
    }
    let cancelled = false;
    setPanelEntityBusy(true);
    setPanelEntityError(null);
    fetch(sessionApiUrl("/dataset/entity-filter"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity_col: detection.entityCol.selected, date_col: detection.dateCol.selected !== "(не использовать)" ? detection.dateCol.selected : undefined, value: panelEntityValue, apply: false }),
    })
      .then((r) => (r.ok ? r.json() : r.json().catch(() => null).then((d) => Promise.reject(Object.assign(new Error(d?.detail ?? String(r.status)), { detail: d?.detail })))))
      .then((data: { n_rows_after: number | null; n_dates: number | null; date_min: string | null; date_max: string | null; frequency: string | null }) => {
        if (cancelled) return;
        setPanelEntityPreview(data);
      })
      .catch((ex: Error & { detail?: string }) => {
        if (cancelled) return;
        setPanelEntityPreview(null);
        setPanelEntityError(ex.detail ?? "Превью недоступно");
      })
      .finally(() => {
        if (!cancelled) setPanelEntityBusy(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPanelClass, detection?.entityCol.selected, detection?.dateCol.selected, panelEntityValue]);

  // Preview агрегации по функции.
  useEffect(() => {
    if (!isPanelClass || !detection) {
      setPanelAggPreview(null);
      return;
    }
    let cancelled = false;
    setPanelAggBusy(true);
    setPanelAggError(null);
    fetch(sessionApiUrl("/dataset/panel-aggregate"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date_col: detection.dateCol.selected, entity_col: detection.entityCol.selected !== "(нет)" ? detection.entityCol.selected : undefined, func: panelAggFunc, apply: false }),
    })
      .then((r) => (r.ok ? r.json() : r.json().catch(() => null).then((d) => Promise.reject(Object.assign(new Error(d?.detail ?? String(r.status)), { detail: d?.detail })))))
      .then((data: { n_rows_after: number | null; n_dates: number | null; n_dates_skipped: number | null; dropped_columns: string[] }) => {
        if (cancelled) return;
        setPanelAggPreview(data);
      })
      .catch((ex: Error & { detail?: string }) => {
        if (cancelled) return;
        setPanelAggPreview(null);
        setPanelAggError(ex.detail ?? "Превью недоступно");
      })
      .finally(() => {
        if (!cancelled) setPanelAggBusy(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPanelClass, detection?.entityCol.selected, detection?.dateCol.selected, panelAggFunc]);

  // Общая точка после apply любого микросервиса: новая вселенная фактов
  // (transformEpoch+1 -- смена factsUniverseKey сбрасывает просмотры/
  // подтверждение/якорь), re-detection контура детекции, ре-фетч
  // статистик и превью датасета (строки/колонки изменились).
  const handlePanelTransformApplied = useCallback(() => {
    setTransformEpoch((e) => e + 1);
    fetchStructureDetection().then((d) => setDetection(d));
    fetchStats();
    fetch(sessionApiUrl("/dataset"), { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: UploadApiResponse | null) => {
        if (data && data.columns_info) setUploadData(data);
      })
      .catch(() => {
        // Молча: содержательный результат на остановках после ре-фетча.
      });
  }, [fetchStats]);

  const handleApplyEntityFilter = useCallback(async () => {
    if (!detection || !panelEntityValue || panelEntityBusy) return;
    setPanelEntityBusy(true);
    setPanelEntityError(null);
    try {
      const res = await fetch(sessionApiUrl("/dataset/entity-filter"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_col: detection.entityCol.selected, date_col: detection.dateCol.selected !== "(не использовать)" ? detection.dateCol.selected : undefined, value: panelEntityValue, apply: true }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setPanelEntityError((data as { detail?: string } | null)?.detail ?? `Преобразование отклонено (HTTP ${res.status})`);
        return;
      }
      handlePanelTransformApplied();
    } catch {
      setPanelEntityError("Сеть недоступна -- преобразование не применено");
    } finally {
      setPanelEntityBusy(false);
    }
  }, [detection, panelEntityValue, panelEntityBusy, handlePanelTransformApplied]);

  const handleApplyPanelAggregate = useCallback(async () => {
    if (!detection || panelAggBusy) return;
    setPanelAggBusy(true);
    setPanelAggError(null);
    try {
      const res = await fetch(sessionApiUrl("/dataset/panel-aggregate"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date_col: detection.dateCol.selected, entity_col: detection.entityCol.selected !== "(нет)" ? detection.entityCol.selected : undefined, func: panelAggFunc, apply: true }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setPanelAggError((data as { detail?: string } | null)?.detail ?? `Преобразование отклонено (HTTP ${res.status})`);
        return;
      }
      handlePanelTransformApplied();
    } catch {
      setPanelAggError("Сеть недоступна -- преобразование не применено");
    } finally {
      setPanelAggBusy(false);
    }
  }, [detection, panelAggFunc, panelAggBusy, handlePanelTransformApplied]);
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
              <RefreshCw size={12} aria-hidden="true" /> {source === "db" ? "Сменить источник" : "Сменить файл"}
            </button>
          )}
        </div>

        {!isUploaded ? (
          <>
            <div className="grid grid-cols-2 gap-4">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" checked={source === "file"} disabled={uploading || hydrating} onChange={() => { setSource("file"); setUploadError(null); }} className="accent-brand" />
                Файл .xlsx, .xls, .csv, .json
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" checked={source === "db"} disabled={uploading || hydrating} onChange={() => { setSource("db"); setUploadError(null); }} className="accent-brand" />
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
              <DbConnectionForm onLoaded={(data) => acceptUploadedData(data, true)} onBusyChange={setUploading} disabled={hydrating} />
            )}

            {/* ── Демо-датасеты (2026-08-19, согласовано с тимлидом) ──
                Для знакомства с платформой без своего файла -- готовые
                синтетические датасеты, каждый другой структурный класс
                и отрасль. С 2026-09-16 ПЕРВЫЙ -- forecast monitor
                (выбросы + пропуски, быстрый мониторинг «Прогнозирования»,
                см. FC-MON-2). Идут через ТОТ ЖЕ doUpload(file), что и
                drag-and-drop -- реальный пайплайн парсинга/детекции/
                валидации, не имитация (см. packages/ui/lib/demoDatasets.ts). */}
            {source === "file" && !uploading && !hydrating && (
              <div className="mt-5 pt-4 border-t border-neutral-200">
                <p className="text-xs text-neutral-500 mb-2">
                  Нет своего датасета под рукой? Загрузите один из демо-наборов, чтобы познакомиться с платформой:
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-4 gap-2">
                  {DEMO_DATASETS.map((ds) => (
                    <button
                      key={ds.id}
                      type="button"
                      data-testid={`demo-dataset-${ds.id}`}
                      onClick={() => {
                        const file = demoDatasetToFile(ds);
                        setFileName(file.name);
                        doUpload(file);
                      }}
                      className="text-left border border-neutral-200 rounded-lg p-3 hover:border-brand hover:bg-brand-light transition-colors"
                    >
                      <span className="text-[10px] uppercase tracking-wide text-neutral-400">{ds.industry}</span>
                      <p className="text-sm font-medium text-neutral-800 mt-0.5">{ds.name}</p>
                      <span className="inline-block text-[10px] px-1.5 py-0.5 rounded bg-neutral-100 text-neutral-600 mt-1">
                        {ds.structuralClassLabel}
                      </span>
                      <p className="text-[11px] text-neutral-500 mt-1.5">{ds.description}</p>
                      <p className="text-[10px] text-neutral-400 mt-1">{ds.rowsLabel}</p>
                    </button>
                  ))}
                </div>
              </div>
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
        <>
          <div className="flex gap-6">
          {/* ── ЛЕВАЯ КОЛОНКА: заголовок + признак + прогресс + степпер ── */}
          {/* Заголовки трёх колонок -- единый вид (2026-10-14, постановка
              тимлида): (1) размер шрифта -- text-lg, как у заголовка
              «Загрузка» (был рассинхрон: «Описание»/«Файл» и переменные
              заголовки правой колонки рендерились дефолтным text-base);
              (2) низы заголовков на одной горизонтали -- строка заголовка
              первая ветка КАЖДОЙ колонки, офсет pt-1 левой колонки убран,
              высоты строк детерминированы одинаково (text-lg line box
              28px, items-center, иконка 16px). Структурный паттерн --
              заголовки секции «Примеры прикладных задач» страницы
              «Знакомство с платформой» (AppliedTasksNavigator): строка
              flex items-center gap-2 + lucide-иконка (size 16, text-brand,
              aria-hidden) + заголовок font-semibold text-neutral-800.
              Пин контракта: upload-column-headers-unified.test.tsx. */}
          <aside className="w-60 shrink-0 flex flex-col gap-3">
            <div className="mb-1">
              {/* Кнопка «Справка» (UI-UPLOAD-HELP-1, паттерн «Валидации»):
                  в строке заголовка колонки, shrink-0 -- геометрия единого
                  вида заголовков не меняется (line box задаёт text-lg).
                  Выравнивание (UI-UPLOAD-FULL-1, постановка тимлида):
                  кнопка -- У ПРАВОГО КРАЯ колонки, как в «Валидации»
                  (Data Quality -> Справка, строка justify-between). В
                  строке из трёх элементов [иконка, h2, кнопка] прямой
                  justify-between раскидал бы все три по ширине, поэтому
                  правый край достигается растяжением h2 (flex-1, min-w-0
                  -- защита узкой колонки сохранена): кнопка остаётся
                  последним элементом строки, прижатым вправо. */}
              <div className="flex items-center gap-2">
                <Upload size={16} className="text-brand" aria-hidden="true" />
                <h2 className="text-lg font-semibold text-neutral-800 truncate min-w-0 flex-1">Загрузка</h2>
                <button
                  onClick={handleHelpClick}
                  data-testid="upload-help-btn"
                  className={`shrink-0 text-xs px-2 py-1 rounded transition-colors ${
                    descriptionSection === "help"
                      ? "bg-brand text-white"
                      : "bg-brand-light text-neutral-700 hover:bg-brand-light/80"
                  }`}
                >
                  Справка
                </button>
              </div>
              <p className="text-[11px] text-neutral-500 mt-0.5">Проверка и структура датасета</p>
            </div>

            {numericCols.length > 0 && (
              <div>
                <label className="text-[11px] text-neutral-500 block mb-1">Исследуемый признак:</label>
                {/* PROGR-25-B: при незафиксированном признаке селектор
                    показывает РЕКОМЕНДАЦИЮ бэкенда (suggested_column --
                    первый кандидат единого правила), а не просто первую
                    числовую датафрейма; отображение не персистится --
                    фиксация только явным выбором в списке. */}
                <select
                  value={selectedFeature ?? suggestedColumn ?? numericCols[0]}
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
              {/* Паттерн «Моделирования» (эталон TsAnalysisModeling; уже применён
                  к EDA/Предобработке/Валидации): пройденная остановка (зелёная
                  галочка, status done) подсвечивается светло-зелёным с зелёным
                  текстом; при других статусах (warning/pending) кнопка не
                  окрашивается. Активная остановка сохраняет приоритет индиго,
                  как в эталоне. */}
              {STOPS.map((stop) => (
                <button
                  key={stop.id}
                  onClick={() => {
                    // Инвариант информативности (UI-UPLOAD-HELP-1, паттерн
                    // «Валидации»): переключение остановки закрывает Справку
                    // и показывает описание НОВОЙ остановки; клик по УЖЕ
                    // активной остановке открытую Справку сохраняет.
                    if (stop.id !== activeStop) {
                      setActiveStop(stop.id);
                      setDescriptionSection("stop");
                    }
                  }}
                  className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition-colors ${
                    stop.id === activeStop
                      ? "bg-brand text-white border-brand"
                      : stopStatus[stop.id] === "done"
                      ? "bg-green-50 border-green-200 text-green-800"
                      : "bg-white border-neutral-200 hover:bg-neutral-50 text-neutral-800"
                  }`}
                >
                  <span className="truncate">{stop.label}</span>
                  <span className="ml-2 shrink-0">
                    <StatusIcon status={stopStatus[stop.id]} />
                  </span>
                </button>
              ))}
              <StepperNextModuleButton label="Перейти к валидации" href="/validation" />
            </div>
          </aside>

          {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: Описание + Обзор ("лобовое стекло") ── */}
          <section className="flex-1 min-w-0">
            <div className="mb-5">
              <div className="flex items-center gap-2 mb-4">
                <Info size={16} className="text-brand" aria-hidden="true" />
                <h3 className="text-lg font-semibold text-neutral-800">Описание</h3>
              </div>
              {/* Режим «Справка» (UI-UPLOAD-HELP-1): подзаголовок режима +
                  развёрнутое описание модуля из единого реестра справки;
                  многострочный текст сохраняет переводы строк (whitespace-pre-wrap)
                  и скроллится -- паттерн окна «Описание» «Валидации». */}
              {descriptionSection === "help" && (
                <p className="text-xs text-neutral-500 mb-2" data-testid="upload-help-subtitle">
                  Справка по модулю «Загрузка»
                </p>
              )}
              <div
                className={`rounded-lg border border-neutral-200 bg-brand-light/50 px-4 py-3 text-sm text-neutral-600 whitespace-pre-wrap overflow-y-auto max-h-[280px] ${
                  descriptionSection === "help" ? "" : "min-h-[90px]"
                }`}
              >
                {descriptionSection === "help"
                  ? describeNode("upload", null, "module_help")?.text ?? (
                      <span className="text-neutral-400 italic">
                        Справка по модулю готовится
                      </span>
                    )
                  : activeStopDef.description}
              </div>
            </div>

            <div>
              {/* Заголовок окна «Обзор» -- единый паттерн заголовков layout
                  страницы (UI-UPLOAD-HDR-1): flex items-center gap-2 + иконка
                  16 text-brand aria-hidden + text-lg font-semibold neutral-800. */}
              <div className="flex items-center gap-2 mb-1">
                <Eye size={16} className="text-brand" aria-hidden="true" />
                <h3 className="text-lg font-semibold text-neutral-800">Обзор: {activeStopDef.label}</h3>
              </div>
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
                    {/* «Весь датасет» (UI-UPLOAD-FULL-1, постановка тимлида):
                        прокрутка ВСЕГО датасета от начала до конца, ползунок
                        справа размечен на все total_rows (виртуализация по
                        позиции прокрутки, страницы строк -- GET /dataset/rows). */}
                    <button
                      onClick={() => setOverviewTab("full")}
                      className={`text-xs px-3 py-1.5 rounded-t border-b-2 transition-colors ${
                        overviewTab === "full" ? "border-brand text-brand font-medium" : "border-transparent text-neutral-500 hover:text-neutral-800"
                      }`}
                    >
                      <Table size={12} className="inline mr-1" aria-hidden="true" />
                      Весь датасет
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    {overviewTab === "preview" && (
                      <VisualExportButton viewId="upload.overview.preview" label="Скачать PNG: превью датасета" compact />
                    )}
                    {overviewTab === "columns" && (
                      <VisualExportButton viewId="upload.overview.tech_table" label="Скачать PNG: типы колонок" compact />
                    )}
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
                  ) : overviewTab === "columns" ? (
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
                  ) : (
                    /* ── «Весь датасет» (UI-UPLOAD-FULL-1) ──
                       Виртуализированная сетка: ползунок контейнера
                       размечен на ВСЕ строки (spacer = шапка +
                       total*ROW_H), по позиции прокрутки рендерится
                       только видимое окно (± overscan), страницы строк
                       догружаются с /dataset/rows. Шапка закреплена
                       (sticky), ячейки однострочные (truncate + title),
                       строки одной высоты -- геометрия окна детерминирована. */
                    <div data-testid="full-dataset-panel">
                      {!fullMeta && fullPending > 0 && !fullError && (
                        <div className="h-48 flex flex-col items-center justify-center gap-2 text-neutral-500">
                          <Loader2 size={20} className="animate-spin text-brand" aria-hidden="true" />
                          <p className="text-xs">Загружаем строки датасета…</p>
                        </div>
                      )}

                      {fullError && (
                        <div
                          data-testid="full-rows-error"
                          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 flex items-center justify-between gap-3"
                        >
                          <p className="text-sm text-red-700">{fullError}</p>
                          <button
                            data-testid="full-rows-retry"
                            onClick={() => setFullError(null)}
                            className="shrink-0 text-xs px-2 py-1 rounded bg-white border border-red-300 text-red-700 hover:bg-red-100 transition-colors"
                          >
                            Повторить
                          </button>
                        </div>
                      )}

                      {fullMeta && fullMeta.totalRows === 0 && (
                        <p className="text-sm text-neutral-500 bg-neutral-50 rounded-lg p-4">
                          Датасет не содержит строк.
                        </p>
                      )}

                      {fullMeta && fullMeta.totalRows > 0 && (
                        <>
                          <div
                            data-testid="full-scroll-container"
                            onScroll={handleFullScroll}
                            className="overflow-auto border border-neutral-200 rounded-lg"
                            style={{ height: FULL_VIEWPORT_H }}
                          >
                            {/* Spacer: высота = шапка + ВСЕ строки -- ползунок
                                размечен на весь датасет от начала до конца. */}
                            <div
                              data-testid="full-rows-spacer"
                              className="relative"
                              style={{
                                height: FULL_HEADER_H + fullTotal * FULL_ROW_H,
                                width: "max-content",
                                minWidth: "100%",
                              }}
                            >
                              {/* Закреплённая шапка колонок */}
                              <div
                                data-testid="full-rows-header"
                                className="sticky top-0 z-10 grid bg-neutral-50 border-b border-neutral-200 text-[11px] text-neutral-500 uppercase"
                                style={{
                                  height: FULL_HEADER_H,
                                  gridTemplateColumns: fullGridTemplate(fullMeta.columns.length),
                                  width: "max-content",
                                  minWidth: "100%",
                                }}
                              >
                                <div className="flex items-center justify-end px-2 font-medium">№</div>
                                {fullMeta.columns.map((colName) => (
                                  <div key={colName} className="flex items-center px-3 font-medium truncate" title={colName}>
                                    {colName}
                                  </div>
                                ))}
                              </div>

                              {/* Видимое окно строк (абсолютное позиционирование
                                  по ползунку; страницы вне кэша честно пусты --
                                  место зарезервировано, статус -- в строке ниже) */}
                              <div
                                data-testid="full-rows-window"
                                className="absolute left-0"
                                style={{
                                  top: FULL_HEADER_H + fullStart * FULL_ROW_H,
                                  width: "max-content",
                                  minWidth: "100%",
                                }}
                              >
                                {fullVisibleRows.map(({ rowIndex, values }) => (
                                  <div
                                    key={rowIndex}
                                    data-row-index={rowIndex}
                                    className={`grid border-b border-neutral-100 ${
                                      rowIndex % 2 === 1 ? "bg-neutral-50/60" : "bg-white"
                                    }`}
                                    style={{
                                      height: FULL_ROW_H,
                                      gridTemplateColumns: fullGridTemplate(values.length),
                                    }}
                                  >
                                    <div className="flex items-center justify-end px-2 text-[11px] text-neutral-400 tabular-nums">
                                      {rowIndex + 1}
                                    </div>
                                    {values.map((cellValue, j) => (
                                      <div key={j} className="flex items-center px-3 text-xs truncate" title={cellValue}>
                                        {cellValue}
                                      </div>
                                    ))}
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>

                          {/* Честный статус окна прокрутки */}
                          <p data-testid="full-rows-footer" className="text-[11px] text-neutral-500 mt-1.5">
                            Строки {fullStart + 1}–{fullEnd} из {formatNum(fullTotal)}
                            {fullPending > 0 ? " · догружаем…" : ""}
                          </p>
                        </>
                      )}
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
                      <VisualExportChartScope viewId="upload.chart.series" label="линейный график признака">
                        <TimeSeriesLineChart data={timeseries} loading={timeseriesLoading} />
                      </VisualExportChartScope>
                      <div className="mt-4">
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <h4 className="text-xs font-semibold text-neutral-600">Декомпозиция</h4>
                          <VisualExportButton viewId="upload.chart.decomposition_shares" label="Скачать PNG: доли компонент" compact />
                        </div>
                        <p className="text-[11px] text-neutral-500 mb-2">
                          Доля дисперсии ряда, объяснимая каждой компонентой (Тренд/Сезонность/Цикличность/Остаток) — не абсолютные величины, а вклад в % от общей изменчивости.
                        </p>
                        <DecompositionBadges
                          data={decomposition}
                          loading={decompositionLoading}
                          onCompute={fetchDecomposition}
                          hasComputed={decompositionRequested}
                        />
                        {decompositionRequested && (
                          <div className="mt-3">
                            <VisualExportChartScope viewId="upload.chart.decomposition_series" label="компоненты декомпозиции">
                              <DecompositionSeriesChart data={decompositionSeries} loading={decompositionLoading} />
                            </VisualExportChartScope>
                          </div>
                        )}
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
                              <VisualExportChartScope viewId="upload.distribution.scatter" label="точечный график">
                                <ScatterDistributionChart data={distribution} />
                              </VisualExportChartScope>
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
                            <VisualExportChartScope viewId="upload.distribution.histogram" label="гистограмма">
                              <HistogramDistributionChart data={distribution} />
                            </VisualExportChartScope>
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
                            <VisualExportChartScope viewId="upload.distribution.kde" label="KDE">
                              <KdeDistributionChart data={distribution} />
                            </VisualExportChartScope>
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
                      onChange={(e) => { setDateColTouched(true); setStructureConfirmed(false); setDetection({ ...detection, dateCol: { ...detection.dateCol, selected: e.target.value } }); }}
                      className="w-full border border-neutral-300 rounded px-2 py-1.5 text-sm font-medium"
                    >
                      {detection.dateCol.candidates.map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                      <option value="(не использовать)">(не использовать)</option>
                    </select>
                    {dateStructureImpossible && (
                      <p className="mt-2 text-xs bg-red-50 border border-red-200 text-red-700 rounded px-2 py-1.5">
                        Авто-детект не нашёл ни одного правдоподобного кандидата во временную колонку — подтвердите выбор вручную или замените датасет.
                      </p>
                    )}
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
                      onChange={(e) => { setStructureConfirmed(false); setDetection({ ...detection, entityCol: { ...detection.entityCol, selected: e.target.value } }); }}
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
                      onChange={(e) => { setStructureConfirmed(false); setDetection({ ...detection, freq: { ...detection.freq, selected: e.target.value } }); }}
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

                  {/* ── UPLOAD-RECOMP-2c: панельные микросервисы ── */}
                  {isPanelClass && structuralClass && (
                    <div className="md:col-span-3 border border-neutral-200 rounded-lg p-4" data-testid="panel-paths-block">
                      <div className="flex items-center gap-2 mb-1">
                        <Layers size={14} className="text-brand" aria-hidden="true" />
                        <span className="text-xs font-medium text-neutral-500 uppercase tracking-wide">Панельные данные: три пути исследования</span>
                      </div>
                      <p className="text-xs text-neutral-500 mb-3">
                        Все преобразования рядов платформа выполняет внутри себя — выберите путь под исследовательский вопрос.
                      </p>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        {/* Микросервис 1: Фильтр сущности */}
                        <div className="border border-neutral-200 rounded-lg p-3 flex flex-col">
                          <p className="text-sm font-semibold text-neutral-800">Фильтр сущности</p>
                          <p className="text-xs text-neutral-600 mt-1 mb-2">
                            Оставить в датасете строки только одной сущности (например, один регион). Панель превращается в обычный временной ряд —
                            открываются декомпозиция, ACF/PACF, классические модели и прогноз. Используйте, когда исследовательский вопрос про конкретную сущность.
                          </p>
                          <select
                            data-testid="panel-entity-select"
                            value={panelEntityValue}
                            onChange={(e) => setPanelEntityValue(e.target.value)}
                            className="w-full border border-neutral-300 rounded px-2 py-1 text-xs font-medium mb-2"
                            aria-label="Значение сущности для фильтра"
                          >
                            <option value="">— выберите сущность —</option>
                            {panelEntityOptions.map((v) => (
                              <option key={v} value={v}>
                                {v}
                              </option>
                            ))}
                          </select>
                          {panelEntityError && (
                            <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1 mb-2">{panelEntityError}</p>
                          )}
                          {panelEntityPreview && (
                            <p className="text-xs text-neutral-500 mb-2" data-testid="panel-entity-preview">
                              Превью: строк {panelEntityPreview.n_rows_after ?? "—"}
                              {panelEntityPreview.n_dates != null ? ` · дат ${panelEntityPreview.n_dates}` : ""}
                              {panelEntityPreview.date_min ? ` · ${panelEntityPreview.date_min} … ${panelEntityPreview.date_max ?? ""}` : ""}
                              {panelEntityPreview.frequency ? ` · ${panelEntityPreview.frequency}` : ""}
                            </p>
                          )}
                          <Button
                            data-testid="panel-entity-apply"
                            onClick={handleApplyEntityFilter}
                            disabled={!panelEntityValue || panelEntityBusy}
                            className="mt-auto w-full text-xs"
                          >
                            {panelEntityBusy ? "Применяяем…" : "Применить"}
                          </Button>
                        </div>

                        {/* Микросервис 2: Агрегация по времени */}
                        <div className="border border-neutral-200 rounded-lg p-3 flex flex-col">
                          <p className="text-sm font-semibold text-neutral-800">Агрегация по времени</p>
                          <p className="text-xs text-neutral-600 mt-1 mb-2">
                            Для каждой даты усреднить (или просуммировать) значения по всем сущностям. Панель превращается в один агрегированный ряд.
                            Используйте, когда исследовательский вопрос про совокупность целиком; суммирование — только для аддитивных величин (объёмы),
                            для уровней (цены, индексы) — среднее.
                          </p>
                          <select
                            data-testid="panel-agg-select"
                            value={panelAggFunc}
                            onChange={(e) => setPanelAggFunc(e.target.value as (typeof PANEL_AGG_FUNCS)[number])}
                            className="w-full border border-neutral-300 rounded px-2 py-1 text-xs font-medium mb-2"
                            aria-label="Функция агрегации"
                          >
                            {PANEL_AGG_FUNCS.map((f) => (
                              <option key={f} value={f}>
                                {f === "mean" ? "mean — среднее" : f === "sum" ? "sum — сумма" : f === "median" ? "median — медиана" : f === "min" ? "min — минимум" : "max — максимум"}
                              </option>
                            ))}
                          </select>
                          {panelAggError && (
                            <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1 mb-2">{panelAggError}</p>
                          )}
                          {panelAggPreview && (
                            <p className="text-xs text-neutral-500 mb-2" data-testid="panel-agg-preview">
                              Превью: дат {panelAggPreview.n_dates ?? "—"}
                              {panelAggPreview.n_dates_skipped != null ? ` · отброшено без значений: ${panelAggPreview.n_dates_skipped}` : ""}
                              {panelAggPreview.dropped_columns?.length ? ` · удалены колонки: ${panelAggPreview.dropped_columns.join(", ")}` : ""}
                            </p>
                          )}
                          <Button
                            data-testid="panel-agg-apply"
                            onClick={handleApplyPanelAggregate}
                            disabled={panelAggBusy}
                            className="mt-auto w-full text-xs"
                          >
                            {panelAggBusy ? "Применяяем…" : "Применить"}
                          </Button>
                        </div>

                        {/* Альтернатива 3: пассивный бейдж (дефолт) */}
                        <div className="border border-neutral-200 rounded-lg p-3 bg-neutral-50" data-testid="panel-badge">
                          <p className="text-sm font-semibold text-neutral-800">Ряд не трансформируем, исследуем панельные данные</p>
                          <p className="text-xs text-neutral-600 mt-1">
                            Панель сохраняется как есть. Доступно: по-сущностные проверки «Валидации» (регулярность, достаточность), панельная проверка
                            баланса. Панельные модели исследования и прогноза (контур PANEL-MODELS-3) доступны в «Моделировании»; классические
                            однорядные модели к панели неприменимы без сведения к одному ряду.
                          </p>
                        </div>
                      </div>
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
                    <div className="col-span-2 md:col-span-4">
                      <VisualExportButton viewId="upload.quality.teaser" label="Скачать PNG: показатели качества" compact />
                    </div>
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
                <div className="flex items-center gap-2 mb-4">
                  <FileText size={16} className="text-brand" aria-hidden="true" />
                  <h3 className="text-lg font-semibold text-neutral-800">Файл</h3>
                </div>
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
                <div className="flex items-center gap-2 mb-4">
                  <BarChart3 size={16} className="text-brand" aria-hidden="true" />
                  <h3 className="text-lg font-semibold text-neutral-800">Зачем это здесь</h3>
                </div>
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
                <div className="flex items-center gap-2 mb-4">
                  <Activity size={16} className="text-brand" aria-hidden="true" />
                  <h3 className="text-lg font-semibold text-neutral-800">Зачем это здесь</h3>
                </div>
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
                <div className="flex items-center gap-2 mb-4">
                  <Calendar size={16} className="text-brand" aria-hidden="true" />
                  <h3 className="text-lg font-semibold text-neutral-800">Подтверждение</h3>
                </div>
                {structureConfirmed ? (
                  <>
                    <p
                      className="text-sm bg-green-50 border border-green-200 text-green-800 rounded px-3 py-2 mb-3"
                      data-testid="structure-confirmed-note"
                    >
                      Структура подтверждена — факт structure_confirmed передан панели «Прогресса».
                    </p>
                    <p className="text-xs text-neutral-500">
                      Изменение селекторов даты, группировки или частоты сбрасывает подтверждение — подтвердите заново той же кнопкой.
                    </p>
                  </>
                ) : (
                  <>
                    <p className="text-sm text-neutral-600 mb-3">
                      Подтвердите определение структуры (временная колонка, группировка, частота). Факт пишется на бэкенде (structure_confirmed)
                      и доставляется панели «Прогресса». Явное подтверждение принимает колонку даже при низкой оценке детектора — ответственность
                      за выбор остаётся за вами.
                    </p>
                    {structureConfirmError && (
                      <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2 mb-3">{structureConfirmError}</p>
                    )}
                    <Button
                      onClick={handleConfirmStructure}
                      disabled={!canConfirmStructure || structureConfirming}
                      className="w-full"
                      data-testid="confirm-structure-button"
                    >
                      {structureConfirming ? "Подтверждаем…" : "Подтвердить структуру данных"}
                    </Button>
                    {!canConfirmStructure && (
                      <p className="text-xs text-neutral-500 mt-2">
                        Сначала сделайте явный выбор временной колонки (или маркера «(не использовать)») в селекторе слева.
                      </p>
                    )}
                  </>
                )}
              </article>
            )}

            {activeStop === "quality" && uploadData!.quality && (
              <article>
                <div className="flex items-center gap-2 mb-4">
                  <ArrowRight size={16} className="text-brand" aria-hidden="true" />
                  <h3 className="text-lg font-semibold text-neutral-800">Что дальше</h3>
                </div>
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
          <DatasetPassportPanel
            stage="start"
            targetColumn={selectedFeature}
            suggestedDateColumn={confidentDateCol}
            onDateColumnConfirmed={reportUploadStopsNow}
            historyResetNotice={passportResetNotice
              ? `Смена исследуемого признака «${passportResetNotice.previousColumn}» → «${passportResetNotice.newColumn}» сбросила цепочку паспортов.`
              : null}
          />
        </>
      )}
    </div>
  );
}
