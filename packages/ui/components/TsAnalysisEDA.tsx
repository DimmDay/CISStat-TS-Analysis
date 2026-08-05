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

import { useState } from "react";
import { Button } from "./Button";
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
    description: "Таблица mean, std, skew, kurtosis, quantiles по каждому признаку. Сравнение до/после предобработки. Подтверждение, что ряд стал «моделируемым»." },
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

// Моковый список числовых признаков (заменить на activeDataset.columns)
const NUMERIC_FEATURES = [
  "price", "volume", "open", "high", "low", "close", "adj_close",
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

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisEDA() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  const [activeFeature, setActiveFeature] = useState(NUMERIC_FEATURES[0]);
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | null>(null);

  const doneCount = CHECKS.filter((c) => c.status === "done").length;
  const progressPct = Math.round((doneCount / CHECKS.length) * 100);
  const activeCheck = CHECKS.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...CHECKS].sort((a, b) =>
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

  // Текст описания для центрального поля
  const descriptionContent = (() => {
    if (descriptionSection === "help") return EDA_HELP;
    if (!descriptionSection) return null;
    if (descriptionSection === "metrics") {
      return `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`;
    }
    return `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`;
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка — Цели модуля и результаты EDA";
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
              EDA
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
            Разведочный анализ данных
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
            {doneCount}/{CHECKS.length}
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
          {CHECKS.map((check) => (
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
          <div className="rounded-lg bg-brand-light/50 border border-neutral-200 px-4 py-3 min-h-[220px] max-h-[220px] overflow-y-auto text-sm text-neutral-600 whitespace-pre-wrap">
            {descriptionContent || (
              <span className="text-neutral-400 italic">
                Нажмите «Метрики и алгоритм», «Полный пайплайн» или «Справка»
              </span>
            )}
          </div>
        </div>

        {/* График */}
        <div>
          <h3 className="font-semibold mb-1">Обзор: {activeCheck.label}</h3>
          <p className="text-xs text-neutral-500 mb-3">
            Визуализация результатов исследования.
          </p>

          <div className="bg-brand-light rounded-lg h-[420px] flex items-center justify-center text-sm text-neutral-500">
            [ график для «{activeCheck.label}» ]
          </div>

          <div className="grid grid-cols-4 gap-3 mt-4">
            <Metric label="Строк" value="200" />
            <Metric label="Признаков" value="8" />
            <Metric label="H(ряд)" value="2.14" />
            <Metric label="ADF p" value="0.03" />
            <Metric label="Частота" value="D" />
          </div>
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

              <Button>Запустить анализ ({check.label.toLowerCase()})</Button>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}