// packages/ui/lib/knowledge/types.ts
//
// Task EDU-1 (spec_education.md, Часть I, §1–2) — типы слоя знаний.
//
// Слой знаний — ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ по методологии платформы:
// UI (хаб «Обучение и база знаний», контекстная справка в будущем)
// рендерит ТОЛЬКО из реестров этого слоя и не содержит текстов.
//
// Словарь stage_id — ТЕ ЖЕ строки, что STAGES платформы
// (apps/api/session_store.py::STAGES, packages/ui/lib/stages.ts), 1:1 —
// контракт §1.1 spec_education.md, застрахован инвариант-тестом.
//
// Тело статьи — структурированные блоки (paragraph/bullets/callout), а не
// сырой markdown: рендер типизирован и тривиален, а при промоушене
// реестра в backend (Этап 1 spec_education.md: KnowledgeArticle.body_md)
// блоки сериализуются в markdown 1:1 (paragraph → абзац, bullets →
// "- ", callout → "> ") без потери содержимого.

import type { LucideIcon } from "lucide-react";
import {
  Upload,
  ShieldCheck,
  Wrench,
  BarChart3,
  Brain,
  TrendingUp,
} from "lucide-react";

// ── Этапы пайплайна (1:1 со STAGES платформы, §1.1) ─────────────

export type KnowledgeStageId =
  | "upload"
  | "validation"
  | "preprocessing"
  | "eda"
  | "modeling"
  | "forecasting";

export const KNOWLEDGE_STAGES: readonly KnowledgeStageId[] = [
  "upload",
  "validation",
  "preprocessing",
  "eda",
  "modeling",
  "forecasting",
];

export const STAGE_LABELS_RU: Record<KnowledgeStageId, string> = {
  upload: "Загрузка",
  validation: "Валидация",
  preprocessing: "Предобработка",
  eda: "Разведочный EDA",
  modeling: "Моделирование",
  forecasting: "Прогнозирование",
};

export const STAGE_ICONS: Record<KnowledgeStageId, LucideIcon> = {
  upload: Upload,
  validation: ShieldCheck,
  preprocessing: Wrench,
  eda: BarChart3,
  modeling: Brain,
  forecasting: TrendingUp,
};

// ── Направления (§2.2: второе измерение тегирования, пересекает этапы) ──

export const KNOWLEDGE_DIRECTIONS = [
  "seasonality",
  "missing_outliers",
  "intervals",
  "volatility",
  "multivariate",
  "trees_boosting",
  "neural",
  "methodology_validation",
] as const;

export type KnowledgeDirection = (typeof KNOWLEDGE_DIRECTIONS)[number];

export const DIRECTION_LABELS_RU: Record<KnowledgeDirection, string> = {
  seasonality: "Работа с сезонностью",
  missing_outliers: "Пропуски и выбросы",
  intervals: "Интервальное прогнозирование",
  volatility: "Волатильность финансовых рядов",
  multivariate: "Многомерные модели (VAR/VECM)",
  trees_boosting: "Модели на деревьях и бустинге",
  neural: "Нейросетевые модели",
  methodology_validation: "Методология и валидация",
};

// ── Цитаты источников (§7.1: официальные/авторитетные) ──────────

export interface KnowledgeCitation {
  /** "book" | "paper" | "official_docs" */
  kind: "book" | "paper" | "official_docs";
  /** Человекочитаемая ссылка: «Hyndman & Athanasopoulos, FPP3, 3rd ed.» */
  label: string;
  url?: string;
}

// ── Блоки тела статьи (структурированное подмножество markdown) ──

export type KnowledgeBlock =
  | { type: "paragraph"; text: string }
  | { type: "bullets"; items: readonly string[] }
  | { type: "callout"; text: string };

// ── Статья базы знаний (spec_education.md §1) ────────────────────

export type KnowledgeArticleStatus = "published" | "draft";

export interface KnowledgeArticle {
  article_id: string;
  /** «где в пайплайне» (§2.2, первое измерение тегирования) */
  stage_id: KnowledgeStageId;
  /** «про что тематически» (§2.2, второе измерение) */
  directions: readonly KnowledgeDirection[];
  title: string;
  summary: string;
  reading_minutes: number;
  body: readonly KnowledgeBlock[];
  sources: readonly KnowledgeCitation[];
  status: KnowledgeArticleStatus;
}

// ── Термин словаря ──────────────────────────────────────────────

export interface GlossaryTerm {
  term_id: string;
  term: string;
  definition: string;
  /** Связанные статьи библиотеки (связность базы знаний) */
  related_article_ids: readonly string[];
  /** Этапы, где термин встречается в работе */
  stage_ids: readonly KnowledgeStageId[];
}
