"use client";

// packages/ui/components/NavigatorChartPreview.tsx
//
// Статичный линейный график для окна «Обзор» остановки «График»
// (id="chart") секции «Этапы модуля» остановки «Загрузка» на странице
// Навигатор (Task 2026-08-29).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Источник данных — детерминированный синтетический датасет
//     demo_finance_ohlcv.csv (id="finance_ohlcv" в DEMO_DATASETS,
//     генератор generateFinanceOhlcv, mulberry32 seed 20260821,
//     500 торговых дней, без выходных).
//   • Признак: volume (5-я колонка CSV).
//   • График СТАТИЧНЫЙ: isAnimationActive={false}, нет загрузочного
//     состояния, нет «нет данных», нет «пример» — всегда готовый график.
//   • Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии. Даже если пользователь удалил
//     датасет, график остаётся на месте (это и есть требование тимлида).
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Ближайший родственник — TimeSeriesLineChart, но без пропов
//     data/loading и без API-вызова. Данные берутся из детерминированного
//     генератора через `getDemoFinanceOhlcvVolumeSeries()` — тот же
//     seed, что и у демо-датасета «Загрузки», поэтому график всегда
//     совпадает с тем, что пользователь увидит, если загрузит demo-файл.
//   • useMemo — генерация 500 точек недорога, но мемоизация страхует от
//     повторной работы при ре-рендерах родительского компонента
//     (TsAnalysisNavigator ре-рендерится при переключении items).
//   • recharts ResponsiveContainer + LineChart (тот же набор, что и в
//     TimeSeriesLineChart/DistributionCharts/BacktestComparisonChart —
//     единая библиотека графиков проекта).
//   • Высота h-[280px] — визуально соответствует высоте бывшей текстовой
//     заглушки (также h-[280px]), чтобы не менять компоновку окна «Обзор».
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label с указанием датасета, признака и
//     числа точек — скринридер читает график как одно изображение.
//   • Tooltip/внутренние элементы recharts — aria-hidden через recharts
//     defaults (SVG-декорация, не самостоятельный контент).

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getDemoFinanceOhlcvVolumeSeries } from "../lib/demoDatasets";

// ── Константы контракта ─────────────────────────────────────────────
//
// Экспортированы, чтобы тесты и (потенциально) другие превью-компоненты
// Навигатора могли опираться на те же строки, что и реализация, без
// дублирования литералов.

export const NAVIGATOR_CHART_PREVIEW_DATASET_ID = "demo_finance_ohlcv";
export const NAVIGATOR_CHART_PREVIEW_DATASET_FILE = "demo_finance_ohlcv.csv";
export const NAVIGATOR_CHART_PREVIEW_FEATURE = "volume";

// ── Палитра (та же, что у TimeSeriesLineChart) ──────────────────────
const BRAND = "#2E3192";
const AXIS_TICK_STYLE = { fontSize: 11, fill: "#737373" };

// ── Форматирование тиков оси X ──────────────────────────────────────
//
// Короткий формат даты для оси (полная дата в tooltip). ru-RU —
// единая локаль платформы (см. TimeSeriesLineChart.tsx).

function formatDateTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("ru-RU", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

// ── Компонент ───────────────────────────────────────────────────────

export function NavigatorChartPreview() {
  // Данные детерминированы и не зависят от внешнего состояния —
  // useMemo страхует от повторной генерации 500 точек при ре-рендерах
  // родителя (TsAnalysisNavigator ре-рендерится при клике по item-карточкам
  // и при изменении activeStopId/activeItemId).
  const points = useMemo(() => getDemoFinanceOhlcvVolumeSeries(), []);

  // Пустой ряд возможен только при структурных изменениях demoDatasets.ts
  // (например, переименовании колонки volume). Граaceful degradation:
  // показываем понятную заглушку вместо падения страницы Навигатор.
  const isEmpty = points.length === 0;

  const ariaLabel =
    `Статичный линейный график признака ${NAVIGATOR_CHART_PREVIEW_FEATURE} ` +
    `синтетического датасета ${NAVIGATOR_CHART_PREVIEW_DATASET_FILE}, ` +
    `${points.length} точек`;

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: имя файла + признак — чтобы пользователь сразу видел,
          что именно изображено на графике. */}
      <div className="flex items-baseline justify-between gap-2 mb-2 px-1">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-[12px] font-semibold text-neutral-900 truncate">
            {NAVIGATOR_CHART_PREVIEW_DATASET_FILE}
          </span>
          <span className="text-[11px] text-neutral-500 whitespace-nowrap">
            признак:&nbsp;
            <span className="font-mono text-neutral-700">
              {NAVIGATOR_CHART_PREVIEW_FEATURE}
            </span>
          </span>
        </div>
        <span className="text-[10px] uppercase tracking-wide text-neutral-400 whitespace-nowrap">
          статичный пример
        </span>
      </div>

      {/* График / заглушка */}
      {isEmpty ? (
        <div className="h-[280px] rounded-lg bg-brand-light flex items-center justify-center text-sm text-neutral-500 px-8 text-center">
          Демо-датасет временно недоступен
        </div>
      ) : (
        <div className="h-[280px] border border-neutral-200 rounded-lg bg-white px-2 pt-4 pb-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={points}
              margin={{ top: 4, right: 16, bottom: 4, left: 0 }}
            >
              <CartesianGrid stroke="#F0F0F0" vertical={false} />
              <XAxis
                dataKey="date"
                tick={AXIS_TICK_STYLE}
                tickFormatter={formatDateTick}
                minTickGap={40}
              />
              <YAxis tick={AXIS_TICK_STYLE} width={56} />
              <Tooltip
                labelFormatter={(x: string) => formatDateTick(x)}
                formatter={(value: number) => [
                  value.toLocaleString("ru-RU"),
                  NAVIGATOR_CHART_PREVIEW_FEATURE,
                ]}
              />
              <Line
                type="monotone"
                dataKey="volume"
                stroke={BRAND}
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Подпись: число точек + источник. */}
      <p className="text-[11px] text-neutral-500 mt-1.5 px-1">
        {isEmpty
          ? "Данные для статичного примера недоступны."
          : `${points.length.toLocaleString("ru-RU")} точек · demo_finance_ohlcv.csv`}
      </p>
    </div>
  );
}
