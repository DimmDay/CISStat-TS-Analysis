import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ProductHeader } from "@/components/ProductHeader";
import { AppShellProvider, DatasetContextBar, ModuleNav } from "@cisstat/ui";

const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "CISStat TS Analysis",
  description: "Платформа анализа временных рядов — самостоятельный продукт: веб и API",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={inter.variable}>
      <body>
        <ProductHeader />
        <AppShellProvider>
          <DatasetContextBar />
          <ModuleNav />
          <main className="max-w-[1600px] mx-auto px-6 py-6">{children}</main>
        </AppShellProvider>
      </body>
    </html>
  );
}
