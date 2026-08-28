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
//   0/11 ░░░░░░         Обзор: ...             [бейдж]
//   ┌─Описательные──○─┐  [график]              [Метрики и алгоритм]
//   ├─ACF/PACF────○─┤   [карточки]            [Полный пайплайн]
//   └────────────────┘                         [Запустить анализ]

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { sessionApiUrl } from "../lib/apiClient";
import { useTargetColumn } from "../hooks/useTargetColumn";
import { Button } from "./Button";
import {
  EdaDescriptiveOverview,
  type DescriptiveStatsResponse,
} from "./EdaDescriptiveOverview";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";

// ── Типы ──────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
}

// ── 11 исследований EDA ──────────────────────────────────────

const CHECKS: Check[] = [
  { id: "descriptive", label: "Описательные статистики", status: "pending", count: null,
    description: "Mean, median, std, квартильный профиль, skewness и excess kurtosis по каждому числовому признаку текущего преобразованного датасета. Таблица и три переключаемые визуализации помогают оценить масштаб, вариативность, асимметрию и тяжесть хвостов перед дальнейшим EDA." },
  { id: "correlation", label: "Корреляция (ACF/PACF)", status: "pending", count: null,
    description: "Автокорреляционная и частная автокорреляционная функции с доверительными интервалами. Ключевой вход для идентификации ARIMA-порядков (p, q). Сезонные ACF/PACF при наличии сезонности." },
  { id: "ih_analysis", label: "IH-анализ", status: "pending", count: null,
    description: "Информационно-энтропийное исследование: Shannon entropy (сложность), Sample/Approximate entropy (регулярность), Permutation entropy (хаотичность), Mutual information (нелинейная связь), Transfer entropy (направленная причинность). Дополняет ACF/PACF нелинейной структурой." },
  { id: "seasonality", label: "Сезонность и периодичность", status: "pending", count: null,
    description: "FFT/periodogram на преобразованном ряде. Выделение доминантных частот и множественной сезонности. Калькулятор сезонных периодов. Сравнение с результатами спектрального анализа из Предобработки." },
  { id: "stationarity", label: "Верификация стационарности", status: "pending", count: null,
    description: "Финальная проверка ADF/KPSS/PP на полностью преобразованном ряде. Скользящие mean/std. Автоматическая рекомендация: «ряд стационарен — ARIMA применима» или «вернитесь к шагу 7 Предобработки»." },
  { id: "distribution", label: "Распределение", status: "pending", count: null,
    description: "Гистограмма + плотность N(0,σ²), QQ-plot, тесты Jarque-Bera / Shapiro-Wilk / Kolmogorov-Smirnov. Вывод о корректности доверительных интервалов модели." },
  { id: "structural", label: "Структурные сдвиги", status: "pending", count: null,
    description: "Поиск точек regime change: CUSUM, Chow test, PELT. Визуализация с аннотациями. Рекомендация: «обучать на периоде после [date]» или «использовать модель с переключением режимов»." },
  { id: "feature_select", label: "Отбор признаков", status: "pending", count: null,
    description: "Корреляционная матрица сгенерированных признаков, VIF (Variance Inflation Factor), Granger causality для многомерных моделей. Рекомендация: оставить N значимых из M сгенерированных." },
  { id: "validation_strategy", label: "Стратегия валидации", status: "pending", count: null,
    description: "Выбор схемы разбиения: expanding window / sliding window / single split. Визуализация train/test на графике. Задание горизонта прогноза. Проверка достаточности наблюдений в train." },
  { id: "model_matrix", label: "Матрица моделей", status: "pending", count: null,
    description: "Таблица применимости: модель → требование → статус ряда → вывод. ARIMA, SARIMA, Prophet, LSTM, VAR, XGBoost и др. Автоматическая фильтрация по свойствам ряда." },
  { id: "passport", label: "Паспорт свойств ряда", status: "pending", count: null,
    description: "Финальная сводка конвейера: v1.0 (загрузка) → v1.1 (валидация) → v1.2 (предобработка) → v1.3 (EDA). Включает ACF-структуру, энтропийные метрики, стационарность, рекомендованные модели. Экспорт в Excel." },
];

// ── Справка по целям модуля «Разведочный EDA» ────────────────

const EDA_HELP = `Цели модуля "Разведочный EDA"

После валидации и предобработки данные очищены и трансформированы, но прежде чем выбирать и обучать модель, необходимо понять их статистические свойства, структуру зависимостей и пределы применимости различных моделей.

Цель раздела. Провести финальное разведочное исследование преобразованного временного ряда, верифицировать выполнение требований моделей и сформировать рекомендацию по выбору класса моделей прогнозирования.

Что мы получим на выходе? Аналитик получает:
- Подтверждение стационарности и нормальности остатков
- Идентификацию ACF/PACF структуры для ARIMA (p,d,q)
- Оценку предсказуемости ряда через энтропийные метрики
- Обнаружение структурных сдвигов и рекомендацию периода обучения
- Отбор значимых признаков с исключением мультиколлинеарности
- Стратегию временной валидации (train/test split)
- Матрицу применимости моделей с автоматической фильтрацией
- Финальный паспорт свойств ряда v1.0 → v1.3

Пайплайн EDA (11 шагов):
1. Описательные статистики — mean, std, skew, kurtosis
2. Корреляция (ACF/PACF) — линейная структура, идентификация (p,q)
3. IH-анализ — нелинейная структура, предсказуемость (энтропия)
4. Сезонность и периодичность — FFT, доминантные частоты
5. Верификация стационарности — ADF/KPSS/PP, финальная проверка
6. Распределение — нормальность, QQ-plot, JB/SW тесты
7. Структурные сдвиги — CUSUM, Chow, regime changes
8. Отбор признаков — VIF, Granger causality, мультиколлинеарность
9. Стратегия валидации — expanding/sliding window, горизонт
10. Матрица моделей — рекомендация по применимости
11. Паспорт свойств ряда — сводка v1.0 → v1.3`;

const DESCRIPTIVE_METRICS_DESCRIPTION = `Метрики и алгоритм: Описательные статистики

Остановка рассчитывает профиль каждой числовой колонки по ПОЛНОМУ текущему dataset в AnalysisSession. Это состояние уже включает применённые исправления и преобразования. Исторического снимка «до предобработки» сессия сейчас не хранит, поэтому интерфейс не показывает выдуманное сравнение до/после.

Основные метрики
1. N = число непустых наблюдений. При N < 2 статистики не вычисляются, а признак остаётся в таблице с честным пояснением.
2. Mean и Median характеризуют центр. Их заметное расхождение — сигнал асимметрии или влияния экстремальных значений.
3. Std — выборочное стандартное отклонение (pandas, ddof=1), мера абсолютного разброса в единицах признака.
4. Q1 и Q3 — 25-й и 75-й процентили; IQR = Q3 − Q1 — устойчивый к выбросам разброс центральных 50% наблюдений.
5. Skewness — коэффициент асимметрии: около 0 — симметрия; > 0 — длинный правый хвост; < 0 — длинный левый хвост. Доступен при N ≥ 3.
6. Kurtosis — excess kurtosis (у нормального распределения 0): положительное значение указывает на более тяжёлые хвосты, отрицательное — на более плоскую форму. Доступен при N ≥ 4.

Эвристика формы распределения
- |skew| < 0.5 и |kurtosis| < 1 → близко к нормальному;
- skew ≥ 0.5 / ≤ −0.5 → правосторонняя / левосторонняя асимметрия;
- при умеренной асимметрии kurtosis ≥ 1 → тяжёлые хвосты, иначе плосковершинная форма.

Эта эвристика — навигационный сигнал, а не статистический тест нормальности. Формальные тесты и QQ-plot относятся к отдельной остановке «Распределение».`;

const DESCRIPTIVE_PIPELINE_DESCRIPTION = `Полный пайплайн: описательные статистики

1. GET /v1/session/dataset/stats читает полный текущий session.dataframe; превью 5+5 строк не используется.
2. Backend выбирает все числовые колонки и отдельно удаляет NaN только на время расчёта каждой колонки.
3. Для N ≥ 2 pandas вычисляет mean, median, sample std, Q1, Q3 и IQR; skewness доступна при N ≥ 3, excess kurtosis — при N ≥ 4. Недоступные показатели формы возвращаются как null. Признаки с N < 2 не исчезают: возвращаются с stats=null и фактическим N.
4. Backend добавляет объяснимую эвристику формы распределения по skewness/kurtosis.
5. Выбор признака в левой колонке синхронизирует таблицу, нижние метрики и вкладки визуализации.
6. При первом открытии графической вкладки GET /v1/session/dataset/distribution?column=... возвращает scatter, гистограмму и KDE для выбранного признака. Один ответ переиспользуется при переключении вкладок.
7. Scatter сэмплируется LTTB только для больших рядов с сохранением экстремумов; гистограмма и KDE всегда считаются по полному выбранному диапазону.
8. Остановка read-only: она диагностирует текущее состояние и не мутирует датасет. Кнопка «Пересчитать статистики» повторно читает данные после преобразований предыдущих этапов.`;

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось загрузить описательные статистики (HTTP ${response.status})`;
}

function formatMetric(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const normalized = Object.is(value, -0) ? 0 : value;
  return normalized.toLocaleString("ru-RU", { maximumFractionDigits: 3 });
}

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisEDA() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | null>(null);
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
    loading: targetLoading,
    error: targetError,
    setColumn: setActiveFeature,
  } = useTargetColumn(undefined);

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
  }, [descriptiveRefreshKey]);

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

  const checks = useMemo<Check[]>(() => CHECKS.map((check) =>
    check.id === "descriptive"
      ? { ...check, status: descriptiveStatus, count: insufficientColumns }
      : check,
  ), [descriptiveStatus, insufficientColumns]);

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

  // Показать/скрыть справку
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

  // Текст описания для центрального поля
  const descriptionContent = (() => {
    if (descriptionSection === "help") return EDA_HELP;
    if (!descriptionSection) return null;
    if (activeCheckId === "descriptive") {
      return descriptionSection === "metrics"
        ? DESCRIPTIVE_METRICS_DESCRIPTION
        : DESCRIPTIVE_PIPELINE_DESCRIPTION;
    }
    if (descriptionSection === "metrics") {
      return `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`;
    }
    return `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`;
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
          ) : (
            <div className="bg-brand-light rounded-lg h-[420px] flex items-center justify-center text-sm text-neutral-500">
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

      {/* ── ПРАВАЯ КОЛОНКА: список исследований ── */}
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
              ) : (
                <Button>Запустить анализ ({check.label.toLowerCase()})</Button>
              )}
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
