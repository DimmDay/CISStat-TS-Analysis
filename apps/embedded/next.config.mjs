/** @type {import('next').NextConfig} */
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
};

export default nextConfig;
