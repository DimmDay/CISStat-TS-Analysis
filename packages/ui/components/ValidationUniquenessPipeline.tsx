"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { UniquenessProfile, UniquenessProfileResponse } from "./ValidationUniquenessOverview";
import { uniquenessKeyLabel } from "./ValidationUniquenessOverview";


type Strategy = "keep_first" | "keep_last" | "drop_all" | "aggregate" | "flag";

interface CorrectionResponse {
  applied: boolean;
  strategy: Strategy;
  duplicate_rows: number;
  redundant_rows: number;
  rows_changed: number;
  rows_removed: number;
  still_duplicate_rows: number;
  added_columns: string[];
  profile: UniquenessProfile;
}

const STRATEGIES: Record<Strategy, { label: string; help: string }> = {
  keep_first: { label: "Удалить лишние копии — оставить первую", help: "Сохраняется первая строка каждой группы; удаляются только последующие копии." },
  keep_last: { label: "Удалить лишние копии — оставить последнюю", help: "Сохраняется последняя строка каждой группы." },
  drop_all: { label: "Удалить все строки групп дублей", help: "Удаляются и исходная строка, и все её копии. Используйте только при недостоверности всей группы." },
  aggregate: { label: "Агрегировать: mean / first", help: "По ключу вычисляется среднее числовых полей, для остальных берётся первое значение." },
  flag: { label: "Добавить флаг уникальности", help: "Значения не меняются; добавляется колонка uniqueness_valid." },
};

async function responseDetail(response: Response) {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

export function ValidationUniquenessPipeline({ onApplied }: { onApplied: () => void }) {
  const [profileResponse, setProfileResponse] = useState<UniquenessProfileResponse | null>(null);
  const [strategy, setStrategy] = useState<Strategy>("keep_first");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/uniqueness-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data = await response.json();
        if (active) setProfileResponse(data);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль");
      } finally { if (active) setBusy(null); }
    })();
    return () => { active = false; };
  }, []);

  const profile = profileResponse?.profile;
  const execute = async (apply: boolean) => {
    setBusy(apply ? "apply" : "preview"); setError(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/uniqueness-corrections"), {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ strategy, apply }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const result = await response.json();
      setPreview(result);
      if (apply) onApplied();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось выполнить операцию"); }
    finally { setBusy(null); }
  };

  if (busy === "load") return <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light text-sm text-neutral-500">Загрузка мастера…</div>;
  if (!profile?.applicable) return <div role="region" aria-label="Мастер исправления уникальности" className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-600">{profile?.applicability_message || "Правило уникальности неприменимо. Проверьте составной ключ в «Управлении правилами»."}</div>;
  if ((profile.duplicate_rows ?? 0) === 0) return <div role="region" aria-label="Мастер исправления уникальности" className="flex h-[468px] flex-col items-center justify-center rounded-lg border border-green-100 bg-green-50 px-8 text-center"><p className="font-medium text-green-700">Дубликаты не найдены</p><p className="mt-2 text-sm text-neutral-600">Исправление не требуется. Активный ключ: {uniquenessKeyLabel(profile)}.</p></div>;

  const available = (Object.keys(STRATEGIES) as Strategy[]).filter((item) => profile.supported_actions.includes(item));
  return (
    <section role="region" aria-label="Мастер исправления уникальности" className="grid h-[468px] grid-cols-2 gap-3 overflow-y-auto rounded-lg border border-neutral-200 bg-white p-3 feed-scroll">
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Ключ и группы дублей</h4><p className="mt-2 text-xs text-neutral-600">{uniquenessKeyLabel(profile)}</p><p className="mt-2 text-sm font-medium text-amber-700">{profile.duplicate_groups} группа · {profile.duplicate_rows} строки · {profile.redundant_rows} лишняя копия</p><p className="mt-1 text-[11px] text-neutral-500">Удаление keep first/last затронет только лишние копии, а не все строки групп.</p></div>
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Стратегия исправления</h4><select aria-label="Стратегия исправления уникальности" value={strategy} onChange={(event) => { setStrategy(event.target.value as Strategy); setPreview(null); setConfirmed(false); }} className="mt-2 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm">{available.map((item) => <option key={item} value={item}>{STRATEGIES[item].label}</option>)}</select><p className="mt-2 text-xs text-neutral-500">{STRATEGIES[strategy].help}</p></div>
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><p className="mt-1 text-xs text-neutral-500">Выполняется на глубокой копии и не изменяет активный датасет.</p><button type="button" disabled={busy !== null} onClick={() => void execute(false)} className="mt-3 w-full rounded bg-brand-light px-3 py-2 text-sm font-medium text-brand disabled:opacity-50">{busy === "preview" ? "Расчёт…" : "Предпросмотр изменений"}</button>{preview && <div className="mt-2 space-y-1 text-xs text-neutral-700"><p>Строк в дублях до: {preview.duplicate_rows}</p><p>Строк в дублях после: {preview.still_duplicate_rows}</p><p>Будет удалено строк: {preview.rows_removed}</p></div>}</div>
      <div className="rounded border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Применение</h4><label className="mt-3 flex items-start gap-2 text-xs text-neutral-600"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />Подтверждаю изменение активного датасета</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => void execute(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Применение…" : "Применить исправления"}</button><p className="mt-2 text-[11px] text-neutral-500">После применения общая валидация запускается повторно.</p></div>
      {error && <p role="alert" className="col-span-2 rounded bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
    </section>
  );
}
