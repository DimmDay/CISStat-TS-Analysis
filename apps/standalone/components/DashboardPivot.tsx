"use client";

// apps/standalone/components/DashboardPivot.tsx
//
// AUTH-KABINET-DEMO: пивот маршрута /dashboard — цель надписи «Вход» в
// ProductHeader. Сценарий тимлида: авторизован → /account («Аккаунт и
// команда»: биллинг/кошелёк/пополнения), не авторизован →
// /login?return_to=/account (safeReturnTo уже содержит /account —
// whitelist не расширяется). fail-closed: при "unavailable" никаких
// автопереходов — честное сообщение + ручные ссылки; при "loading" —
// статус. `/dashboard` в RETURNS не добавляется: пивот сразу переправляет,
// прямой доступ к нему извне login-потока не предусмотрен. Метаданные
// (noindex) — в app/dashboard/page.tsx (server component).

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@cisstat/ui/context/AuthContext";

export function DashboardPivot() {
  const { status, refresh } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (status === "authenticated") router.replace("/account");
    else if (status === "anonymous")
      router.replace("/login?return_to=/account");
  }, [status, router]);
  if (status === "loading")
    return (
      <p role="status" className="p-6 text-sm text-neutral-500">
        Проверяем вход…
      </p>
    );
  if (status === "unavailable")
    return (
      <div className="mx-auto max-w-md space-y-3 p-6 text-sm text-neutral-700">
        <p role="alert">
          Сервис авторизации недоступен. Повторите попытку позже.
        </p>
        <p className="space-x-4">
          <a href="/" className="text-brand underline">
            На главную
          </a>
          <button
            type="button"
            className="text-brand underline"
            onClick={() => void refresh().catch(() => {})}
          >
            Повторить
          </button>
        </p>
      </div>
    );
  return (
    <p role="status" className="p-6 text-sm text-neutral-500">
      Перенаправляем…
    </p>
  );
}
