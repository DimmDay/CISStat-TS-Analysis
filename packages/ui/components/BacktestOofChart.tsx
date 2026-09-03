"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BacktestResponse } from "../lib/modeling";

const TICK = { fontSize: 10, fill: "#737373" };

export function BacktestOofChart({ result }: { result: BacktestResponse }) {
  const points = result.oof_predictions ?? [];
  if (points.length === 0) {
    return (
      <div className="flex h-[180px] items-center justify-center rounded border border-neutral-200 bg-neutral-50 text-xs text-neutral-500">
        OOF-прогнозы отсутствуют
      </div>
    );
  }
  const foldStarts = points.filter((point) => point.horizon_step === 1).slice(1);
  const data = points.map((point) => ({ ...point, x: point.label ?? String(point.index) }));

  return (
    <div>
      <div
        role="img"
        aria-label={`OOF прогноз ${result.model_name}: факт и прогноз по временным folds`}
        className="h-[210px] rounded border border-neutral-200 bg-white px-1 pb-1 pt-2"
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 10, bottom: 2, left: -12 }}>
            <CartesianGrid stroke="#F0F0F0" vertical={false} />
            <XAxis dataKey="x" tick={TICK} minTickGap={28} />
            <YAxis tick={TICK} width={54} domain={["auto", "auto"]} />
            <Tooltip
              labelFormatter={(label) => String(label)}
              formatter={(value: number, name: string) => [
                Number(value).toFixed(4), name === "actual" ? "Факт" : "Прогноз",
              ]}
            />
            {foldStarts.map((point) => (
              <ReferenceLine
                key={`${point.fold}-${point.index}`}
                x={point.label ?? String(point.index)}
                stroke="#D4D4D4"
                strokeDasharray="3 3"
              />
            ))}
            <Line type="monotone" dataKey="actual" name="actual" stroke="#171717" dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="predicted" name="predicted" stroke="#2E3192" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1.5 text-[11px] text-neutral-500">
        {points.length} OOF-точки · {result.n_folds ?? new Set(points.map((point) => point.fold)).size} folds · чёрный — факт, синий — fixed-origin прогноз
      </p>
    </div>
  );
}
