"use client";

// packages/ui/components/ValidationCheckChart.tsx
//
// Реальный график детализации проверки -- вкладка «Валидация», центральная
// колонка, заменяет плейсхолдер "[ график для «{activeCheck.label}» ]".
// Третье подключение Recharts на платформе после Загрузки и Моделирования
// (2026-08-14, решение тимлида: "график детализации activeCheck").
//
// Данные -- items: [{label, count}] из GET /v1/session/dataset/validate,
// см. apps/api/routers/session.py::get_dataset_validate и
// validation/engine.py::_run_all_checks. Три честных состояния:
//   - status="pending": проверка неприменима к этому датасету (нет нужной
//     колонки/справочника) -- НЕ "0 нарушений", явно другое сообщение.
//   - status="done": 0 нарушений -- позитивное сообщение, не пустой график.
//   - status="warning": bar chart по items (нарушения по колонке/группе/правилу).
// error -- sub-check упал на бэкенде (см. _safe() в engine.py) -- честно
// показываем, что проверка временно недоступна, не "0 нарушений".

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const BRAND = "#2E3192";
const AXIS_TICK_STYLE = { fontSize: 11, fill: "#737373" };

export interface ValidationCheckItem {
  label: string;
  count: number;
}

export interface ValidationCheckData {
  status: "done" | "warning" | "pending";
  count: number | null;
  items: ValidationCheckItem[];
  /** "column" -- проверка учитывает выбранный target_column (см.
   * useTargetColumn); "dataset" -- принципиально весь датасет, выбор
   * признака слева НЕ меняет результат этой конкретной проверки
   * (межколоночные правила / дубли строк / ось времени -- см.
   * validation/engine.py::_run_all_checks). */
  scope?: "column" | "dataset";
  error?: string | null;
}

function truncateLabel(label: string, max = 16): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

function InfoFrame({ tone, children }: { tone: "neutral" | "positive" | "error"; children: React.ReactNode }) {
  const toneClass =
    tone === "positive"
      ? "bg-green-50 text-green-700"
      : tone === "error"
        ? "bg-red-50 text-red-700"
        : "bg-brand-light text-neutral-500";
  return (
    <div className={`rounded-lg h-[420px] flex items-center justify-center text-sm text-center px-8 ${toneClass}`}>
      {children}
    </div>
  );
}

function ScopeCaption({ scope, selectedColumn }: { scope?: "column" | "dataset"; selectedColumn: string | null }) {
  if (!selectedColumn) return null;
  return (
    <p className="text-[11px] text-neutral-400 mb-1.5">
      {scope === "dataset"
        ? `По всему датасету — не зависит от выбранного признака «${selectedColumn}»`
        : `По признаку «${selectedColumn}»`}
    </p>
  );
}

export function ValidationCheckChart({
  checkLabel,
  data,
  loading,
  selectedColumn = null,
}: {
  checkLabel: string;
  data: ValidationCheckData | null;
  loading: boolean;
  /** Текущий выбранный признак (target_column) -- только для честной
   * подписи над графиком ("по всему датасету" vs "по признаку X"), см.
   * ScopeCaption. Не обязателен -- используется только когда data.scope известен. */
  selectedColumn?: string | null;
}) {
  if (loading) {
    return <InfoFrame tone="neutral">Загрузка результатов проверки…</InfoFrame>;
  }

  if (!data) {
    return <InfoFrame tone="neutral">Загрузите датасет, чтобы увидеть результаты проверки</InfoFrame>;
  }

  if (data.error) {
    return (
      <InfoFrame tone="error">
        Проверка «{checkLabel}» временно недоступна: {data.error}
      </InfoFrame>
    );
  }

  if (data.status === "pending") {
    return (
      <div>
        <ScopeCaption scope={data.scope} selectedColumn={selectedColumn} />
        <InfoFrame tone="neutral">
          Проверка «{checkLabel}» неприменима к текущему датасету -- не найдено нужных колонок или справочника для
          сверки
        </InfoFrame>
      </div>
    );
  }

  if (data.status === "done" || data.items.length === 0) {
    return (
      <div>
        <ScopeCaption scope={data.scope} selectedColumn={selectedColumn} />
        <InfoFrame tone="positive">✅ Проверка «{checkLabel}» пройдена, нарушений не найдено</InfoFrame>
      </div>
    );
  }

  return (
    <div>
      <ScopeCaption scope={data.scope} selectedColumn={selectedColumn} />
      <div className="h-[420px] border border-neutral-200 rounded-lg bg-white px-2 pt-4 pb-2">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data.items} margin={{ top: 4, right: 12, bottom: 24, left: -12 }}>
          <CartesianGrid stroke="#F0F0F0" vertical={false} />
          <XAxis
            dataKey="label"
            tick={AXIS_TICK_STYLE}
            tickFormatter={(label: string) => truncateLabel(label)}
            interval={0}
            angle={data.items.length > 6 ? -30 : 0}
            textAnchor={data.items.length > 6 ? "end" : "middle"}
            height={data.items.length > 6 ? 50 : 24}
          />
          <YAxis tick={AXIS_TICK_STYLE} width={36} allowDecimals={false} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as ValidationCheckItem;
              return (
                <div className="rounded border border-neutral-200 bg-white px-2 py-1.5 text-[11px] shadow-sm">
                  <p className="font-semibold text-neutral-800">{row.label}</p>
                  <p className="text-neutral-600">
                    Нарушений: <span className="font-mono font-semibold">{row.count}</span>
                  </p>
                </div>
              );
            }}
          />
          <Bar dataKey="count" fill={BRAND} radius={[2, 2, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
      </div>
    </div>
  );
}
