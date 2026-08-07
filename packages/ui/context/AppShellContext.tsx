"use client";

// packages/ui/context/AppShellContext.tsx
//
// Глобальное состояние, нужное на ЛЮБОЙ странице (в отличие от формы
// загрузки, которая нужна только на странице "Загрузка"):
// - какой датасет сейчас активен (контекст, не действие)
// - лог событий (сквозной, накопительный)
//
// Живёт в React Context, а не в самой форме загрузки, потому что форма
// загрузки -- это одноразовое ДЕЙСТВИЕ, а знание "какой датасет активен"
// нужно постоянно, независимо от вкладки/страницы.

import { createContext, useCallback, useContext, useState, ReactNode } from "react";

export interface LogEntry {
  id: number;
  time: string;
  level: "INFO" | "WARNING" | "ERROR";
  message: string;
}

export interface ActiveDataset {
  name: string;
  rows: number;
  sizeLabel: string;
  // Опциональные поля для автозаполнения DataProfile в модуле «Моделирование».
  // Добавляются при наличии в ответе API загрузки (passport / structure-detection).
  frequency?: string;       // "D" | "W" | "M" | "Q" | "Y"
  domain?: string;          // "financial" | "macro" | "price" | "other"
  nSeries?: number;         // число временных рядов (≥ 1)
  hasSeasonality?: boolean; // обнаружена сезонность
  isRegular?: boolean;      // регулярность временного индекса
}

interface AppShellContextValue {
  activeDataset: ActiveDataset | null;
  setActiveDataset: (dataset: ActiveDataset) => void;
  log: LogEntry[];
  addLogEntry: (level: LogEntry["level"], message: string) => void;
  clearLog: () => void;
}

const AppShellContext = createContext<AppShellContextValue | null>(null);

export function AppShellProvider({ children }: { children: ReactNode }) {
  const [activeDataset, setActiveDatasetState] = useState<ActiveDataset | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);

  const addLogEntry = useCallback((level: LogEntry["level"], message: string) => {
    setLog((prev) => [
      { id: prev.length, time: new Date().toLocaleTimeString("ru-RU"), level, message },
      ...prev,
    ]);
  }, []);

  const setActiveDataset = useCallback(
    (dataset: ActiveDataset) => {
      setActiveDatasetState(dataset);
      addLogEntry("INFO", `✅ Загружен файл: ${dataset.name}`);
    },
    [addLogEntry]
  );

  const clearLog = useCallback(() => setLog([]), []);

  return (
    <AppShellContext.Provider value={{ activeDataset, setActiveDataset, log, addLogEntry, clearLog }}>
      {children}
    </AppShellContext.Provider>
  );
}

export function useAppShell() {
  const ctx = useContext(AppShellContext);
  if (!ctx) {
    throw new Error("useAppShell должен вызываться внутри <AppShellProvider>");
  }
  return ctx;
}
