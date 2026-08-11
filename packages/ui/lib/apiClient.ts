// packages/ui/lib/apiClient.ts
//
// Единая точка выбора API-базы и префикса (public/internal). ЗАМЕНЯЕТ
// прежнюю логику в DataUploadForm.tsx (`window.location.pathname.
// startsWith("/embedded")`), которая не соответствовала реальности --
// ни один из apps/* не монтируется под путём /embedded, оба -- корневые
// Next.js-приложения на разных портах. Та логика к тому же строила
// ОТНОСИТЕЛЬНЫЙ URL ("/v1/internal/upload"), который бьёт в сам
// Next.js-сервер (порт 3000/3001), а не в FastAPI-бэкенд (порт 8000) --
// без прокси/rewrite в next.config.mjs запрос не мог дойти до API.
//
// Правильный сигнал режима -- переменная окружения, задаваемая на
// уровне next.config.mjs КАЖДОГО приложения (см. env в
// apps/embedded/next.config.mjs и apps/standalone/next.config.mjs),
// а не путь в браузере.

export type ApiMode = "internal" | "public";

export function getApiBase(): string {
  // В проде (deployed to Vercel) используем ОТНОСИТЕЛЬНЫЙ путь "/api" --
  // Next.js rewrite (apps/standalone/next.config.mjs, apps/embedded/...)
  // проксирует запросы на бэкенд, и cisstat_session_id cookie становится
  // FIRST-PARTY для домена фронтенда. Это критично: в противном случае
  // cookie с SameSite=None; Secure (нужна для cross-origin credentialed
  // fetch) классифицируется браузером как third-party и БЛОКИРУЕТСЯ
  // (Chrome 120+ third-party cookie blocking, Safari ITP, Firefox ETP).
  // Симптом бага: "загружаю датасет → ухожу на другую вкладку → возвращаюсь
  // → сессия упала, загрузка нужна заново" (бэкенд сохраняет сессию в
  // Redis корректно, но браузер не отдаёт cookie на следующий fetch).
  //
  // В dev / тестах -- по-прежнему можно дёрнуть бэкенд напрямую через
  // NEXT_PUBLIC_API_URL (http://localhost:8000). typeof window отличает
  // браузер (нужен /api) от SSR/тестов (нужен абсолютный URL).
  if (typeof window !== "undefined" && process.env.NODE_ENV === "production") {
    return "/api";
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

export function getApiMode(): ApiMode {
  const mode = process.env.NEXT_PUBLIC_API_MODE;
  // "internal" -- безопасный дефолт для локальной разработки без .env
  return mode === "public" ? "public" : "internal";
}

/** URL для /v1/public/* или /v1/internal/* в зависимости от приложения. */
export function apiUrl(path: string): string {
  return `${getApiBase()}/v1/${getApiMode()}${path}`;
}

/**
 * Сессия (AnalysisSession) НЕ разделена на public/internal -- один и тот
 * же браузер = одна сессия, независимо от того, embedded или standalone
 * сейчас открыт (см. apps/api/routers/session.py, docstring модуля).
 */
export function sessionApiUrl(path: string): string {
  return `${getApiBase()}/v1/session${path}`;
}
