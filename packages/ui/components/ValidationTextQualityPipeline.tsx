"use client";

import { useEffect, useState } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import type { TextQualityProfileItem, TextQualityProfileResponse } from "./ValidationTextQualityOverview";

type Strategy = "normalize" | "replace_null" | "drop_rows" | "replace_unknown" | "flag";
interface CorrectionResponse {
  applied: boolean; strategy: Strategy; total_violations: number; total_changed: number;
  total_still_invalid: number; rows_removed: number; added_columns: string[];
  columns: Array<{ column: string; invalid_count: number; changed_count: number; still_invalid: number; flag_column: string | null }>;
  profile: TextQualityProfileItem[];
}

const STRATEGIES: Record<Strategy, { label: string; help: string }> = {
  normalize: { label: "Очистить и нормализовать", help: "Удаляются управляющие и повреждённые символы, края и повторы пробелов; регистр приводится к нижнему." },
  replace_null: { label: "Заменить нарушения пропусками", help: "Проблемные значения становятся пропусками для последующей обработки." },
  replace_unknown: { label: "Заменить на «Неизвестно»", help: "Подходит для категориальных подписей, если допустимо явное служебное значение." },
  drop_rows: { label: "Удалить строки с нарушениями", help: "Удаляется объединение строк, нарушающих любую отмеченную колонку." },
  flag: { label: "Только отметить флагом", help: "Исходный текст сохраняется; добавляется колонка *_text_valid." },
};

async function responseDetail(response: Response) {
  try { const body = await response.json(); if (typeof body?.detail === "string") return body.detail; } catch { /* fallback */ }
  return `Не удалось выполнить операцию (HTTP ${response.status})`;
}

export function ValidationTextQualityPipeline({ onApplied }: { onApplied: () => void }) {
  const [profile, setProfile] = useState<TextQualityProfileResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [strategy, setStrategy] = useState<Strategy>("normalize");
  const [preview, setPreview] = useState<CorrectionResponse | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"load" | "preview" | "apply" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const passed = Boolean(profile?.columns.length) && profile!.columns.every((item) => item.invalid_count === 0);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/text-quality-profile"), { credentials: "include" });
        if (!response.ok) throw new Error(await responseDetail(response));
        const data: TextQualityProfileResponse = await response.json();
        if (!active) return;
        setProfile(data);
        setSelected(data.columns.filter((item) => item.invalid_count > 0).map((item) => item.column));
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : "Не удалось загрузить профиль целостности текста");
      } finally { if (active) setBusy(null); }
    })();
    return () => { active = false; };
  }, []);

  const invalidate = () => { setPreview(null); setConfirmed(false); setSuccess(null); setError(null); };
  const requestCorrection = async (apply: boolean) => {
    setBusy(apply ? "apply" : "preview"); setError(null); setSuccess(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/text-quality-corrections"), {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ columns: selected, strategy, apply }),
      });
      if (!response.ok) throw new Error(await responseDetail(response));
      const data: CorrectionResponse = await response.json();
      setPreview(data); setConfirmed(false);
      if (apply) {
        setProfile((current) => current ? { ...current, columns: data.profile } : current);
        setSelected(data.profile.filter((item) => item.invalid_count > 0).map((item) => item.column));
        setSuccess("Изменения применены, проверка запущена повторно"); onApplied();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось исправить целостность текста");
    } finally { setBusy(null); }
  };

  return (
    <section role="region" aria-label="Мастер исправления целостности текста" className="h-[420px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 feed-scroll">
      {passed && <div role="status" className="mb-4 rounded bg-green-50 px-3 py-2 text-sm text-green-700"><p className="font-medium">Нарушения целостности текста не найдены.</p><p className="mt-0.5 text-xs">Исправление не требуется.</p></div>}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">1. Колонки и нарушения</h4><p className="mt-1 text-xs text-neutral-500">Отмечены текстовые колонки, где найдены мусор, пустые значения, длина, пробелы или несоответствие шаблону.</p><div className="mt-3 space-y-2">{busy === "load" && <p className="text-sm text-neutral-400">Загрузка профиля…</p>}{profile?.columns.length === 0 && <p className="rounded bg-neutral-50 p-2 text-sm text-neutral-600">В датасете нет текстовых колонок.</p>}{profile?.columns.map((item) => <label key={item.column} className="block rounded bg-neutral-50 p-2 text-sm"><span className="flex items-center gap-2"><input type="checkbox" checked={selected.includes(item.column)} disabled={!item.invalid_count} onChange={() => { invalidate(); setSelected((current) => current.includes(item.column) ? current.filter((value) => value !== item.column) : [...current, item.column]); }} aria-label={`Выбрать колонку ${item.column}`} className="accent-brand"/><span className="font-medium">{item.column}</span><span className="ml-auto text-xs">нарушений: {item.invalid_count}</span></span>{item.invalid_examples.length > 0 && <span className="mt-1 block truncate text-xs text-amber-700">Примеры: {item.invalid_examples.join(" | ")}</span>}</label>)}</div></div>
        <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">2. Стратегия исправления</h4><p className="mt-1 text-xs text-neutral-500">Стратегии переиспользуют бизнес-логику Streamlit и применяются только к отмеченным нарушениям.</p><select aria-label="Стратегия исправления целостности текста" value={strategy} onChange={(event) => { invalidate(); setStrategy(event.target.value as Strategy); }} className="mt-3 w-full rounded border border-neutral-300 bg-white px-2 py-2 text-sm">{(Object.keys(STRATEGIES) as Strategy[]).map((key) => <option key={key} value={key}>{STRATEGIES[key].label}</option>)}</select><p className="mt-2 text-xs text-neutral-600">{STRATEGIES[strategy].help}</p></div>
        <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">3. Предпросмотр</h4><p className="mt-1 text-xs text-neutral-500">Расчёт выполняется на глубокой копии и не меняет активный датасет.</p><button type="button" disabled={!selected.length || busy !== null} onClick={() => requestCorrection(false)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "preview" ? "Выполняется…" : "Предпросмотр изменений"}</button>{preview && <div className="mt-3 rounded bg-neutral-50 p-2 text-xs"><p className="font-medium">Исправлено значений: {preview.total_changed}</p><p>Осталось нарушений: {preview.total_still_invalid}</p>{preview.rows_removed > 0 && <p>Будет удалено строк: {preview.rows_removed}</p>}{preview.added_columns.length > 0 && <p>Добавлены колонки: {preview.added_columns.join(", ")}</p>}</div>}</div>
        <div className="rounded-md border border-neutral-200 p-3"><h4 className="text-sm font-semibold">4. Применение</h4><p className="mt-1 text-xs text-neutral-500">После подтверждения копия сохраняется атомарно, затем валидация запускается повторно.</p><label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={!preview || busy !== null} onChange={(event) => setConfirmed(event.target.checked)} aria-label="Подтверждаю изменение активного датасета" className="mt-0.5 accent-brand"/>Подтверждаю изменение активного датасета</label><button type="button" disabled={!preview || !confirmed || busy !== null} onClick={() => requestCorrection(true)} className="mt-3 w-full rounded bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-40">{busy === "apply" ? "Применение…" : "Применить исправления"}</button></div>
      </div>
      {error && <p role="alert" className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}{success && <p role="status" className="mt-3 rounded bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}
    </section>
  );
}
