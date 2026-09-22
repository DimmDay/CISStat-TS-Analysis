// scripts/promote_knowledge_registry.test.ts
//
// Task EDU-API-1 (Шаг 4 EDU) — ПРОМОУШЕН слоя знаний в backend без
// перенабора контента (docs/education_knowledge_base_architecture.md
// §6 Шаг 4; spec_education.md §1).
//
// Этот файл — одновременно:
//   1. ГЕНЕРАТОР артефакта: `PROMOTE_KNOWLEDGE=1 npx jest promote_knowledge_registry`
//      читает TS-реестры (единственный источник истины) и записывает
//      apps/api/knowledge/registry_data.json;
//   2. ПАРИТЕТ-СТРАЖ: обычный прогон (`npx jest promote_knowledge_registry`)
//      сверяет артефакт с TS-реестрами — расхождение (правка контента
//      без перегенерации, потеря записи, искажение текста) падает тестом.
//
// Сериализация блоков в body_md (§3 арх.док п.1): paragraph -> абзац,
// bullets -> "- ", callout -> "> ", блоки соединяются пустой строкой.
// Тот же алгоритм реализован в apps/api/knowledge/models.py
// (blocks_to_body_md); согласованность двух реализаций страхуется
// кросс-проверкой pytest на ВСЕХ реальных записях:
// tests/api/test_knowledge_api.py::TestRegistryIntegrity.
//
// ГАРД коллации: порядок статей внутри этапа на backend — кодопойнтная
// сортировка Python, на фронте — localeCompare("ru"). Для текущего
// набора заголовков результаты совпадают; гард-тест ловит расхождение
// в момент добавления заголовка, а не в проде.

import { readFileSync, writeFileSync } from "fs";
import * as path from "path";
import {
  KNOWLEDGE_ARTICLES,
} from "../packages/ui/lib/knowledge/articles";
import { GLOSSARY_TERMS } from "../packages/ui/lib/knowledge/glossary";
import { KNOWLEDGE_HELP_ENTRIES } from "../packages/ui/lib/knowledge/help";
import {
  DIRECTION_LABELS_RU,
  KNOWLEDGE_DIRECTIONS,
  KNOWLEDGE_STAGES,
  STAGE_LABELS_RU,
  type KnowledgeArticle,
  type KnowledgeBlock,
} from "../packages/ui/lib/knowledge/types";

const OUT_PATH = path.join(
  __dirname,
  "..",
  "apps",
  "api",
  "knowledge",
  "registry_data.json",
);

/** Сериализация блоков в markdown — 1:1 с blocks_to_body_md() на backend. */
function blocksToBodyMd(blocks: readonly KnowledgeBlock[]): string {
  const parts: string[] = [];
  for (const block of blocks) {
    if (block.type === "paragraph") {
      parts.push(block.text);
    } else if (block.type === "bullets") {
      parts.push(block.items.map((item) => "- " + item).join("\n"));
    } else {
      parts.push("> " + block.text);
    }
  }
  return parts.join("\n\n");
}

function buildPayload() {
  return {
    meta: {
      source:
        "packages/ui/lib/knowledge (TS-реестры — единый источник истины; промоушен без перенабора контента)",
      generator: "scripts/promote_knowledge_registry.test.ts (npx jest, PROMOTE_KNOWLEDGE=1)",
      spec: "spec_education.md §1/§2.1/§2.2; docs/education_knowledge_base_architecture.md §6 Шаг 4",
      note:
        "НЕ редактировать вручную: правки контента — в TS-реестрах, затем перегенерация",
    },
    stages: [...KNOWLEDGE_STAGES],
    directions: [...KNOWLEDGE_DIRECTIONS],
    stage_labels_ru: Object.fromEntries(
      KNOWLEDGE_STAGES.map((s) => [s, STAGE_LABELS_RU[s]]),
    ),
    direction_labels_ru: Object.fromEntries(
      KNOWLEDGE_DIRECTIONS.map((d) => [d, DIRECTION_LABELS_RU[d]]),
    ),
    articles: KNOWLEDGE_ARTICLES.map((article: KnowledgeArticle) => ({
      article_id: article.article_id,
      stage_id: article.stage_id,
      node_id: null,
      facet: "library",
      directions: [...article.directions],
      title: article.title,
      summary: article.summary,
      reading_minutes: article.reading_minutes,
      body_blocks: article.body.map((block) =>
        block.type === "bullets"
          ? { type: block.type, items: [...block.items] }
          : { type: block.type, text: block.text },
      ),
      body_md: blocksToBodyMd(article.body),
      sources: article.sources.map((s) => ({
        kind: s.kind,
        label: s.label,
        url: s.url ?? null,
      })),
      status: article.status,
      last_reviewed_at: null,
      superseded_constant: null,
    })),
    help_entries: KNOWLEDGE_HELP_ENTRIES.map((entry) => ({
      entry_id: entry.entry_id,
      stage_id: entry.stage_id,
      node_id: entry.node_id,
      facet: entry.facet,
      superseded_constant: entry.superseded_constant,
      text: entry.text,
    })),
    glossary: GLOSSARY_TERMS.map((term) => ({
      term_id: term.term_id,
      term: term.term,
      definition: term.definition,
      related_article_ids: [...term.related_article_ids],
      stage_ids: [...term.stage_ids],
    })),
  };
}

describe("Промоушен слоя знаний в backend (Шаг 4 EDU, EDU-API-1)", () => {
  const promote = process.env.PROMOTE_KNOWLEDGE === "1";

  it("registry_data.json байт-в-байт соответствует TS-реестрам", () => {
    const payload = buildPayload();
    if (promote) {
      writeFileSync(OUT_PATH, JSON.stringify(payload, null, 2) + "\n", "utf8");
    }
    const onDisk = JSON.parse(readFileSync(OUT_PATH, "utf8"));
    expect(onDisk).toEqual(payload);
  });

  it("состав реестра: 77 записей справки + 13 статей (12 published + 1 draft) + 28 терминов", () => {
    // Постановка Шага 4 называла «12 статей + 25 терминов» (состояние на
    // момент Шага 1); фактический реестр — источник истины: 13 записей
    // статей (12 published + 1 draft) и 28 терминов. Счётчики жестко
    // зафиксированы: изменение состава реестра требует сознательного
    // обновления обеих сторон промоушена.
    expect(KNOWLEDGE_HELP_ENTRIES).toHaveLength(77);
    expect(KNOWLEDGE_ARTICLES).toHaveLength(13);
    expect(
      KNOWLEDGE_ARTICLES.filter((a) => a.status === "published"),
    ).toHaveLength(12);
    expect(GLOSSARY_TERMS).toHaveLength(28);
  });

  it("гард коллации: кодопойнтный порядок заголовков внутри этапа == localeCompare('ru')", () => {
    // backend сортирует внутри этапа кодопойнтно (Python str);
    // фронт — localeCompare("ru"). Наборы должны совпадать, пока не
    // появится заголовок с ё/регистровым конфликтом на первой букве.
    const stagesOf = (s: string) => s; // этап уже в поле stage_id
    for (const stage of KNOWLEDGE_STAGES) {
      const titles = KNOWLEDGE_ARTICLES.filter(
        (a) => a.status === "published" && stagesOf(a.stage_id) === stage,
      ).map((a) => a.title);
      const codepoint = [...titles].sort();
      const ru = [...titles].sort((a, b) => a.localeCompare(b, "ru"));
      expect(codepoint).toEqual(ru);
    }
  });

  it("гард сериализации: body_md содержит абзацы, '- ' для bullets, '> ' для callout", () => {
    for (const article of KNOWLEDGE_ARTICLES) {
      const bodyMd = blocksToBodyMd(article.body);
      expect(bodyMd.length).toBeGreaterThan(0);
      for (const block of article.body) {
        if (block.type === "bullets") {
          for (const item of block.items) expect(bodyMd).toContain("- " + item);
        } else if (block.type === "callout") {
          expect(bodyMd).toContain("> " + block.text);
        } else {
          expect(bodyMd).toContain(block.text);
        }
      }
    }
  });
});
