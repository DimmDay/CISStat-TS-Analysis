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

/** Короткие пояснения направлений — для подсказок чекбоксов (§2.2). */
export const DIRECTION_DESCRIPTIONS_RU: Record<KnowledgeDirection, string> = {
  seasonality:
    "STL/MSTL, множественные сезонные периоды, сезонный naive, TBATS",
  missing_outliers:
    "Пропуски и дубликаты строк, выбросы: обнаружение и коррекции этапа Предобработки",
  intervals: "Интервалы прогноза, доверительные и предиктивные границы",
  volatility:
    "Условная дисперсия, GARCH/EGARCH, кластеризация волатильности, QLIKE",
  multivariate:
    "VAR/VECM, коинтеграция, векторные OOF-точки и устойчивость системы",
  trees_boosting: "LightGBM/XGBoost/CatBoost и их место в каталоге моделей",
  neural: "Нейросетевые модели: ресурсы, контракты, применимость",
  methodology_validation:
    "Бэктест, утечки данных, честные метрики и методология платформы",
};

// ── Персональный обучающий стек (§2.2: LearningTrackBuilder) ────────

/**
 * Результат сборки персонального стека по выбранным направлениям.
 * Контракты (§13): articles — без дублей, в порядке пайплайна, только
 * published; missing_directions — выбранные направления, по которым
 * опубликованных статей пока нет (честная маркировка «готовится»).
 */
export interface LearningStack {
  /** Запрошенные направления — в порядке запроса пользователя. */
  directions: readonly KnowledgeDirection[];
  /** Статьи стека: dedupe + порядок stage_id пайплайна (§13). */
  articles: readonly KnowledgeArticle[];
  /** Направления запроса без опубликованных статей. */
  missing_directions: readonly KnowledgeDirection[];
}

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

// ── Контекстная справка узлов (Шаг 3, ревизия 2026-09-22: §2.1) ─────
//
// Единый реестр справки — источник истины: секции окна «Описание»
// модулей TsAnalysis*.tsx рендерят запись по (stage_id, node_id, facet)
// через describeNode(...). Никаких строковых констант в компонентах и
// никаких новых справочных поверхностей на узлах (без '?').

/** Грань потребления справки: какая секция окна «Описание» рендерится. */
export type KnowledgeHelpFacet =
  | "metrics" // секция «Метрики и алгоритм» — на уровне узла
  | "pipeline" // секция «Полный пайплайн»/мастер — на уровне узла
  | "module_help" // кнопка «Справка» в заголовке модуля (node_id = null)
  | "stage_overview"; // описание этапа/стадии по умолчанию (узел графа или весь этап)

/**
 * Запись реестра справки — вербатим-текст мигрированной константы.
 * При промоушене в backend становится строкой KnowledgeArticle.body_md
 * (модель spec_education.md §1: node_id/facet уже в контракте ревизии).
 */
export interface KnowledgeHelpEntry {
  /** "validation.data_types.metrics", "eda.module.module_help", ... */
  entry_id: string;
  /** «где в пайплайне» — тот же словарь STAGES (§1.1) */
  stage_id: KnowledgeStageId;
  /** узел стадии (остановка степпера/стадия графа); null — уровень модуля/этапа */
  node_id: string | null;
  /** какая секция окна «Описание» потребляет запись */
  facet: KnowledgeHelpFacet;
  /** аудит происхождения: "TsAnalysisEDA.tsx::DESCRIPTIVE_METRICS_DESCRIPTION" */
  superseded_constant: string;
  /** текст справки — байт-в-байт перенесён из константы (паритет §13) */
  text: string;
}
