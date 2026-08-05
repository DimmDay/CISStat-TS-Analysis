// packages/ui/index.ts
export { PortalNavBar } from "./components/PortalNavBar";
export { Button } from "./components/Button";
export { Metric } from "./components/Metric";
export { StatusIcon, STATUS_ICON } from "./components/StatusIcon";
export type { CheckStatus } from "./components/StatusIcon";
export { TsAnalysisPreprocessing } from "./components/TsAnalysisPreprocessing";
export { TsAnalysisValidation } from "./components/TsAnalysisValidation";
export { TsAnalysisEDA } from "./components/TsAnalysisEDA";
export { default as tailwindPreset } from "./tailwind-preset";

// Глобальный shell: активный датасет + лог событий.
export { AppShellProvider, useAppShell } from "./context/AppShellContext";
export type { LogEntry, ActiveDataset } from "./context/AppShellContext";
export { DatasetContextBar } from "./components/DatasetContextBar";
export { EventsLogDrawer } from "./components/EventsLogDrawer";
export { DataUploadForm } from "./components/DataUploadForm";

// Навигация между модулями анализа (Загрузка/Валидация/Предобработка/...).
export { ModuleNav } from "./components/ModuleNav";
export { ModulePlaceholder } from "./components/ModulePlaceholder";

// Контракт Роль/План/Возможности (зеркало apps/api/plans.py) -- только для UX,
// реальная защита на бэкенде.
export { getCapabilities, PLAN_DEFINITIONS } from "./lib/plans";
export type { Role, PlanName, Capabilities } from "./lib/plans";
export { TrainModelButton } from "./components/TrainModelButton";
