// packages/ui/lib/knowledge/knowledge.ts
//
// Task EDU-1 (spec_education.md, Часть I) — API доступа к базе знаний.
// Единственная точка, через которую UI читает реестры: фильтры, поиск,
// сортировка. Прямой импорт реестров компонентами — только для
// инвариант-тестов; для рендера используется этот модуль.
//
// Task EDU-2 (spec_education.md, §2.2) — обучающие стеки по направлениям:
// buildLearningStack() собирает персональную траекторию из множества
// направлений (чекбоксы дают МНОЖЕСТВО), порядок статей в стеке всегда
// идёт по пайплайну (не по порядку выбора чекбоксов) — личная
// траектория, но не хаотичная. LearningTrackBuilder — UI над этим API.
//
// Контракты (spec_education.md):
//   - §13: порядок статей всегда следует порядку stage_id в пайплайне;
//   - §2.2: два независимых измерения тегирования — stage_id («где в
//     пайплайне») и directions («про что тематически»);
//   - принцип честности: draft-статьи не попадают в публичную выдачу;
//   - поиск ищет по заголовку/summary/телу статей и по терминам словаря.

import type {
  KnowledgeArticle,
  KnowledgeDirection,
  KnowledgeStageId,
  GlossaryTerm,
} from "./types";
import { KNOWLEDGE_STAGES, KNOWLEDGE_DIRECTIONS } from "./types";
import { KNOWLEDGE_ARTICLES } from "./articles";
import { GLOSSARY_TERMS } from "./glossary";

/** Порядок этапа в пайплайне (для сортировки выдачи, §13). */
export const STAGE_ORDER_INDEX: Record<KnowledgeStageId, number> =
  Object.fromEntries(KNOWLEDGE_STAGES.map((s, i) => [s, i])) as Record<
    KnowledgeStageId,
    number
  >;

/** Канонический порядок направлений (§2.2) — для нормализации выдачи. */
export const DIRECTION_ORDER_INDEX: Record<KnowledgeDirection, number> =
  Object.fromEntries(KNOWLEDGE_DIRECTIONS.map((d, i) => [d, i])) as Record<
    KnowledgeDirection,
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

// ── Обучающие стеки по направлениям (§2.2, Task EDU-2) ───────────

/**
 * Персональный обучающий стек (§2.2): результат POST /v1/learning/track
 * на стороне UI (до промоушена слоя знаний в backend — Этап 4 спеки).
 * Статьи — опубликованные, объединение выбранных направлений,
 * дедупликация по article_id, порядок строго по пайплайну (§13).
 * Термины — только те, что связаны со статьями стека (related_article_ids),
 * в алфавитном порядке; термины «в пустоту» не выдаются.
 */
export interface LearningStack {
  /** Направления стека — нормализованы к каноническому порядку §2.2. */
  directions: readonly KnowledgeDirection[];
  /** Статьи стека — порядок пайплайна (§13), независимо от порядка чекбоксов. */
  articles: KnowledgeArticle[];
  /** Термины словаря, связанные со статьями стека (алфавитный порядок). */
  terms: GlossaryTerm[];
}

/**
 * Строит обучающий стек по МНОЖЕСТВУ направлений (§2.2).
 * Пустой/неизвестный ввод → пустой стек: вызывающий код обязан показать
 * «справка готовится» (no fabricated results), а не подменять траекторию
 * всей базой знаний. Направления дедуплицируются и нормализуются к
 * каноническому порядку KNOWLEDGE_DIRECTIONS — детерминизм для тестов
 * и рендера независимо от порядка кликов по чекбоксам.
 */
export function buildLearningStack(
  rawDirections: readonly KnowledgeDirection[],
): LearningStack {
  const directions = KNOWLEDGE_DIRECTIONS.filter((d) =>
    rawDirections.includes(d),
  );

  if (directions.length === 0) {
    return { directions: [], articles: [], terms: [] };
  }

  const seen = new Set<string>();
  const articles: KnowledgeArticle[] = [];
  for (const direction of directions) {
    for (const article of getArticlesByDirection(direction)) {
      if (!seen.has(article.article_id)) {
        seen.add(article.article_id);
        articles.push(article);
      }
    }
  }
  // Инвариант §2.2/§13: порядок стека — по пайплайну, НЕ по порядку
  // выбора чекбоксов и не по порядку направлений во вводе.
  articles.sort(
    (a, b) =>
      STAGE_ORDER_INDEX[a.stage_id] - STAGE_ORDER_INDEX[b.stage_id] ||
      a.title.localeCompare(b.title, "ru"),
  );

  const articleIds = new Set(articles.map((a) => a.article_id));
  const terms = getGlossaryTerms().filter((t) =>
    t.related_article_ids.some((id) => articleIds.has(id)),
  );

  return { directions, articles, terms };
}

/**
 * Число опубликованных статей по каждому направлению (§2.2).
 * Счётчик для чекбоксов LearningTrackBuilder: пользователь видит,
 * сколько материала даст каждое направление, ДО построения стека.
 * Направления без опубликованных статей честно получают 0.
 */
export function getDirectionArticleCounts(): Record<KnowledgeDirection, number> {
  const counts = Object.fromEntries(
    KNOWLEDGE_DIRECTIONS.map((d) => [d, 0]),
  ) as Record<KnowledgeDirection, number>;
  for (const article of getPublishedArticles()) {
    for (const direction of article.directions) {
      counts[direction] += 1;
    }
  }
  return counts;
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
