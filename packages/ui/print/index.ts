// packages/ui/print/index.ts
//
// PGV-07 — Shared pure print layout: публичный баррель print-бандла.
//
// Потребители: print-renderer worker (PGV-08 собирает print page из этих
// компонентов), страницы поставки/превью, оракулы. Импорт напрямую из
// packages/ui/print (не через packages/ui/index.ts): компоненты без хуков
// и обработчиков рендерятся в server-контексте, barrel продукта
// сознательно не расширяется (граница поставки).
//
// Всё содержимое — pure presentation (§4.1): без fetch/state/animation,
// светлая тема инлайном (AC04), детерминированные форматтеры.

export * from "./printTheme";
export * from "./printLayout";
export * from "./printSections";
export * from "./printIh";
export * from "./printPassport";
export * from "./printComparison";
