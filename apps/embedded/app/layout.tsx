// apps/embedded/app/layout.tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppShellProvider } from "@cisstat/ui";
import { PortalNavBar, ModuleNav } from "@cisstat/ui";
import { Toaster } from "sonner";

const inter = Inter({ subsets: ["latin", "cyrillic"] });

export const metadata: Metadata = {
  title: "CISStat TS Analysis (Embedded)",
  description: "Анализ временных рядов — встроенный модуль портала CISStat",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className={inter.className}>
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