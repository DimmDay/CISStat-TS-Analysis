"use client";

// packages/ui/components/DecompositionSeriesChart.tsx
//
// Дополнительный график под бейджами декомпозиции -- остановка «График»
// вкладки «Загрузка» (согласовано с тимлидом 2026-08-19: "визуализировать
// данный декомпозированный ряд на дополнительном графике... каждый
// своим цветом, график подписывается легендой: цвет - составляющая").
// Исходный линейный график (TimeSeriesLineChart) остаётся БЕЗ ИЗМЕНЕНИЙ --
// это ДОПОЛНИТЕЛЬНЫЙ график, не замена.
//
// Данные -- GET /v1/session/dataset/decomposition-series
// (apps/api/decomposition_data.py::build_decomposition_series), считается
// ПО ТОЙ ЖЕ КНОПКЕ «Считать декомпозицию», что и бейджи (один клик --
// оба результата, см. TsAnalysisUpload.tsx::fetchDecomposition).

import { Line, LineChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// Палитра -- 4 визуально различимых цвета, ни один не совпадает с BRAND
// (#2E3192) исходного линейного графика выше, чтобы не путать "сырой
// ряд" и "тренд" при беглом просмотре двух графиков подряд.
const COLORS = {
  trend: "#2563EB", // синий
  seasonal: "#16A34A", // зелёный
  cyclical: "#D97706", // оранжевый -- напоминание, что это оценочная эвристика
  resid: "#9CA3AF", // серый -- остаток/шум, наименее "содержательная" линия
};

const AXIS_TICK_STYLE = { fontSize: 11, fill: "#737373" };

export interface DecompositionSeriesPoint {
  x: string;
  trend: number;
  seasonal: number;
  cyclical: number;
  resid: number;
}

export interface DecompositionSeriesData {
  applicable: boolean;
  reason: string | null;
  method: string | null;
  sampled: boolean;
  sampling_method: string | null;
  original_count: number;
  points: DecompositionSeriesPoint[];
}

function formatDateTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("ru-RU", { year: "numeric", month: "short", day: "2-digit" });
}

const COMPONENT_LABELS: Record<string, string> = {
  trend: "Тренд",
  seasonal: "Сезонность",
  cyclical: "Цикличность",
  resid: "Остаток",
};

export function DecompositionSeriesChart({
  data,
  loading,
}: {
  data: DecompositionSeriesData | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="h-[320px] rounded-lg bg-brand-light flex items-center justify-center text-sm text-neutral-500">
        Считаем разложение ряда…
      </div>
    );
  }

  if (!data) return null; // кнопка ещё не нажата -- ничего не показываем (бейджи уже сообщают об этом)

  if (!data.applicable) {
    // Тот же reason, что и в бейджах (общий гейт на бэкенде) -- не
    // дублируем сообщение, просто не рисуем график, раз бейджи уже
    // объяснили причину прямо над этим местом.
    return null;
  }

  return (
    <div>
      <div className="h-[320px] border border-neutral-200 rounded-lg bg-white px-2 pt-4 pb-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data.points} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="#F0F0F0" vertical={false} />
            <XAxis dataKey="x" tick={AXIS_TICK_STYLE} tickFormatter={formatDateTick} minTickGap={40} />
            <YAxis tick={AXIS_TICK_STYLE} width={48} />
            <Tooltip
              labelFormatter={(x: string) => formatDateTick(x)}
              formatter={(value: number, name: string) => [value.toFixed(4), COMPONENT_LABELS[name] ?? name]}
            />
            <Legend
              formatter={(value: string) => COMPONENT_LABELS[value] ?? value}
              wrapperStyle={{ fontSize: 12 }}
            />
            <Line type="monotone" dataKey="trend" stroke={COLORS.trend} strokeWidth={1.75} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="seasonal" stroke={COLORS.seasonal} strokeWidth={1.5} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="cyclical" stroke={COLORS.cyclical} strokeWidth={1.5} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="resid" stroke={COLORS.resid} strokeWidth={1} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-neutral-500 mt-1.5">
        {data.sampled
          ? `Показано ${data.points.length.toLocaleString("ru-RU")} из ${data.original_count.toLocaleString("ru-RU")} точек (сэмплировано)`
          : `${data.points.length.toLocaleString("ru-RU")} точек`}
        {" · "}Цикличность — оценочная эвристика, не строгий метод
      </p>
    </div>
  );
}
