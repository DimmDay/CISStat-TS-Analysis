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
//
// UI-FORECAST-HDR-1 (2026-10-15): заголовки колонок 3-колоночного layout
// («Forecasting», «Описание этапа», «Панель управления») приведены к
// единому виду по паттерну UI-PREPR-HDR-1 «Предобработки»
// (UI-VALIDATION-HDR-1 «Валидации» / UI-UPLOAD-HDR-1 «Загрузки» /
// UI-EDA-HDR-1 EDA / UI-MODELING-HDR-1 «Моделирования»): строка
// flex items-center gap-2 + lucide-иконка (TrendingUp/Info/Settings,
// size 16, text-brand, aria-hidden) + заголовок text-lg font-semibold
// text-neutral-800; низы заголовков колонок на одной горизонтали (pt-1
// обеих aside убран). Заголовок левой колонки «Прогнозирование» заменён
// на «Forecasting» по прямому указанию тимлида (прецедент UI-EDA-HDR-2;
// модульное имя на других поверхностях не менялось). Отличия лейаута
// учтены: (1) круглая кнопка справки «?» сохраняла свой дизайн (не
// заголовок), строке передан shrink-0; (2) «Панель управления» поднят из
// h4 text-sm первой карточки control-panel на уровень колонки (строка
// -- первая ветка aside), текст сохранён. Пин контракта:
// forecasting-column-headers-unified.test.tsx.
//
// UI-FORECAST-HELP-1 (2026-10-15): три правки по паттерну EDA
// (TsAnalysisEDA.tsx, эталон): (1) круглая «?» левой колонки заменена
// текстовой кнопкой «Справка» (text-xs px-2 py-1 rounded
// transition-colors; active bg-brand text-white / inactive
// bg-brand-light text-neutral-700 hover:bg-brand-light/80; toggle --
// второй клик возвращает к описанию этапа, зеркально EDA-2; testid
// forecasting-help-btn СОХРАН -- пины двух сюитов; aria-label снят --
// доступное имя по видимому тексту, паритет с EDA); (2) шрифт текста
// окна «Описание этапа» text-xs → text-sm (паттерн EDA «text-sm
// text-neutral-600», геометрия 220px не тронута); (3) шеврон окна по
// паттерну EDA: сворачивание -- sticky bottom-0 ВНУТРИ развёрнутого
// бокса (desc-collapse-btn, прилипает к НИЗУ окна; прежде единый
// toggle desc-toggle-btn сидел absolute bottom-1 внешней обёртки --
// при развёрнутом окне визуально «вверху»), разворачивание --
// absolute bottom-1 только при переполнении (desc-expand-btn;
// hasOverflow: ref + ResizeObserver, scrollHeight > clientHeight + 2 --
// перенос EDA :1311-1322). Click-outside и сворачивание при смене
// секции (EDA :1269-1284) -- вне скоупа постановки. Пин контракта:
// forecasting-help-eda-pattern.test.tsx.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
// Иконки заголовков layout (UI-FORECAST-HDR-1, паттерн UI-PREPR-HDR-1
// «Предобработки» / серия UI-*-HDR): TrendingUp -- левая колонка
// («прогнозирование» -- продолжение ряда в будущее; семантически
// отличима от FileText «Загрузки», ShieldCheck «Валидации»,
// SlidersHorizontal «Предобработки», Telescope EDA, FlaskConical
// «Моделирования»), Info -- блок «Описание этапа» (как во всех
// вкладках), Settings -- «Панель управления» (тот же значок, что во
// всех вкладках серии). Плюс прежние AlertTriangle/ChevronDown/
// ChevronUp/Loader2/Play/RefreshCw/Wand2 (предупреждения, шевроны,
// спиннеры, запуск, обновление, веер). TrendingUp/Info/Settings
// присутствуют в lucide-react 0.427.0 (проверено node-пробой).
import { AlertTriangle, ChevronDown, ChevronUp, Loader2, Play, RefreshCw, Wand2, TrendingUp, Info, Settings } from "lucide-react";
import { Button } from "./Button";
import { getApiBase } from "../lib/apiClient";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  Legend as RechartsLegend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { StepperNextModuleButton } from "./StepperNextModuleButton";
import { ForecastChart } from "./ForecastChart";
import { ForecastAccuracyPanel } from "./ForecastAccuracyPanel";
import { ForecastHistoryList } from "./ForecastHistoryList";
import { ForecastExportMenu } from "./ForecastExportMenu";
import { useAppShell } from "../context/AppShellContext";
import { describeNode } from "../lib/knowledge/knowledge";
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
  // PROGR-4 (§6.1): addLogEntry удалён -- факты построения/сравнения/
  // экспорта прогнозов пишутся в трассу бэкендом (ForecastRun.trace,
  // make_trace_event, PROGR-1; унификация с панелью -- PROGR-5).
  const { activeDataset, stages, refreshSession } = useAppShell();

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
  // Переполнение окна описания (UI-FORECAST-HELP-1, паттерн EDA):
  // expand-шеврон показывается только когда контент не влезает в 220px.
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

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

  // FORECAST-GATE-1 (2026-09-23): монтирование вкладки = пересинхронизация
  // stages с сервером (GET /v1/session/current), паттерн PREPR-4 (TasksHub).
  // Провайдер AppShell (layout) НЕ ремоунтится при клиентской навигации:
  // после завершения «Моделирования» (create_model_card ->
  // set_stage("modeling","done") на бэкенде) и перехода «Перейти к
  // прогнозированию» контекст отдавал устаревший stages["modeling"] с
  // момента F5/upload — гейт no-modeling держал плейсхолдер «Завершите
  // этап Моделирование» и disabled «Построить прогноз» до перезагрузки
  // страницы. Сервер — источник истины о stages (контракт AppShellContext),
  // refreshSession стабилен (useCallback) — эффект выполняется один раз
  // на монтирование, без циклов.
  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

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
      setForecasts((previous) => [...previous, run]);
      setActiveForecastId(run.forecast_id);
      setDescriptionSection("main");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "Ошибка построения прогноза";
      setError(message);
    } finally {
      setBusy(null);
    }
  }, [selectedCardId, horizon, alpha]);

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
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Ошибка сравнения");
    } finally {
      setBusy(null);
    }
  }, [selectedForCompare]);

  const runSensitivity = useCallback(async () => {
    if (!activeForecast) return;
    setBusy("sensitivity");
    setError(null);
    try {
      const updated = await computeSensitivity(activeForecast.forecast_id);
      setForecasts((previous) =>
        previous.map((run) => (run.forecast_id === updated.forecast_id ? updated : run)),
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Ошибка расчёта чувствительности");
    } finally {
      setBusy(null);
    }
  }, [activeForecast]);

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

  // Описание этапа и «Справка» — из единого реестра справки (Шаг 3,
  // ревизия 2026-09-22: describeNode по (stage_id, node_id, facet);
  // паритет миграции застрахован фиксстурой help-parity.fixture.json, §13)
  const descriptionContent =
    descriptionSection === "help"
      ? (describeNode("forecasting", null, "module_help")?.text ?? "")
      : (describeNode("forecasting", null, "stage_overview")?.text ?? "");

  // ── Overflow detection для expandable description (UI-FORECAST-HELP-1,
//    паттерн EDA -- перенос TsAnalysisEDA.tsx :1311-1322) ──
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

  // Справка -- toggle по паттерну EDA (EDA-2, «инвариант
  // информативности»): закрытие возвращает к описанию этапа.
  const handleHelpClick = () => {
    setDescriptionSection((prev) => (prev === "help" ? "main" : "help"));
  };

  // ── Рендер ──
  return (
    <div className="flex gap-6">
      {/* ══ ЛЕВАЯ КОЛОНКА ══ */}
      {/* Офсет pt-1 УБРАН (UI-FORECAST-HDR-1): строка заголовка -- первая
          ветка колонки, низы заголовков трёх колонок на одной горизонтали
          (как во всех вкладках серии UI-*-HDR). */}
      <aside className="w-60 shrink-0 flex flex-col gap-3">
        {/* Единый вид заголовков (UI-FORECAST-HDR-1, паттерн
            UI-PREPR-HDR-1 / серия UI-*-HDR): строка flex items-center
            gap-2 + иконка TrendingUp («прогнозирование» -- продолжение
            ряда в будущее, size 16, text-brand, aria-hidden) + h2 text-lg
            font-semibold text-neutral-800 «Forecasting» (переименование
            «Прогнозирование» -- прямой пункт постановки, прецедент
            UI-EDA-HDR-2; растяжение flex-1 min-w-0 прижимает кнопку
            справки к правому краю узкой колонки -- раньше здесь был
            justify-between без иконки, font-bold text-neutral-900;
            truncate -- защита узкой колонки). Текстовая кнопка «Справка» --
            паттерн EDA (UI-FORECAST-HELP-1; прежде круглая «?», чей
            дизайн сохранялся до отдельной постановки): toggle-семантика
            (второй клик закрывает справку), активное состояние
            bg-brand text-white; строке передан shrink-0. Пины:
            forecasting-column-headers-unified.test.tsx (состав строки),
            forecasting-help-eda-pattern.test.tsx (кнопка). */}
        <div className="mb-1">
          <div className="flex items-center gap-2">
            <TrendingUp size={16} className="text-brand" aria-hidden="true" />
            <h2 className="text-lg font-semibold text-neutral-800 truncate min-w-0 flex-1">
              Forecasting
            </h2>
            <button
              type="button"
              onClick={handleHelpClick}
              className={`shrink-0 text-xs px-2 py-1 rounded transition-colors ${
                descriptionSection === "help"
                  ? "bg-brand text-white"
                  : "bg-brand-light text-neutral-700 hover:bg-brand-light/80"
              }`}
              data-testid="forecasting-help-btn"
            >
              Справка
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

        {/* ── Замыкание цепочки «Ведём исследователя за руку» (v1.1 §9.4) ──
            Цепочка StepperNextModuleButton тянулась через все пять
            степперов и обрывалась здесь (решение FORECAST-1). Теперь,
            когда хаб /tasks существует, цепочка замыкается: та же
            кнопка-приглашение стоит в конце шагов этапа и ведёт на
            /tasks. Прецедент целевой страницы НЕ-степпера уже был —
            Моделирование ведёт на Прогнозирование (workspace).
            Компонент переиспользуется БЕЗ изменений: label/href —
            единственные входы; черта border-t встроена в обёртку. */}
        <StepperNextModuleButton label="Перейти к задачам" href="/tasks" />

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
          {/* Заголовок блока «Описание этапа» -- единый паттерн заголовков
              layout страницы (UI-FORECAST-HDR-1, паттерн серии UI-*-HDR):
              строка flex items-center gap-2 + иконка Info (как у
              «Описаний» всех вкладок) + text-lg font-semibold
              text-neutral-800 (был дефолтный text-sm без иконки);
              заголовок переключается на «Справка» в режиме справки,
              возврат «К описанию этапа» -- хвостовая кнопка строки
              (shrink-0, раньше justify-between без иконки). Ритм до
              текстового поля не тронут (mt-1 на боксе). */}
          <div className="flex items-center gap-2">
            <Info size={16} className="text-brand" aria-hidden="true" />
            <h3 className="text-lg font-semibold text-neutral-800 flex-1 min-w-0">
              {descriptionSection === "help" ? "Справка" : "Описание этапа"}
            </h3>
            {descriptionSection === "help" && (
              <button
                type="button"
                onClick={() => setDescriptionSection("main")}
                className="shrink-0 text-[11px] font-medium text-brand underline"
              >
                К описанию этапа
              </button>
            )}
          </div>
          {/* Expandable Description Box -- паттерн EDA (UI-FORECAST-HELP-1):
              шрифт текста text-sm (был text-xs; эталон EDA «text-sm
              text-neutral-600»), геометрия 220px/px-4 py-3 сохранена.
              Шевроны по паттерну EDA: сворачивание -- sticky bottom-0
              ВНУТРИ развёрнутого бокса (прилипает к НИЗУ окна; прежде
              единый toggle desc-toggle-btn сидел absolute bottom-1
              внешней обёртки -- при развёрнутом окне визуально
              «вверху», у нижней грани свёрнутого следа);
              разворачивание -- absolute bottom-1 по центру, только при
              переполнении (hasOverflow). Пин:
              forecasting-help-eda-pattern.test.tsx. */}
          <div className="relative">
            <div
              ref={descRef}
              className={`mt-1 rounded-lg border px-4 py-3 text-sm text-neutral-600 whitespace-pre-wrap ${
                descriptionExpanded
                  ? "absolute top-0 left-0 right-0 z-20 max-h-[calc(100vh-180px)] min-h-[220px] overflow-y-auto border-brand/30 bg-brand-light shadow-lg"
                  : "max-h-[220px] min-h-[220px] overflow-hidden bg-brand-light/50 border-neutral-200"
              }`}
            >
              {descriptionContent}
              {/* Collapse chevron -- паттерн EDA: sticky прилипает к низу
                  scroll-области развёрнутого окна. */}
              {descriptionExpanded && (
                <div className="sticky bottom-0 flex justify-center py-1 bg-brand-light rounded-b-lg">
                  <button
                    type="button"
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
            {/* Expand chevron -- паттерн EDA: только при переполнении,
                absolute bottom-1 по центру под боксом. */}
            {hasOverflow && !descriptionExpanded && (
              <button
                type="button"
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

        {/* ══ ПАНЕЛЬНЫЙ ПРОГНОЗ (PANEL-MODELS-3c): по-сущностные прогнозы
            панельного семейства (FE/RE сценарно, Panel VAR рекурсивно,
            DeepAR entity-pivot с квантильной поверхностью),
            мульти-сущностный график, экспорт CSV. Изолирован от однорядного
            карточного прогноза (R4). ══ */}
        <PanelForecastSection />
      </main>

      {/* ══ ПРАВАЯ КОЛОНКА ══ */}
      {/* Офсет pt-1 УБРАН (UI-FORECAST-HDR-1): строка заголовка -- первая
          ветка колонки, низы заголовков трёх колонок на одной горизонтали.
          Иконка Settings -- семантика «руль и педали» (тот же значок, что
          во всех вкладках серии). Заголовок «Панель управления» ПОДНЯТ из
          h4 text-sm первой карточки control-panel на уровень колонки
          (строка-паттерн -- первая ветка aside, mb-4 -- ритм правых
          колонок серии; текст сохранён, дубль в карточке убран). */}
      <aside className="w-80 shrink-0">
        <div className="flex items-center gap-2 mb-4">
          <Settings size={16} className="text-brand" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-neutral-800">
            Панель управления
          </h2>
        </div>
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-neutral-200 bg-white p-4" data-testid="control-panel">

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
              onExported={() => {
                void refreshAll();
              }}
            />
          </div>
        </div>
      </aside>
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════════════════
// PANEL-MODELS-3c: панельная секция «Прогноза» -- по-сущностные прогнозы
// панельного семейства №9 (этапы 3b/3c). Требует подтверждённый checkpoint
// panel_entry (Моделирование, панельный контур). FE/RE -- сценарный прогноз
// (константные пути экзогенных по сущностям, дисклоужено); Panel VAR --
// рекурсивный; deepar_panel -- по-сущностной прогноз глобальной модели с
// probabilistic-поверхностью. Таблица (сущность, точка, интервал) +
// мульти-сущностный график + экспорт CSV.
// ══════════════════════════════════════════════════════════════════════════════

interface PanelForecastCard {
  model_id: string;
  name: string;
  applicable: boolean;
  reasons: string[];
  engine: string | null;
  runtime_available: boolean;
  supports_prediction_intervals: boolean;
}

interface PanelForecastEntityRecord {
  entity: string;
  dates: string[];
  point: number[];
  lower: number[] | null;
  upper: number[] | null;
}

interface PanelForecastResult {
  model_id: string;
  model_name: string;
  horizon: number;
  panel: Record<string, any>;
  entities: PanelForecastEntityRecord[];
  variables: Record<string, { date: string; value: number }[]> | null;
  warnings: string[];
  method: string | null;
}

const PANEL_API_BASE = getApiBase();

function PanelForecastSection() {
  const [open, setOpen] = useState(false);
  const [cards, setPanelCards] = useState<PanelForecastCard[] | null>(null);
  const [gateMessage, setGateMessage] = useState<string | null>(null);
  const [modelId, setModelId] = useState("");
  const [horizon, setPanelHorizon] = useState(6);
  const [result, setResult] = useState<PanelForecastResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [visibleEntities, setVisibleEntities] = useState<string[]>([]);

  const loadCards = useCallback(async () => {
    setGateMessage(null);
    setError(null);
    try {
      const res = await fetch(`${PANEL_API_BASE}/v1/session/modeling/panel/candidates`, {
        credentials: "include",
      });
      const body = await res.json();
      if (!res.ok) {
        setPanelCards(null);
        setGateMessage(
          String(body?.detail ?? "Панельный контур недоступен: подтвердите checkpoint panel_entry в «Моделировании»"),
        );
        return;
      }
      const list = (body?.models ?? []) as PanelForecastCard[];
      setPanelCards(list);
      const firstApplicable = list.find((card) => card.applicable);
      setModelId((current) => (current ? current : firstApplicable?.model_id ?? ""));
    } catch {
      setGateMessage("Панельный контур недоступен: API не отвечает");
    }
  }, []);

  useEffect(() => {
    if (open && cards === null) void loadCards();
  }, [open, cards, loadCards]);

  const runForecast = useCallback(async () => {
    if (!modelId) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      // FE/RE -- сценарная постановка: без exog_paths платформа вернёт
      // честный 422 (статическая панель прогнозирует только сценарно,
      // GMM-контур в разработке); Panel VAR / deepar_panel прогнозируют
      // горизонт без путей. JSON-редактор путей -- развитие секции.
      const payload: Record<string, unknown> = {
        model_id: modelId,
        horizon,
      };
      const res = await fetch(`${PANEL_API_BASE}/v1/session/modeling/panel/forecast`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail ?? "Панельный прогноз не выполнен");
      const forecastResult = body as PanelForecastResult;
      setResult(forecastResult);
      setVisibleEntities(forecastResult.entities.slice(0, 3).map((r) => r.entity));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Ошибка панельного прогноза");
    } finally {
      setBusy(false);
    }
  }, [modelId, horizon]);

  const toggleEntity = useCallback((entity: string) => {
    setVisibleEntities((previous) =>
      previous.includes(entity)
        ? previous.filter((item) => item !== entity)
        : [...previous, entity],
    );
  }, []);

  const exportCsv = useCallback(() => {
    if (!result) return;
    const header = "entity,date,point,lower,upper";
    const lines = result.entities.flatMap((record) =>
      record.dates.map((date, index) =>
        [
          record.entity,
          date,
          record.point[index] ?? "",
          record.lower?.[index] ?? "",
          record.upper?.[index] ?? "",
        ].join(","),
      ),
    );
    const blob = new Blob([`${header}\n${lines.join("\n")}\n`], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `panel-forecast-${result.model_id}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [result]);

  const chartData = useMemo(() => {
    if (!result) return [];
    const byDate = new Map<string, Record<string, number | null>>();
    for (const record of result.entities) {
      if (!visibleEntities.includes(record.entity)) continue;
      record.dates.forEach((date, index) => {
        const row = byDate.get(date) ?? {};
        row[date] = null;
        row[record.entity] = record.point[index] ?? null;
        byDate.set(date, row);
      });
    }
    return Array.from(byDate.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, row]) => ({ date, ...row }));
  }, [result, visibleEntities]);

  const selectedCard = cards?.find((card) => card.model_id === modelId) ?? null;
  const needsExogPaths = modelId === "panel_fe" || modelId === "panel_re";

  return (
    <div className="mt-4 rounded-lg border border-neutral-200 bg-white" data-testid="panel-forecast-section">
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-neutral-800">
          <TrendingUp size={15} className="text-neutral-500" />
          Панельный прогноз: по-сущностные прогнозы (PANEL-MODELS-3c)
        </span>
        {open ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3 text-xs text-neutral-700">
          {gateMessage && (
            <p className="text-[11px] text-amber-700" data-testid="panel-forecast-gate">
              {gateMessage}
            </p>
          )}
          {cards && (
            <>
              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] text-neutral-500">Модель панели</span>
                  <select
                    className="border rounded px-2 py-1 text-xs"
                    value={modelId}
                    onChange={(e) => setModelId(e.target.value)}
                    data-testid="panel-forecast-model-select"
                  >
                    {cards.map((card) => (
                      <option
                        key={card.model_id}
                        value={card.model_id}
                        disabled={!card.applicable}
                      >
                        {card.name}{card.applicable ? "" : " (недоступна)"}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[10px] text-neutral-500">Горизонт</span>
                  <input
                    type="number" min={1} max={100}
                    className="border rounded px-2 py-1 text-xs"
                    value={horizon}
                    onChange={(e) => setPanelHorizon(Number(e.target.value) || 1)}
                    data-testid="panel-forecast-horizon"
                  />
                </label>
              </div>
              {selectedCard && !selectedCard.applicable && (
                <ul className="space-y-0.5">
                  {selectedCard.reasons.map((reason) => (
                    <li key={reason} className="text-[10px] text-amber-700">• {reason}</li>
                  ))}
                </ul>
              )}
              {needsExogPaths && (
                <p className="text-[10px] text-neutral-500">
                  FE/RE -- сценарная постановка: укажите константные пути
                  экзогенных (JSON-редактор путей по сущностям -- развитие
                  секции; без путей платформа вернёт честный 422).
                </p>
              )}
              <Button
                onClick={() => void runForecast()}
                disabled={busy || !modelId}
                className="w-full text-xs"
                data-testid="panel-forecast-run"
              >
                {busy ? "Расчёт…" : "Построить по-сущностной прогноз"}
              </Button>
            </>
          )}

          {result && (
            <div className="space-y-2" data-testid="panel-forecast-result">
              <div className="flex items-center justify-between">
                <h4 className="text-[11px] font-semibold text-neutral-800">
                  {result.model_name} · h={result.horizon} · сущностей: {result.entities.length}
                </h4>
                <Button onClick={exportCsv} className="text-[11px]" data-testid="panel-forecast-export-csv">
                  Экспорт CSV
                </Button>
              </div>

              {/* ── Мульти-сущностный график ── */}
              {chartData.length > 0 && (
                <div className="h-56" data-testid="panel-forecast-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} />
                      <YAxis tick={{ fontSize: 9 }} />
                      <RechartsTooltip />
                      <RechartsLegend wrapperStyle={{ fontSize: 10 }} />
                      {visibleEntities.map((entity) => (
                        <Line
                          key={entity}
                          type="monotone"
                          dataKey={entity}
                          dot={false}
                          strokeWidth={1.5}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
              <div className="flex flex-wrap gap-1" data-testid="panel-forecast-entity-switch">
                {result.entities.map((record) => (
                  <button
                    key={record.entity}
                    type="button"
                    onClick={() => toggleEntity(record.entity)}
                    className={`text-[9px] px-1.5 py-0.5 rounded-full border ${visibleEntities.includes(record.entity) ? "border-brand text-brand bg-brand/5" : "border-neutral-300 text-neutral-500"}`}
                  >
                    {record.entity}
                  </button>
                ))}
              </div>

              {/* ── Таблица по-сущностных прогнозов ── */}
              <div className="overflow-x-auto max-h-64 overflow-y-auto">
                <table className="text-[10px] w-full" data-testid="panel-forecast-table">
                  <thead className="sticky top-0 bg-white">
                    <tr className="text-left text-neutral-500">
                      <th className="pr-2">Сущность</th>
                      <th className="pr-2">Дата</th>
                      <th className="pr-2">Точка</th>
                      <th className="pr-2">Нижняя</th>
                      <th className="pr-2">Верхняя</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.entities.flatMap((record) =>
                      record.dates.map((date, index) => (
                        <tr key={`${record.entity}:${date}`} className="border-t border-neutral-100">
                          <td className="pr-2 font-medium">{record.entity}</td>
                          <td className="pr-2">{date}</td>
                          <td className="pr-2 font-mono">{(record.point[index] ?? 0).toFixed(2)}</td>
                          <td className="pr-2 font-mono text-neutral-500">
                            {record.lower?.[index] == null ? "—" : (record.lower[index] as number).toFixed(2)}
                          </td>
                          <td className="pr-2 font-mono text-neutral-500">
                            {record.upper?.[index] == null ? "—" : (record.upper[index] as number).toFixed(2)}
                          </td>
                        </tr>
                      )),
                    )}
                  </tbody>
                </table>
              </div>
              {result.warnings.map((warning) => (
                <p key={warning} className="text-[10px] text-amber-700">{warning}</p>
              ))}
            </div>
          )}

          {error && (
            <p className="text-[11px] text-red-600" data-testid="panel-forecast-error">{error}</p>
          )}
        </div>
      )}
    </div>
  );
}
