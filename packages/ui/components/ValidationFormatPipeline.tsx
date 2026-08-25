"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";

type Strategy = "replace_null" | "smart_replace" | "normalize" | "flag";

interface FormatProfileItem {
  column: string;
  pattern: string;
  threshold: number;
  total_count: number;
  valid_count: number;
  invalid_count: number;
  match_pct: number | null;
  invalid_examples: string[];
}

interface FormatProfileResponse {
  rule_source: "system" | "template" | "session" | "not_applicable";
  columns: FormatProfileItem[];
}

interface CorrectionResponse {
  applied: boolean;
  strategy: Strategy;
  total_violations: number;
  total_changed: number;
  total_still_invalid: number;
  added_columns: string[];
  columns: Array<{
    column: string;
    invalid_count: number;
    changed_count: number;
    still_invalid: number;
    invalid_examples: string[];
    flag_column: string | null;
  }>;
  profile: FormatProfileItem[];
}

const STRATEGY_TEXT: Record<Strategy, { label: string; help: string }> = {
  flag: {
    label: "Добавить флаг валидности",
    help: "Исходные значения сохраняются; рядом создаётся булева колонка *_format_valid.",
  },
  replace_null: {
    label: "Заменить нарушения пропусками",
    help: "Только значения, не совпавшие с regex, заменяются на пропуски.",
  },
  smart_replace: {
    label: "Безопасная подстановка",
    help: "Для известных шаблонов используется нейтральное значение, для остальных — пропуск.",
  },
  normalize: {
    label: "Нормализовать строки",
    help: "Удаляются лишние пробелы и символы, регистр приводится к нижнему; затем regex проверяется повторно.",
  },
};

async function responseDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Нейтральная ошибка ниже покрывает ответ без JSON.
  }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

export function ValidationFormatPipeline({
  onApplied,
  onOpenRules = () => undefined,
}: {
  onApplied: () => void;
  onOpenRules?: () => void;
}) {
  const [profile, setProfile] = useState<FormatProfileResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [strategy, setStrategy] = useState<Strategy>("flag");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const hasApplicableRules = (profile?.columns.length ?? 0) > 0;
  const allRulesPassed = hasApplicableRules && profile!.columns.every((item) => item.invalid_count === 0);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/format-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: FormatProfileResponse = await response.json();
        if (!active) return;
        setProfile(data);
        setSelected(data.columns.filter((item) => item.invalid_count > 0).map((item) => item.column));
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить правила форматов");
      } finally {
        if (active) setBusy(null);
      }
    })();
    return () => { active = false; };
  }, []);

  const invalidatePreview = () => {
    setPreview(null);
    setConfirmed(false);
    setSuccess(null);
    setError(null);
  };

  const requestCorrection = async (apply: boolean) => {
    setBusy(apply ? "apply" : "preview");
    setError(null);
    setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/format-corrections"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ columns: selected, strategy, apply }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const data: CorrectionResponse = await response.json();
      setPreview(data);
      setConfirmed(false);
      if (apply) {
        setProfile((current) => current ? { ...current, columns: data.profile } : current);
        setSelected(data.profile.filter((item) => item.invalid_count > 0).map((item) => item.column));
        setSuccess("Изменения применены, проверка запущена повторно");
        onApplied();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось исправить форматы");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      role="region"
      aria-label="Мастер исправления форматов и шаблонов"
      className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll"
    >
      {allRulesPassed && (
        <div role="status" className="mb-4 rounded bg-green-50 px-3 py-2 text-sm text-green-700">
          <p className="font-medium">Все значения соответствуют активным правилам форматов.</p>
          <p className="mt-0.5 text-xs">Исправление не требуется.</p>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="font-semibold text-sm text-neutral-800">1. Правила и колонки</h4>
          <p className="mt-1 text-xs text-neutral-500">Используются regex из активных правил сессии; отмечены найденные нарушения.</p>
          <div className="mt-3 space-y-2">
            {busy === "load" && <p className="text-sm text-neutral-400">Загрузка правил…</p>}
            {profile && profile.columns.length === 0 && (
              <div className="rounded bg-amber-50 p-2 text-sm text-amber-800">
                <p className="font-medium">Эталон форматов не задан.</p>
                <p className="mt-1 text-xs">Выберите предметный шаблон или добавьте regex для нужных колонок.</p>
                <button
                  type="button"
                  onClick={onOpenRules}
                  className="mt-2 rounded border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100"
                >
                  Открыть управление правилами
                </button>
              </div>
            )}
            {profile?.columns.map((item) => (
              <label key={item.column} className="block rounded bg-neutral-50 p-2 text-sm text-neutral-700">
                <span className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(item.column)}
                    disabled={item.invalid_count === 0}
                    onChange={() => {
                      invalidatePreview();
                      setSelected((current) => current.includes(item.column)
                        ? current.filter((column) => column !== item.column)
                        : [...current, item.column]);
                    }}
                    aria-label={`Выбрать колонку ${item.column}`}
                    className="accent-brand"
                  />
                  <span className="font-medium">{item.column}</span>
                  <span className="ml-auto text-xs">нарушений: {item.invalid_count}</span>
                </span>
                <code className="mt-1 block truncate text-[11px] text-neutral-500" title={item.pattern}>{item.pattern}</code>
                {item.invalid_examples.length > 0 && (
                  <span className="mt-1 block text-xs text-amber-700">Примеры: {item.invalid_examples.join(", ")}</span>
                )}
              </label>
            ))}
          </div>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="font-semibold text-sm text-neutral-800">2. Стратегия исправления</h4>
          <p className="mt-1 text-xs text-neutral-500">Выберите действие для всех отмеченных колонок.</p>
          <select
            aria-label="Стратегия исправления"
            value={strategy}
            onChange={(event) => { invalidatePreview(); setStrategy(event.target.value as Strategy); }}
            className="mt-3 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm"
          >
            {(Object.keys(STRATEGY_TEXT) as Strategy[]).map((key) => (
              <option key={key} value={key}>{STRATEGY_TEXT[key].label}</option>
            ))}
          </select>
          <p className="mt-2 text-xs text-neutral-600">{STRATEGY_TEXT[strategy].help}</p>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="font-semibold text-sm text-neutral-800">3. Предпросмотр</h4>
          <p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на копии и не изменяет активный датасет.</p>
          <button
            type="button"
            disabled={selected.length === 0 || busy !== null}
            onClick={() => requestCorrection(false)}
            className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}
          </button>
          {preview && (
            <div className="mt-3 rounded bg-neutral-50 p-2 text-xs text-neutral-700">
              <p className="font-medium">Исправлено значений: {preview.total_changed}</p>
              <p>Осталось нарушений: {preview.total_still_invalid}</p>
              {preview.added_columns.length > 0 && <p>Добавлены колонки: {preview.added_columns.join(", ")}</p>}
            </div>
          )}
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="font-semibold text-sm text-neutral-800">4. Применение</h4>
          <p className="mt-1 text-xs text-neutral-500">После подтверждения копия сохраняется атомарно, затем валидация запускается повторно.</p>
          <label className="mt-3 flex items-start gap-2 text-xs text-neutral-700">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={!preview || busy !== null}
              onChange={(event) => setConfirmed(event.target.checked)}
              aria-label="Подтверждаю изменение активного датасета"
              className="mt-0.5 accent-brand"
            />
            Подтверждаю изменение активного датасета
          </label>
          <button
            type="button"
            disabled={!preview || !confirmed || busy !== null}
            onClick={() => requestCorrection(true)}
            className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
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
