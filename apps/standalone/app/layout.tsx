import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppShellProvider, ModuleNav, ThemeProvider, ThemeToaster, NO_FOUC_SCRIPT } from "@cisstat/ui";
import { ProductHeader } from "@/components/ProductHeader";

const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "CISStat TS Analysis",
  description: "Платформа анализа временных рядов — самостоятельный продукт: веб и API",
  icons: {
    icon: "/logo_TS.png",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: класс .dark на <html> ставит блокирующий
    // no-FOUC-скрипт ДО гидратации (spec_dark_theme.md §4.4/§4.5) —
    // расхождение атрибутов ожидаемо и ограничено атрибутом class.
    <html lang="ru" className={inter.variable} suppressHydrationWarning>
      <head>
        {/* Task DKT-1 §4.5: арифметика localStorage → системная схема →
            светлая до первого кадра; после гидратации владеет ThemeProvider. */}
        <script dangerouslySetInnerHTML={{ __html: NO_FOUC_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <ProductHeader />
          <AppShellProvider>
            <ModuleNav />
            <main className="max-w-[1600px] mx-auto px-6 py-6">{children}</main>
            <ThemeToaster />
          </AppShellProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
