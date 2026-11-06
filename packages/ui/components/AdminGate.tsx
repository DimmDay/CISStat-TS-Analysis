"use client";

// packages/ui/components/AdminGate.tsx
//
// AUTH-07 «Общая админка обеих оболочек» (spec_auth_architecture.md,
// строка 196): общий гейт доступа к админ-страницам standalone и
// embedded. Оракул дословно: «Named ADMIN+MFA управляет реальными API
// standalone/embedded; analyst/OWNER получают отказ».
//
// Поток входа (спека §3, «Администратор»): /login?return_to=/admin →
// личный password+MFA → /admin. Гейт проверяет named-сессию через
// GET /api/v1/auth/me (authClient.authMe):
//   * аноним → ссылка на /login с return_to (allowlist safeReturnTo,
//     AUTH-06; открытый редирект закрыт);
//   * роль НЕ admin (internal_analyst; external_user даже с
//     membership_role=owner -- «OWNER не ADMIN», spec §3) → различимый
//     отказ, дети НЕ рендерятся;
//   * admin → дети. MFA-принуждение и решающая проверка роли --
//     СЕРВЕР (auth.py require_admin_role; UI не заменяет backend
//     enforcement, admission честно UI-навигационный).
//
// «use client» -- первый statement (auth06SourceBoundary: браузерные
// вызовы -- только через apiFetch; authMe им и пользуется).

import { useCallback, useEffect, useState } from "react";
import { authMe, AuthFailure, safeReturnTo, type AuthSession } from "../lib/authClient";

type GateState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "unavailable" }
  | { status: "denied"; role: string; membership: string }
  | { status: "ready"; session: AuthSession };

export function AdminGate({
  children,
  returnTo,
}: {
  children: React.ReactNode;
  returnTo?: unknown;
}) {
  const [state, setState] = useState<GateState>({ status: "loading" });
  const check = useCallback(() => {
    setState({ status: "loading" });
    authMe()
      .then((session) => {
        if (!session) setState({ status: "anonymous" });
        else if (session.role !== "admin")
          setState({
            status: "denied",
            role: session.role,
            membership: session.membership_role,
          });
        else setState({ status: "ready", session });
      })
      .catch(() => setState({ status: "unavailable" }));
  }, []);
  useEffect(() => {
    check();
  }, [check]);

  if (state.status === "ready") return <>{children}</>;

  if (state.status === "anonymous")
    return (
      <section className="mx-auto max-w-lg space-y-4 rounded-2xl border border-neutral-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-neutral-900">
          Администрирование
        </h2>
        <p className="text-sm text-neutral-600">
          Панель доступна после личного входа администратора (пароль и
          подтверждение MFA).
        </p>
        <a
          className="inline-block rounded bg-brand px-4 py-2 text-sm font-semibold text-white"
          href={
            "/login?return_to=" + encodeURIComponent(safeReturnTo(returnTo))
          }
        >
          Войти как администратор
        </a>
      </section>
    );

  if (state.status === "denied")
    return (
      <section className="mx-auto max-w-lg space-y-3 rounded-2xl border border-neutral-200 bg-white p-6">
        <h2 className="text-lg font-semibold text-neutral-900">
          Доступ закрыт
        </h2>
        <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-700">
          Панель администрирования доступна только роли
          &laquo;администратор платформы&raquo;. Ваша роль: {state.role}
          {state.membership === "owner" ? " (владелец аккаунта)" : ""} -- она
          не даёт платформенных прав администрирования.
        </p>
        <p className="text-xs text-neutral-500">
          Оракул AUTH-07: analyst/OWNER получают отказ. Если вам нужны права
          администратора -- обратитесь к владельцу платформы.
        </p>
      </section>
    );

  if (state.status === "unavailable")
    return (
      <section className="mx-auto max-w-lg space-y-3 rounded-2xl border border-neutral-200 bg-white p-6">
        <p role="status" className="text-sm text-neutral-700">
          Проверка сессии недоступна. Повторите попытку позднее.
        </p>
        <button
          type="button"
          onClick={check}
          className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:border-neutral-500"
        >
          Проверить снова
        </button>
      </section>
    );

  return (
    <p role="status" className="text-sm text-neutral-500">
      Проверка доступа…
    </p>
  );
}

// AuthFailure импортирован для явного контракта типов (ошибки authMe
// конвертируются в состояние unavailable, текст не раскрывается).
export type { AuthFailure };
