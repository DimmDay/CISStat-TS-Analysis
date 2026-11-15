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
  require_admission?: boolean;
  participant_requests?: number;
  campaign_requests?: number;
  max_upload_bytes?: number;
  retention_hours?: number;
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
  admission_consumed:
    "Код уже использован. Продолжите свой доступ в прежнем браузере.",
  demo_request_limit: "Лимит запросов демо исчерпан.",
  demo_upload_limit: "Файл превышает предел демо-доступа.",
  // AUTH-KABINET-DEMO: лексика самообслуживаемого демо — запуск и
  // перезапуск со страницы «Демо» или личный вход; без бумажной
  // дистрибуции.
  demo_expired:
    "Демо-доступ завершён. Запустите демо заново на странице «Демо» или войдите в личный аккаунт.",
  campaign_inactive:
    "Кампания ещё не началась, приостановлена или недоступна в этой оболочке.",
  campaign_policy_conflict:
    "Кампания изменилась. Обновите список перед повтором.",
  campaign_capacity_exhausted:
    "Лимит кампании исчерпан. Попробуйте позже или войдите в личный аккаунт.",
  mfa_required: "Подтвердите MFA заново: повторите личный вход администратора.",
  invalid_credential: "Вход не подтверждён. Проверьте логин и пароль кампании.",
  invalid_campaign_policy:
    "Проверьте конечные лимиты и временное окно кампании.",
  too_many_attempts: "Слишком много попыток. Повторите позже.",
};

// AUTH-KABINET-DEMO: пара самообслуживаемого демо задаётся окружением
// сборки (NEXT_PUBLIC_* Next.js инлайнит при сборке). Пара намеренно НЕ
// хранится в коде репозитория: rotation = rotate-credential в админ-панели
// + обновление env + редеплой; при отсутствии env кнопка «Запустить
// демо-режим» честно отключена (никаких молчаливых fallback-пар).
// Пара передаётся только в теле POST /v1/auth/demo/enter — в URL и
// ссылках credentials не появляются (AC22).
export function publicDemoCredentials(): {
  login: string;
  password: string;
} | null {
  const login = process.env.NEXT_PUBLIC_DEMO_LOGIN;
  const password = process.env.NEXT_PUBLIC_DEMO_PASSWORD;
  return login && password ? { login, password } : null;
}
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
