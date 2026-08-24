"use client";

// Специализированный «Обзор» для первой остановки «Типы данных».
// В отличие от ValidationCheckChart, который визуализирует нарушения,
// матрица полезна и в честном status="pending": backend уже построил
// фактический type_profile, но ожидаемая схема ещё не выбрана.

export type ValidationSemanticType = "numeric" | "datetime" | "categorical" | "text";
export type TypeValidationMode = "profile" | "schema";

export interface ValidationTypeProfileItem {
  name: string;
  dtype: string;
  type_icon: ValidationSemanticType;
  non_null: number;
  nulls: number;
  unique: number;
  /** Поля зарезервированы для режима явной схемы. Текущий auto API
   * возвращает только фактический профиль, поэтому они опциональны. */
  expected_type?: string | null;
  validation_status?: "matched" | "mismatch" | "profile" | null;
  violations?: number | null;
}

interface TypeConfig {
  id: ValidationSemanticType;
  label: string;
  shortLabel: string;
  segmentClass: string;
  dotClass: string;
}

const TYPE_CONFIG: TypeConfig[] = [
  { id: "numeric", label: "Числовые", shortLabel: "Числовой", segmentClass: "bg-brand", dotClass: "bg-brand" },
  { id: "datetime", label: "Дата/время", shortLabel: "Дата/время", segmentClass: "bg-cyan-500", dotClass: "bg-cyan-500" },
  { id: "categorical", label: "Категориальные", shortLabel: "Категориальный", segmentClass: "bg-amber-400", dotClass: "bg-amber-400" },
  { id: "text", label: "Текстовые", shortLabel: "Текстовый", segmentClass: "bg-neutral-400", dotClass: "bg-neutral-400" },
];

function InfoFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg h-[420px] flex items-center justify-center bg-brand-light px-8 text-center text-sm text-neutral-500">
      {children}
    </div>
  );
}

function statusView(item: ValidationTypeProfileItem, mode: TypeValidationMode) {
  if (item.validation_status === "matched") {
    return { label: "Соответствует", className: "bg-green-50 text-green-700" };
  }
  if (item.validation_status === "mismatch") {
    return { label: "Несоответствие", className: "bg-amber-50 text-amber-700" };
  }
  if (mode === "schema") {
    return { label: "По схеме", className: "bg-brand-light text-brand" };
  }
  return { label: "Профиль", className: "bg-brand-light text-brand" };
}

export function ValidationTypeMatrix({
  profile,
  mode,
  loading,
  hasDataset,
}: {
  profile: ValidationTypeProfileItem[];
  mode: TypeValidationMode;
  loading: boolean;
  hasDataset: boolean;
}) {
  if (loading) {
    return <InfoFrame>Загрузка профиля типов…</InfoFrame>;
  }

  if (!hasDataset) {
    return <InfoFrame>Загрузите датасет, чтобы увидеть матрицу типов</InfoFrame>;
  }

  if (profile.length === 0) {
    return <InfoFrame>Профиль типов не получен. Повторите проверку датасета.</InfoFrame>;
  }

  const counts = Object.fromEntries(
    TYPE_CONFIG.map(({ id }) => [id, profile.filter((column) => column.type_icon === id).length])
  ) as Record<ValidationSemanticType, number>;
  const distributionLabel = TYPE_CONFIG
    .map(({ id, label }) => `${label} — ${counts[id]}`)
    .join(", ");

  return (
    <div className="h-[420px] overflow-hidden rounded-lg border border-neutral-200 bg-white flex flex-col">
      <div className="border-b border-neutral-100 px-4 py-3">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <h4 className="text-sm font-semibold text-neutral-800">Распределение классов</h4>
          <span className="text-[11px] text-neutral-400 tabular-nums">{profile.length} колонок</span>
        </div>

        <div
          role="img"
          aria-label={`Распределение типов колонок: ${distributionLabel}`}
          className="flex h-3 w-full overflow-hidden rounded-full bg-neutral-100"
        >
          {TYPE_CONFIG.map(({ id, segmentClass }) => {
            const count = counts[id];
            if (count === 0) return null;
            return (
              <div
                key={id}
                data-testid={`type-segment-${id}`}
                className={segmentClass}
                style={{ width: `${(count / profile.length) * 100}%` }}
                aria-hidden="true"
              />
            );
          })}
        </div>

        <div className="mt-2 grid grid-cols-4 gap-2">
          {TYPE_CONFIG.map(({ id, label, dotClass }) => (
            <div key={id} className="flex min-w-0 items-center gap-1.5 text-[11px] text-neutral-600">
              <span className={`h-2 w-2 shrink-0 rounded-full ${dotClass}`} />
              <span className="truncate">{label}</span>
              <span data-testid={`type-count-${id}`} className="ml-auto font-mono font-semibold text-neutral-800">
                {counts[id]}
              </span>
            </div>
          ))}
        </div>

        <p className={`mt-2 rounded px-2.5 py-1.5 text-[11px] ${mode === "profile" ? "bg-brand-light/60 text-neutral-600" : "bg-green-50 text-green-700"}`}>
          {mode === "profile"
            ? "Режим профиля: ожидаемая схема не выбрана; фактические типы показаны, нарушения не рассчитываются."
            : "Режим схемы: фактические типы сопоставлены с ожидаемыми правилами."}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <table aria-label="Матрица типов колонок" className="w-full border-collapse text-left text-xs">
          <thead className="sticky top-0 z-10 bg-neutral-50 text-[11px] text-neutral-500">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Колонка</th>
              <th scope="col" className="px-3 py-2 font-medium">dtype</th>
              <th scope="col" className="px-3 py-2 font-medium">Ожидаемый тип</th>
              <th scope="col" className="px-3 py-2 font-medium">Статус</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Нарушения</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100">
            {profile.map((column) => {
              const semanticType = TYPE_CONFIG.find(({ id }) => id === column.type_icon);
              const status = statusView(column, mode);
              return (
                <tr key={column.name} className="text-neutral-700 hover:bg-neutral-50/70">
                  <th scope="row" className="max-w-[180px] truncate px-3 py-2.5 font-medium text-neutral-800" title={column.name}>
                    {column.name}
                  </th>
                  <td className="px-3 py-2.5">
                    <span className="block font-mono text-neutral-800">{column.dtype}</span>
                    <span className="text-[10px] text-neutral-400">{semanticType?.shortLabel ?? column.type_icon}</span>
                  </td>
                  <td className="px-3 py-2.5 text-neutral-500">{column.expected_type ?? (mode === "profile" ? "Не задан" : "По схеме")}</td>
                  <td className="px-3 py-2.5">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${status.className}`}>
                      {status.label}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular-nums">
                    {column.violations ?? "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
