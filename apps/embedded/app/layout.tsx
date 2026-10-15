// apps/embedded/app/layout.tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppShellProvider } from "@cisstat/ui";
import { PortalNavBar, ModuleNav } from "@cisstat/ui";
import { Toaster } from "sonner";

// Inter подключаем через CSS-переменную --font-sans (как и в standalone),
// чтобы tailwind-preset'овский `font-sans` = var(--font-sans) работал
// симметрично в обоих apps. Раньше здесь был `inter.className` — он не
// выставлял --font-sans, и font-sans fallback'ил на system-ui.
const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-sans" });

export const metadata: Metadata = {
  // UI-HOME-BRAND-1 (2026-10-15): title вкладки браузера — переименование
  // бренда «CISStat TS Analysis» → «CISStat DataTime Lab» (скоуп-решение:
  // та же поверхность «название во вкладке браузера», что и у standalone).
  title: "CISStat DataTime Lab (Embedded)",
  description: "Анализ временных рядов — встроенный модуль портала CISStat",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru" className={inter.variable}>
      <body className="font-sans antialiased">
        <AppShellProvider>
          <PortalNavBar />
          <ModuleNav />
          <main className="p-4">{children}</main>
          <Toaster />
        </AppShellProvider>
      </body>
    </html>
  );
}
