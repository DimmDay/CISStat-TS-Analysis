"use client";

// apps/standalone/lib/useAuth.ts
//
// ЗАГЛУШКА -- реальной авторизации standalone-продукта ещё нет (см.
// docs/ROLES_AND_PLANS_SPEC.md §7.1: "хранилище клиентов/ключей" не
// реализовано, есть только статичный API-ключ в env). По решению
// тимлида, чтобы не блокировать вёрстку sessions-aware Home на
// отсутствующем бэкенде авторизации, используется ручной переключатель
// поверх localStorage.
//
// ЖИВЁТ В apps/standalone, НЕ в packages/ui -- это концепция, специфичная
// для продаваемого продукта (у embedded такого разделения нет, см.
// EmbeddedHome.tsx).
//
// ЗАМЕНИТЬ: когда появится реальная авторизация пользователя (сессия
// клиента / JWT / OAuth) -- эта функция должна читать её вместо
// localStorage-переключателя, а сам переключатель (DevAuthToggle) убрать
// из продакшен-сборки.

import { useCallback, useEffect, useState } from "react";

const DEV_AUTH_KEY = "cisstat_dev_auth_override";

export function useAuth() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      setIsAuthenticated(window.localStorage.getItem(DEV_AUTH_KEY) === "1");
    } finally {
      setReady(true);
    }
  }, []);

  const setDevAuthOverride = useCallback((value: boolean) => {
    window.localStorage.setItem(DEV_AUTH_KEY, value ? "1" : "0");
    setIsAuthenticated(value);
  }, []);

  return { isAuthenticated, ready, setDevAuthOverride };
}
