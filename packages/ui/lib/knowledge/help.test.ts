// packages/ui/lib/knowledge/help.test.ts
//
// Task EDU-HELP-1 (Шаг 3, ревизия 2026-09-22 spec_education.md §2.1/§13,
// docs/education_knowledge_base_architecture.md §3 п.7) — инварианты реестра
// контекстной справки и адаптера describeNode(...).
//
// Постановка тимлида: миграция контента справки в единый реестр — источник
// истины; секции окна «Описание» (metrics/pipeline/module_help) рендерят
// статью по (stage_id, node_id, facet) через describeNode(...); БЕЗ
// ContextHelpButton и новых панелей на узлах — окно «Описание» остаётся
// единственной справочной поверхностью узла, дублирование исключено;
// паритет-снапшоты байт-в-байт.
//
// Ключевые контракты:
//   - паритет: текст каждой записи реестра === текст мигрированной константы
//     (help-parity.fixture.json — оракул, снятый с кода до миграции);
//   - покрытие двунаправленное: реестр покрывает РОВНО ключи фиксстуры
//     (ни одной утерянной и ни одной лишней записи);
//   - ключ (stage_id, node_id, facet) уникален, entry_id уникален;
//   - честный промах: несуществующий ключ → null (no fabricated results);
//   - superseded_constant — аудит происхождения («файл::КОНСТАНТА»);
//   - греп-инвариант: в TsAnalysis*.tsx нет методологических строковых
//     констант справки — второй источник текстов не существует по построению.

import { readFileSync } from "fs";
import { join } from "path";
import { KNOWLEDGE_STAGES } from "./types";
import { KNOWLEDGE_HELP_ENTRIES, describeNode } from "./knowledge";
import type { KnowledgeHelpEntry, KnowledgeHelpFacet } from "./types";

interface FixtureEntry {
  entry_id: string;
  stage_id: string;
  node_id: string | null;
  facet: string;
  superseded_constant: string;
  text: string;
}

const fixture: FixtureEntry[] = JSON.parse(
  readFileSync(join(__dirname, "help-parity.fixture.json"), "utf-8"),
) as FixtureEntry[];

const registryKey = (e: { stage_id: string; node_id: string | null; facet: string }) =>
  `${e.stage_id}|${e.node_id ?? "module"}|${e.facet}`;

describe("EDU-HELP-1: реестр контекстной справки — источник истины (Шаг 3)", () => {
  test("фикстура-оракул снята с кода до миграции: 77 констант пяти модулей", () => {
    expect(fixture).toHaveLength(77);
    const byStage: Record<string, number> = {};
    for (const f of fixture) byStage[f.stage_id] = (byStage[f.stage_id] ?? 0) + 1;
    expect(byStage).toEqual({
      validation: 21,
      preprocessing: 21,
      eda: 21,
      modeling: 12,
      forecasting: 2,
    });
  });

  test("паритет байт-в-байт: каждый текст реестра === текст мигрированной константы", () => {
    for (const f of fixture) {
      const entry = describeNode(
        f.stage_id as never,
        f.node_id as never,
        f.facet as never,
      );
      expect(entry).not.toBeNull();
      expect((entry as KnowledgeHelpEntry).text).toBe(f.text);
    }
  });

  test("покрытие двунаправленное: ключи реестра === ключи фиксстуры (без дублей и лишних)", () => {
    const registryKeys = KNOWLEDGE_HELP_ENTRIES.map(registryKey).sort();
    const fixtureKeys = fixture.map(registryKey).sort();
    expect(new Set(registryKeys).size).toBe(registryKeys.length);
    expect(registryKeys).toEqual(fixtureKeys);
  });

  test("ключ (stage_id, node_id, facet) уникален и entry_id уникален", () => {
    const keys = KNOWLEDGE_HELP_ENTRIES.map(registryKey);
    expect(new Set(keys).size).toBe(keys.length);
    const ids = KNOWLEDGE_HELP_ENTRIES.map((e) => e.entry_id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test("stage_id каждой записи — из словаря STAGES платформы (§1.1)", () => {
    for (const e of KNOWLEDGE_HELP_ENTRIES) {
      expect(KNOWLEDGE_STAGES).toContain(e.stage_id);
    }
  });

  test("контракт facet/node_id: metrics|pipeline — на узле; module_help — модульный (node_id=null)", () => {
    for (const e of KNOWLEDGE_HELP_ENTRIES) {
      if (e.facet === "metrics" || e.facet === "pipeline") {
        expect(e.node_id).not.toBeNull();
      }
      if (e.facet === "module_help") {
        expect(e.node_id).toBeNull();
      }
    }
  });

  test("модульная справка (module_help) есть у всех пяти реализованных этапов", () => {
    for (const stage of ["validation", "preprocessing", "eda", "modeling", "forecasting"] as const) {
      expect(describeNode(stage, null, "module_help")).not.toBeNull();
    }
  });

  test("stage_overview: Моделирование покрывает 11 стадий графа, Прогнозирование — этап целиком", () => {
    const modelingStages = KNOWLEDGE_HELP_ENTRIES.filter(
      (e) => e.stage_id === "modeling" && e.facet === "stage_overview",
    ).map((e) => e.node_id);
    expect(modelingStages).toHaveLength(11);
    expect(modelingStages).toContain("problem_definition");
    expect(describeNode("forecasting", null, "stage_overview")).not.toBeNull();
  });

  test("честный промах: несуществующий ключ → null (no fabricated results)", () => {
    expect(describeNode("validation", "nonexistent_check", "metrics")).toBeNull();
    expect(describeNode("eda", "descriptive", "module_help")).toBeNull();
    expect(describeNode("upload", "anything", "metrics" as KnowledgeHelpFacet)).toBeNull();
  });

  test("superseded_constant — аудит происхождения в формате «Файл::КОНСТАНТА»", () => {
    for (const e of KNOWLEDGE_HELP_ENTRIES) {
      expect(e.superseded_constant).toMatch(/^TsAnalysis[A-Za-z]+\.tsx::[A-Za-z_0-9.]+$/);
    }
  });

  test("греп-инвариант: в TsAnalysis*.tsx больше нет строковых констант справки (один источник — реестр)", () => {
    const componentsDir = join(__dirname, "..", "..", "components");
    const files = [
      "TsAnalysisValidation.tsx",
      "TsAnalysisPreprocessing.tsx",
      "TsAnalysisEDA.tsx",
      "TsAnalysisModeling.tsx",
      "TsAnalysisForecasting.tsx",
    ];
    const forbidden = [
      /const [A-Z_0-9]+_(METRICS_DESCRIPTION|PIPELINE_DESCRIPTION|HELP) = `/,
      /const FORECASTING_DESCRIPTION = `/,
      /const MODELING_STAGE_DESCRIPTIONS[:\s]/,
    ];
    for (const file of files) {
      const src = readFileSync(join(componentsDir, file), "utf-8");
      for (const pattern of forbidden) {
        expect(pattern.test(src)).toBe(false);
      }
    }
  });
});
