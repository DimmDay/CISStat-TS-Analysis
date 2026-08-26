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
import { sessionApiUrl } from "../lib/apiClient";
import { PreprocessingMissingOverview, type MissingProfileResponse } from "./PreprocessingMissingOverview";
import { PreprocessingMissingPipeline } from "./PreprocessingMissingPipeline";

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
  { id: "outliers", label: "Выбросы", status: "warning", count: 1145,
    description: "Выбросы завышают дисперсию, искажают оценки тренда и ломают тесты стационарности (ADF/KPSS). Методы: IQR, Z-score, MAD, Isolation Forest, LOF." },
  { id: "regularity", label: "Регулярность ряда", status: "pending", count: null,
    description: "Нерегулярный временной шаг мешает декомпозиции (STL), спектральному анализу (FFT) и моделям ARIMA. Решение: интерполяция gaps, ресемплирование к фиксированной частоте." },
  { id: "decomposition", label: "Декомпозиция ряда", status: "pending", count: null,
    description: "Разложение на Trend + Seasonal + Cycle + Residual методами STL, Classical, SEATS или X13. Диагностика остатков на нормальность и автокорреляцию." },
  { id: "variance_stab", label: "Стабилизация дисперсии", status: "pending", count: null,
    description: "Гетероскедастичность ломает доверительные интервалы и тесты. Трансформации: Box-Cox, Yeo-Johnson, log, sqrt. Параметры сохраняются для обратного преобразования." },
  { id: "smoothing", label: "Сглаживание ряда", status: "pending", count: null,
    description: "Удаление высокочастотного шума методами SMA, EMA, Holt-Winters, HP-filter, Savitzky-Golay или фильтром Калмана. Опциональный шаг для зашумлённых рядов." },
  { id: "stationarity", label: "Стационарность ряда", status: "pending", count: null,
    description: "Нестационарность ломает ACF/PACF и идентификацию ARIMA. Дифференцирование порядка d и сезонное D с контролем ADF/KPSS/PP. Порядок сохраняется для обратного преобразования." },
  { id: "spectral", label: "Спектральный анализ", status: "pending", count: null,
    description: "Разведочный анализ частотного состава ряда: FFT, periodogram, вейвлет-преобразование. Определяет доминантные частоты и сезонные периоды для генерации лаговых признаков." },
  { id: "feature_eng", label: "Генерация признаков", status: "pending", count: null,
    description: "Создание временных (hour, day, month), лаговых, скользящих статистик (rolling mean/std) и производных признаков. Структура лагов определяется результатами спектрального анализа." },
  { id: "scaling", label: "Масштабирование", status: "pending", count: null,
    description: "Нормализация признаков методами StandardScaler, MinMaxScaler, RobustScaler, QuantileTransformer или PowerTransformer. Критично для NN, SVM, k-NN." },
  { id: "passport", label: "Паспорт свойств ряда", status: "pending", count: null,
    description: "Сравнительный анализ свойств ряда: v1.0 (загрузка) → v1.1 (после валидации) → v1.2 (после предобработки). Метрики: ADF, Ljung-Box, Jarque-Bera, R². Экспорт в Excel." },
];

// Моковый список числовых признаков (заменить на activeDataset.columns)
const NUMERIC_FEATURES = [
  "price", "volume", "open", "high", "low", "close", "adj_close",
];

// ── Справка по целям модуля «Предобработка» (из app.py) ───────────

const PREPROCESSING_HELP = `Цели модуля "Предобработка"

Большинство классических моделей временных рядов и нейросетей предъявляют строгие требования к данным:
- отсутствие пропусков
- стационарность
- гомоскедастичность
- нормальность распределения и др.

Цель раздела. Применить математические преобразования, чтобы удовлетворить эти требования, сохранив при этом полезный сигнал (тренд, цикличность, сезонность). Предобработка решает задачу превращения данных в формат, пригодный для машинного обучения.

Что мы получим на выходе? Применив обратные преобразования после предобработки, мы имеем трансформированный датасет, готовый к загрузке в блок «Моделирование». Пользователь получает рекомендации по доступным моделям прогнозирования и сравнительные паспорта свойств ряда для анализа их изменения:
- v1.0 до валидации vs v1.3 после предобработки
- v1.2 до предобработки vs v1.3 после предобработки

Пайплайн предобработки (11 шагов):
1. Пропуски — интерполяция, forward-fill, mean, drop
2. Выбросы — IQR, Z-score, MAD, Isolation Forest, LOF
3. Регулярность ряда — интерполяция gaps, ресемплирование
4. Декомпозиция — STL / Classical / SEATS / X13
5. Стабилизация дисперсии — Box-Cox, Yeo-Johnson, log, sqrt
6. Сглаживание — SMA, EMA, Holt-Winters, HP-filter, Kalman
7. Стационарность — дифференцирование d/D, контроль ADF/KPSS/PP
8. Спектральный анализ — FFT, periodogram, вейвлет
9. Генерация признаков — время, лаги, rolling, производные
10. Масштабирование — Standard, MinMax, Robust, Quantile, Power
11. Паспорт свойств ряда — сравнение v1.0 → v1.1 → v1.2`;

type PreprocessingCheckMode = "auto" | "enabled" | "disabled";

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisPreprocessing() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  const [activeFeature, setActiveFeature] = useState(NUMERIC_FEATURES[0]);
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | null>(null);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // ── Режимы остановок (Task 47, применено к «Предобработке») ──
  // «Авто» / «Включена» / «Отключена» -- сохраняются в сессии через
  // GET/PUT /dataset/preprocessing-check-modes, отдельно от режимов
  // «Валидации» (другой степпер, другой словарь на бэкенде). Только
  // «Пропуски» реально реагируют на режим сегодня -- у остальных 10
  // остановок ещё нет backend-проверки, которую можно включить/отключить,
  // поэтому селектор режима показан только для «Пропусков»: показывать
  // его для мока значило бы обещать эффект, которого нет.
  const [checkModes, setCheckModes] = useState<Record<string, PreprocessingCheckMode>>({});
  const [modeSaving, setModeSaving] = useState<string | null>(null);
  const [modeError, setModeError] = useState<{ checkId: string; message: string } | null>(null);

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
  }, [missingRefreshKey]);

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

  // Итоговый список проверок -- статика для ещё не реализованных
  // остановок, реальные данные для «Пропусков».
  const checks = useMemo<Check[]>(() => CHECKS.map((check) =>
    check.id === "missing"
      ? { ...check, status: missingStatus, count: missingProfile?.total_missing ?? null }
      : check
  ), [missingStatus, missingProfile]);

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

  // Показать/скрыть справку по целям модуля
  const handleHelpClick = () => {
    setDescriptionSection((prev) => prev === "help" ? null : "help");
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

  // Текст описания для центрального поля — вычисляется из активной проверки и секции
  const descriptionContent = (() => {
    if (descriptionSection === "help") return PREPROCESSING_HELP;
    if (!descriptionSection) return null;
    if (descriptionSection === "metrics") {
      return `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`;
    }
    return `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`;
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка — Цели модуля и результаты прохождения";
    if (!descriptionSection) return "Выберите раздел в боковой панели";
    if (descriptionSection === "metrics") return `Метрики и алгоритм — ${activeCheck.label}`;
    return `Полный пайплайн — ${activeCheck.label}`;
  })();

  return (
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
          <label className="text-[11px] text-neutral-500 block mb-1">
            Исследуемый признак:
          </label>
          <select
            value={activeFeature}
            onChange={(e) => setActiveFeature(e.target.value)}
            className="w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
          >
            {NUMERIC_FEATURES.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
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

        {/* Степпер: прямоугольные карточки с текстом + иконка */}
        <div className="flex flex-col gap-1.5">
          {checks.map((check) => (
            <button
              key={check.id}
              onClick={() => {
                setActiveCheckId(check.id);
                if (descriptionSection === "help") setDescriptionSection(null);
              }}
              className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition-colors ${
                check.id === activeCheckId
                  ? "bg-brand text-white border-brand"
                  : "bg-white border-neutral-200 hover:bg-neutral-50 text-neutral-800"
              }`}
            >
              <span className="truncate">{check.label}</span>
              <span className="ml-2 shrink-0">
                <StatusIcon status={check.status} />
              </span>
            </button>
          ))}
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
              : `Обзор: ${activeCheck.label}`}
          </h3>
          <p className="text-xs text-neutral-500 mb-3">
            {activeCheckId === "missing" && descriptionSection === "pipeline"
              ? "Выберите колонки и стратегию, оцените последствия на копии и примените исправления."
              : activeCheckId === "missing"
              ? "Полнота данных по колонкам, рекомендованная стратегия исправления."
              : "Меняется автоматически под активную проверку."}
          </p>

          {activeCheckId === "missing" && descriptionSection === "pipeline" ? (
            <PreprocessingMissingPipeline onApplied={() => setMissingRefreshKey((k) => k + 1)} />
          ) : activeCheckId === "missing" ? (
            <PreprocessingMissingOverview refreshKey={missingRefreshKey} />
          ) : (
            <div className="bg-brand-light rounded-lg h-[420px] flex items-center justify-center text-sm text-neutral-500">
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

      {/* ── ПРАВАЯ КОЛОНКА: список проверок (бывший центр) ── */}
      <aside className="w-80 shrink-0">
        <div className="max-h-[830px] overflow-y-auto pr-2 space-y-5 feed-scroll">
          {orderedChecks.map((check) => (
            <article
              key={check.id}
              className={`pb-5 border-b border-neutral-100 ${
                check.id === activeCheckId ? "border-l-4 border-l-brand pl-3" : ""
              }`}
            >
              <h3 className="font-semibold mb-1">
                <StatusIcon status={check.status} /> Проверка: {check.label}
              </h3>

              <p className="text-sm text-neutral-600 mb-2">{check.description}</p>

              {/* Режим проверки -- только для «Пропусков»: у остальных
                  10 остановок ещё нет backend-проверки, которую можно
                  реально включить/отключить (см. комментарий у useState
                  checkModes выше). */}
              {check.id === "missing" && (
                <label className="mb-2 block text-[11px] font-medium text-neutral-600">
                  Режим проверки
                  <select
                    aria-label={`Режим проверки ${check.label}`}
                    value={checkModes.missing ?? "auto"}
                    disabled={modeSaving !== null}
                    onChange={(event) => void handleCheckModeChange("missing", event.target.value as PreprocessingCheckMode)}
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

              {/* Бейдж результата -- для «Пропусков» все состояния явно
                  различимы; для остальных (ещё не подключённых)
                  остановок -- прежняя упрощённая логика по count/status. */}
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
                {check.id === "missing" ? "Исправить пропуски" : "Полный пайплайн"}
              </button>

              <Button>Пересчитать свойства после преобразования ({check.label.toLowerCase()})</Button>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
