"use client";

// packages/ui/components/NavigatorPreview55Preview.tsx
//
// Статичная таблица превью 5+5 строк для окна «Обзор» остановки
// «Превью 5+5 строк» (id="preview_5_5") секции «Этапы модуля»
// остановки «Загрузка» на странице Навигатор (Task 2026-09-01).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНАЯ таблица 5+5 строк синтетического датасета
//     demo_finance_ohlcv.csv (первые 5 строк + separator «…» + последние
//     5 строк). Та же визуальная структура, что в TsAnalysisUpload.tsx
//     (строки 1012-1049): header → 5 head rows → separator → 5 tail rows.
//   • Источник данных — детерминированный клиентский генератор
//     `getDemoFinanceOhlcvPreview55()` (переиспользует generateFinanceOhlcv,
//     mulberry32 seed 20260821, 500 торговых дней, без выходных; колонки:
//     date,open,high,low,close,volume). Тот же seed, что и у NavigatorChartPreview
//     (Task 64) и у демо-датасета «Котировки инструмента (OHLCV)» во вкладке
//     «Загрузка».
//   • Превью закреплено СТАТИЧНО как пример — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если пользователь удалил
//     датасет, превью остаётся на месте (это и есть требование тимлида).
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Ближайший родственник — NavigatorChartPreview (Task 64): статичные
//     данные из детерминированного генератора, useMemo для кэширования.
//   • Recharts НЕ нужен — это таблица (как в TsAnalysisUpload.tsx),
//     чистая HTML-разметка с Tailwind.
//   • Высота автоматически определяется содержимым (header + 5 + separator
//     + 5 строк), визуально соответствует другим Overview-компонентам.
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label с описанием датасета и признака —
//     скринридер читает превью как одно изображение с описанием.
//   • Внутренние строки таблицы помечены data-testid="preview-row"
//     для тестов (10 строк: 5 head + 5 tail).

import { useMemo } from "react";
import { Database } from "lucide-react";
import { getDemoFinanceOhlcvPreview55 } from "../lib/demoDatasets";

// ── Константы контракта ─────────────────────────────────────────────
//
// Экспортированы, чтобы тесты и (потенциально) другие превью-компоненты
// Навигатора могли опираться на те же строки, что и реализация, без
// дублирования литералов.

export const NAVIGATOR_PREVIEW55_DATASET_FILE = "demo_finance_ohlcv.csv";
export const NAVIGATOR_PREVIEW55_FEATURE = "OHLCV";

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorPreview55Preview() {
  // Данные детерминированы и не зависят от внешнего состояния —
  // useMemo страхует от повторной генерации при ре-рендерах родителя
  // (TsAnalysisNavigator ре-рендерится при клике по item-карточкам).
  const { head, tail } = useMemo(() => getDemoFinanceOhlcvPreview55(), []);

  const isEmpty = head.length === 0;
  const headers = head[0] ?? [];
  const headRows = head.slice(1);
  const totalRows = 500; // фиксировано в генераторе (mulberry32 seed 20260821)

  const ariaLabel =
    `Статичное превью 5+5 строк синтетического датасета ${NAVIGATOR_PREVIEW55_DATASET_FILE}, ` +
    `признак ${NAVIGATOR_PREVIEW55_FEATURE}, ` +
    `всего ${totalRows} строк в датасете (показаны первые 5 и последние 5)`;

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + имя файла + бейдж «статичный пример» */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1">
        <div className="flex items-baseline gap-2 min-w-0">
          <h3 className="text-[13px] font-semibold text-neutral-900">
            Превью 5+5 строк
          </h3>
          <span className="text-[11px] text-neutral-500 font-mono whitespace-nowrap">
            {NAVIGATOR_PREVIEW55_DATASET_FILE}
          </span>
        </div>
        <span className="text-[10px] uppercase tracking-wide text-neutral-400 whitespace-nowrap">
          статичный пример
        </span>
      </div>

      {/* Таблица / заглушка */}
      {isEmpty ? (
        <div className="h-[280px] rounded-lg bg-brand-light flex items-center justify-center text-sm text-neutral-500 px-8 text-center">
          Демо-датасет временно недоступен
        </div>
      ) : (
        <div className="overflow-x-auto border border-neutral-200 rounded-lg">
          <table className="w-full text-xs">
            <thead className="bg-neutral-50 text-neutral-500 uppercase">
              <tr>
                {headers.map((colName, i) => (
                  <th
                    key={i}
                    className="text-left px-2 py-1.5 font-medium whitespace-nowrap"
                  >
                    {colName}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {/* Первые 5 строк данных */}
              {headRows.map((row, i) => (
                <tr key={`head-${i}`} data-testid="preview-row">
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className="px-2 py-1.5 font-mono text-[11px] text-neutral-700 whitespace-nowrap"
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
              {/* Separator «…» между head и tail — тот же визуальный
                  паттерн, что в TsAnalysisUpload.tsx:1034-1038. */}
              <tr className="text-neutral-400">
                <td
                  colSpan={headers.length || 1}
                  className="px-2 py-1.5 text-center"
                >
                  …
                </td>
              </tr>
              {/* Последние 5 строк данных */}
              {tail.map((row, i) => (
                <tr key={`tail-${i}`} data-testid="preview-row">
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className="px-2 py-1.5 font-mono text-[11px] text-neutral-700 whitespace-nowrap"
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Подпись: краткое пояснение */}
      <p className="text-[10px] text-neutral-500 mt-2.5 px-1 leading-snug flex items-start gap-1.5">
        <Database size={11} className="text-neutral-400 shrink-0 mt-0.5" aria-hidden="true" />
        <span>
          Показаны первые 5 и последние 5 строк из {totalRows} торговых дней
          синтетического OHLCV-датасета. Те же данные доступны во вкладке
          «Загрузка» через кнопку демо-датасета — превью здесь закреплено
          статично как пример и не зависит от сессии.
        </span>
      </p>
    </div>
  );
}
