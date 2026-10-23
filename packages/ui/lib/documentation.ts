// packages/ui/lib/documentation.ts
//
// DOCLOG-4 (спека §12, §17): клиент API документирования /v1/documentation.
// Типы -- контракты роутера apps/api/routers/documentation.py; все запросы
// credentials: include (cookie-сессия -- субъект-суррогат DOCLOG-0).
// Каждый клиент возвращает дискриминированный результат
// { ok: true, data } | { ok: false, status } -- UI честно рендерит
// негативные состояния §12.3 (forbidden/offline/409), не бросая исключения
// в слой компонентов.

import { getApiBase } from "./apiClient";

/** База /v1/documentation (тот же first-party /api-прокси в проде). */
export function documentationApiUrl(path: string): string {
  return `${getApiBase()}/v1/documentation${path}`;
}

// ── Типы контракта (§11 состояния генерации, §17 ответы) ────────────

export type RenditionState = "ready" | "failed";
export type JobState = "queued" | "rendering" | "ready" | "failed" | "cancelled";
export type CompletenessStatus = "complete" | "partial";

export interface RenditionSummary {
  rendition_id: string;
  revision_id: string;
  snapshot_id: string;
  run_id: string;
  format: string;
  redaction_profile: string;
  state: RenditionState;
  media_type: string;
  size_bytes: number;
  content_sha256: string;
  storage_key: string;
  job_id: string | null;
  created_by: string | null;
  created_at: string;
}

export interface RevisionSummary {
  revision_id: string;
  document_id: string;
  snapshot_id: string;
  run_id: string;
  version_no: number;
  created_by: string | null;
  created_at: string;
  captured_at?: string | null;
  completeness_status?: CompletenessStatus | null;
  renditions: RenditionSummary[];
}

export interface DocumentSummary {
  document_id: string;
  run_id: string;
  kind_code: string;
  title: string;
  current_revision_id: string | null;
  created_by: string | null;
  created_at: string;
  revisions: RevisionSummary[];
}

export interface SnapshotClaim {
  text: string;
  event_refs: string[];
  result_refs: string[];
  validity: "current" | "stale" | "unknown";
  evidence_level: string | null;
}

export interface SnapshotSection {
  code: string;
  kind: string;
  title: string;
  methodology_stage: string | null;
  claims: SnapshotClaim[];
}

/** Frozen ReportSnapshot (doclog.report_snapshot/1, §10.1). */
export interface SnapshotPayload {
  schema_version: string;
  snapshot_id: string;
  research_run_id: string;
  context_id: string | null;
  data_revision: number | null;
  data_ref: string | null;
  data_digest: { algorithm: string; value: string } | null;
  source_cutoff: Record<string, unknown>;
  captured_at: string;
  template: { id: string; version: string };
  knowledge_version: string | null;
  locale: string;
  display_timezone: string;
  classification: string;
  redaction_profile: string;
  completeness: { status: CompletenessStatus; missing_refs: string[] };
  reproducibility: { status: string; reasons: string[] };
  sections: SnapshotSection[];
  dependencies: string[];
  approval: null;
}

export interface JobPayload {
  job_id: string;
  run_id: string;
  snapshot_id: string;
  format: string;
  redaction_profile: string;
  revision_id: string | null;
  rendition_id: string | null;
  state: JobState;
  error_code: string | null;
  attempt: number;
  created_at: string;
  updated_at: string;
  rendition: RenditionSummary | null;
}

export interface ApiResult<T> {
  /** false -- HTTP-отказ (403/404/409/400) либо сеть недоступна. */
  ok: boolean;
  /** HTTP-статус; null -- сеть/исключение (offline, §12.3). */
  status: number | null;
  /** Тело ответа (только при ok=true). */
  data?: T;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const resp = await fetch(url, {
      credentials: "include",
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
    if (!resp.ok) {
      return { ok: false, status: resp.status };
    }
    const data = (await resp.json()) as T;
    return { ok: true, status: resp.status, data };
  } catch {
    // Сеть недоступна -- честный offline (§12.3: offline не «нет документов»).
    return { ok: false, status: null };
  }
}

// ── Клиенты §17 ─────────────────────────────────────────────────────

export function listDocuments(
  runId: string,
  kind?: string | null,
): Promise<ApiResult<{ run_id: string; documents: DocumentSummary[] }>> {
  const suffix = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return requestJson(documentationApiUrl(`/runs/${encodeURIComponent(runId)}/documents${suffix}`));
}

export function createDraft(
  runId: string,
  kind: string,
  options?: { refresh?: boolean; idempotency_key?: string },
): Promise<ApiResult<{ document: DocumentSummary; revision: RevisionSummary }>> {
  return requestJson(documentationApiUrl(`/runs/${encodeURIComponent(runId)}/documents`), {
    method: "POST",
    body: JSON.stringify({
      kind,
      refresh: options?.refresh ?? false,
      ...(options?.idempotency_key ? { idempotency_key: options.idempotency_key } : {}),
    }),
  });
}

export function getRevision(
  revisionId: string,
): Promise<ApiResult<{
  revision: RevisionSummary;
  document: DocumentSummary;
  snapshot: SnapshotPayload;
  renditions: RenditionSummary[];
}>> {
  return requestJson(documentationApiUrl(`/revisions/${encodeURIComponent(revisionId)}`));
}

export function requestRendition(
  revisionId: string,
  format: string,
): Promise<ApiResult<{ job: JobPayload; status_url: string }>> {
  return requestJson(documentationApiUrl(`/revisions/${encodeURIComponent(revisionId)}/renditions`), {
    method: "POST",
    body: JSON.stringify({ format }),
  });
}

export function getJob(jobId: string): Promise<ApiResult<{ job: JobPayload }>> {
  return requestJson(documentationApiUrl(`/jobs/${encodeURIComponent(jobId)}`));
}

export function cancelJob(jobId: string): Promise<ApiResult<{ job: JobPayload }>> {
  return requestJson(documentationApiUrl(`/jobs/${encodeURIComponent(jobId)}/cancel`), {
    method: "POST",
  });
}

/** Прямая ссылка на байты готового rendition (GET content, §17). */
export function renditionContentUrl(renditionId: string): string {
  return documentationApiUrl(`/renditions/${encodeURIComponent(renditionId)}/content`);
}

/** Прямая ссылка на preview HTML (GET, §17) -- для iframe src, не fetch. */
export function revisionPreviewUrl(revisionId: string): string {
  return documentationApiUrl(`/revisions/${encodeURIComponent(revisionId)}/preview`);
}
