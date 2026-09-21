// packages/ui/lib/knowledge/track.test.ts
//
// Task EDU-2 (spec_education.md, §2.2) — контракты обучающих стеков
// по направлениям на уровне слоя знаний. LearningTrackBuilder — UI над
// этим API, поэтому инварианты страхуются здесь, до рендера.
//
// Ключевые контракты (по spec_education.md):
//   - §2.2: чекбоксы дают МНОЖЕСТВО направлений; стек — объединение
//     опубликованных статей выбранных направлений без дублей;
//   - §2.2/§13: порядок статей в стеке ВСЕГДА по пайплайну — не по
//     порядку выбора чекбоксов и не по порядку направлений во вводе;
//   - принцип честности: draft-статьи не попадают в стек; пустой ввод →
//     пустой стек («справка готовится» — решение вызывающего кода,
//     слой знаний не подменяет траекторию всей базой);
//   - термины стека — только связанные со статьями стека
//     (related_article_ids), термины «в пустоту» не выдаются;
//   - счётчики направлений честные: направление без опубликованных
//     статей получает 0 (no fabricated content).

import {
  KNOWLEDGE_DIRECTIONS,
  DIRECTION_LABELS_RU,
  KNOWLEDGE_STAGES,
  type KnowledgeDirection,
} from "./types";
import { GLOSSARY_TERMS } from "./glossary";
import {
  buildLearningStack,
  getDirectionArticleCounts,
  getPublishedArticles,
  getArticlesByDirection,
  STAGE_ORDER_INDEX,
  DIRECTION_ORDER_INDEX,
} from "./knowledge";

const published = getPublishedArticles();

// ── 1. Пустой и вырожденный ввод — честность (§2.2) ─────────────

describe("buildLearningStack — пустой ввод (принцип честности)", () => {
  it("пустой список направлений → полностью пустой стек", () => {
    const stack = buildLearningStack([]);
    expect(stack.directions).toEqual([]);
    expect(stack.articles).toEqual([]);
    expect(stack.terms).toEqual([]);
  });
});

// ── 2. Одно направление — подмножество published, только tagged ──

describe("buildLearningStack — одно направление", () => {
  it("стек содержит только опубликованные статьи этого направления", () => {
    for (const direction of KNOWLEDGE_DIRECTIONS) {
      const stack = buildLearningStack([direction]);
      expect(stack.directions).toEqual([direction]);
      for (const article of stack.articles) {
        expect(article.status).toBe("published");
        expect(article.directions).toContain(direction);
      }
      // эквивалентность с прямым фильтром Библиотеки
      expect(stack.articles.map((a) => a.article_id)).toEqual(
        getArticlesByDirection(direction).map((a) => a.article_id),
      );
    }
  });

  it("направление без опубликованных статей → пустой стек статей (volatility, multivariate)", () => {
    // честность: направление с 0 статей даёт 0 статей, а не «всю базу»
    const emptyDirections = KNOWLEDGE_DIRECTIONS.filter(
      (d) => !published.some((a) => a.directions.includes(d)),
    );
    expect(emptyDirections.length).toBeGreaterThan(0); // в реестре такие есть
    for (const direction of emptyDirections) {
      const stack = buildLearningStack([direction]);
      expect(stack.articles).toEqual([]);
      expect(stack.terms).toEqual([]);
    }
  });
});

// ── 3. Множество направлений — объединение без дублей, §13 ──────

describe("buildLearningStack — множество направлений (§2.2)", () => {
  it("стек — объединение статей выбранных направлений без дублей по article_id", () => {
    const selected: readonly KnowledgeDirection[] = [
      "seasonality",
      "intervals",
      "methodology_validation",
    ];
    const stack = buildLearningStack([...selected]);
    const ids = stack.articles.map((a) => a.article_id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const article of stack.articles) {
      expect(article.directions.some((d) => selected.includes(d))).toBe(true);
    }
    // объединение = сумма прямых фильтров минус пересечения
    const expectedIds = new Set(
      selected.flatMap((d) => getArticlesByDirection(d).map((a) => a.article_id)),
    );
    expect(new Set(ids)).toEqual(expectedIds);
  });

  it("порядок статей — строго по пайплайну (§13), внутри этапа по заголовку", () => {
    const stack = buildLearningStack(["neural", "seasonality", "intervals"]);
    const stages = stack.articles.map((a) => a.stage_id);
    for (let i = 1; i < stages.length; i++) {
      expect(STAGE_ORDER_INDEX[stages[i - 1]]).toBeLessThanOrEqual(
        STAGE_ORDER_INDEX[stages[i]],
      );
    }
    for (let i = 1; i < stack.articles.length; i++) {
      const prev = stack.articles[i - 1];
      const curr = stack.articles[i];
      if (prev.stage_id === curr.stage_id) {
        expect(prev.title.localeCompare(curr.title, "ru")).toBeLessThanOrEqual(0);
      }
    }
  });

  it("порядок выбора чекбоксов НЕ влияет на содержимое и порядок стека", () => {
    const a = buildLearningStack(["neural", "seasonality", "intervals"]);
    const b = buildLearningStack(["intervals", "neural", "seasonality"]);
    const c = buildLearningStack(["intervals", "seasonality", "neural"]);
    const idsOf = (s: ReturnType<typeof buildLearningStack>) =>
      s.articles.map((x) => x.article_id);
    expect(idsOf(a)).toEqual(idsOf(b));
    expect(idsOf(b)).toEqual(idsOf(c));
    expect(a.directions).toEqual(b.directions);
  });

  it("дубли направлений во вводе дедуплицируются", () => {
    const single = buildLearningStack(["seasonality"]);
    const dup = buildLearningStack(["seasonality", "seasonality", "seasonality"]);
    expect(dup.directions).toEqual(single.directions);
    expect(dup.articles.map((a) => a.article_id)).toEqual(
      single.articles.map((a) => a.article_id),
    );
  });

  it("направления в выдаче нормализованы к каноническому порядку §2.2", () => {
    const stack = buildLearningStack(["neural", "methodology_validation", "seasonality"]);
    const canonical = KNOWLEDGE_DIRECTIONS.filter((d) =>
      ["neural", "methodology_validation", "seasonality"].includes(d),
    );
    expect(stack.directions).toEqual(canonical);
  });
});

// ── 4. Термины стека — только связанные со статьями стека ───────

describe("buildLearningStack — термины стека", () => {
  it("каждый термин связан (related_article_ids) хотя бы с одной статьёй стека", () => {
    const stack = buildLearningStack(["seasonality", "missing_outliers"]);
    const stackIds = new Set(stack.articles.map((a) => a.article_id));
    expect(stack.terms.length).toBeGreaterThan(0);
    for (const term of stack.terms) {
      expect(term.related_article_ids.some((id) => stackIds.has(id))).toBe(true);
    }
  });

  it("термины в алфавитном порядке (ru), без дублей", () => {
    const stack = buildLearningStack(["methodology_validation"]);
    const sorted = [...stack.terms].sort((a, b) =>
      a.term.localeCompare(b.term, "ru"),
    );
    expect(stack.terms.map((t) => t.term_id)).toEqual(sorted.map((t) => t.term_id));
    expect(new Set(stack.terms.map((t) => t.term_id)).size).toBe(stack.terms.length);
  });

  it("у стека без статей — нет и терминов (термины «в пустоту» не выдаются)", () => {
    const stack = buildLearningStack(["volatility", "multivariate"]);
    expect(stack.articles).toEqual([]);
    expect(stack.terms).toEqual([]);
  });
});

// ── 5. Счётчики направлений — для чекбоксов билдера ─────────────

describe("getDirectionArticleCounts — честные счётчики для чекбоксов", () => {
  it("возвращает запись по всем 8 направлениям §2.2", () => {
    const counts = getDirectionArticleCounts();
    expect(Object.keys(counts).sort()).toEqual(
      [...KNOWLEDGE_DIRECTIONS].map(String).sort(),
    );
  });

  it("счётчик направления = числу опубликованных статей с этим направлением", () => {
    const counts = getDirectionArticleCounts();
    for (const direction of KNOWLEDGE_DIRECTIONS) {
      const expected = published.filter((a) => a.directions.includes(direction)).length;
      expect(counts[direction]).toBe(expected);
    }
  });

  it("направления без опубликованных статей честно получают 0", () => {
    const counts = getDirectionArticleCounts();
    for (const direction of KNOWLEDGE_DIRECTIONS) {
      if (!published.some((a) => a.directions.includes(direction))) {
        expect(counts[direction]).toBe(0);
      }
    }
    expect(counts.volatility + counts.multivariate).toBe(0);
  });

  it("сумма счётчиков ≥ числа опубликованных статей (мульти-тегирование)", () => {
    const counts = getDirectionArticleCounts();
    const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
    expect(total).toBeGreaterThanOrEqual(published.length);
  });
});

// ── 6. Словари порядка — стабильные константы §2.2/§13 ──────────

describe("STAGE_ORDER_INDEX / DIRECTION_ORDER_INDEX — канонические порядки", () => {
  it("STAGE_ORDER_INDEX следует KNOWLEDGE_STAGES (§13)", () => {
    KNOWLEDGE_STAGES.forEach((stage, i) => {
      expect(STAGE_ORDER_INDEX[stage]).toBe(i);
    });
  });

  it("DIRECTION_ORDER_INDEX следует KNOWLEDGE_DIRECTIONS (§2.2)", () => {
    KNOWLEDGE_DIRECTIONS.forEach((direction, i) => {
      expect(DIRECTION_ORDER_INDEX[direction]).toBe(i);
    });
  });

  it("у каждого направления есть человекочитаемая русская метка", () => {
    for (const direction of KNOWLEDGE_DIRECTIONS) {
      expect(DIRECTION_LABELS_RU[direction].length).toBeGreaterThan(0);
    }
  });
});

// ── 7. Связность данных: термины ссылаются на существующие статьи ─

describe("связность реестров для стеков", () => {
  it("related_article_ids терминов указывают на существующие статьи", () => {
    for (const term of GLOSSARY_TERMS) {
      for (const id of term.related_article_ids) {
        expect(published.some((a) => a.article_id === id)).toBe(true);
      }
    }
  });
});