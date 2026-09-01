"use client";

// packages/ui/components/NavigatorDistributionPreview.tsx
//
// Статичная визуализация распределения для окна «Обзор» остановки
// «Визуализация распределения» (id="distribution") секции «Этапы модуля»
// остановки «Загрузка» на странице Навигатор (Task 2026-09-02).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНЫЕ графики распределения (точечный/
//     гистограмма/KDE) + 8 бейджей описательной статистики
//     синтетического датасета demo_energy_consumption.csv (колонка
//     consumption_mwh, 300 значений: 5 регионов × 60 месяцев).
//   • Источник данных — детерминированный клиентский генератор
//     `getDemoEnergyDistributionData()` (переиспользует
//     generateEnergyConsumption, mulberry32 seed 20260820). Тот же seed,
//     что у демо-датасета «Энергопотребление по регионам» во вкладке
//     «Загрузка».
//   • Визуализация закреплена СТАТИЧНО как пример — НЕ зависит от
//     useAppShell, activeDataset, fetch, сети, сессии. Даже если
//     пользователь удалил датасет, графики и бейджи остаются на месте.
//
// ── Архитектурный выбор ──────────────────────────────────────────────
//   • Ближайший родственник — NavigatorChartPreview (Task 64): статичные
//     данные из детерминированного генератора, useMemo для кэширования.
//   • Переиспользует СУЩЕСТВУЮЩИЕ ScatterDistributionChart /
//     HistogramDistributionChart / KdeDistributionChart из
//     DistributionCharts.tsx (те же, что в TsAnalysisUpload.tsx:1131-1157).
//     Не дублирует recharts-разметку.
//   • Metric-бейджи (8 шт.) — те же, что в TsAnalysisUpload.tsx:1173-1180,
//     тот же формат лейблов ("Mean (среднее)", "Q1 (1 квартиль)" и т.д.).
//
// ── a11y ────────────────────────────────────────────────────────────
//   • Корень: role="img" + aria-label с описанием датасета и признака —
//     скринридер читает визуализацию как одно изображение.
//   • Внутренние графики recharts — стандартная a11y через tooltip.

import { useMemo } from "react";
import {
  ScatterDistributionChart,
  HistogramDistributionChart,
  KdeDistributionChart,
} from "./DistributionCharts";
import { Metric } from "./Metric";
import { getDemoEnergyDistributionData } from "../lib/demoDatasets";

// ── Константы контракта ─────────────────────────────────────────────
//
// Экспортированы, чтобы тесты и (потенциально) другие превью-компоненты
// Навигатора могли опираться на те же строки, без дублирования литералов.

export const NAVIGATOR_DISTRIBUTION_DATASET_FILE = "demo_energy_consumption.csv";
export const NAVIGATOR_DISTRIBUTION_FEATURE = "consumption_mwh";

// ── Форматирование чисел для Metric-бейджей ─────────────────────────
//
// ru-RU, максимум 2 знака после запятой — тот же формат, что
// TsAnalysisUpload.tsx::fmtStat. Для null → "—" (бэкенд так же
// сериализует NaN в null для коротких рядов; в нашем случае 300
// значений, null не ожидается, но graceful degradation страховка).

function fmtStat(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorDistributionPreview() {
  // Данные детерминированы и не зависят от внешнего состояния —
  // useMemo страхует от повторной генерации при ре-рендерах родителя
  // (TsAnalysisNavigator ре-рендерится при клике по item-карточкам).
  const { distribution, stats } = useMemo(
    () => getDemoEnergyDistributionData(),
    []
  );

  const isEmpty = distribution.non_null_count === 0;

  const ariaLabel =
    `Статичная визуализация распределения синтетического датасета ${NAVIGATOR_DISTRIBUTION_DATASET_FILE}, ` +
    `признак ${NAVIGATOR_DISTRIBUTION_FEATURE}, ` +
    `${distribution.non_null_count} значений: точечный график, гистограмма, KDE и 8 описательных статистик`;

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className="rounded-lg border border-neutral-200 bg-white p-3"
    >
      {/* Шапка: заголовок + имя файла + признак + бейдж «статичный пример» */}
      <div className="flex items-baseline justify-between gap-2 mb-3 px-1 flex-wrap">
        <div className="flex items-baseline gap-2 min-w-0 flex-wrap">
          <h3 className="text-[13px] font-semibold text-neutral-900">
            Визуализация распределения
          </h3>
          <span className="text-[11px] text-neutral-500 font-mono whitespace-nowrap">
            {NAVIGATOR_DISTRIBUTION_DATASET_FILE}
          </span>
          <span className="text-[11px] text-neutral-500 whitespace-nowrap">
            признак:&nbsp;
            <span className="font-mono text-neutral-700">
              {NAVIGATOR_DISTRIBUTION_FEATURE}
            </span>
          </span>
        </div>
        <span className="text-[10px] uppercase tracking-wide text-neutral-400 whitespace-nowrap">
          статичный пример
        </span>
      </div>

      {isEmpty ? (
        <div className="h-[280px] rounded-lg bg-brand-light flex items-center justify-center text-sm text-neutral-500 px-8 text-center">
          Демо-датасет временно недоступен
        </div>
      ) : (
        <>
          {/* 3 графика распределения — переиспользуют существующие
              ScatterDistributionChart / HistogramDistributionChart /
              KdeDistributionChart из DistributionCharts.tsx. */}
          <div className="space-y-2 mb-3">
            <ScatterDistributionChart data={distribution} />
            <HistogramDistributionChart data={distribution} />
            <KdeDistributionChart data={distribution} />
          </div>

          {/* 8 бейджей описательной статистики — те же лейблы, что в
              TsAnalysisUpload.tsx:1173-1180 (Mean (среднее) / Median
              (медиана) / Std (стандартное отклонение) / Skewness
              (асимметрия) / Kurtosis (эксцесс) / Q1 (1 квартиль) /
              Q3 (3 квартиль) / IQR (межквартильный размах)). */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Metric label="Mean (среднее)" value={fmtStat(stats.mean)} />
            <Metric label="Median (медиана)" value={fmtStat(stats.median)} />
            <Metric label="Std (стандартное отклонение)" value={fmtStat(stats.std)} />
            <Metric label="Skewness (асимметрия)" value={fmtStat(stats.skewness)} />
            <Metric label="Kurtosis (эксцесс)" value={fmtStat(stats.kurtosis)} />
            <Metric label="Q1 (1 квартиль)" value={fmtStat(stats.q1)} />
            <Metric label="Q3 (3 квартиль)" value={fmtStat(stats.q3)} />
            <Metric label="IQR (межквартильный размах)" value={fmtStat(stats.iqr)} />
          </div>
        </>
      )}

      {/* Подпись: краткое пояснение */}
      <p className="text-[10px] text-neutral-500 mt-2.5 px-1 leading-snug">
        Показаны точечный график, гистограмма и KDE для признака{" "}
        <span className="font-mono">{NAVIGATOR_DISTRIBUTION_FEATURE}</span> из{" "}
        {distribution.non_null_count.toLocaleString("ru-RU")} значений
        синтетического датасета. Те же графики и статистики доступны во
        вкладке «Загрузка» — здесь закреплены статично как пример и не
        зависят от сессии.
      </p>
    </div>
  );
}
