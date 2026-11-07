import type { AuthMeResponseDTO } from "./access-contract.generated";
import { capabilitiesFromDTO } from "./access-contract.generated";
import { apiFetch, csrfProof, AUTH_PREFIX } from "./browserTransport";
const RETURNS = new Set([
  "/",
  "/admin",
  "/admin/progress",
  "/admin/logs",
  "/upload",
  "/validation",
  "/preprocessing",
  "/eda",
  "/modeling",
  "/forecasting",
  "/navigator",
]);
export function safeReturnTo(value: unknown): string {
  return typeof value === "string" && RETURNS.has(value) ? value : "/";
}
export type AuthSession = AuthMeResponseDTO;
export type Challenge = {
  status: "challenge_required";
  challenge_token: string;
  purpose:
    | "login"
    | "enroll_start"
    | "enroll"
    | "recovery"
    | "step_up"
    | "proof";
  expires_at: string;
};
export type LoginResult =
  | Challenge
  | { status: "authenticated"; session?: unknown; recovery_codes?: string[] }
  | {
      status: "account_required";
      accounts: { account_id: string; label: string }[];
    };
const messages: Record<string, string> = {
  csrf_invalid: "Защита запроса устарела. Повторите попытку.",
  too_many_attempts: "Слишком много попыток. Попробуйте позже.",
  mfa_required:
    "Для этой учётной записи требуется настройка MFA через администратора.",
  password_policy: "Пароль не соответствует политике безопасности.",
  account_expired: "Срок доступа аккаунта истёк. Обратитесь к владельцу или администратору.",
  account_access_denied: "Доступ к аккаунту запрещён. Обратитесь к владельцу или администратору.",
};
export class AuthFailure extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(
      messages[code] ??
        (status === 401
          ? "Вход не подтверждён. Проверьте данные и повторите попытку."
          : "Сервис входа временно недоступен. Повторите попытку."),
    );
  }
}
async function decoded(response: Response) {
  if (!response.ok) {
    let code = "auth_unavailable";
    try {
      code = (await response.json()).detail?.code ?? code;
    } catch {}
    throw new AuthFailure(response.status, code);
  }
  return response.status === 204 ? null : response.json();
}
export async function authMe(
  signal?: AbortSignal,
): Promise<AuthSession | null> {
  const r = await apiFetch(AUTH_PREFIX + "/me", { cache: "no-store", signal });
  if (r.status === 401) return null;
  const data = await decoded(r);
  if (
    !data ||
    data.auth_method !== "auth_session" ||
    typeof data.subject_id !== "string" ||
    typeof data.account_id !== "string" ||
    !["demo", "starter", "professional", "enterprise", "internal"].includes(data.account_plan) ||
    !["mono", "multi"].includes(data.account_type) ||
    !Number.isSafeInteger(data.entitlement_version) || data.entitlement_version < 1 ||
    !data.capabilities
  )
    throw new AuthFailure(503, "auth_unavailable");
  try {
    // Version guard plus generated projection. No role-to-plan inference.
    capabilitiesFromDTO(data.capabilities);
  } catch {
    throw new AuthFailure(503, "auth_unavailable");
  }
  const keys = [
    "subject_id",
    "account_id",
    "tenant_id",
    "membership_role",
    "role",
    "auth_method",
    "auth_session_id",
    "auth_time",
    "mfa_verified_at",
    "account_plan",
    "account_type",
    "plan_expires_at",
    "entitlement_version",
    "capabilities",
  ] as const;
  return Object.fromEntries(keys.map((key) => [key, data[key]])) as AuthSession;
}
const commands = new Set([
  "login",
  "mfa/enroll",
  "mfa/verify",
  "step-up",
  "mfa/replace",
  "recovery",
  "recovery/rotate",
  "logout",
  "password",
  "sessions/revoke-all",
]);
export async function authCommand<T = LoginResult>(
  command: string,
  payload: unknown = {},
  signal?: AbortSignal,
): Promise<T> {
  if (!commands.has(command)) throw new AuthFailure(400, "invalid_request");
  const proof = await csrfProof(signal);
  return decoded(
    await apiFetch(AUTH_PREFIX + "/" + command, {
      method: "POST",
      cache: "no-store",
      redirect: "error",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": proof },
      body: JSON.stringify(payload),
      signal,
    }),
  );
}
