import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { PortalNavBar } from "@cisstat/ui";

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
        <main className="max-w-[1600px] mx-auto px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
