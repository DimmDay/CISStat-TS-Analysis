// packages/ui/lib/plans.ts
//
// TypeScript-зеркало контракта из apps/api/plans.py.
//
// ⚠️ ЭТО ТОЛЬКО ДЛЯ UX (скрыть кнопку "Обучить модель" для плана без этой
// возможности). РЕАЛЬНАЯ защита -- всегда на бэкенде через
// Depends(require_capability(...)) в apps/api. Скрытие кнопки в интерфейсе
// не заменяет проверку на сервере -- это ровно то предостережение, которое
// уже зафиксировано в предыдущем обсуждении ролей/тарифов.
//
// Поддерживайте это в синхронизации с apps/api/plans.py вручную, либо
// (лучше) сгенерируйте оба файла из единой OpenAPI-схемы FastAPI, когда
// дойдёте до автоматизации контракта.

export type Role = "admin" | "internal_analyst" | "external_user";

export type PlanName = "demo" | "starter" | "professional" | "enterprise";

export interface Capabilities {
  canTrainModels: boolean;
  canUseApi: boolean;
  canSaveHistory: boolean;
  canUploadOwnData: boolean;
  maxDatasetRows: number | null;
  maxApiCallsPerMonth: number | null;
  maxAnalysesTotal: number | null;
  trialDays: number | null;
  watermarkExports: boolean;
}

export const PLAN_DEFINITIONS: Record<PlanName, Capabilities> = {
  demo: {
    canTrainModels: false,
    canUseApi: false,
    canSaveHistory: false,
    canUploadOwnData: true,
    maxDatasetRows: 5_000,
    maxApiCallsPerMonth: 0,
    maxAnalysesTotal: 10,
    trialDays: 14,
    watermarkExports: true,
  },
  starter: {
    canTrainModels: false,
    canUseApi: true,
    canSaveHistory: true,
    canUploadOwnData: true,
    maxDatasetRows: 50_000,
    maxApiCallsPerMonth: 1_000,
    maxAnalysesTotal: null,
    trialDays: null,
    watermarkExports: false,
  },
  professional: {
    canTrainModels: true,
    canUseApi: true,
    canSaveHistory: true,
    canUploadOwnData: true,
    maxDatasetRows: null,
    maxApiCallsPerMonth: 50_000,
    maxAnalysesTotal: null,
    trialDays: null,
    watermarkExports: false,
  },
  enterprise: {
    canTrainModels: true,
    canUseApi: true,
    canSaveHistory: true,
    canUploadOwnData: true,
    maxDatasetRows: null,
    maxApiCallsPerMonth: null,
    maxAnalysesTotal: null,
    trialDays: null,
    watermarkExports: false,
  },
};

const INTERNAL_CAPABILITIES: Capabilities = {
  canTrainModels: true,
  canUseApi: true,
  canSaveHistory: true,
  canUploadOwnData: true,
  maxDatasetRows: null,
  maxApiCallsPerMonth: null,
  maxAnalysesTotal: null,
  trialDays: null,
  watermarkExports: false,
};

export function getCapabilities(role: Role, plan: PlanName | null): Capabilities {
  if (role === "admin" || role === "internal_analyst") {
    return INTERNAL_CAPABILITIES;
  }
  if (!plan) {
    throw new Error(`У роли ${role} нет плана, но getCapabilities вызван без него`);
  }
  return PLAN_DEFINITIONS[plan];
}
