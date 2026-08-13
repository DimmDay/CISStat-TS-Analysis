// packages/ui/index.ts
export { PortalNavBar } from "./components/PortalNavBar";
export { Button } from "./components/Button";
export { Metric } from "./components/Metric";
export { StatusIcon, STATUS_ICON } from "./components/StatusIcon";
export type { CheckStatus } from "./components/StatusIcon";
export { TsAnalysisPreprocessing } from "./components/TsAnalysisPreprocessing";
export { TsAnalysisValidation } from "./components/TsAnalysisValidation";
export { TsAnalysisEDA } from "./components/TsAnalysisEDA";
export { TsAnalysisUpload } from "./components/TsAnalysisUpload";
export { StructuralClassSchema } from "./components/StructuralClassSchema";
export { classifyStructure } from "./lib/structuralClass";
export type { StructuralClass, StructuralClassResult, PanelBalance } from "./lib/structuralClass";
export { default as tailwindPreset } from "./tailwind-preset";

// Глобальный shell: активный датасет (гидрируется с сервера, см.
// apps/api/session_store.py) + прогресс по этапам + лог событий.
export { AppShellProvider, useAppShell } from "./context/AppShellContext";
export type { LogEntry, ActiveDataset } from "./context/AppShellContext";
export { EventsLogDrawer } from "./components/EventsLogDrawer";

// Sessions-aware Home: общий "Рабочий стол" + embedded-онбординг.
// Standalone-версия (с auth-веткой) живёт в apps/standalone/components --
// см. обсуждение с тимлидом про разные ответственности embedded/standalone.
export { WorkbenchSummary } from "./components/WorkbenchSummary";
export { EmbeddedHome } from "./components/EmbeddedHome";
export { STAGE_DEFS } from "./lib/stages";
export type { StageDef, StageStatus } from "./lib/stages";
export { apiUrl, sessionApiUrl, getApiBase, getApiMode } from "./lib/apiClient";
export type { ApiMode } from "./lib/apiClient";

// Навигация между модулями анализа (Загрузка/Валидация/Предобработка/...).
export { ModuleNav } from "./components/ModuleNav";
export { ModulePlaceholder } from "./components/ModulePlaceholder";

// Контракт Роль/План/Возможности (зеркало apps/api/plans.py) -- только для UX,
// реальная защита на бэкенде.
export { getCapabilities, PLAN_DEFINITIONS } from "./lib/plans";
export type { Role, PlanName, Capabilities } from "./lib/plans";
export { TrainModelButton } from "./components/TrainModelButton";

// ── Ниже: перенесено без изменений из origin/main (команда, "Моделирование") ──

export { TsAnalysisModeling } from "./components/TsAnalysisModeling";

// Типы моделирования (зеркало apps/api/schemas.py).
export type {
  DataProfile,
  ModelCandidate,
  CandidatesRequest,
  CandidatesResponse,
  CandidatesStatistics,
  ApplicabilityLevel,
  PipelineStage,
  ModelFamily,
  BacktestRequest,
  BacktestMetrics,
  BacktestResponse,
  TargetColumnRequest,
  TargetColumnResponse,
} from "./lib/modeling";
export {
  APPLICABILITY_RANK,
  APPLICABILITY_LABEL,
  APPLICABILITY_BADGE,
  MODEL_FAMILIES,
  PIPELINE_STAGES,
  DEFAULT_PROFILE,
  DOMAINS,
  FREQUENCIES,
  BACKTEST_WEIGHTS,
} from "./lib/modeling";

// Панель «Управление правилами» — рендерится внутри TsAnalysisValidation.
export { RulesManagementPanel } from "./components/RulesManagementPanel";
