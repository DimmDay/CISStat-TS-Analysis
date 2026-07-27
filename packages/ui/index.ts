// packages/ui/index.ts
export { PortalNavBar } from "./components/PortalNavBar";
export { Button } from "./components/Button";
export { Metric } from "./components/Metric";
export { StatusIcon, STATUS_ICON } from "./components/StatusIcon";
export type { CheckStatus } from "./components/StatusIcon";
export { TsAnalysisPreprocessing } from "./components/TsAnalysisPreprocessing";
export { default as tailwindPreset } from "./tailwind-preset";

// Глобальный shell: активный датасет + лог событий (см. решение по
// фидбэку -- убрали постоянную боковую панель, оставили лёгкий контекст-бар).
export { AppShellProvider, useAppShell } from "./context/AppShellContext";
export type { LogEntry, ActiveDataset } from "./context/AppShellContext";
export { DatasetContextBar } from "./components/DatasetContextBar";
export { EventsLogDrawer } from "./components/EventsLogDrawer";
export { DataUploadForm } from "./components/DataUploadForm";
