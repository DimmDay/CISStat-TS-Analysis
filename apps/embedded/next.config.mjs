/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // См. apps/standalone/next.config.mjs -- та же причина: packages/ui
  // тянет собственные сторонние зависимости (react-dropzone, sonner).
  transpilePackages: ["@cisstat/ui"],
};

export default nextConfig;
