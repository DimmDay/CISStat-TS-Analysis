"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { ValidationTypeProfileItem } from "./ValidationTypeMatrix";

type TargetType = "integer" | "float" | "datetime" | "string" | "boolean";
type InvalidPolicy = "reject" | "coerce";

interface ConversionResult {
  column: string;
  from_dtype: string;
  to_dtype: string;
  converted_count: number;
  invalid_count: number;
  invalid_examples: string[];
}

interface ConversionResponse {
  applied: boolean;
  invalid_policy: InvalidPolicy;
  total_invalid: number;
  target_column_reset: boolean;
  columns: ConversionResult[];
  type_profile: ValidationTypeProfileItem[];
}

interface ValidationTypePipelineProps {
  profile: ValidationTypeProfileItem[];
  activeTargetColumn?: string | null;
  onApplied: (profile: ValidationTypeProfileItem[], targetColumnReset: boolean) => void;
  onSchemaSaved?: () => void;
}

const TARGET_LABELS: Record<TargetType, string> = {
  integer: "Целое число",
  float: "Число",
  datetime: "Дата / время",
  string: "Строка",
  boolean: "Логический",
};

const TARGET_TYPES = Object.keys(TARGET_LABELS) as TargetType[];

function suggestedTarget(item: ValidationTypeProfileItem): TargetType {
  const dtype = item.dtype.toLowerCase();
  if (dtype.includes("datetime") || item.type_icon === "datetime") return "datetime";
  if (dtype.includes("bool")) return "boolean";
  if (dtype.includes("int")) return "integer";
  if (dtype.includes("float") || item.type_icon === "numeric") return "float";
  return "string";
}

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Ответ без JSON: ниже возвращается нейтральное сообщение с HTTP-кодом.
  }
  return `Не удалось выполнить преобразование (HTTP ${response.status})`;
}

export function ValidationTypePipeline({
  profile,
  activeTargetColumn = null,
  onApplied,
  onSchemaSaved = () => undefined,
}: ValidationTypePipelineProps) {
  const suggestedTargets = useMemo(
    () => Object.fromEntries(profile.map((item) => [item.name, suggestedTarget(item)])) as Record<string, TargetType>,
    [profile]
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [targets, setTargets] = useState<Record<string, TargetType>>({});
  const [invalidPolicy, setInvalidPolicy] = useState<InvalidPolicy>("reject");
  const [preview, setPreview] = useState<ConversionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"schema" | "preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const hydratedSchema = useRef("");

  const schemaSignature = useMemo(
    () => JSON.stringify(profile
      .filter((item) => item.expected_type)
      .map((item) => [item.name, item.expected_type])),
    [profile]
  );

  useEffect(() => {
    if (schemaSignature === "[]" || schemaSignature === hydratedSchema.current) return;
    const schemaColumns = profile.filter((item) => item.expected_type);
    setSelected(schemaColumns.map((item) => item.name));
    setTargets((current) => ({
      ...current,
      ...Object.fromEntries(schemaColumns.map((item) => [item.name, item.expected_type as TargetType])),
    }));
    hydratedSchema.current = schemaSignature;
  }, [profile, schemaSignature]);

  const invalidatePreview = () => {
    setPreview(null);
    setConfirmed(false);
    setError(null);
    setSuccess(null);
  };

  const toggleColumn = (column: string) => {
    invalidatePreview();
    setSelected((current) =>
      current.includes(column) ? current.filter((name) => name !== column) : [...current, column]
    );
  };

  const changeTarget = (column: string, target: TargetType) => {
    invalidatePreview();
    setTargets((current) => ({ ...current, [column]: target }));
  };

  const requestConversion = async (apply: boolean) => {
    setBusy(apply ? "apply" : "preview");
    setError(null);
    setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/convert-types"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          conversions: selected.map((column) => ({
            column,
            target_type: targets[column] ?? suggestedTargets[column],
          })),
          invalid_policy: invalidPolicy,
          apply,
        }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));

      const data: ConversionResponse = await response.json();
      setPreview(data);
      setConfirmed(false);
      if (apply) {
        setSuccess("Изменения применены к активному датасету");
        onApplied(data.type_profile, data.target_column_reset);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось выполнить преобразование");
    } finally {
      setBusy(null);
    }
  };

  const saveSchema = async () => {
    setBusy("schema");
    setError(null);
    setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/type-schema"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          columns: selected.map((column) => ({
            column,
            target_type: targets[column] ?? suggestedTargets[column],
          })),
        }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      await response.json();
      setSuccess("Эталон типов сохранён, проверка запущена");
      onSchemaSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось сохранить эталон типов");
    } finally {
      setBusy(null);
    }
  };

  const applyBlockedByReject = invalidPolicy === "reject" && (preview?.total_invalid ?? 0) > 0;

  return (
    <section
      role="region"
      aria-label="Мастер исправления типов"
      className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll"
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="font-semibold text-sm text-neutral-800">1. Выбор колонок</h4>
          <p className="mt-1 text-xs text-neutral-500">Отметьте только те колонки, тип которых нужно исправить.</p>
          <div className="mt-3 space-y-2">
            {profile.length > 0 ? profile.map((item) => (
              <label key={item.name} className="flex items-center gap-2 text-sm text-neutral-700">
                <input
                  type="checkbox"
                  checked={selected.includes(item.name)}
                  onChange={() => toggleColumn(item.name)}
                  aria-label={`Выбрать колонку ${item.name}`}
                  className="accent-brand"
                />
                <span className="min-w-0 truncate">{item.name}</span>
                <span className="ml-auto shrink-0 font-mono text-xs text-neutral-400">{item.dtype}</span>
              </label>
            )) : (
              <p className="text-sm text-neutral-400">Профиль колонок пока недоступен.</p>
            )}
          </div>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="font-semibold text-sm text-neutral-800">2. Ожидаемые типы</h4>
          <p className="mt-1 text-xs text-neutral-500">Задайте эталон сессии и поведение для неприводимых значений.</p>
          <div className="mt-3 space-y-2">
            {profile.map((item) => (
              <div key={item.name} className="grid grid-cols-[minmax(0,1fr)_minmax(130px,1fr)] items-center gap-2">
                <span className={`truncate text-sm ${selected.includes(item.name) ? "text-neutral-800" : "text-neutral-400"}`}>
                  {item.name}
                </span>
                <select
                  aria-label={`Целевой тип для ${item.name}`}
                  value={targets[item.name] ?? suggestedTargets[item.name]}
                  onChange={(event) => changeTarget(item.name, event.target.value as TargetType)}
                  className="rounded border border-neutral-300 bg-white px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-brand"
                >
                  {TARGET_TYPES.map((target) => (
                    <option
                      key={target}
                      value={target}
                      disabled={item.name === activeTargetColumn && !["integer", "float"].includes(target)}
                    >
                      {TARGET_LABELS[target]}
                    </option>
                  ))}
                </select>
              </div>
            ))}
            <label className="block pt-1 text-xs text-neutral-500">
              Политика ошибок
              <select
                aria-label="Политика ошибок"
                value={invalidPolicy}
                onChange={(event) => {
                  invalidatePreview();
                  setInvalidPolicy(event.target.value as InvalidPolicy);
                }}
                className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm text-neutral-800 focus:outline-none focus:ring-1 focus:ring-brand"
              >
                <option value="reject">Отклонить весь набор при ошибке</option>
                <option value="coerce">Заменить ошибки пропусками</option>
              </select>
            </label>
            {activeTargetColumn && (
              <p className="text-[11px] text-neutral-500">
                Исследуемый признак «{activeTargetColumn}» можно преобразовать только в числовой тип.
              </p>
            )}
            <button
              type="button"
              disabled={selected.length === 0 || busy !== null}
              onClick={saveSchema}
              className="w-full rounded border border-brand px-3 py-2 text-sm font-medium text-brand transition-opacity hover:bg-brand-light/50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy === "schema" ? "Сохранение…" : "Сохранить эталон и проверить"}
            </button>
          </div>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="font-semibold text-sm text-neutral-800">3. Предпросмотр</h4>
          <p className="mt-1 text-xs text-neutral-500">Проверка выполняется на копии и не изменяет активный датасет.</p>
          <button
            type="button"
            disabled={selected.length === 0 || busy !== null}
            onClick={() => requestConversion(false)}
            className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}
          </button>
          {preview && (
            <div className="mt-3 rounded bg-neutral-50 p-2 text-xs text-neutral-700">
              <p className="font-medium">Неприводимых значений: {preview.total_invalid}</p>
              <ul className="mt-1 space-y-1">
                {preview.columns.map((item) => (
                  <li key={item.column}>
                    {item.column}: {item.from_dtype} → {item.to_dtype}; преобразовано {item.converted_count}
                    {item.invalid_examples.length > 0 && `; примеры ошибок: ${item.invalid_examples.join(", ")}`}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="font-semibold text-sm text-neutral-800">4. Применение</h4>
          <p className="mt-1 text-xs text-neutral-500">После подтверждения изменения атомарно сохраняются в текущей сессии.</p>
          <label className="mt-3 flex items-start gap-2 text-xs text-neutral-700">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={!preview || applyBlockedByReject || busy !== null}
              onChange={(event) => setConfirmed(event.target.checked)}
              aria-label="Подтверждаю изменение активного датасета"
              className="mt-0.5 accent-brand"
            />
            Подтверждаю изменение активного датасета
          </label>
          {applyBlockedByReject && (
            <p className="mt-2 text-xs text-amber-700">
              Применение заблокировано: исправьте значения или выберите замену ошибок пропусками.
            </p>
          )}
          <button
            type="button"
            disabled={!preview || !confirmed || applyBlockedByReject || busy !== null}
            onClick={() => requestConversion(true)}
            className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === "apply" ? "Применение…" : "Применить исправления"}
          </button>
        </div>
      </div>

      {error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}
    </section>
  );
}
