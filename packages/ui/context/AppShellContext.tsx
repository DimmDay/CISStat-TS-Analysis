"use client";

// packages/ui/context/AppShellContext.tsx
//
// Глобальное состояние, нужное на ЛЮБОЙ странице:
// - какой датасет сейчас активен + на каком этапе остановился пользователь
// - лог событий (сквозной, накопительный)
//
// ИЗМЕНЕНИЕ (сессионная Home page, по решению тимлида): activeDataset
// раньше был чисто клиентским useState, который обнулялся на F5. Теперь
// при монтировании провайдер гидрируется с бэкенда (GET
// /v1/session/current) -- источник истины сервер (session_store.py),
// клиентский стейт -- только кэш для рендера. setActiveDataset остаётся
// как ОПТИМИСТИЧНОЕ обновление сразу после успешного upload (чтобы не
// ждать лишний round-trip), но сервер уже обновлён тем же вызовом
// upload (см. upload_common.py) -- refreshSession() при необходимости
// синхронизирует состояние заново.

import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import { STAGE_DEFS, StageStatus } from "../lib/stages";

export interface LogEntry {
  id: number;
  time: string;
  level: "INFO" | "WARNING" | "ERROR";
  message: string;
}

export interface ActiveDataset {
  datasetId?: string;
  name: string;
  rows: number;
  sizeLabel: string;
  // Опциональные поля для автозаполнения DataProfile в модуле «Моделирование».
  // Перенесено без изменений из origin/main (команда, задача 6 в worklog.md).
  // Добавляются при наличии в ответе API загрузки (passport / structure-detection).
  frequency?: string;       // "D" | "W" | "M" | "Q" | "Y"
  domain?: string;          // "financial" | "macro" | "price" | "other"
  nSeries?: number;         // число временных рядов (≥ 1)
  hasSeasonality?: boolean; // обнаружена сезонность
  isRegular?: boolean;      // регулярность временного индекса
}

type StagesMap = Record<string, StageStatus>;

const EMPTY_STAGES: StagesMap = Object.fromEntries(STAGE_DEFS.map((s) => [s.key, "pending" as StageStatus]));

interface SessionCurrentResponse {
  has_active_dataset: boolean;
  dataset: { dataset_id: string; name: string; rows: number; columns: number; size_label: string } | null;
  stages: StagesMap;
  last_active_stage: string | null;
  updated_at: string | null;
}

interface AppShellContextValue {
  activeDataset: ActiveDataset | null;
  setActiveDataset: (dataset: ActiveDataset) => void;
  stages: StagesMap;
  lastActiveStage: string | null;
  sessionLoading: boolean;
  refreshSession: () => Promise<void>;
  log: LogEntry[];
  addLogEntry: (level: LogEntry["level"], message: string) => void;
  clearLog: () => void;
}

const AppShellContext = createContext<AppShellContextValue | null>(null);

export function AppShellProvider({ children }: { children: ReactNode }) {
  const [activeDataset, setActiveDatasetState] = useState<ActiveDataset | null>(null);
  const [stages, setStages] = useState<StagesMap>(EMPTY_STAGES);
  const [lastActiveStage, setLastActiveStage] = useState<string | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [log, setLog] = useState<LogEntry[]>([]);

  const addLogEntry = useCallback((level: LogEntry["level"], message: string) => {
    setLog((prev) => [
      { id: prev.length, time: new Date().toLocaleTimeString("ru-RU"), level, message },
      ...prev,
    ]);
  }, []);

  const applySessionResponse = useCallback((data: SessionCurrentResponse) => {
    if (data.has_active_dataset && data.dataset) {
      setActiveDatasetState({
        datasetId: data.dataset.dataset_id,
        name: data.dataset.name,
        rows: data.dataset.rows,
        sizeLabel: data.dataset.size_label,
      });
    } else {
      setActiveDatasetState(null);
    }
    setStages(data.stages ?? EMPTY_STAGES);
    setLastActiveStage(data.last_active_stage ?? null);
  }, []);

  const refreshSession = useCallback(async () => {
    try {
      const resp = await fetch(sessionApiUrl("/current"), { credentials: "include" });
      if (resp.ok) {
        applySessionResponse(await resp.json());
      }
    } catch {
      // Бэкенд недоступен -- Home page остаётся в состоянии онбординга
      // (activeDataset уже null по умолчанию), без сессии ничего не рушим.
    } finally {
      setSessionLoading(false);
    }
  }, [applySessionResponse]);

  useEffect(() => {
    refreshSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    <AppShellContext.Provider
      value={{
        activeDataset,
        setActiveDataset,
        stages,
        lastActiveStage,
        sessionLoading,
        refreshSession,
        log,
        addLogEntry,
        clearLog,
      }}
    >
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
