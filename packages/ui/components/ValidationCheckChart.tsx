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
// validation/engine.py::_run_all_checks. Четыре честных состояния:
//   - status="pending": включённой проверке требуется настройка правила.
//   - status="skipped": проверка отключена либо не требуется в режиме auto.
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
  status: "done" | "warning" | "pending" | "skipped";
  count: number | null;
  items: ValidationCheckItem[];
  /** "column" -- проверка учитывает выбранный target_column (см.
   * useTargetColumn); "dataset" -- принципиально весь датасет, выбор
   * признака слева НЕ меняет результат этой конкретной проверки
   * (межколоночные правила / дубли строк / ось времени -- см.
   * validation/engine.py::_run_all_checks). */
  scope?: "column" | "dataset";
  error?: string | null;
  rule_source?: "system" | "template" | "session" | "not_applicable";
  mode?: "auto" | "enabled" | "disabled";
  status_reason?: "not_required" | "disabled" | "needs_rule" | null;
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
    <div
      data-testid="validation-check-info"
      className={`flex min-h-0 flex-1 items-center justify-center rounded-lg px-8 text-center text-sm ${toneClass}`}
    >
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

function StateFrame({
  tone,
  children,
  scope,
  selectedColumn = null,
}: {
  tone: "neutral" | "positive" | "error";
  children: React.ReactNode;
  scope?: "column" | "dataset";
  selectedColumn?: string | null;
}) {
  return (
    <div
      data-testid="validation-check-state"
      className="flex h-[468px] min-h-0 flex-col"
    >
      <ScopeCaption scope={scope} selectedColumn={selectedColumn} />
      <InfoFrame tone={tone}>{children}</InfoFrame>
    </div>
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
    return <StateFrame tone="neutral">Загрузка результатов проверки…</StateFrame>;
  }

  if (!data) {
    return <StateFrame tone="neutral">Загрузите датасет, чтобы увидеть результаты проверки</StateFrame>;
  }

  if (data.error) {
    return (
      <StateFrame tone="error">
        Проверка «{checkLabel}» временно недоступна: {data.error}
      </StateFrame>
    );
  }

  if (data.status === "pending") {
    const isFormats = checkLabel === "Форматы и шаблоны";
    return (
      <StateFrame tone="neutral" scope={data.scope} selectedColumn={selectedColumn}>
        {isFormats
          ? "Эталон форматов не задан. Задайте regex-правила в «Управлении правилами» и запустите валидацию повторно."
          : `Проверка «${checkLabel}» неприменима к текущему датасету -- не найдено нужных колонок или справочника для сверки`}
      </StateFrame>
    );
  }

  if (data.status === "skipped") {
    return (
      <StateFrame tone="neutral" scope={data.scope} selectedColumn={selectedColumn}>
        {data.status_reason === "disabled"
          ? `Проверка «${checkLabel}» отключена аналитиком и не участвует в DQ Score`
          : `Проверка «${checkLabel}» не требуется для текущего датасета в режиме «Авто»`}
      </StateFrame>
    );
  }

  if (data.status === "done" || data.items.length === 0) {
    return (
      <StateFrame tone="positive" scope={data.scope} selectedColumn={selectedColumn}>
        ✅ Проверка «{checkLabel}» пройдена, нарушений не найдено
      </StateFrame>
    );
  }

  return (
    <div
      data-testid="validation-check-workspace"
      className="flex h-[468px] min-h-0 flex-col"
    >
      <ScopeCaption scope={data.scope} selectedColumn={selectedColumn} />
      <div
        data-testid="validation-check-visualization"
        className="min-h-0 flex-1 rounded-lg border border-neutral-200 bg-white px-2 pb-2 pt-4"
      >
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
