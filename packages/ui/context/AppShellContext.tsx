"use client";

// packages/ui/context/AppShellContext.tsx
//
// Глобальное состояние, нужное на ЛЮБОЙ странице:
// - какой датасет сейчас активен + на каком этапе остановился пользователь
// - исследуемый признак (target_column) -- шапка панели «Прогресс» §6.1
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
//
// ИЗМЕНЕНИЕ (PROGR-4, spec_progress.md §6.1): клиентский лог
// log/addLogEntry/clearLog УДАЛЁН, не остаётся вторым параллельным
// логом -- его нишу заняла персистентная трасса (§4-§5, слой 1
// PROGR-3, панель ProgressDrawer). Факты решений пишутся хуком на
// бэкенде (§4.2: upload_completed и т.д. -- единая точка интеграции);
// ошибки операций показываются инлайн/тостами своих вкладок. Добавлен
// targetColumn из GET /v1/session/current (шапка панели §6.1: «поле
// есть -- новых данных не требуется»).

import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from "react";
import { sessionApiUrl } from "../lib/apiClient";
import { STAGE_DEFS, StageStatus } from "../lib/stages";

export interface ActiveDataset {
  datasetId?: string;
  name: string;
  rows: number;
  sizeLabel: string;
  // Legacy-метаданные ответа upload API оставлены в shell-контракте
  // для обратной совместимости. Modeling больше не строит из них
  // ручной DataProfile, а читает канонический EDA hand-off из session API.
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
  target_column: string | null;
  // AUDIT-C (контракт docs/progress_audit_contract.md §3.4/§14): серверный
  // контекст расчёта и ревизия данных. Контекст вычисляет ТОЛЬКО сервер
  // (фронт не создаёт догадками и не ведёт счётчик версий, план §6 GREEN);
  // absence -- старый бэкенд или нет активного датасета.
  context_id?: string | null;
  data_revision?: number | null;
  updated_at: string | null;
}

interface AppShellContextValue {
  activeDataset: ActiveDataset | null;
  setActiveDataset: (dataset: ActiveDataset) => void;
  stages: StagesMap;
  lastActiveStage: string | null;
  // Шапка панели «Прогресс» (§6.1). Опционально в контракте: часть
  // тестов мокает контекст частично, отсутствие поля -- не ошибка.
  targetColumn?: string | null;
  // AUDIT-C: серверный контекст расчёта (устойчивый между чтениями) и
  // ревизия данных -- ключи контекста для будущих keyed-кэшей
  // потребителей (AUDIT-3/2B); гидрируются только с сервера.
  contextId?: string | null;
  dataRevision?: number | null;
  sessionLoading: boolean;
  refreshSession: () => Promise<void>;
}

const AppShellContext = createContext<AppShellContextValue | null>(null);

export function AppShellProvider({ children }: { children: ReactNode }) {
  const [activeDataset, setActiveDatasetState] = useState<ActiveDataset | null>(null);
  const [stages, setStages] = useState<StagesMap>(EMPTY_STAGES);
  const [lastActiveStage, setLastActiveStage] = useState<string | null>(null);
  const [targetColumn, setTargetColumn] = useState<string | null>(null);
  // AUDIT-C: гидратация серверного контекста расчёта (источник истины --
  // /current; клиентский стейт -- только кэш для рендера).
  const [contextId, setContextId] = useState<string | null>(null);
  const [dataRevision, setDataRevision] = useState<number | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);

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
    setTargetColumn(data.target_column ?? null);
    setContextId(data.context_id ?? null);
    setDataRevision(typeof data.data_revision === "number" ? data.data_revision : null);
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

  // Оптимистичное обновление сразу после успешного upload; факт
  // upload_completed в трассу пишет бэкенд-хук (§4.2, PROGR-3), поэтому
  // клиентская запись в лог больше не нужна (PROGR-4, §6.1).
  const setActiveDataset = useCallback((dataset: ActiveDataset) => {
    setActiveDatasetState(dataset);
  }, []);

  return (
    <AppShellContext.Provider
      value={{
        activeDataset,
        setActiveDataset,
        stages,
        lastActiveStage,
        targetColumn,
        contextId,
        dataRevision,
        sessionLoading,
        refreshSession,
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