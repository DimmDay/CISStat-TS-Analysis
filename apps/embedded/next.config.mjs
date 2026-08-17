/** @type {import('next').NextConfig} */

// См. apps/standalone/next.config.mjs -- здесь ТОТ ЖЕ фикс third-party cookie
// blocking: браузер ходит на /api/v1/* (relative, first-party), Next.js
// проксирует на бэкенд. Важно и для embedded, если он деплоится отдельно
// (на сегодня не задеплоен, но архитектура должна быть готова).
const apiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // См. apps/standalone/next.config.mjs -- та же причина: packages/ui
  // тянет собственные сторонние зависимости (react-dropzone, sonner).
  transpilePackages: ["@cisstat/ui"],
  // Режим API для packages/ui/lib/apiClient.ts -- embedded всегда ходит
  // на /v1/internal/* (сессия портала, без API-ключа). См. решение
  // тимлида про Home page: не различать режим по window.location.pathname.
  env: {
    NEXT_PUBLIC_API_MODE: "internal",
  },
  // См. apps/standalone/next.config.mjs: тот же серверсайд-прокси для
  // first-party cookie. Без него cisstat_session_id блокируется браузером
  // при cross-origin fetch (Chrome 120+ third-party cookie blocking).
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
