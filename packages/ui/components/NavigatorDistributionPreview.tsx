"use client";

// packages/ui/components/NavigatorDistributionPreview.tsx
//
// Статичная визуализация распределения для окна «Обзор» остановки
// «Визуализация распределения» (id="distribution") секции «Этапы модуля»
// остановки «Загрузка» на странице Навигатор (Task 2026-09-02).
//
// ── Контракт ────────────────────────────────────────────────────────
//   • Визуализация — СТАТИЧНЫЕ графики распределения (точечный/
//     гистограмма/KDE) + бейджи описательной статистики
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
// ── Раскладка (1:1 как во вкладке «Загрузка», TsAnalysisUpload.tsx:1113-1182) ──
//   НЕ добавляем шапку/подпись/бейдж «статичный пример» — это расширило
//   бы границы окна «Обзор» сверх того, что было в плейсхолдере. Только
//   то, что относится к распределению:
//
//     grid grid-cols-1 md:grid-cols-3 gap-4
//     ├─ Точечный график (ScatterChart icon) + ScatterDistributionChart + SamplingBadge
//     ├─ Гистограмма (BarChart3 icon)     + HistogramDistributionChart
//     └─ KDE (Activity icon)              + KdeDistributionChart
//
//     параграф «Тип распределения: <hint>»
//
//     grid grid-cols-2 md:grid-cols-4 gap-3 — 8 Metric-бейджей:
//     Mean / Median / Std / Skewness / Kurtosis / Q1 / Q3 / IQR
//
//   Те же иконки lucide-react (ScatterChart / BarChart3 / Activity), те
//   же лейблы, те же классы Tailwind, что в TsAnalysisUpload.tsx:1120-1181.
//   Разница — без loading-state (данные статичны) и без fallback-веток
//   (numericCols всегда есть — это demo_energy_consumption.csv).
//
// ── a11y ────────────────────────────────────────────────────────────
//   Корня role="img" НЕТ — график распределения сам по себе не одно
//   изображение, а композиция из 3 чартов + статистик. Каждый график
//   имеет свой H4 заголовок для скринридера. Это совпадает с тем, как
//   вкладка «Загрузка» НЕ оборачивает распределение в role="img".

import { useMemo } from "react";
import { ScatterChart, BarChart3, Activity } from "lucide-react";
import {
  ScatterDistributionChart,
  HistogramDistributionChart,
  KdeDistributionChart,
  SamplingBadge,
} from "./DistributionCharts";
import { Metric } from "./Metric";
import { getDemoEnergyDistributionData } from "../lib/demoDatasets";

// ── Константы контракта (экспортированы для тестов) ──────────────────

export const NAVIGATOR_DISTRIBUTION_DATASET_FILE = "demo_energy_consumption.csv";
export const NAVIGATOR_DISTRIBUTION_FEATURE = "consumption_mwh";

// ── Эвристика «тип распределения» — упрощённая, основана на skewness ──
//
// Бэкенд (apps/api/...) строит distribution_hint из skewness/kurtosis, но
// для статичного примера достаточно простой эвристики:
//   |skew| < 0.5  → «Симметричное (близко к нормальному)»
//   skew ≥ 0.5   → «Правосторонняя асимметрия (длинный хвост справа)»
//   skew ≤ -0.5  → «Левосторонняя асимметрия (длинный хвост слева)»
//
// Те же пороги 0.5 — общепринятая практика интерпретации skewness
// (Bulmer 1979), не выдуманы.

function distributionHint(skewness: number | null): string {
  if (skewness === null) return "Недостаточно данных";
  if (Math.abs(skewness) < 0.5) return "Симметричное (близко к нормальному)";
  if (skewness >= 0.5) return "Правосторонняя асимметрия (длинный хвост справа)";
  return "Левосторонняя асимметрия (длинный хвост слева)";
}

// ── Форматирование чисел для Metric-бейджей ─────────────────────────
//
// ru-RU, максимум 2 знака после запятой — тот же формат, что
// TsAnalysisUpload.tsx::fmtStat. Для null → "—" (бэкенд так же
// сериализует NaN в null для коротких рядов).

function fmtStat(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

// ── Компонент ──────────────────────────────────────────────────────

export function NavigatorDistributionPreview() {
  // Данные детерминированы и не зависят от внешнего состояния —
  // useMemo страхует от повторной генерации при ре-рендерах родителя.
  const { distribution, stats } = useMemo(
    () => getDemoEnergyDistributionData(),
    []
  );

  return (
    <div>
      {/* 3 графика распределения в сетке 3 колонки — ТОЧНО как в
          TsAnalysisUpload.tsx:1120-1160. Каждый блок: H4 с иконкой
          + график (h-[200px] через ChartFrame внутри). */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        {/* Точечный график */}
        <div>
          <h4 className="text-xs font-semibold mb-2 inline-flex items-center gap-1.5 text-neutral-600">
            <ScatterChart size={13} aria-hidden="true" /> Точечный график
          </h4>
          <ScatterDistributionChart data={distribution} />
          <SamplingBadge data={distribution} />
        </div>
        {/* Гистограмма */}
        <div>
          <h4 className="text-xs font-semibold mb-2 inline-flex items-center gap-1.5 text-neutral-600">
            <BarChart3 size={13} aria-hidden="true" /> Гистограмма
          </h4>
          <HistogramDistributionChart data={distribution} />
        </div>
        {/* KDE */}
        <div>
          <h4 className="text-xs font-semibold mb-2 inline-flex items-center gap-1.5 text-neutral-600">
            <Activity size={13} aria-hidden="true" /> KDE (плотность)
          </h4>
          <KdeDistributionChart data={distribution} />
        </div>
      </div>

      {/* Параграф «Тип распределения» — ТОЧНО как в
          TsAnalysisUpload.tsx:1168-1171. */}
      <p className="text-sm mb-3">
        <span className="text-neutral-500">Тип распределения: </span>
        <strong className="text-neutral-900">
          {distributionHint(stats.skewness)}
        </strong>
      </p>

      {/* 8 Metric-бейджей в сетке 4 колонки — ТОЧНО как в
          TsAnalysisUpload.tsx:1172-1181. Те же лейблы и тот же fmtStat. */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="Mean (среднее)" value={fmtStat(stats.mean)} />
        <Metric label="Median (медиана)" value={fmtStat(stats.median)} />
        <Metric label="Std (стандартное отклонение)" value={fmtStat(stats.std)} />
        <Metric label="Skewness (асимметрия)" value={fmtStat(stats.skewness)} />
        <Metric label="Kurtosis (эксцесс)" value={fmtStat(stats.kurtosis)} />
        <Metric label="Q1 (1 квартиль)" value={fmtStat(stats.q1)} />
        <Metric label="Q3 (3 квартиль)" value={fmtStat(stats.q3)} />
        <Metric label="IQR (межквартильный размах)" value={fmtStat(stats.iqr)} />
      </div>
    </div>
  );
}
