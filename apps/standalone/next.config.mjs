/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Обязательно для монорепозитория: packages/ui теперь тянет собственные
  // сторонние зависимости (react-dropzone, sonner), а не только react/next.
  // Без этого Next.js не гарантирует резолвинг bare-импортов внутри файлов,
  // физически лежащих вне apps/standalone (см. официальную документацию
  // Next.js по монорепозиториям).
  transpilePackages: ["@cisstat/ui"],
  // Режим API для packages/ui/lib/apiClient.ts -- standalone всегда ходит
  // на /v1/public/* (требует API-ключ на бэкенде). См. решение тимлида
  // про Home page: не различать режим по window.location.pathname.
  env: {
    NEXT_PUBLIC_API_MODE: "public",
  },
};

export default nextConfig;
