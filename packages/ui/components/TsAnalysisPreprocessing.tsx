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
//   3/10 ████░░         [текстовое поле]       описание
//   ┌─Пропуски──⚠─┐    Обзор: Пропуски        ⚠ 11 наруш.
//   ├─Выбросы───⚠─┤    [график]               ▼ Метрики
//   └─────────────┘    [Строк][Проп][Выбр]    ▼ Пайплайн
//                                                [Пересчитать]

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

// ── Моковые данные (заменить на API) ─────────────────────────

const CHECKS: Check[] = [
  { id: "missing", label: "Пропуски", status: "warning", count: 11,
    description: "Пропуски нарушают DatetimeIndex, делают невозможной STL-декомпозицию, искажают ACF/PACF и ломают ARIMA/SARIMA." },
  { id: "outliers", label: "Выбросы", status: "warning", count: 1145,
    description: "Выбросы завышают дисперсию, искажают оценки тренда и ломают тесты стационарности (ADF/KPSS)." },
  { id: "duplicates", label: "Дубликаты", status: "done", count: 0,
    description: "Дублирующиеся временные метки ломают уникальность индекса." },
  { id: "regularity", label: "Регулярность шага", status: "pending", count: null,
    description: "Нерегулярный шаг мешает корректной декомпозиции и прогнозированию." },
  { id: "text_quality", label: "Качество текста", status: "pending", count: null,
    description: "Мусорные символы и пустые строки искажают категориальный анализ." },
  { id: "ranges", label: "Диапазоны значений", status: "done", count: 0,
    description: "Значения вне допустимого диапазона искажают статистику." },
  { id: "referential", label: "Ссылочная целостность", status: "pending", count: null,
    description: "Нарушение ссылочной целостности между справочниками." },
  { id: "formats", label: "Форматы", status: "warning", count: 3,
    description: "Несогласованные форматы дат/чисел ломают парсинг." },
  { id: "consistency", label: "Согласованность", status: "done", count: 0,
    description: "Нарушение хронологии внутри групп панельных данных." },
  { id: "ts_properties", label: "Свойства ряда", status: "pending", count: null,
    description: "Базовые свойства ряда для выбора модели прогнозирования." },
];

// Моковый список числовых признаков (заменить на activeDataset.columns)
const NUMERIC_FEATURES = [
  "price", "volume", "open", "high", "low", "close", "adj_close",
];

// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisPreprocessing() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);
  const [activeFeature, setActiveFeature] = useState(NUMERIC_FEATURES[0]);
  const [metricsText, setMetricsText] = useState("");

  const doneCount = CHECKS.filter((c) => c.status === "done").length;
  const progressPct = Math.round((doneCount / CHECKS.length) * 100);
  const activeCheck = CHECKS.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...CHECKS].sort((a, b) =>
    a.id === activeCheckId ? -1 : b.id === activeCheckId ? 1 : 0
  );

  // Populates the metrics text field when user clicks an accordion
  const handleMetricsClick = (check: Check) => {
    setMetricsText(
      `Метрики и алгоритм: ${check.label}\n\n(содержимое — только текст, без графиков)`
    );
  };

  const handlePipelineClick = (check: Check) => {
    setMetricsText(
      `Полный пайплайн: ${check.label.toLowerCase()}\n\n(содержимое — только текст, без графиков)`
    );
  };

  return (
    <div className="flex gap-6">
      {/* ── ЛЕВАЯ КОЛОНКА: селектор признака + прогресс + степпер ── */}
      <aside className="w-60 shrink-0 flex flex-col gap-3 pt-1">
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
              onClick={() => setActiveCheckId(check.id)}
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
        {/* Блок «Метрики и алгоритм» — текстовое поле над графиком */}
        <div className="mb-5">
          <h3 className="font-semibold mb-1">
            Метрики и алгоритм: {activeCheck.label}
          </h3>
          <p className="text-xs text-neutral-500 mb-2">
            поле заполняется при нажатии в боковой панели
          </p>
          <div className="rounded-lg bg-brand-light/50 border border-neutral-200 px-4 py-3 min-h-[120px] text-sm text-neutral-600 whitespace-pre-wrap">
            {metricsText || (
              <span className="text-neutral-400 italic">
                [текстовое поле для кнопок — Метрики и алгоритм / Справка по методу / Полный пайплайн]
              </span>
            )}
          </div>
        </div>

        {/* График */}
        <div>
          <h3 className="font-semibold mb-1">Обзор: {activeCheck.label}</h3>
          <p className="text-xs text-neutral-500 mb-3">
            Меняется автоматически под активную проверку.
          </p>

          <div className="bg-brand-light rounded-lg h-[420px] flex items-center justify-center text-sm text-neutral-500">
            [ график для «{activeCheck.label}» ]
          </div>

          <div className="grid grid-cols-4 gap-3 mt-4">
            <Metric label="Строк" value="200" />
            <Metric label="Пропусков" value="11" />
            <Metric label="Выбросов" value="3" />
            <Metric label="Частота" value="D" />
          </div>
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: список проверок (бывший центр) ── */}
      <aside className="w-80 shrink-0">
        <div className="max-h-[720px] overflow-y-auto pr-2 space-y-5 feed-scroll">
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

              <details
                className="mb-2 rounded bg-brand-light px-3 py-2 text-sm"
                open={check.id === activeCheckId}
                onClick={() => handleMetricsClick(check)}
              >
                <summary className="cursor-pointer font-medium">Метрики и алгоритм</summary>
                <p className="mt-2 text-neutral-600">(содержимое — только текст, без графиков)</p>
              </details>

              {check.count !== null && check.count > 0 && (
                <p className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                  ⚠️ Найдено {check.count} нарушений
                </p>
              )}
              {check.status === "done" && (
                <p className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                  Проверка пройдена, нарушений не найдено
                </p>
              )}

              <details
                className="mb-3 rounded bg-brand-light px-3 py-2 text-sm"
                open={check.id === activeCheckId}
                onClick={() => handlePipelineClick(check)}
              >
                <summary className="cursor-pointer font-medium">
                  Полный пайплайн: {check.label.toLowerCase()}
                </summary>
                <p className="mt-2 text-neutral-600">(содержимое — только текст, без графиков)</p>
              </details>

              <Button>Пересчитать свойства после преобразования ({check.label.toLowerCase()})</Button>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
