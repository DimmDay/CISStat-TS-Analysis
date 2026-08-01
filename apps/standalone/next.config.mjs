/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Обязательно для монорепозитория: packages/ui теперь тянет собственные
  // сторонние зависимости (react-dropzone, sonner), а не только react/next.
  // Без этого Next.js не гарантирует резолвинг bare-импортов внутри файлов,
  // физически лежащих вне apps/standalone (см. официальную документацию
  // Next.js по монорепозиториям).
  transpilePackages: ["@cisstat/ui"],
};

export default nextConfig;
