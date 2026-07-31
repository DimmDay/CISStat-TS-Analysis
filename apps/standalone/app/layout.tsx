// apps/standalone/app/layout.tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppShellProvider } from "@cisstat/ui";
import { ProductHeader, ModuleNav } from "@cisstat/ui";
import { Toaster } from "sonner";

const inter = Inter({ subsets: ["latin", "cyrillic"] });

export const metadata: Metadata = {
  title: "CISStat TS Analysis (Standalone)",
  description: "Автономная платформа для анализа временных рядов",
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
          <ProductHeader />
          <ModuleNav />
          <main className="p-4">{children}</main>
          <Toaster />
        </AppShellProvider>
      </body>
    </html>
  );
}