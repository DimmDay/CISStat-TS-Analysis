"use client";

// packages/ui/components/TsAnalysisPreprocessing.tsx
//
// ОБЩИЙ компонент фичи "Предобработка" -- используется И embedded-,
// И standalone-приложением. Только внешняя "рамка" (шапка/навигация)
// вокруг него отличается между apps/embedded и apps/standalone;
// сама аналитическая UI-логика -- одна, чтобы не плодить дубли
// (см. историю разговора: 4 копии calculate_ts_passport -- урок учтён).

import { useState } from "react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
}

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

export function TsAnalysisPreprocessing() {
  const [activeCheckId, setActiveCheckId] = useState(CHECKS[0].id);

  const doneCount = CHECKS.filter((c) => c.status === "done").length;
  const progressPct = Math.round((doneCount / CHECKS.length) * 100);
  const activeCheck = CHECKS.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...CHECKS].sort((a, b) =>
    a.id === activeCheckId ? -1 : b.id === activeCheckId ? 1 : 0
  );

  return (
    <div className="flex gap-6">
      {/* Степпер: узкая вертикальная колонка иконок вместо широкой сетки --
          освобождает пространство для графика (см. правку по фидбэку). */}
      <aside className="w-14 shrink-0 flex flex-col items-center gap-1.5 pt-1">
        <p className="text-[10px] text-neutral-500 text-center leading-tight mb-0.5">
          {doneCount}/{CHECKS.length}
        </p>
        <div className="w-full bg-neutral-200 rounded-full h-1 mb-1">
          <div className="bg-brand h-1 rounded-full transition-all" style={{ width: `${progressPct}%` }} />
        </div>
        {CHECKS.map((check) => (
          <button
            key={check.id}
            title={`${check.label}${check.count ? ` (${check.count})` : ""}`}
            onClick={() => setActiveCheckId(check.id)}
            className={`w-10 h-10 rounded flex items-center justify-center text-base shrink-0 transition-colors ${
              check.id === activeCheckId ? "bg-brand text-white" : "bg-brand-light hover:bg-brand-light/70"
            }`}
          >
            <StatusIcon status={check.status} />
          </button>
        ))}
      </aside>

      {/* Список проверок: сужен (flex-1), уступает место графику справа. */}
      <section className="flex-1 min-w-0">
        <div className="max-h-[720px] overflow-y-auto pr-2 space-y-6 feed-scroll">
          {orderedChecks.map((check) => (
            <article
              key={check.id}
              className={`pb-6 border-b border-neutral-100 ${
                check.id === activeCheckId ? "border-l-4 border-l-brand pl-3" : ""
              }`}
            >
              <h3 className="font-semibold mb-1">
                <StatusIcon status={check.status} /> Проверка: {check.label}
              </h3>
              <p className="text-sm text-neutral-600 mb-2">{check.description}</p>

              <details className="mb-2 rounded bg-brand-light px-3 py-2 text-sm" open={check.id === activeCheckId}>
                <summary className="cursor-pointer font-medium">Метрики и алгоритм</summary>
                <p className="mt-2 text-neutral-600">(содержимое -- только текст, без графиков)</p>
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

              <details className="mb-3 rounded bg-brand-light px-3 py-2 text-sm" open={check.id === activeCheckId}>
                <summary className="cursor-pointer font-medium">
                  Полный пайплайн: {check.label.toLowerCase()}
                </summary>
                <p className="mt-2 text-neutral-600">(содержимое -- только текст, без графиков)</p>
              </details>

              <Button>Пересчитать свойства после преобразования ({check.label.toLowerCase()})</Button>
            </article>
          ))}
        </div>
      </section>

      {/* График: теперь доминирующая по ширине и высоте колонка --
          графики "один из верхних приоритетов" (правка по фидбэку). */}
      <aside className="flex-[2] min-w-[420px]">
        <div className="sticky top-6">
          <h3 className="font-semibold mb-1">Обзор: {activeCheck.label}</h3>
          <p className="text-xs text-neutral-500 mb-3">Меняется автоматически под активную проверку.</p>

          <div className="bg-brand-light rounded-lg h-[520px] flex items-center justify-center text-sm text-neutral-500">
            [ график для «{activeCheck.label}» ]
          </div>

          <div className="grid grid-cols-4 gap-3 mt-4">
            <Metric label="Строк" value="200" />
            <Metric label="Пропусков" value="11" />
            <Metric label="Выбросов" value="3" />
            <Metric label="Частота" value="D" />
          </div>
        </div>
      </aside>
    </div>
  );
}
