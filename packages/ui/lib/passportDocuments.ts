import { parseExportErrorBody, exportAuthorityErrorText } from "./exportErrors";
import { apiFetch } from "./browserTransport";
// packages/ui/lib/passportDocuments.ts
//
// PGV-15 (spec_passport_graphics_visual.md §10.2/§11/§13, строка PGV-15):
// клиент пикера/предпросмотра/PNG печатных семейств «Документов
// исследования». Контракты -- роутер apps/api/routers/documentation.py:
//   GET  /v1/documentation/runs/{run_id}/passport-sources   (PGV-13, пикер)
//   POST /v1/documentation/runs/{run_id}/passport-documents (PGV-13, one/all/compare)
//   GET  /v1/documentation/runs/{run_id}/print-documents    (PGV-15, листинг)
//   POST /v1/documentation/print-revisions/{id}/renditions  (PGV-09, replay ready)
// Поллинг/отмена/скачивание/metadata -- общий клиент lib/documentation
// (jobs/{id}, renditions/{id}/content, output_format/metadata_url -- PGV-14).
//
// Каждый клиент возвращает дискриминированный результат
// { ok, status, data?, error? } -- UI честно рендерит негативные
// состояния §12.3 (плоские коды §17/PGV-13), не бросая исключения в слой
// компонентов. Наука не запускается (AC06): клиенты только ставят
// документные jobs и читают frozen-факты.

import { getApiBase } from "./apiClient";
import { documentationApiUrl } from "./documentation";

export type PassportDocumentMode = "single" | "set" | "compare";
export type PrintDocumentFamily = "visuals" | "passports";
export type PrintRenditionFormat = "png" | "zip" | "json";

/** Запись pgv.passport_history/1 в листинге пикера (§8; контент -- только
 * метаданные: полный паспорт остаётся в durable-слое). */
export interface PassportSourceSnapshot {
  schema_version: string;
  snapshot_ref: string;
  stage: string | null;
  universe: string | null;
  content_status: string;
  content_gap_reason: string | null;
  target_column: string | null;
  date_column: string | null;
  context_id: string | null;
  data_revision: number | string | null;
  captured_at: string | null;
  fingerprint: string | null;
  fingerprint_reason: string | null;
}

/** Запись чекпоинта для version picker'а (§10). */
export interface PassportSourceCheckpoint {
  schema_version: string;
  checkpoint_id: string;
  stage: string | null;
  universe: string | null;
  confirmed_at: string | null;
  confirmed_at_reason: string | null;
  flags: Record<string, unknown> | null;
  snapshot_ref: string | null;
  integrity_status: string;
  integrity_reason: string | null;
  fingerprint: string | null;
}

export interface PassportSourcesPayload {
  run_id: string;
  snapshots: PassportSourceSnapshot[];
  checkpoints: PassportSourceCheckpoint[];
}

/** Готовая rendition печатной ревизии в листинге (metadata-only). */
export interface PrintRenditionSummary {
  rendition_id: string;
  format: PrintRenditionFormat;
  redaction_profile: string;
  state: string;
  media_type: string;
  size_bytes: number;
  content_sha256: string;
  job_id: string | null;
  created_at: string | null;
}

/** Ревизия печатного документа (frozen basis, §10.2). */
export interface PrintRevisionSummary {
  print_revision_id: string;
  version_no: number;
  profile_id: string;
  basis_kind: string;
  basis_artifact_ids: string[];
  basis_fingerprint: string;
  created_by: string | null;
  created_at: string | null;
  renditions: PrintRenditionSummary[];
}

/** Печатный документ семейства (V01/P01/P02; <=1 документ на вид/run). */
export interface PrintDocumentSummary {
  document_id: string;
  run_id: string;
  print_kind: "V01" | "P01" | "P02";
  family: PrintDocumentFamily;
  kind_title: string;
  created_by: string | null;
  created_at: string | null;
  revisions: PrintRevisionSummary[];
}

/** Resolved-точка комплекта (честные статусы content, AC11/AC12). */
export interface PassportDocumentSectionSummary {
  snapshot_ref: string | null;
  stage: string | null;
  content_status: string | null;
}

export interface PassportDocumentOutcome {
  run_id: string;
  mode: PassportDocumentMode;
  print_kind: "P01" | "P02";
  document_id: string;
  print_revision_id: string;
  snapshot_artifact_id: string;
  job: {
    job_id: string;
    state: string;
    format: string;
    attempt: number;
    print_revision_id: string | null;
    error_code: string | null;
    created_at: string | null;
  };
  status_url: string;
  checkpoint_id?: string;
  snapshot_refs?: string[];
  completeness?: "complete" | "partial";
  display?: {
    title: string;
    completeness: "complete" | "partial";
    gaps: Array<Record<string, unknown>>;
    sections: PassportDocumentSectionSummary[];
  };
  comparison?: {
    mode: string | null;
    cross_context: boolean | null;
    completeness: unknown;
    gaps: unknown;
  } | null;
}

export interface ApiResult<T> {
  ok: boolean;
  status: number | null;
  data?: T;
  /** Плоское тело ошибки §17 ({code, message}) при HTTP-отказе. */
  error?: { code: string | null; message: string | null };
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const resp = await apiFetch(url, {
      credentials: "include",
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
    if (!resp.ok) {
      let error: { code: string | null; message: string | null } = {
        code: null,
        message: null,
      };
      try {
        error = parseExportErrorBody(await resp.json());
      } catch {
        // тело не JSON -- честные null-коды (статус остаётся).
      }
      return { ok: false, status: resp.status, error };
    }
    const data = (await resp.json()) as T;
    return { ok: true, status: resp.status, data };
  } catch {
    // Сеть недоступна -- честный offline (§12.3).
    return { ok: false, status: null };
  }
}

/** GET passport-sources: durable версии/чекпоинты пикера (без DataFrame). */
export function listPassportSources(
  runId: string,
): Promise<ApiResult<PassportSourcesPayload>> {
  return requestJson(
    documentationApiUrl(`/runs/${encodeURIComponent(runId)}/passport-sources`),
  );
}

/** GET print-documents: сохранённые печатные документы (PGV-15 листинг). */
export function listPrintDocuments(
  runId: string,
): Promise<ApiResult<{ run_id: string; documents: PrintDocumentSummary[] }>> {
  return requestJson(
    documentationApiUrl(`/runs/${encodeURIComponent(runId)}/print-documents`),
  );
}

export interface RequestPassportDocumentInput {
  runId: string;
  mode: PassportDocumentMode;
  /** single: ровно один ref; compare: >=2 refs (взаимоисключающ с checkpoint). */
  snapshotRefs?: string[];
  /** set/compare: траектория «на выбранное подтверждение EDA» (§8/AC10). */
  checkpointId?: string | null;
  profileId?: string;
}

/** POST passport-documents: создать печатное представление (P01/P02) ->
 * 202 + job/status_url; идемпотентно (§11/§12.2: тот же refs/checkpoint --
 * та же ревизия и тот же job). Наука не запускается (AC06). */
export function requestPassportDocument(
  input: RequestPassportDocumentInput,
): Promise<ApiResult<PassportDocumentOutcome>> {
  const body: Record<string, unknown> = { mode: input.mode };
  if (input.checkpointId) body.checkpoint_id = input.checkpointId;
  if (input.snapshotRefs && input.snapshotRefs.length > 0) {
    body.snapshot_refs = input.snapshotRefs;
  }
  if (input.profileId) body.profile_id = input.profileId;
  return requestJson(
    documentationApiUrl(`/runs/${encodeURIComponent(input.runId)}/passport-documents`),
    { method: "POST", body: JSON.stringify(body) },
  );
}

/** POST print-revisions/{id}/renditions (PGV-09): поставить PNG ревизии в
 * очередь; повтор той же цели -- прежний job (replay ready, AC09). */
export function requestPrintRendition(
  printRevisionId: string,
  format: string = "png",
): Promise<ApiResult<{ job: { job_id: string; state: string }; status_url: string }>> {
  return requestJson(
    documentationApiUrl(
      `/print-revisions/${encodeURIComponent(printRevisionId)}/renditions`,
    ),
    { method: "POST", body: JSON.stringify({ format }) },
  );
}

/**
 * Человеческая фраза честного отказа (§10.2/§12.3; паритет кодов
 * роутеров PGV-13/15). status null -- сеть недоступна (offline).
 */
export function passportDocumentErrorText(
  status: number | null,
  code: string | null,
): string {
  if (status === null) return "Сеть недоступна — действие не выполнено.";
  const authorityError = exportAuthorityErrorText(code);
  if (authorityError) return authorityError;
  switch (code) {
    case "source_unavailable":
      return "Сохранённый источник недоступен из durable-слоя — пересчёт науки запрещён; выберите другую версию.";
    case "comparison_incompatible":
      return "Паспорта несовместимы (target/universe/схема) — сравнение не выполняется; выберите сопоставимые версии.";
    case "invalid_selection":
      return "Выбор неполный или некорректный — выберите версию и повторите.";
    case "quota_exceeded":
      return status === 402 ? "Лимит ресурсов для экспорта исчерпан — обратитесь к администратору."
        : "Очередь печати переполнена — повторите позднее.";
    case "retry_limit_exceeded":
      return "Исчерпаны попытки рендера — обратитесь в поддержку.";
    case "not_found":
      return "Исследование недоступно в этой среде — доступ запрещён или запуск не найден.";
    default:
      return status >= 500
        ? "Сервис печати временно недоступен — повторите попытку позже."
        : "Действие не выполнено — повторите попытку.";
  }
}
