import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { PortalNavBar, AppShellProvider, DatasetContextBar } from "@cisstat/ui";

const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "CISStat — Анализ временных рядов",
  description: "Платформа анализа временных рядов, встроенная в портал CISStat",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={inter.variable}>
      <body>
        {/* ЗАМЕНИТЬ: логотип-шапка + поисковая строка с ИИ-агентом портала --
            это отдельные компоненты, ещё не присланные (см. README).
            PortalNavBar -- только вторая строка (ссылки разделов). */}
        <PortalNavBar />
        <AppShellProvider>
          {/* Лёгкий глобальный контекст-бар вместо постоянной боковой панели --
              решение по фидбэку: форма загрузки живёт только на /data/upload,
              здесь -- только индикатор активного датасета + лог по клику. */}
          <DatasetContextBar />
          <main className="max-w-[1600px] mx-auto px-6 py-6">{children}</main>
        </AppShellProvider>
      </body>
    </html>
  );
}
