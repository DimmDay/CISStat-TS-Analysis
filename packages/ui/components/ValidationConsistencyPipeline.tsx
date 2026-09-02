"use client";

import { useEffect, useMemo, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { ConsistencyProfileItem, ConsistencyProfileResponse } from "./ValidationConsistencyOverview";


type Strategy = "sort_chronology" | "drop_rows" | "replace_null" | "flag";

interface CorrectionResponse {
  applied: boolean;
  strategy: Strategy;
  total_violations: number;
  total_changed: number;
  total_still_invalid: number;
  rows_removed: number;
  added_columns: string[];
  rules: Array<{
    rule_index: number;
    rule_name: string;
    invalid_count: number;
    affected_rows: number;
    changed_count: number;
    still_invalid: number;
    flag_column: string | null;
  }>;
  profile: ConsistencyProfileItem[];
}

const STRATEGIES: Record<Strategy, { label: string; help: string }> = {
  sort_chronology: {
    label: "Восстановить хронологический порядок",
    help: "Стабильная сортировка выполняется отдельно внутри каждой группы по временной колонке правила.",
  },
  drop_rows: {
    label: "Удалить затронутые строки",
    help: "Удаляется объединение строк, участвующих хотя бы в одном выбранном нарушении.",
  },
  replace_null: {
    label: "Заменить конфликтующее значение пропуском",
    help: "Меняется только корректируемая сторона правила; пропуски затем обрабатываются отдельным этапом качества.",
  },
  flag: {
    label: "Добавить флаг соблюдения правила",
    help: "Исходные значения сохраняются, для каждого правила добавляется булева колонка *_consistency_valid.",
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

export function ValidationConsistencyPipeline({
  onApplied,
  onOpenRules = () => undefined,
}: {
  onApplied: () => void;
  onOpenRules?: () => void;
}) {
  const [profile, setProfile] = useState<ConsistencyProfileResponse | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [strategy, setStrategy] = useState<Strategy>("sort_chronology");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const applicableRules = profile?.rules.filter((item) => item.applicable) ?? [];
  const hasApplicableRules = applicableRules.length > 0;
  const allRulesPassed = hasApplicableRules && applicableRules.every((item) => (item.invalid_count ?? 0) === 0);
  const selectedRules = useMemo(
    () => applicableRules.filter((item) => selected.includes(item.rule_index)),
    [applicableRules, selected]
  );
  const availableStrategies = useMemo(() => {
    if (selectedRules.length === 0) return [] as Strategy[];
    return (Object.keys(STRATEGIES) as Strategy[]).filter((candidate) =>
      selectedRules.every((item) => item.supported_actions.includes(candidate))
    );
  }, [selectedRules]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/consistency-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: ConsistencyProfileResponse = await response.json();
        if (!active) return;
        setProfile(data);
        setSelected(
          data.rules
            .filter((item) => item.applicable && (item.invalid_count ?? 0) > 0)
            .map((item) => item.rule_index)
        );
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить правила логики");
      } finally {
        if (active) setBusy(null);
      }
    })();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (availableStrategies.length > 0 && !availableStrategies.includes(strategy)) {
      setStrategy(availableStrategies[0]);
    }
  }, [availableStrategies, strategy]);

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
      const response = await fetch(sessionApiUrl("/dataset/consistency-corrections"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ rule_indices: selected, strategy, apply }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const data: CorrectionResponse = await response.json();
      setPreview(data);
      setConfirmed(false);
      if (apply) {
        setProfile((current) => current ? { ...current, rules: data.profile } : current);
        setSelected(
          data.profile
            .filter((item) => item.applicable && (item.invalid_count ?? 0) > 0)
            .map((item) => item.rule_index)
        );
        setSuccess("Изменения применены, общая валидация запущена повторно");
        onApplied();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось исправить логику и хронологию");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      role="region"
      aria-label="Мастер исправления логики и хронологии"
      className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll"
    >
      {allRulesPassed && (
        <div role="status" className="mb-4 rounded bg-green-50 px-3 py-2 text-sm text-green-700">
          <p className="font-medium">Все применимые правила логики и хронологии соблюдены.</p>
          <p className="mt-0.5 text-xs">Исправление не требуется.</p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">1. Правила с нарушениями</h4>
          <p className="mt-1 text-xs text-neutral-500">Отмечены только применимые правила, по которым найдены противоречия.</p>
          <div className="mt-3 space-y-2">
            {busy === "load" && <p className="text-sm text-neutral-400">Загрузка правил…</p>}
            {profile && !hasApplicableRules && (
              <div className="rounded bg-amber-50 p-2 text-sm text-amber-800">
                <p className="font-medium">Эталон логики и хронологии не задан.</p>
                <p className="mt-1 text-xs">Для хронологии нужна временная колонка; предметные связи задаются явными правилами.</p>
                <button
                  type="button"
                  onClick={onOpenRules}
                  className="mt-2 rounded border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100"
                >
                  Открыть управление правилами
                </button>
              </div>
            )}
            {profile?.rules.map((item) => (
              <label key={item.rule_index} className="block rounded bg-neutral-50 p-2 text-sm text-neutral-700">
                <span className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(item.rule_index)}
                    disabled={!item.applicable || (item.invalid_count ?? 0) === 0}
                    onChange={() => {
                      invalidatePreview();
                      setSelected((current) => current.includes(item.rule_index)
                        ? current.filter((index) => index !== item.rule_index)
                        : [...current, item.rule_index]);
                    }}
                    aria-label={`Выбрать правило ${item.rule_name}`}
                    className="accent-brand"
                  />
                  <span className="font-medium">{item.rule_name}</span>
                  <span className="ml-auto text-xs">нарушений: {item.invalid_count ?? "—"}</span>
                </span>
                <span className="mt-1 block text-[11px] text-neutral-500">
                  {item.rule_type} · {item.columns.join(" ↔ ") || "колонки не заданы"}
                  {item.group_column ? ` · группы: ${item.group_column}` : ""}
                </span>
                {item.invalid_examples.length > 0 && (
                  <span className="mt-1 block text-xs text-amber-700">Пример: {item.invalid_examples[0]}</span>
                )}
                {!item.applicable && item.applicability_message && (
                  <span className="mt-1 block text-xs text-neutral-400">{item.applicability_message}</span>
                )}
              </label>
            ))}
          </div>
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">2. Стратегия исправления</h4>
          <p className="mt-1 text-xs text-neutral-500">Список ограничен действиями, безопасными для всех отмеченных правил.</p>
          <select
            aria-label="Стратегия исправления логики"
            value={strategy}
            disabled={availableStrategies.length === 0}
            onChange={(event) => { invalidatePreview(); setStrategy(event.target.value as Strategy); }}
            className="mt-3 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm disabled:opacity-50"
          >
            {availableStrategies.map((key) => (
              <option key={key} value={key}>{STRATEGIES[key].label}</option>
            ))}
          </select>
          {availableStrategies.length > 0 && <p className="mt-2 text-xs text-neutral-600">{STRATEGIES[strategy].help}</p>}
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">3. Предпросмотр</h4>
          <p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на глубокой копии и не изменяет активный датасет.</p>
          <button
            type="button"
            disabled={selected.length === 0 || availableStrategies.length === 0 || busy !== null}
            onClick={() => requestCorrection(false)}
            className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}
          </button>
          {preview && (
            <div className="mt-3 rounded bg-neutral-50 p-2 text-xs text-neutral-700">
              <p className="font-medium">Нарушений до: {preview.total_violations}</p>
              <p>Нарушений после: {preview.total_still_invalid}</p>
              <p>Изменений: {preview.total_changed}</p>
              {preview.rows_removed > 0 && <p>Будет удалено строк: {preview.rows_removed}</p>}
              {preview.added_columns.length > 0 && <p>Добавлены колонки: {preview.added_columns.join(", ")}</p>}
            </div>
          )}
        </div>

        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold text-neutral-800">4. Применение</h4>
          <p className="mt-1 text-xs text-neutral-500">После подтверждения копия сохраняется атомарно, затем общая валидация запускается повторно.</p>
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
