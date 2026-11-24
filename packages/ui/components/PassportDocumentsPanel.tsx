"use client";

// packages/ui/components/PassportDocumentsPanel.tsx
//
// PGV-15 (spec_passport_graphics_visual.md §10.2/§8/§13, строка PGV-15):
// вкладка «Паспорта свойств» в «Документах исследования»:
//   (1) сохранённые печатные P01/P02 (PrintDocumentsPanel, family=passports);
//   (2) «Восстановить паспорта» -- пикер durable-источников
//       (GET passport-sources, PGV-13) -> context/trajectory/checkpoint ->
//       сохранённые точки/gaps -> один/все/сравнение ПО ВЕРСИИ ->
//       «Создать печатное представление» (POST passport-documents, §10.2;
//       frozen refs/pins, без capture и перерасчёта -- AC06);
//   (3) сводка resolved-точек/gaps/completeness (AC10/AC11/AC12) и
//       поллинг job -> предпросмотр/скачивание PNG или ZIP (PGV-14:
//       output_format/metadata_url готового job).
//
// ЧЕСТНОСТЬ (§3/§8): D02 «Паспорт источника» -- вид snapshot-каталога
// D01-D12 и НЕ есть P01 (печать из durable-источников) -- подпись
// разведена явно (критерий «D02 не P01», AC22). Default-режим пикера --
// «Комплект траектории» (§8: default «Траектория на выбранное
// подтверждение EDA»). Missing/corrupt точки -- честные статусы, не нули;
// reused-чекпоинт печатает подтверждение и исходный снимок (AC11).
// Доступность: role=status/alert, aria-pressed/aria-current, видимый
// focus, текстовые метки статусов (цвет не единственный носитель).

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/browserTransport";
import { getApiBase } from "../lib/apiClient";
import {
  cancelJob,
  getJob,
  renditionContentUrl,
} from "../lib/documentation";
import type { JobPayload } from "../lib/documentation";
import {
  listPassportSources,
  passportDocumentErrorText,
  requestPassportDocument,
  type PassportDocumentMode,
  type PassportDocumentOutcome,
  type PassportSourceCheckpoint,
  type PassportSourceSnapshot,
} from "../lib/passportDocuments";
import { PrintDocumentsPanel } from "./PrintDocumentsPanel";

const MODE_LABELS: Record<PassportDocumentMode, string> = {
  single: "Один паспорт",
  set: "Комплект траектории",
  compare: "Сравнение",
};

const STAGE_LABELS: Record<string, string> = {
  start: "старт",
  validation: "валидация",
  exit: "выход",
  modeling_entry: "вход в моделирование",
  panel: "панель",
  panel_entry: "вход в панель",
  confirmed: "подтверждение",
};

const CONTENT_STATUS_LABELS: Record<string, string> = {
  present: "содержимое сохранено",
  missing_artifact: "содержимое отсутствует (gap)",
  corrupt: "содержимое повреждено (gap)",
};

function stageLabel(stage: string | null): string {
  if (!stage) return "—";
  return STAGE_LABELS[stage] ?? stage;
}

function contentStatusLabel(status: string | null): string {
  if (!status) return "—";
  return CONTENT_STATUS_LABELS[status] ?? status;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU");
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return "—";
  if (size < 1024) return `${size} Б`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`;
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}

type SourcesPhase =
  | "idle"
  | "loading"
  | "ready"
  | "empty"
  | "forbidden"
  | "offline";

export function PassportDocumentsPanel({ runId }: { runId: string }) {
  // ── Пикер: режим по версии (§8 default -- траектория чекпоинта) ────
  const [mode, setMode] = useState<PassportDocumentMode>("set");
  const [sourcesPhase, setSourcesPhase] = useState<SourcesPhase>("idle");
  const [snapshots, setSnapshots] = useState<PassportSourceSnapshot[]>([]);
  const [checkpoints, setCheckpoints] = useState<PassportSourceCheckpoint[]>([]);
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const [compareRefs, setCompareRefs] = useState<string[]>([]);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<string | null>(null);
  const [sourcesError, setSourcesError] = useState<string | null>(null);

  // ── Создание печатного представления: job + сводка (§10.2) ─────────
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<PassportDocumentOutcome | null>(null);
  const [job, setJob] = useState<JobPayload | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewNote, setPreviewNote] = useState<string | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const pollTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
    },
    [],
  );

  const loadSources = useCallback(async () => {
    setSourcesPhase("loading");
    setSourcesError(null);
    const result = await listPassportSources(runId);
    if (!result.ok) {
      // Плоские коды §17/PGV-13: uniform 404 (AC18-дух), null -- offline.
      setSourcesPhase(result.status === null ? "offline" : "forbidden");
      setSourcesError(passportDocumentErrorText(result.status, result.error?.code ?? null));
      return;
    }
    const nextSnapshots = result.data?.snapshots ?? [];
    const nextCheckpoints = result.data?.checkpoints ?? [];
    setSnapshots(nextSnapshots);
    setCheckpoints(nextCheckpoints);
    setSourcesPhase(
      nextSnapshots.length === 0 && nextCheckpoints.length === 0 ? "empty" : "ready",
    );
    // Выбор по умолчанию: первый чекпоинт траектории (§8 default).
    setSelectedCheckpoint((current) => current ?? nextCheckpoints[0]?.checkpoint_id ?? null);
    setSelectedRef((current) => current ?? nextSnapshots[0]?.snapshot_ref ?? null);
    setCompareRefs([]);
  }, [runId]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  // ── Поллинг созданного job (§17) -> готовые байты/metadata ─────────
  useEffect(() => {
    if (!job || (job.state !== "queued" && job.state !== "rendering")) return;
    pollTimer.current = window.setTimeout(async () => {
      const result = await getJob(job.job_id);
      if (result.ok && result.data) setJob(result.data.job);
    }, 600);
    return () => {
      if (pollTimer.current !== null) {
        window.clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [job]);

  // ── Готовый job: предпросмотр соответствует скачиваемой версии ─────
  useEffect(() => {
    if (!job || job.state !== "ready" || !job.rendition) return;
    let cancelled = false;
    const loadPreview = async () => {
      const rendition = job.rendition!;
      const actualFormat = job.output_format ?? rendition.format;
      if (actualFormat === "png") {
        try {
          const resp = await apiFetch(renditionContentUrl(rendition.rendition_id), {
            credentials: "include",
          });
          if (!resp.ok) throw new Error("content_unavailable");
          const blob = await resp.blob();
          if (cancelled) {
            URL.revokeObjectURL(URL.createObjectURL(blob));
            return;
          }
          if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
          const url = URL.createObjectURL(blob);
          objectUrlRef.current = url;
          setPreviewUrl(url);
          setPreviewNote(null);
        } catch {
          setPreviewUrl(null);
          setPreviewNote(
            "Предпросмотр недоступен (файл не прочитан) — скачивание остаётся доступным.",
          );
        }
      } else if (job.metadata_url) {
        try {
          const resp = await apiFetch(`${getApiBase()}${job.metadata_url}`, {
            credentials: "include",
          });
          if (!resp.ok) throw new Error("metadata_unavailable");
          const metadata = (await resp.json()) as {
            page_count?: number;
            pages?: Array<Record<string, unknown>>;
          };
          if (cancelled) return;
          setPreviewUrl(null);
          setPreviewNote(
            `Комплект: ${metadata.page_count ?? metadata.pages?.length ?? "?"} стр. (ZIP). Состав комплекта не рисуется в браузере — скачайте ZIP; metadata JSON доступен по ссылке.`,
          );
        } catch {
          setPreviewUrl(null);
          setPreviewNote(
            "Metadata sidecar недоступен — состав комплекта не показывается; скачайте файл как есть.",
          );
        }
      }
    };
    void loadPreview();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.state, job?.output_format, job?.metadata_url]);

  const handleCreate = useCallback(async () => {
    setCreating(true);
    setCreateError(null);
    setOutcome(null);
    setJob(null);
    setPreviewUrl(null);
    setPreviewNote(null);
    // Явные ДВА снимка в compare имеют приоритет над чекпоинтом-траекторией;
    // иначе set/compare идут по чекпоинту (§8: траектория на выбранное
    // подтверждение EDA), single -- по единственному снимку.
    const explicitRefs =
      mode === "single"
        ? selectedRef
          ? [selectedRef]
          : []
        : mode === "compare"
          ? compareRefs
          : [];
    const useCheckpoint =
      mode !== "single" &&
      Boolean(selectedCheckpoint) &&
      !(mode === "compare" && explicitRefs.length === 2);
    const result = await requestPassportDocument({
      runId,
      mode,
      snapshotRefs: !useCheckpoint && explicitRefs.length > 0 ? explicitRefs : undefined,
      checkpointId: useCheckpoint ? selectedCheckpoint : null,
    });
    setCreating(false);
    if (!result.ok) {
      setCreateError(
        passportDocumentErrorText(result.status, result.error?.code ?? null),
      );
      return;
    }
    setOutcome(result.data ?? null);
    if (result.data?.job) setJob(toJobPayload(result.data.job));
  }, [compareRefs, mode, runId, selectedCheckpoint, selectedRef]);

  const handleCancelJob = useCallback(async () => {
    if (!job || (job.state !== "queued" && job.state !== "rendering")) return;
    await cancelJob(job.job_id);
    const result = await getJob(job.job_id);
    if (result.ok && result.data) setJob(result.data.job);
  }, [job]);

  const toggleCompareRef = useCallback((ref: string) => {
    setCompareRefs((previous) =>
      previous.includes(ref)
        ? previous.filter((item) => item !== ref)
        : [...previous, ref].slice(-2),
    );
  }, []);

  const canCreate = (() => {
    if (creating || sourcesPhase !== "ready") return false;
    if (mode === "single") return Boolean(selectedRef);
    if (mode === "set") return Boolean(selectedCheckpoint);
    // compare: чекпоинт-траектория ЛИБО ровно два явных снимка
    return Boolean(selectedCheckpoint) || compareRefs.length === 2;
  })();

  return (
    <div
      data-testid="pgv15-passports-panel"
      aria-label="Паспорта свойств ряда"
      className="flex flex-col gap-4"
    >
      {/* Критерий «D02 не P01»: явное разведение семейств (§10.2/AC22) */}
      <p
        data-testid="pgv15-d02-not-p01-note"
        className="rounded-lg border border-neutral-200 px-3 py-2 text-xs text-neutral-600 dark:border-neutral-700 dark:text-neutral-300"
      >
        Печать паспортов (P01/P02) строится из durable-источников без активной
        сессии. Это НЕ вид каталога D02 «Паспорт источника»: D02 остаётся
        снимком источника в каталоге документов D01–D12 и не переименовывается.
      </p>

      <PrintDocumentsPanel runId={runId} family="passports" />

      <section
        data-testid="pgv15-restore-picker"
        aria-label="Восстановить паспорта"
        className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-700"
      >
        <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
          Восстановить паспорта
        </h3>
        <p role="status" data-testid="pgv15-sources-status" className="mt-1 text-xs text-neutral-500">
          {sourcesPhase === "loading" && "Загрузка durable-источников…"}
          {sourcesPhase === "offline" && "Сеть недоступна — повторите попытку позже."}
          {sourcesPhase === "forbidden" && "Источники этого исследования недоступны вашему субъекту."}
          {sourcesPhase === "empty" && "Сохранённых паспортов/чекпоинтов нет — зафиксируйте паспорта в исследовании."}
          {sourcesPhase === "idle" && ""}
          {sourcesPhase === "ready" && `Снимков: ${snapshots.length}; чекпоинтов: ${checkpoints.length}.`}
        </p>
        {sourcesError && sourcesPhase !== "ready" && (
          <p role="alert" className="mt-1 text-xs text-neutral-700">
            {sourcesError}
          </p>
        )}

        {sourcesPhase === "ready" && (
          <>
            {/* Режимы «один/все/сравнение» по версии (критерий PGV-15) */}
            <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Режим восстановления">
              {(Object.keys(MODE_LABELS) as PassportDocumentMode[]).map((value) => (
                <button
                  key={value}
                  type="button"
                  data-testid={`pgv15-mode-${value}`}
                  aria-pressed={mode === value}
                  onClick={() => setMode(value)}
                  className={`rounded-full px-3 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                    mode === value
                      ? "bg-brand/20 font-medium text-brand"
                      : "bg-neutral-100 text-neutral-700 hover:bg-neutral-200 dark:bg-white/10 dark:text-neutral-200"
                  }`}
                >
                  {MODE_LABELS[value]}
                </button>
              ))}
            </div>

            {/* Версии: чекпоинты-траектории (set/compare, default §8) */}
            {(mode === "set" || mode === "compare") && checkpoints.length > 0 && (
              <table className="mt-2 w-full text-left text-xs">
                <caption className="sr-only">Чекпоинты подтверждения EDA</caption>
                <thead>
                  <tr className="text-neutral-500">
                    <th scope="col" className="py-1">Выбор</th>
                    <th scope="col" className="py-1">Этап</th>
                    <th scope="col" className="py-1">Подтверждён</th>
                    <th scope="col" className="py-1">Флаги/целостность</th>
                  </tr>
                </thead>
                <tbody>
                  {checkpoints.map((checkpoint) => (
                    <tr key={checkpoint.checkpoint_id} data-testid="pgv15-checkpoint-row">
                      <td className="py-1">
                        <input
                          type="radio"
                          name="pgv15-checkpoint"
                          aria-label={`Чекпоинт ${checkpoint.stage ?? "—"} от ${formatDate(checkpoint.confirmed_at)}`}
                          checked={selectedCheckpoint === checkpoint.checkpoint_id}
                          onChange={() => setSelectedCheckpoint(checkpoint.checkpoint_id)}
                          className="focus-visible:ring-2 focus-visible:ring-brand"
                        />
                      </td>
                      <td className="py-1">
                        {stageLabel(checkpoint.stage)}{" "}
                        <span className="text-neutral-400">{shortId(checkpoint.checkpoint_id)}</span>
                      </td>
                      <td className="py-1 text-neutral-500">{formatDate(checkpoint.confirmed_at)}</td>
                      <td className="py-1 text-neutral-500">
                        {checkpoint.flags?.reused ? "reused (исходный снимок)" : "новая фиксация"}
                        {checkpoint.integrity_status !== "ok"
                          ? `; целостность: ${checkpoint.integrity_status}`
                          : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* Версии: снимки (single; compare -- ровно два) */}
            {(mode === "single" || mode === "compare") && snapshots.length > 0 && (
              <table className="mt-3 w-full text-left text-xs">
                <caption className="sr-only">Сохранённые паспорта (версии)</caption>
                <thead>
                  <tr className="text-neutral-500">
                    <th scope="col" className="py-1">Выбор</th>
                    <th scope="col" className="py-1">Этап</th>
                    <th scope="col" className="py-1">Дата фиксации</th>
                    <th scope="col" className="py-1">Target/дата</th>
                    <th scope="col" className="py-1">Содержимое</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshots.map((snapshot) => {
                    const isCompareChecked = compareRefs.includes(snapshot.snapshot_ref);
                    return (
                      <tr key={snapshot.snapshot_ref} data-testid="pgv15-snapshot-row">
                        <td className="py-1">
                          {mode === "single" ? (
                            <input
                              type="radio"
                              name="pgv15-snapshot"
                              aria-label={`Паспорт ${stageLabel(snapshot.stage)} от ${formatDate(snapshot.captured_at)}`}
                              checked={selectedRef === snapshot.snapshot_ref}
                              onChange={() => setSelectedRef(snapshot.snapshot_ref)}
                              className="focus-visible:ring-2 focus-visible:ring-brand"
                            />
                          ) : (
                            <input
                              type="checkbox"
                              aria-label={`Для сравнения: паспорт ${stageLabel(snapshot.stage)}`}
                              checked={isCompareChecked}
                              onChange={() => toggleCompareRef(snapshot.snapshot_ref)}
                              className="focus-visible:ring-2 focus-visible:ring-brand"
                            />
                          )}
                        </td>
                        <td className="py-1">
                          {stageLabel(snapshot.stage)}{" "}
                          <span className="text-neutral-400">{shortId(snapshot.snapshot_ref)}</span>
                          {snapshot.universe ? ` (${snapshot.universe})` : ""}
                        </td>
                        <td className="py-1 text-neutral-500">{formatDate(snapshot.captured_at)}</td>
                        <td className="py-1 text-neutral-500">
                          {snapshot.target_column ?? "—"} / {snapshot.date_column ?? "—"}
                        </td>
                        <td className="py-1 text-neutral-500">
                          {contentStatusLabel(snapshot.content_status)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

            <button
              type="button"
              data-testid="pgv15-create-print"
              disabled={!canCreate}
              onClick={() => void handleCreate()}
              className="mt-3 rounded-lg border border-brand px-3 py-1.5 text-sm text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
            >
              {creating ? "Сборка печатного представления…" : "Создать печатное представление"}
            </button>
            {mode === "compare" && !selectedCheckpoint && compareRefs.length < 2 && (
              <p className="mt-1 text-xs text-neutral-500">
                Для сравнения выберите чекпоинт-траекторию либо ровно два снимка.
              </p>
            )}
            {createError && (
              <p role="alert" data-testid="pgv15-create-error" className="mt-2 text-sm text-red-600">
                {createError}
              </p>
            )}
          </>
        )}
      </section>

      {/* Сводка созданного представления (§10.2: точки/gaps/completeness) */}
      {outcome && (
        <section
          data-testid="pgv15-outcome"
          className="rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-700"
        >
          <p className="text-xs font-semibold text-neutral-700 dark:text-neutral-200">
            Печатное представление: {outcome.print_kind} ({MODE_LABELS[outcome.mode]}) —
            полнота: {outcome.completeness === "partial" ? "неполная (partial)" : "полная (complete)"}
          </p>
          {outcome.display && (
            <>
              <ul data-testid="pgv15-outcome-sections" className="ml-4 mt-1 list-disc text-xs text-neutral-600 dark:text-neutral-300">
                {outcome.display.sections.map((section, index) => (
                  <li key={`${section.snapshot_ref ?? "gap"}-${index}`}>
                    {stageLabel(section.stage)} — {contentStatusLabel(section.content_status)}
                    {section.snapshot_ref ? ` (${shortId(section.snapshot_ref)})` : ""}
                  </li>
                ))}
              </ul>
              {outcome.display.gaps.length > 0 && (
                <p className="mt-1 text-xs text-amber-600">
                  Явные пропуски (gaps): {outcome.display.gaps.length} — печатается баннером, не нулём.
                </p>
              )}
            </>
          )}
          {outcome.comparison?.cross_context && (
            <p className="mt-1 text-xs text-amber-600">
              Явный cross-context режим сравнения — сопоставимость промаркирована.
            </p>
          )}
        </section>
      )}

      {/* Job: состояние + предпросмотр/скачивание (PNG или ZIP, PGV-14) */}
      {job && (
        <section
          data-testid="pgv15-job-section"
          className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-700"
        >
          <p role="status" data-testid="pgv15-job-state" className="text-xs text-neutral-600">
            Задание печати:{" "}
            {job.state === "queued"
              ? "в очереди (queued)"
              : job.state === "rendering"
                ? "рендеринг (rendering)"
                : job.state === "ready"
                  ? "готово (ready)"
                  : job.state === "failed"
                    ? `ошибка (${job.error_code ?? "render_failed"})`
                    : "отменено (cancelled)"}
            {job.attempt > 1 ? ` (попытка ${job.attempt})` : ""}
          </p>
          {(job.state === "queued" || job.state === "rendering") && (
            <button
              type="button"
              data-testid="pgv15-cancel-job"
              onClick={() => void handleCancelJob()}
              className="mt-2 rounded-full border border-neutral-300 px-3 py-1 text-xs text-neutral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-600"
            >
              Отменить
            </button>
          )}
          {job.state === "ready" && job.rendition && (
            <>
              <p data-testid="pgv15-ready-downloads" className="mt-2 flex flex-wrap gap-2 text-xs">
                <a
                  href={renditionContentUrl(job.rendition.rendition_id)}
                  className="rounded-full bg-brand/10 px-3 py-1 font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  {(job.output_format ?? job.rendition.format) === "zip"
                    ? `Скачать все страницы PNG (ZIP) (${formatBytes(job.rendition.size_bytes)})`
                    : `Скачать PNG (${formatBytes(job.rendition.size_bytes)})`}
                </a>
                {job.metadata_url && (
                  <a
                    href={`${getApiBase()}${job.metadata_url}`}
                    className="rounded-full bg-neutral-100 px-3 py-1 text-neutral-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:bg-white/10 dark:text-neutral-200"
                  >
                    Metadata (JSON)
                  </a>
                )}
              </p>
              {previewUrl && (
                <img
                  data-testid="pgv15-outcome-preview"
                  src={previewUrl}
                  alt="Предпросмотр печатного представления (светлый печатный профиль)"
                  className="mt-2 max-h-[420px] w-auto max-w-full rounded border border-neutral-200 bg-white dark:border-neutral-700"
                />
              )}
              {previewNote && <p className="mt-2 text-xs text-neutral-500">{previewNote}</p>}
            </>
          )}
        </section>
      )}
    </div>
  );
}

function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 10 ? `${value.slice(0, 10)}…` : value;
}

function toJobPayload(job: PassportDocumentOutcome["job"]): JobPayload {
  return {
    job_id: job.job_id,
    run_id: "",
    snapshot_id: "",
    format: job.format,
    redaction_profile: "",
    revision_id: job.print_revision_id,
    rendition_id: null,
    state: (job.state as JobPayload["state"]) ?? "queued",
    error_code: job.error_code,
    attempt: job.attempt,
    created_at: job.created_at ?? "",
    updated_at: job.created_at ?? "",
    rendition: null,
  };
}
