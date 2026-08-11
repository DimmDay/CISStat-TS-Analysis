/** @type {import('next').NextConfig} */

// URL бэкенда для серверсайд-прокси (Next.js rewrite ниже).
//
// Источник в порядке приоритета:
//   1. API_URL (server-side only, НЕ NEXT_PUBLIC_) -- рекомендуемый способ
//      для продакшена на Vercel: значение НЕ попадает в клиентский bundle.
//   2. NEXT_PUBLIC_API_URL (старый вариант, остался для обратной совместимости)
//   3. http://localhost:8000 (дефолт для локальной разработки без .env)
//
// ВАЖНО: в проде браузер НЕ использует это значение напрямую (см.
// packages/ui/lib/apiClient.ts::getApiBase -- в production возвращается
// ОТНОСИТЕЛЬНЫЙ путь "/api"). Здесь URL нужен ТОЛЬКО для того, чтобы
// Next.js-сервер знал, куда проксировать запросы, пришедшие на /api/*.
//
// На Vercel: Settings → Environment Variables → добавить API_URL
//   = https://cisstat-ts-analysis.onrender.com
// NEXT_PUBLIC_API_URL можно убрать (больше не нужен в проде).
const apiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // Обязательно для монорепозитория: packages/ui теперь тянет собственные
  // сторонние зависимости (react-dropzone, sonner), а не только react/next.
  // Без этого Next.js не гарантирует резолвинг bare-импортов внутри файлов,
  // физически лежащих вне apps/standalone (см. официальную документацию
  // Next.js по монорепозиториям).
  transpilePackages: ["@cisstat/ui"],
  // Режим API для packages/ui/lib/apiClient.ts.
  //
  // ИСПРАВЛЕНО (было "public"): собственный браузерный UI standalone-сайта
  // (вкладки Загрузка/Валидация/... для посетителя в браузере) должен
  // работать БЕЗ API-ключа -- это сессионный доступ (cookie
  // cisstat_session_id, см. apps/api/session_store.py), а не программная
  // интеграция стороннего разработчика. "public" (/v1/public/*) требует
  // X-Api-Key (apps/api/auth.py::require_api_key) -- у обычного посетителя
  // сайта его физически нет и взять неоткуда, вкладка «Загрузка» не могла
  // работать в браузере вообще, только теоретически через curl с ключом.
  //
  // /v1/public/* остаётся полноценно рабочим и задокументированным на
  // /docs -- именно ДЛЯ такой внешней программной интеграции по ключу.
  // Браузерный UI сайта -- это отдельный, сессионный сценарий использования,
  // конкурирующий не с /v1/public/*, а зеркальный /v1/internal/* (тот же,
  // что использует embedded -- см. решение тимлида про Home page).
  env: {
    NEXT_PUBLIC_API_MODE: "internal",
  },
  // Серверсайд-прокси: браузерные запросы на /api/v1/* идут на ТОТ ЖЕ
  // origin (https://ts-standalone.vercel.app), а Next.js проксирует их
  // на бэкенд (${apiUrl}/v1/*). cisstat_session_id cookie становится
  // first-party и НЕ блокируется браузером как third-party
  // (Chrome 120+ блокирует SameSite=None на cross-origin fetch).
  //
  // Размер proxy-payload: Vercel ограничивает body Serverless Function
  // до 4.5 MB. Загрузка файла (POST /v1/internal/upload) должна быть
  // меньше этого лимита (текущий клиентский лимит в TsAnalysisUpload.tsx
  // -- 50 MB, надо будет снизить до 4 MB для Vercel-прокси; либо грузить
  // файл напрямую в S3/Render, а через прокси слать только метаданные).
  // Для cookie/GET/POST JSON -- лимит не проблема.
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiUrl}/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;