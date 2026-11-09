import { apiFetch, csrfProof } from "./browserTransport";
export type CampaignPolicy = {
  starts_at: string;
  ends_at: string;
  grant_minutes: number;
  max_grants: number;
  campaign_cu: number;
  participant_cu: number;
  campaign_concurrency: number;
  participant_concurrency: number;
  campaign_analyses: number;
  participant_analyses: number;
  max_rows: number;
  allow_upload: boolean;
  allowed_origins: string[];
};
export type Campaign = {
  campaign_id: string;
  alias: string;
  status: string;
  policy_version: number;
  credential_version: number;
  issued_grants: number;
  policy: CampaignPolicy;
  secret?: string;
};
const messages: Record<string, string> = {
  demo_expired:
    "Демо-доступ завершён. Войдите в личный аккаунт или обратитесь на стенд.",
  campaign_inactive:
    "Кампания ещё не началась, приостановлена или недоступна в этой оболочке.",
  campaign_policy_conflict:
    "Кампания изменилась. Обновите список перед повтором.",
  campaign_capacity_exhausted: "Лимит кампании исчерпан. Обратитесь на стенд.",
  mfa_required: "Подтвердите MFA заново: повторите личный вход администратора.",
  invalid_credential: "Вход не подтверждён. Проверьте данные с флаера.",
  invalid_campaign_policy:
    "Проверьте конечные лимиты и временное окно кампании.",
  too_many_attempts: "Слишком много попыток. Повторите позже.",
};
export async function demoRequest(
  path: string,
  method = "GET",
  body?: unknown,
) {
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    headers["X-CSRF-Token"] = await csrfProof();
    headers["Content-Type"] = "application/json";
  }
  const response = await apiFetch("/api/v1/" + path, {
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let code = "";
    try {
      code = (await response.json()).detail?.code ?? "";
    } catch {}
    throw new Error(
      messages[code] ??
        (response.status === 403
          ? "Доступ запрещён."
          : response.status === 422
            ? "Проверьте параметры формы."
            : response.status === 401
              ? "Требуется личный вход."
              : "Сервис временно недоступен. Повторите попытку."),
    );
  }
  return response.json();
}
