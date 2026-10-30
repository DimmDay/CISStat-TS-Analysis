// packages/ui/lib/visualExports.ts
//
// PGV-10 (spec_passport_graphics_visual.md §10.1/§11/§13, строка
// PGV-10): клиент «Скачать PNG» научных визуализаций остановок
// upload/validation/preprocessing.
//
// Контракт §11: POST /v1/documentation/runs/{run_id}/visuals ->
// freeze durable visual_result -> VisualPrintSnapshot/1 (screen_svg --
// сериализация СВОЕГО chart-узла) -> V01 revision -> PNG job -> 202 +
// status_url. Наука не запускается (AC06); CAS expected_context
// (context_id трассы -- единый источник слоя 1, паритет
// resolveCurrentRun) -- 409 context_changed при смене данных (AC07).
//
// run_id резолвится тем же GET /v1/progress/trace, что и «Документы»
// (урок C01 DOCLOG-E2E-RECHECK-1: единый источник run_id слоя 1).

import { getApiBase } from "./apiClient";
import { documentationApiUrl } from "./documentation";

export interface VisualExportJob {
  job_id: string;
  state: string;
  format: string;
  attempt: number;
  print_revision_id: string | null;
  error_code: string | null;
  created_at: string | null;
  rendition_id?: string | null;
  rendition_state?: string | null;
}

export interface VisualExportOutcome {
  run_id: string;
  view_id: string;
  result_artifact_id: string | null;
  result_ref: string | null;
  snapshot_artifact_id: string | null;
  document_id: string;
  print_revision_id: string;
  print_kind: string;
  profile_id: string;
  job: VisualExportJob;
  status_url: string;
}

export interface VisualSourceSummary {
  view_id: string;
  module_id: string;
  stop_id: string;
  renderer_kind: string;
  applicability: string;
  title: string;
  export_ready: boolean;
  latest_result: {
    artifact_id: string;
    result_ref: string | null;
    digest: string | null;
    computed_at: string | null;
    computed_at_reason: string | null;
    context_id: string | null;
    data_revision: number | null;
  } | null;
  latest_snapshot: {
    artifact_id: string;
    profile_id: string | null;
    captured_at: string | null;
  } | null;
  unavailable_reason: string | null;
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
    const resp = await fetch(url, {
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
        const body = (await resp.json()) as { code?: string; message?: string; error?: { code?: string; message?: string } };
        error = {
          code: body.code ?? body.error?.code ?? null,
          message: body.message ?? body.error?.message ?? null,
        };
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

/** run_id текущего исследования (единый источник слоя 1 -- /trace). */
export function resolveCurrentRunForExport(): Promise<ApiResult<{ run_id: string | null; context_id?: string | null }>> {
  return requestJson<{ run_id?: string | null; context_id?: string | null }>(
    `${getApiBase()}/v1/progress/trace`,
  ).then((result): ApiResult<{ run_id: string | null; context_id?: string | null }> =>
    result.ok
      ? {
          ok: true,
          status: result.status,
          data: {
            run_id: result.data?.run_id || null,
            context_id: result.data?.context_id || null,
          },
        }
      : { ok: false, status: result.status },
  );
}

export interface RequestVisualExportInput {
  runId: string;
  viewId: string;
  /** Сериализованный SVG chart-узла ЭТОГО view (не первый SVG документа). */
  screenSvg?: string | null;
  /** CAS: контекст, который видит аналитик (context_id трассы). */
  expectedContextId?: string | null;
  profileId?: string;
  dateColumn?: string | null;
}

/** POST /visuals: поставить PNG-экспорт view в очередь (202). */
export function requestVisualExport(
  input: RequestVisualExportInput,
): Promise<ApiResult<VisualExportOutcome>> {
  const body: Record<string, unknown> = {
    view_id: input.viewId,
    ...(input.profileId ? { profile_id: input.profileId } : {}),
    ...(input.screenSvg ? { screen_svg: input.screenSvg } : {}),
    ...(input.expectedContextId ? { expected_context_id: input.expectedContextId } : {}),
    ...(input.dateColumn ? { date_column: input.dateColumn } : {}),
  };
  return requestJson<VisualExportOutcome>(
    documentationApiUrl(`/runs/${encodeURIComponent(input.runId)}/visuals`),
    { method: "POST", body: JSON.stringify(body) },
  );
}

/** GET /visual-sources: доступные frozen inputs (без запуска науки). */
export function listVisualSources(
  runId: string,
): Promise<ApiResult<{ run_id: string; sources: VisualSourceSummary[] }>> {
  return requestJson(
    documentationApiUrl(`/runs/${encodeURIComponent(runId)}/visual-sources`),
  );
}

/**
 * Человеческая фраза честного отказа (§10.1 «Unavailable/loading имеет
 * причину»; паритет кодов роутера PGV-10).
 */
export function visualExportErrorText(status: number | null, code: string | null): string {
  if (status === null) return "Сеть недоступна — экспорт не выполнен.";
  switch (code) {
    case "context_changed":
      return "Данные изменились после показа — обновите представление и повторите экспорт.";
    case "source_unavailable":
      return "Зафиксированный результат недоступен — откройте представление заново и повторите.";
    case "screen_svg_required":
    case "invalid_screen_svg":
      return "Печатная геометрия графика не приложена — разверните график и повторите.";
    case "view_out_of_scope":
      return "Экспорт этого вида появится в отдельной поставке.";
    case "unknown_view":
      return "Неизвестный вид визуализации.";
    case "invalid_profile":
      return "Профиль печати вне каталога.";
    case "quota_exceeded":
      return "Очередь печати переполнена — повторите позднее.";
    case "retry_limit_exceeded":
      return "Исчерпаны попытки рендера — обратитесь в поддержку.";
    case "not_found":
      return "Исследование недоступно в этой среде.";
    default:
      return status >= 500
        ? "Экспорт временно недоступен — повторите позднее."
        : "Экспорт не выполнен — повторите попытку.";
  }
}
