// packages/ui/lib/knowledge/knowledge.ts
//
// Task EDU-1 (spec_education.md, Часть I) — API доступа к базе знаний.
// Единственная точка, через которую UI читает реестры: фильтры, поиск,
// сортировка. Прямой импорт реестров компонентами — только для
// инвариант-тестов; для рендера используется этот модуль.
//
// Контракты (spec_education.md):
//   - §13: порядок статей всегда следует порядку stage_id в пайплайне;
//   - принцип честности: draft-статьи не попадают в публичную выдачу;
//   - поиск ищет по заголовку/summary/телу статей и по терминам словаря.

import type {
  KnowledgeArticle,
  KnowledgeDirection,
  KnowledgeStageId,
  GlossaryTerm,
} from "./types";
import { KNOWLEDGE_STAGES } from "./types";
import { KNOWLEDGE_ARTICLES } from "./articles";
import { GLOSSARY_TERMS } from "./glossary";

/** Порядок этапа в пайплайне (для сортировки выдачи, §13). */
export const STAGE_ORDER_INDEX: Record<KnowledgeStageId, number> =
  Object.fromEntries(KNOWLEDGE_STAGES.map((s, i) => [s, i])) as Record<
    KnowledgeStageId,
    number
  >;

/** Все статьи реестра (включая draft) — для админ-контекстов и тестов. */
export function getAllArticles(): KnowledgeArticle[] {
  return [...KNOWLEDGE_ARTICLES];
}

/**
 * Опубликованные статьи в порядке пайплайна (§13).
 * Внутри одного этапа — по заголовку (стабильный, предсказуемый порядок).
 */
export function getPublishedArticles(): KnowledgeArticle[] {
  return KNOWLEDGE_ARTICLES.filter((a) => a.status === "published").sort(
    (a, b) =>
      STAGE_ORDER_INDEX[a.stage_id] - STAGE_ORDER_INDEX[b.stage_id] ||
      a.title.localeCompare(b.title, "ru"),
  );
}

/** Статья по точному id (включая draft — читатель может открыть ссылку). */
export function getArticleById(articleId: string): KnowledgeArticle | undefined {
  return KNOWLEDGE_ARTICLES.find((a) => a.article_id === articleId);
}

/** Опубликованные статьи одного этапа (фильтр Библиотеки). */
export function getArticlesByStage(stage: KnowledgeStageId): KnowledgeArticle[] {
  return getPublishedArticles().filter((a) => a.stage_id === stage);
}

/** Опубликованные статьи одного направления (§2.2: пересекает этапы). */
export function getArticlesByDirection(
  direction: KnowledgeDirection,
): KnowledgeArticle[] {
  return getPublishedArticles().filter((a) => a.directions.includes(direction));
}

/** Термины словаря в алфавитном порядке (ru). */
export function getGlossaryTerms(): GlossaryTerm[] {
  return [...GLOSSARY_TERMS].sort((a, b) => a.term.localeCompare(b.term, "ru"));
}

/** Термин по точному id. */
export function getTermById(termId: string): GlossaryTerm | undefined {
  return GLOSSARY_TERMS.find((t) => t.term_id === termId);
}

export interface KnowledgeSearchResult {
  articles: KnowledgeArticle[];
  terms: GlossaryTerm[];
}

/**
 * Поиск по базе знаний: статьи (заголовок, summary, тело) + термины.
 * Регистронезависимый, подстрочный; пустой запрос возвращает всю базу.
 * Статьи в выдаче — только published (draft в поиск не попадает).
 */
export function searchKnowledge(rawQuery: string): KnowledgeSearchResult {
  const query = rawQuery.trim().toLowerCase();

  const published = getPublishedArticles();
  const terms = getGlossaryTerms();

  if (query === "") {
    return { articles: published, terms };
  }

  const articles = published.filter((a) => {
    const haystackParts: string[] = [a.title, a.summary];
    for (const block of a.body) {
      if (block.type === "bullets") {
        haystackParts.push(...block.items);
      } else {
        haystackParts.push(block.text);
      }
    }
    return haystackParts.some((part) => part.toLowerCase().includes(query));
  });

  const matchedTerms = terms.filter(
    (t) =>
      t.term.toLowerCase().includes(query) ||
      t.definition.toLowerCase().includes(query),
  );

  return { articles, terms: matchedTerms };
}
