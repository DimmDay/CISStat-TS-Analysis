"use client";

// packages/ui/components/ThemeToaster.tsx
//
// Task DKT-4 (spec_dark_theme.md §7 DKT-4, R-7): sonner Toaster —
// сторонняя поверхность с собственным дефолтом вне токенов. Тема тостов
// следует контексту платформы: useTheme() вне провайдера деградирует в
// светлую no-op-пару (ThemeContext), поэтому компонент безопасен в любой
// оболочке; в embedded (решение §10.2 — «v1 только standalone») тосты
// остаются светлыми, потому что провайдер там не монтируется.

import { Toaster } from "sonner";
import { useTheme } from "../context/ThemeContext";

export function ThemeToaster() {
  const { theme } = useTheme();
  return <Toaster theme={theme} />;
}
