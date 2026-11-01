/** @type {import('next').NextConfig} */
// AUTH-06 fixed-target handler replaces unrestricted external rewrites.
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@cisstat/ui"],
  env: { NEXT_PUBLIC_API_MODE: "internal" },
  async headers() {
    return [{source: "/login", headers: [
      {key: "Cache-Control", value: "private, no-store"},
      {key: "Referrer-Policy", value: "no-referrer"},
      {key: "X-Frame-Options", value: "SAMEORIGIN"},
      {key: "Content-Security-Policy", value: "frame-ancestors 'self'; form-action 'self'; base-uri 'self'"},
      {key: "X-Content-Type-Options", value: "nosniff"},
    ]}];
  },
};
export default nextConfig;
