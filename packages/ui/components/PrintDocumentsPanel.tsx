"use client";

// packages/ui/components/PrintDocumentsPanel.tsx
//
// PGV-15 (spec_passport_graphics_visual.md §10.2/§13, строка PGV-15):
// сохранённые печатные документы семейства (V01 «Научная визуализация» /
// P01 «Паспорта свойств ряда» / P02 «Сравнение паспортов») внутри
// «Документов исследования»: versioned-листинг (GET /runs/{run_id}/
// print-documents), готовые форматы с размерами, предпросмотр и честные
// скачивания:
//   - одна страница  -> «Скачать PNG» (content-маршрут, attachment);
//   - комплект/набор -> «Скачать все страницы PNG (ZIP)» + metadata JSON
//     (sidecar того же job, PGV-14);
//   - предпросмотр соответствует скачиваемой версии/профилю: PNG рисуется
//     как есть (blob через тот же защищённый content-маршрут); ZIP НЕ
//     рисуется клиентом -- печатается состав страниц из frozen metadata
//     (pgv.page_metadata/1) с честной подписью.
//
// Состояния §12.3: loading/ready/empty/forbidden (uniform 404)/offline/
// error; поллинг job «Запросить PNG» -- общий getJob (AC09: replay ready
// возвращает прежний job, дубли не создаются). Цвет НЕ единственный
// носитель статуса; aria-pressed/aria-current; видимый focus.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../lib/browserTransport";
import { getJob, renditionContentUrl } from "../lib/documentation";
import type { JobPayload } from "../lib/documentation";
import {
  listPrintDocuments,
  passportDocumentErrorText,
  requestPrintRendition,
  type PrintDocumentFamily,
  type PrintDocumentSummary,
  type PrintRenditionSummary,
} from "../lib/passportDocuments";

const PRINT_KIND_TITLES: Record<string, string> = {
  V01: "Научная визуализация (V01)",
  P01: "Паспорта свойств ряда (P01)",
  P02: "Сравнение паспортов (P02)",
};

const BASIS_LABELS: Record<string, string> = {
  visual_print_snapshot: "basis: печатный снимок визуализации",
  passport_print_snapshot: "basis: печатный вход паспортов",
  passport_comparison_snapshot: "basis: frozen сравнение паспортов",
};

const METADATA_KIND_LABELS: Record<string, string> = {
  png: "PNG (одна страница)",
  zip: "ZIP: все страницы PNG",
  json: "Metadata (JSON)",
};

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return "—";
  if (size < 1024) return `${size} Б`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`;
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU");
}

function shortHash(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 12 ? `${value.slice(0, 12)}…` : value;
}

type ListPhase = "loading" | "ready" | "empty" | "forbidden" | "offline" | "error";

interface PageMetaRow {
  index?: number;
  filename?: string;
  role?: string;
  size_bytes?: number;
  sha256?: string;
}

/** Разобранные данные предпросмотра (metadata-only; байты PNG -- blob URL). */
interface PreviewState {
  key: string;
  mainFormat: string;
  objectUrl: string | null;
  pages: PageMetaRow[];
  pageCount: number | null;
  profileId: string | null;
  note: string | null;
}

/** Абстрактный fetch blob через общий браузерный транспорт (credentials).
 * metadata_url сервера относителен корню API -- prepend getApiBase(). */
async function fetchBlobUrl(url: string): Promise<string> {
  const resp = await apiFetch(url, { credentials: "include" });
  if (!resp.ok) {
    throw Object.assign(new Error("content_unavailable"), { status: resp.status });
  }
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
}

export function PrintDocumentsPanel({
  runId,
  family,
}: {
  runId: string;
  family: PrintDocumentFamily;
}) {
  const [phase, setPhase] = useState<ListPhase>("loading");
  const [documents, setDocuments] = useState<PrintDocumentSummary[]>([]);
  const [errorText, setErrorText] = useState<string | null>(null);
  // Активный job «Запросить PNG» по print_revision_id (поллинг статуса).
  const [jobs, setJobs] = useState<Record<string, JobPayload>>({});
  const [jobError, setJobError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [previewLoading, setPreviewLoading] = useState<string | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const pollTimer = useRef<number | null>(null);

  const releaseObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  useEffect(() => releaseObjectUrl, [releaseObjectUrl]);

  const load = useCallback(async () => {
    setPhase("loading");
    setErrorText(null);
    const result = await listPrintDocuments(runId);
    if (!result.ok) {
      // Плоские коды §17: uniform 404 (чужой/несуществующий run) --
      // безальтернативный запрет (R09/AC18); null -- offline.
      setPhase(result.status === null ? "offline" : "forbidden");
      setErrorText(passportDocumentErrorText(result.status, result.error?.code ?? null));
      return;
    }
    const all = result.data?.documents ?? [];
    const familyDocs = all.filter((document) => document.family === family);
    setDocuments(familyDocs);
    setPhase(familyDocs.length === 0 ? "empty" : "ready");
  }, [runId, family]);

  useEffect(() => {
    void load();
  }, [load]);

  // ── Поллинг активных jobs («Запросить PNG», AC09 replay ready) ──────
  const activeJobEntry = useMemo(
    () =>
      Object.entries(jobs).find(
        ([, job]) => job.state === "queued" || job.state === "rendering",
      ),
    [jobs],
  );
  useEffect(() => {
    if (!activeJobEntry) return;
    const [revisionId, job] = activeJobEntry;
    pollTimer.current = window.setTimeout(async () => {
      const result = await getJob(job.job_id);
      if (result.ok && result.data) {
        setJobs((previous) => ({ ...previous, [revisionId]: result.data!.job }));
        if (result.data.job.state === "ready") void load();
      } else if (result.status !== null && result.status >= 400) {
        setJobError(passportDocumentErrorText(result.status, null));
        setJobs((previous) => {
          const next = { ...previous };
          delete next[revisionId];
          return next;
        });
      }
    }, 600);
    return () => {
      if (pollTimer.current !== null) {
        window.clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [activeJobEntry, load]);

  const handleRequestPng = useCallback(
    async (printRevisionId: string) => {
      setJobError(null);
      const result = await requestPrintRendition(printRevisionId, "png");
      if (!result.ok) {
        setJobError(
          passportDocumentErrorText(result.status, result.error?.code ?? null),
        );
        return;
      }
      // Поллинг вернёт полный DTO (включая rendition/metadata_url).
      const queued: JobPayload = {
        job_id: result.data!.job.job_id,
        state: (result.data!.job.state as JobPayload["state"]) ?? "queued",
        run_id: "",
        snapshot_id: "",
        format: "png",
        redaction_profile: "",
        revision_id: printRevisionId,
        rendition_id: null,
        error_code: null,
        attempt: 1,
        created_at: "",
        updated_at: "",
        rendition: null,
      };
      setJobs((previous) => ({ ...previous, [printRevisionId]: queued }));
    },
    [],
  );

  const handlePreview = useCallback(
    async (revisionId: string, main: PrintRenditionSummary, meta: PrintRenditionSummary | null) => {
      const key = `${revisionId}:${main.rendition_id}`;
      setPreviewLoading(key);
      releaseObjectUrl();
      try {
        if (main.format === "png") {
          const url = await fetchBlobUrl(renditionContentUrl(main.rendition_id));
          objectUrlRef.current = url;
          setPreview({
            key,
            mainFormat: "png",
            objectUrl: url,
            pages: [],
            pageCount: 1,
            profileId: null,
            note: null,
          });
        } else if (meta) {
          // ZIP не рисуется: состав страниц печатается из frozen metadata.
          const resp = await apiFetch(renditionContentUrl(meta.rendition_id), {
            credentials: "include",
          });
          if (!resp.ok) throw Object.assign(new Error("metadata_unavailable"), { status: resp.status });
          const metadata = (await resp.json()) as {
            page_count?: number;
            profile_id?: string;
            pages?: PageMetaRow[];
          };
          setPreview({
            key,
            mainFormat: "zip",
            objectUrl: null,
            pages: metadata.pages ?? [],
            pageCount: metadata.page_count ?? metadata.pages?.length ?? null,
            profileId: metadata.profile_id ?? null,
            note: "Комплект страниц не рисуется в браузере: состав из frozen metadata; скачайте ZIP для печати.",
          });
        } else {
          setPreview({
            key,
            mainFormat: main.format,
            objectUrl: null,
            pages: [],
            pageCount: null,
            profileId: null,
            note: "Metadata sidecar недоступен -- состав комплекта не показывается; скачайте файл как есть.",
          });
        }
      } catch {
        setPreview({
          key,
          mainFormat: main.format,
          objectUrl: null,
          pages: [],
          pageCount: null,
          profileId: null,
          note: "Предпросмотр недоступен (файл не прочитан) — скачивание остаётся доступным.",
        });
      } finally {
        setPreviewLoading(null);
      }
    },
    [releaseObjectUrl],
  );

  const status = (() => {
    if (phase === "loading") return "Загрузка печатных документов…";
    if (phase === "offline")
      return "Сервис документирования недоступен — повторите попытку позже";
    if (phase === "forbidden")
      return "Доступ запрещён — печатные документы этого исследования недоступны вашему субъекту";
    return null;
  })();

  return (
    <div
      data-testid="pgv15-print-documents"
      aria-label="Печатные документы"
      className="flex flex-col gap-3"
    >
      <p role="status" data-testid="pgv15-print-documents-status" className="text-xs text-neutral-500">
        {status ?? ""}
      </p>

      {phase === "empty" && (
        <p className="text-sm text-neutral-500">
          {family === "passports"
            ? "Печатных паспортов (P01/P02) пока нет — восстановите паспорта из durable-источников ниже."
            : "Сохранённых печатных визуализаций (V01) пока нет — экспорт создаётся действием «Скачать PNG» на остановках исследования."}
        </p>
      )}

      {errorText && phase !== "ready" && (
        <p role="alert" data-testid="pgv15-print-documents-error" className="text-sm text-neutral-700">
          {errorText}
        </p>
      )}

      {phase === "ready" &&
        documents.map((document) => (
          <section
            key={document.document_id}
            data-testid={`pgv15-print-document-${document.print_kind}`}
            className="rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-700"
          >
            <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
              {PRINT_KIND_TITLES[document.print_kind] ?? document.kind_title}
            </h3>
            <table className="mt-2 w-full text-left text-xs">
              <caption className="sr-only">
                Версии печатного документа {document.print_kind}
              </caption>
              <thead>
                <tr className="text-neutral-500">
                  <th scope="col" className="py-1">Версия</th>
                  <th scope="col" className="py-1">Профиль</th>
                  <th scope="col" className="py-1">Создана</th>
                  <th scope="col" className="py-1">Готовые форматы</th>
                  <th scope="col" className="py-1">Действия</th>
                </tr>
              </thead>
              <tbody>
                {document.revisions.map((revision) => {
                  const main =
                    revision.renditions.find((item) => item.format === "png") ??
                    revision.renditions.find((item) => item.format === "zip") ??
                    null;
                  const meta =
                    revision.renditions.find((item) => item.format === "json") ?? null;
                  const job = jobs[revision.print_revision_id];
                  return (
                    <tr key={revision.print_revision_id} data-testid="pgv15-print-revision-row">
                      <td className="py-1 font-medium">v{revision.version_no}</td>
                      <td className="py-1 text-neutral-500">{revision.profile_id}</td>
                      <td className="py-1 text-neutral-500">{formatDate(revision.created_at)}</td>
                      <td className="py-1 text-neutral-500">
                        {main ? (
                          <>
                            <a
                              data-testid="pgv15-download-main"
                              href={renditionContentUrl(main.rendition_id)}
                              className="rounded-full bg-brand/10 px-3 py-1 font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                            >
                              {main.format === "zip"
                                ? "Скачать все страницы PNG (ZIP)"
                                : "Скачать PNG"}{" "}
                              ({formatBytes(main.size_bytes)})
                            </a>
                            {meta && (
                              <>
                                {" "}
                                <a
                                  data-testid="pgv15-download-metadata"
                                  href={renditionContentUrl(meta.rendition_id)}
                                  className="rounded-full bg-neutral-100 px-3 py-1 text-neutral-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:bg-white/10 dark:text-neutral-200"
                                >
                                  Metadata (JSON)
                                </a>
                              </>
                            )}
                            <span className="sr-only"> hash {shortHash(main.content_sha256)}</span>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="py-1">
                        <div className="flex flex-wrap gap-1">
                          {main && (
                            <button
                              type="button"
                              data-testid="pgv15-preview-button"
                              onClick={() => void handlePreview(revision.print_revision_id, main, meta)}
                              className="rounded-full border border-neutral-300 px-2 py-1 text-neutral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-600"
                            >
                              Предпросмотр
                            </button>
                          )}
                          {!main && !job && (
                            <button
                              type="button"
                              data-testid="pgv15-request-png"
                              onClick={() => void handleRequestPng(revision.print_revision_id)}
                              className="rounded-full bg-brand/10 px-2 py-1 font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                            >
                              Запросить PNG
                            </button>
                          )}
                          {job && (job.state === "queued" || job.state === "rendering") && (
                            <span role="status" className="text-neutral-500">
                              {job.state === "queued" ? "В очереди…" : "Рендеринг…"}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="mt-1 text-xs text-neutral-500">
              {BASIS_LABELS[document.revisions[0]?.basis_kind ?? ""] ?? document.revisions[0]?.basis_kind}
            </p>
            {jobError && (
              <p role="alert" data-testid="pgv15-job-error" className="mt-1 text-xs text-red-600">
                {jobError}
              </p>
            )}
          </section>
        ))}

      {preview && (
        <div
          data-testid="pgv15-print-preview"
          className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-700"
        >
          <p className="text-xs font-semibold text-neutral-700 dark:text-neutral-200">
            Предпросмотр ({preview.mainFormat === "png" ? "PNG, светлая печать" : "комплект страниц"})
          </p>
          {preview.mainFormat === "png" && preview.objectUrl && (
            <img
              data-testid="pgv15-preview-image"
              src={preview.objectUrl}
              alt="Предпросмотр печатного представления (светлый печатный профиль)"
              className="mt-2 max-h-[420px] w-auto max-w-full rounded border border-neutral-200 bg-white dark:border-neutral-700"
            />
          )}
          {preview.mainFormat === "zip" && (
            <ul data-testid="pgv15-preview-pages" className="ml-4 mt-2 list-disc text-xs text-neutral-600 dark:text-neutral-300">
              {preview.pages.map((page, index) => (
                <li key={page.filename ?? index}>
                  {page.filename ?? `страница ${page.index ?? index + 1}`}
                  {page.role ? ` — роль ${page.role}` : ""}
                  {page.size_bytes ? `, ${formatBytes(page.size_bytes)}` : ""}
                </li>
              ))}
              {preview.pages.length === 0 && <li>Состав страниц недоступен</li>}
            </ul>
          )}
          {preview.note && (
            <p className="mt-2 text-xs text-neutral-500">{preview.note}</p>
          )}
        </div>
      )}
      {previewLoading && (
        <p role="status" className="text-xs text-neutral-500">Загрузка предпросмотра…</p>
      )}
    </div>
  );
}
