"use client";

// packages/ui/context/ThemeContext.tsx
//
// Task DKT-1 — провайдер темы платформы (spec_dark_theme.md §4.3, §5).
//
// КОНТРАКТ ТЕМЫ (§5, фиксируется спекой):
//   - ключ хранения: localStorage["cisstat-theme"], значения "light"|"dark";
//   - класс-триггер: .dark на <html>; отсутствие класса = светлая тема;
//   - порядок инициализации: localStorage → prefers-color-scheme → "light";
//   - обе оболочки (standalone/embedded) используют ОДИН ключ и ОДИН класс
//     (общий packages/ui; переключатель в embedded — отдельное решение
//     тимлида §10.2).
//
// Hand-rolled ~60 строк по прецеденту NAVSTG-2 (отказ от отдельного
// пакета ради одной утилиты; next-themes — задокументированная
// альтернатива §10.5, контракт от замены не меняется).
//
// Класс на первом кадре ставит NO_FOUC_SCRIPT (§4.5) в <head> layout —
// провайдер подхватывает состояние в useEffect и далее владеет
// переключением. Кросс-таб-синхронизация — storage-событие.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "cisstat-theme";
export const THEME_DARK_CLASS = "dark";

/** meta theme-color: фон страницы в обеих темах (каталог §6.1). */
export const THEME_META_COLOR: Record<Theme, string> = {
  light: "#FFFFFF",
  dark: "#0B0C10",
};

/**
 * Источник истины при инициализации (§4.3):
 * localStorage → prefers-color-scheme → light.
 * Чистая функция — юнит-тестируется отдельно от React (§8.3).
 */
export function resolveInitialTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // localStorage недоступен (приватный режим/политики) — системная схема
  }
  try {
    if (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    ) {
      return "dark";
    }
  } catch {
    // matchMedia недоступен — светлый дефолт
  }
  return "light";
}

/** Идемпотентное применение темы к <html> + color-scheme + meta theme-color. */
export function applyTheme(theme: Theme): void {
  const el = document.documentElement;
  el.classList.toggle(THEME_DARK_CLASS, theme === "dark");
  el.style.colorScheme = theme;
  let meta = document.querySelector('meta[name="theme-color"]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.setAttribute("name", "theme-color");
    document.head.appendChild(meta);
  }
  meta.setAttribute("content", THEME_META_COLOR[theme]);
}

/**
 * No-FOUC-скрипт (§4.5): блокирующий inline-скрипт в <head> ДО гидратации.
 * Повторяет арифметику resolveInitialTheme: localStorage → системная
 * схема → светлая; ставит класс .dark на <html> и color-scheme.
 * Самодостаточный IIFE без зависимостей (~10 строк, §4.5).
 */
export const NO_FOUC_SCRIPT = `(function(){try{var k="${THEME_STORAGE_KEY}";var s=localStorage.getItem(k);var d=s==="dark"||((s!=="light")&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches);var e=document.documentElement;e.classList.toggle("${THEME_DARK_CLASS}",d);e.style.colorScheme=d?"dark":"light";}catch(e){}})();`;

export interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Первый рендер — "light" (совпадает с SSR); в useEffect состояние
  // синхронизируется с классом, выставленным no-FOUC-скриптом.
  const [theme, setThemeState] = useState<Theme>("light");

  useEffect(() => {
    // Подхват класса от no-FOUC-скрипта (idempotentно, §4.3)
    const initial = resolveInitialTheme();
    setThemeState(initial);
    applyTheme(initial);

    // Кросс-таб-синхронизация (§4.3): storage-событие
    const onStorage = (e: StorageEvent) => {
      if (e.key !== THEME_STORAGE_KEY) return;
      if (e.newValue === "light" || e.newValue === "dark") {
        setThemeState(e.newValue);
        applyTheme(e.newValue);
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    applyTheme(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // персист недоступен — тема живёт до перезагрузки
    }
  }, []);

  const toggleTheme = useCallback(() => {
    // Источник истины — класс на <html> (устойчиво к лагам useState)
    const dark = document.documentElement.classList.contains(THEME_DARK_CLASS);
    setTheme(dark ? "light" : "dark");
  }, [setTheme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

/**
 * Хук доступа к теме. Вне провайдера возвращает светло-дефолтную пару
 * (переключатель деградирует в no-op вместо падения — переключатель
 * монтируется только внутри ThemeProvider в standalone).
 */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  return (
    ctx ?? {
      theme: "light",
      setTheme: () => {},
      toggleTheme: () => {},
    }
  );
}
