// packages/ui/lib/stages.ts
//
// Шесть этапов анализа (см. docs/MIGRATION_ARCHITECTURE.md §1.1 и
// STAGES в apps/api/session_store.py -- ключи должны совпадать 1:1,
// это контракт между фронтендом и сессией). "Задачи" сознательно НЕ
// включены -- отдельная сущность (What-if/iDSS), не шаг пайплайна.

export interface StageDef {
  key: string;
  label: string;
  href: string;
}

export const STAGE_DEFS: StageDef[] = [
  { key: "upload", label: "Загрузка", href: "/data/upload" },
  { key: "validation", label: "Валидация", href: "/validation" },
  { key: "preprocessing", label: "Предобработка", href: "/preprocessing" },
  { key: "eda", label: "Разведочный EDA", href: "/eda" },
  { key: "modeling", label: "Моделирование", href: "/modeling" },
  { key: "forecasting", label: "Прогнозирование", href: "/forecasting" },
];

export type StageStatus = "pending" | "in_progress" | "done";
