import { apiFetch } from "./browserTransport";
import { progressApiUrl } from "./apiClient";

/** AUTH-09 transport for history clients. Named restore requires a CSRF POST. */
export async function restoreResearchRun(runId: string): Promise<unknown> {
  if (!/^RUN-[0-9A-Z]{8}$/.test(runId)) throw new Error("Некорректный ID исследования");
  const response = await apiFetch(progressApiUrl(`/runs/${runId}/restore`), {
    method: "POST", cache: "no-store",
  });
  if (!response.ok) throw new Error(`Восстановление недоступно (${response.status})`);
  return response.json();
}
