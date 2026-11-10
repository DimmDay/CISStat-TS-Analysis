import { apiFetch, csrfProof } from "./browserTransport";
export function commandKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}
export type TeamMember = {
  subject_id: string;
  account_role: "owner" | "member";
  status: "active" | "revoked";
  label: string;
};
export type TeamAccount = {
  account_id: string;
  tenant_id: string;
  account_type: "mono" | "multi";
  plan: string;
  seats: number;
  occupied: number;
  free_seats: number;
  entitlement_version: number;
  can_manage: boolean;
  members: TeamMember[];
  invitations: {
    invitation_id: string;
    email: string | null;
    target_subject_id: string | null;
    expires_at: string;
    consumed_at: string | null;
    revoked_at: string | null;
  }[];
  seat_requests: { request_id: string; seats: number; state: string }[];
};
const messages: Record<string, string> = {
  owner_required: "Действие доступно владельцу аккаунта.",
  seat_capacity_exhausted:
    "Нет свободного подтверждённого места. Владелец может подать заявку на изменение ёмкости.",
  invitation_unavailable:
    "Приглашение недоступно, истекло или предназначено другому пользователю.",
  invitation_consumed:
    "Приглашение уже использовано. Для повторного вступления запросите новое.",
  recent_login_required:
    "Выйдите и войдите заново с MFA, если он настроен, затем повторите передачу владения.",
  account_version_conflict:
    "Состав или параметры аккаунта изменились. Обновите страницу.",
  owner_transfer_required: "Сначала передайте владение другому участнику.",
  team_unavailable: "Командное управление недоступно для этого аккаунта.",
  seat_request_pending: "Заявка на изменение мест уже ожидает подтверждения.",
  account_obligations:
    "Переход требует одного места, одного участника и отсутствия незавершённых операций.",
  idempotency_conflict:
    "Ключ запроса уже использован. Обновите состояние аккаунта.",
};
export async function teamRequest(path = "", body?: unknown) {
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["X-CSRF-Token"] = await csrfProof();
    headers["Content-Type"] = "application/json";
  }
  const r = await apiFetch("/api/v1/accounts" + path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let code = "";
    try {
      code = (await r.json()).detail?.code ?? "";
    } catch {}
    throw new Error(
      messages[code] ??
        (r.status === 401
          ? "Требуется личный вход."
          : r.status === 403
            ? "Доступ запрещён."
            : r.status === 422
              ? "Проверьте параметры формы."
              : r.status === 409
                ? "Данные изменились. Обновите страницу."
                : "Сервис аккаунтов временно недоступен."),
    );
  }
  return r.json();
}
