"use client";

// packages/ui/components/BacktestComparisonChart.tsx
//
// Реальный график сравнения результатов бэктеста -- вкладка
// «Моделирование», центральная колонка, после сводки метрик пула
// кандидатов. Второе подключение Recharts на платформе после
// DistributionCharts.tsx (Загрузка) -- по решению тимлида 2026-08-14:
// "Прогнозирование/Кандидаты в Моделировании — реальные данные уже
// есть, графика нет. Добавить сразу (быстро, честно, как Upload)".
//
// Данные -- НЕ новый API-запрос: тот же backtestResults (Record<model_id,
// BacktestResponse>), который TsAnalysisModeling.tsx уже накапливает при
// каждом клике «Запустить бэктест» (см. runBacktest). График появляется
// только когда есть хотя бы один реальный результат -- не мок.
//
// weighted_score -- НОРМАЛИЗОВАННАЯ ОШИБКА (0.35*MAE_n + 0.25*RMSE_n +
// 0.20*MAPE_n + 0.20*MASE_n), см. apps/api/routers/models.py::_compute_metrics.
// НИЖЕ = ЛУЧШЕ. В детальной карточке кандидата (справа) это подписано
// просто «Скоринг» без указания направления -- здесь явно проговариваем,
// чтобы график не читался наоборот.
//
// Палитра -- та же brand/brand-light из tailwind-preset.ts, что и в
// DistributionCharts.tsx (см. её докстринг).

import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BacktestResponse } from "../lib/modeling";

const BRAND = "#2E3192";
const BRAND_BEST = "#16A34A"; // green-600 -- лучшая (минимальная ошибка) модель
const AXIS_TICK_STYLE = { fontSize: 11, fill: "#737373" };

interface BacktestChartRow {
  model_id: string;
  model_name: string;
  score_pct: number; // weighted_score * 100, для читаемой оси (0-100)
  mae: number;
  rmse: number;
  mape: number;
  mase: number;
  data_source: string | null | undefined;
}

function truncateName(name: string, max = 14): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

export function BacktestComparisonChart({
  backtestResults,
}: {
  backtestResults: Record<string, BacktestResponse>;
}) {
  const entries = Object.values(backtestResults);

  if (entries.length === 0) {
    return (
      <div className="h-[180px] border border-neutral-200 rounded flex items-center justify-center text-xs text-neutral-500 bg-neutral-50">
        Запустите бэктест хотя бы для одной модели, чтобы увидеть сравнение
      </div>
    );
  }

  const rows: BacktestChartRow[] = entries
    .map((bt) => ({
      model_id: bt.model_id,
      model_name: bt.model_name,
      score_pct: Math.round(bt.metrics.weighted_score * 1000) / 10,
      mae: bt.metrics.mae,
      rmse: bt.metrics.rmse,
      mape: bt.metrics.mape,
      mase: bt.metrics.mase,
      data_source: bt.data_source,
    }))
    // Ниже = лучше -- сортируем по возрастанию ошибки, лучшая модель первая
    .sort((a, b) => a.score_pct - b.score_pct);

  const bestScore = rows[0]?.score_pct;

  return (
    <div>
      <div className="h-[180px] border border-neutral-200 rounded bg-white px-1 pt-2 pb-1">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
            <CartesianGrid stroke="#F0F0F0" vertical={false} />
            <XAxis
              dataKey="model_name"
              tick={AXIS_TICK_STYLE}
              tickFormatter={(name: string) => truncateName(name)}
              interval={0}
            />
            <YAxis tick={AXIS_TICK_STYLE} width={32} domain={[0, 100]} />
            <Tooltip
              formatter={(value: number, name: string) => {
                if (name === "score_pct") return [`${value.toFixed(1)}`, "Скоринг ошибки (ниже лучше)"];
                return [value, name];
              }}
              labelFormatter={(label: string) => label}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const row = payload[0].payload as BacktestChartRow;
                return (
                  <div className="rounded border border-neutral-200 bg-white px-2 py-1.5 text-[11px] shadow-sm">
                    <p className="font-semibold text-neutral-800 mb-1">{row.model_name}</p>
                    <p className="text-neutral-600">
                      Скоринг ошибки: <span className="font-mono font-semibold">{row.score_pct.toFixed(1)}</span>{" "}
                      <span className="text-neutral-400">(ниже лучше)</span>
                    </p>
                    <p className="text-neutral-500 mt-0.5">
                      MAE {row.mae.toFixed(2)} · RMSE {row.rmse.toFixed(2)} · MAPE {row.mape.toFixed(1)}% · MASE{" "}
                      {row.mase.toFixed(2)}
                    </p>
                    {row.data_source && (
                      <p className="text-[10px] text-neutral-400 mt-0.5">
                        {row.data_source === "session" ? "Реальные данные" : "Синтетический ряд"}
                      </p>
                    )}
                  </div>
                );
              }}
            />
            <Bar dataKey="score_pct" radius={[2, 2, 0, 0]} isAnimationActive={false}>
              {rows.map((row) => (
                <Cell key={row.model_id} fill={row.score_pct === bestScore ? BRAND_BEST : BRAND} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-neutral-500 mt-1.5">
        Скоринг ошибки (0–100, ниже = лучше) · <span className="text-green-700 font-medium">зелёным</span> — лучшая
        из {rows.length} протестированных
      </p>
    </div>
  );
}
