"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { ReferentialProfileItem, ReferentialProfileResponse } from "./ValidationReferentialOverview";

type Strategy = "mode" | "replace_null" | "drop_rows" | "replace_default" | "flag";
interface CorrectionResponse {
  applied: boolean; strategy: Strategy; total_violations: number; total_changed: number;
  total_still_invalid: number; rows_removed: number; added_columns: string[];
  rules: Array<{ rule_index: number; rule_name: string; child_column: string; invalid_count: number; changed_count: number; still_invalid: number; replacement_value: unknown; flag_column: string | null }>;
  profile: ReferentialProfileItem[];
}

const STRATEGIES: Record<Strategy, { label: string; help: string }> = {
  mode: { label: "Заменить модой связанных значений", help: "Используется самое частое уже наблюдаемое значение, существующее в родительском справочнике." },
  replace_default: { label: "Заменить значением по умолчанию", help: "Используется явно заданный родительский ключ, который входит в справочник." },
  replace_null: { label: "Заменить сироты пропусками", help: "Неизвестные дочерние ключи становятся пропусками для последующей обработки." },
  drop_rows: { label: "Удалить сиротские строки", help: "Удаляется объединение строк, нарушающих любое отмеченное правило." },
  flag: { label: "Добавить флаг связности", help: "Ключи сохраняются; создаётся колонка *_ref_valid." },
};

async function responseDetail(response: Response) {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

export function ValidationReferentialPipeline({ onApplied, onOpenRules = () => undefined }: { onApplied: () => void; onOpenRules?: () => void }) {
  const [profile, setProfile] = useState<ReferentialProfileResponse | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [strategy, setStrategy] = useState<Strategy>("mode");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const applicable = profile?.rules.filter((item) => item.applicable) ?? [];
  const passed = applicable.length > 0 && applicable.every((item) => item.invalid_count === 0);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/referential-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: ReferentialProfileResponse = await response.json();
        if (!active) return;
        setProfile(data);
        setSelected(data.rules.filter((item) => item.applicable && (item.invalid_count ?? 0) > 0).map((item) => item.rule_index));
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить правила ссылочной целостности");
      } finally {
        if (active) setBusy(null);
      }
    })();
    return () => { active = false; };
  }, []);

  const invalidate = () => { setPreview(null); setConfirmed(false); setSuccess(null); setError(null); };
  const strategyAvailable = (candidate: Strategy) => selected.every((index) => profile?.rules.find((item) => item.rule_index === index)?.supported_actions.includes(candidate));
  const requestCorrection = async (apply: boolean) => {
    setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/referential-corrections"), {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ rule_indices: selected, strategy, apply }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const data: CorrectionResponse = await response.json();
      setPreview(data); setConfirmed(false);
      if (apply) {
        setProfile((current) => current ? { ...current, rules: data.profile } : current);
        setSelected(data.profile.filter((item) => item.applicable && (item.invalid_count ?? 0) > 0).map((item) => item.rule_index));
        setSuccess("Изменения применены, проверка запущена повторно"); onApplied();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось исправить ссылочную целостность");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section role="region" aria-label="Мастер исправления ссылочной целостности" className="h-[468px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll">
      {passed && <div role="status" className="mb-4 rounded bg-green-50 px-3 py-2 text-sm text-green-700"><p className="font-medium">Сиротские дочерние ключи не найдены.</p><p className="mt-0.5 text-xs">Исправление не требуется.</p></div>}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-md border border-neutral-200 p-3">
          <h4 className="text-sm font-semibold">1. Правила и связи</h4><p className="mt-1 text-xs text-neutral-500">Используются только явно заданные эталоны родительских ключей; отмечены связи с найденными сиротами.</p>
          <div className="mt-3 space-y-2">
            {busy === "load" && <p className="text-sm text-neutral-400">Загрузка правил…</p>}
            {profile && profile.rules.length === 0 && <div className="rounded bg-amber-50 p-2 text-sm text-amber-800"><p className="font-medium">Правила ссылочной целостности не заданы.</p><p className="mt-1 text-xs">Добавьте дочернюю колонку и справочник родительских ключей.</p><button type="button" onClick={onOpenRules} className="mt-2 rounded border border-amber-300 bg-white px-2 py-1 text-xs font-medium">Открыть управление правилами</button></div>}
            {profile?.rules.map((item) => <label key={item.rule_index} className="block rounded bg-neutral-50 p-2 text-sm"><span className="flex items-center gap-2"><input type="checkbox" checked={selected.includes(item.rule_index)} disabled={!item.applicable || !(item.invalid_count ?? 0)} onChange={() => { invalidate(); setSelected((current) => current.includes(item.rule_index) ? current.filter((value) => value !== item.rule_index) : [...current, item.rule_index]); }} aria-label={`Выбрать правило ${item.rule_name}`} className="accent-brand"/><span className="font-medium">{item.rule_name}</span><span className="ml-auto text-xs">нарушений: {item.invalid_count ?? "—"}</span></span><span className="mt-1 block text-[11px] text-neutral-500">{item.child_column || "Колонка не задана"} → {item.allowed_values.map(String).join(", ") || "справочник пуст"}</span>{item.invalid_values.length > 0 && <span className="mt-1 block text-xs text-amber-700">Сироты: {item.invalid_values.map((entry) => `${entry.value} × ${entry.count}`).join(", ")}</span>}{!item.applicable && <span className="mt-1 block text-xs text-neutral-500">{item.applicability_message}</span>}</label>)}
          </div>
        </div>
        <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Стратегия исправления</h4><p className="mt-1 text-xs text-neutral-500">Доступность зависит от справочника и валидных наблюдений.</p><select aria-label="Стратегия исправления ссылочной целостности" value={strategy} onChange={(event) => { invalidate(); setStrategy(event.target.value as Strategy); }} className="mt-3 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm">{(Object.keys(STRATEGIES) as Strategy[]).map((key) => <option key={key} value={key} disabled={!strategyAvailable(key)}>{STRATEGIES[key].label}</option>)}</select><p className="mt-2 text-xs text-neutral-600">{STRATEGIES[strategy].help}</p></div>
        <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на копии и не изменяет активный датасет.</p><button type="button" disabled={!selected.length || busy !== null || !strategyAvailable(strategy)} onClick={() => requestCorrection(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs"><p className="font-medium">Исправлено значений: {preview.total_changed}</p><p>Осталось сирот: {preview.total_still_invalid}</p>{preview.rows_removed > 0 && <p>Будет удалено строк: {preview.rows_removed}</p>}{preview.added_columns.length > 0 && <p>Добавлены колонки: {preview.added_columns.join(", ")}</p>}</div>}</div>
        <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Применение</h4><p className="mt-1 text-xs text-neutral-500">После подтверждения копия сохраняется атомарно, затем валидация запускается повторно.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} aria-label="Подтверждаю изменение активного датасета" className="mt-0.5 accent-brand"/>Подтверждаю изменение активного датасета</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => requestCorrection(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Применение…" : "Применить исправления"}</button></div>
      </div>
      {error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}
    </section>
  );
}
