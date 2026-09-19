// packages/ui/lib/knowledge/knowledge.test.ts
//
// Task EDU-1 (spec_education.md, Часть I, Этап 1 роллаута) — инварианты
// слоя знаний и контракт доступа. Слой знаний — ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ
// по методологии: UI рендерит ТОЛЬКО из реестров, ничего не хардкодит.
//
// Ключевые контракты (по spec_education.md):
//   - §1.1: словарь stage_id — ТЕ ЖЕ строки, что STAGES платформы
//     (apps/api/session_store.py / packages/ui/lib/stages.ts), 1:1;
//   - §2.2: два независимых измерения тегирования — stage_id («где в
//     пайплайне») и directions («про что тематически»);
//   - §13: порядок статей в выдаче всегда следует порядку stage_id в
//     пайплайне, а не порядку добавления записей;
//   - принцип честной маркировки: status="draft" не попадает в
//     публичную выдачу страницы (no fabricated content).

import {
  KNOWLEDGE_STAGES,
  DIRECTION_LABELS_RU,
  STAGE_LABELS_RU,
} from "./types";
import { KNOWLEDGE_ARTICLES } from "./articles";
import { GLOSSARY_TERMS } from "./glossary";
import {
  getPublishedArticles,
  getArticleById,
  getArticlesByStage,
  getArticlesByDirection,
  getGlossaryTerms,
  getTermById,
  searchKnowledge,
  STAGE_ORDER_INDEX,
} from "./knowledge";

// ── 1. Словарь этапов — контракт 1:1 с платформой (§1.1) ────────

describe("KNOWLEDGE_STAGES (единый словарь id с платформой)", () => {
  it("содержит ровно 6 этапов пайплайна в правильном порядке", () => {
    expect([...KNOWLEDGE_STAGES]).toEqual([
      "upload",
      "validation",
      "preprocessing",
      "eda",
      "modeling",
      "forecasting",
    ]);
  });

  it("каждый этап имеет человекочитаемую русскую метку", () => {
    for (const stage of KNOWLEDGE_STAGES) {
      expect(typeof STAGE_LABELS_RU[stage]).toBe("string");
      expect(STAGE_LABELS_RU[stage].length).toBeGreaterThan(0);
    }
  });

  it("каждое направление имеет человекочитаемую русскую метку (§2.2)", () => {
    const keys = Object.keys(DIRECTION_LABELS_RU);
    expect(keys.length).toBeGreaterThanOrEqual(6);
    for (const key of keys) {
      expect((DIRECTION_LABELS_RU as Record<string, string>)[key].length).toBeGreaterThan(0);
    }
  });
});

// ── 2. Инварианты реестра статей ─────────────────────────────────

describe("KNOWLEDGE_ARTICLES (инварианты реестра)", () => {
  it("непуст и все статьи имеют уникальные article_id", () => {
    expect(KNOWLEDGE_ARTICLES.length).toBeGreaterThanOrEqual(8);
    const ids = KNOWLEDGE_ARTICLES.map((a) => a.article_id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("каждая статья привязана к валидному stage_id из KNOWLEDGE_STAGES", () => {
    for (const a of KNOWLEDGE_ARTICLES) {
      expect(KNOWLEDGE_STAGES).toContain(a.stage_id);
    }
  });

  it("directions каждой статьи — подмножество известного словаря направлений", () => {
    const directionKeys = new Set(Object.keys(DIRECTION_LABELS_RU));
    for (const a of KNOWLEDGE_ARTICLES) {
      expect(a.directions.length).toBeGreaterThanOrEqual(1);
      for (const d of a.directions) {
        expect(directionKeys.has(d)).toBe(true);
      }
    }
  });

  it("тело статьи непустое и состоит из валидных блоков", () => {
    for (const a of KNOWLEDGE_ARTICLES) {
      expect(a.body.length).toBeGreaterThanOrEqual(3);
      for (const block of a.body) {
        if (block.type === "paragraph" || block.type === "callout") {
          expect(block.text.trim().length).toBeGreaterThan(0);
        } else if (block.type === "bullets") {
          expect(block.items.length).toBeGreaterThanOrEqual(2);
          for (const item of block.items) {
            expect(item.trim().length).toBeGreaterThan(0);
          }
        } else {
          throw new Error(`Неизвестный тип блока: ${(block as { type: string }).type}`);
        }
      }
    }
  });

  it("у каждой статьи есть sources (§7: официальные/авторитетные источники)", () => {
    for (const a of KNOWLEDGE_ARTICLES) {
      expect(a.sources.length).toBeGreaterThanOrEqual(1);
      for (const c of a.sources) {
        expect(["book", "paper", "official_docs"]).toContain(c.kind);
        expect(c.label.trim().length).toBeGreaterThan(0);
      }
    }
  });

  it("summary и reading_minutes заполнены (reading_minutes > 0)", () => {
    for (const a of KNOWLEDGE_ARTICLES) {
      expect(a.summary.trim().length).toBeGreaterThanOrEqual(10);
      expect(a.reading_minutes).toBeGreaterThan(0);
    }
  });

  it("status — только published или draft (честная маркировка)", () => {
    for (const a of KNOWLEDGE_ARTICLES) {
      expect(["published", "draft"]).toContain(a.status);
    }
  });

  it("каждый этап пайплайна покрыт хотя бы одной опубликованной статьёй", () => {
    for (const stage of KNOWLEDGE_STAGES) {
      const published = KNOWLEDGE_ARTICLES.filter(
        (a) => a.stage_id === stage && a.status === "published",
      );
      expect(published.length).toBeGreaterThanOrEqual(1);
    }
  });
});

// ── 3. Инварианты реестра словаря терминов ──────────────────────

describe("GLOSSARY_TERMS (инварианты реестра)", () => {
  it("непуст и все термины имеют уникальные term_id", () => {
    expect(GLOSSARY_TERMS.length).toBeGreaterThanOrEqual(16);
    const ids = GLOSSARY_TERMS.map((t) => t.term_id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("related_article_ids термина существуют в реестре статей", () => {
    const articleIds = new Set(KNOWLEDGE_ARTICLES.map((a) => a.article_id));
    for (const t of GLOSSARY_TERMS) {
      for (const ref of t.related_article_ids) {
        expect(articleIds.has(ref)).toBe(true);
      }
    }
  });

  it("stage_ids термина — валидные этапы", () => {
    for (const t of GLOSSARY_TERMS) {
      for (const s of t.stage_ids) {
        expect(KNOWLEDGE_STAGES).toContain(s);
      }
    }
  });

  it("определения непустые и содержательные (>= 20 символов)", () => {
    for (const t of GLOSSARY_TERMS) {
      expect(t.term.trim().length).toBeGreaterThan(0);
      expect(t.definition.trim().length).toBeGreaterThanOrEqual(20);
    }
  });
});

// ── 4. API доступа: порядок, фильтры (§13) ───────────────────────

describe("API доступа (порядок пайплайна, фильтры)", () => {
  it("STAGE_ORDER_INDEX отражает порядок пайплайна", () => {
    expect(STAGE_ORDER_INDEX.upload).toBeLessThan(STAGE_ORDER_INDEX.validation);
    expect(STAGE_ORDER_INDEX.validation).toBeLessThan(STAGE_ORDER_INDEX.preprocessing);
    expect(STAGE_ORDER_INDEX.preprocessing).toBeLessThan(STAGE_ORDER_INDEX.eda);
    expect(STAGE_ORDER_INDEX.eda).toBeLessThan(STAGE_ORDER_INDEX.modeling);
    expect(STAGE_ORDER_INDEX.modeling).toBeLessThan(STAGE_ORDER_INDEX.forecasting);
  });

  it("getPublishedArticles отдаёт только published, порядок следует пайплайну", () => {
    const published = getPublishedArticles();
    expect(published.length).toBe(
      KNOWLEDGE_ARTICLES.filter((a) => a.status === "published").length,
    );
    for (let i = 1; i < published.length; i += 1) {
      expect(STAGE_ORDER_INDEX[published[i].stage_id]).toBeGreaterThanOrEqual(
        STAGE_ORDER_INDEX[published[i - 1].stage_id],
      );
    }
  });

  it("getArticleById находит по точному id и возвращает undefined для отсутствующего", () => {
    const first = KNOWLEDGE_ARTICLES[0];
    expect(getArticleById(first.article_id)?.article_id).toBe(first.article_id);
    expect(getArticleById("no-such-article-id")).toBeUndefined();
  });

  it("getArticlesByStage фильтрует только published данного этапа", () => {
    const eda = getArticlesByStage("eda");
    expect(eda.length).toBeGreaterThanOrEqual(1);
    for (const a of eda) {
      expect(a.stage_id).toBe("eda");
      expect(a.status).toBe("published");
    }
  });

  it("getArticlesByDirection фильтрует по направлению, включая пересечение этапов", () => {
    const seasonality = getArticlesByDirection("seasonality");
    expect(seasonality.length).toBeGreaterThanOrEqual(2);
    const stages = new Set(seasonality.map((a) => a.stage_id));
    // направление «Работа с сезонностью» пересекает этапы (§2.2)
    expect(stages.size).toBeGreaterThanOrEqual(2);
    for (const a of seasonality) {
      expect(a.directions).toContain("seasonality");
    }
  });
});

// ── 5. Словарь: алфавитный порядок и поиск ──────────────────────

describe("Словарь терминов (API)", () => {
  it("getGlossaryTerms возвращает термины в алфавитном порядке (ru)", () => {
    const terms = getGlossaryTerms();
    expect(terms.length).toBe(GLOSSARY_TERMS.length);
    for (let i = 1; i < terms.length; i += 1) {
      const cmp = terms[i].term.localeCompare(terms[i - 1].term, "ru");
      expect(cmp).toBeGreaterThanOrEqual(0);
    }
  });

  it("getTermById находит по точному id", () => {
    const first = GLOSSARY_TERMS[0];
    expect(getTermById(first.term_id)?.term_id).toBe(first.term_id);
    expect(getTermById("no-such-term")).toBeUndefined();
  });
});

// ── 6. Поиск по базе знаний ──────────────────────────────────────

describe("searchKnowledge", () => {
  it("пустой запрос возвращает всю базу (статьи published + все термины)", () => {
    const empty = searchKnowledge("   ");
    expect(empty.articles.length).toBe(getPublishedArticles().length);
    expect(empty.terms.length).toBe(GLOSSARY_TERMS.length);
  });

  it("находит статьи по заголовку и термины по названию, без дублей", () => {
    const hit = searchKnowledge("ARIMA");
    expect(hit.articles.length).toBeGreaterThan(0);
    expect(hit.terms.length).toBeGreaterThan(0);
    const articleIds = hit.articles.map((a) => a.article_id);
    expect(new Set(articleIds).size).toBe(articleIds.length);
  });

  it("поиск регистронезависим и ищет по телу статьи", () => {
    const lower = searchKnowledge("стационарност");
    expect(lower.articles.length).toBeGreaterThan(0);
  });

  it("пустой результат — честный ноль, не подмена", () => {
    const miss = searchKnowledge("zzz-нет-такого-термина-xyz");
    expect(miss.articles.length).toBe(0);
    expect(miss.terms.length).toBe(0);
  });
});
